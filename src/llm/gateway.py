import json
import logging
import re
from typing import Type, TypeVar, Optional, Any
from pydantic import BaseModel
from config.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

def _mock_fallback_generator(prompt: str, response_model: Type[T]) -> T:
    """Sinh dữ liệu giả lập cho testing hoặc khi không có API key."""
    model_name = response_model.__name__
    
    if model_name == "CriteriaList":
        from src.schemas.criteria import EvaluationCriterion, CriterionCategory, CriteriaList
        return response_model(
            package_name="Dự án Đầu tư Xây dựng Khu đô thị mới Bắc Sông Hồng",
            criteria=[
                EvaluationCriterion(
                    criterion_id="CRIT_TU_CACH_01",
                    criterion_name="Tư cách hợp lệ của nhà thầu",
                    category=CriterionCategory.TU_CACH_HOP_LE,
                    requirement_summary="Nhà thầu phải có giấy chứng nhận ĐKKD hợp pháp, hạch toán độc lập.",
                    source_section_id="HSMT_SEC_01",
                    page_number=4,
                    extracted_quote="Nhà thầu tham dự phải có Giấy chứng nhận đăng ký doanh nghiệp hợp pháp, hạch toán tài chính độc lập"
                ),
                EvaluationCriterion(
                    criterion_id="CRIT_DON_THAU_01",
                    criterion_name="Tính hợp lệ của Đơn dự thầu và Giấy ủy quyền",
                    category=CriterionCategory.UY_QUYEN,
                    requirement_summary="Đơn dự thầu ký đúng thẩm quyền, có giấy ủy quyền hợp lệ trước ngày ký đơn.",
                    source_section_id="HSMT_SEC_02",
                    page_number=6,
                    extracted_quote="Đơn dự thầu phải được người đại diện theo pháp luật của nhà thầu ký tên và đóng dấu. Trường hợp ủy quyền thì người được ủy quyền phải có Giấy ủy quyền hợp lệ"
                ),
                EvaluationCriterion(
                    criterion_id="CRIT_BAO_LANH_01",
                    criterion_name="Giá trị và thời hạn hiệu lực của Bảo đảm dự thầu",
                    category=CriterionCategory.BAO_LANH_DU_THAU,
                    requirement_summary="Bảo lãnh dự thầu 25 tỷ VNĐ (5% tổng mức đầu tư), hiệu lực tối thiểu 120 ngày.",
                    source_section_id="HSMT_SEC_03",
                    page_number=8,
                    extracted_quote="nhà thầu phải nộp Thư bảo lãnh dự thầu với giá trị là 25.000.000.000 VNĐ (tương đương 5,0% tổng mức đầu tư của dự án). Thời hạn hiệu lực của bảo lãnh dự thầu tối thiểu là 120 ngày",
                    configured_rate_percent=5.0,
                    max_legal_rate_percent=3.0,
                    required_days=120,
                    required_amount=25000000000.0
                )
            ]
        )
        
    elif model_name == "ExtractedGuaranteeFacts":
        issue_date = "2026-05-10"
        expiry_date = "2026-08-08"
        bid_close_date = "2026-05-15"
        amount = 25000000000.0
        
        # Regex thông minh theo ngữ cảnh văn bản
        m_issue = re.search(r"phát hành(?:\s+bảo\s+lãnh)?(?:\s*:\s*|\s+ngày\s+)(\d{1,2}[/-]\d{1,2}[/-]\d{4})", prompt, re.IGNORECASE)
        if m_issue:
            d = m_issue.group(1).replace("-", "/").split("/")
            issue_date = f"{d[2]}-{int(d[1]):02d}-{int(d[0]):02d}"
            
        m_exp = re.search(r"(?:đến hết ngày|hết hạn|hiệu lực đến)(?:\s*:\s*|\s+)(\d{1,2}[/-]\d{1,2}[/-]\d{4})", prompt, re.IGNORECASE)
        if m_exp:
            d = m_exp.group(1).replace("-", "/").split("/")
            expiry_date = f"{d[2]}-{int(d[1]):02d}-{int(d[0]):02d}"
            
        m_close = re.search(r"đóng thầu(?:\s+theo\s+thông\s+báo)?(?:\s*:\s*|\s+ngày\s+)(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})", prompt, re.IGNORECASE)
        if m_close:
            val = m_close.group(1)
            if "/" in val:
                d = val.split("/")
                bid_close_date = f"{d[2]}-{int(d[1]):02d}-{int(d[0]):02d}"
            else:
                bid_close_date = val

        m_amt = re.search(r"(\d{1,3}(?:\.\d{3})+)\s*(?:VNĐ|đồng)", prompt, re.IGNORECASE)
        if m_amt:
            amount = float(m_amt.group(1).replace(".", ""))

        return response_model(
            issue_date=issue_date,
            expiry_date=expiry_date,
            bid_close_date=bid_close_date,
            validity_days_mentioned=85,
            actual_amount=amount
        )
        
    elif model_name == "ExtractedAuthFacts":
        auth_date = "2026-05-05"
        bid_sign_date = "2026-05-10"
        bid_close_date = "2026-05-15"
        
        m_auth = re.search(r"(?:Hôm nay,\s*ngày|Giấy\s+ủy\s+quyền\s+số[^\n]+ngày)\s+(\d{1,2}[/-]\d{1,2}[/-]\d{4})", prompt, re.IGNORECASE)
        if m_auth:
            d = m_auth.group(1).replace("-", "/").split("/")
            auth_date = f"{d[2]}-{int(d[1]):02d}-{int(d[0]):02d}"
            
        m_sign = re.search(r"ký\s+đơn\s+dự\s+thầu(?:\s*:\s*|\s+)(\d{1,2}[/-]\d{1,2}[/-]\d{4})", prompt, re.IGNORECASE)
        if m_sign:
            d = m_sign.group(1).replace("-", "/").split("/")
            bid_sign_date = f"{d[2]}-{int(d[1]):02d}-{int(d[0]):02d}"
            
        m_close = re.search(r"đóng thầu(?:\s+theo\s+thông\s+báo)?(?:\s*:\s*|\s+ngày\s+)(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})", prompt, re.IGNORECASE)
        if m_close:
            val = m_close.group(1)
            if "/" in val:
                d = val.split("/")
                bid_close_date = f"{d[2]}-{int(d[1]):02d}-{int(d[0]):02d}"
            else:
                bid_close_date = val

        return response_model(
            auth_date=auth_date,
            auth_expiry_date=None,
            bid_sign_date=bid_sign_date,
            bid_close_date=bid_close_date
        )

    # Generic fallback
    try:
        return response_model()
    except Exception:
        # Nếu model yêu cầu trường bắt buộc
        schema = response_model.model_json_schema()
        fake_data = {}
        for prop, spec in schema.get("properties", {}).items():
            prop_type = spec.get("type", "string")
            if prop_type == "string":
                fake_data[prop] = "Thông tin thẩm tra mẫu"
            elif prop_type == "integer":
                fake_data[prop] = 1
            elif prop_type == "number":
                fake_data[prop] = 1.0
            elif prop_type == "boolean":
                fake_data[prop] = True
            elif prop_type == "array":
                fake_data[prop] = []
        return response_model.model_validate(fake_data)

def generate_structured_output(
    prompt: str,
    response_model: Type[T],
    provider: Optional[str] = None,
    system_instruction: Optional[str] = None,
    **kwargs
) -> T:
    """Unified LLM Gateway gọi Gemini API, Local LLM hoặc Mock Fallback."""
    chosen_provider = provider or settings.default_llm_provider
    
    # 1. Mock Provider trực tiếp
    if chosen_provider == "mock":
        return _mock_fallback_generator(prompt, response_model)

    # 2. Gemini Provider
    if chosen_provider == "gemini":
        api_key = kwargs.get("api_key") or settings.gemini_api_key
        model_name = kwargs.get("model") or settings.gemini_model
        
        if not api_key:
            if settings.allow_mock_fallback:
                logger.warning("Không tìm thấy GEMINI_API_KEY, tự động chuyển sang chế độ Mock Fallback.")
                return _mock_fallback_generator(prompt, response_model)
            raise ValueError("GEMINI_API_KEY chưa được cấu hình!")
            
        try:
            from google import genai
            from google.genai import types
            
            client = genai.Client(api_key=api_key)
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=response_model,
                temperature=0.1
            )
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            return response_model.model_validate_json(response.text)
        except Exception as e:
            logger.error(f"Lỗi khi gọi Google Gemini API: {e}")
            if settings.allow_mock_fallback:
                logger.warning("Kích hoạt Mock Fallback sau lỗi Gemini API.")
                return _mock_fallback_generator(prompt, response_model)
            raise

    # 3. Local LLM Provider (OpenAI Compatible)
    if chosen_provider == "local":
        base_url = kwargs.get("base_url") or settings.local_llm_base_url
        api_key = kwargs.get("api_key") or settings.local_llm_api_key
        model_name = kwargs.get("model") or settings.local_llm_model
        
        try:
            from openai import OpenAI
            client = OpenAI(base_url=base_url, api_key=api_key)
            
            system_content = (system_instruction or "") + "\n\nBạn BẮT BUỘC phải trả về kết quả tuân thủ đúng định dạng JSON Schema sau:\n" + json.dumps(response_model.model_json_schema(), ensure_ascii=False)
            
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt}
            ]
            
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1
            )
            content = completion.choices[0].message.content
            return response_model.model_validate_json(content)
        except Exception as e:
            logger.error(f"Lỗi khi gọi Local LLM: {e}")
            if settings.allow_mock_fallback:
                logger.warning("Kích hoạt Mock Fallback sau lỗi Local LLM.")
                return _mock_fallback_generator(prompt, response_model)
            raise

    # Fallback cuối cùng
    return _mock_fallback_generator(prompt, response_model)
