import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Đảm bảo thư mục gốc dự án luôn nằm trong sys.path khi chạy bằng streamlit
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from src.schemas.document import ParsedDocument, DocRole, DocCategory
from src.schemas.criteria import CriteriaList
from src.schemas.report import ComplianceStatus, VerificationReport
from src.graph_rag.indexer import build_law_index
from src.graph_rag.retriever import retrieve_legal_context
from src.graph_rag.visualizer import (
    load_networkx_graph,
    build_pyvis_html,
    get_graph_edges_data,
    generate_matplotlib_fig,
    RELATION_COLORS,
)
from src.schemas.playbook import HSMTAuditPlaybook, PlaybookCriterionGuide
from src.engines.hsmt_reviewer import review_hsmt, load_default_playbook
from src.engines.hsdt_checker import check_hsdt
from src.converters.pdf_converter import convert_pdf_to_parsed_document, save_parsed_document_to_json
from config.settings import settings

st.set_page_config(
    page_title="Hệ thống Trợ lý AI Thẩm tra Hồ sơ Đấu thầu",
    page_icon="⚖️",
    layout="wide"
)

# Custom CSS cho phong cách chuyên nghiệp, phân cấp rõ ràng
st.markdown("""
<style>
    .main-header {
        font-size: 26px;
        font-weight: 800;
        color: #60a5fa;
        margin-bottom: 2px;
    }
    .sub-header {
        font-size: 14px;
        color: #94a3b8;
        margin-bottom: 16px;
    }
    .section-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        color: #f8fafc;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
    }
    .badge-valid {
        background-color: #dcfce7;
        color: #15803d;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
    .badge-invalid {
        background-color: #fee2e2;
        color: #b91c1c;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
    .badge-unclear {
        background-color: #fef9c3;
        color: #a16207;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
    .evidence-box {
        background-color: #1e293b;
        color: #e2e8f0;
        border: 1px solid #334155;
        border-left: 4px solid #38bdf8;
        padding: 12px 16px;
        border-radius: 6px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        margin-top: 8px;
        margin-bottom: 8px;
        line-height: 1.5;
    }
    .evidence-box b {
        color: #93c5fd;
    }
    .evidence-box i {
        color: #f8fafc;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 16px;
        font-weight: 600;
        padding: 10px 20px;
        border-radius: 6px 6px 0 0;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- SIDEBAR CẤU HÌNH -----------------
with st.sidebar:
    st.image("https://img.icons8.com/color/96/scales.png", width=60)
    st.title("Cấu hình AI Gateway")
    
    provider_option = st.selectbox(
        "Mô hình AI:",
        options=["mock", "gemini", "local"],
        index=0,
        help="'mock' để chạy thử nghiệm nhanh với dữ liệu giả lập; 'gemini' dùng Google GenAI SDK; 'local' dùng endpoint nội bộ (vLLM/Ollama)."
    )
    
    api_key_input = ""
    model_name_input = ""
    local_url_input = ""
    
    if provider_option == "gemini":
        api_key_input = st.text_input(
            "Gemini API Key",
            value=settings.gemini_api_key,
            type="password",
            placeholder="Nhập AIzaSy..."
        )
        model_name_input = st.text_input(
            "Gemini Model",
            value=settings.gemini_model,
            help="Khuyên dùng: gemini-2.5-flash hoặc gemini-2.0-flash"
        )
        if st.button("🔌 Kiểm tra kết nối Gemini API", use_container_width=True):
            from src.llm.gateway import test_gemini_connection
            with st.spinner("Đang kiểm tra kết nối tới Google Gemini API..."):
                res_conn = test_gemini_connection(api_key_input, model_name_input)
            if res_conn["ok"]:
                st.success(res_conn["message"])
            else:
                st.error(res_conn["message"])
    elif provider_option == "local":
        local_url_input = st.text_input(
            "Local LLM Base URL",
            value=settings.local_llm_base_url
        )
        model_name_input = st.text_input(
            "Model Name",
            value=settings.local_llm_model
        )
    else:
        st.info("💡 **Chế độ Mock:** Chạy độc lập, không cần kết nối mạng hay API Key.")

    st.divider()
    st.caption("Phiên bản: Demo MVP 1.0\nHỗ trợ tải lên: JSON Schema & File PDF tự động chuyển đổi")

# Khởi tạo session_state
if "criteria_list" not in st.session_state:
    st.session_state.criteria_list = None
if "hsmt_doc" not in st.session_state:
    st.session_state.hsmt_doc = None
if "hsmt_report" not in st.session_state:
    st.session_state.hsmt_report = None
if "hsdt_report" not in st.session_state:
    st.session_state.hsdt_report = None
if "last_graph_stats" not in st.session_state:
    st.session_state.last_graph_stats = None

llm_kwargs = {}
if provider_option == "gemini":
    if api_key_input:
        llm_kwargs["api_key"] = api_key_input
    if model_name_input:
        llm_kwargs["model"] = model_name_input
elif provider_option == "local":
    if local_url_input:
        llm_kwargs["base_url"] = local_url_input
    if model_name_input:
        llm_kwargs["model"] = model_name_input

# ----------------- TIÊU ĐỀ HỆ THỐNG -----------------
st.markdown("<div class='main-header'>⚖️ HỆ THỐNG TRỢ LÝ AI THẨM TRA HỒ SƠ ĐẤU THẦU</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-header'>Thẩm định tính hợp pháp của HSMT và kiểm tra tính tuân thủ pháp lý của HSDT theo Luật Đấu thầu & Luật Đất đai (Hỗ trợ nạp trực tiếp file PDF)</div>", unsafe_allow_html=True)

# ----------------- 3 PHẦN LỚN CỦA HỆ THỐNG -----------------
main_tab1, main_tab2, main_tab3 = st.tabs([
    "🗄️ PHẦN 1: KHO DỮ LIỆU",
    "📋 PHẦN 2: THẨM ĐỊNH HSMT",
    "⚖️ PHẦN 3: THẨM ĐỊNH HSDT"
])

# =========================================================
# PHẦN 1: KHO DỮ LIỆU
# =========================================================
with main_tab1:
    st.subheader("Quản lý Dữ liệu Luật & Dựng Đồ thị Tri thức (GraphRAG)")
    st.write("Nạp các văn bản quy phạm pháp luật (hỗ trợ cả **PDF** và **JSON**), bóc tách các điều khoản và dựng đồ thị liên kết tham chiếu (REFERENCES).")

    col_law_left, col_law_right = st.columns([1, 1], gap="medium")
    
    with col_law_left:
        st.markdown("#### 📥 Tải lên & Nạp văn bản Luật")
        source_law = st.radio(
            "Chọn nguồn dữ liệu Luật:",
            ["Sử dụng CSDL Luật mẫu có sẵn (data/mock_law)", "Tải lên file (PDF hoặc JSON) văn bản Luật mới"],
            horizontal=False
        )
        
        uploaded_law_doc = None
        if source_law.startswith("Tải lên"):
            uploaded_file = st.file_uploader(
                "Chọn file Luật (hỗ trợ .pdf hoặc .json)",
                type=["pdf", "json"],
                key="uploader_law"
            )
            if uploaded_file:
                try:
                    if uploaded_file.name.lower().endswith(".pdf"):
                        with st.spinner(f"Đang bóc tách và phân mảnh văn bản Luật từ PDF: {uploaded_file.name}..."):
                            bytes_data = uploaded_file.read()
                            uploaded_law_doc = convert_pdf_to_parsed_document(
                                pdf_source=bytes_data,
                                doc_role=DocRole.LAW,
                                file_name=uploaded_file.name
                            )
                        st.success(f"✅ Đã chuyển đổi PDF thành công! Gồm {uploaded_law_doc.total_pages} trang, bóc tách được **{len(uploaded_law_doc.sections)}** điều khoản/phân đoạn.")
                    else:
                        content_str = uploaded_file.read().decode("utf-8")
                        uploaded_law_doc = ParsedDocument.model_validate_json(content_str)
                        st.success(f"File JSON hợp lệ: {uploaded_law_doc.file_name} ({len(uploaded_law_doc.sections)} điều khoản)")

                    if uploaded_law_doc:
                        with st.expander("👁️ Xem trước các điều khoản bóc tách từ file vừa tải:"):
                            for s in uploaded_law_doc.sections[:8]:
                                st.markdown(f"- **{s.section_id}** (Trang {s.page_start}): {s.heading}")
                            if len(uploaded_law_doc.sections) > 8:
                                st.caption(f"...và {len(uploaded_law_doc.sections) - 8} điều khoản khác.")

                        if st.button("💾 Lưu vào kho `data/mock_law/` để lập chỉ mục", key="save_law_btn"):
                            save_target = settings.law_dir / f"{uploaded_law_doc.doc_id}.json"
                            save_parsed_document_to_json(uploaded_law_doc, save_target)
                            st.success(f"Đã lưu văn bản vào `{save_target.name}` thành công!")

                except Exception as e:
                    st.error(f"Lỗi khi xử lý file: {e}")
        else:
            existing_laws = sorted(
                list(settings.law_dir.glob("*.json")),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if not existing_laws:
                st.info("Chưa có file văn bản luật nào trong CSDL. Bạn hãy chọn mục **'Tải lên file PDF / JSON mới'** ở trên để nạp văn bản vào hệ thống.")
            else:
                st.markdown(f"##### 📋 Danh sách file hiện có trong CSDL ({len(existing_laws)} file)")
                for idx, lf in enumerate(existing_laws):
                    size_kb = lf.stat().st_size / 1024
                    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.2f} MB"
                    mtime_str = datetime.fromtimestamp(lf.stat().st_mtime).strftime("%d/%m/%Y %H:%M")

                    sec_info = ""
                    try:
                        with open(lf, "r", encoding="utf-8") as _f:
                            _d = json.load(_f)
                        if isinstance(_d, dict):
                            _secs = _d.get("sections", [])
                            sec_info = f" • **{len(_secs)}** điều khoản"
                        elif isinstance(_d, list):
                            sec_info = f" • **{len(_d)}** văn bản"
                    except Exception:
                        pass

                    with st.container(border=True):
                        col_card_info, col_card_btn = st.columns([4, 1.2])
                        with col_card_info:
                            st.markdown(f"📄 **`{lf.name}`**")
                            st.caption(f"📊 Dung lượng: `{size_str}`{sec_info} &nbsp;|&nbsp; 🕒 `{mtime_str}`")
                        with col_card_btn:
                            st.write("")
                            if st.button("🗑️ Xóa", key=f"btn_del_single_law_{idx}_{lf.name}", use_container_width=True, help=f"Xóa vĩnh viễn file {lf.name} khỏi CSDL"):
                                lf.unlink(missing_ok=True)
                                st.toast(f"Đã xóa file {lf.name} thành công!")
                                st.rerun()

        st.write("")
        if st.button("🔄 Dựng / Cập nhật Đồ thị Tri thức (GraphRAG)", type="primary", use_container_width=True):
            with st.spinner("Đang phân tích các liên kết tham chiếu và lập chỉ mục Vector/Graph..."):
                try:
                    res = build_law_index()
                    st.session_state.last_graph_stats = res
                    st.success(f"Hoàn thành! Đã nạp {res['total_nodes']} điều khoản và phát hiện {res['total_edges']} liên kết tham chiếu.")
                except Exception as e:
                    st.error(f"Lỗi khi dựng đồ thị tri thức: {e}")

    with col_law_right:
        st.markdown("#### 📊 Trạng thái Đồ thị Tri thức")
        if st.session_state.last_graph_stats:
            stats = st.session_state.last_graph_stats
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Văn bản luật", stats.get("total_documents", 1))
            m2.metric("Điều khoản (Nodes)", stats.get("total_nodes", 3))
            m3.metric("Liên kết (Edges)", stats.get("total_edges", 1))
            m4.metric("Chunks A3 (Context)", stats.get("total_chunks", 0))
            st.caption(f"Đường dẫn file đồ thị: `{stats.get('graph_path', '')}`")
        else:
            st.info("Bấm nút **'Dựng / Cập nhật Đồ thị Tri thức'** ở bên trái để tải thông số đồ thị.")

        st.markdown("#### 🔎 Tra cứu thử nghiệm Căn cứ Pháp lý")
        query_test = st.text_input("Nhập từ khóa pháp luật cần tra cứu:", value="bảo lãnh dự thầu", help="Hệ thống sẽ kết hợp Vector Search và duyệt các cạnh REFERENCES 1-hop để tìm điều khoản liên quan")
        if st.button("Tra cứu GraphRAG"):
            with st.spinner("Đang truy xuất đồ thị..."):
                results = retrieve_legal_context(query_test, top_k=2, hop_depth=1)
                if not results:
                    st.warning("Không tìm thấy điều khoản liên quan.")
                else:
                    st.write(f"Tìm thấy **{len(results)}** điều khoản liên quan:")
                    for idx, item in enumerate(results, 1):
                        rel_type = item.get("relation_type", "DIRECT_MATCH")
                        tag = "📌 Khớp trực tiếp" if rel_type == "DIRECT_MATCH" else f"🔗 {rel_type}"
                        with st.expander(f"{idx}. {item.get('clause_id')} ({tag})"):
                            st.caption(f"Nguồn: {item.get('law_name')} (Trang {item.get('page_number')})")
                            if item.get("expansion_path"):
                                st.markdown(f"**Đường đi giải trình:** `{item.get('expansion_path')}`")
                            if item.get("evidence_text"):
                                st.caption(f"**Căn cứ dẫn chiếu:** {item.get('evidence_text')}")
                            st.markdown(item.get("content_markdown"))


    # ---------- TRỰC QUAN HÓA MẠNG LƯỚI ĐỒ THỊ TRI THỨC (PHONG CÁCH TEST-KG-RAG) ----------
    st.divider()
    st.markdown("#### 🕸️ Khám phá Đồ thị Tri thức Pháp luật (Interactive Knowledge Graph Explorer)")
    st.markdown("""
    Khám phá đồ thị quan hệ pháp lý có căn cứ được xây dựng từ:
    - **Cấu trúc (`PART_OF` / `CONTAINS`):** Văn bản → Chương → Điều → Khoản → Điểm.
    - **Dẫn chiếu (`REFERENCES`):** Dẫn chiếu điều khoản trong cùng văn bản hoặc liên văn bản.
    - **Quy định chi tiết (`DETAILS`):** Nghị định/Thông tư hướng dẫn thi hành Luật gốc.
    - **Sửa đổi / Bổ sung / Bãi bỏ (`AMENDS`, `SUPPLEMENTS`, `REPEALS`):** Căn cứ từ các điều khoản sửa đổi chính thức.
    """)

    graph_inst = load_networkx_graph()
    total_g_nodes = graph_inst.number_of_nodes()
    total_g_edges = graph_inst.number_of_edges()

    if total_g_nodes == 0:
        st.info("Chưa có đồ thị tri thức. Hãy bấm nút **'Dựng / Cập nhật Đồ thị Tri thức'** ở trên để khởi tạo.")
    else:
        graph_subtab1, graph_subtab2, graph_subtab3 = st.tabs([
            "🌐 Đồ thị Tương tác (Interactive Dynamic Graph)",
            "📋 Bảng Danh sách Quan hệ Pháp lý (Edges Table)",
            "🖼️ Sơ đồ Mạng lưới Tĩnh (Matplotlib Diagram)"
        ])

        with graph_subtab1:
            st.markdown("##### 1. Đồ thị mạng lưới quan hệ trực quan (Interactive Dynamic Graph)")

            col_m1, col_m2 = st.columns([1, 1])
            with col_m1:
                view_mode = st.radio(
                    "Không gian hiển thị đồ thị:",
                    [
                        "🌐 Toàn cảnh (Hiển thị tất cả Nodes & Cạnh trong cùng không gian)",
                        "🎯 Trọng tâm (Chỉ hiển thị cụm láng giềng của Điều khoản được chọn)"
                    ],
                    horizontal=False,
                    key="kg_view_mode"
                )
            is_show_all = "Toàn cảnh" in view_mode

            with col_m2:
                search_kw = st.text_input(
                    "🔍 Lọc nhanh danh sách điều khoản (theo từ khóa/số điều):",
                    value="",
                    placeholder="VD: 14, 18, bảo đảm, hợp lệ...",
                    key="kg_search_kw"
                )

            # Thu thập danh sách nodes hợp lệ
            candidate_nodes = []
            for nid, data in graph_inst.nodes(data=True):
                h = data.get("heading", nid)
                doc = data.get("file_name", "")
                if search_kw.strip():
                    kw_lower = search_kw.strip().lower()
                    if kw_lower not in h.lower() and kw_lower not in doc.lower() and kw_lower not in nid.lower():
                        continue
                candidate_nodes.append((nid, f"{h} ({doc or 'Luật'})"))

            candidate_nodes.sort(key=lambda x: graph_inst.degree(x[0]), reverse=True)
            
            all_opt_key = "🌐 Hiển thị Toàn bộ Không gian Đồ thị (Toàn cảnh)"
            node_options = {all_opt_key: None}
            for nid, label in candidate_nodes:
                node_options[label] = nid

            # Chọn Điều khoản trọng tâm (hoặc xem toàn cảnh)
            options_keys = list(node_options.keys())
            prev_label = st.session_state.get("kg_selected_node_label")
            sel_idx = options_keys.index(prev_label) if prev_label in options_keys else 0

            selected_label = st.selectbox(
                "Lựa chọn Điều khoản cụ thể để làm nổi bật (Spotlight) và xem mối quan hệ:",
                options=options_keys,
                index=sel_idx,
                key="kg_selected_node_label"
            )
            selected_node_id = node_options[selected_label]
            selected_data = graph_inst.nodes.get(selected_node_id, {}) if selected_node_id else {}

            # Interactive Graph Controls
            cg1, cg2, cg3 = st.columns([1, 2, 1])
            with cg1:
                graph_hops = st.selectbox(
                    "Độ sâu quan hệ liên kết:",
                    [1, 2],
                    index=0,
                    format_func=lambda h: f"{h} hop (Láng giềng trực tiếp)" if h == 1 else f"{h} hops (Mở rộng 2 tầng)",
                    key="kg_graph_hops"
                )
            with cg2:
                graph_rels = st.multiselect(
                    "Lọc loại quan hệ hiển thị:",
                    ["REFERENCES", "DETAILS", "AMENDS", "SUPPLEMENTS", "REPEALS", "PART_OF"],
                    default=["REFERENCES", "DETAILS", "AMENDS", "PART_OF"],
                    key="kg_graph_rels"
                )
            with cg3:
                enable_physics = st.checkbox("Mô phỏng vật lý động (Physics)", value=True, key="kg_enable_physics")

            # Chú giải trực quan phân biệt rõ ràng Node và Cạnh (Edge)
            st.markdown("""
            <div style="background-color: #1e293b; padding: 12px 16px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 12px; font-size: 13px;">
                <div style="margin-bottom: 6px;">
                    <b>📌 Nút (Node - Điều khoản / Thực thể):</b> 
                    <span style="color: #fbbf24;">🟡 Vàng</span> (Tâm điểm được chọn) &nbsp;|&nbsp; 
                    <span style="color: #34d399;">🟢 Xanh lá</span> (Láng giềng liên kết) &nbsp;|&nbsp; 
                    <span style="color: #60a5fa;">🔵 Xanh dương <i>(Hình thoi)</i></span> (Chương/Văn bản) &nbsp;|&nbsp; 
                    <span style="color: #f87171;">🔴 Đỏ <i>(Tam giác)</i></span> (Điều khoản sửa đổi) &nbsp;|&nbsp; 
                    <span style="color: #c084fc;">🟣 Tím</span> (Điều khoản thông thường)
                </div>
                <div>
                    <b>🔗 Đường mũi tên (Cạnh - Mối quan hệ pháp lý):</b> 
                    <span style="color: #c084fc;">🟣 Tím</span> (Dẫn chiếu <code>REFERENCES</code>) &nbsp;|&nbsp; 
                    <span style="color: #38bdf8;">🌐 Xanh lơ</span> (Hướng dẫn chi tiết <code>DETAILS</code>) &nbsp;|&nbsp; 
                    <span style="color: #ef4444;">🔴 Đỏ</span> (Sửa đổi <code>AMENDS</code>) &nbsp;|&nbsp; 
                    <span style="color: #f97316;">🟠 Cam</span> (Bổ sung <code>SUPPLEMENTS</code>) &nbsp;|&nbsp; 
                    <span style="color: #94a3b8;">⚪ Xám</span> (Cấu trúc <code>PART_OF</code>)
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Render PyVis Graph
            with st.spinner("Đang vẽ đồ thị tương tác toàn không gian..."):
                graph_html = build_pyvis_html(
                    graph=graph_inst,
                    center_node_id=selected_node_id,
                    show_all_nodes=is_show_all,
                    max_hops=graph_hops,
                    allowed_relations=graph_rels,
                    height="580px",
                    physics=enable_physics,
                )
                components.html(graph_html, height=600, scrolling=False)

            st.caption("💡 *Mẹo tương tác: Kéo thả các node để quan sát, cuộn chuột để phóng to/thu nhỏ (Zoom), hover vào node hoặc đường nối để xem chi tiết căn cứ và loại quan hệ.*")

            st.divider()

            # Chi tiết Điều khoản được chọn hoặc Tổng quan toàn cảnh
            if selected_node_id and selected_data:
                st.markdown(f"##### 📌 Chi tiết Điều khoản được chọn: {selected_data.get('heading', selected_node_id)}")
                st.caption(f"**Văn bản:** {selected_data.get('file_name', '')} | **Trang:** {selected_data.get('page_start', 1)}")
                
                with st.expander("📖 Xem toàn văn nội dung điều khoản này:", expanded=True):
                    st.markdown(selected_data.get("content_markdown", "Không có nội dung chi tiết."))

                # Hai cột In-edges & Out-edges
                c_in, c_out = st.columns(2)
                with c_in:
                    st.markdown("###### ⬅️ Quan hệ trỏ vào (Incoming Edges)")
                    in_edges = list(graph_inst.in_edges(selected_node_id, data=True))
                    if not in_edges:
                        st.caption("Không có quan hệ trỏ vào.")
                    for src, _, data in in_edges:
                        src_node = graph_inst.nodes.get(src, {})
                        rel = data.get("relation_type") or data.get("relation", "")
                        st.markdown(f"- **{src_node.get('heading', src)}** `--[{rel}]-->` `{selected_data.get('heading', selected_node_id)}`")
                        if data.get("evidence_text"):
                            st.caption(f"  *Căn cứ:* {data.get('evidence_text')}")

                with c_out:
                    st.markdown("###### ➡️ Quan hệ trỏ ra (Outgoing Edges)")
                    out_edges = list(graph_inst.out_edges(selected_node_id, data=True))
                    if not out_edges:
                        st.caption("Không có quan hệ trỏ ra.")
                    for _, tgt, data in out_edges:
                        tgt_node = graph_inst.nodes.get(tgt, {})
                        rel = data.get("relation_type") or data.get("relation", "")
                        st.markdown(f"- `{selected_data.get('heading', selected_node_id)}` `--[{rel}]-->` **{tgt_node.get('heading', tgt)}**")
                        if data.get("evidence_text"):
                            st.caption(f"  *Căn cứ:* {data.get('evidence_text')}")
            else:
                st.markdown("##### 🌐 Tổng quan Toàn bộ Không gian Đồ thị Tri thức")
                st.info(f"Đang hiển thị toàn cảnh tất cả **{total_g_nodes} Điều khoản / Phân đoạn** và **{total_g_edges} Liên kết quan hệ pháp lý** trong cùng 1 không gian đồ thị. Bạn có thể chọn bất kỳ Điều khoản nào ở menu dropdown phía trên để phóng to và phân tích sâu các quan hệ chiều vào / chiều ra của điều đó.")

        with graph_subtab2:
            st.markdown("##### 2. Danh sách quan hệ pháp lý (Edges Table)")
            edge_rel_filter = st.multiselect(
                "Lọc theo loại quan hệ:",
                ["REFERENCES", "DETAILS", "AMENDS", "SUPPLEMENTS", "REPEALS", "PART_OF"],
                default=["REFERENCES", "DETAILS", "AMENDS"],
                key="kg_edge_table_filter"
            )
            edges_records = get_graph_edges_data(graph_inst, allowed_relations=edge_rel_filter)
            if edges_records:
                df_edges = pd.DataFrame(edges_records)
                st.dataframe(df_edges, use_container_width=True)
                st.caption(f"Tổng số quan hệ hiển thị: **{len(edges_records)}** / {total_g_edges}")
            else:
                st.info("Không có quan hệ nào phù hợp bộ lọc.")

        with graph_subtab3:
            st.markdown("##### 3. Sơ đồ Mạng lưới Tĩnh (Matplotlib)")
            c_filter1, c_filter2 = st.columns([1, 1])
            with c_filter1:
                max_n = st.slider("Số lượng điều khoản hiển thị tối đa:", min_value=15, max_value=70, value=45, step=5, key="slider_max_nodes")
            with c_filter2:
                hide_isolated = st.checkbox("Ẩn các điều khoản đứng độc lập (không có liên kết)", value=True, key="cb_hide_isolated")
            
            fig_graph = generate_matplotlib_fig(filter_isolated=hide_isolated, max_nodes=max_n)
            if fig_graph:
                st.pyplot(fig_graph, use_container_width=True)
            else:
                st.info("Chưa có đồ thị để hiển thị. Vui lòng bấm 'Dựng / Cập nhật Đồ thị Tri thức' ở trên.")


# =========================================================
# PHẦN 2: THẨM ĐỊNH HSMT
# =========================================================
with main_tab2:
    st.subheader("🏛️ Thẩm định Hồ sơ Mời thầu (HSMT) theo Sổ tay Playbook & GraphRAG")
    st.write("Quản lý CSDL HSMT, cấu hình File Hướng dẫn Tiêu chí Thẩm định (Audit Playbook) và đối chiếu với Đồ thị Tri thức Pháp luật để đưa ra danh sách thẩm định cho chuyên gia xem xét và ra quyết định.")

    col_hsmt_db, col_playbook = st.columns([1, 1], gap="large")

    # ---------- CỘT 1: QUẢN LÝ CSDL HỒ SƠ MỜI THẦU ----------
    with col_hsmt_db:
        st.markdown("#### 📋 1. Quản lý CSDL Hồ sơ Mời thầu (`data/mock_hsmt/`)")
        source_hsmt = st.radio(
            "Chọn nguồn HSMT để thẩm định:",
            ["Dùng file có sẵn trong CSDL", "Tải lên file HSMT mới (PDF hoặc JSON)"],
            horizontal=True,
            key="source_hsmt_radio"
        )

        hsmt_to_process = None

        if source_hsmt == "Tải lên file HSMT mới (PDF hoặc JSON)":
            uploaded_hsmt = st.file_uploader("Chọn file HSMT (hỗ trợ .pdf hoặc .json)", type=["pdf", "json"], key="uploader_hsmt_file")
            if uploaded_hsmt:
                try:
                    if uploaded_hsmt.name.lower().endswith(".pdf"):
                        with st.spinner("Đang chuyển đổi PDF HSMT sang ParsedDocument..."):
                            uploaded_doc = convert_pdf_to_parsed_document(
                                pdf_source=uploaded_hsmt.read(),
                                doc_role=DocRole.HSMT,
                                file_name=uploaded_hsmt.name
                            )
                        st.success(f"✅ Đã chuyển đổi PDF HSMT thành công! Gói thầu: **{uploaded_doc.metadata.bidding_package_name or uploaded_doc.file_name}** ({len(uploaded_doc.sections)} phân đoạn)")
                    else:
                        content_str = uploaded_hsmt.read().decode("utf-8")
                        uploaded_doc = ParsedDocument.model_validate_json(content_str)
                        st.success(f"Nạp thành công file JSON: `{uploaded_doc.file_name}`")

                    if uploaded_doc:
                        with st.expander("👁️ Xem trước phân đoạn HSMT vừa nạp:"):
                            for s in uploaded_doc.sections[:6]:
                                st.markdown(f"- **{s.heading}** (Trang {s.page_start}-{s.page_end})")

                        if st.button("💾 Lưu vào CSDL `data/mock_hsmt/`", key="save_hsmt_btn", use_container_width=True):
                            save_target = settings.hsmt_dir / f"{uploaded_doc.doc_id}.json"
                            save_parsed_document_to_json(uploaded_doc, save_target)
                            st.success(f"Đã lưu HSMT vào `{save_target.name}` thành công!")
                            st.rerun()

                        hsmt_to_process = uploaded_doc
                except Exception as e:
                    st.error(f"Lỗi khi xử lý file HSMT: {e}")
        else:
            existing_hsmts = sorted(list(settings.hsmt_dir.glob("*.json")), key=lambda p: p.stat().st_mtime, reverse=True)
            if not existing_hsmts:
                st.info("Chưa có file HSMT nào trong CSDL. Bạn hãy chuyển sang mục **'Tải lên file HSMT mới'** ở trên để nạp hồ sơ.")
            else:
                st.caption(f"📁 CSDL hiện có **{len(existing_hsmts)}** file HSMT:")

                hsmt_options = {}
                for idx, hf in enumerate(existing_hsmts):
                    size_kb = hf.stat().st_size / 1024
                    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.2f} MB"
                    mtime_str = datetime.fromtimestamp(hf.stat().st_mtime).strftime("%d/%m/%Y %H:%M")

                    pkg_name = hf.stem
                    num_sections = 0
                    try:
                        with open(hf, "r", encoding="utf-8") as _f:
                            _d = json.load(_f)
                        if isinstance(_d, dict):
                            num_sections = len(_d.get("sections", []))
                            meta = _d.get("metadata", {})
                            pkg_name = meta.get("bidding_package_name") or _d.get("file_name") or hf.stem
                    except Exception:
                        pass

                    label = f"📄 {hf.name} — {pkg_name} ({num_sections} phần)"
                    hsmt_options[label] = hf

                    with st.container(border=True):
                        c_info, c_action = st.columns([4, 1.2])
                        with c_info:
                            st.markdown(f"📄 **`{hf.name}`**")
                            st.caption(f"🎯 Gói thầu: **{pkg_name}** &nbsp;|&nbsp; 📊 `{size_str}` ({num_sections} phân đoạn) &nbsp;|&nbsp; 🕒 `{mtime_str}`")
                        with c_action:
                            st.write("")
                            if st.button("🗑️ Xóa", key=f"btn_del_hsmt_{idx}_{hf.name}", use_container_width=True, help=f"Xóa vĩnh viễn file {hf.name} khỏi CSDL HSMT"):
                                hf.unlink(missing_ok=True)
                                st.toast(f"Đã xóa file HSMT {hf.name} thành công!")
                                st.rerun()

                st.write("")
                selected_hsmt_label = st.selectbox(
                    "🎯 Chọn Hồ sơ Mời thầu kích hoạt để Thẩm định:",
                    options=list(hsmt_options.keys()),
                    index=0,
                    key="sel_active_hsmt"
                )
                if selected_hsmt_label:
                    active_hsmt_path = hsmt_options[selected_hsmt_label]
                    try:
                        hsmt_to_process = ParsedDocument.model_validate_json(active_hsmt_path.read_text(encoding="utf-8"))
                        st.session_state.active_hsmt_file_name = active_hsmt_path.name
                    except Exception as e:
                        st.error(f"Lỗi nạp file HSMT đã chọn: {e}")

    # ---------- CỘT 2: CẤU HÌNH FILE HƯỚNG DẪN THẨM ĐỊNH (AUDIT PLAYBOOK) ----------
    with col_playbook:
        st.markdown("#### 📖 2. File Hướng dẫn Tiêu chí Thẩm định (Audit Playbook)")
        st.write("Sổ tay hướng dẫn định hướng cho LLM các tiêu chí cần rà soát, dấu hiệu vi phạm và câu truy vấn Đồ thị Luật.")

        playbooks_dir = Path("data/playbooks")
        playbooks_dir.mkdir(parents=True, exist_ok=True)
        available_playbooks = sorted(list(playbooks_dir.glob("*.json")))

        playbook_options = {}
        for pb_file in available_playbooks:
            try:
                with open(pb_file, "r", encoding="utf-8") as _pf:
                    pb_obj = json.load(_pf)
                pb_title = pb_obj.get("playbook_name", pb_file.stem)
                playbook_options[f"📘 {pb_title} ({pb_file.name})"] = pb_file
            except Exception:
                playbook_options[f"📘 {pb_file.name}"] = pb_file

        if not playbook_options:
            default_pb = load_default_playbook()
            active_playbook = default_pb
            st.info("Đang áp dụng Sổ tay Hướng dẫn Thẩm định HSMT mặc định.")
        else:
            selected_pb_label = st.selectbox(
                "Chọn File Hướng dẫn Tiêu chí Thẩm định:",
                options=list(playbook_options.keys()),
                index=0,
                key="sel_playbook_guide"
            )
            selected_pb_file = playbook_options[selected_pb_label]
            try:
                active_playbook = HSMTAuditPlaybook.model_validate_json(selected_pb_file.read_text(encoding="utf-8"))
            except Exception as e:
                st.warning(f"Lỗi nạp file hướng dẫn: {e}. Áp dụng bộ chuẩn mặc định.")
                active_playbook = load_default_playbook()

        st.markdown(f"📘 **Sổ tay đang áp dụng:** {active_playbook.playbook_name} `v{active_playbook.version}`")
        st.caption(f"📝 {active_playbook.description} &nbsp;|&nbsp; Gồm **{len(active_playbook.guides)}** tiêu chí rà soát.")

        with st.expander("👁️ Xem chi tiết các Tiêu chí & Quy tắc rà soát trong File Hướng dẫn:", expanded=True):
            st.caption("💡 *Cuộn chuột để xem toàn bộ danh sách tiêu chí & chỉ dẫn rà soát:*")
            with st.container(height=340, border=False):
                for idx, g in enumerate(active_playbook.guides, 1):
                    cat_val = g.category.value if hasattr(g.category, 'value') else g.category
                    chk_type = getattr(g, "check_type", "Ngữ nghĩa (LLM)")
                    sev = getattr(g, "severity", "Chặn")
                    loc = getattr(g, "target_location", "Toàn bộ HSMT")
                    ref_law = getattr(g, "legal_basis_ref", "Luật Đấu thầu 2023")
                    sev_badge = "🛑 Chặn" if sev == "Chặn" else ("⚠️ Cảnh báo" if sev == "Cảnh báo" else "💡 Gợi ý")
                    st.markdown(f"**{idx}. [{g.guide_id}] {g.criterion_name}** — `{sev_badge}` | `{chk_type}`")
                    st.caption(f"📍 **Vị trí HSMT:** {loc} &nbsp;|&nbsp; ⚖️ **Căn cứ:** {ref_law} &nbsp;|&nbsp; 🏷️ `{cat_val}`")
                    st.markdown(f"- **AI kiểm tra / Chỉ dẫn đối soát:** {g.audit_instruction}")
                    if g.red_flags:
                        st.markdown(f"- **Dấu hiệu vi phạm (Red flags):** {'; '.join(g.red_flags)}")
                    st.caption(f"- **Truy vấn Đồ thị Luật (GraphRAG):** `{g.legal_query}`")
                    if idx < len(active_playbook.guides):
                        st.divider()

        # Tùy chọn tải lên Playbook mới
        with st.expander("📤 Tải lên File Hướng dẫn Thẩm định mới (.json)", expanded=False):
            uploaded_pb_file = st.file_uploader("Chọn file Playbook JSON", type=["json"], key="uploader_pb_file")
            if uploaded_pb_file:
                try:
                    pb_content = uploaded_pb_file.read().decode("utf-8")
                    new_pb = HSMTAuditPlaybook.model_validate_json(pb_content)
                    save_pb_path = playbooks_dir / f"{new_pb.playbook_id}.json"
                    save_pb_path.write_text(pb_content, encoding="utf-8")
                    st.success(f"Đã lưu Sổ tay Hướng dẫn '{new_pb.playbook_name}' thành công!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi cấu trúc file Playbook: {e}")

    # ---------- NÚT KÍCH HOẠT THẨM ĐỊNH TOÀN DIỆN ----------
    st.divider()
    if st.button("🚀 Bắt đầu Thẩm định HSMT theo File Hướng dẫn & Đồ thị Luật", type="primary", use_container_width=True):
        if not hsmt_to_process:
            st.warning("Vui lòng chọn hoặc tải lên file HSMT trước khi tiến hành thẩm định!")
        else:
            with st.spinner("Đang bóc tách tiêu chí, đối chiếu Sổ tay Hướng dẫn và tra cứu Đồ thị Tri thức Pháp luật..."):
                try:
                    crit_list, rep = review_hsmt(
                        hsmt_to_process,
                        provider=provider_option,
                        playbook=active_playbook,
                        **llm_kwargs
                    )
                    st.session_state.criteria_list = crit_list
                    st.session_state.hsmt_doc = hsmt_to_process
                    st.session_state.hsmt_report = rep
                    st.success(f"✅ Thẩm định hoàn tất! Đã đánh giá {rep.total_criteria} tiêu chí theo Sổ tay '{active_playbook.playbook_name}'.")
                except Exception as e:
                    st.error(f"Lỗi khi thẩm định HSMT: {e}")

    # ---------- KẾT QUẢ & BÀN RA QUYẾT ĐỊNH CHO NGƯỜI DÙNG (HUMAN-IN-THE-LOOP) ----------
    if st.session_state.hsmt_report:
        rep: VerificationReport = st.session_state.hsmt_report
        st.divider()
        st.markdown(f"### 📊 Kết quả Thẩm định & Bàn Ra Quyết định: {rep.package_name}")
        st.info(f"**Tóm lược tổng thể của Hệ thống:** {rep.overall_summary}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Tổng số tiêu chí", rep.total_criteria)
        m2.metric("🟢 Hợp lệ (Đạt)", rep.valid_count)
        m3.metric("🔴 Trái luật / Cài cắm", rep.invalid_count, delta=f"-{rep.invalid_count}" if rep.invalid_count > 0 else 0, delta_color="inverse")
        m4.metric("🟡 Cần làm rõ", rep.insufficient_count)

        st.markdown("#### 📝 Bàn Thẩm định Chuyên gia: Đối chiếu HSMT & Đánh giá Tiêu chí")
        st.caption("Giao diện chia đôi trực quan: Bên trái hiển thị văn bản HSMT để tra cứu và đối chiếu; Bên phải là danh sách đánh giá từng tiêu chí và biểu mẫu phê duyệt của chuyên gia.")

        col_hsmt_view, col_crit_eval = st.columns([1, 1.15], gap="large")

        # =========================================================
        # BÊN TRÁI: HIỂN THỊ NỘI DUNG HSMT
        # =========================================================
        with col_hsmt_view:
            st.markdown("##### 📄 Văn bản Hồ sơ Mời thầu (HSMT)")
            active_doc: Optional[ParsedDocument] = st.session_state.get("hsmt_doc")
            if not active_doc and hsmt_to_process:
                active_doc = hsmt_to_process
                
            if not active_doc:
                try:
                    active_doc = ParsedDocument.model_validate_json(
                        (settings.hsmt_dir / "hsmt_sample.json").read_text(encoding="utf-8")
                    )
                except Exception:
                    pass

            if active_doc:
                st.caption(f"📁 **File:** `{active_doc.file_name}` &nbsp;|&nbsp; 📊 **{len(active_doc.sections)}** phân đoạn &nbsp;|&nbsp; 📖 **{active_doc.total_pages}** trang")
                
                # Bộ chọn phân đoạn & ô tìm kiếm từ khóa
                c_sec_sel, c_sec_search = st.columns([1.3, 1])
                with c_sec_sel:
                    sec_options = {"🌐 Xem Toàn bộ các Phân đoạn": "ALL"}
                    for s in active_doc.sections:
                        sec_options[f"📑 {s.heading} (Trang {s.page_start}-{s.page_end})"] = s.section_id
                    selected_sec_label = st.selectbox(
                        "Chọn phân đoạn xem nhanh:",
                        options=list(sec_options.keys()),
                        index=0,
                        key="view_hsmt_sec_sel"
                    )
                    selected_sec_id = sec_options[selected_sec_label]

                with c_sec_search:
                    search_doc_kw = st.text_input(
                        "🔍 Tìm từ khóa trong HSMT:",
                        placeholder="VD: bảo lãnh, hợp đồng...",
                        key="view_hsmt_search_kw"
                    )

                # Khung cuộn hiển thị toàn văn HSMT
                with st.container(height=650, border=True):
                    matched_count = 0
                    kw_filter = search_doc_kw.strip().lower()

                    for s in active_doc.sections:
                        if selected_sec_id != "ALL" and s.section_id != selected_sec_id:
                            continue

                        if kw_filter:
                            if kw_filter not in s.heading.lower() and kw_filter not in s.content_markdown.lower():
                                continue

                        matched_count += 1
                        st.markdown(f"**📑 {s.heading}**")
                        st.caption(f"📍 *Trang {s.page_start} - {s.page_end} &nbsp;|&nbsp; Phân đoạn: `{s.section_id}`*")
                        st.markdown(s.content_markdown)

                        if s.tables:
                            for t in s.tables:
                                cap = getattr(t, "caption", None) or getattr(t, "title", None)
                                if cap:
                                    st.caption(f"📊 {cap}")
                                if getattr(t, "markdown_table", None):
                                    st.markdown(t.markdown_table)

                        st.divider()

                    if matched_count == 0:
                        st.info("Không tìm thấy nội dung phù hợp với từ khóa tìm kiếm trong phân đoạn này.")
            else:
                st.info("Chưa nạp được nội dung HSMT.")

        # =========================================================
        # BÊN PHẢI: DANH SÁCH ĐÁNH GIÁ CỦA CÁC TIÊU CHÍ
        # =========================================================
        with col_crit_eval:
            st.markdown("##### ⚖️ Danh sách Đánh giá Tiêu chí & Phê duyệt Chuyên gia")
            st.caption("Xem kết luận của AI, đối chiếu quy tắc Sổ tay & Căn cứ Đồ thị Luật, sau đó chốt quyết định:")

            filter_crit_mode = st.radio(
                "Lọc tiêu chí:",
                ["Tất cả", "🔴 Trái luật / Cài cắm", "🟡 Cần làm rõ", "🟢 Hợp lệ"],
                horizontal=True,
                key="filter_crit_mode_radio"
            )

            matched_crit = 0
            for idx, a in enumerate(rep.assessments, 1):
                badge = "🟢 HỢP LỆ" if a.status == ComplianceStatus.VALID else ("🔴 TRÁI LUẬT / CÀI CẮM" if a.status == ComplianceStatus.INVALID else "🟡 CẦN LÀM RÕ")
                
                if filter_crit_mode == "🔴 Trái luật / Cài cắm" and a.status != ComplianceStatus.INVALID:
                    continue
                if filter_crit_mode == "🟡 Cần làm rõ" and a.status != ComplianceStatus.INSUFFICIENT_BASIS:
                    continue
                if filter_crit_mode == "🟢 Hợp lệ" and a.status != ComplianceStatus.VALID:
                    continue

                matched_crit += 1
                exp_open = (a.status != ComplianceStatus.VALID)

                with st.expander(f"**#{idx}. {a.criterion_name}** — {badge}", expanded=exp_open):
                    st.markdown("###### 📄 1. Trích xuất HSMT & Quy tắc Playbook")
                    st.markdown(f"**Yêu cầu tóm tắt:** {a.requirement_summary}")
                    if a.evidences:
                        ev = a.evidences[0]
                        st.markdown(
                            f"<div class='evidence-box'><b>Trích xuất nguyên văn (Trang {ev.page_number}):</b><br/>"
                            f"<i>\"{ev.extracted_quote}\"</i></div>",
                            unsafe_allow_html=True
                        )
                    if a.playbook_guide_used:
                        st.caption(f"**📖 Quy tắc Playbook áp dụng:** {a.playbook_guide_used}")

                    st.write("")
                    st.markdown("###### ⚖️ 2. Căn cứ Pháp lý từ Đồ thị Tri thức (GraphRAG)")
                    st.markdown(f"**Lập luận của AI:** {a.reasoning}")
                    if a.missing_or_unclear_points:
                        st.error(f"**Điểm vi phạm / Cài cắm:** {'; '.join(a.missing_or_unclear_points)}")
                    st.warning(f"**Khuyến nghị cho Bên mời thầu:** {a.recommendation}")

                    if a.references:
                        with st.expander(f"📚 Xem Căn cứ Pháp lý đối chiếu từ GraphRAG ({len(a.references)} điều khoản)", expanded=False):
                            st.caption("💡 *Cuộn chuột trong khung bên dưới để tra cứu các điều khoản:*")
                            with st.container(height=220, border=True):
                                for r_idx, r in enumerate(a.references, 1):
                                    st.markdown(f"**{r_idx}. {r.law_name} ({r.clause_id})**")
                                    st.markdown(f"- *Nội dung quy định:* {r.summary}")
                                    if r.expansion_path:
                                        st.markdown(f"- *Đường đi giải trình:* `{r.expansion_path}`")
                                    if r.evidence_text:
                                        st.caption(f"- *Căn cứ dẫn chiếu:* {r.evidence_text}")
                                    if r_idx < len(a.references):
                                        st.divider()

                    st.divider()
                    st.markdown("###### ✍️ 3. Quyết định của Chuyên gia Thẩm định (Human-in-the-Loop)")
                    col_dec_status, col_dec_note = st.columns([1, 1.5])

                    with col_dec_status:
                        current_dec = a.user_decision or a.status
                        status_options = [ComplianceStatus.VALID, ComplianceStatus.INVALID, ComplianceStatus.INSUFFICIENT_BASIS]
                        status_labels = {
                            ComplianceStatus.VALID: "✅ Phê duyệt: HỢP LỆ",
                            ComplianceStatus.INVALID: "❌ Không hợp lệ (Sửa HSMT)",
                            ComplianceStatus.INSUFFICIENT_BASIS: "⚠️ Yêu cầu làm rõ"
                        }
                        new_dec = st.selectbox(
                            "Chốt quyết định:",
                            options=status_options,
                            index=status_options.index(current_dec),
                            format_func=lambda x: status_labels.get(x, x.value),
                            key=f"user_dec_sel_{idx}"
                        )
                        a.user_decision = new_dec

                    with col_dec_note:
                        default_note = a.user_decision_note or (a.recommendation if a.status != ComplianceStatus.VALID else "Đồng ý với đánh giá của AI.")
                        user_note = st.text_input(
                            "Ý kiến / Ghi chú chỉ đạo:",
                            value=default_note,
                            key=f"user_dec_note_{idx}"
                        )
                        a.user_decision_note = user_note

            if matched_crit == 0:
                st.info("Không có tiêu chí nào phù hợp với bộ lọc trạng thái đã chọn.")

        # ---------- KHUNG HÀNH ĐỘNG CHỐT QUYẾT ĐỊNH & XUẤT BÁO CÁO ----------
        st.divider()
        st.markdown("#### 📥 Hoàn tất & Xuất Báo cáo Thẩm định HSMT")
        b1, b2, b3 = st.columns([2, 1, 1])

        with b1:
            if st.button("✅ Lưu Quyết định Thẩm định & Chuyển sang Thẩm định HSDT", type="primary", use_container_width=True):
                st.session_state.hsmt_report = rep
                st.success("Đã lưu Quyết định Thẩm định của Chuyên gia! Bộ tiêu chí đã sẵn sàng áp dụng tại Phần 3 (Thẩm định HSDT).")

        with b2:
            report_json_str = rep.model_dump_json(indent=2)
            st.download_button(
                "📥 Tải Báo cáo (JSON)",
                data=report_json_str,
                file_name=f"Bao_cao_Tham_dinh_HSMT_{rep.package_name[:20]}.json",
                mime="application/json",
                use_container_width=True
            )

        with b3:
            # Tạo báo cáo Markdown hoàn chỉnh
            md_lines = [
                f"# BÁO CÁO THẨM ĐỊNH HỒ SƠ MỜI THẦU",
                f"**Gói thầu:** {rep.package_name}  ",
                f"**Ngày thẩm định:** {datetime.now().strftime('%d/%m/%Y %H:%M')}  ",
                f"**Tổng kết:** {rep.overall_summary}  \n",
                f"| STT | Tiêu chí | Đánh giá AI | Quyết định Chuyên gia | Ý kiến chỉ đạo |",
                f"| :--- | :--- | :--- | :--- | :--- |"
            ]
            for i, ass in enumerate(rep.assessments, 1):
                ai_st = ass.status.value
                user_st = ass.user_decision.value if ass.user_decision else ai_st
                note = ass.user_decision_note or "-"
                md_lines.append(f"| {i} | {ass.criterion_name} | {ai_st} | **{user_st}** | {note} |")

            report_md_str = "\n".join(md_lines)
            st.download_button(
                "📄 Tải Biên bản (Markdown)",
                data=report_md_str,
                file_name=f"Bien_ban_Tham_dinh_HSMT_{rep.package_name[:20]}.md",
                mime="text/markdown",
                use_container_width=True
            )



# =========================================================
# PHẦN 3: THẨM ĐỊNH HSDT
# =========================================================
with main_tab3:
    st.subheader("Thẩm định Hồ sơ Dự thầu (HSDT) & Lập Ma trận Tuân thủ")
    st.write("Đối chiếu chi tiết Hồ sơ dự thầu của nhà thầu (hỗ trợ cả **PDF** và **JSON**) với Bộ tiêu chí đã thẩm định từ HSMT. Tự động kiểm tra thời hạn bảo lãnh, ngày ký ủy quyền, con dấu đỏ và cảnh báo các điểm mâu thuẫn.")

    # Banner thông báo bộ tiêu chí đang áp dụng
    if st.session_state.criteria_list:
        st.success(f"📌 Đang áp dụng Bộ tiêu chí thẩm định từ gói thầu: **{st.session_state.criteria_list.package_name}** ({len(st.session_state.criteria_list.criteria)} tiêu chí)")
    else:
        st.warning("⚠️ Chưa có Bộ tiêu chí từ phần Thẩm định HSMT. Bạn có thể bấm Thẩm định HSMT ở Phần 2 trước, hoặc hệ thống sẽ tự động dùng bộ tiêu chí từ HSMT mẫu khi bấm Thẩm định HSDT.")

    col_hsdt_left, col_hsdt_right = st.columns([2, 1], gap="medium")
    
    with col_hsdt_left:
        source_hsdt = st.radio(
            "Nguồn dữ liệu HSDT:",
            ["Dùng file HSDT mẫu (Công ty CP ĐTXD Sao Việt: 1 Đạt, 1 Bảo lãnh thiếu ngày, 1 Giấy ủy quyền mờ dấu)", "Tải lên file HSDT (PDF hoặc JSON)"],
            horizontal=True
        )

        hsdt_to_process = None
        if source_hsdt.startswith("Dùng file HSDT mẫu"):
            sample_hsdt_path = settings.hsdt_dir / "hsdt_sample.json"
            if sample_hsdt_path.exists():
                hsdt_to_process = ParsedDocument.model_validate_json(sample_hsdt_path.read_text(encoding="utf-8"))
                st.success(f"Đã nạp file mẫu: `{hsdt_to_process.file_name}` — Nhà thầu: **{hsdt_to_process.metadata.bidder_name}**")
        else:
            uploaded_hsdt = st.file_uploader("Chọn file HSDT (hỗ trợ .pdf hoặc .json)", type=["pdf", "json"], key="uploader_hsdt")
            if uploaded_hsdt:
                try:
                    if uploaded_hsdt.name.lower().endswith(".pdf"):
                        with st.spinner("Đang chuyển đổi PDF HSDT sang ParsedDocument..."):
                            hsdt_to_process = convert_pdf_to_parsed_document(
                                pdf_source=uploaded_hsdt.read(),
                                doc_role=DocRole.HSDT,
                                file_name=uploaded_hsdt.name
                            )
                        st.success(f"✅ Đã chuyển đổi PDF HSDT thành công! Nhà thầu: **{hsdt_to_process.metadata.bidder_name or 'Chưa xác định'}** ({len(hsdt_to_process.sections)} phân đoạn)")
                    else:
                        content_str = uploaded_hsdt.read().decode("utf-8")
                        hsdt_to_process = ParsedDocument.model_validate_json(content_str)
                        st.success(f"Nạp thành công: `{hsdt_to_process.file_name}` (Nhà thầu: {hsdt_to_process.metadata.bidder_name})")

                    if hsdt_to_process:
                        with st.expander("👁️ Xem các thành phần HSDT vừa bóc tách:"):
                            for s in hsdt_to_process.sections[:6]:
                                sig_status = "✍️ Có chữ ký/dấu" if (s.visual_cues and (s.visual_cues.has_signature or s.visual_cues.has_red_stamp)) else "Chưa phát hiện dấu"
                                st.markdown(f"- **{s.heading}** (Trang {s.page_start}) — *{sig_status}*")
                except Exception as e:
                    st.error(f"Lỗi cú pháp file HSDT: {e}")

    with col_hsdt_right:
        st.write("")
        st.write("")
        if st.button("🔍 Bắt đầu Thẩm định HSDT", type="primary", use_container_width=True):
            if not hsdt_to_process:
                st.warning("Vui lòng nạp Hồ sơ dự thầu trước khi thẩm định!")
            else:
                with st.spinner("Đang chạy Deterministic Rules, GraphRAG và LLM Gateway..."):
                    try:
                        active_criteria = st.session_state.criteria_list
                        active_hsmt = st.session_state.hsmt_doc
                        
                        # Nếu chưa có criteria_list, tự động thẩm định HSMT mẫu
                        if not active_criteria:
                            sample_hsmt = ParsedDocument.model_validate_json(
                                (settings.hsmt_dir / "hsmt_sample.json").read_text(encoding="utf-8")
                            )
                            active_criteria, _ = review_hsmt(sample_hsmt, provider=provider_option, **llm_kwargs)
                            active_hsmt = sample_hsmt
                            st.session_state.criteria_list = active_criteria
                            st.session_state.hsmt_doc = active_hsmt
                        
                        rep_hsdt = check_hsdt(
                            hsdt_doc=hsdt_to_process,
                            criteria_list=active_criteria,
                            hsmt_doc=active_hsmt,
                            provider=provider_option,
                            **llm_kwargs
                        )
                        st.session_state.hsdt_report = rep_hsdt
                        st.success("Thẩm định HSDT hoàn tất!")
                    except Exception as e:
                        st.error(f"Lỗi khi thẩm định HSDT: {e}")

    # Hiển thị kết quả Thẩm định HSDT
    if st.session_state.hsdt_report:
        rep_h: VerificationReport = st.session_state.hsdt_report
        st.divider()
        st.markdown(f"### Báo cáo Thẩm tra Nhà thầu: {rep_h.target_entity_name}")
        st.info(f"**Kết luận tổng quan:** {rep_h.overall_summary}")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Tổng số tiêu chí", rep_h.total_criteria)
        col2.metric("Đạt (Hợp lệ)", rep_h.valid_count)
        col3.metric("Không đạt (Vi phạm)", rep_h.invalid_count, delta=f"-{rep_h.invalid_count}" if rep_h.invalid_count > 0 else 0, delta_color="inverse")
        col4.metric("Cần làm rõ (Chưa đủ căn cứ)", rep_h.insufficient_count)

        # Bảng Ma trận Tuân thủ (Compliance Matrix)
        st.subheader("📊 Ma trận Tuân thủ (Compliance Matrix)")
        matrix_rows = []
        for a in rep_h.assessments:
            badge_label = "🟢 ĐẠT (HỢP LỆ)" if a.status == ComplianceStatus.VALID else ("🔴 KHÔNG ĐẠT" if a.status == ComplianceStatus.INVALID else "🟡 CẦN LÀM RÕ")
            matrix_rows.append({
                "Mã tiêu chí": a.criterion_id,
                "Tiêu chí thẩm định": a.criterion_name,
                "Kết quả sơ bộ": badge_label,
                "Yếu tố xác thực (Dấu/Chữ ký)": a.evidences[0].visual_check_note if a.evidences else "N/A",
                "Đề xuất chuyên viên": a.recommendation
            })
        st.dataframe(matrix_rows, use_container_width=True)

        # Chi tiết từng tiêu chí
        st.subheader("🔍 Chi tiết Bằng chứng, Lập luận & Khuyến nghị làm rõ:")
        for idx, a in enumerate(rep_h.assessments, 1):
            badge = "🟢 ĐẠT" if a.status == ComplianceStatus.VALID else ("🔴 KHÔNG ĐẠT" if a.status == ComplianceStatus.INVALID else "🟡 CẦN LÀM RÕ")
            with st.expander(f"{idx}. {a.criterion_name} — {badge}", expanded=(a.status != ComplianceStatus.VALID)):
                st.write(f"**Yêu cầu HSMT:** {a.requirement_summary}")
                
                if a.evidences:
                    ev = a.evidences[0]
                    st.markdown(f"<div class='evidence-box'><b>Trích dẫn bằng chứng từ HSDT (Trang {ev.page_number}):</b><br/><i>\"{ev.extracted_quote}\"</i><br/><br/><b>Kiểm tra thực thể vật lý:</b> {ev.visual_check_note}</div>", unsafe_allow_html=True)
                
                st.markdown(f"**Phân tích & Lập luận của AI Reviewer:**\n{a.reasoning}")
                
                if a.missing_or_unclear_points:
                    st.error(f"**Điểm vi phạm / Thiếu căn cứ:** {'; '.join(a.missing_or_unclear_points)}")
                
                st.warning(f"**Đề xuất nội dung gửi nhà thầu giải trình / làm rõ:**\n{a.recommendation}")
                
                if a.references:
                    with st.expander(f"📚 Xem Căn cứ Pháp lý đối chiếu từ GraphRAG ({len(a.references)} điều khoản)", expanded=False):
                        st.caption("💡 *Cuộn chuột trong khung bên dưới để tra cứu các điều khoản:*")
                        with st.container(height=220, border=True):
                            for r_idx, r in enumerate(a.references, 1):
                                st.markdown(f"**{r_idx}. {r.law_name} ({r.clause_id})**")
                                st.markdown(f"- *Nội dung quy định:* {r.summary}")
                                if r.expansion_path:
                                    st.markdown(f"- *Đường đi giải trình:* `{r.expansion_path}`")
                                if r.evidence_text:
                                    st.caption(f"- *Căn cứ dẫn chiếu:* {r.evidence_text}")
                                if r_idx < len(a.references):
                                    st.divider()
