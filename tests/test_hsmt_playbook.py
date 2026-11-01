import pytest
from pathlib import Path

from src.schemas.document import ParsedDocument
from src.schemas.report import ComplianceStatus
from src.schemas.playbook import HSMTAuditPlaybook
from src.engines.hsmt_reviewer import review_hsmt, load_default_playbook


@pytest.fixture
def sample_hsmt_doc():
    sample_path = Path("data/mock_hsmt/hsmt_sample.json")
    return ParsedDocument.model_validate_json(sample_path.read_text(encoding="utf-8"))


def test_load_default_playbook():
    playbook = load_default_playbook()
    assert playbook is not None
    assert len(playbook.guides) >= 5
    guide_ids = [g.guide_id for g in playbook.guides]
    assert "PB_01" in guide_ids
    assert "PB_02" in guide_ids
    assert "PB_05" in guide_ids


def test_review_hsmt_with_playbook_detects_illegal_guarantee(sample_hsmt_doc):
    playbook = load_default_playbook()
    criteria_list, report = review_hsmt(sample_hsmt_doc, playbook=playbook)

    assert report is not None
    assert report.total_criteria >= 1

    # Kiểm tra phát hiện tiêu chí bảo lãnh 5% vi phạm trần 3%
    invalid_assessments = [a for a in report.assessments if a.status == ComplianceStatus.INVALID]
    assert len(invalid_assessments) >= 1

    guarantee_assessment = next(
        (a for a in report.assessments if "bảo đảm" in a.criterion_name.lower() or "bảo lãnh" in a.criterion_name.lower()),
        None
    )
    assert guarantee_assessment is not None
    assert guarantee_assessment.status == ComplianceStatus.INVALID
    assert "Điều 14" in guarantee_assessment.reasoning or "3" in guarantee_assessment.reasoning
    assert guarantee_assessment.playbook_guide_used is not None
    assert guarantee_assessment.user_decision == ComplianceStatus.INVALID


def test_human_decision_update(sample_hsmt_doc):
    playbook = load_default_playbook()
    _, report = review_hsmt(sample_hsmt_doc, playbook=playbook)

    first_assessment = report.assessments[0]
    first_assessment.user_decision = ComplianceStatus.VALID
    first_assessment.user_decision_note = "Đã rà soát thực tế, chấp thuận điều khoản."

    assert first_assessment.user_decision == ComplianceStatus.VALID
    assert "chấp thuận" in first_assessment.user_decision_note


def test_review_virtual_hospital_hsmt_10_criteria():
    hospital_path = Path("data/mock_hsmt/hsmt_benh_vien_da_khoa_2026.json")
    assert hospital_path.exists()
    doc = ParsedDocument.model_validate_json(hospital_path.read_text(encoding="utf-8"))
    playbook = load_default_playbook()

    assert len(playbook.guides) == 10
    crit_list, report = review_hsmt(doc, provider="mock", playbook=playbook)

    assert report.total_criteria == 10
    assert report.valid_count == 3
    assert report.invalid_count == 6
    assert report.insufficient_count == 1
    assert all(len(a.references) >= 1 for a in report.assessments)
