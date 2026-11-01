import pytest
import networkx as nx

from src.schemas.document import ParsedDocument, DocumentSection, DocRole, DocumentMetadata
from src.graph_rag.citation_parser import LegalCitationParser, CitationMatch
from src.converters.structure_chunker import StructureChunker, LegalChunk
from src.graph_rag.expander import GraphExpander


# ==============================================================================
# TEST SUITE 1: LegalCitationParser
# ==============================================================================

def test_citation_parser_extracts_in_text_references():
    text = (
        "Bảo đảm dự thầu được thực hiện theo quy định tại Điều 14 của Luật Đấu thầu số 22/2023/QH15. "
        "Ngoài ra nhà thầu phải tuân thủ điều kiện tại khoản 2 Điều 19 và điểm b khoản 1 Điều 43."
    )
    citations = LegalCitationParser.extract_citations(text)
    assert len(citations) >= 3

    # Check Điều 14 Luật 22/2023/QH15
    ref_14 = next((c for c in citations if c.article_number == "14"), None)
    assert ref_14 is not None
    assert ref_14.relation_type == "REFERENCES"
    assert ref_14.doc_number == "22/2023/QH15"

    # Check Điều 19
    ref_19 = next((c for c in citations if c.article_number == "19"), None)
    assert ref_19 is not None
    assert ref_19.clause_number == "2"


def test_citation_parser_extracts_details_and_amends():
    text = (
        "Nghị định này quy định chi tiết thi hành một số điều của Luật số 22/2023/QH15. "
        "Đồng thời sửa đổi, bổ sung Điều 18 Nghị định số 214/2024/NĐ-CP."
    )
    citations = LegalCitationParser.extract_citations(text)
    
    details = [c for c in citations if c.relation_type == "DETAILS"]
    assert len(details) >= 1
    assert details[0].doc_number == "22/2023/QH15"

    amends = [c for c in citations if c.relation_type == "AMENDS"]
    assert len(amends) >= 1
    assert amends[0].article_number == "18"
    assert amends[0].doc_number == "214/2024/NĐ-CP"


def test_citation_parser_enriches_graph():
    G = nx.DiGraph()
    G.add_node(
        "DOC1::SEC1",
        doc_id="DOC1",
        file_name="Luat_Dau_Thau_22_2023_QH15.pdf",
        heading="Điều 14. Bảo đảm dự thầu",
        section_id="SEC1",
        content_markdown="Bảo đảm dự thầu thực hiện theo Điều 19."
    )
    G.add_node(
        "DOC1::SEC2",
        doc_id="DOC1",
        file_name="Luat_Dau_Thau_22_2023_QH15.pdf",
        heading="Điều 19. Thời hạn hiệu lực của hồ sơ dự thầu",
        section_id="SEC2",
        content_markdown="Thời hạn hiệu lực được tính theo ngày đóng thầu."
    )
    
    LegalCitationParser.enrich_graph_with_citations(G, [])
    assert G.has_edge("DOC1::SEC1", "DOC1::SEC2")
    edge_data = G.get_edge_data("DOC1::SEC1", "DOC1::SEC2")
    assert edge_data["relation_type"] == "REFERENCES"
    assert "Điều 19" in edge_data["evidence_text"]


# ==============================================================================
# TEST SUITE 2: StructureChunker (Strategy A3)
# ==============================================================================

def test_structure_chunker_context_header_injection():
    doc = ParsedDocument(
        doc_id="LAW_TEST_01",
        doc_role=DocRole.LAW,
        file_name="Luat_Dau_Thau_Sample.pdf",
        total_pages=3,
        metadata=DocumentMetadata(),
        sections=[
            DocumentSection(
                section_id="SEC_CH1",
                parent_id=None,
                heading="Chương I: Quy định chung",
                page_start=1,
                page_end=1,
                content_markdown="Chương này quy định về phạm vi điều chỉnh và đối tượng áp dụng."
            ),
            DocumentSection(
                section_id="SEC_ART14",
                parent_id="SEC_CH1",
                heading="Điều 14: Bảo đảm dự thầu",
                page_start=2,
                page_end=2,
                content_markdown=(
                    "Khoản 1. Nhà thầu phải thực hiện một trong các biện pháp bảo đảm dự thầu.\n"
                    "Khoản 2. Giá trị bảo đảm dự thầu được quy định từ 1% đến 3% giá gói thầu."
                )
            )
        ]
    )

    chunker = StructureChunker(max_tokens=20)  # Thấp để ép rã theo Khoản
    chunks = chunker.chunk_document(doc)

    assert len(chunks) >= 2
    # Kiểm tra chunk đã được tiêm Context Header
    art14_chunks = [c for c in chunks if "SEC_ART14" in c.chunk_id]
    assert len(art14_chunks) >= 1
    
    first_chunk = art14_chunks[0]
    assert "Văn bản Luật: Luat_Dau_Thau_Sample.pdf" in first_chunk.injected_header
    assert "Chương I: Quy định chung > Điều 14: Bảo đảm dự thầu" in first_chunk.structural_path
    assert first_chunk.content_with_header.startswith(first_chunk.injected_header)
    assert first_chunk.token_count > 0


def test_structure_chunker_compute_stats():
    chunks = [
        LegalChunk(
            chunk_id="C1",
            doc_id="D1",
            section_id="S1",
            parent_id=None,
            structural_path="Path 1",
            heading="Heading 1",
            injected_header="Header 1",
            content="Content 1",
            content_with_header="Header 1\nContent 1",
            token_count=50,
            level="ARTICLE"
        ),
        LegalChunk(
            chunk_id="C2",
            doc_id="D1",
            section_id="S2",
            parent_id=None,
            structural_path="Path 2",
            heading="Heading 2",
            injected_header="Header 2",
            content="Content 2",
            content_with_header="Header 2\nContent 2",
            token_count=120,
            level="CLAUSE"
        )
    ]
    stats = StructureChunker.compute_stats(chunks)
    assert stats["total_chunks"] == 2
    assert stats["token_min"] == 50
    assert stats["token_max"] == 120
    assert stats["level_distribution"]["ARTICLE"] == 1
    assert stats["level_distribution"]["CLAUSE"] == 1


# ==============================================================================
# TEST SUITE 3: GraphExpander
# ==============================================================================

def test_graph_expander_multihop_and_decay():
    G = nx.DiGraph()
    G.add_node("N1", heading="Điều 14: Bảo đảm dự thầu", content_markdown="Quy định bảo đảm dự thầu", file_name="Luat_Dau_Thau.pdf", page_start=5)
    G.add_node("N2", heading="Điều 19: Hiệu lực HSDT", content_markdown="Quy định hiệu lực", file_name="Luat_Dau_Thau.pdf", page_start=8)
    G.add_node("N3", heading="Điều 24: Gia hạn hiệu lực", content_markdown="Quy định gia hạn bảo lãnh", file_name="Luat_Dau_Thau.pdf", page_start=12)

    G.add_edge("N1", "N2", relation="REFERENCES", relation_type="REFERENCES", evidence_text="Dẫn chiếu theo Điều 19")
    G.add_edge("N2", "N3", relation="REFERENCES", relation_type="REFERENCES", evidence_text="Dẫn chiếu theo Điều 24")

    expander = GraphExpander(graph=G, decay_factor=0.7)
    seed = [{
        "node_id": "N1",
        "clause_id": "Điều 14: Bảo đảm dự thầu",
        "score": 1.0,
        "relation_type": "DIRECT_MATCH"
    }]

    # 1-hop expansion
    res_1hop = expander.expand(query="bảo đảm dự thầu", seed_nodes=seed, max_hops=1)
    res_node_ids_1 = [r["node_id"] for r in res_1hop]
    assert "N1" in res_node_ids_1
    assert "N2" in res_node_ids_1
    assert "N3" not in res_node_ids_1  # 1-hop chưa chạm tới N3

    # Kiểm tra expansion_path của N2
    n2_item = next(r for r in res_1hop if r["node_id"] == "N2")
    assert "REFERENCES" in n2_item["expansion_path"]
    assert n2_item["score"] < 1.0  # Điểm đã bị decay theo hệ số 0.7

    # 2-hop expansion
    res_2hop = expander.expand(query="gia hạn bảo đảm", seed_nodes=seed, max_hops=2)
    res_node_ids_2 = [r["node_id"] for r in res_2hop]
    assert "N3" in res_node_ids_2


def test_graph_expander_annotate_inter_node_relations():
    G = nx.DiGraph()
    G.add_node("A", heading="Điều A")
    G.add_node("B", heading="Điều B")
    G.add_edge("A", "B", relation="DETAILS", evidence_text="Hướng dẫn chi tiết")

    expander = GraphExpander(graph=G)
    results = [
        {"node_id": "A", "clause_id": "Điều A", "expansion_path": ""},
        {"node_id": "B", "clause_id": "Điều B", "expansion_path": ""}
    ]

    expander.annotate_inter_node_relations(results)
    assert "Dẫn chiếu [DETAILS] tới Điều B" in results[0]["expansion_path"]
    assert results[0]["evidence_text"] == "Hướng dẫn chi tiết"


# ==============================================================================
# TEST SUITE 4: Visualizer (Dark Theme PyVis like test-kg-rag)
# ==============================================================================

def test_pyvis_visualizer_dark_theme_generation():
    from src.graph_rag.visualizer import build_pyvis_html, get_graph_edges_data

    G = nx.DiGraph()
    G.add_node("DIEU_14", heading="Điều 14: Bảo đảm dự thầu", content_markdown="Quy định bảo lãnh", file_name="Luat_143.pdf")
    G.add_node("DIEU_18", heading="Điều 18: Tính hợp lệ", content_markdown="Quy định hợp lệ", file_name="Luat_143.pdf")
    G.add_edge("DIEU_18", "DIEU_14", relation_type="REFERENCES", relation="REFERENCES", evidence_text="Dẫn chiếu theo Điều 14")

    html = build_pyvis_html(G, center_node_id="DIEU_14", max_hops=1, physics=True)
    assert "bgcolor" in html or "#0e1117" in html
    assert "DIEU_14" in html
    assert "DIEU_18" in html

    edges_data = get_graph_edges_data(G)
    assert len(edges_data) == 1
    assert edges_data[0]["Loại quan hệ (Relation)"] == "REFERENCES"
    assert "Điều 14" in edges_data[0]["Điều khoản đích (Target)"]

