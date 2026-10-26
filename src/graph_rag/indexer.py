import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List
import networkx as nx

try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    chromadb = None
    HAS_CHROMADB = False

from src.schemas.document import ParsedDocument
from config.settings import settings

logger = logging.getLogger(__name__)

def build_law_index(law_dir: str = None, storage_dir: str = None) -> Dict[str, Any]:
    """
    Nạp các văn bản luật từ law_dir:
    1. Xây dựng đồ thị NetworkX biểu diễn liên kết tham chiếu (REFERENCES)
    2. Lưu đồ thị ra law_graph.json
    3. Lưu vector embedding của các điều khoản vào ChromaDB
    """
    target_law_dir = Path(law_dir) if law_dir else settings.law_dir
    target_storage_dir = Path(storage_dir) if storage_dir else settings.storage_dir
    target_storage_dir.mkdir(parents=True, exist_ok=True)
    
    G = nx.DiGraph()
    sections_for_vector = []
    
    # 1. Đọc tất cả các file JSON văn bản luật
    json_files = list(target_law_dir.glob("*.json"))
    if not json_files:
        logger.warning(f"Không tìm thấy file JSON nào trong {target_law_dir}")
        return {"total_documents": 0, "total_nodes": 0, "total_edges": 0}
        
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            docs: List[ParsedDocument] = []
            if isinstance(data, list):
                docs = [ParsedDocument.model_validate(d) for d in data]
            else:
                docs = [ParsedDocument.model_validate(data)]
                
            for doc in docs:
                for sec in doc.sections:
                    node_id = f"{doc.doc_id}::{sec.section_id}"
                    G.add_node(
                        node_id,
                        doc_id=doc.doc_id,
                        file_name=doc.file_name,
                        section_id=sec.section_id,
                        heading=sec.heading,
                        page_start=sec.page_start,
                        page_end=sec.page_end,
                        content_markdown=sec.content_markdown
                    )
                    
                    if sec.parent_id:
                        parent_node_id = f"{doc.doc_id}::{sec.parent_id}"
                        G.add_edge(node_id, parent_node_id, relation="PART_OF")
                        
                    sections_for_vector.append({
                        "node_id": node_id,
                        "doc_id": doc.doc_id,
                        "heading": sec.heading,
                        "page_start": sec.page_start,
                        "content": f"{sec.heading}\n{sec.content_markdown}"
                    })
        except Exception as e:
            logger.error(f"Lỗi khi đọc file luật {json_file}: {e}")

    # 2. Phân tích tham chiếu chéo (REFERENCES) bằng Regex
    # Ví dụ: "theo quy định tại Điều 14", "Điều 19", "Khoản 2"
    ref_pattern = re.compile(r"(?:Điều|Khoản|Mục)\s+(\d+[a-zA-Z0-9\.]*)", re.IGNORECASE)
    
    node_lookup: Dict[str, str] = {}
    for node_id, attrs in G.nodes(data=True):
        heading = attrs.get("heading", "")
        sec_id = attrs.get("section_id", "")
        # Map số điều khoản (ví dụ "14") tới node_id
        numbers = ref_pattern.findall(heading) + ref_pattern.findall(sec_id)
        for num in numbers:
            node_lookup[num] = node_id
            
    for node_id, attrs in G.nodes(data=True):
        content = attrs.get("content_markdown", "")
        found_refs = ref_pattern.findall(content)
        for ref_num in found_refs:
            if ref_num in node_lookup and node_lookup[ref_num] != node_id:
                target_node = node_lookup[ref_num]
                G.add_edge(node_id, target_node, relation="REFERENCES")

    # 3. Lưu đồ thị ra law_graph.json
    try:
        graph_data = nx.node_link_data(G, edges="edges")
    except TypeError:
        graph_data = nx.node_link_data(G)
    graph_path = target_storage_dir / "law_graph.json"
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, ensure_ascii=False, indent=2)

    # 4. Nạp vào ChromaDB (nếu đã cài đặt thư viện)
    if HAS_CHROMADB:
        chroma_dir = target_storage_dir / "chroma_db"
        try:
            client = chromadb.PersistentClient(path=str(chroma_dir))
            collection = client.get_or_create_collection(name="legal_articles")
            
            # Xóa các vector cũ nếu có để tránh trùng lặp
            existing = collection.get()
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
                
            if sections_for_vector:
                collection.add(
                    ids=[item["node_id"] for item in sections_for_vector],
                    documents=[item["content"] for item in sections_for_vector],
                    metadatas=[{
                        "node_id": item["node_id"],
                        "doc_id": item["doc_id"],
                        "heading": item["heading"],
                        "page_start": item["page_start"]
                    } for item in sections_for_vector]
                )
        except Exception as e:
            logger.warning(f"Lỗi khi index vào ChromaDB: {e}. Hệ thống sẽ sử dụng fallback đồ thị và từ khóa.")
    else:
        logger.info("ChromaDB chưa được cài đặt trong môi trường này, sử dụng NetworkX Graph và tra cứu từ khóa dự phòng.")

    return {
        "total_documents": len(json_files),
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "graph_path": str(graph_path)
    }
