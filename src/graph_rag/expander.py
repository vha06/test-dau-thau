import logging
from typing import List, Dict, Any, Set, Optional, Tuple
import networkx as nx

logger = logging.getLogger(__name__)


class GraphExpander:
    """
    Module mở rộng đồ thị pháp lý tri thức (Graph Expander with Evidence Path & Hop Decay):
    - Kế thừa và cải tiến từ Legal Retrieval Lab (test-kg-rag)
    - Duyệt đồ thị tri thức đa tầng (1-hop, 2-hop) từ các nút gốc (Seed Nodes)
    - Áp dụng hệ số suy giảm (hop_decay = 0.7) và ma trận trọng số quan hệ pháp lý
    - Thưởng điểm tương đồng từ vựng (lexical overlap bonus) giữa câu truy vấn và điều luật
    - Tự động ghi lại đường đi giải trình (expansion_path) và căn cứ pháp lý (evidence_text)
    - Nối liên kết nội bộ giữa các điều luật trong kết quả (annotate_inter_node_relations)
    """

    DEFAULT_RELATION_WEIGHTS = {
        "AMENDS": 1.0,         # Sửa đổi, bổ sung
        "SUPPLEMENTS": 1.0,    # Bổ sung quy định
        "REPEALS": 1.0,        # Bãi bỏ điều khoản
        "DETAILS": 0.95,       # Nghị định/Thông tư quy định chi tiết thi hành Luật
        "REFERENCES": 0.85,    # Dẫn chiếu quy định liên quan
        "PART_OF": 0.70,       # Quan hệ cấu trúc (Khoản thuộc Điều, Điều thuộc Chương)
        "CONTAINS": 0.70,
    }

    def __init__(
        self,
        graph: nx.DiGraph,
        decay_factor: float = 0.7,
        relation_weights: Optional[Dict[str, float]] = None,
    ):
        self.graph = graph
        self.decay_factor = decay_factor
        self.relation_weights = relation_weights or self.DEFAULT_RELATION_WEIGHTS

    def expand(
        self,
        query: str,
        seed_nodes: List[Dict[str, Any]],
        max_hops: int = 1,
        seed_limit: int = 5,
        max_expanded_nodes: int = 4,
        allowed_relations: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Mở rộng từ danh sách seed_nodes qua các cạnh đồ thị tri thức:
        - seed_nodes: danh sách dict chứa ít nhất "node_id", "clause_id", "score" (hoặc mặc định 1.0)
        """
        if not seed_nodes or self.graph.number_of_nodes() == 0:
            return seed_nodes

        if allowed_relations is None:
            allowed_relations = list(self.relation_weights.keys())
        allowed_set = set(allowed_relations)

        seen_nodes: Set[str] = {s["node_id"] for s in seed_nodes if "node_id" in s}
        seeds_to_expand = seed_nodes[:seed_limit]

        query_terms = set(query.lower().split()) if query else set()
        expanded_candidates: Dict[str, Tuple[Dict[str, Any], float]] = {}

        for seed in seeds_to_expand:
            seed_id = seed.get("node_id")
            if not seed_id or not self.graph.has_node(seed_id):
                continue

            seed_score = float(seed.get("score", 1.0))
            seed_title = seed.get("clause_id", seed_id)

            # Hàng đợi BFS: (current_node, current_hop, path_history_str, current_score)
            queue: List[Tuple[str, int, str, float]] = [
                (seed_id, 0, f"Gốc: {seed_title}", seed_score)
            ]
            visited_in_path: Set[str] = {seed_id}

            while queue:
                curr_node, hop, path_str, curr_score = queue.pop(0)
                if hop >= max_hops:
                    continue

                # Thu thập cả quan hệ trỏ ra (outgoing) và trỏ vào (incoming)
                neighbors: List[Tuple[str, str, str, str]] = []  # (next_node, rel, evidence, direction)

                # Outgoing: curr_node trỏ tới neighbor
                for _, nxt, d in self.graph.out_edges(curr_node, data=True):
                    rel = d.get("relation_type") or d.get("relation", "REFERENCES")
                    evidence = d.get("evidence_text", "")
                    neighbors.append((nxt, rel, evidence, "-->"))

                # Incoming: neighbor trỏ tới curr_node
                for prev, _, d in self.graph.in_edges(curr_node, data=True):
                    rel = d.get("relation_type") or d.get("relation", "REFERENCES")
                    evidence = d.get("evidence_text", "")
                    neighbors.append((prev, rel, evidence, "<--"))

                for nxt_node, rel, evidence, direction in neighbors:
                    if rel not in allowed_set or nxt_node in visited_in_path:
                        continue

                    node_data = self.graph.nodes.get(nxt_node, {})
                    if not node_data:
                        continue

                    rel_weight = self.relation_weights.get(rel, 0.5)
                    node_content = node_data.get("content_markdown", "")
                    node_title = node_data.get("heading", nxt_node)

                    # Điểm cộng trùng khớp từ khóa (lexical overlap bonus)
                    overlap = 0.0
                    if query_terms and node_content:
                        c_terms = set(node_content.lower().split())
                        overlap = len(query_terms.intersection(c_terms)) / max(1, len(query_terms))

                    cand_score = curr_score * (self.decay_factor ** (hop + 1)) * rel_weight * (0.6 + 0.4 * overlap)
                    step_desc = f" {direction}[{rel}] {node_title}"
                    new_path = path_str + step_desc

                    if nxt_node not in seen_nodes:
                        cand_item = {
                            "node_id": nxt_node,
                            "law_name": node_data.get("file_name", "Văn bản liên quan"),
                            "clause_id": node_title,
                            "content_markdown": node_content,
                            "page_number": node_data.get("page_start", 1),
                            "relation_type": f"GRAPH_HOP_{hop+1}_{rel}",
                            "score": round(cand_score, 4),
                            "expansion_path": new_path,
                            "evidence_text": evidence or f"Mở rộng {hop+1}-hop qua quan hệ {rel}",
                        }

                        if nxt_node not in expanded_candidates or cand_score > expanded_candidates[nxt_node][1]:
                            expanded_candidates[nxt_node] = (cand_item, cand_score)

                    visited_in_path.add(nxt_node)
                    queue.append((nxt_node, hop + 1, new_path, cand_score))

        # Sắp xếp các node mở rộng theo điểm giảm dần và lấy top
        sorted_expanded = sorted(expanded_candidates.values(), key=lambda x: x[1], reverse=True)
        top_expanded = [item[0] for item in sorted_expanded[:max_expanded_nodes]]

        # Hợp nhất danh sách seed và expanded
        combined = list(seed_nodes) + top_expanded

        # Bổ sung ghi chú liên kết giữa các điều luật trong tập kết quả
        self.annotate_inter_node_relations(combined, allowed_relations=allowed_relations)

        return combined

    def annotate_inter_node_relations(
        self,
        results: List[Dict[str, Any]],
        allowed_relations: Optional[List[str]] = None,
    ):
        """
        Quét và bổ sung các quan hệ giữa bất kỳ cặp node nào trong kết quả tra cứu,
        giúp tạo bản đồ giải trình pháp lý toàn diện và minh bạch.
        """
        if not results or self.graph.number_of_nodes() == 0:
            return

        allowed_set = set(allowed_relations) if allowed_relations else set(self.relation_weights.keys())
        node_map = {r.get("node_id"): r for r in results if "node_id" in r}

        for r in results:
            u = r.get("node_id")
            if not u or not self.graph.has_node(u):
                continue

            for _, v, d in self.graph.out_edges(u, data=True):
                rel = d.get("relation_type") or d.get("relation", "")
                if rel in allowed_set and v in node_map and v != u:
                    target_r = node_map[v]
                    evidence = d.get("evidence_text", "")
                    target_title = target_r.get("clause_id", v)

                    out_note = f"Dẫn chiếu [{rel}] tới {target_title}"
                    existing_path = r.get("expansion_path", "")
                    if not existing_path:
                        r["expansion_path"] = out_note
                        if evidence and not r.get("evidence_text"):
                            r["evidence_text"] = evidence
                    elif out_note not in existing_path:
                        r["expansion_path"] = f"{existing_path}; {out_note}"
