import json
import logging
import re
import urllib.request
import urllib.error
from typing import Type, TypeVar, Optional, Any
from pydantic import BaseModel
from config.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _mock_fallback_generator(prompt: str, response_model: Type[T]) -> T:
    """Sinh dữ liệu giả lập cho testing hoặc khi chạy chế độ Mock."""
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


def _clean_json_text(raw_text: str) -> str:
    """Làm sạch chuỗi JSON trả về từ LLM nếu có bọc markdown ```json ... ```."""
    txt = raw_text.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt)
    return txt.strip()


def _call_gemini_rest_api(
    prompt: str,
    response_model: Type[T],
    api_key: str,
    model_name: str,
    system_instruction: Optional[str] = None
) -> T:
    """
    Gọi trực tiếp Google Gemini REST API (v1beta) qua HTTPS chuẩn (không phụ thuộc C++ gRPC SDK).
    Đảm bảo chạy ổn định trên mọi môi trường Python / Windows.
    """
    clean_model = model_name.strip()
    if clean_model.startswith("models/"):
        clean_model = clean_model[len("models/"):]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key.strip()}"

    schema_json = json.dumps(response_model.model_json_schema(), ensure_ascii=False, indent=2)
    full_system_inst = (
        (system_instruction or "Bạn là chuyên gia pháp lý đấu thầu Việt Nam.")
        + "\n\nBẮT BUỘC trả về duy nhất một đối tượng JSON hợp lệ tuân thủ chính xác JSON Schema dưới đây (không kèm giải thích ngoài JSON):\n"
        + schema_json
    )

    payload = {
        "system_instruction": {
            "parts": [{"text": full_system_inst}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as http_err:
        err_detail = http_err.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini API HTTP {http_err.code}: {err_detail}") from http_err

    candidates = resp_body.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini API không trả về candidates: {resp_body}")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError(f"Gemini API phản hồi thiếu trường text: {resp_body}")

    raw_json = _clean_json_text(parts[0]["text"])
    return response_model.model_validate_json(raw_json)


def test_gemini_connection(api_key: str, model_name: str = "gemini-2.5-flash") -> dict:
    """Kiểm tra nhanh kết nối và tính hợp lệ của Gemini API Key."""
    if not api_key or not api_key.strip():
        return {"ok": False, "message": "Chưa nhập Gemini API Key."}

    clean_model = model_name.strip()
    if clean_model.startswith("models/"):
        clean_model = clean_model[len("models/"):]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key.strip()}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Trả lời ngắn gọn: OK"}]}],
        "generationConfig": {"maxOutputTokens": 16, "temperature": 0.0}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            reply = body.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            return {"ok": True, "message": f"Kết nối thành công tới `{clean_model}`! Phản hồi: {reply}"}
    except urllib.error.HTTPError as e:
        err_text = e.read().decode("utf-8", errors="ignore")
        return {"ok": False, "message": f"Lỗi HTTP {e.code} từ Gemini API: {err_text[:250]}"}
    except Exception as e:
        return {"ok": False, "message": f"Lỗi kết nối: {e}"}


def generate_structured_output(
    prompt: str,
    response_model: Type[T],
    provider: Optional[str] = None,
    system_instruction: Optional[str] = None,
    allow_fallback: Optional[bool] = None,
    **kwargs
) -> T:
    """Unified LLM Gateway gọi Gemini API (SDK hoặc HTTPS REST), Local LLM hoặc Mock Fallback."""
    chosen_provider = provider or settings.default_llm_provider
    use_fallback = settings.allow_mock_fallback if allow_fallback is None else allow_fallback

    # 1. Mock Provider trực tiếp
    if chosen_provider == "mock":
        return _mock_fallback_generator(prompt, response_model)

    # 2. Gemini Provider
    if chosen_provider == "gemini":
        api_key = kwargs.get("api_key") or settings.gemini_api_key
        model_name = kwargs.get("model") or settings.gemini_model

        if not api_key:
            if use_fallback:
                logger.warning("Không tìm thấy GEMINI_API_KEY, tự động chuyển sang chế độ Mock Fallback.")
                return _mock_fallback_generator(prompt, response_model)
            raise ValueError("Chưa cấu hình GEMINI_API_KEY! Vui lòng nhập Gemini API Key ở thanh công cụ bên trái.")

        try:
            # Ưu tiên gọi qua REST API chuẩn để tránh xung đột gRPC DLL trên Windows và hoạt động trên mọi env
            return _call_gemini_rest_api(
                prompt=prompt,
                response_model=response_model,
                api_key=api_key,
                model_name=model_name,
                system_instruction=system_instruction
            )
        except Exception as rest_err:
            logger.error(f"Lỗi khi gọi Google Gemini API: {rest_err}")
            if use_fallback:
                logger.warning("Kích hoạt Mock Fallback sau lỗi Gemini API.")
                return _mock_fallback_generator(prompt, response_model)
            raise

    # 3. Local LLM Provider (OpenAI Compatible REST / SDK)
    if chosen_provider == "local":
        base_url = (kwargs.get("base_url") or settings.local_llm_base_url).rstrip("/")
        api_key = kwargs.get("api_key") or settings.local_llm_api_key
        model_name = kwargs.get("model") or settings.local_llm_model

        try:
            system_content = (
                (system_instruction or "")
                + "\n\nBạn BẮT BUỘC phải trả về kết quả tuân thủ đúng định dạng JSON Schema sau:\n"
                + json.dumps(response_model.model_json_schema(), ensure_ascii=False)
            )
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1
            }
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": f"Bearer {api_key}"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
            content = _clean_json_text(resp_data["choices"][0]["message"]["content"])
            return response_model.model_validate_json(content)
        except Exception as e:
            logger.error(f"Lỗi khi gọi Local LLM: {e}")
            if use_fallback:
                logger.warning("Kích hoạt Mock Fallback sau lỗi Local LLM.")
                return _mock_fallback_generator(prompt, response_model)
            raise

    # Fallback cuối cùng
    return _mock_fallback_generator(prompt, response_model)
