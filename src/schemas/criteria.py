from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class CriterionCategory(str, Enum):
    TU_CACH_HOP_LE = "TU_CACH_HOP_LE"
    DON_DU_THAU = "DON_DU_THAU"
    BAO_LANH_DU_THAU = "BAO_LANH_DU_THAU"
    UY_QUYEN = "UY_QUYEN"
    NANG_LUC_TAI_CHINH = "NANG_LUC_TAI_CHINH"
    KINH_NGHIEM_DU_AN = "KINH_NGHIEM_DU_AN"
    KHAC = "KHAC"

class EvaluationCriterion(BaseModel):
    criterion_id: str = Field(..., description="Mã định danh tiêu chí (VD: CRIT_BAO_LANH_01)")
    criterion_name: str = Field(..., description="Tên tiêu chí (VD: Tính hợp lệ của Bảo lãnh dự thầu)")
    category: CriterionCategory = Field(..., description="Nhóm tiêu chí đánh giá")
    requirement_summary: str = Field(..., description="Tóm tắt yêu cầu quy định trong HSMT")
    source_section_id: Optional[str] = Field(None, description="Mã phân đoạn nguồn trong HSMT")
    page_number: Optional[int] = Field(None, description="Số trang chứa tiêu chí trong HSMT")
    extracted_quote: Optional[str] = Field(None, description="Đoạn văn bản trích dẫn nguyên văn trong HSMT")
    
    # Tham số định lượng phục vụ đối chiếu
    max_legal_rate_percent: Optional[float] = Field(None, description="Mức trần % tối đa theo quy định Luật nếu có")
    configured_rate_percent: Optional[float] = Field(None, description="Tỷ lệ % bảo lãnh cài đặt trong HSMT")
    required_days: Optional[int] = Field(None, description="Số ngày hiệu lực yêu cầu tối thiểu")
    required_amount: Optional[float] = Field(None, description="Giá trị bảo lãnh tối thiểu yêu cầu (VNĐ)")
    quantitative_params: Dict[str, Any] = Field(default_factory=dict, description="Các tham số định lượng bổ sung")

class CriteriaList(BaseModel):
    package_name: str = Field(..., description="Tên gói thầu thẩm định")
    criteria: List[EvaluationCriterion] = Field(default_factory=list, description="Danh sách các tiêu chí đánh giá")
