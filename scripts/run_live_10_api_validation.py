from __future__ import annotations

import io
import os
import time

import fitz  # PyMuPDF
import httpx
from PIL import Image, ImageDraw

BASE_URL = os.environ.get("VALIDATION_BASE_URL", "http://localhost:18080")
POLL_TIMEOUT_SECONDS = int(os.environ.get("VALIDATION_TIMEOUT_SECONDS", "90"))
ENABLE_LIVE_VLM = os.environ.get("ENABLE_LIVE_VLM", "0") == "1"
ENABLE_LIVE_AI = os.environ.get("ENABLE_LIVE_AI", "0") == "1"
DEVELOPMENT_BUDGET = int(os.environ.get("DEVELOPMENT_CANDIDATE_BUDGET", "10"))


def _visual_png(label: str) -> bytes:
    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 55, 845, 465), outline="black", width=5)
    draw.line((100, 380, 800, 140), fill="black", width=5)
    draw.ellipse((315, 155, 585, 410), outline="black", width=5)
    # ASCII label avoids system-font dependence while still embedding a real raster asset.
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
        response = client.get(f"/api/projects/{project_id}")
        detail = _json(response, f"poll {label}")
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
    stage: str,
    filename: str,
    pdf_bytes: bytes,
) -> tuple[str, str]:
    response = client.post(
        f"/api/projects/{project_id}/documents",
        params={"kind": kind, "stage": stage},
        files={"file": (filename, pdf_bytes, "application/pdf")},
    )
    data = _json(response, f"upload {filename}")
    version_id = data["documentVersionId"]
    ingest_run_id = data["analysisRunId"]
    _wait_project_run(
        client,
        project_id,
        ingest_run_id,
        label=f"ingest {filename}",
    )
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
    response = client.post(
        f"/api/v1/projects/{project_id}/rounds",
        json={
            "body_version_id": body_version_id,
            "plate_version_id": plate_version_id,
            "drawing_version_id": drawing_version_id,
            "notes": notes,
        },
    )
    return _json(response, "create ReviewRound")


def _assert_image_url(client: httpx.Client, image_url: str, label: str) -> None:
    response = client.get(image_url)
    assert response.status_code == 200, f"{label} render failed: {response.status_code} {response.text[:200]}"
    assert response.content, f"{label} render returned empty bytes"
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("image/"), f"{label} render is not image data: {content_type}"


def run_10_api_validation() -> None:
    print("=" * 78)
    print("[Remediation Live E2E] ReviewRound + Neo4j + development budget validation")
    print(f"Target: {BASE_URL}")
    print(
        f"AI/VLM live calls: AI={ENABLE_LIVE_AI}, VLM={ENABLE_LIVE_VLM}, "
        f"budget={DEVELOPMENT_BUDGET}"
    )
    print("=" * 78)

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # Gate 1: service and isolated project
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

        # Gate 2: first canonical input set. Plate/drawing PDFs contain real raster assets,
        # not just caption text, so render delivery can be exercised.
        body_v1_pdf = generate_sample_pdf(
            [
                "제3장 발굴조사 내용",
                "1. 1지점 6호 석관묘 (도면 30, 도판 45)",
                "1지점 6호 석관묘의 규모는 길이 210cm, 너비 70cm, 잔존 깊이 35cm이다.",
                "2. 1지점 2호 토광묘 (도면 : , 도판 : )",
                "2호 토광묘는 길이 180cm, 너비 60cm의 장방형 토광묘이다.",
            ]
        )
        plate_v1_pdf = generate_sample_pdf(
            [
                "【도판 45】 1지점 6호 석관묘 조사 후 전경",
                "① 조사 전 ② 조사 중 ③ 토층 A-A' ④ 동벽 세부 ⑤ 유물 출토 상태",
            ],
            visual_label="PLATE 45 / FEATURE 6",
        )
        drawing_v1_pdf = generate_sample_pdf(
            ["【도면 30】 1지점 6호 석관묘 평·단면도"],
            visual_label="DRAWING 30 / FEATURE 6",
        )

        body_v1, _ = _upload(
            client,
            project_id,
            kind="report_body",
            stage="1차",
            filename="산노리-본문-v1.pdf",
            pdf_bytes=body_v1_pdf,
        )
        plate_v1, _ = _upload(
            client,
            project_id,
            kind="plate_book",
            stage="1차",
            filename="산노리-도판-v1.pdf",
            pdf_bytes=plate_v1_pdf,
        )
        drawing_v1, _ = _upload(
            client,
            project_id,
            kind="drawing_book",
            stage="1차",
            filename="산노리-도면-v1.pdf",
            pdf_bytes=drawing_v1_pdf,
        )
        print(f"[2] v1 body={body_v1}, plate={plate_v1}, drawing={drawing_v1}")

        # Gate 3: Round 1 exists and approval timestamp is immutable.
        round1 = _create_round(
            client,
            project_id,
            body_version_id=body_v1,
            plate_version_id=plate_v1,
            drawing_version_id=drawing_v1,
            notes="1차 입력 기준선",
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
        assert approved1_again["approvedAt"] == first_approved_at, "approvedAt changed on repeat approval"
        print(f"[3] round1 approvedAt frozen={first_approved_at}")

        # Gate 4: create a REAL second body version. Plate/drawing are deliberately reused.
        body_v2_pdf = generate_sample_pdf(
            [
                "제3장 발굴조사 내용",
                "1. 1지점 6호 석관묘 (도면 30, 도판 45)",
                # Deliberate version change for comparison.
                "1지점 6호 석관묘의 규모는 길이 220cm, 너비 70cm, 잔존 깊이 35cm이다.",
                # Deliberate unresolved publication reference for a deterministic rule finding.
                "추가 기록은 도판 99를 참조한다.",
                "2. 1지점 2호 토광묘 (도면 : , 도판 : )",
                "2호 토광묘는 길이 180cm, 너비 60cm의 장방형 토광묘이다.",
            ]
        )
        body_v2, _ = _upload(
            client,
            project_id,
            kind="report_body",
            stage="2차",
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
            notes="2차 수정본문 + 1차 도판/도면 재사용",
        )
        assert round2["sequence"] == 2
        assert round2["bodyVersionId"] == body_v2
        assert round2["plateVersionId"] == plate_v1
        assert round2["drawingVersionId"] == drawing_v1
        print(f"[4] round2={round2['id']} body v2 + reused visual versions")

        # Gate 5: run is launched by ReviewRound ID ONLY. Neo4j must resolve the three inputs.
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

        completed_run = _wait_project_run(
            client,
            project_id,
            run_id,
            label=f"proofreading {run_id}",
        )
        assert completed_run["status"] == "completed"
        print(f"[5] analysis completed run={run_id}")

        # Gate 6: audited run diagnostics prove the round authority + cost budget.
        diagnostics = _json(
            client.get(f"/api/v1/projects/{project_id}/runs/{run_id}"),
            "run diagnostics",
        )
        assert diagnostics.get("reviewRoundId") == round2["id"]
        assert diagnostics.get("bodyVersionId") == body_v2
        assert diagnostics.get("plateVersionId") == plate_v1
        assert diagnostics.get("drawingVersionId") == drawing_v1
        summary = diagnostics.get("summary") or {}
        selected_count = int(
            summary.get("selected_candidates", diagnostics.get("selectedCandidates", 0)) or 0
        )
        expensive_ops = int(
            summary.get("expensive_operations", diagnostics.get("expensiveOperations", 0)) or 0
        )
        raw_findings = int(summary.get("raw_findings", diagnostics.get("rawFindings", 0)) or 0)
        deduped_findings = int(
            summary.get("deduped_findings", diagnostics.get("dedupedFindings", 0)) or 0
        )
        assert selected_count <= DEVELOPMENT_BUDGET, (
            f"selected candidate budget exceeded: {selected_count}>{DEVELOPMENT_BUDGET}"
        )
        assert expensive_ops <= DEVELOPMENT_BUDGET, (
            f"expensive operation budget exceeded: {expensive_ops}>{DEVELOPMENT_BUDGET}"
        )
        assert deduped_findings <= raw_findings, (
            f"invalid finding counters: raw={raw_findings}, deduped={deduped_findings}"
        )
        print(
            f"[6] budget raw={raw_findings}, deduped={deduped_findings}, "
            f"selected={selected_count}, expensive={expensive_ops}"
        )

        # Gate 7: development candidate materialization must be non-empty and <= budget.
        candidate_payload = _json(
            client.get(f"/api/v1/projects/{project_id}/candidates"),
            "fetch candidates",
        )
        candidates = candidate_payload.get("candidates") or []
        assert 1 <= len(candidates) <= DEVELOPMENT_BUDGET, (
            f"expected 1..{DEVELOPMENT_BUDGET} materialized candidates, got {len(candidates)}"
        )
        assert all(candidate.get("status") == "pending_review" for candidate in candidates)
        target_candidate = candidates[0]
        candidate_id = target_candidate["id"]
        print(f"[7] materialized candidates={len(candidates)} first={candidate_id}")

        # Gate 8: project-scoped traceability must resolve through Neo4j.
        trace = _json(
            client.get(
                f"/api/v1/projects/{project_id}/candidates/{candidate_id}/traceability"
            ),
            "candidate traceability",
        )
        assert (trace.get("candidateId") or trace.get("candidate_id")) == candidate_id
        assert trace.get("candidate"), "candidate trace is missing candidate node"
        print("[8] candidate traceability resolved")

        # Gate 9: visual bundle must never return an unrelated arbitrary target.
        visual = _json(
            client.get(
                f"/api/v1/projects/{project_id}/candidates/{candidate_id}/visual-bundle"
            ),
            "candidate visual bundle",
        )
        source_asset = visual.get("source")
        canonical_asset = visual.get("canonical")
        unresolved_reason = visual.get("unresolvedReason") or visual.get("unresolved_reason")
        if source_asset and source_asset.get("imageUrl"):
            _assert_image_url(client, source_asset["imageUrl"], "source page")
        if canonical_asset and canonical_asset.get("imageUrl"):
            _assert_image_url(client, canonical_asset["imageUrl"], "canonical visual")
        else:
            # Failing closed is valid; silently selecting the first unrelated asset is not.
            assert unresolved_reason, "canonical asset missing without an explicit unresolved reason"
        print(
            "[9] visual bundle "
            + ("rendered exact canonical target" if canonical_asset else f"failed closed: {unresolved_reason}")
        )

        # Gate 10: expert decision is project-scoped and auditable.
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
    print("PASS: ReviewRound authority, v2 revision, Neo4j traceability, budget, and visual fail-closed gates passed")
    print("NOTE: external AI/VLM semantic quality is only exercised when ENABLE_LIVE_AI/VLM=1")
    print("=" * 78)


if __name__ == "__main__":
    run_10_api_validation()
