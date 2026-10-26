from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.schemas.document import ParsedDocument, VisualCues
from src.schemas.criteria import CriteriaList, EvaluationCriterion, CriterionCategory
from src.schemas.report import ComplianceStatus, VerificationReport
from src.engines.deterministic_rules import (
    check_guarantee_validity,
    check_authorization_dates,
    verify_visual_stamps
)
from src.graph_rag.indexer import build_law_index
from src.graph_rag.retriever import retrieve_legal_context
from src.engines.hsmt_reviewer import review_hsmt
from src.engines.hsdt_checker import check_hsdt
from src.api.main import app

@pytest.fixture
def mock_law_doc():
    p = Path("data/mock_law/land_bidding_laws.json")
    return ParsedDocument.model_validate_json(p.read_text(encoding="utf-8"))

@pytest.fixture
def mock_hsmt_doc():
    p = Path("data/mock_hsmt/hsmt_sample.json")
    return ParsedDocument.model_validate_json(p.read_text(encoding="utf-8"))

@pytest.fixture
def mock_hsdt_doc():
    p = Path("data/mock_hsdt/hsdt_sample.json")
    return ParsedDocument.model_validate_json(p.read_text(encoding="utf-8"))

def test_schemas_and_mock_data(mock_law_doc, mock_hsmt_doc, mock_hsdt_doc):
    assert mock_law_doc.doc_id == "LAW_DAU_THAU_DAT_DAI_2023"
    assert len(mock_law_doc.sections) == 3
    assert mock_hsmt_doc.doc_id == "HSMT_BAC_SONG_HONG_2026"
    assert mock_hsdt_doc.doc_id == "HSDT_SAO_VIET_2026"

def test_deterministic_guarantee():
    # Trường hợp đạt
    res_ok = check_guarantee_validity(
        issue_date="2026-05-10",
        expiry_date="2026-09-20",
        bid_close_date="2026-05-15",
        required_days=120,
        required_amount=25000000000.0,
        actual_amount=25000000000.0
    )
    assert res_ok["passed"] is True
    assert res_ok["status"] == ComplianceStatus.VALID

    # Trường hợp thiếu ngày hiệu lực (85 < 120)
    res_short = check_guarantee_validity(
        issue_date="2026-05-10",
        expiry_date="2026-08-08",
        bid_close_date="2026-05-15",
        required_days=120,
        required_amount=25000000000.0,
        actual_amount=25000000000.0
    )
    assert res_short["passed"] is False
    assert res_short["status"] == ComplianceStatus.INVALID

    # Trường hợp thiếu số tiền
    res_amt = check_guarantee_validity(
        issue_date="2026-05-10",
        expiry_date="2026-09-20",
        bid_close_date="2026-05-15",
        required_days=120,
        required_amount=25000000000.0,
        actual_amount=20000000000.0
    )
    assert res_amt["passed"] is False
    assert res_amt["status"] == ComplianceStatus.INVALID

def test_deterministic_auth_dates():
    # Hợp lệ
    res_ok = check_authorization_dates(
        auth_date="2026-05-05",
        bid_sign_date="2026-05-10",
        bid_close_date="2026-05-15"
    )
    assert res_ok["passed"] is True
    assert res_ok["status"] == ComplianceStatus.VALID

    # Giấy ủy quyền ký sau ngày ký đơn
    res_fail = check_authorization_dates(
        auth_date="2026-05-12",
        bid_sign_date="2026-05-10",
        bid_close_date="2026-05-15"
    )
    assert res_fail["passed"] is False
    assert res_fail["status"] == ComplianceStatus.INVALID

def test_deterministic_visual_stamps():
    # Đạt: có chữ ký và dấu đỏ rõ nét
    v_ok = verify_visual_stamps(VisualCues(
        has_signature=True,
        has_red_stamp=True,
        stamp_text_ocr="CÔNG TY CP ĐẦU TƯ XÂY DỰNG SAO VIỆT"
    ))
    assert v_ok["status"] == ComplianceStatus.VALID

    # Dấu mờ / rỗng -> CHUA_DU_CAN_CU
    v_blur = verify_visual_stamps(VisualCues(
        has_signature=True,
        has_red_stamp=True,
        stamp_text_ocr=""
    ))
    assert v_blur["status"] == ComplianceStatus.INSUFFICIENT_BASIS

    # Thiếu chữ ký -> KHONG_HOP_LE
    v_nosign = verify_visual_stamps(VisualCues(
        has_signature=False,
        has_red_stamp=True,
        stamp_text_ocr="CON DAU"
    ))
    assert v_nosign["status"] == ComplianceStatus.INVALID

def test_graphrag_pipeline():
    idx_res = build_law_index()
    assert idx_res["total_documents"] >= 1
    assert idx_res["total_nodes"] >= 3

    ctx = retrieve_legal_context("bảo đảm dự thầu", top_k=1, hop_depth=1)
    assert len(ctx) >= 1
    # Có ít nhất 1 node trực tiếp
    assert any(c["relation_type"] == "DIRECT_MATCH" for c in ctx)

def test_flow1_hsmt_review(mock_hsmt_doc):
    crit_list, report = review_hsmt(mock_hsmt_doc, provider="mock")
    assert report.workflow_type == "THAM_DINH_HSMT"
    assert report.total_criteria >= 3
    # Phát hiện tiêu chí bảo lãnh 5% vi phạm trần 3%
    assert report.invalid_count >= 1
    invalid_crits = [a for a in report.assessments if a.status == ComplianceStatus.INVALID]
    assert len(invalid_crits) >= 1
    assert "vượt quá mức trần" in invalid_crits[0].reasoning or "vượt" in invalid_crits[0].reasoning

def test_flow2_hsdt_check(mock_hsmt_doc, mock_hsdt_doc):
    crit_list, _ = review_hsmt(mock_hsmt_doc, provider="mock")
    report = check_hsdt(mock_hsdt_doc, crit_list, hsmt_doc=mock_hsmt_doc, provider="mock")
    assert report.workflow_type == "KIEM_TRA_HSDT"
    assert report.total_criteria >= 3
    # Có đủ 3 trạng thái
    assert report.valid_count >= 1
    assert report.invalid_count >= 1
    assert report.insufficient_count >= 1

def test_fastapi_endpoints(mock_hsmt_doc, mock_hsdt_doc):
    client = TestClient(app)

    # 1. Health
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    # 2. Re-index
    res_idx = client.post("/api/v1/graph/reindex")
    assert res_idx.status_code == 200
    assert res_idx.json()["success"] is True

    # 3. Review HSMT
    res_hsmt = client.post("/api/v1/hsmt/review?provider=mock", json=mock_hsmt_doc.model_dump())
    assert res_hsmt.status_code == 200
    hsmt_data = res_hsmt.json()
    assert "criteria" in hsmt_data
    assert "report" in hsmt_data
    assert hsmt_data["report"]["invalid_count"] >= 1

    # 4. Check HSDT
    payload = {
        "hsdt_doc": mock_hsdt_doc.model_dump(),
        "criteria_list": hsmt_data["criteria"],
        "hsmt_doc": mock_hsmt_doc.model_dump(),
        "provider": "mock"
    }
    res_hsdt = client.post("/api/v1/hsdt/check", json=payload)
    assert res_hsdt.status_code == 200
    hsdt_report = res_hsdt.json()
    assert hsdt_report["total_criteria"] >= 3
    assert hsdt_report["valid_count"] >= 1
    assert hsdt_report["invalid_count"] >= 1
    assert hsdt_report["insufficient_count"] >= 1
