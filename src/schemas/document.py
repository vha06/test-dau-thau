from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

class DocRole(str, Enum):
    LAW = "LAW"
    HSMT = "HSMT"
    HSDT = "HSDT"

class DocCategory(str, Enum):
    TONG_HOP = "TONG_HOP"
    DON_DU_THAU = "DON_DU_THAU"
    BAO_LANH_DU_THAU = "BAO_LANH_DU_THAU"
    THOA_THUAN_LIEN_DANH = "THOA_THUAN_LIEN_DANH"
    GIAY_UY_QUYEN = "GIAY_UY_QUYEN"
    DANG_KY_KINH_DOANH = "DANG_KY_KINH_DOANH"
    BAO_CAO_TAI_CHINH = "BAO_CAO_TAI_CHINH"
    HOP_DONG_TUONG_TU = "HOP_DONG_TUONG_TU"
    NHAN_SU_CHU_CHOT = "NHAN_SU_CHU_CHOT"
    KHAC = "KHAC"

class TableItem(BaseModel):
    table_id: str = Field(..., description="Mã định danh bảng biểu")
    page_number: int = Field(..., description="Số trang chứa bảng")
    caption: Optional[str] = Field(None, description="Tiêu đề bảng")
    markdown_table: str = Field(..., description="Nội dung bảng dạng markdown")

class VisualCues(BaseModel):
    has_signature: bool = Field(False, description="Có chữ ký hay không")
    has_red_stamp: bool = Field(False, description="Có con dấu đỏ hay không")
    stamp_text_ocr: Optional[str] = Field(None, description="Nội dung bóc tách trên con dấu nếu đọc được")
    page_numbers: List[int] = Field(default_factory=list, description="Các trang xuất hiện chữ ký/con dấu")

class DocumentSection(BaseModel):
    section_id: str = Field(..., description="Mã phân đoạn")
    parent_id: Optional[str] = Field(None, description="Mã phân đoạn cha nếu có")
    heading: str = Field(..., description="Tiêu đề phân đoạn/mục")
    page_start: int = Field(..., description="Trang bắt đầu")
    page_end: int = Field(..., description="Trang kết thúc")
    content_markdown: str = Field(..., description="Toàn văn nội dung đoạn văn bản được định dạng Markdown")
    tables: List[TableItem] = Field(default_factory=list, description="Danh sách bảng biểu")
    visual_cues: Optional[VisualCues] = Field(None, description="Yếu tố xác thực vật lý")

class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    bidding_package_name: Optional[str] = Field(None, description="Tên gói thầu")
    bidder_name: Optional[str] = Field(None, description="Tên nhà thầu")
    submission_date: Optional[str] = Field(None, description="Ngày nộp hồ sơ (YYYY-MM-DD)")
    bid_close_date: Optional[str] = Field(None, description="Thời điểm đóng thầu (YYYY-MM-DD)")
    
    # Định lượng HSMT (nếu có sẵn)
    total_investment: Optional[float] = Field(None, description="Tổng mức đầu tư dự án (VNĐ)")
    required_guarantee_days: Optional[int] = Field(None, description="Số ngày hiệu lực bảo lãnh yêu cầu")
    required_guarantee_amount: Optional[float] = Field(None, description="Số tiền bảo lãnh dự thầu yêu cầu (VNĐ)")
    required_guarantee_rate_percent: Optional[float] = Field(None, description="Tỷ lệ % bảo lãnh theo tổng mức đầu tư")

    # Định lượng HSDT (nếu có sẵn)
    guarantee_issue_date: Optional[str] = Field(None, description="Ngày phát hành bảo lãnh")
    guarantee_expiry_date: Optional[str] = Field(None, description="Ngày hết hạn bảo lãnh")
    actual_guarantee_amount: Optional[float] = Field(None, description="Số tiền bảo lãnh thực tế")
    auth_date: Optional[str] = Field(None, description="Ngày ký giấy ủy quyền")
    bid_sign_date: Optional[str] = Field(None, description="Ngày ký đơn dự thầu")

class ParsedDocument(BaseModel):
    doc_id: str = Field(..., description="Mã định danh duy nhất của tài liệu")
    doc_role: DocRole = Field(..., description="Vai trò văn bản: LAW, HSMT, HSDT")
    doc_category: Optional[DocCategory] = Field(DocCategory.TONG_HOP, description="Phân loại thành phần hồ sơ")
    file_name: str = Field(..., description="Tên file gốc kèm phần mở rộng")
    total_pages: int = Field(..., description="Tổng số trang")
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    sections: List[DocumentSection] = Field(..., description="Danh sách các phân đoạn nội dung")

class ExtractedGuaranteeFacts(BaseModel):
    issue_date: Optional[str] = Field(None, description="Ngày phát hành bảo lãnh định dạng YYYY-MM-DD")
    expiry_date: Optional[str] = Field(None, description="Ngày hết hạn bảo lãnh định dạng YYYY-MM-DD")
    bid_close_date: Optional[str] = Field(None, description="Ngày đóng thầu định dạng YYYY-MM-DD")
    validity_days_mentioned: Optional[int] = Field(None, description="Số ngày hiệu lực ghi trong văn bản nếu có")
    actual_amount: Optional[float] = Field(None, description="Số tiền bảo lãnh thực tế (VNĐ)")

class ExtractedAuthFacts(BaseModel):
    auth_date: Optional[str] = Field(None, description="Ngày ký giấy ủy quyền định dạng YYYY-MM-DD")
    auth_expiry_date: Optional[str] = Field(None, description="Ngày hết hạn ủy quyền định dạng YYYY-MM-DD nếu có")
    bid_sign_date: Optional[str] = Field(None, description="Ngày ký đơn dự thầu định dạng YYYY-MM-DD")
    bid_close_date: Optional[str] = Field(None, description="Ngày đóng thầu định dạng YYYY-MM-DD")
