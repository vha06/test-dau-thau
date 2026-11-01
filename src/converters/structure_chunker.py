import hashlib
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from src.schemas.document import ParsedDocument, DocumentSection, DocRole


@dataclass
class LegalChunk:
    chunk_id: str
    doc_id: str
    section_id: str
    parent_id: Optional[str]
    structural_path: str
    heading: str
    injected_header: str
    content: str
    content_with_header: str
    token_count: int
    level: str  # "ARTICLE", "CLAUSE", "POINT", "SECTION"
    page_start: int = 1
    page_end: int = 1
    content_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "section_id": self.section_id,
            "parent_id": self.parent_id,
            "structural_path": self.structural_path,
            "heading": self.heading,
            "injected_header": self.injected_header,
            "content": self.content,
            "content_with_header": self.content_with_header,
            "token_count": self.token_count,
            "level": self.level,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "content_hash": self.content_hash,
        }


class StructureChunker:
    """
    Chiến lược phân mảnh A3 (Structure-aware Legal Chunking with Context Header Injection):
    - Kế thừa và cải tiến từ Legal Retrieval Lab (test-kg-rag)
    - Tiêm tiêu đề văn bản, tên Chương, tên Điều và câu dẫn cha vào đầu mỗi chunk con
    - Bảo toàn 100% ngữ cảnh pháp lý khi nhúng vector và tra cứu GraphRAG
    - Phân tách linh hoạt: Giữ nguyên cấp Điều nếu ngắn, rã xuống Khoản/Điểm nếu vượt ngưỡng max_tokens
    """

    CLAUSE_PATTERN = re.compile(r"(?:^|\n)(Khoản\s+\d+[\.:]?\s*[^\n]*)", re.IGNORECASE)
    POINT_PATTERN = re.compile(r"(?:^|\n)([a-zđ]\)\s*[^\n]*)", re.IGNORECASE)

    def __init__(self, max_tokens: int = 384):
        self.max_tokens = max_tokens
        self.strategy_name = "A3_structure"

    @staticmethod
    def count_tokens(text: str) -> int:
        """Bộ đếm token nhất quán cho văn bản tiếng Việt dựa trên từ và dấu câu."""
        if not text:
            return 0
        tokens = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
        return len(tokens)

    def chunk_document(self, doc: ParsedDocument) -> List[LegalChunk]:
        """Phân mảnh một ParsedDocument thành danh sách LegalChunk có tiêm ngữ cảnh cha-con."""
        chunks: List[LegalChunk] = []

        # Xây dựng cây phân cấp từ sections
        sections_by_id: Dict[str, DocumentSection] = {s.section_id: s for s in doc.sections}
        children_map: Dict[str, List[DocumentSection]] = {}
        for s in doc.sections:
            if s.parent_id:
                children_map.setdefault(s.parent_id, []).append(s)

        # Nhận diện vai trò văn bản để đặt tiền tố nhãn
        role_label = "Văn bản Luật" if doc.doc_role == DocRole.LAW else (
            "Hồ sơ mời thầu (HSMT)" if doc.doc_role == DocRole.HSMT else "Hồ sơ dự thầu (HSDT)"
        )
        doc_header_prefix = f"[{role_label}: {doc.file_name} (Mã: {doc.doc_id})]"

        for sec in doc.sections:
            # Xây dựng đường dẫn cấu trúc (structural_path)
            path_parts = [sec.heading]
            curr_parent_id = sec.parent_id
            while curr_parent_id and curr_parent_id in sections_by_id:
                p_sec = sections_by_id[curr_parent_id]
                path_parts.insert(0, p_sec.heading)
                curr_parent_id = p_sec.parent_id

            structural_path = " > ".join(path_parts)
            injected_header = f"{doc_header_prefix} | {structural_path}"

            sec_tokens = self.count_tokens(sec.content_markdown)
            has_children = sec.section_id in children_map

            # 1. Nếu section ngắn hơn max_tokens hoặc không có phân đoạn con: Tạo 1 chunk trọn vẹn
            if sec_tokens <= self.max_tokens or has_children:
                # Nếu đã có children quản lý nội dung chi tiết, ta chỉ lưu chunk tóm lược hoặc chunk chính của nó
                full_text = f"{injected_header}\n{sec.heading}\n{sec.content_markdown}".strip()
                c_id = f"CHK_{self.strategy_name}_{doc.doc_id}_{sec.section_id}"
                c_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

                chunks.append(LegalChunk(
                    chunk_id=c_id,
                    doc_id=doc.doc_id,
                    section_id=sec.section_id,
                    parent_id=sec.parent_id,
                    structural_path=structural_path,
                    heading=sec.heading,
                    injected_header=injected_header,
                    content=sec.content_markdown,
                    content_with_header=full_text,
                    token_count=self.count_tokens(full_text),
                    level="ARTICLE" if "điều" in sec.heading.lower() else "SECTION",
                    page_start=sec.page_start,
                    page_end=sec.page_end,
                    content_hash=c_hash,
                ))
                continue

            # 2. Section dài hơn max_tokens và chứa nhiều Khoản trong nội dung markdown
            # Thử phân rã theo Khoản (Clause splitting)
            clauses = self._split_by_clauses(sec.content_markdown)
            if len(clauses) > 1:
                for idx, (clause_title, clause_body) in enumerate(clauses):
                    cl_path = f"{structural_path} > {clause_title}"
                    cl_header = f"{doc_header_prefix} | {cl_path}"
                    cl_full_text = f"{cl_header}\n{clause_title}\n{clause_body}".strip()
                    c_id = f"CHK_{self.strategy_name}_{doc.doc_id}_{sec.section_id}_CL{idx+1}"
                    c_hash = hashlib.sha256(cl_full_text.encode("utf-8")).hexdigest()

                    chunks.append(LegalChunk(
                        chunk_id=c_id,
                        doc_id=doc.doc_id,
                        section_id=sec.section_id,
                        parent_id=sec.section_id,
                        structural_path=cl_path,
                        heading=f"{sec.heading} - {clause_title}",
                        injected_header=cl_header,
                        content=clause_body,
                        content_with_header=cl_full_text,
                        token_count=self.count_tokens(cl_full_text),
                        level="CLAUSE",
                        page_start=sec.page_start,
                        page_end=sec.page_end,
                        content_hash=c_hash,
                    ))
            else:
                # Fallback: Nếu không phát hiện cú pháp Khoản, lưu nguyên vẹn section kèm header
                full_text = f"{injected_header}\n{sec.heading}\n{sec.content_markdown}".strip()
                c_id = f"CHK_{self.strategy_name}_{doc.doc_id}_{sec.section_id}"
                c_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

                chunks.append(LegalChunk(
                    chunk_id=c_id,
                    doc_id=doc.doc_id,
                    section_id=sec.section_id,
                    parent_id=sec.parent_id,
                    structural_path=structural_path,
                    heading=sec.heading,
                    injected_header=injected_header,
                    content=sec.content_markdown,
                    content_with_header=full_text,
                    token_count=self.count_tokens(full_text),
                    level="SECTION",
                    page_start=sec.page_start,
                    page_end=sec.page_end,
                    content_hash=c_hash,
                ))

        return chunks

    def chunk_documents(self, documents: List[ParsedDocument]) -> List[LegalChunk]:
        """Phân mảnh hàng loạt danh sách ParsedDocument."""
        all_chunks: List[LegalChunk] = []
        for doc in documents:
            all_chunks.extend(self.chunk_document(doc))
        return all_chunks

    @classmethod
    def _split_by_clauses(cls, text: str) -> List[tuple]:
        """Tách nội dung thành các (tên_khoản, nội_dung_khoản)."""
        splits = re.split(r"(?=(?:^|\n)Khoản\s+\d+[\.:]?)", text, flags=re.IGNORECASE)
        results = []
        for part in splits:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            first_line = lines[0].strip()
            rest = lines[1].strip() if len(lines) > 1 else ""
            if re.match(r"^Khoản\s+\d+", first_line, re.IGNORECASE):
                results.append((first_line, rest if rest else first_line))
            else:
                results.append(("Lời dẫn", part))
        return results

    @classmethod
    def compute_stats(cls, chunks: List[LegalChunk]) -> Dict[str, Any]:
        """Thống kê chi tiết chất lượng phân mảnh chunks."""
        if not chunks:
            return {"total_chunks": 0, "token_min": 0, "token_median": 0, "token_max": 0}

        tokens = [c.token_count for c in chunks]
        sorted_tokens = sorted(tokens)
        n = len(sorted_tokens)
        median = sorted_tokens[n // 2] if n % 2 != 0 else (sorted_tokens[n // 2 - 1] + sorted_tokens[n // 2]) / 2

        return {
            "total_chunks": n,
            "token_min": min(tokens),
            "token_median": round(median, 1),
            "token_max": max(tokens),
            "level_distribution": {
                lvl: sum(1 for c in chunks if c.level == lvl)
                for lvl in set(c.level for c in chunks)
            }
        }
