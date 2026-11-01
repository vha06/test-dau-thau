import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List, Set
import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from config.settings import settings

logger = logging.getLogger(__name__)

# Bảng mã màu chuẩn nhận diện các loại quan hệ pháp luật (kế thừa từ test-kg-rag)
RELATION_COLORS = {
    "AMENDS": "#ef4444",       # Đỏ: Sửa đổi, bổ sung
    "SUPPLEMENTS": "#f97316",  # Cam: Bổ sung quy định
    "REPEALS": "#dc2626",      # Đỏ đậm: Bãi bỏ quy định
    "DETAILS": "#38bdf8",      # Xanh lơ: Hướng dẫn chi tiết thi hành Luật
    "REFERENCES": "#a855f7",   # Tím: Dẫn chiếu pháp lý
    "PART_OF": "#64748b",      # Xám: Cấu trúc phân cấp (Khoản thuộc Điều, Điều thuộc Chương)
    "CONTAINS": "#64748b",     # Xám: Cấu trúc chứa đựng
}

COLOR_PALETTE = [
    "#2563eb",  # Blue
    "#059669",  # Green
    "#d97706",  # Amber
    "#7c3aed",  # Purple
    "#0891b2",  # Cyan
    "#e11d48",  # Rose
]


def load_networkx_graph(graph_path: Optional[Path] = None) -> nx.DiGraph:
    """Nạp đồ thị NetworkX DiGraph từ file law_graph.json."""
    target_path = graph_path if graph_path else (settings.storage_dir / "law_graph.json")
    if not target_path.exists():
        return nx.DiGraph()
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        edges_key = "edges" if "edges" in data else "links"
        try:
            return nx.node_link_graph(data, directed=True, edges=edges_key)
        except TypeError:
            return nx.node_link_graph(data, directed=True)
    except Exception as e:
        logger.error(f"Lỗi khi đọc file đồ thị {target_path}: {e}")
        return nx.DiGraph()


def build_pyvis_html(
    graph: nx.DiGraph,
    center_node_id: Optional[str] = None,
    show_all_nodes: bool = True,
    highlight_node_ids: Optional[List[str]] = None,
    max_hops: int = 1,
    allowed_relations: Optional[List[str]] = None,
    height: str = "580px",
    width: str = "100%",
    physics: bool = True,
    **kwargs,
) -> str:
    """
    Tạo mã HTML đồ thị tương tác mạng lưới tri thức bằng PyVis (vis.js).
    Chuẩn hóa giao diện theo phong cách Dark Mode chuyên nghiệp của Legal Retrieval Lab (test-kg-rag):
    - Mặc định: Hiển thị TẤT CẢ các Node và Cạnh quan hệ trong cùng 1 không gian đồ thị toàn cảnh.
    - Khi chọn 1 node trung tâm (center_node_id): Nổi bật (Spotlight) node đó và các liên kết n-hop của nó,
      đồng thời vẫn giữ các node khác trong cùng không gian để quan sát toàn cảnh.
    - Màu sắc phân loại sắc nét cho các loại quan hệ (REFERENCES, DETAILS, AMENDS, REPEALS, PART_OF).
    - Mô phỏng lực học Barnes-Hut cho độ bung tỏa tự nhiên, kéo thả mượt mà, có nút điều hướng Zoom/Pan.
    """
    from pyvis.network import Network

    if graph.number_of_nodes() == 0:
        return (
            "<div style='text-align:center; padding: 40px; color: #94a3b8; background: #0e1117; font-family: sans-serif; border-radius: 8px;'>"
            "Chưa có dữ liệu đồ thị tri thức. Vui lòng bấm 'Dựng / Cập nhật Đồ thị Tri thức' để khởi tạo.</div>"
        )

    allowed_rels = set(allowed_relations) if allowed_relations else set(RELATION_COLORS.keys())

    # 1. Xác định tập hợp các nodes và tính toán cụm láng giềng liên quan
    connected_neighbors: Set[str] = set()
    direct_edges_to_center: Set[Tuple[str, str]] = set()

    if center_node_id and graph.has_node(center_node_id):
        current_frontier = {center_node_id}
        for _ in range(max_hops):
            next_frontier = set()
            for n in current_frontier:
                # Outgoing edges
                for _, tgt, d in graph.out_edges(n, data=True):
                    rel = d.get("relation_type") or d.get("relation", "")
                    if rel in allowed_rels:
                        next_frontier.add(tgt)
                        direct_edges_to_center.add((n, tgt))
                # Incoming edges
                for src, _, d in graph.in_edges(n, data=True):
                    rel = d.get("relation_type") or d.get("relation", "")
                    if rel in allowed_rels:
                        next_frontier.add(src)
                        direct_edges_to_center.add((src, n))
            connected_neighbors.update(next_frontier)
            current_frontier = next_frontier

    if show_all_nodes:
        # Hiển thị TẤT CẢ các nodes trong cùng 1 không gian đồ thị
        sub_nodes = set(graph.nodes())
    else:
        # Chế độ thu hẹp (Focus Subgraph): chỉ hiện node chọn và láng giềng
        sub_nodes = set()
        if highlight_node_ids:
            sub_nodes.update([nid for nid in highlight_node_ids if graph.has_node(nid)])
        if center_node_id and graph.has_node(center_node_id):
            sub_nodes.add(center_node_id)
            sub_nodes.update(connected_neighbors)
        if not sub_nodes:
            sub_nodes = set(graph.nodes())

    # 2. Khởi tạo mạng lưới PyVis với nền tối (Dark Theme) chuẩn test-kg-rag
    net = Network(
        height=height,
        width=width,
        bgcolor="#0e1117",
        font_color="#ffffff",
        directed=True,
        cdn_resources="remote",
    )

    if physics:
        # Cấu hình lực học Barnes-Hut tối ưu để tất cả nodes phân tán đều đẹp mắt, không rối
        net.barnes_hut(
            gravity=-2800,
            central_gravity=0.25,
            spring_length=135,
            spring_strength=0.04,
            damping=0.92,
        )
    else:
        net.toggle_physics(False)

    # 3. Thêm các Node vào đồ thị
    for node_id in sub_nodes:
        if not graph.has_node(node_id):
            continue
        ndata = graph.nodes[node_id]
        raw_heading = ndata.get("heading") or node_id
        file_name = ndata.get("file_name", "")
        doc_id = ndata.get("doc_id", "")
        page_start = ndata.get("page_start", 1)

        # Cắt ngắn nhãn để hiển thị gọn gàng trên đồ thị
        label = raw_heading if len(raw_heading) <= 24 else raw_heading[:21] + "..."

        # Tooltip HTML đa dòng sắc nét
        content_snippet = ndata.get("content_markdown", "")[:260]
        if len(ndata.get("content_markdown", "")) > 260:
            content_snippet += "..."
        content_snippet_html = content_snippet.replace("\n", "<br/>")

        tooltip_lines = [
            f"<div style='font-family: sans-serif; font-size: 13px;'>",
            f"<b style='color: #38bdf8;'>{raw_heading}</b><br/>",
            f"<i>Văn bản: {file_name or doc_id} (Trang {page_start})</i>",
            f"<hr style='border: none; border-top: 1px solid #475569; margin: 6px 0;'/>",
            f"<div style='color: #cbd5e1; font-size: 12px; line-height: 1.4;'>{content_snippet_html}</div>",
            f"</div>"
        ]
        tooltip = "".join(tooltip_lines)

        # Định dạng màu sắc và hình dạng node theo vai trò
        shape = "dot"
        if node_id == center_node_id:
            color = "#f59e0b"  # Vàng hổ phách (Amber gold) cho node được chọn làm tâm điểm
            size = 35
            border_width = 4
        elif node_id in connected_neighbors:
            color = "#10b981"  # Xanh ngọc lục bảo (Emerald green) cho các láng giềng liên kết trực tiếp
            size = 26
            border_width = 3
        elif highlight_node_ids and node_id in highlight_node_ids:
            color = "#10b981"
            size = 25
            border_width = 3
        elif "CHƯƠNG" in raw_heading.upper() or "CHUONG" in node_id.upper():
            color = "#3b82f6"  # Xanh dương hoàng gia cho cấp Chương/Văn bản
            size = 24
            shape = "diamond"
            border_width = 2
        elif "sửa đổi" in raw_heading.lower() or "bổ sung" in raw_heading.lower():
            color = "#ef4444"  # Đỏ cho điều khoản sửa đổi
            size = 22
            shape = "triangle"
            border_width = 2
        else:
            # Nếu đang chọn 1 node cụ thể, các node ngoài cụm có thể hơi trầm hơn một chút
            if center_node_id:
                color = "#7c3aed"  # Tím thanh lịch
                size = 18
                border_width = 1.5
            else:
                deg = graph.degree(node_id)
                color = "#a855f7"  # Tím sáng
                size = 18 + min(deg * 2, 12)
                border_width = 2

        net.add_node(
            node_id,
            label=label,
            title=tooltip,
            color={
                "background": color,
                "border": "#ffffff",
                "highlight": {"background": "#fbbf24", "border": "#ffffff"}
            },
            size=size,
            shape=shape,
            borderWidth=border_width,
            font={"size": 13, "color": "#ffffff", "face": "Segoe UI, sans-serif"},
        )

    # 4. Thêm các Cạnh (Edges) giữa các nodes được hiển thị
    edge_counts: Dict[Tuple[str, str], int] = {}
    for src in sub_nodes:
        for _, tgt, d in graph.out_edges(src, data=True):
            if tgt not in sub_nodes:
                continue
            rel = d.get("relation_type") or d.get("relation", "REFERENCES")
            if rel not in allowed_rels:
                continue

            edge_key = (src, tgt)
            edge_counts[edge_key] = edge_counts.get(edge_key, 0) + 1
            idx = edge_counts[edge_key]

            is_connected_to_center = (src == center_node_id or tgt == center_node_id or edge_key in direct_edges_to_center)

            color = RELATION_COLORS.get(rel, "#94a3b8")
            evidence = d.get("evidence_text") or ""
            edge_tooltip = (
                f"<div style='font-family: sans-serif; font-size: 12px; color: #f1f5f9;'>"
                f"<b>Quan hệ:</b> <span style='color: {color}; font-weight: bold;'>{rel}</span><br/>"
                f"<b>Căn cứ pháp lý:</b> <i>{evidence or 'Dẫn chiếu trong văn bản'}</i>"
                f"</div>"
            )

            # Độ dày và nổi bật của cạnh
            if center_node_id:
                if is_connected_to_center:
                    edge_width = 3.5
                    edge_color = {"color": color, "highlight": "#ffffff"}
                else:
                    edge_width = 1.2
                    edge_color = {"color": f"{color}66", "highlight": "#ffffff"}  # Mờ nhẹ 40% để nổi bật cạnh trọng tâm
            else:
                edge_width = 2.0
                edge_color = {"color": color, "highlight": "#ffffff"}

            # Tạo độ cong nhẹ để các cạnh song song không bị đè lên nhau
            smooth_opt = {"type": "curvedCW", "roundness": 0.15 * idx}

            net.add_edge(
                src,
                tgt,
                label=rel,
                title=edge_tooltip,
                color=edge_color,
                arrows="to",
                width=edge_width,
                font={
                    "size": 10,
                    "color": color,
                    "align": "middle",
                    "strokeWidth": 2,
                    "strokeColor": "#0e1117"
                },
                smooth=smooth_opt,
            )

    # Tích hợp thêm các nút điều khiển Zoom và Pan tương tác của vis.js
    net.set_options("""
    {
      "interaction": {
        "hover": true,
        "navigationButtons": true,
        "keyboard": true,
        "zoomView": true
      }
    }
    """)

    return net.generate_html()


def generate_pyvis_html(
    graph_path: Optional[Path] = None,
    filter_relation: Optional[str] = None,
    height: str = "540px",
    **kwargs
) -> str:
    """Hàm tương thích ngược gọi trực tiếp sang build_pyvis_html."""
    G = load_networkx_graph(graph_path)
    allowed_rels = [filter_relation] if filter_relation else list(RELATION_COLORS.keys())
    return build_pyvis_html(
        graph=G,
        allowed_relations=allowed_rels,
        height=height,
        **kwargs
    )


def get_graph_edges_data(
    graph: Optional[nx.DiGraph] = None,
    allowed_relations: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Trích xuất danh sách các quan hệ pháp lý dạng bảng chi tiết."""
    G = graph if graph is not None else load_networkx_graph()
    if G.number_of_nodes() == 0:
        return []

    allowed_set = set(allowed_relations) if allowed_relations else set(RELATION_COLORS.keys())
    edge_records: List[Dict[str, Any]] = []

    for u, v, d in G.edges(data=True):
        rel = d.get("relation_type") or d.get("relation", "REFERENCES")
        if rel in allowed_set:
            src_node = G.nodes.get(u, {})
            tgt_node = G.nodes.get(v, {})
            edge_records.append({
                "Điều khoản nguồn (Source)": src_node.get("heading", u),
                "Loại quan hệ (Relation)": rel,
                "Điều khoản đích (Target)": tgt_node.get("heading", v),
                "Căn cứ trích dẫn (Evidence)": d.get("evidence_text", ""),
                "Phương thức phát hiện": d.get("detection_method", "LEGAL_PARSER"),
            })

    return edge_records


def generate_matplotlib_fig(
    graph_path: Optional[Path] = None,
    filter_isolated: bool = True,
    max_nodes: int = 50
) -> Optional[plt.Figure]:
    """Vẽ hình ảnh đồ thị tĩnh chất lượng cao bằng NetworkX + Matplotlib."""
    G = load_networkx_graph(graph_path)
    if G.number_of_nodes() == 0:
        return None

    if filter_isolated:
        connected = [n for n in G.nodes if G.degree(n) > 0]
        if connected:
            G = G.subgraph(connected).copy()

    if G.number_of_nodes() > max_nodes:
        sorted_nodes = sorted(G.nodes, key=lambda n: G.degree(n), reverse=True)[:max_nodes]
        G = G.subgraph(sorted_nodes).copy()

    plt.rcParams["font.sans-serif"] = ["Segoe UI", "Arial", "DejaVu Sans", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(11, 6.5), facecolor="#0e1117")
    ax.set_facecolor("#0e1117")

    try:
        pos = nx.spring_layout(G, k=0.85, seed=42, iterations=80)
    except Exception:
        pos = nx.random_layout(G)

    # Phân loại màu sắc theo loại quan hệ và tài liệu
    node_colors = []
    for n in G.nodes:
        h = G.nodes[n].get("heading", "")
        if "sửa đổi" in h.lower() or "bổ sung" in h.lower():
            node_colors.append("#ef4444")
        elif "CHƯƠNG" in h.upper():
            node_colors.append("#3b82f6")
        else:
            node_colors.append("#a855f7")

    node_sizes = [180 + min(G.degree(n) * 70, 750) for n in G.nodes]

    # Vẽ các cạnh PART_OF (xám mờ)
    part_of_edges = [(u, v) for u, v, d in G.edges(data=True) if (d.get("relation_type") or d.get("relation")) == "PART_OF"]
    if part_of_edges:
        nx.draw_networkx_edges(
            G, pos, edgelist=part_of_edges, ax=ax,
            edge_color="#475569", width=1.0, arrows=True,
            arrowsize=9, style="dotted", connectionstyle="arc3,rad=0.08"
        )

    # Vẽ các cạnh REFERENCES (tím)
    ref_edges = [(u, v) for u, v, d in G.edges(data=True) if (d.get("relation_type") or d.get("relation")) == "REFERENCES"]
    if ref_edges:
        nx.draw_networkx_edges(
            G, pos, edgelist=ref_edges, ax=ax,
            edge_color="#a855f7", width=1.8, arrows=True,
            arrowsize=13, connectionstyle="arc3,rad=0.15"
        )

    # Vẽ các cạnh DETAILS (xanh lơ)
    details_edges = [(u, v) for u, v, d in G.edges(data=True) if (d.get("relation_type") or d.get("relation")) == "DETAILS"]
    if details_edges:
        nx.draw_networkx_edges(
            G, pos, edgelist=details_edges, ax=ax,
            edge_color="#38bdf8", width=2.0, arrows=True,
            arrowsize=14, connectionstyle="arc3,rad=0.15"
        )

    # Vẽ nodes
    nx.draw_networkx_nodes(
        G, pos, ax=ax, node_color=node_colors, node_size=node_sizes,
        edgecolors="#ffffff", linewidths=1.5
    )

    labels = {}
    for n in G.nodes:
        sec_id = G.nodes[n].get("section_id", "")
        heading = G.nodes[n].get("heading", "")
        short_label = sec_id.replace("DIEU_", "Đ.").replace("CHUONG_", "Ch.").replace("_", "") if sec_id else heading[:8]
        labels[n] = short_label

    nx.draw_networkx_labels(
        G, pos, labels=labels, ax=ax,
        font_size=8, font_family="Segoe UI", font_weight="bold", font_color="#ffffff"
    )

    legend_handles = [
        mpatches.Patch(color="#3b82f6", label="Chương / Văn bản cha"),
        mpatches.Patch(color="#a855f7", label="Điều khoản luật"),
        mpatches.Patch(color="#ef4444", label="Điều khoản sửa đổi/bổ sung"),
        plt.Line2D([0], [0], color="#a855f7", lw=2, label="Dẫn chiếu (REFERENCES)"),
        plt.Line2D([0], [0], color="#38bdf8", lw=2, label="Hướng dẫn thi hành (DETAILS)"),
        plt.Line2D([0], [0], color="#475569", lw=1.2, ls=":", label="Phân cấp (PART_OF)"),
    ]

    ax.legend(
        handles=legend_handles, loc="upper right",
        frameon=True, facecolor="#1e293b", edgecolor="#334155", labelcolor="#ffffff", fontsize=8
    )

    ax.set_title("SƠ ĐỒ MẠNG LƯỚI ĐỒ THỊ TRI THỨC PHÁP LUẬT ĐẤU THẦU (GraphRAG)", fontsize=11, fontweight="bold", color="#38bdf8", pad=12)
    ax.axis("off")
    plt.tight_layout()
    return fig
