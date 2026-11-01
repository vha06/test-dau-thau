import logging
import yaml
from pathlib import Path
from src.schemas.document import ParsedDocument
from src.schemas.criteria import CriteriaList, EvaluationCriterion, CriterionCategory
from src.llm.gateway import generate_structured_output
from config.settings import settings

logger = logging.getLogger(__name__)

def _load_prompts():
    prompt_path = Path(__file__).resolve().parent.parent.parent / "config" / "prompts.yaml"
    with open(prompt_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def extract_criteria_from_hsmt(
    hsmt_doc: ParsedDocument,
    provider: str = None,
    **llm_kwargs
) -> CriteriaList:
    """
    Bóc tách các tiêu chí thẩm định từ HSMT thành CriteriaList chuẩn hóa.
    Nếu provider là 'mock' hoặc LLM gặp sự cố, trích xuất chuẩn hóa trực tiếp từ các phân đoạn của HSMT.
    """
    package_name = hsmt_doc.metadata.bidding_package_name or hsmt_doc.file_name

    def _build_criteria_from_sections() -> CriteriaList:
        criteria = []
        for sec in hsmt_doc.sections:
            cat = CriterionCategory.KHAC
            title = sec.heading.lower()
            if "tư cách" in title:
                cat = CriterionCategory.TU_CACH_HOP_LE
            elif "đơn dự thầu" in title or "đại diện" in title or "ủy quyền" in title or "liên danh" in title:
                cat = CriterionCategory.UY_QUYEN
            elif "bảo đảm" in title or "bảo lãnh" in title:
                cat = CriterionCategory.BAO_LANH_DU_THAU
            elif "tài chính" in title or "doanh thu" in title or "hợp đồng tương tự" in title or "kinh nghiệm" in title:
                cat = CriterionCategory.NANG_LUC_TAI_CHINH

            rate_pct = hsmt_doc.metadata.required_guarantee_rate_percent if cat == CriterionCategory.BAO_LANH_DU_THAU else None
            req_days = hsmt_doc.metadata.required_guarantee_days if cat == CriterionCategory.BAO_LANH_DU_THAU else None
            req_amt = hsmt_doc.metadata.required_guarantee_amount if cat == CriterionCategory.BAO_LANH_DU_THAU else None

            criteria.append(EvaluationCriterion(
                criterion_id=f"CRIT_{sec.section_id}",
                criterion_name=sec.heading,
                category=cat,
                requirement_summary=sec.content_markdown[:220] + "...",
                source_section_id=sec.section_id,
                page_number=sec.page_start,
                extracted_quote=sec.content_markdown,
                configured_rate_percent=rate_pct,
                max_legal_rate_percent=3.0 if cat == CriterionCategory.BAO_LANH_DU_THAU else None,
                required_days=req_days,
                required_amount=req_amt
            ))
        return CriteriaList(package_name=package_name, criteria=criteria)

    chosen_provider = provider or settings.default_llm_provider
    if chosen_provider == "mock":
        return _build_criteria_from_sections()

    prompts = _load_prompts()
    extract_cfg = prompts.get("extract_criteria", {})
    system_inst = extract_cfg.get("system", "")
    prompt_tmpl = extract_cfg.get("prompt", "")

    # Tổng hợp nội dung các phân đoạn HSMT
    sections_text = []
    for sec in hsmt_doc.sections:
        sections_text.append(f"[{sec.section_id}] {sec.heading} (Trang {sec.page_start}-{sec.page_end}):\n{sec.content_markdown}")
    full_hsmt_content = "\n\n".join(sections_text)

    prompt = prompt_tmpl.format(
        package_name=package_name,
        hsmt_content=full_hsmt_content
    )

    try:
        criteria_list = generate_structured_output(
            prompt=prompt,
            response_model=CriteriaList,
            provider=chosen_provider,
            system_instruction=system_inst,
            **llm_kwargs
        )
        return criteria_list
    except Exception as e:
        logger.error(f"Lỗi khi bóc tách tiêu chí HSMT qua LLM: {e}")
        return _build_criteria_from_sections()
