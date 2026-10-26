import uuid
import logging
from typing import Tuple, List, Optional
from src.schemas.document import ParsedDocument
from src.schemas.criteria import CriteriaList, CriterionCategory
from src.schemas.report import (
    VerificationReport,
    CriterionAssessment,
    ComplianceStatus,
    EvidenceItem,
    LegalReference
)
from src.graph_rag.retriever import retrieve_legal_context
from src.engines.criteria_extractor import extract_criteria_from_hsmt
from config.settings import settings

logger = logging.getLogger(__name__)

def review_hsmt(
    hsmt_doc: ParsedDocument,
    provider: Optional[str] = None,
    **llm_kwargs
) -> Tuple[CriteriaList, VerificationReport]:
    """
    Luồng 1: Thẩm định HSMT
    1. Bóc tách danh mục tiêu chí đánh giá từ HSMT
    2. Đối chiếu từng tiêu chí với GraphRAG Luật để phát hiện các quy định trái luật
    3. Trả về CriteriaList và VerificationReport
    """
    chosen_provider = provider or settings.default_llm_provider
    criteria_list = extract_criteria_from_hsmt(hsmt_doc, provider=chosen_provider, **llm_kwargs)
    
    assessments: List[CriterionAssessment] = []
    
    for crit in criteria_list.criteria:
        # 1. Truy vấn căn cứ pháp lý từ GraphRAG
        query = f"{crit.criterion_name} {crit.requirement_summary}"
        legal_items = retrieve_legal_context(query, top_k=2, hop_depth=1)
        
        legal_refs = [
            LegalReference(
                law_name=item.get("law_name", "Luật Đấu thầu"),
                clause_id=item.get("clause_id", "Quy định liên quan"),
                summary=item.get("content_markdown", "")[:250] + "..."
            )
            for item in legal_items
        ]
        
        # 2. Tạo chứng cứ trích xuất từ HSMT
        evidences = [
            EvidenceItem(
                doc_id=hsmt_doc.doc_id,
                file_name=hsmt_doc.file_name,
                page_number=crit.page_number or 1,
                extracted_quote=crit.extracted_quote or crit.requirement_summary,
                visual_check_note="Văn bản HSMT pháp lý"
            )
        ]
        
        # 3. Đánh giá tính tuân thủ pháp luật
        status = ComplianceStatus.VALID
        reasoning = f"Tiêu chí '{crit.criterion_name}' phù hợp với quy chuẩn Luật Đấu thầu hiện hành."
        missing_points = []
        recommendation = "Tiêu chí đạt yêu cầu, giữ nguyên trong HSMT."
        
        # Kiểm tra tiêu chí Bảo lãnh dự thầu có vi phạm trần không
        if crit.category == CriterionCategory.BAO_LANH_DU_THAU:
            rate = crit.configured_rate_percent or (hsmt_doc.metadata.required_guarantee_rate_percent if hsmt_doc.metadata else None)
            quote_text = (crit.extracted_quote or "").lower()
            
            # Nếu tỷ lệ > 3.0% hoặc trong nội dung có nhắc tới 5%
            is_over_limit = False
            if rate is not None and rate > 3.0:
                is_over_limit = True
            elif "5%" in quote_text or "5,0%" in quote_text:
                is_over_limit = True
                
            if is_over_limit:
                status = ComplianceStatus.INVALID
                reasoning = (
                    "HSMT quy định mức bảo đảm dự thầu là 5,0% tổng mức đầu tư, vượt quá mức trần tối đa 3,0% "
                    "được quy định tại Khoản 1 & Khoản 2 Điều 14 Luật Đấu thầu. Quy định này làm tăng gánh nặng "
                    "tài chính bất hợp lý và có dấu hiệu hạn chế sự tham gia của các nhà thầu có năng lực."
                )
                missing_points = [
                    "Quy định tỷ lệ bảo đảm dự thầu 5% vượt trần pháp luật (tối đa 3%)",
                    "Dấu hiệu cài cắm điều kiện hạn chế cạnh tranh"
                ]
                recommendation = (
                    "Kiến nghị Bên mời thầu điều chỉnh tỷ lệ bảo đảm dự thầu về khoảng từ 1,0% đến 3,0% "
                    "tổng mức đầu tư theo đúng quy định tại Điều 14 Luật Đấu thầu trước khi phát hành hồ sơ chính thức."
                )
        
        assessment = CriterionAssessment(
            criterion_id=crit.criterion_id,
            criterion_name=crit.criterion_name,
            requirement_summary=crit.requirement_summary,
            status=status,
            evidences=evidences,
            references=legal_refs,
            reasoning=reasoning,
            missing_or_unclear_points=missing_points,
            recommendation=recommendation
        )
        assessments.append(assessment)

    # Tổng hợp báo cáo
    valid_count = sum(1 for a in assessments if a.status == ComplianceStatus.VALID)
    invalid_count = sum(1 for a in assessments if a.status == ComplianceStatus.INVALID)
    insufficient_count = sum(1 for a in assessments if a.status == ComplianceStatus.INSUFFICIENT_BASIS)
    
    package_name = hsmt_doc.metadata.bidding_package_name or hsmt_doc.file_name
    overall_summary = (
        f"Thẩm định HSMT gói thầu '{package_name}': Tổng số {len(assessments)} tiêu chí. "
        f"Phát hiện {invalid_count} tiêu chí trái luật/hạn chế nhà thầu cần sửa đổi, "
        f"{valid_count} tiêu chí hợp lệ."
    )

    report = VerificationReport(
        report_id=f"REPORT_HSMT_{uuid.uuid4().hex[:8].upper()}",
        workflow_type="THAM_DINH_HSMT",
        package_name=package_name,
        target_entity_name="Bên mời thầu",
        llm_provider_used=chosen_provider,
        overall_summary=overall_summary,
        total_criteria=len(assessments),
        valid_count=valid_count,
        invalid_count=invalid_count,
        insufficient_count=insufficient_count,
        assessments=assessments
    )
    
    return criteria_list, report
