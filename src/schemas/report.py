from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class ComplianceStatus(str, Enum):
    VALID = "HOP_LE"                         # Đạt / Hợp lệ
    INVALID = "KHONG_HOP_LE"                 # Không đạt / Vi phạm
    INSUFFICIENT_BASIS = "CHUA_DU_CAN_CU"    # Chưa đủ căn cứ / Cần làm rõ bổ sung

class EvidenceItem(BaseModel):
    doc_id: str = Field(..., description="Mã tài liệu được trích xuất")
    file_name: str = Field(..., description="Tên file nguồn chứa bằng chứng")
    page_number: int = Field(..., description="Số trang chứa bằng chứng")
    extracted_quote: str = Field(..., description="Đoạn văn bản hoặc số liệu trích xuất nguyên văn")
    visual_check_note: Optional[str] = Field(None, description="Ghi chú về chữ ký/con dấu nếu có")

class LegalReference(BaseModel):
    law_name: str = Field(..., description="Tên văn bản (VD: Luật Đấu thầu 2023, HSMT Mục 2)")
    clause_id: str = Field(..., description="Điều, khoản, điểm tham chiếu")
    summary: str = Field(..., description="Tóm tắt nội dung quy định áp dụng")
    expansion_path: Optional[str] = Field(None, description="Đường đi duyệt đồ thị tri thức (nếu có)")
    evidence_text: Optional[str] = Field(None, description="Căn cứ dẫn chiếu cụ thể")

class CriterionAssessment(BaseModel):
    criterion_id: str = Field(..., description="Mã định danh tiêu chí (VD: CRIT_BAO_LANH_01)")
    criterion_name: str = Field(..., description="Tên tiêu chí (VD: Tính hợp lệ của Bảo lãnh dự thầu)")
    requirement_summary: str = Field(..., description="Tóm tắt yêu cầu quy định trong HSMT và Luật")
    status: ComplianceStatus = Field(..., description="Kết luận sơ bộ của hệ thống")
    evidences: List[EvidenceItem] = Field(default_factory=list, description="Danh sách bằng chứng tìm thấy")
    references: List[LegalReference] = Field(default_factory=list, description="Căn cứ pháp lý đối chiếu")
    reasoning: str = Field(..., description="Lập luận phân tích chi tiết dẫn đến kết luận")
    missing_or_unclear_points: List[str] = Field(default_factory=list, description="Các điểm mâu thuẫn, thiếu căn cứ")
    recommendation: str = Field(..., description="Đề xuất hành động cho chuyên viên thẩm định")
    playbook_guide_used: Optional[str] = Field(None, description="Chỉ dẫn từ File hướng dẫn đã áp dụng")
    user_decision: Optional[ComplianceStatus] = Field(None, description="Quyết định cuối cùng của người thẩm định")
    user_decision_note: Optional[str] = Field("", description="Ý kiến phê duyệt / chỉ đạo chỉnh sửa của người dùng")

class VerificationReport(BaseModel):
    report_id: str
    workflow_type: str = Field(..., description="THAM_DINH_HSMT hoặc KIEM_TRA_HSDT")
    package_name: str
    target_entity_name: str = Field(..., description="Tên bên mời thầu hoặc tên nhà thầu dự thầu")
    llm_provider_used: str = Field(..., description="gemini hoặc local")
    overall_summary: str = Field(..., description="Tóm lược tổng thể hồ sơ")
    total_criteria: int
    valid_count: int
    invalid_count: int
    insufficient_count: int
    assessments: List[CriterionAssessment]
