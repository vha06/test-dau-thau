import uuid
import logging
from typing import Optional, List
from src.schemas.document import (
    ParsedDocument,
    ExtractedGuaranteeFacts,
    ExtractedAuthFacts,
    DocumentSection
)
from src.schemas.criteria import CriteriaList, CriterionCategory, EvaluationCriterion
from src.schemas.report import (
    VerificationReport,
    CriterionAssessment,
    ComplianceStatus,
    EvidenceItem,
    LegalReference
)
from src.graph_rag.retriever import retrieve_legal_context
from src.engines.deterministic_rules import (
    check_guarantee_validity,
    check_authorization_dates,
    verify_visual_stamps
)
from src.llm.gateway import generate_structured_output
from config.settings import settings

logger = logging.getLogger(__name__)

def _find_relevant_section(hsdt_doc: ParsedDocument, criterion: EvaluationCriterion) -> DocumentSection:
    """Tìm phân đoạn hồ sơ dự thầu liên quan nhất tới tiêu chí."""
    cat = criterion.category
    for sec in hsdt_doc.sections:
        h_lower = sec.heading.lower()
        if cat == CriterionCategory.BAO_LANH_DU_THAU and ("bảo lãnh" in h_lower or "bảo đảm" in h_lower):
            return sec
        if cat == CriterionCategory.UY_QUYEN and ("ủy quyền" in h_lower or "đại diện" in h_lower):
            return sec
        if cat in (CriterionCategory.DON_DU_THAU, CriterionCategory.TU_CACH_HOP_LE) and ("đơn" in h_lower or "tư cách" in h_lower):
            return sec
            
    # Mặc định lấy phân đoạn đầu tiên nếu không tìm thấy từ khóa khớp
    return hsdt_doc.sections[0] if hsdt_doc.sections else None

def check_hsdt(
    hsdt_doc: ParsedDocument,
    criteria_list: CriteriaList,
    hsmt_doc: Optional[ParsedDocument] = None,
    provider: Optional[str] = None,
    **llm_kwargs
) -> VerificationReport:
    """
    Luồng 2: Kiểm tra HSDT
    1. Đọc JSON HSDT và Bộ tiêu chí HSMT
    2. Trích xuất tham số số học/ngày tháng (Ưu tiên Metadata, Demo dùng LLM Structured Output)
    3. Thực thi Deterministic Rules cho Bảo lãnh, Ủy quyền, Con dấu
    4. Tra cứu GraphRAG và tổng hợp VerificationReport
    """
    chosen_provider = provider or settings.default_llm_provider
    assessments: List[CriterionAssessment] = []
    
    # Lấy thông tin ngày đóng thầu và yêu cầu bảo lãnh từ HSMT hoặc metadata
    bid_close_date = (
        (hsmt_doc.metadata.bid_close_date if hsmt_doc else None) or
        hsdt_doc.metadata.bid_close_date or
        "2026-05-15"
    )
    
    for crit in criteria_list.criteria:
        sec = _find_relevant_section(hsdt_doc, crit)
        sec_text = sec.content_markdown if sec else ""
        page_num = sec.page_start if sec else 1
        
        # 1. Tra cứu căn cứ pháp lý từ GraphRAG
        query = f"{crit.criterion_name} {crit.requirement_summary}"
        legal_items = retrieve_legal_context(query, top_k=2, hop_depth=1)
        legal_refs = [
            LegalReference(
                law_name=item.get("law_name", "Luật Đấu thầu"),
                clause_id=item.get("clause_id", "Quy định liên quan"),
                summary=item.get("content_markdown", "")[:250] + "...",
                expansion_path=item.get("expansion_path"),
                evidence_text=item.get("evidence_text"),
            )
            for item in legal_items
        ]

        # 2. Thực thi kiểm tra quy tắc định lượng & trực quan
        status = ComplianceStatus.VALID
        reasoning_parts = []
        missing_points = []
        recommendation = "Hồ sơ đáp ứng yêu cầu của tiêu chí này."
        visual_note = "Yếu tố xác thực đạt yêu cầu."
        
        if crit.category == CriterionCategory.BAO_LANH_DU_THAU:
            # Bóc tách tham số bảo lãnh
            issue_date = hsdt_doc.metadata.guarantee_issue_date
            expiry_date = hsdt_doc.metadata.guarantee_expiry_date
            actual_amount = hsdt_doc.metadata.actual_guarantee_amount
            
            # Nếu chưa có sẵn trong metadata (chế độ Demo), dùng LLM trích xuất từ văn bản
            if not (issue_date and expiry_date and actual_amount):
                extract_prompt = f"Trích xuất thông tin bảo lãnh từ nội dung sau:\n{sec_text}\nNgày đóng thầu: {bid_close_date}"
                facts = generate_structured_output(
                    prompt=extract_prompt,
                    response_model=ExtractedGuaranteeFacts,
                    provider=chosen_provider,
                    **llm_kwargs
                )
                issue_date = issue_date or facts.issue_date
                expiry_date = expiry_date or facts.expiry_date
                actual_amount = actual_amount or facts.actual_amount
                bid_close_date = facts.bid_close_date or bid_close_date
            
            req_days = crit.required_days or (hsmt_doc.metadata.required_guarantee_days if hsmt_doc else 120)
            req_amt = crit.required_amount or (hsmt_doc.metadata.required_guarantee_amount if hsmt_doc else 25000000000.0)
            
            # Chạy deterministic rules
            rule_res = check_guarantee_validity(
                issue_date=issue_date,
                expiry_date=expiry_date,
                bid_close_date=bid_close_date,
                required_days=req_days,
                required_amount=req_amt,
                actual_amount=actual_amount
            )
            stamp_res = verify_visual_stamps(sec.visual_cues if sec else None)
            
            visual_note = stamp_res["details"]
            
            # Kết hợp trạng thái
            if not rule_res["passed"]:
                status = rule_res["status"]
                reasoning_parts.append(rule_res["details"])
                missing_points.extend(rule_res["violations"])
                recommendation = "Đề nghị Hội đồng xét thầu đánh giá HSDT KHÔNG ĐẠT do bảo lãnh dự thầu không đáp ứng thời hạn hiệu lực theo quy định bắt buộc."
            elif not stamp_res["passed"]:
                status = stamp_res["status"]
                reasoning_parts.append(stamp_res["details"])
                missing_points.extend(stamp_res["violations"])
                recommendation = "Yêu cầu nhà thầu làm rõ tính xác thực của bảo lãnh dự thầu."
            else:
                status = ComplianceStatus.VALID
                reasoning_parts.append(rule_res["details"])
                reasoning_parts.append(stamp_res["details"])
                recommendation = "Bảo lãnh dự thầu hợp lệ về cả giá trị, thời hạn và tính xác thực."

        elif crit.category == CriterionCategory.UY_QUYEN:
            # Bóc tách tham số ủy quyền
            auth_date = hsdt_doc.metadata.auth_date
            bid_sign_date = hsdt_doc.metadata.bid_sign_date
            
            if not (auth_date and bid_sign_date):
                # Gom nội dung giấy ủy quyền và đơn dự thầu để trích xuất ngày ký
                all_text = "\n\n".join([s.content_markdown for s in hsdt_doc.sections])
                extract_prompt = f"Trích xuất ngày ủy quyền và ngày ký đơn dự thầu:\n{all_text}\nNgày đóng thầu: {bid_close_date}"
                facts = generate_structured_output(
                    prompt=extract_prompt,
                    response_model=ExtractedAuthFacts,
                    provider=chosen_provider,
                    **llm_kwargs
                )
                auth_date = auth_date or facts.auth_date
                bid_sign_date = bid_sign_date or facts.bid_sign_date
                bid_close_date = facts.bid_close_date or bid_close_date
                
            rule_res = check_authorization_dates(auth_date, bid_sign_date, bid_close_date)
            stamp_res = verify_visual_stamps(sec.visual_cues if sec else None)
            
            visual_note = stamp_res["details"]
            
            if not rule_res["passed"]:
                status = rule_res["status"]
                reasoning_parts.append(rule_res["details"])
                missing_points.extend(rule_res["violations"])
                recommendation = "Đánh giá không đạt do giấy ủy quyền được ký sau ngày ký đơn dự thầu hoặc sau thời điểm đóng thầu."
            elif not stamp_res["passed"]:
                status = stamp_res["status"]
                reasoning_parts.append(stamp_res["details"])
                missing_points.extend(stamp_res["violations"])
                recommendation = (
                    "Yêu cầu nhà thầu gửi văn bản giải trình và xuất trình bản gốc Giấy ủy quyền "
                    "để đối chiếu con dấu pháp nhân trước khi công nhận tính hợp lệ (theo Điều 19)."
                )
            else:
                status = ComplianceStatus.VALID
                reasoning_parts.append(rule_res["details"])
                reasoning_parts.append(stamp_res["details"])
                recommendation = "Giấy ủy quyền hợp lệ về thời gian ký và yếu tố pháp lý con dấu."

        else:
            # Các tiêu chí khác: kiểm tra chữ ký & con dấu nếu có visual_cues
            stamp_res = verify_visual_stamps(sec.visual_cues if sec else None)
            visual_note = stamp_res["details"]
            if not stamp_res["passed"]:
                status = stamp_res["status"]
                reasoning_parts.append(stamp_res["details"])
                missing_points.extend(stamp_res["violations"])
                recommendation = "Cần làm rõ yếu tố xác thực chữ ký/con dấu với nhà thầu."
            else:
                status = ComplianceStatus.VALID
                reasoning_parts.append(f"Hồ sơ cung cấp đầy đủ thông tin đáp ứng tiêu chí '{crit.criterion_name}'.")
                reasoning_parts.append(stamp_res["details"])
                recommendation = "Tiêu chí đạt, chấp thuận."

        evidence_item = EvidenceItem(
            doc_id=hsdt_doc.doc_id,
            file_name=hsdt_doc.file_name,
            page_number=page_num,
            extracted_quote=sec_text[:400] + ("..." if len(sec_text) > 400 else ""),
            visual_check_note=visual_note
        )
        
        reasoning = "\n".join(reasoning_parts) if reasoning_parts else "Đã hoàn thành đối chiếu hồ sơ."

        assessment = CriterionAssessment(
            criterion_id=crit.criterion_id,
            criterion_name=crit.criterion_name,
            requirement_summary=crit.requirement_summary,
            status=status,
            evidences=[evidence_item],
            references=legal_refs,
            reasoning=reasoning,
            missing_or_unclear_points=missing_points,
            recommendation=recommendation
        )
        assessments.append(assessment)

    # Đếm số lượng kết quả
    valid_count = sum(1 for a in assessments if a.status == ComplianceStatus.VALID)
    invalid_count = sum(1 for a in assessments if a.status == ComplianceStatus.INVALID)
    insufficient_count = sum(1 for a in assessments if a.status == ComplianceStatus.INSUFFICIENT_BASIS)
    
    bidder_name = hsdt_doc.metadata.bidder_name or "Nhà thầu tham dự"
    package_name = hsdt_doc.metadata.bidding_package_name or (hsmt_doc.metadata.bidding_package_name if hsmt_doc else "Gói thầu")
    
    overall_summary = (
        f"Kết quả kiểm tra HSDT của '{bidder_name}' cho gói thầu '{package_name}': "
        f"Tổng {len(assessments)} tiêu chí. Trong đó: {valid_count} Đạt (HỢP LỆ), "
        f"{invalid_count} Không Đạt (KHÔNG HỢP LỆ), {insufficient_count} Cần làm rõ (CHƯA ĐỦ CĂN CỨ)."
    )

    report = VerificationReport(
        report_id=f"REPORT_HSDT_{uuid.uuid4().hex[:8].upper()}",
        workflow_type="KIEM_TRA_HSDT",
        package_name=package_name,
        target_entity_name=bidder_name,
        llm_provider_used=chosen_provider,
        overall_summary=overall_summary,
        total_criteria=len(assessments),
        valid_count=valid_count,
        invalid_count=invalid_count,
        insufficient_count=insufficient_count,
        assessments=assessments
    )

    return report
