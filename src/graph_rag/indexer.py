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
from src.converters.structure_chunker import StructureChunker
from src.graph_rag.citation_parser import LegalCitationParser
from config.settings import settings

logger = logging.getLogger(__name__)

def build_law_index(law_dir: str = None, storage_dir: str = None) -> Dict[str, Any]:
    """
    Nạp các văn bản luật từ law_dir:
    1. Xây dựng đồ thị NetworkX biểu diễn cấu trúc văn bản và liên kết dẫn chiếu đa tầng
    2. Áp dụng LegalCitationParser để phân tích quan hệ pháp luật (REFERENCES, DETAILS, AMENDS, REPEALS)
    3. Áp dụng StructureChunker (Chiến lược A3) để tiêm Context Header cho các vector chunks
    4. Lưu đồ thị ra law_graph.json và vector embedding vào ChromaDB
    """
    target_law_dir = Path(law_dir) if law_dir else settings.law_dir
    target_storage_dir = Path(storage_dir) if storage_dir else settings.storage_dir
    target_storage_dir.mkdir(parents=True, exist_ok=True)
    
    G = nx.DiGraph()
    all_docs: List[ParsedDocument] = []
    
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
                all_docs.append(doc)
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
                        G.add_edge(node_id, parent_node_id, relation="PART_OF", relation_type="PART_OF")
        except Exception as e:
            logger.error(f"Lỗi khi đọc file luật {json_file}: {e}")

    # 2. Phân tích dẫn chiếu pháp luật bằng LegalCitationParser (từ test-kg-rag)
    LegalCitationParser.enrich_graph_with_citations(G, all_docs)

    # 3. Phân mảnh theo Chiến lược A3 (Structure-aware Legal Chunking with Context Header Injection)
    chunker = StructureChunker(max_tokens=384)
    legal_chunks = chunker.chunk_documents(all_docs)

    # 4. Lưu đồ thị ra law_graph.json
    try:
        graph_data = nx.node_link_data(G, edges="edges")
    except TypeError:
        graph_data = nx.node_link_data(G)
    graph_path = target_storage_dir / "law_graph.json"
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, ensure_ascii=False, indent=2)

    # 5. Nạp vào ChromaDB (nếu có) với các Chunks đã được tiêm Context Header
    if HAS_CHROMADB:
        chroma_dir = target_storage_dir / "chroma_db"
        try:
            client = chromadb.PersistentClient(path=str(chroma_dir))
            collection = client.get_or_create_collection(name="legal_articles")
            
            existing = collection.get()
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
                
            if legal_chunks:
                collection.add(
                    ids=[c.chunk_id for c in legal_chunks],
                    documents=[c.content_with_header for c in legal_chunks],
                    metadatas=[{
                        "chunk_id": c.chunk_id,
                        "node_id": f"{c.doc_id}::{c.section_id}",
                        "doc_id": c.doc_id,
                        "heading": c.heading,
                        "structural_path": c.structural_path,
                        "page_start": c.page_start,
                        "level": c.level,
                    } for c in legal_chunks]
                )
        except Exception as e:
            logger.warning(f"Lỗi khi index vào ChromaDB: {e}. Hệ thống sẽ sử dụng fallback đồ thị và từ khóa.")
    else:
        logger.info("ChromaDB chưa được cài đặt trong môi trường này, sử dụng NetworkX Graph và tra cứu từ khóa dự phòng.")

    chunk_stats = StructureChunker.compute_stats(legal_chunks)

    return {
        "total_documents": len(all_docs),
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "total_chunks": len(legal_chunks),
        "chunk_stats": chunk_stats,
        "graph_path": str(graph_path)
    }
