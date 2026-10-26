import json
import sys
from pathlib import Path

# Đảm bảo thư mục gốc dự án luôn nằm trong sys.path khi chạy bằng streamlit
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st

from src.schemas.document import ParsedDocument
from src.schemas.criteria import CriteriaList
from src.schemas.report import ComplianceStatus, VerificationReport
from src.graph_rag.indexer import build_law_index
from src.graph_rag.retriever import retrieve_legal_context
from src.engines.hsmt_reviewer import review_hsmt
from src.engines.hsdt_checker import check_hsdt
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
        color: #1e3a8a;
        margin-bottom: 2px;
    }
    .sub-header {
        font-size: 14px;
        color: #475569;
        margin-bottom: 16px;
    }
    .section-card {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
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
        background-color: #ffffff;
        border-left: 4px solid #2563eb;
        padding: 10px 14px;
        border-radius: 4px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        margin-top: 8px;
        margin-bottom: 8px;
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
            type="password"
        )
        model_name_input = st.text_input(
            "Gemini Model",
            value=settings.gemini_model
        )
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
    st.caption("Phiên bản: Demo MVP 1.0\nKiến trúc: Hybrid (GraphRAG + Rule Engine + LLM)")

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
st.markdown("<div class='sub-header'>Thẩm định tính hợp pháp của HSMT và kiểm tra tính tuân thủ pháp lý của HSDT theo Luật Đấu thầu & Luật Đất đai</div>", unsafe_allow_html=True)

# ----------------- 2 PHẦN LỚN CỦA HỆ THỐNG -----------------
main_tab1, main_tab2 = st.tabs([
    "🗄️ PHẦN 1: KHO DỮ LIỆU",
    "⚖️ PHẦN 2: THẨM ĐỊNH HSDT"
])

# =========================================================
# PHẦN 1: KHO DỮ LIỆU
# =========================================================
with main_tab1:
    st.info("💡 **Kho Dữ liệu:** Nơi lưu trữ, lập chỉ mục đồ thị tri thức Luật (GraphRAG) và thực hiện thẩm định tính hợp pháp của Hồ sơ mời thầu (HSMT) làm cơ sở đánh giá.")
    
    subtab_law, subtab_hsmt = st.tabs([
        "📜 1. Dữ liệu Luật & GraphRAG",
        "📋 2. Thẩm định HSMT"
    ])
    
    # ---------- 1. DỮ LIỆU LUẬT & GRAPHRAG ----------
    with subtab_law:
        st.subheader("1. Quản lý Dữ liệu Luật & Dựng Đồ thị Tri thức (GraphRAG)")
        st.write("Nạp các văn bản quy phạm pháp luật (Luật Đấu thầu, Luật Đất đai...), bóc tách các điều khoản và dựng đồ thị liên kết tham chiếu (REFERENCES).")

        col_law_left, col_law_right = st.columns([1, 1], gap="medium")
        
        with col_law_left:
            st.markdown("#### 📥 Tải lên & Nạp văn bản Luật")
            source_law = st.radio(
                "Chọn nguồn dữ liệu Luật:",
                ["Sử dụng CSDL Luật mẫu có sẵn (data/mock_law)", "Tải lên file JSON văn bản Luật mới"],
                horizontal=False
            )
            
            uploaded_law_doc = None
            if source_law.startswith("Tải lên"):
                uploaded_file = st.file_uploader("Chọn file JSON văn bản Luật (theo ParsedDocument Schema)", type=["json"], key="uploader_law")
                if uploaded_file:
                    try:
                        content_str = uploaded_file.read().decode("utf-8")
                        uploaded_law_doc = ParsedDocument.model_validate_json(content_str)
                        st.success(f"File hợp lệ: {uploaded_law_doc.file_name} ({len(uploaded_law_doc.sections)} điều khoản)")
                        if st.button("💾 Lưu vào thư mục `data/mock_law/`"):
                            save_target = settings.law_dir / f"{uploaded_law_doc.doc_id}.json"
                            with open(save_target, "w", encoding="utf-8") as f:
                                f.write(content_str)
                            st.success(f"Đã lưu văn bản vào `{save_target.name}` thành công!")
                    except Exception as e:
                        st.error(f"Lỗi kiểm tra schema file JSON: {e}")
            else:
                existing_laws = list(settings.law_dir.glob("*.json"))
                st.caption(f"📁 Thư mục `data/mock_law/` hiện có **{len(existing_laws)}** file văn bản luật:")
                for lf in existing_laws:
                    st.text(f" - {lf.name}")

            st.write("")
            if st.button("🔄 Dựng / Cập nhật Đồ thị Tri thức (GraphRAG)", type="primary", use_container_width=True):
                with st.spinner("Đang phân tích các liên kết tham chiếu và lập chỉ mục Vector/Graph..."):
                    res = build_law_index()
                    st.session_state.last_graph_stats = res
                    st.success(f"Hoàn thành! Đã nạp {res['total_nodes']} điều khoản và phát hiện {res['total_edges']} liên kết tham chiếu.")

        with col_law_right:
            st.markdown("#### 📊 Trạng thái Đồ thị Tri thức")
            if st.session_state.last_graph_stats:
                stats = st.session_state.last_graph_stats
                m1, m2, m3 = st.columns(3)
                m1.metric("Văn bản luật", stats.get("total_documents", 1))
                m2.metric("Điều khoản (Nodes)", stats.get("total_nodes", 3))
                m3.metric("Liên kết tham chiếu (Edges)", stats.get("total_edges", 1))
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
                            tag = "📌 Khớp trực tiếp" if item.get("relation_type") == "DIRECT_MATCH" else "🔗 Dẫn chiếu qua đồ thị (1-Hop)"
                            with st.expander(f"{idx}. {item.get('clause_id')} ({tag})"):
                                st.caption(f"Nguồn: {item.get('law_name')} (Trang {item.get('page_number')})")
                                st.markdown(item.get("content_markdown"))

    # ---------- 2. THẨM ĐỊNH HSMT ----------
    with subtab_hsmt:
        st.subheader("2. Thẩm định Hồ sơ Mời thầu (HSMT)")
        st.write("Tải lên HSMT, bóc tách danh mục tiêu chí và đối chiếu với GraphRAG Luật để phát hiện các quy định vi phạm trần luật hoặc cài cắm hạn chế nhà thầu.")

        col_hsmt_input, col_hsmt_action = st.columns([2, 1], gap="medium")
        with col_hsmt_input:
            source_hsmt = st.radio(
                "Nguồn dữ liệu HSMT:",
                ["Dùng file HSMT mẫu (Dự án Khu đô thị mới Bắc Sông Hồng - Cài 1 tiêu chí bảo lãnh 5%)", "Tải lên file JSON HSMT"],
                horizontal=True
            )

            hsmt_to_process = None
            if source_hsmt.startswith("Dùng file HSMT mẫu"):
                sample_path = settings.hsmt_dir / "hsmt_sample.json"
                if sample_path.exists():
                    hsmt_to_process = ParsedDocument.model_validate_json(sample_path.read_text(encoding="utf-8"))
                    st.success(f"Đã nạp file mẫu: `{hsmt_to_process.file_name}` — Gói thầu: **{hsmt_to_process.metadata.bidding_package_name}**")
            else:
                uploaded_hsmt = st.file_uploader("Chọn file JSON HSMT theo ParsedDocument Schema", type=["json"], key="uploader_hsmt")
                if uploaded_hsmt:
                    try:
                        content_str = uploaded_hsmt.read().decode("utf-8")
                        hsmt_to_process = ParsedDocument.model_validate_json(content_str)
                        st.success(f"Nạp thành công: `{hsmt_to_process.file_name}`")
                    except Exception as e:
                        st.error(f"Lỗi đọc file HSMT: {e}")

        with col_hsmt_action:
            st.write("")
            st.write("")
            if st.button("🚀 Bắt đầu Thẩm định HSMT", type="primary", use_container_width=True):
                if not hsmt_to_process:
                    st.warning("Vui lòng chọn hoặc tải lên file HSMT trước!")
                else:
                    with st.spinner("Đang bóc tách tiêu chí và đối chiếu GraphRAG Luật..."):
                        crit_list, rep = review_hsmt(hsmt_to_process, provider=provider_option, **llm_kwargs)
                        st.session_state.criteria_list = crit_list
                        st.session_state.hsmt_doc = hsmt_to_process
                        st.session_state.hsmt_report = rep
                        st.success("Thẩm định HSMT hoàn tất! Bộ tiêu chí đã được lưu để sẵn sàng chuyển sang thẩm định HSDT.")

        # Hiển thị kết quả thẩm định HSMT nếu có
        if st.session_state.hsmt_report:
            rep: VerificationReport = st.session_state.hsmt_report
            st.divider()
            st.markdown(f"### Kết quả Thẩm định: {rep.package_name}")
            st.info(f"**Tóm lược tổng thể:** {rep.overall_summary}")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Tổng số tiêu chí", rep.total_criteria)
            c2.metric("Hợp lệ", rep.valid_count)
            c3.metric("Trái luật / Cài cắm", rep.invalid_count, delta=f"-{rep.invalid_count}" if rep.invalid_count > 0 else 0, delta_color="inverse")
            c4.metric("Cần làm rõ", rep.insufficient_count)

            st.subheader("Chi tiết đánh giá tiêu chí HSMT:")
            for idx, a in enumerate(rep.assessments, 1):
                badge = "🟢 HỢP LỆ" if a.status == ComplianceStatus.VALID else ("🔴 TRÁI LUẬT / CÀI CẮM" if a.status == ComplianceStatus.INVALID else "🟡 CẦN LÀM RÕ")
                with st.expander(f"{idx}. {a.criterion_name} — {badge}", expanded=(a.status != ComplianceStatus.VALID)):
                    st.write(f"**Yêu cầu tóm tắt trong HSMT:** {a.requirement_summary}")
                    
                    if a.evidences:
                        ev = a.evidences[0]
                        st.markdown(f"<div class='evidence-box'><b>Trích xuất nguyên văn (Trang {ev.page_number}):</b><br/><i>\"{ev.extracted_quote}\"</i></div>", unsafe_allow_html=True)
                    
                    st.markdown(f"**Lập luận pháp lý:** {a.reasoning}")
                    
                    if a.missing_or_unclear_points:
                        st.error(f"**Điểm vi phạm / Cài cắm:** {'; '.join(a.missing_or_unclear_points)}")
                    
                    st.warning(f"**Khuyến nghị cho Bên mời thầu:** {a.recommendation}")
                    
                    if a.references:
                        st.markdown("**Căn cứ pháp lý đối chiếu từ GraphRAG:**")
                        for r in a.references:
                            st.caption(f"- **{r.law_name} ({r.clause_id})**: {r.summary}")


# =========================================================
# PHẦN 2: THẨM ĐỊNH HSDT
# =========================================================
with main_tab2:
    st.subheader("Thẩm định Hồ sơ Dự thầu (HSDT) & Lập Ma trận Tuân thủ")
    st.write("Đối chiếu chi tiết Hồ sơ dự thầu của nhà thầu với Bộ tiêu chí đã thẩm định từ HSMT. Tự động kiểm tra thời hạn bảo lãnh, ngày ký ủy quyền, con dấu đỏ và cảnh báo các điểm mâu thuẫn.")

    # Banner thông báo bộ tiêu chí đang áp dụng
    if st.session_state.criteria_list:
        st.success(f"📌 Đang áp dụng Bộ tiêu chí thẩm định từ gói thầu: **{st.session_state.criteria_list.package_name}** ({len(st.session_state.criteria_list.criteria)} tiêu chí)")
    else:
        st.warning("⚠️ Chưa có Bộ tiêu chí từ phần Thẩm định HSMT. Bạn có thể bấm Thẩm định HSMT ở Phần 1 trước, hoặc hệ thống sẽ tự động dùng bộ tiêu chí từ HSMT mẫu khi bấm Thẩm định HSDT.")

    col_hsdt_left, col_hsdt_right = st.columns([2, 1], gap="medium")
    
    with col_hsdt_left:
        source_hsdt = st.radio(
            "Nguồn dữ liệu HSDT:",
            ["Dùng file HSDT mẫu (Công ty CP ĐTXD Sao Việt: 1 Đạt, 1 Bảo lãnh thiếu ngày, 1 Giấy ủy quyền mờ dấu)", "Tải lên file JSON HSDT"],
            horizontal=True
        )

        hsdt_to_process = None
        if source_hsdt.startswith("Dùng file HSDT mẫu"):
            sample_hsdt_path = settings.hsdt_dir / "hsdt_sample.json"
            if sample_hsdt_path.exists():
                hsdt_to_process = ParsedDocument.model_validate_json(sample_hsdt_path.read_text(encoding="utf-8"))
                st.success(f"Đã nạp file mẫu: `{hsdt_to_process.file_name}` — Nhà thầu: **{hsdt_to_process.metadata.bidder_name}**")
        else:
            uploaded_hsdt = st.file_uploader("Chọn file JSON HSDT theo ParsedDocument Schema", type=["json"], key="uploader_hsdt")
            if uploaded_hsdt:
                try:
                    content_str = uploaded_hsdt.read().decode("utf-8")
                    hsdt_to_process = ParsedDocument.model_validate_json(content_str)
                    st.success(f"Nạp thành công: `{hsdt_to_process.file_name}` (Nhà thầu: {hsdt_to_process.metadata.bidder_name})")
                except Exception as e:
                    st.error(f"Lỗi cú pháp file JSON HSDT: {e}")

    with col_hsdt_right:
        st.write("")
        st.write("")
        if st.button("🔍 Bắt đầu Thẩm định HSDT", type="primary", use_container_width=True):
            if not hsdt_to_process:
                st.warning("Vui lòng nạp Hồ sơ dự thầu trước khi thẩm định!")
            else:
                with st.spinner("Đang chạy Deterministic Rules, GraphRAG và LLM Gateway..."):
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
                    st.markdown("**Căn cứ pháp lý đối chiếu từ GraphRAG:**")
                    for r in a.references:
                        st.caption(f"- **{r.law_name} ({r.clause_id})**: {r.summary}")
