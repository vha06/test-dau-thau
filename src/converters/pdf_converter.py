import io
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Union, BinaryIO, Optional, List, Dict, Any

from pypdf import PdfReader

from src.schemas.document import (
    DocRole,
    DocCategory,
    ParsedDocument,
    DocumentSection,
    DocumentMetadata,
    VisualCues,
    TableItem,
)

logger = logging.getLogger(__name__)


def _clean_text(text: str) -> str:
    """Loại bỏ ký tự rác và chuẩn hóa khoảng trắng."""
    if not text:
        return ""
    # Chuẩn hóa Unicode
    text = unicodedata.normalize("NFC", text)
    # Loại bỏ null bytes
    text = text.replace("\x00", "")
    return text.strip()


def _slugify(text: str) -> str:
    """Tạo mã định danh an toàn từ tên file hoặc tiêu đề."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().upper()
    return re.sub(r"[-\s]+", "_", text)[:50]


def _detect_visual_cues(text: str, page_number: int) -> Optional[VisualCues]:
    """Phát hiện dấu hiệu chữ ký và con dấu pháp nhân từ nội dung văn bản."""
    sig_patterns = [
        r"(?:ký\s+(?:tên|bởi)|người\s+đại\s+diện|giám\s+đốc|tổng\s+giám\s+đốc|thẩm\s+quyền|chữ\s+ký\s+số|signed\s+by)",
        r"(?:đã\s+ký|chức\s+vụ|phó\s+tổng\s+giám\s+đốc|đại\s+diện\s+hợp\s+pháp)"
    ]
    stamp_patterns = [
        r"(?:con\s+dấu|dấu\s+đỏ|đóng\s+dấu|mst\s*:|mã\s+số\s+thuế)",
        r"(?:công\s+ty\s+(?:cổ\s+phần|tnhh)|chi\s+nhánh\s+ngân\s+hàng|ngân\s+hàng\s+thương\s+mại)"
    ]

    has_sig = any(re.search(pat, text, re.IGNORECASE) for pat in sig_patterns)
    has_stamp = any(re.search(pat, text, re.IGNORECASE) for pat in stamp_patterns)

    stamp_text = None
    if has_stamp:
        # Thử trích xuất dòng tên công ty/ngân hàng gần chữ ký
        comp_match = re.search(r"(CÔNG TY [^\n\r]{10,80}|NGÂN HÀNG [^\n\r]{10,80})", text, re.IGNORECASE)
        if comp_match:
            stamp_text = comp_match.group(1).strip()
        else:
            stamp_text = "Phát hiện thông tin pháp nhân và con dấu trong văn bản"

    if has_sig or has_stamp:
        return VisualCues(
            has_signature=has_sig,
            has_red_stamp=has_stamp,
            stamp_text_ocr=stamp_text,
            page_numbers=[page_number]
        )
    return None


def _extract_metadata_from_text(full_text: str, role: DocRole) -> DocumentMetadata:
    """Trích xuất tự động một số trường thông tin định lượng từ văn bản."""
    meta = DocumentMetadata()

    # Tìm tên gói thầu / dự án
    pkg_match = re.search(
        r"(?:Gói\s+thầu|Dự\s+án|gói\s+thầu|dự\s+án)\s*[:：]\s*([^\n\r;]{5,120})",
        full_text,
        re.IGNORECASE
    )
    if pkg_match:
        meta.bidding_package_name = pkg_match.group(1).strip()

    # Tìm tên nhà thầu
    bidder_match = re.search(
        r"(?:Nhà\s+thầu|nhà\s+thầu|Chúng\s+tôi\s*[-–,]\s*)(CÔNG TY [^\n\r;]{5,100})",
        full_text,
        re.IGNORECASE
    )
    if bidder_match:
        meta.bidder_name = bidder_match.group(1).strip()

    # Tìm ngày đóng thầu
    close_match = re.search(
        r"(?:đóng\s+thầu|thời\s+điểm\s+đóng\s+thầu)[^\d]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        full_text,
        re.IGNORECASE
    )
    if close_match:
        d_str = close_match.group(1).replace("-", "/")
        parts = d_str.split("/")
        meta.bid_close_date = f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"

    # Tìm ngày ký / nộp
    sub_match = re.search(
        r"(?:Ngày\s+ký\s+đơn|ngày\s+ký|ngày\s+nộp)[^\d]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        full_text,
        re.IGNORECASE
    )
    if sub_match:
        d_str = sub_match.group(1).replace("-", "/")
        parts = d_str.split("/")
        meta.submission_date = f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"

    return meta


def _segment_law_document(
    pages_text: List[Dict[str, Any]],
    doc_id: str
) -> List[DocumentSection]:
    """
    Phân mảnh văn bản Luật theo Điều/Khoản:
    Regex bắt các dạng: 'Điều 1.', 'Điều 14. Bảo đảm dự thầu...', 'ĐIỀU 2...'
    """
    sections: List[DocumentSection] = []
    current_sec_id = None
    current_heading = ""
    current_lines = []
    current_start_page = 1
    current_end_page = 1
    current_parent_id = None

    chapter_pattern = re.compile(r"^(?:CHƯƠNG|Chương)\s+([IVXLCDM\d]+)[.:\s]*(.*)$", re.IGNORECASE)
    article_pattern = re.compile(r"^(?:ĐIỀU|Điều)\s+(\d+[a-zA-Z0-9\.]*)[.:\s]*(.*)$", re.IGNORECASE)

    for p_info in pages_text:
        page_num = p_info["page_number"]
        lines = p_info["lines"]

        for line in lines:
            chap_m = chapter_pattern.match(line)
            if chap_m:
                current_parent_id = f"CHUONG_{chap_m.group(1).upper()}"

            art_m = article_pattern.match(line)
            if art_m:
                # Đóng section trước đó nếu có
                if current_sec_id:
                    content_md = "\n".join(current_lines).strip()
                    vc = _detect_visual_cues(content_md, current_end_page)
                    sections.append(DocumentSection(
                        section_id=current_sec_id,
                        parent_id=current_parent_id,
                        heading=current_heading,
                        page_start=current_start_page,
                        page_end=current_end_page,
                        content_markdown=content_md,
                        visual_cues=vc
                    ))
                
                # Mở section mới
                art_num = art_m.group(1).replace(".", "_")
                current_sec_id = f"DIEU_{art_num}"
                current_heading = line
                current_lines = [line]
                current_start_page = page_num
                current_end_page = page_num
            else:
                if current_sec_id:
                    current_lines.append(line)
                    current_end_page = page_num
                else:
                    # Phần mở đầu trước Điều 1 (Lệnh công bố, căn cứ ban hành)
                    if not current_heading:
                        current_sec_id = "CAN_CU_BAN_HANH"
                        current_heading = "Căn cứ pháp lý & Ban hành"
                        current_start_page = page_num
                    current_lines.append(line)
                    current_end_page = page_num

    # Đóng section cuối cùng
    if current_sec_id and current_lines:
        content_md = "\n".join(current_lines).strip()
        vc = _detect_visual_cues(content_md, current_end_page)
        sections.append(DocumentSection(
            section_id=current_sec_id,
            parent_id=current_parent_id,
            heading=current_heading,
            page_start=current_start_page,
            page_end=current_end_page,
            content_markdown=content_md,
            visual_cues=vc
        ))

    return sections


def _segment_hsmt_document(
    pages_text: List[Dict[str, Any]],
    doc_id: str
) -> List[DocumentSection]:
    """Phân mảnh HSMT theo Chương, Mục và các Yêu cầu tiêu chí."""
    sections: List[DocumentSection] = []
    current_sec_id = None
    current_heading = ""
    current_lines = []
    current_start_page = 1
    current_end_page = 1
    current_parent = None

    header_patterns = [
        re.compile(r"^(?:CHƯƠNG|Chương)\s+([IVXLCDM\d]+)[.:\s]*(.*)$", re.IGNORECASE),
        re.compile(r"^(?:MỤC|Mục|PHẦN|Phần)\s+(\d+|[IVXLCDM]+)[.:\s]*(.*)$", re.IGNORECASE),
        re.compile(r"^(?:ĐIỀU|Điều)\s+(\d+[a-zA-Z0-9\.]*)[.:\s]*(.*)$", re.IGNORECASE),
        re.compile(r"^(?:Yêu\s+cầu|Tiêu\s+chuẩn\s+đánh\s+giá|Bảo\s+đảm\s+dự\s+thầu|Tư\s+cách\s+hợp\s+lệ|Đơn\s+dự\s+thầu|Năng\s+lực\s+tài\s+chính).*$", re.IGNORECASE)
    ]

    sec_counter = 1
    for p_info in pages_text:
        page_num = p_info["page_number"]
        lines = p_info["lines"]

        for line in lines:
            is_header = any(pat.match(line) for pat in header_patterns)
            if is_header and len(line) < 150:
                if current_sec_id and len(current_lines) > 1:
                    content_md = "\n".join(current_lines).strip()
                    vc = _detect_visual_cues(content_md, current_end_page)
                    sections.append(DocumentSection(
                        section_id=current_sec_id,
                        parent_id=current_parent,
                        heading=current_heading,
                        page_start=current_start_page,
                        page_end=current_end_page,
                        content_markdown=content_md,
                        visual_cues=vc
                    ))
                
                current_sec_id = f"HSMT_SEC_{sec_counter:02d}"
                sec_counter += 1
                current_heading = line
                current_lines = [line]
                current_start_page = page_num
                current_end_page = page_num
            else:
                if not current_sec_id:
                    current_sec_id = f"HSMT_SEC_{sec_counter:02d}"
                    sec_counter += 1
                    current_heading = "Thông tin chung HSMT"
                    current_start_page = page_num
                current_lines.append(line)
                current_end_page = page_num

    if current_sec_id and current_lines:
        content_md = "\n".join(current_lines).strip()
        vc = _detect_visual_cues(content_md, current_end_page)
        sections.append(DocumentSection(
            section_id=current_sec_id,
            parent_id=current_parent,
            heading=current_heading,
            page_start=current_start_page,
            page_end=current_end_page,
            content_markdown=content_md,
            visual_cues=vc
        ))

    return sections


def _segment_hsdt_document(
    pages_text: List[Dict[str, Any]],
    doc_id: str
) -> List[DocumentSection]:
    """Phân mảnh HSDT theo từng thành phần hồ sơ: Đơn dự thầu, Bảo lãnh, Giấy ủy quyền..."""
    sections: List[DocumentSection] = []
    
    bidding_parts = [
        (re.compile(r"(?:ĐƠN\s+DỰ\s+THẦU|Đơn\s+dự\s+thầu)", re.IGNORECASE), "DON_DU_THAU", "Đơn dự thầu"),
        (re.compile(r"(?:BẢO\s+LÃNH\s+DỰ\s+THẦU|THƯ\s+BẢO\s+LÃNH|Bảo\s+đảm\s+dự\s+thầu)", re.IGNORECASE), "BAO_LANH_DU_THAU", "Thư bảo lãnh dự thầu"),
        (re.compile(r"(?:GIẤY\s+ỦY\s+QUYỀN|Giấy\s+ủy\s+quyền|VĂN\s+BẢN\s+ỦY\s+QUYỀN)", re.IGNORECASE), "GIAY_UY_QUYEN", "Giấy ủy quyền tham gia dự thầu"),
        (re.compile(r"(?:THỎA\s+THUẬN\s+LIÊN\s+DANH|Thỏa\s+thuận\s+liên\s+danh)", re.IGNORECASE), "THOA_THUAN_LIEN_DANH", "Thỏa thuận liên danh"),
        (re.compile(r"(?:ĐĂNG\s+KÝ\s+KINH\s+DOANH|ĐĂNG\s+KÝ\s+DOANH\s+NGHIỆP)", re.IGNORECASE), "DANG_KY_KINH_DOANH", "Giấy chứng nhận đăng ký kinh doanh"),
        (re.compile(r"(?:BÁO\s+CÁO\s+TÀI\s+CHÍNH|Báo\s+cáo\s+tài\s+chính)", re.IGNORECASE), "BAO_CAO_TAI_CHINH", "Báo cáo tài chính"),
        (re.compile(r"(?:HỢP\s+ĐỒNG\s+TƯƠNG\s+TỰ|Hợp\s+đồng\s+tương\s+tự)", re.IGNORECASE), "HOP_DONG_TUONG_TU", "Hợp đồng tương tự"),
        (re.compile(r"(?:NHÂN\s+SỰ\s+CHỦ\s+CHỐT|Nhân\s+sự\s+chủ\s+chốt)", re.IGNORECASE), "NHAN_SU_CHU_CHOT", "Danh sách nhân sự chủ chốt"),
    ]

    current_sec_id = None
    current_heading = ""
    current_lines = []
    current_start_page = 1
    current_end_page = 1
    sec_counter = 1

    for p_info in pages_text:
        page_num = p_info["page_number"]
        lines = p_info["lines"]

        for line in lines:
            matched_part = None
            for pat, cat_code, default_title in bidding_parts:
                if pat.search(line) and len(line) < 120:
                    matched_part = (cat_code, line.strip())
                    break

            if matched_part:
                if current_sec_id and len(current_lines) > 1:
                    content_md = "\n".join(current_lines).strip()
                    vc = _detect_visual_cues(content_md, current_end_page)
                    sections.append(DocumentSection(
                        section_id=current_sec_id,
                        heading=current_heading,
                        page_start=current_start_page,
                        page_end=current_end_page,
                        content_markdown=content_md,
                        visual_cues=vc
                    ))
                
                cat_code, title = matched_part
                current_sec_id = f"HSDT_{cat_code}_{sec_counter:02d}"
                sec_counter += 1
                current_heading = title
                current_lines = [line]
                current_start_page = page_num
                current_end_page = page_num
            else:
                if not current_sec_id:
                    current_sec_id = f"HSDT_SEC_{sec_counter:02d}"
                    sec_counter += 1
                    current_heading = "Hồ sơ dự thầu chung"
                    current_start_page = page_num
                current_lines.append(line)
                current_end_page = page_num

    if current_sec_id and current_lines:
        content_md = "\n".join(current_lines).strip()
        vc = _detect_visual_cues(content_md, current_end_page)
        sections.append(DocumentSection(
            section_id=current_sec_id,
            heading=current_heading,
            page_start=current_start_page,
            page_end=current_end_page,
            content_markdown=content_md,
            visual_cues=vc
        ))

    return sections


def _segment_by_pages(
    pages_text: List[Dict[str, Any]],
    doc_id: str,
    role: DocRole
) -> List[DocumentSection]:
    """Phân mảnh dự phòng theo từng trang nếu không nhận diện được tiêu đề mục."""
    sections: List[DocumentSection] = []
    prefix = "SEC"
    if role == DocRole.LAW:
        prefix = "LAW_PAGE"
    elif role == DocRole.HSMT:
        prefix = "HSMT_PAGE"
    elif role == DocRole.HSDT:
        prefix = "HSDT_PAGE"

    for p_info in pages_text:
        p_num = p_info["page_number"]
        content_md = "\n".join(p_info["lines"]).strip()
        if not content_md:
            continue
        first_line = p_info["lines"][0] if p_info["lines"] else f"Phân đoạn trang {p_num}"
        heading = first_line[:80]
        vc = _detect_visual_cues(content_md, p_num)

        sections.append(DocumentSection(
            section_id=f"{prefix}_{p_num:02d}",
            heading=heading,
            page_start=p_num,
            page_end=p_num,
            content_markdown=content_md,
            visual_cues=vc
        ))
    return sections


def convert_pdf_to_parsed_document(
    pdf_source: Union[str, Path, bytes, BinaryIO],
    doc_role: DocRole = DocRole.LAW,
    doc_category: DocCategory = DocCategory.TONG_HOP,
    file_name: Optional[str] = None,
    doc_id: Optional[str] = None,
    metadata: Optional[DocumentMetadata] = None,
) -> ParsedDocument:
    """
    Chuyển đổi một file PDF thành ParsedDocument JSON chuẩn đầu vào của hệ thống:
    1. Bóc tách text và cấu trúc từng trang qua pypdf
    2. Phân mảnh theo cấu trúc Điều/Khoản (Luật), Mục/Chương (HSMT) hoặc Hồ sơ thành phần (HSDT)
    3. Nhận diện các yếu tố chữ ký, con dấu đỏ (Visual Cues)
    4. Trích xuất metadata định lượng (ngày đóng thầu, số tiền, tên gói thầu)
    """
    # 1. Khởi tạo PdfReader từ nhiều loại đầu vào
    if isinstance(pdf_source, (str, Path)):
        path = Path(pdf_source)
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy file PDF tại: {path}")
        reader = PdfReader(str(path))
        resolved_file_name = file_name or path.name
    elif isinstance(pdf_source, bytes):
        stream = io.BytesIO(pdf_source)
        reader = PdfReader(stream)
        resolved_file_name = file_name or "uploaded_document.pdf"
    elif hasattr(pdf_source, "read"):
        reader = PdfReader(pdf_source)
        resolved_file_name = file_name or getattr(pdf_source, "name", "uploaded_document.pdf")
    else:
        raise ValueError(f"Kiểu dữ liệu đầu vào không hợp lệ: {type(pdf_source)}")

    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ValueError("File PDF rỗng, không có trang nào.")

    # 2. Đọc text từng trang
    pages_text: List[Dict[str, Any]] = []
    full_text_collector = []

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1
        raw_text = page.extract_text() or ""
        cleaned = _clean_text(raw_text)
        lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
        pages_text.append({
            "page_number": page_num,
            "text": cleaned,
            "lines": lines
        })
        if cleaned:
            full_text_collector.append(cleaned)

    all_text = "\n\n".join(full_text_collector)

    # Cảnh báo nếu PDF không có text layer (file scan ảnh thuần)
    if not all_text.strip():
        logger.warning(f"File '{resolved_file_name}' không trích xuất được text layer. Đây có thể là file scan ảnh thuần.")
        # Tạo 1 section giữ chỗ
        empty_sec = DocumentSection(
            section_id="SCAN_PLACEHOLDER",
            heading=f"Văn bản scan ảnh: {resolved_file_name}",
            page_start=1,
            page_end=total_pages,
            content_markdown=f"*Văn bản '{resolved_file_name}' gồm {total_pages} trang scan dạng hình ảnh. Cần chạy OCR để trích xuất toàn văn.*",
            visual_cues=VisualCues(has_signature=True, has_red_stamp=True, stamp_text_ocr="Bản scan con dấu", page_numbers=[total_pages])
        )
        resolved_id = doc_id or f"DOC_{_slugify(resolved_file_name)}"
        return ParsedDocument(
            doc_id=resolved_id,
            doc_role=doc_role,
            doc_category=doc_category,
            file_name=resolved_file_name,
            total_pages=total_pages,
            metadata=metadata or DocumentMetadata(bidding_package_name=resolved_file_name),
            sections=[empty_sec]
        )

    # 3. Phân mảnh theo vai trò văn bản (doc_role)
    if doc_role == DocRole.LAW:
        sections = _segment_law_document(pages_text, resolved_file_name)
    elif doc_role == DocRole.HSMT:
        sections = _segment_hsmt_document(pages_text, resolved_file_name)
    elif doc_role == DocRole.HSDT:
        sections = _segment_hsdt_document(pages_text, resolved_file_name)
    else:
        sections = []

    # Nếu phân đoạn cụ thể không phát hiện được tiêu đề, chuyển sang phân đoạn theo trang
    if len(sections) <= 1 and total_pages > 1:
        fallback_sections = _segment_by_pages(pages_text, resolved_file_name, doc_role)
        if len(fallback_sections) > len(sections):
            sections = fallback_sections

    if not sections:
        sections = _segment_by_pages(pages_text, resolved_file_name, doc_role)

    # 4. Trích xuất metadata
    extracted_meta = _extract_metadata_from_text(all_text, doc_role)
    if metadata:
        # Hợp nhất: ưu tiên metadata truyền từ người dùng
        user_meta_dict = metadata.model_dump(exclude_none=True)
        ext_meta_dict = extracted_meta.model_dump(exclude_none=True)
        ext_meta_dict.update(user_meta_dict)
        final_meta = DocumentMetadata.model_validate(ext_meta_dict)
    else:
        final_meta = extracted_meta

    resolved_id = doc_id or f"{doc_role.value}_{_slugify(resolved_file_name)}"

    return ParsedDocument(
        doc_id=resolved_id,
        doc_role=doc_role,
        doc_category=doc_category,
        file_name=resolved_file_name,
        total_pages=total_pages,
        metadata=final_meta,
        sections=sections
    )


def save_parsed_document_to_json(
    parsed_doc: ParsedDocument,
    output_path: Union[str, Path]
) -> Path:
    """Lưu ParsedDocument ra file JSON chuẩn UTF-8."""
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        f.write(parsed_doc.model_dump_json(indent=2))
    return out_p


def load_parsed_document_from_json(json_path: Union[str, Path]) -> ParsedDocument:
    """Nạp ParsedDocument từ file JSON."""
    p = Path(json_path)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ParsedDocument.model_validate(data)

