import logging
from datetime import datetime, date
from typing import Optional, Dict, Any, List, Union
from src.schemas.report import ComplianceStatus
from src.schemas.document import VisualCues

logger = logging.getLogger(__name__)

def _parse_date(d: Optional[Union[str, date, datetime]]) -> Optional[date]:
    """Chuyển đổi chuỗi ngày linh hoạt sang datetime.date."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
        
    s = str(d).strip()
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def check_guarantee_validity(
    issue_date: Optional[Union[str, date]],
    expiry_date: Optional[Union[str, date]],
    bid_close_date: Optional[Union[str, date]],
    required_days: Optional[int],
    required_amount: Optional[float],
    actual_amount: Optional[float]
) -> Dict[str, Any]:
    """
    Kiểm tra độ dài hiệu lực và giá trị bảo lãnh dự thầu:
    1. issue_date <= bid_close_date
    2. (expiry_date - bid_close_date).days >= required_days
    3. actual_amount >= required_amount
    """
    p_issue = _parse_date(issue_date)
    p_expiry = _parse_date(expiry_date)
    p_close = _parse_date(bid_close_date)
    
    missing_fields = []
    if p_issue is None:
        missing_fields.append("Ngày phát hành bảo lãnh (issue_date)")
    if p_expiry is None:
        missing_fields.append("Ngày hết hạn bảo lãnh (expiry_date)")
    if p_close is None:
        missing_fields.append("Ngày đóng thầu (bid_close_date)")
    if actual_amount is None:
        missing_fields.append("Số tiền bảo lãnh thực tế (actual_amount)")

    if missing_fields:
        return {
            "status": ComplianceStatus.INSUFFICIENT_BASIS,
            "passed": False,
            "validity_days": None,
            "amount_diff": None,
            "violations": [f"Thiếu thông tin đầu vào: {', '.join(missing_fields)}"],
            "details": f"Chưa đủ căn cứ kiểm tra do thiếu dữ liệu: {', '.join(missing_fields)}"
        }

    violations = []
    
    # Kiểm tra ngày phát hành
    if p_issue > p_close:
        violations.append(f"Bảo lãnh phát hành sau ngày đóng thầu ({p_issue} > {p_close})")

    # Kiểm tra số ngày hiệu lực tính từ ngày đóng thầu
    validity_days = (p_expiry - p_close).days
    req_days = required_days or 0
    if validity_days < req_days:
        violations.append(
            f"Thời hạn hiệu lực không đạt: {validity_days} ngày kể từ ngày đóng thầu (Yêu cầu tối thiểu: {req_days} ngày, thiếu {req_days - validity_days} ngày)"
        )

    # Kiểm tra giá trị bảo lãnh
    req_amt = required_amount or 0.0
    amount_diff = actual_amount - req_amt
    if amount_diff < 0:
        violations.append(
            f"Giá trị bảo lãnh không đủ: {actual_amount:,.0f} VNĐ (Yêu cầu tối thiểu: {req_amt:,.0f} VNĐ, thiếu {abs(amount_diff):,.0f} VNĐ)"
        )

    if violations:
        return {
            "status": ComplianceStatus.INVALID,
            "passed": False,
            "validity_days": validity_days,
            "amount_diff": amount_diff,
            "violations": violations,
            "details": "; ".join(violations)
        }

    return {
        "status": ComplianceStatus.VALID,
        "passed": True,
        "validity_days": validity_days,
        "amount_diff": amount_diff,
        "violations": [],
        "details": f"Bảo lãnh hợp lệ: Giá trị {actual_amount:,.0f} VNĐ đạt yêu cầu, hiệu lực {validity_days} ngày (>= {req_days} ngày)."
    }

def check_authorization_dates(
    auth_date: Optional[Union[str, date]],
    bid_sign_date: Optional[Union[str, date]],
    bid_close_date: Optional[Union[str, date]]
) -> Dict[str, Any]:
    """
    Kiểm tra tính hợp lệ về thời gian của giấy ủy quyền so với đơn dự thầu:
    Quy tắc: auth_date <= bid_sign_date <= bid_close_date
    """
    p_auth = _parse_date(auth_date)
    p_sign = _parse_date(bid_sign_date)
    p_close = _parse_date(bid_close_date)
    
    missing_fields = []
    if p_auth is None:
        missing_fields.append("Ngày ký giấy ủy quyền (auth_date)")
    if p_sign is None:
        missing_fields.append("Ngày ký đơn dự thầu (bid_sign_date)")
        
    if missing_fields:
        return {
            "status": ComplianceStatus.INSUFFICIENT_BASIS,
            "passed": False,
            "violations": [f"Thiếu thông tin: {', '.join(missing_fields)}"],
            "details": f"Chưa đủ dữ liệu để kiểm tra ngày ủy quyền: {', '.join(missing_fields)}"
        }

    violations = []
    if p_auth > p_sign:
        violations.append(f"Giấy ủy quyền được ký sau ngày ký đơn dự thầu ({p_auth} > {p_sign})")
        
    if p_close and p_sign > p_close:
        violations.append(f"Đơn dự thầu ký sau thời điểm đóng thầu ({p_sign} > {p_close})")

    if violations:
        return {
            "status": ComplianceStatus.INVALID,
            "passed": False,
            "violations": violations,
            "details": "; ".join(violations)
        }

    return {
        "status": ComplianceStatus.VALID,
        "passed": True,
        "violations": [],
        "details": f"Thời điểm ủy quyền hợp lệ: Giấy ủy quyền ký ngày {p_auth}, đơn dự thầu ký ngày {p_sign} (trước thời điểm đóng thầu {p_close})."
    }

def verify_visual_stamps(visual_cues: Optional[VisualCues]) -> Dict[str, Any]:
    """
    Kiểm tra sự hiện diện của chữ ký và con dấu pháp nhân.
    - Không có visual_cues -> CHUA_DU_CAN_CU
    - Thiếu chữ ký hoặc thiếu dấu đỏ -> KHONG_HOP_LE
    - Có chữ ký + dấu đỏ nhưng nội dung dấu bị mờ hoặc rỗng -> CHUA_DU_CAN_CU
    - Có chữ ký + dấu đỏ rõ nét -> HOP_LE
    """
    if visual_cues is None:
        return {
            "status": ComplianceStatus.INSUFFICIENT_BASIS,
            "passed": False,
            "violations": ["Chưa có dữ liệu nhận diện chữ ký/con dấu từ hệ thống OCR"],
            "details": "Chưa đủ căn cứ xác thực yếu tố vật lý do thiếu visual_cues."
        }

    if not visual_cues.has_signature:
        return {
            "status": ComplianceStatus.INVALID,
            "passed": False,
            "violations": ["Văn bản thiếu chữ ký của người có thẩm quyền"],
            "details": "Không phát hiện chữ ký trên văn bản dự thầu."
        }

    if not visual_cues.has_red_stamp:
        return {
            "status": ComplianceStatus.INVALID,
            "passed": False,
            "violations": ["Văn bản thiếu con dấu pháp nhân (con dấu đỏ)"],
            "details": "Không phát hiện con dấu đỏ pháp nhân của nhà thầu."
        }

    # Có chữ ký và con dấu đỏ, kiểm tra độ rõ ràng của nội dung con dấu
    stamp_text = (visual_cues.stamp_text_ocr or "").strip().lower()
    unclear_keywords = ["mờ", "không rõ", "unreadable", "blur"]
    
    if not stamp_text or any(kw in stamp_text for kw in unclear_keywords):
        return {
            "status": ComplianceStatus.INSUFFICIENT_BASIS,
            "passed": False,
            "violations": ["Nội dung con dấu bị mờ hoặc không đọc được tên pháp nhân"],
            "details": "Phát hiện con dấu đỏ nhưng nội dung bị mờ, không nhận diện được rõ tên nhà thầu. Cần yêu cầu nhà thầu làm rõ hoặc xuất trình bản gốc đối chiếu theo Điều 19."
        }

    return {
        "status": ComplianceStatus.VALID,
        "passed": True,
        "violations": [],
        "details": f"Chữ ký và con dấu đỏ hợp lệ, nội dung nhận diện: {visual_cues.stamp_text_ocr}"
    }
