from __future__ import annotations

import io
import os
import time
from collections import Counter

import fitz  # PyMuPDF
import httpx
from PIL import Image, ImageDraw

BASE_URL = os.environ.get("VALIDATION_BASE_URL", "http://localhost:18080")
POLL_TIMEOUT_SECONDS = int(os.environ.get("VALIDATION_TIMEOUT_SECONDS", "180"))
ENABLE_LIVE_VLM = os.environ.get("ENABLE_LIVE_VLM", "0") == "1"
ENABLE_LIVE_AI = os.environ.get("ENABLE_LIVE_AI", "0") == "1"
DEVELOPMENT_BUDGET = int(os.environ.get("DEVELOPMENT_CANDIDATE_BUDGET", "10"))
RAW_FINDING_FLOOR = int(os.environ.get("VALIDATION_RAW_FINDING_FLOOR", "50"))
STRESS_PAGE_COUNT = max(RAW_FINDING_FLOOR + 5, 55)


def _visual_png(label: str) -> bytes:
    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 55, 845, 465), outline="black", width=5)
    draw.line((100, 380, 800, 140), fill="black", width=5)
    draw.ellipse((315, 155, 585, 410), outline="black", width=5)
    draw.text((80, 80), label, fill="black")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def generate_sample_pdf(text_lines: list[str], *, visual_label: str | None = None) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 50
    for line in text_lines:
        page.insert_text((50, y), line, fontname="korea", fontsize=11)
        y += 25
    if visual_label:
        page.insert_image(
            fitz.Rect(50, max(y + 20, 210), 545, 650),
            stream=_visual_png(visual_label),
            keep_proportion=True,
        )
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def generate_stress_body_pdf(*, revision: int) -> bytes:
    """Generate body PDFs that force 50+ cheap deterministic findings.

    All pages belong to the same archaeological object so Graph identity stays
    simple. Page 1 and 2 deliberately retain valid publication identifiers for
    plate/drawing comparison modes. Remaining pages differ by one dimension
    value, producing many revision findings without requiring AI/VLM.
    """

    assert revision in {1, 2}
    doc = fitz.open()

    def add_page(lines: list[str]) -> None:
        page = doc.new_page(width=595, height=842)
        y = 50
        for line in lines:
            page.insert_text((50, y), line, fontname="korea", fontsize=11)
            y += 25

    add_page(
        [
            "제3장 발굴조사 내용",
            "1지점 6호 석관묘 (도판 : 45): 길이 275cm이다.",
            "1지점 6호 석관묘 (도판 : 45): 길이 245cm이다.",
        ]
    )
    add_page(
        [
            "제3장 발굴조사 내용",
            "1지점 6호 석관묘 (도면 : 30): 너비 120cm이다.",
            "1지점 6호 석관묘 (도면 : 30): 너비 80cm이다.",
        ]
    )

    base = 210 if revision == 1 else 220
    for chunk_start in range(1, STRESS_PAGE_COUNT + 1, 5):
        lines = ["제3장 발굴조사 내용"]
        for index in range(chunk_start, min(chunk_start + 5, STRESS_PAGE_COUNT + 1)):
            lines.append(f"1지점 {index}호 석관묘: 길이 {base + index}cm, 너비 70cm, 잔존 깊이 35cm이다.")
        add_page(lines)

    if revision == 2:
        add_page(
            [
                "제3장 발굴조사 내용",
                "1지점 6호 석관묘 (도판 : 99)",
                "1지점 6호 석관묘 (도면 : 99)",
            ]
        )
    else:
        add_page(
            [
                "제3장 발굴조사 내용",
                "1지점 6호 석관묘",
                "추가 기록 없음.",
            ]
        )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _json(response: httpx.Response, label: str) -> dict:
    assert response.status_code < 300, f"{label} failed: {response.status_code} {response.text}"
    data = response.json()
    assert isinstance(data, dict), f"{label} did not return an object: {data!r}"
    return data


def _wait_project_run(
    client: httpx.Client,
    project_id: str,
    run_id: str,
    *,
    label: str,
) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    last: dict | None = None
    while time.monotonic() < deadline:
        detail = _json(client.get(f"/api/projects/{project_id}"), f"poll {label}")
        runs = detail.get("analysisRuns", [])
        match = next((run for run in runs if run.get("id") == run_id), None)
        if match:
            last = match
            if match.get("status") == "completed":
                return match
            if match.get("status") == "failed":
                raise AssertionError(
                    f"{label} failed: errorCode={match.get('errorCode')} retryable={match.get('retryable')}"
                )
        time.sleep(1.0)
    raise AssertionError(f"{label} did not complete within {POLL_TIMEOUT_SECONDS}s; last={last}")


def _upload(
    client: httpx.Client,
    project_id: str,
    *,
    kind: str,
    filename: str,
    pdf_bytes: bytes,
) -> tuple[str, str]:
    """Mirror the real frontend upload contract: every document stage is source."""

    response = client.post(
        f"/api/projects/{project_id}/documents",
        params={"kind": kind, "stage": "source"},
        files={"file": (filename, pdf_bytes, "application/pdf")},
    )
    data = _json(response, f"upload {filename}")
    version_id = data["documentVersionId"]
    ingest_run_id = data["analysisRunId"]
    _wait_project_run(client, project_id, ingest_run_id, label=f"ingest {filename}")
    return version_id, ingest_run_id


def _create_round(
    client: httpx.Client,
    project_id: str,
    *,
    body_version_id: str,
    plate_version_id: str | None,
    drawing_version_id: str | None,
    notes: str,
) -> dict:
    return _json(
        client.post(
            f"/api/v1/projects/{project_id}/rounds",
            json={
                "body_version_id": body_version_id,
                "plate_version_id": plate_version_id,
                "drawing_version_id": drawing_version_id,
                "notes": notes,
            },
        ),
        "create ReviewRound",
    )


def _assert_image_url(client: httpx.Client, image_url: str, label: str) -> None:
    response = client.get(image_url)
    assert response.status_code == 200, f"{label} render failed: {response.status_code} {response.text[:200]}"
    assert response.content, f"{label} render returned empty bytes"
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("image/"), f"{label} render is not image data: {content_type}"


def _comparison_type(visual: dict) -> str:
    return str(visual.get("comparisonType") or visual.get("comparison_type") or "")


def _render_status(visual: dict) -> str:
    return str(visual.get("renderStatus") or visual.get("render_status") or "")


def _validate_visual_bundle(client: httpx.Client, visual: dict, candidate_id: str) -> str:
    mode = _comparison_type(visual)
    assert mode in {
        "version_change",
        "plate_reference",
        "drawing_reference",
        "text_evidence",
    }, f"candidate {candidate_id} has invalid comparison type: {mode!r}"

    source = visual.get("source")
    comparison = visual.get("comparison")
    canonical = visual.get("canonical")
    reference = visual.get("reference")
    render_status = _render_status(visual)
    unresolved = visual.get("unresolvedReason") or visual.get("unresolved_reason")

    if source and source.get("imageUrl"):
        _assert_image_url(client, source["imageUrl"], f"{candidate_id} source")

    if mode == "version_change":
        assert source, f"{candidate_id}: version_change missing previous source"
        assert comparison, f"{candidate_id}: version_change missing current comparison"
        assert canonical is None, f"{candidate_id}: version_change must not fabricate canonical plate/drawing"
        assert source.get("documentVersionId") != comparison.get("documentVersionId"), (
            f"{candidate_id}: previous/current versions are identical"
        )
        if render_status == "ready":
            _assert_image_url(client, comparison["imageUrl"], f"{candidate_id} current body")
        else:
            assert render_status == "missing_render"
            assert unresolved == "render_unavailable"
        return mode

    if mode in {"plate_reference", "drawing_reference"}:
        assert reference, f"{candidate_id}: visual reference mode missing Graph reference identity"
        target_id = reference.get("targetId") or reference.get("target_id")
        assert target_id, f"{candidate_id}: resolved reference missing targetId"
        assert canonical, f"{candidate_id}: resolved reference missing canonical metadata"
        assert canonical.get("documentVersionId"), f"{candidate_id}: canonical target missing owning DocumentVersion"
        if render_status == "ready":
            _assert_image_url(client, canonical["imageUrl"], f"{candidate_id} canonical")
        else:
            assert render_status == "missing_render"
            assert unresolved, f"{candidate_id}: missing render without explicit reason"
        return mode

    assert mode == "text_evidence"
    assert canonical is None, f"{candidate_id}: text evidence must not show an arbitrary canonical asset"
    assert comparison is None, f"{candidate_id}: text evidence must not show a fake revision comparison"
    assert render_status == "not_applicable"
    return mode


def run_10_api_validation() -> None:
    print("=" * 78)
    print("[Remediation Live E2E] ReviewRound + Neo4j + budget + visual semantics")
    print(f"Target: {BASE_URL}")
    print(
        f"AI/VLM live calls: AI={ENABLE_LIVE_AI}, VLM={ENABLE_LIVE_VLM}, "
        f"budget={DEVELOPMENT_BUDGET}, raw-floor={RAW_FINDING_FLOOR}"
    )
    print("=" * 78)

    with httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(120.0, connect=30.0)) as client:
        health = client.get("/health")
        assert health.status_code == 200, f"health failed: {health.text}"

        project = _json(
            client.post(
                "/api/projects",
                json={
                    "name": f"논산 산노리 remediation-live-{int(time.time())}",
                    "internalCode": "NONSAN-REMEDIATION-LIVE",
                },
            ),
            "create project",
        )
        project_id = project["id"]
        print(f"[1] project={project_id}")

        body_v1_pdf = generate_stress_body_pdf(revision=1)
        plate_v1_pdf = generate_sample_pdf(
            [
                "【도판 45】 1지점 7호 석관묘 조사 후 전경",
                "① 조사 전 ② 조사 중 ③ 토층 A-A' ④ 동벽 세부 ⑤ 유물 출토 상태",
            ],
            visual_label="PLATE 45 / FEATURE 7",
        )
        drawing_v1_pdf = generate_sample_pdf(
            ["【도면 30】 1지점 8호 석관묘 평·단면도"],
            visual_label="DRAWING 30 / FEATURE 8",
        )

        body_v1, _ = _upload(
            client,
            project_id,
            kind="report_body",
            filename="산노리-본문-v1.pdf",
            pdf_bytes=body_v1_pdf,
        )
        plate_v1, _ = _upload(
            client,
            project_id,
            kind="plate_book",
            filename="산노리-도판-v1.pdf",
            pdf_bytes=plate_v1_pdf,
        )
        drawing_v1, _ = _upload(
            client,
            project_id,
            kind="drawing_book",
            filename="산노리-도면-v1.pdf",
            pdf_bytes=drawing_v1_pdf,
        )
        print(f"[2] source-stage v1 body={body_v1}, plate={plate_v1}, drawing={drawing_v1}")

        round1 = _create_round(
            client,
            project_id,
            body_version_id=body_v1,
            plate_version_id=plate_v1,
            drawing_version_id=drawing_v1,
            notes="Round 1 source-stage 기준선",
        )
        assert round1["sequence"] == 1
        assert round1["bodyVersionId"] == body_v1
        assert round1["plateVersionId"] == plate_v1
        assert round1["drawingVersionId"] == drawing_v1

        approved1 = _json(
            client.post(f"/api/v1/projects/{project_id}/rounds/{round1['id']}/approve"),
            "approve round1",
        )
        first_approved_at = approved1["approvedAt"]
        assert first_approved_at
        approved1_again = _json(
            client.post(f"/api/v1/projects/{project_id}/rounds/{round1['id']}/approve"),
            "approve round1 twice",
        )
        assert approved1_again["approvedAt"] == first_approved_at
        print(f"[3] round1 approvedAt frozen={first_approved_at}")

        body_v2_pdf = generate_stress_body_pdf(revision=2)
        body_v2, _ = _upload(
            client,
            project_id,
            kind="report_body",
            filename="산노리-본문-v2.pdf",
            pdf_bytes=body_v2_pdf,
        )
        assert body_v2 != body_v1

        round2 = _create_round(
            client,
            project_id,
            body_version_id=body_v2,
            plate_version_id=plate_v1,
            drawing_version_id=drawing_v1,
            notes="Round 2 source-stage 수정본문 + 도판/도면 재사용",
        )
        assert round2["sequence"] == 2
        assert round2["bodyVersionId"] == body_v2
        assert round2["plateVersionId"] == plate_v1
        assert round2["drawingVersionId"] == drawing_v1
        print(f"[4] round2={round2['id']} body v2 + reused visual versions")

        run_response = _json(
            client.post(
                f"/api/v1/projects/{project_id}/runs",
                json={
                    "review_round_id": round2["id"],
                    "enable_vlm": ENABLE_LIVE_VLM,
                    "enable_ai_review": ENABLE_LIVE_AI,
                },
            ),
            "trigger ReviewRound run",
        )
        run_id = run_response.get("runId") or run_response.get("run_id")
        assert run_id
        assert (run_response.get("reviewRoundId") or run_response.get("review_round_id")) == round2["id"]
        completed_run = _wait_project_run(client, project_id, run_id, label=f"proofreading {run_id}")
        assert completed_run["status"] == "completed"
        print(f"[5] analysis completed run={run_id}")

        diagnostics = _json(
            client.get(f"/api/v1/projects/{project_id}/runs/{run_id}"),
            "run diagnostics",
        )
        assert diagnostics.get("reviewRoundId") == round2["id"]
        assert diagnostics.get("bodyVersionId") == body_v2
        assert diagnostics.get("plateVersionId") == plate_v1
        assert diagnostics.get("drawingVersionId") == drawing_v1
        summary = diagnostics.get("summary") or {}
        selected_count = int(summary.get("selected_candidates", diagnostics.get("selectedCandidates", 0)) or 0)
        expensive_ops = int(summary.get("expensive_operations", diagnostics.get("expensiveOperations", 0)) or 0)
        raw_findings = int(summary.get("raw_findings", diagnostics.get("rawFindings", 0)) or 0)
        deduped_findings = int(summary.get("deduped_findings", diagnostics.get("dedupedFindings", 0)) or 0)

        assert raw_findings >= RAW_FINDING_FLOOR, (
            f"stress fixture did not create enough raw findings: {raw_findings}<{RAW_FINDING_FLOOR}"
        )
        assert deduped_findings <= raw_findings
        assert selected_count <= DEVELOPMENT_BUDGET, (
            f"selected candidate budget exceeded: {selected_count}>{DEVELOPMENT_BUDGET}"
        )
        assert expensive_ops <= DEVELOPMENT_BUDGET, (
            f"expensive operation budget exceeded: {expensive_ops}>{DEVELOPMENT_BUDGET}"
        )
        if ENABLE_LIVE_AI or ENABLE_LIVE_VLM:
            assert 1 <= expensive_ops <= DEVELOPMENT_BUDGET, (
                "AI/VLM were enabled but no budgeted expensive operation was recorded"
            )
        print(
            f"[6] stress budget raw={raw_findings}, deduped={deduped_findings}, "
            f"selected={selected_count}, expensive={expensive_ops}"
        )

        candidate_payload = _json(
            client.get(f"/api/v1/projects/{project_id}/candidates"),
            "fetch candidates",
        )
        candidates = candidate_payload.get("candidates") or []
        assert 1 <= len(candidates) <= DEVELOPMENT_BUDGET
        assert all(candidate.get("status") == "pending_review" for candidate in candidates)
        print(f"[7] materialized candidates={len(candidates)}")

        for candidate in candidates:
            candidate_id = candidate["id"]
            trace = _json(
                client.get(f"/api/v1/projects/{project_id}/candidates/{candidate_id}/traceability"),
                f"traceability {candidate_id}",
            )
            assert (trace.get("candidateId") or trace.get("candidate_id")) == candidate_id
            assert trace.get("candidate"), f"{candidate_id}: trace missing candidate node"
        print("[8] every materialized candidate has project-scoped traceability")

        mode_counts: Counter[str] = Counter()
        candidate_visuals: dict[str, dict] = {}
        for candidate in candidates:
            candidate_id = candidate["id"]
            visual = _json(
                client.get(f"/api/v1/projects/{project_id}/candidates/{candidate_id}/visual-bundle"),
                f"visual bundle {candidate_id}",
            )
            mode = _validate_visual_bundle(client, visual, candidate_id)
            mode_counts[mode] += 1
            candidate_visuals[candidate_id] = visual

        assert len(mode_counts) >= 1, f"no visual modes resolved: {mode_counts}"
        assert sum(mode_counts.values()) == len(candidates)
        print(f"[9] evidence-aware visual modes={dict(mode_counts)}")

        target_candidate = candidates[0]
        candidate_id = target_candidate["id"]
        decision = _json(
            client.post(
                f"/api/v1/projects/{project_id}/candidates/{candidate_id}/decisions",
                json={
                    "decision": "accepted",
                    "reviewer": "remediation-live-validator",
                    "rationale": "live E2E audit decision",
                    "modified_text": None,
                },
            ),
            "submit review decision",
        )
        assert (decision.get("candidateId") or decision.get("candidate_id")) == candidate_id

        approved2 = _json(
            client.post(f"/api/v1/projects/{project_id}/rounds/{round2['id']}/approve"),
            "approve round2",
        )
        assert approved2["status"] == "approved"
        assert approved2["approvedAt"]
        print("[10] expert decision + round2 approval recorded")

    print("=" * 78)
    print("PASS: source-stage ReviewRound authority, 50+ finding budget stress, traceability, and evidence-aware visual modes")
    print("NOTE: external AI/VLM call budget is exercised only when ENABLE_LIVE_AI/VLM=1")
    print("=" * 78)


if __name__ == "__main__":
    run_10_api_validation()
