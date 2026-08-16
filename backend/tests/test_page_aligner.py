from pathlib import Path
import pytest
from app.domain.document_structure import ParsedPage, TextBlockData
from app.services.pdf_parser import PDFParser
from app.services.page_aligner import (
    AlignedPagePair,
    AlignedPageRow,
    AlignmentStatus,
    PageAligner,
)


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("Could not find repository root containing src/ directory")


REPO_ROOT = _find_repo_root()
SRC_PDF_1 = REPO_ROOT / "src/완성까지 가던 교정본들/11.8-본문-1차 교정/11.8-115집 논산 산노리 산17-1번지 유적-본문-1차 교정.pdf"
SRC_PDF_2 = REPO_ROOT / "src/완성까지 가던 교정본들/11.19-2차 교정/11.19-115집 논산 산노리 산17-1번지 유적-본문-2차 교정.pdf"
SRC_PDF_3 = REPO_ROOT / "src/완성까지 가던 교정본들/11.21-3차 교정/11.21-115집 논산 산노리 산17-1번지 유적-본문-3차 교정.pdf"


def _make_dummy_page(page_num: int, text: str) -> ParsedPage:
    return ParsedPage(
        physical_page=page_num,
        printed_page=page_num,
        header="",
        raw_text=text,
        normalized_text=text,
        text_blocks=[
            TextBlockData(
                block_id=f"b_{page_num}_0",
                text=text,
                normalized_text=text,
                order=0,
                block_type="paragraph",
            )
        ],
        captions=[],
    )


def test_page_aligner_weighted_similarity():
    aligner = PageAligner()
    s1 = "2지점 시대미상 2호 토광묘는 해발 42.80m에 조성되었으며"
    s2 = "2지점 시대미상 2호 토광묘는 해발 42.80m에 조성되었으며"
    assert aligner.calculate_weighted_similarity(s1, s2) == pytest.approx(1.0)
    assert aligner.weighted_similarity(s1, s2) == pytest.approx(1.0)
    assert aligner._jaccard_similarity({"a", "b"}, {"a", "b"}) == pytest.approx(1.0)

    s3 = "완전히 다른 내용의 문장입니다."
    assert aligner.calculate_weighted_similarity(s1, s3) < 0.2
    assert aligner.weighted_similarity(s1, s3) < 0.2


def test_page_aligner_aligns_real_sample_pages():
    parser = PDFParser()
    p1 = parser.parse_page_range(SRC_PDF_1, 105, 114)
    p2 = parser.parse_page_range(SRC_PDF_2, 111, 120)
    p3 = parser.parse_page_range(SRC_PDF_3, 126, 135)

    aligner = PageAligner()
    version_dict = {
        "1차": p1,
        "2차": p2,
        "3차": p3,
    }
    rows = aligner.align_parallel_ranges(version_dict)
    assert len(rows) == 10

    for idx, row in enumerate(rows):
        assert isinstance(row, AlignedPageRow)
        assert row.row_id == idx + 1
        assert "1차" in row.pages
        assert "2차" in row.pages
        assert "3차" in row.pages
        assert row.pages["1차"] is not None
        assert row.pages["2차"] is not None
        assert row.pages["3차"] is not None
        assert row.pages["1차"].physical_page == 105 + idx
        assert row.pages["2차"].physical_page == 111 + idx
        assert row.pages["3차"].physical_page == 126 + idx
        assert row.similarity_score > 0.8
        assert row.sequence_matcher_ratio > 0.9


def test_page_aligner_unequal_page_counts():
    """Verify alignment works correctly when versions have different page counts."""
    p_a = _make_dummy_page(1, "논산 산노리 유적 1호 토광묘 조사 개요 및 위치 정보")
    p_b = _make_dummy_page(2, "유구 확인 결과 풍화암반층을 굴착하여 장방형 평면으로 축조함")
    p_c = _make_dummy_page(3, "출토유물로는 타날문토기편 및 적갈색 연질토기 구연부가 수습됨")
    p_d = _make_dummy_page(4, "결론 및 향후 보존 대책에 관한 고찰")

    # 1차 has 3 pages (A, B, C)
    # 2차 has 4 pages (A, B, C, D) - extra trailing page
    v1 = [p_a, p_b, p_c]
    v2 = [p_a, p_b, p_c, p_d]

    aligner = PageAligner()
    rows = aligner.align_parallel_ranges({"1차": v1, "2차": v2})

    assert len(rows) == 4
    # Rows 1-3 are 1:1 matches
    for i in range(3):
        assert rows[i].pages["1차"] == v1[i]
        assert rows[i].pages["2차"] == v2[i]
        assert rows[i].similarity_score == pytest.approx(1.0)

    # Row 4 is trailing page in 2차, gap in 1차
    assert rows[3].pages["1차"] is None
    assert rows[3].pages["2차"] == p_d
    assert rows[3].similarity_score == pytest.approx(0.0)


def test_page_aligner_inserted_page_creates_none_gap_in_reference():
    """Verify that an inserted page in a newer version creates a None gap in the reference sequence."""
    p_a = _make_dummy_page(1, "1지점 발굴조사 개요와 지형 환경 분석")
    p_ins = _make_dummy_page(2, "도면 57 산노리 2호 토광묘 평단면도 및 실측도 삽입 페이지")
    p_b = _make_dummy_page(3, "유구의 규모는 길이 240cm 너비 120cm 잔존깊이 35cm이다")
    p_c = _make_dummy_page(4, "동쪽 단벽에서 완형에 가까운 호형토기가 출토되었다")

    # Reference (1차) has A, B, C (3 pages)
    # 2차 has A, INSERTED, B, C (4 pages)
    v1 = [p_a, p_b, p_c]
    v2 = [p_a, p_ins, p_b, p_c]

    aligner = PageAligner()
    rows = aligner.align_parallel_ranges({"1차": v1, "2차": v2})

    assert len(rows) == 4
    # Row 1: A matches A
    assert rows[0].pages["1차"] == p_a
    assert rows[0].pages["2차"] == p_a
    assert rows[0].similarity_score == pytest.approx(1.0)

    # Row 2: None in 1차 (gap), inserted page in 2차
    assert rows[1].pages["1차"] is None
    assert rows[1].pages["2차"] == p_ins
    assert rows[1].similarity_score == pytest.approx(0.0)

    # Row 3: B matches B
    assert rows[2].pages["1차"] == p_b
    assert rows[2].pages["2차"] == p_b
    assert rows[2].similarity_score == pytest.approx(1.0)

    # Row 4: C matches C
    assert rows[3].pages["1차"] == p_c
    assert rows[3].pages["2차"] == p_c
    assert rows[3].similarity_score == pytest.approx(1.0)


def test_page_aligner_real_pages_unequal_slices():
    """Verify alignment on unequal slices of real PDF pages."""
    parser = PDFParser()
    p1 = parser.parse_page_range(SRC_PDF_1, 105, 108)  # 4 pages
    p2 = parser.parse_page_range(SRC_PDF_2, 111, 115)  # 5 pages

    aligner = PageAligner()
    rows = aligner.align_parallel_ranges({"1차": p1, "2차": p2})

    assert len(rows) == 5
    for i in range(4):
        assert rows[i].pages["1차"] is not None
        assert rows[i].pages["2차"] is not None
        assert rows[i].pages["1차"].physical_page == 105 + i
        assert rows[i].pages["2차"].physical_page == 111 + i
        assert rows[i].similarity_score > 0.8

    assert rows[4].pages["1차"] is None
    assert rows[4].pages["2차"] is not None
    assert rows[4].pages["2차"].physical_page == 115


def test_page_aligner_three_versions_with_insertions():
    """Verify 3-way alignment merges pairwise alignments with inserted pages correctly."""
    p_a = _make_dummy_page(1, "1지점 발굴조사 개요와 지형 환경 분석")
    p_ins1 = _make_dummy_page(2, "도면 57 산노리 2호 토광묘 평단면도 2차 삽입 페이지")
    p_ins2 = _make_dummy_page(3, "도판 15 유물 사진 추가 3차 삽입 페이지")
    p_b = _make_dummy_page(4, "유구의 규모는 길이 240cm 너비 120cm 잔존깊이 35cm이다")

    # 1차: [A, B]
    # 2차: [A, INS1, B]
    # 3차: [A, INS1, INS2, B]
    v1 = [p_a, p_b]
    v2 = [p_a, p_ins1, p_b]
    v3 = [p_a, p_ins1, p_ins2, p_b]

    aligner = PageAligner()
    rows = aligner.align_parallel_ranges({"1차": v1, "2차": v2, "3차": v3})

    assert len(rows) == 4
    # Row 1: A, A, A
    assert rows[0].pages["1차"] == p_a
    assert rows[0].pages["2차"] == p_a
    assert rows[0].pages["3차"] == p_a

    # Row 2: None, INS1, INS1
    assert rows[1].pages["1차"] is None
    assert rows[1].pages["2차"] == p_ins1
    assert rows[1].pages["3차"] == p_ins1

    # Row 3: None, None, INS2
    assert rows[2].pages["1차"] is None
    assert rows[2].pages["2차"] is None
    assert rows[2].pages["3차"] == p_ins2

    # Row 4: B, B, B
    assert rows[3].pages["1차"] == p_b
    assert rows[3].pages["2차"] == p_b
    assert rows[3].pages["3차"] == p_b


def test_page_aligner_deleted_page_creates_none_gap_in_other_version():
    """Verify that a page deleted in a newer version creates a None gap in that version."""
    p_a = _make_dummy_page(1, "1지점 발굴조사 개요와 지형 환경 분석")
    p_del = _make_dummy_page(2, "삭제될 예정인 임시 초안 페이지 내용")
    p_b = _make_dummy_page(3, "유구의 규모는 길이 240cm 너비 120cm 잔존깊이 35cm이다")

    # 1차: [A, DEL, B]
    # 2차: [A, B]
    v1 = [p_a, p_del, p_b]
    v2 = [p_a, p_b]

    aligner = PageAligner()
    rows = aligner.align_parallel_ranges({"1차": v1, "2차": v2})

    assert len(rows) == 3
    assert rows[0].pages["1차"] == p_a
    assert rows[0].pages["2차"] == p_a

    assert rows[1].pages["1차"] == p_del
    assert rows[1].pages["2차"] is None

    assert rows[2].pages["1차"] == p_b
    assert rows[2].pages["2차"] == p_b


def test_alignment_status_enum_values_and_classification():
    """Verify AlignmentStatus values and classification thresholds."""
    assert AlignmentStatus.EXACT == "exact"
    assert AlignmentStatus.PROBABLE == "probable"
    assert AlignmentStatus.MANUAL_REVIEW == "manual_review"
    assert AlignmentStatus.UNMATCHED == "unmatched"

    aligner = PageAligner()

    # Exact matches: similarity >= 0.85
    assert aligner.classify_status(1.0) == AlignmentStatus.EXACT
    assert aligner.classify_status(0.90) == AlignmentStatus.EXACT
    assert aligner.classify_status(0.85) == AlignmentStatus.EXACT

    # Probable matches: 0.60 <= similarity < 0.85
    assert aligner.classify_status(0.84) == AlignmentStatus.PROBABLE
    assert aligner.classify_status(0.70) == AlignmentStatus.PROBABLE
    assert aligner.classify_status(0.60) == AlignmentStatus.PROBABLE

    # Manual review: 0.30 <= similarity < 0.60
    assert aligner.classify_status(0.59) == AlignmentStatus.MANUAL_REVIEW
    assert aligner.classify_status(0.45) == AlignmentStatus.MANUAL_REVIEW
    assert aligner.classify_status(0.30) == AlignmentStatus.MANUAL_REVIEW

    # Unmatched: similarity < 0.30 or has_gap
    assert aligner.classify_status(0.29) == AlignmentStatus.UNMATCHED
    assert aligner.classify_status(0.0) == AlignmentStatus.UNMATCHED
    assert aligner.classify_status(0.95, has_gap=True) == AlignmentStatus.UNMATCHED


def test_unrelated_pages_rejection():
    """Verify DTW / pairwise alignment rejects unrelated pages and assigns unmatched or manual_review status."""
    p_arch = _make_dummy_page(
        1, "논산 산노리 유적 1호 토광묘 발굴조사 개요 및 지형 환경 분석 풍화암반층 축조"
    )
    p_astronomy = _make_dummy_page(
        1, "천문 관측 기록 망원경 분광기 항성 분광형 분류 적색왜성 흑점 주기"
    )

    aligner = PageAligner()

    # Pairwise align single pair
    pair = aligner.align_page_pair(p_arch, p_astronomy)
    assert isinstance(pair, AlignedPagePair)
    assert pair.page_a == p_arch
    assert pair.page_b == p_astronomy
    assert pair.similarity_score < 0.30
    assert pair.status in (AlignmentStatus.UNMATCHED, AlignmentStatus.MANUAL_REVIEW)
    assert pair.status == AlignmentStatus.UNMATCHED
    assert pair.method != ""

    # Pairwise list alignment
    pairs = aligner.align_pairwise([p_arch], [p_astronomy])
    assert len(pairs) == 1
    assert pairs[0].status == AlignmentStatus.UNMATCHED
    assert pairs[0].similarity_score < 0.30

    # Multi-page parallel range alignment
    rows = aligner.align_parallel_ranges({"1차": [p_arch], "2차": [p_astronomy]})
    assert len(rows) == 1
    assert rows[0].status == AlignmentStatus.UNMATCHED
    assert rows[0].similarity_score < 0.30


def test_partially_similar_pages_categorization():
    """Verify moderately revised pages are marked probable or manual_review rather than exact or unmatched."""
    p1 = _make_dummy_page(
        1,
        "논산 산노리 유적 1호 토광묘는 길이 240cm 너비 120cm 잔존깊이 35cm의 장방형 토광묘로 풍화암반층을 굴착하여 조성되었다. 출토유물로는 타날문토기편과 경질토기편이 수습되었다.",
    )
    # Page with revised measurements and additional sentences (moderate overlap ~0.70)
    p2 = _make_dummy_page(
        1,
        "논산 산노리 유적 1호 토광묘는 길이 245cm 너비 125cm 잔존깊이 40cm의 장방형 토광묘로 풍화암반층을 굴착하여 축조되었다. 출토유물로는 타날문토기편과 연질토기편이 수습되었다. 바닥면에는 목관 흔적이 관찰된다.",
    )

    aligner = PageAligner()
    pair = aligner.align_page_pair(p1, p2)
    assert 0.30 <= pair.similarity_score < 0.85
    assert pair.status in (AlignmentStatus.PROBABLE, AlignmentStatus.MANUAL_REVIEW)
    assert pair.status != AlignmentStatus.EXACT
    assert pair.status != AlignmentStatus.UNMATCHED



def test_multi_version_alignment_safety():
    """Verify multi-version alignment tracks status per row and handles gaps and unrelated pages safely."""
    p_a = _make_dummy_page(1, "논산 산노리 유적 1호 토광묘 조사 개요 및 위치 정보")
    p_b = _make_dummy_page(2, "유구 확인 결과 풍화암반층을 굴착하여 장방형 평면으로 축조함")
    p_c = _make_dummy_page(3, "출토유물로는 타날문토기편 및 적갈색 연질토기 구연부가 수습됨")
    p_unrelated = _make_dummy_page(2, "완전히 엉뚱한 다른 문서의 내용 주식 시장 투자 분석 보고서")

    aligner = PageAligner()

    # 3 versions: v1=[A, B, C], v2=[A, B, C], v3=[A, unrelated, C]
    rows = aligner.align_parallel_ranges(
        {"1차": [p_a, p_b, p_c], "2차": [p_a, p_b, p_c], "3차": [p_a, p_unrelated, p_c]}
    )

    assert len(rows) == 3
    # Row 1 (A, A, A) should be EXACT
    assert rows[0].status == AlignmentStatus.EXACT
    assert rows[0].similarity_score > 0.85

    # Row 2 (B, B, unrelated) has a non-matching page in 3차 -> UNMATCHED or MANUAL_REVIEW
    assert rows[1].status in (AlignmentStatus.UNMATCHED, AlignmentStatus.MANUAL_REVIEW)

    # Row 3 (C, C, C) should be EXACT
    assert rows[2].status == AlignmentStatus.EXACT
    assert rows[2].similarity_score > 0.85


def test_aligned_page_pair_with_gap_pages():
    """Verify AlignedPagePair handles None pages gracefully with unmatched status."""
    p_a = _make_dummy_page(1, "논산 산노리 유적 조사 내용")
    aligner = PageAligner()

    pair_gap_b = aligner.align_page_pair(p_a, None)
    assert pair_gap_b.page_a == p_a
    assert pair_gap_b.page_b is None
    assert pair_gap_b.similarity_score == 0.0
    assert pair_gap_b.status == AlignmentStatus.UNMATCHED

    pair_gap_a = aligner.align_page_pair(None, p_a)
    assert pair_gap_a.page_a is None
    assert pair_gap_a.page_b == p_a
    assert pair_gap_a.similarity_score == 0.0
    assert pair_gap_a.status == AlignmentStatus.UNMATCHED


def test_single_version_alignment_row_status():
    """Verify single version parallel range creates rows with EXACT status."""
    p_a = _make_dummy_page(1, "논산 산노리 유적 1호 토광묘 조사 개요")
    aligner = PageAligner()
    rows = aligner.align_parallel_ranges({"1차": [p_a]})
    assert len(rows) == 1
    assert rows[0].status == AlignmentStatus.EXACT
    assert rows[0].similarity_score == 1.0


def test_align_pairwise_multi_page_with_insertions_and_rejection():
    """Verify align_pairwise processes multi-page lists with insertions and status categorization."""
    p1 = _make_dummy_page(1, "논산 산노리 1호 토광묘 평면도 및 위치도")
    p2 = _make_dummy_page(2, "유구 확인 결과 및 단면 토층 분석")
    p_ins = _make_dummy_page(2, "신규 발굴 추가 조사 내용")
    p_unrel = _make_dummy_page(3, "완전히 무관한 주식 금융 보고서 내용")

    aligner = PageAligner()
    pairs = aligner.align_pairwise([p1, p2], [p1, p_ins, p_unrel])

    # p1 matches p1
    assert pairs[0].page_a == p1
    assert pairs[0].page_b == p1
    assert pairs[0].status == AlignmentStatus.EXACT

    # Check statuses across the alignment results
    for p in pairs:
        assert isinstance(p, AlignedPagePair)
        assert p.status in (
            AlignmentStatus.EXACT,
            AlignmentStatus.PROBABLE,
            AlignmentStatus.MANUAL_REVIEW,
            AlignmentStatus.UNMATCHED,
        )


def test_dtw_unrelated_pages_never_confident():
    """Unrelated pages must never be classified exact/probable by DTW."""
    p_arch = _make_dummy_page(
        1, "논산 산노리 유적 1호 토광묘 발굴조사 개요 및 지형 환경 분석"
    )
    p_astronomy = _make_dummy_page(
        1, "천문 관측 기록 망원경 분광기 항성 분광형 분류 적색왜성 흑점 주기"
    )
    aligner = PageAligner()
    pairs = aligner.align_pairwise([p_arch], [p_astronomy])
    for p in pairs:
        assert p.status in (AlignmentStatus.UNMATCHED, AlignmentStatus.MANUAL_REVIEW)
        assert p.status not in (AlignmentStatus.EXACT, AlignmentStatus.PROBABLE)


def test_dtw_tie_break_prefers_gap_for_unrelated_pages():
    """When match cost ties with gap cost for unrelated pages, DTW must prefer
    a gap over manufacturing a diagonal match (plan Task 8 DTW fix)."""
    p_arch = _make_dummy_page(
        1, "논산 산노리 유적 1호 토광묘 발굴조사 개요 및 지형 환경 분석"
    )
    p_astronomy = _make_dummy_page(
        1, "천문 관측 기록 망원경 분광기 항성 분광형 분류 적색왜성 흑점 주기"
    )
    aligner = PageAligner()
    # gap_cost=0.5 makes the diagonal match cost (1.0) tie with the accumulated
    # gap cost, so the old tie-break would emit a diagonal match between
    # unrelated pages. The fix must prefer a gap instead.
    pairs = aligner.align_pairwise([p_arch], [p_astronomy, p_astronomy], gap_cost=0.5)
    assert not any(p.page_a is not None and p.page_b is not None for p in pairs)
    for p in pairs:
        assert p.status in (AlignmentStatus.UNMATCHED, AlignmentStatus.MANUAL_REVIEW)


