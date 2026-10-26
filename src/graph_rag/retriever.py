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

logger = logging.getLogger(__name__)

def retrieve_legal_context(
    query: str,
    top_k: int = 3,
    hop_depth: int = 1,
    storage_dir: str = None
) -> List[Dict[str, Any]]:
    """
    Truy xuất lai:
    1. Vector Search trên ChromaDB lấy Top-K điều khoản liên quan
    2. Duyệt đồ thị NetworkX theo các cạnh REFERENCES (1-hop) để lấy thêm điều khoản liên quan
    3. Hợp nhất kết quả và trả về danh sách có trích dẫn chi tiết
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
    
    matched_node_ids: List[str] = []
    
    # 1. Thử truy vấn qua ChromaDB (nếu có thư viện)
    if HAS_CHROMADB:
        try:
            client = chromadb.PersistentClient(path=str(chroma_dir))
            collection = client.get_collection(name="legal_articles")
            results = collection.query(query_texts=[query], n_results=min(top_k, max(1, G.number_of_nodes())))
            if results and results["ids"] and results["ids"][0]:
                matched_node_ids = results["ids"][0]
        except Exception as e:
            logger.info(f"Vector search qua ChromaDB không khả dụng ({e}), sử dụng từ khóa dự phòng.")
        
    # Fallback tìm kiếm từ khóa nếu Vector search chưa tìm thấy
    if not matched_node_ids:
        query_words = set(query.lower().split())
        scored_nodes = []
        for n, attrs in G.nodes(data=True):
            text = (attrs.get("heading", "") + " " + attrs.get("content_markdown", "")).lower()
            score = sum(1 for word in query_words if word in text)
            if score > 0:
                scored_nodes.append((score, n))
        scored_nodes.sort(reverse=True)
        matched_node_ids = [n for _, n in scored_nodes[:top_k]]
        
    if not matched_node_ids and G.number_of_nodes() > 0:
        matched_node_ids = list(G.nodes())[:top_k]

    # 2. Graph Traversal: Duyệt 1-2 hop theo cạnh REFERENCES
    direct_nodes: Set[str] = set(matched_node_ids)
    hop_nodes: Set[str] = set()
    
    for node_id in direct_nodes:
        if not G.has_node(node_id):
            continue
        # Đi theo cạnh ra (node dẫn chiếu tới ai)
        for _, target, data in G.out_edges(node_id, data=True):
            if data.get("relation") == "REFERENCES" and target not in direct_nodes:
                hop_nodes.add(target)
        # Đi theo cạnh vào (ai dẫn chiếu tới node)
        for source, _, data in G.in_edges(node_id, data=True):
            if data.get("relation") == "REFERENCES" and source not in direct_nodes:
                hop_nodes.add(source)

    # 3. Tổng hợp kết quả
    output = []
    
    for n in direct_nodes:
        if G.has_node(n):
            attrs = G.nodes[n]
            output.append({
                "node_id": n,
                "law_name": attrs.get("file_name", "Luật liên quan"),
                "clause_id": attrs.get("heading", n),
                "content_markdown": attrs.get("content_markdown", ""),
                "page_number": attrs.get("page_start", 1),
                "relation_type": "DIRECT_MATCH"
            })
            
    for n in hop_nodes:
        if G.has_node(n):
            attrs = G.nodes[n]
            output.append({
                "node_id": n,
                "law_name": attrs.get("file_name", "Luật liên quan"),
                "clause_id": attrs.get("heading", n),
                "content_markdown": attrs.get("content_markdown", ""),
                "page_number": attrs.get("page_start", 1),
                "relation_type": "GRAPH_HOP"
            })
            
    return output

def format_legal_context_str(context_items: List[Dict[str, Any]]) -> str:
    """Định dạng danh sách căn cứ pháp lý thành chuỗi Markdown cho Prompt LLM."""
    if not context_items:
        return "Không tìm thấy điều khoản luật liên quan trực tiếp."
        
    formatted = []
    for idx, item in enumerate(context_items, 1):
        rel_label = "[Khớp trực tiếp]" if item.get("relation_type") == "DIRECT_MATCH" else "[Dẫn chiếu liên quan qua đồ thị]"
        formatted.append(
            f"### {idx}. {item.get('clause_id')} {rel_label}\n"
            f"- Nguồn: {item.get('law_name')} (Trang {item.get('page_number')})\n"
            f"- Nội dung quy định:\n{item.get('content_markdown')}\n"
        )
    return "\n".join(formatted)
