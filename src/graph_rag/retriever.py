import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Set
import networkx as nx

try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    chromadb = None
    HAS_CHROMADB = False

from config.settings import settings
from src.graph_rag.expander import GraphExpander

logger = logging.getLogger(__name__)

def retrieve_legal_context(
    query: str,
    top_k: int = 3,
    hop_depth: int = 1,
    storage_dir: str = None
) -> List[Dict[str, Any]]:
    """
    Truy xuất lai (Hybrid GraphRAG Retriever):
    1. Vector Search trên ChromaDB hoặc Keyword Overlap để tìm Seed Nodes
    2. Áp dụng GraphExpander (kế thừa từ test-kg-rag) để mở rộng n-hop có tính hệ số suy giảm (hop_decay)
    3. Tự động lưu vết đường đi giải trình (expansion_path) và căn cứ pháp lý (evidence_text)
    4. Trả về danh sách điều luật có cấu trúc phục vụ Deterministic Engine & LLM Gateway
    """
    target_storage_dir = Path(storage_dir) if storage_dir else settings.storage_dir
    graph_path = target_storage_dir / "law_graph.json"
    chroma_dir = target_storage_dir / "chroma_db"
    
    if not graph_path.exists():
        logger.warning(f"Chưa tìm thấy {graph_path}. Tiến hành tạo index tự động...")
        from .indexer import build_law_index
        build_law_index(storage_dir=str(target_storage_dir))
        
    # Nạp đồ thị
    with open(graph_path, "r", encoding="utf-8") as f:
        graph_data = json.load(f)
    edges_key = "edges" if "edges" in graph_data else "links"
    try:
        G = nx.node_link_graph(graph_data, edges=edges_key)
    except TypeError:
        G = nx.node_link_graph(graph_data)
    
    seed_nodes: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    
    # 1. Thử truy vấn qua ChromaDB (Vector Search)
    if HAS_CHROMADB:
        try:
            client = chromadb.PersistentClient(path=str(chroma_dir))
            collection = client.get_collection(name="legal_articles")
            results = collection.query(
                query_texts=[query],
                n_results=min(top_k * 2, max(1, G.number_of_nodes())),
                include=["metadatas", "documents", "distances"]
            )
            if results and results["ids"] and results["ids"][0]:
                for idx, item_id in enumerate(results["ids"][0]):
                    meta = results["metadatas"][0][idx] if results.get("metadatas") else {}
                    node_id = meta.get("node_id", item_id)
                    dist = results["distances"][0][idx] if results.get("distances") else 0.5
                    score = round(max(0.1, 1.0 - dist), 4)

                    if node_id in G.nodes and node_id not in seen_ids:
                        seen_ids.add(node_id)
                        attrs = G.nodes[node_id]
                        seed_nodes.append({
                            "node_id": node_id,
                            "law_name": attrs.get("file_name", "Luật liên quan"),
                            "clause_id": attrs.get("heading", node_id),
                            "content_markdown": attrs.get("content_markdown", ""),
                            "page_number": attrs.get("page_start", 1),
                            "relation_type": "DIRECT_MATCH",
                            "score": score,
                            "expansion_path": f"Gốc: {attrs.get('heading', node_id)}",
                            "evidence_text": "Khớp ngữ nghĩa Vector Search"
                        })
                        if len(seed_nodes) >= top_k:
                            break
        except Exception as e:
            logger.info(f"Vector search qua ChromaDB không khả dụng ({e}), chuyển sang tìm kiếm từ khóa dự phòng.")
        
    # 2. Fallback tìm kiếm từ khóa nếu Vector search chưa tìm thấy hoặc không có ChromaDB
    if not seed_nodes:
        query_words = set(query.lower().split())
        scored_nodes = []
        for n, attrs in G.nodes(data=True):
            text = (attrs.get("heading", "") + " " + attrs.get("content_markdown", "")).lower()
            score = sum(1 for word in query_words if word in text)
            if score > 0:
                scored_nodes.append((score, n))
        scored_nodes.sort(reverse=True)
        
        for score, n in scored_nodes[:top_k]:
            attrs = G.nodes[n]
            seed_nodes.append({
                "node_id": n,
                "law_name": attrs.get("file_name", "Luật liên quan"),
                "clause_id": attrs.get("heading", n),
                "content_markdown": attrs.get("content_markdown", ""),
                "page_number": attrs.get("page_start", 1),
                "relation_type": "DIRECT_MATCH",
                "score": float(score),
                "expansion_path": f"Gốc: {attrs.get('heading', n)}",
                "evidence_text": f"Khớp {score} từ khóa truy vấn"
            })
            seen_ids.add(n)
        
    # 3. Fallback tối hậu: Lấy các nodes đầu tiên nếu đồ thị có node
    if not seed_nodes and G.number_of_nodes() > 0:
        for n in list(G.nodes())[:top_k]:
            attrs = G.nodes[n]
            seed_nodes.append({
                "node_id": n,
                "law_name": attrs.get("file_name", "Luật liên quan"),
                "clause_id": attrs.get("heading", n),
                "content_markdown": attrs.get("content_markdown", ""),
                "page_number": attrs.get("page_start", 1),
                "relation_type": "DIRECT_MATCH",
                "score": 0.5,
                "expansion_path": f"Gốc: {attrs.get('heading', n)}",
                "evidence_text": "Chọn mặc định từ đồ thị"
            })

    # 4. Áp dụng GraphExpander (từ test-kg-rag) mở rộng đa tầng có hệ số suy giảm hop_decay
    expander = GraphExpander(graph=G, decay_factor=0.7)
    final_results = expander.expand(
        query=query,
        seed_nodes=seed_nodes,
        max_hops=hop_depth,
        seed_limit=top_k,
        max_expanded_nodes=4
    )

    return final_results

def format_legal_context_str(context_items: List[Dict[str, Any]]) -> str:
    """Định dạng danh sách căn cứ pháp lý thành chuỗi Markdown cho Prompt LLM."""
    if not context_items:
        return "Không tìm thấy điều khoản luật liên quan trực tiếp."
        
    formatted = []
    for idx, item in enumerate(context_items, 1):
        rel_type = item.get("relation_type", "DIRECT_MATCH")
        rel_label = "[Khớp trực tiếp]" if rel_type == "DIRECT_MATCH" else f"[Dẫn chiếu qua đồ thị: {rel_type}]"
        
        path_info = f"- Đường đi pháp lý: {item.get('expansion_path')}\n" if item.get('expansion_path') else ""
        evidence_info = f"- Căn cứ: {item.get('evidence_text')}\n" if item.get('evidence_text') else ""

        formatted.append(
            f"### {idx}. {item.get('clause_id')} {rel_label}\n"
            f"- Nguồn: {item.get('law_name')} (Trang {item.get('page_number')})\n"
            f"{path_info}"
            f"{evidence_info}"
            f"- Nội dung quy định:\n{item.get('content_markdown')}\n"
        )
    return "\n".join(formatted)
