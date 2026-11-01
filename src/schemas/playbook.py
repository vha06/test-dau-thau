from typing import List, Optional
from pydantic import BaseModel, Field
from src.schemas.criteria import CriterionCategory


class PlaybookCriterionGuide(BaseModel):
    guide_id: str = Field(..., description="Mã định danh hướng dẫn (VD: PB_01, PB_02)")
    criterion_name: str = Field(..., description="Tên tiêu chí thẩm định (VD: Bảo đảm dự thầu)")
    category: CriterionCategory = Field(default=CriterionCategory.KHAC, description="Nhóm tiêu chí tương ứng")
    check_type: Optional[str] = Field(default="Ngữ nghĩa (LLM)", description="Loại kiểm tra: Ngưỡng số, Có/Không, Ngữ nghĩa (LLM), So khớp mẫu, Đối chiếu chéo")
    severity: Optional[str] = Field(default="Chặn", description="Mức độ: Chặn, Cảnh báo, Gợi ý")
    target_location: Optional[str] = Field(default="Toàn bộ HSMT", description="Vị trí trong HSMT (VD: Bảng dữ liệu, Tiêu chuẩn đánh giá...)")
    legal_basis_ref: Optional[str] = Field(default="Luật Đấu thầu 2023 (sđ 2024, 2025)", description="Căn cứ pháp lý tham chiếu")
    hsmt_keywords: List[str] = Field(default_factory=list, description="Từ khóa tìm phân đoạn tương ứng trong HSMT")
    legal_query: str = Field(..., description="Truy vấn mẫu để tìm các Node Luật/Nghị định trên GraphRAG")
    audit_instruction: str = Field(..., description="Chỉ dẫn chi tiết cho LLM về cách đối chiếu HSMT với quy định pháp luật")
    red_flags: List[str] = Field(default_factory=list, description="Các dấu hiệu vi phạm, cài cắm tiêu chí cần cảnh báo")
    is_mandatory: bool = Field(default=True, description="Tiêu chí bắt buộc phải có trong HSMT")


class HSMTAuditPlaybook(BaseModel):
    playbook_id: str = Field(..., description="Mã sổ tay hướng dẫn thẩm định")
    playbook_name: str = Field(..., description="Tên bộ hướng dẫn thẩm định")
    description: str = Field(..., description="Mô tả phạm vi áp dụng (VD: Hướng dẫn thẩm định HSMT theo Luật Đấu thầu)")
    version: str = Field(default="1.0", description="Phiên bản của Playbook")
    updated_at: str = Field(default="2026-10-30", description="Ngày cập nhật")
    guides: List[PlaybookCriterionGuide] = Field(default_factory=list, description="Danh sách các tiêu chí hướng dẫn")
