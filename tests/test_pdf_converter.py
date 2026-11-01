from pathlib import Path
import pytest
from src.schemas.document import DocRole, DocCategory, ParsedDocument
from src.converters.pdf_converter import (
    convert_pdf_to_parsed_document,
    save_parsed_document_to_json,
)

SAMPLE_PDF = Path("data_law/43-2024-qh15.pdf")

def test_convert_law_pdf():
    assert SAMPLE_PDF.exists(), "File mẫu data_law/43-2024-qh15.pdf phải tồn tại"
    doc = convert_pdf_to_parsed_document(
        pdf_source=SAMPLE_PDF,
        doc_role=DocRole.LAW,
        file_name="43-2024-qh15.pdf"
    )

    assert isinstance(doc, ParsedDocument)
    assert doc.doc_role == DocRole.LAW
    assert doc.total_pages == 2
    assert len(doc.sections) >= 4
    
    # Kiểm tra các điều khoản luật được bóc tách
    headings = [s.heading for s in doc.sections]
    assert any("Điều 1" in h or "DIEU_1" in s.section_id for s, h in zip(doc.sections, headings))
    assert any("Điều 2" in h or "DIEU_2" in s.section_id for s, h in zip(doc.sections, headings))

    # Kiểm tra số trang được đánh dấu
    for sec in doc.sections:
        assert sec.page_start >= 1
        assert sec.page_end >= sec.page_start
        assert len(sec.content_markdown) > 0

def test_convert_hsmt_pdf():
    doc = convert_pdf_to_parsed_document(
        pdf_source=SAMPLE_PDF,
        doc_role=DocRole.HSMT,
        file_name="sample_hsmt.pdf"
    )
    assert doc.doc_role == DocRole.HSMT
    assert len(doc.sections) >= 1

def test_convert_hsdt_pdf():
    doc = convert_pdf_to_parsed_document(
        pdf_source=SAMPLE_PDF,
        doc_role=DocRole.HSDT,
        file_name="sample_hsdt.pdf"
    )
    assert doc.doc_role == DocRole.HSDT
    assert len(doc.sections) >= 1

def test_save_and_reload_json(tmp_path):
    doc = convert_pdf_to_parsed_document(
        pdf_source=SAMPLE_PDF,
        doc_role=DocRole.LAW
    )
    out_file = tmp_path / "test_output.json"
    save_parsed_document_to_json(doc, out_file)

    assert out_file.exists()
    reloaded = ParsedDocument.model_validate_json(out_file.read_text(encoding="utf-8"))
    assert reloaded.doc_id == doc.doc_id
    assert len(reloaded.sections) == len(doc.sections)

def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        convert_pdf_to_parsed_document("non_existent_file.pdf")
