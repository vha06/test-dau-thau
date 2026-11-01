import re
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
import networkx as nx

from src.schemas.document import ParsedDocument, DocumentSection

logger = logging.getLogger(__name__)


@dataclass
class CitationMatch:
    raw_text: str
    relation_type: str = "REFERENCES"  # REFERENCES, DETAILS, AMENDS, REPEALS
    doc_type: Optional[str] = None
    doc_number: Optional[str] = None
    article_number: Optional[str] = None
    clause_number: Optional[str] = None
    point_letter: Optional[str] = None
    evidence_text: str = ""


class LegalCitationParser:
    """
    Bộ phân tích và trích xuất dẫn chiếu pháp luật chuyên sâu cho lĩnh vực Đấu thầu:
    - Kế thừa và mở rộng từ Legal Retrieval Lab (test-kg-rag)
    - Nhận diện dẫn chiếu nội bộ (Điều -> Điều)
    - Nhận diện dẫn chiếu chéo văn bản (Luật Đấu thầu -> Nghị định hướng dẫn -> Thông tư)
    - Phát hiện các quan hệ pháp lý: REFERENCES, DETAILS, AMENDS, REPEALS
    """

    # 1. Trích xuất dẫn chiếu điều khoản trong văn bản
    # Ví dụ: "theo quy định tại Điểm a Khoản 2 Điều 14", "tại Điều 89 của Luật Đấu thầu số 22/2023/QH15"
    IN_TEXT_REF_RE = re.compile(
        r"(?:theo\s+quy\s+định\s+tại|quy\s+định\s+tại|căn\s+cứ\s+vào|căn\s+cứ|chiếu\s+theo|tại)\s+"
        r"(?:điểm\s+([a-zđ])\s+)?(?:khoản\s+(\d+)\s+)?điều\s+(\d+[a-z]?)"
        r"(?:\s+(?:của|thuộc)?\s*(luật|bộ\s+luật|nghị\s+định|thông\s+tư|quyết\s+định|văn\s+bản|e-hsmt|hsmt)"
        r"(?:(?:\s+[^\d,\.;\n]+?)?\s*(?:số\s+([\w\/\.\-]+)|này))?)?",
        re.IGNORECASE,
    )

    # 2. Quan hệ Quy định chi tiết / Hướng dẫn thi hành (DETAILS)
    # Ví dụ: "Quy định chi tiết thi hành một số điều của Luật Đấu thầu số 22/2023/QH15"
    DETAILS_RE = re.compile(
        r"(?:quy\s+định\s+chi\s+tiết|hướng\s+dẫn\s+thi\s+hành|hướng\s+dẫn\s+thực\s+hiện)(?:\s+thi\s+hành)?\s+"
        r"(?:một\s+số\s+điều\s+của\s+)?(luật|nghị\s+định|pháp\s+lệnh|quyết\s+định)\s+(?:số\s+)?([\w\/\.\-]+)",
        re.IGNORECASE,
    )

    # 3. Quan hệ Sửa đổi, bổ sung (AMENDS / SUPPLEMENTS)
    # Ví dụ: "Sửa đổi, bổ sung Điều 18 Nghị định số 214/2024/NĐ-CP", "Sửa đổi, bổ sung đoạn đầu của khoản 2 Điều 8 của Luật..."
    AMENDS_RE = re.compile(
        r"(?:sửa\s+đổi,\s+bổ\s+sung|sửa\s+đổi|bổ\s+sung)\s+"
        r"(?:(?:đoạn\s+[^\d,\.;]+?|từ\s+[^\d,\.;]+?|cụm\s+từ\s+[^\d,\.;]+?)\s+của\s+)?"
        r"(?:điểm\s+([a-zđ])\s+)?(?:khoản\s+(\d+)\s+)?(?:của\s+)?điều\s+(\d+[a-z]?)"
        r"(?:\s+(?:của|thuộc)?\s*(luật|bộ\s+luật|nghị\s+định|thông\s+tư)(?:(?:\s+[^\d,\.;]+?)?\s*số\s+([\w\/\.\-]+))?)?",
        re.IGNORECASE,
    )

    # 4. Quan hệ Bãi bỏ (REPEALS)
    # Ví dụ: "Bãi bỏ Khoản 3 Điều 19"
    REPEALS_RE = re.compile(
        r"(?:bãi\s+bỏ|hết\s+hiệu\s+lực)\s+(?:quy\s+định\s+tại\s+)?"
        r"(?:(?:đoạn\s+[^\d,\.;]+?|từ\s+[^\d,\.;]+?|cụm\s+từ\s+[^\d,\.;]+?)\s+của\s+)?"
        r"(?:điểm\s+([a-zđ])\s+)?(?:khoản\s+(\d+)\s+)?(?:của\s+)?điều\s+(\d+[a-z]?)"
        r"(?:\s+(?:của|thuộc)?\s*(luật|bộ\s+luật|nghị\s+định|thông\s+tư)(?:(?:\s+[^\d,\.;]+?)?\s*số\s+([\w\/\.\-]+))?)?",
        re.IGNORECASE,
    )

    # 5. Nhận diện số hiệu văn bản pháp quy chuẩn
    DOC_NUMBER_RE = re.compile(
        r"\b(\d{1,4}(?:\/\d{2,4})?\/(?:QH\d+|NĐ-CP|TT-BKHĐT|TT-BTC|TT-BXD|QĐ-TTg))\b",
        re.IGNORECASE,
    )

    # 6. Trích xuất số Điều tổng quát
    GENERAL_ARTICLE_RE = re.compile(
        r"\bĐiều\s+(\d+[a-zA-Z]?)\b",
        re.IGNORECASE,
    )

    @classmethod
    def clean_doc_number(cls, num_str: Optional[str]) -> Optional[str]:
        if not num_str:
            return None
        cleaned = num_str.strip(" ,.;:()[]{}'\"")
        return cleaned.upper() if cleaned else None

    @classmethod
    def extract_citations(cls, text: str) -> List[CitationMatch]:
        """Trích xuất tất cả các dẫn chiếu pháp luật từ một đoạn văn bản."""
        if not text:
            return []

        citations: List[CitationMatch] = []
        seen_keys = set()

        # 1. Trích xuất DETAILS relations
        for match in cls.DETAILS_RE.finditer(text):
            dtype, dnum = match.groups()
            dnum_clean = cls.clean_doc_number(dnum)
            key = ("DETAILS", dtype.lower(), dnum_clean, None, None)
            if key not in seen_keys:
                seen_keys.add(key)
                start, end = max(0, match.start() - 30), min(len(text), match.end() + 30)
                citations.append(CitationMatch(
                    raw_text=match.group(0),
                    relation_type="DETAILS",
                    doc_type=dtype.strip().title(),
                    doc_number=dnum_clean,
                    evidence_text=text[start:end].strip()
                ))

        # 2. Trích xuất AMENDS relations
        for match in cls.AMENDS_RE.finditer(text):
            pt_num, cl_num, art_num, dtype, dnum = match.groups()
            dnum_clean = cls.clean_doc_number(dnum)
            key = ("AMENDS", dtype.lower() if dtype else None, dnum_clean, art_num, cl_num, pt_num)
            if key not in seen_keys:
                seen_keys.add(key)
                start, end = max(0, match.start() - 30), min(len(text), match.end() + 30)
                citations.append(CitationMatch(
                    raw_text=match.group(0),
                    relation_type="AMENDS",
                    doc_type=dtype.strip().title() if dtype else None,
                    doc_number=dnum_clean,
                    article_number=art_num,
                    clause_number=cl_num,
                    point_letter=pt_num,
                    evidence_text=text[start:end].strip()
                ))

        # 3. Trích xuất REPEALS relations
        for match in cls.REPEALS_RE.finditer(text):
            pt_num, cl_num, art_num, dtype, dnum = match.groups()
            dnum_clean = cls.clean_doc_number(dnum)
            key = ("REPEALS", dtype.lower() if dtype else None, dnum_clean, art_num, cl_num, pt_num)
            if key not in seen_keys:
                seen_keys.add(key)
                start, end = max(0, match.start() - 30), min(len(text), match.end() + 30)
                citations.append(CitationMatch(
                    raw_text=match.group(0),
                    relation_type="REPEALS",
                    doc_type=dtype.strip().title() if dtype else None,
                    doc_number=dnum_clean,
                    article_number=art_num,
                    clause_number=cl_num,
                    point_letter=pt_num,
                    evidence_text=text[start:end].strip()
                ))

        # 4. Trích xuất IN_TEXT_REF_RE (REFERENCES)
        for match in cls.IN_TEXT_REF_RE.finditer(text):
            pt_let, cl_num, art_num, dtype, dnum = match.groups()
            dnum_clean = cls.clean_doc_number(dnum)
            key = ("REFERENCES", dtype.lower() if dtype else None, dnum_clean, art_num, cl_num)
            if key not in seen_keys:
                seen_keys.add(key)
                start, end = max(0, match.start() - 30), min(len(text), match.end() + 30)
                citations.append(CitationMatch(
                    raw_text=match.group(0),
                    relation_type="REFERENCES",
                    doc_type=dtype.strip().title() if dtype else None,
                    doc_number=dnum_clean,
                    article_number=art_num,
                    clause_number=cl_num,
                    point_letter=pt_let,
                    evidence_text=text[start:end].strip()
                ))

        # 5. Fallback bổ sung: Điều X chung
        for match in cls.GENERAL_ARTICLE_RE.finditer(text):
            art_num = match.group(1)
            key = ("REFERENCES", None, None, art_num, None)
            if key not in seen_keys:
                seen_keys.add(key)
                start, end = max(0, match.start() - 25), min(len(text), match.end() + 25)
                citations.append(CitationMatch(
                    raw_text=match.group(0),
                    relation_type="REFERENCES",
                    article_number=art_num,
                    evidence_text=text[start:end].strip()
                ))

        return citations

    @classmethod
    def enrich_graph_with_citations(
        cls,
        G: nx.DiGraph,
        documents: List[ParsedDocument],
    ) -> nx.DiGraph:
        """
        Nâng cấp đồ thị NetworkX bằng cách:
        1. Tạo bảng tra cứu Điều -> Node ID trong từng văn bản và trên toàn bộ kho luật.
        2. Tạo bảng tra cứu Số hiệu văn bản -> Danh sách Node IDs.
        3. Quét toàn bộ nội dung của từng node và nối các cạnh có trọng số, loại quan hệ và bằng chứng.
        """
        # Bảng tra cứu: (doc_id, article_num) -> node_id
        # và article_num -> list[node_id] (fallback liên văn bản)
        doc_article_lookup: Dict[Tuple[str, str], str] = {}
        global_article_lookup: Dict[str, List[str]] = {}
        doc_number_lookup: Dict[str, str] = {}  # doc_number_clean -> doc_id

        # Khởi tạo bản đồ tra cứu từ các node hiện có
        for node_id, attrs in G.nodes(data=True):
            doc_id = attrs.get("doc_id", "")
            heading = attrs.get("heading", "")
            sec_id = attrs.get("section_id", "")
            file_name = attrs.get("file_name", "")

            # Trích xuất số Điều từ heading hoặc section_id
            m = cls.GENERAL_ARTICLE_RE.search(heading) or cls.GENERAL_ARTICLE_RE.search(sec_id)
            if m:
                art_num = m.group(1)
                doc_article_lookup[(doc_id, art_num)] = node_id
                global_article_lookup.setdefault(art_num, []).append(node_id)

            # Trích xuất số hiệu văn bản từ tên file hoặc doc_id
            num_match = cls.DOC_NUMBER_RE.search(file_name) or cls.DOC_NUMBER_RE.search(doc_id)
            if num_match:
                dnum_clean = cls.clean_doc_number(num_match.group(1))
                if dnum_clean:
                    doc_number_lookup[dnum_clean] = doc_id

        # Quét từng node để tìm các dẫn chiếu và tạo liên kết đồ thị
        edges_added = 0
        for node_id, attrs in list(G.nodes(data=True)):
            content = attrs.get("content_markdown", "")
            curr_doc_id = attrs.get("doc_id", "")
            if not content:
                continue

            citations = cls.extract_citations(content)
            for cit in citations:
                target_node_id = None

                # TH 1: Dẫn chiếu có đích danh số hiệu văn bản khác
                if cit.doc_number and cit.doc_number in doc_number_lookup:
                    target_doc_id = doc_number_lookup[cit.doc_number]
                    if cit.article_number:
                        target_node_id = doc_article_lookup.get((target_doc_id, cit.article_number))
                    else:
                        # Trỏ tới node đầu tiên của văn bản đích nếu không chỉ rõ Điều
                        matching = [nid for nid, a in G.nodes(data=True) if a.get("doc_id") == target_doc_id]
                        if matching:
                            target_node_id = matching[0]
                elif cit.doc_number and cit.relation_type in ("AMENDS", "SUPPLEMENTS", "REPEALS", "DETAILS"):
                    # Văn bản đích là văn bản bên ngoài (chưa được nạp toàn văn vào kho nội bộ)
                    # Tạo External Node để biểu diễn trực quan mối quan hệ trên đồ thị
                    ext_node_id = f"EXT::{cit.doc_number}::D{cit.article_number or 'ALL'}"
                    if not G.has_node(ext_node_id):
                        art_prefix = f"Điều {cit.article_number} - " if cit.article_number else ""
                        doc_title = f"{cit.doc_type or 'Văn bản'} số {cit.doc_number}"
                        G.add_node(
                            ext_node_id,
                            doc_id=cit.doc_number,
                            file_name=doc_title,
                            section_id=f"D{cit.article_number or 'ALL'}",
                            heading=f"📌 {art_prefix}{doc_title}",
                            page_start=1,
                            page_end=1,
                            content_markdown=f"Văn bản pháp luật ngoài hệ thống: {doc_title}. Được sửa đổi/hướng dẫn trực tiếp từ điều khoản trong hệ thống."
                        )
                    target_node_id = ext_node_id

                # TH 2: Dẫn chiếu nội bộ trong cùng văn bản (ví dụ "theo quy định tại Điều 14")
                if not target_node_id and cit.article_number:
                    target_node_id = doc_article_lookup.get((curr_doc_id, cit.article_number))

                # TH 3: Fallback tra cứu toàn cục nếu chỉ có 1 Điều tương ứng
                if not target_node_id and cit.article_number:
                    candidates = global_article_lookup.get(cit.article_number, [])
                    other_candidates = [cid for cid in candidates if cid != node_id]
                    if len(other_candidates) == 1:
                        target_node_id = other_candidates[0]

                # Bổ sung cạnh nếu tìm thấy node đích hợp lệ
                if target_node_id and target_node_id != node_id:
                    G.add_edge(
                        node_id,
                        target_node_id,
                        relation=cit.relation_type,
                        relation_type=cit.relation_type,
                        evidence_text=cit.evidence_text,
                        raw_citation=cit.raw_text,
                        detection_method="LEGAL_CITATION_PARSER",
                    )
                    edges_added += 1

        logger.info(f"LegalCitationParser: Đã làm giàu thêm {edges_added} cạnh quan hệ pháp lý vào đồ thị.")
        return G
