import pytest
from app.graph.schema import CONSTRAINTS, ensure_schema
from app.graph.review_repository import ReviewRepository
from app.domain.document_structure import ParsedPage, TextBlockData, CaptionData
from app.domain.review_models import CorrectionCandidateData, EvidenceData


def test_schema_includes_review_nodes_constraints():
    labels = [label for _, label in CONSTRAINTS]
    assert "Page" in labels
    assert "TextBlock" in labels
    assert "Caption" in labels
    assert "CorrectionCandidate" in labels
    assert "Evidence" in labels


def test_review_repository_builds_cypher_parameters():
    page = ParsedPage(
        physical_page=105,
        printed_page=101,
        header="백제문화유산연구원 | 101",
        raw_text="2호 토광묘",
        normalized_text="2호 토광묘",
        text_blocks=[
            TextBlockData(block_id="p105_b1", text="2호 토광묘", normalized_text="2호 토광묘", order=1)
        ],
        captions=[
            CaptionData(caption_id="p105_c1", raw_text="① 유구(도면 : , 도판 : )", is_blank_reference=True)
        ]
    )
    
    cand = CorrectionCandidateData(
        candidate_id="cand_1",
        rule_category="figure_plate_table_photo_ref",
        change_type="modified",
        status="confirmed",
        original_text="도면 : ",
        proposed_text="도면 : 57",
        evidence=EvidenceData(
            version_from="1차",
            version_to="2차",
            physical_page_from=105,
            physical_page_to=111,
            printed_page_from=101,
            printed_page_to=102,
            rule_name="figure_plate_table_photo_ref",
            rationale="Filled blank drawing reference"
        )
    )
    
    # Verify repository methods exist and produce correct payload structures
    repo = ReviewRepository(driver=None)
    page_param = repo._page_to_param(version_id="ver_1", page=page)
    assert page_param["physical_page"] == 105
    assert page_param["printed_page"] == 101
    assert len(page_param["blocks"]) == 1
    assert len(page_param["captions"]) == 1
    
    cand_param = repo._candidate_to_param(cand)
    assert cand_param["candidate_id"] == "cand_1"
    assert cand_param["rule_category"] == "figure_plate_table_photo_ref"
    assert cand_param["evidence"]["version_from"] == "1차"
