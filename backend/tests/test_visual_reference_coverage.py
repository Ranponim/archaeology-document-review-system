from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import EvidenceData
from app.services.visual_reference_coverage import VisualReferenceCoverageService


BODY_VERSION = "body-v1"
PLATE_VERSION = "plate-v1"
DRAWING_VERSION = "drawing-v1"
RUN_ID = "run-coverage"
OBJECT_ID = "obj-6-cist"


def _object() -> ArchaeologyObjectData:
    return ArchaeologyObjectData(
        object_id=OBJECT_ID,
        site="산노리",
        point="1지점",
        type="석관묘",
        number="6호",
        canonical_name="1지점 6호 석관묘",
        project_id="project-1",
    )


def _body(region: str, text: str) -> EvidenceData:
    return EvidenceData(
        id=f"ev-body-{region}",
        kind="text_claim",
        source_sha256="body-sha",
        document_version_id=BODY_VERSION,
        page_id=f"{BODY_VERSION}-p10",
        region_id=region,
        value=text,
        analysis_run_id=RUN_ID,
        rule_name="mention_claim",
    )


def _reference(
    region: str,
    ref_type: str,
    number: str,
    *,
    resolved_target_id: str | None = None,
    resolved_target_label: str | None = None,
    resolved_depicts_object: bool = False,
    raw_text: str | None = None,
) -> EvidenceData:
    return EvidenceData(
        id=f"ev-ref-{region}-{ref_type}-{number}",
        kind="reference",
        source_sha256="body-sha",
        document_version_id=BODY_VERSION,
        page_id=f"{BODY_VERSION}-p10",
        region_id=region,
        value={
            "ref_type": ref_type,
            "number": number,
            "raw_text": raw_text or (f"도판 {number}" if ref_type == "plate" else f"도면 {number}"),
            "resolved_target_id": resolved_target_id,
            "resolved_target_label": resolved_target_label,
            "resolved_depicts_object": resolved_depicts_object,
        },
        analysis_run_id=RUN_ID,
        rule_name="reference_evidence",
    )


def _plate(number: str, *, asset_id: str | None = None) -> EvidenceData:
    asset_id = asset_id or f"plate-{number}"
    return EvidenceData(
        id=f"ev-plate-{asset_id}",
        kind="plate_caption",
        source_sha256="plate-sha",
        document_version_id=PLATE_VERSION,
        page_id=f"{PLATE_VERSION}-p45",
        region_id=asset_id,
        value={
            "label": "Plate",
            "plate_number": number,
            "title": f"6호 석관묘 조사 후 전경 {number}",
            "raw_identifier": f"【도판 {number}】",
        },
        analysis_run_id=RUN_ID,
        rule_name="plate_caption_evidence",
    )


def _panel(number: str, panel_id: str) -> EvidenceData:
    return EvidenceData(
        id=f"ev-panel-{panel_id}",
        kind="plate_caption",
        source_sha256="plate-sha",
        document_version_id=PLATE_VERSION,
        page_id=f"{PLATE_VERSION}-p45",
        region_id=panel_id,
        value={
            "label": "PlatePanel",
            "plate_number": number,
            "title": "6호 석관묘 세부 사진",
            "raw_identifier": f"【도판 {number}】",
        },
        analysis_run_id=RUN_ID,
        rule_name="plate_caption_evidence",
    )


def _drawing(number: str, *, asset_id: str | None = None) -> EvidenceData:
    asset_id = asset_id or f"drawing-{number}"
    return EvidenceData(
        id=f"ev-drawing-{asset_id}",
        kind="drawing_caption",
        source_sha256="drawing-sha",
        document_version_id=DRAWING_VERSION,
        page_id=f"{DRAWING_VERSION}-p30",
        region_id=asset_id,
        value={
            "label": "Drawing",
            "drawing_number": number,
            "title": f"6호 석관묘 평·단면도 {number}",
            "raw_identifier": f"【도면 {number}】",
        },
        analysis_run_id=RUN_ID,
        rule_name="drawing_caption_evidence",
    )


def _bundle(
    *,
    bodies: list[EvidenceData] | None = None,
    references: list[EvidenceData] | None = None,
    plates: list[EvidenceData] | None = None,
    drawings: list[EvidenceData] | None = None,
) -> ObjectEvidenceBundle:
    return ObjectEvidenceBundle(
        object_id=OBJECT_ID,
        canonical_name="1지점 6호 석관묘",
        text_claims=bodies or [],
        references=references or [],
        plate_claims=plates or [],
        drawing_claims=drawings or [],
    )


def _service() -> VisualReferenceCoverageService:
    return VisualReferenceCoverageService()


def test_missing_unique_drawing_and_plate_proposes_combined_reference() -> None:
    body = _body("b1", "6호 석관묘는 구릉 정상부에 위치한다.")
    candidates = _service().review_object(
        bundle=_bundle(bodies=[body], plates=[_plate("45")], drawings=[_drawing("30")]),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.change_type == "added"
    assert candidate.status == "pending_review"
    assert candidate.proposed_text == "(도면 30, 도판 45)"
    assert candidate.archaeology_object_id == OBJECT_ID
    assert candidate.evidence is not None
    assert candidate.evidence.rule_name == "visual_reference_missing"
    assert {ev.id for ev in candidate.evidences} >= {body.id, "ev-plate-plate-45", "ev-drawing-drawing-30"}


def test_already_covered_references_do_not_create_reverse_candidate() -> None:
    body = _body("b1", "6호 석관묘는 구릉 정상부에 위치한다. (도면 30, 도판 45)")
    candidates = _service().review_object(
        bundle=_bundle(
            bodies=[body],
            references=[
                _reference("b1", "drawing", "30", resolved_target_id="drawing-30", resolved_target_label="Drawing", resolved_depicts_object=True),
                _reference("b1", "plate", "45", resolved_target_id="plate-45", resolved_target_label="Plate", resolved_depicts_object=True),
            ],
            plates=[_plate("45")],
            drawings=[_drawing("30")],
        ),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert candidates == []


def test_blank_placeholder_with_unique_targets_is_filled_exactly() -> None:
    body = _body("b1", "6호 석관묘 (도면: , 도판: )")
    candidates = _service().review_object(
        bundle=_bundle(bodies=[body], plates=[_plate("45")], drawings=[_drawing("30")]),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.change_type == "modified"
    assert candidate.original_text == "(도면: , 도판: )"
    assert candidate.proposed_text == "(도면: 30, 도판: 45)"
    assert candidate.evidence is not None
    assert candidate.evidence.rule_name == "visual_reference_blank_fill"


def test_blank_placeholder_fills_unique_drawing_and_keeps_plate_ambiguous() -> None:
    body = _body("b1", "6호 석관묘 (도면: , 도판: )")
    candidates = _service().review_object(
        bundle=_bundle(
            bodies=[body],
            plates=[_plate("45"), _plate("46")],
            drawings=[_drawing("30")],
        ),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert len(candidates) == 2
    fill = next(c for c in candidates if c.evidence and c.evidence.rule_name == "visual_reference_blank_fill")
    ambiguous = next(c for c in candidates if c.evidence and c.evidence.rule_name == "visual_reference_ambiguous")
    assert fill.proposed_text == "(도면: 30, 도판: )"
    assert ambiguous.proposed_text is None
    assert {ev.value.get("plate_number") for ev in ambiguous.evidences if isinstance(ev.value, dict)} >= {"45", "46"}


def test_multiple_body_regions_never_choose_first_insertion_location() -> None:
    candidates = _service().review_object(
        bundle=_bundle(
            bodies=[
                _body("b1", "6호 석관묘의 위치를 설명한다."),
                _body("b2", "6호 석관묘의 구조를 설명한다."),
            ],
            plates=[_plate("45")],
        ),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.proposed_text is None
    assert candidate.evidence is not None
    assert candidate.evidence.rule_name == "visual_reference_location_ambiguous"
    assert {ev.region_id for ev in candidate.evidences if ev.kind == "text_claim"} == {"b1", "b2"}


def test_multiple_canonical_plates_never_invent_number() -> None:
    body = _body("b1", "6호 석관묘의 구조를 설명한다.")
    candidates = _service().review_object(
        bundle=_bundle(bodies=[body], plates=[_plate("45"), _plate("46")]),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.proposed_text is None
    assert candidate.evidence is not None
    assert candidate.evidence.rule_name == "visual_reference_ambiguous"


def test_wrong_existing_reference_is_replaced_not_appended() -> None:
    body = _body("b1", "6호 석관묘 (도판 44)")
    wrong = _reference(
        "b1",
        "plate",
        "44",
        resolved_target_id="plate-44",
        resolved_target_label="Plate",
        resolved_depicts_object=False,
        raw_text="도판 44",
    )
    candidates = _service().review_object(
        bundle=_bundle(bodies=[body], references=[wrong], plates=[_plate("45")]),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.change_type == "modified"
    assert candidate.original_text == "도판 44"
    assert candidate.proposed_text == "도판 45"
    assert candidate.evidence is not None
    assert candidate.evidence.rule_name == "visual_reference_wrong_target"


def test_filename_like_text_cannot_create_missing_plate_identity() -> None:
    body = _body("b1", "원천 사진 파일은 4. 조사 후_91.JPG 이다.")
    candidates = _service().review_object(
        bundle=_bundle(bodies=[body]),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert candidates == []


def test_parent_and_panel_claims_for_same_plate_number_deduplicate_identity() -> None:
    body = _body("b1", "6호 석관묘를 설명한다.")
    candidates = _service().review_object(
        bundle=_bundle(bodies=[body], plates=[_plate("45"), _panel("45", "panel-45-1")]),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert len(candidates) == 1
    assert candidates[0].proposed_text == "(도판 45)"


def test_valid_existing_reference_with_filename_decoy_needs_no_coverage_candidate() -> None:
    body = _body("b1", "6호 석관묘 (도판 45), 원천파일 _45.JPG")
    valid = _reference(
        "b1",
        "plate",
        "45",
        resolved_target_id="plate-45",
        resolved_target_label="Plate",
        resolved_depicts_object=True,
    )
    candidates = _service().review_object(
        bundle=_bundle(bodies=[body], references=[valid], plates=[_plate("45")]),
        archaeology_object=_object(),
        analysis_run_id=RUN_ID,
    )

    assert candidates == []
