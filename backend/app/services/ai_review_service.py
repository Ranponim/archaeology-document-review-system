from dataclasses import dataclass, field
import json
import os
from typing import Any
from app.domain.canonical_models import (
    ArchaeologyObjectData,
    DrawingData,
    PlateData,
    ReferenceData,
)
from app.domain.document_structure import ParsedPage
from app.domain.evidence_bundle import ObjectEvidenceBundle
from app.domain.review_models import (
    CorrectionCandidateData,
    EvidenceData,
    RuleCategory,
    ChangeType,
    ReviewStatus,
)
from app.services.json_utils import strip_markdown_json
from app.services.openrouter_client import OpenRouterClient, OpenRouterConfig


@dataclass(frozen=True, slots=True)
class AIReviewResult:
    candidates: list[CorrectionCandidateData]
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AIReviewService:
    DEFAULT_MODEL = "openai/gpt-5.6-luna"

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("OPENROUTER_MODEL", self.DEFAULT_MODEL)
        config = OpenRouterConfig.from_env()
        # Ensure config uses model
        object.__setattr__(config, "model", self._model)
        self._client = client or OpenRouterClient(config)

    async def analyze_page(
        self,
        project_id: str,
        version_stage: str,
        page: ParsedPage,
    ) -> AIReviewResult:
        prompt = (
            "고고학 발굴보고서의 본문 단락과 캡션을 검토하여 다음 오류를 찾아내고 "
            "JSON 형식으로 교정 후보를 출력하십시오:\n"
            "1. 고고학 전문용어 표기 및 맞춤법/띄어쓰기 오류 (annotation_resolution)\n"
            "2. 도면/도판 번호 누락 및 불일치 (figure_plate_table_photo_ref)\n"
            "3. 유구/유물 식별자 번호 및 명칭 모순 (feature_or_artifact_id)\n"
            "4. 수치/치수/고도 모순 (numeric_value)\n\n"
            "반드시 JSON 형식 `{\"candidates\": [{\"category\": \"...\", \"original_text\": \"...\", \"proposed_text\": \"...\", \"change_type\": \"...\", \"rationale\": \"...\"}]}` 으로만 응답하십시오."
        )

        context = {
            "physical_page": page.physical_page,
            "printed_page": page.printed_page,
            "header": page.header,
            "text_blocks": [b.text for b in page.text_blocks],
            "captions": [c.raw_text for c in page.captions],
        }

        response = await self._client.analyze_text_discrepancy(prompt, context)

        candidates: list[CorrectionCandidateData] = []
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        choices = response.get("choices", [])
        if choices:
            msg_content = choices[0].get("message", {}).get("content", "{}")
            try:
                data = json.loads(strip_markdown_json(msg_content))
                raw_cands = data.get("candidates", [])
                for idx, c in enumerate(raw_cands):
                    cat = c.get("category", "annotation_resolution")
                    if cat not in [
                        "figure_plate_table_photo_ref",
                        "annotation_resolution",
                        "feature_or_artifact_id",
                        "numeric_value",
                        "site_or_area_name",
                        "direction_period_term",
                    ]:
                        cat = "annotation_resolution"

                    ch_type = c.get("change_type", "modified")
                    if ch_type not in ["added", "deleted", "modified", "moved"]:
                        ch_type = "modified"

                    status: ReviewStatus = "pending_review"

                    evidence = EvidenceData(
                        version_from=version_stage,
                        version_to=version_stage,
                        physical_page_from=page.physical_page,
                        physical_page_to=page.physical_page,
                        printed_page_from=page.printed_page,
                        printed_page_to=page.printed_page,
                        rule_name=f"ai_{self._model}",
                        rationale=c.get("rationale", "AI review candidate proposal"),
                    )

                    cand = CorrectionCandidateData(
                        candidate_id=f"cand_ai_p{page.physical_page}_{idx+1}",
                        rule_category=cat,
                        change_type=ch_type,
                        status=status,
                        original_text=c.get("original_text"),
                        proposed_text=c.get("proposed_text"),
                        evidence=evidence,
                    )
                    candidates.append(cand)
            except json.JSONDecodeError:
                pass

        return AIReviewResult(
            candidates=candidates,
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    def _evidence_to_context_dict(
        self, ev: EvidenceData, idx: int, version_stage: str
    ) -> dict[str, Any]:
        ev_id = ev.id or f"ev_{idx + 1}"
        ev_dict: dict[str, Any] = {
            "evidence_id": ev_id,
            "kind": ev.kind or "text_claim",
            "value": str(ev.value) if ev.value is not None else "",
            "rationale": ev.rationale or "",
            "confidence": ev.confidence,
        }
        if ev.version_from or version_stage:
            ev_dict["version_stage"] = ev.version_from or version_stage
        if ev.physical_page_from is not None:
            ev_dict["physical_page"] = ev.physical_page_from
        if ev.printed_page_from is not None:
            ev_dict["printed_page"] = ev.printed_page_from
        if ev.source_sha256:
            ev_dict["source_sha256"] = ev.source_sha256
        if ev.document_version_id:
            ev_dict["document_version_id"] = ev.document_version_id
        if ev.page_id:
            ev_dict["page_id"] = ev.page_id
        return ev_dict

    def _parse_object_candidates(
        self,
        response: dict[str, Any],
        archaeology_object: ArchaeologyObjectData,
        evidence_map: dict[str, EvidenceData],
        analysis_run_id: str | None,
    ) -> list[CorrectionCandidateData]:
        candidates: list[CorrectionCandidateData] = []
        choices = response.get("choices", []) if isinstance(response, dict) else []
        if not choices:
            return []

        msg_content = choices[0].get("message", {}).get("content", "{}")
        try:
            data = json.loads(strip_markdown_json(msg_content))
            raw_cands = data.get("candidates", [])
            for idx, c in enumerate(raw_cands):
                if not isinstance(c, dict):
                    continue

                # Grounding check: verify cited evidence IDs exist in evidence_map
                raw_cited_ids = c.get("cited_evidence_ids", [])
                if isinstance(raw_cited_ids, str):
                    raw_cited_ids = [raw_cited_ids]
                elif not isinstance(raw_cited_ids, list):
                    raw_cited_ids = []

                cited_evidences: list[EvidenceData] = []
                for cid in raw_cited_ids:
                    if cid in evidence_map:
                        cited_evidences.append(evidence_map[cid])

                # Reject candidate if it fails to cite any valid provided evidence
                if not cited_evidences:
                    continue

                cat = c.get("category", "annotation_resolution")
                if cat not in [
                    "figure_plate_table_photo_ref",
                    "annotation_resolution",
                    "feature_or_artifact_id",
                    "numeric_value",
                    "site_or_area_name",
                    "direction_period_term",
                ]:
                    cat = "annotation_resolution"

                ch_type = c.get("change_type", "modified")
                if ch_type not in ["added", "deleted", "modified", "moved"]:
                    ch_type = "modified"

                # Status is strictly pending_review
                status: ReviewStatus = "pending_review"

                try:
                    conf = float(c.get("confidence", 0.9))
                    conf = max(0.0, min(1.0, conf))
                except (ValueError, TypeError):
                    conf = 0.9

                primary_ev = cited_evidences[0]
                run_id = analysis_run_id or primary_ev.analysis_run_id

                cand = CorrectionCandidateData(
                    candidate_id=f"cand_ai_obj_{archaeology_object.object_id}_{idx+1}",
                    rule_category=cat,
                    change_type=ch_type,
                    status=status,
                    original_text=c.get("original_text"),
                    proposed_text=c.get("proposed_text"),
                    evidence=primary_ev,
                    evidence_list=cited_evidences,
                    archaeology_object_id=archaeology_object.object_id,
                    confidence=conf,
                    analysis_run_id=run_id,
                )
                candidates.append(cand)
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass

        return candidates

    async def review_object_evidence(
        self,
        archaeology_object: ArchaeologyObjectData | None = None,
        evidences: list[EvidenceData] | None = None,
        references: list[ReferenceData] | None = None,
        project_id: str = "",
        version_stage: str = "",
        analysis_run_id: str | None = None,
        plates: list[PlateData] | None = None,
        drawings: list[DrawingData] | None = None,
    ) -> list[CorrectionCandidateData]:
        """Reviews an ArchaeologyObject against its linked Graph Evidences and References.

        Enforces strict prompt grounding: all candidates must cite valid provided
        evidence IDs, status is strictly 'pending_review', and empty/insufficient evidence
        triggers immediate refusal safety returning no speculative candidates.
        """
        # Refusal & safety check: return empty if object is missing or no evidence
        if archaeology_object is None or not evidences:
            return []

        valid_evidences = [
            ev
            for ev in evidences
            if (ev.value is not None and str(ev.value).strip())
            or (ev.rationale is not None and str(ev.rationale).strip())
        ]
        if not valid_evidences:
            return []

        evidences_context: list[dict[str, Any]] = []
        evidence_map: dict[str, EvidenceData] = {}
        for idx, ev in enumerate(valid_evidences):
            ev_id = ev.id or f"ev_{idx + 1}"
            evidence_map[ev_id] = ev
            evidences_context.append(self._evidence_to_context_dict(ev, idx, version_stage))

        obj_context = {
            "object_id": archaeology_object.object_id,
            "site": archaeology_object.site,
            "point": archaeology_object.point,
            "period": archaeology_object.period,
            "type": archaeology_object.type,
            "number": archaeology_object.number,
            "canonical_name": archaeology_object.canonical_name,
        }

        context: dict[str, Any] = {
            "archaeology_object": obj_context,
            "evidences": evidences_context,
        }

        if references:
            refs_context = []
            for r in references:
                refs_context.append({
                    "ref_type": r.ref_type,
                    "number": r.number,
                    "raw_text": r.raw_text or "",
                    "physical_page": r.physical_page,
                })
            context["references"] = refs_context

        if plates:
            plates_context = []
            for p in plates:
                plates_context.append({
                    "plate_id": p.plate_id,
                    "number": p.number,
                    "title": p.title,
                    "physical_page": p.physical_page,
                })
            context["plates"] = plates_context

        if drawings:
            drawings_context = []
            for d in drawings:
                drawings_context.append({
                    "drawing_id": d.drawing_id,
                    "number": d.number,
                    "title": d.title,
                    "physical_page": d.physical_page,
                })
            context["drawings"] = drawings_context

        prompt = (
            "고고학 발굴보고서의 유구/유물 객체와 관련된 지식 그래프 증거(Evidence), 참조(Reference), 도면/도판 데이터를 검토하여 "
            "서로 모순되거나 잘못된 기술, 수치 불일치, 도면/도판 번호 오류, 용어 오기 등을 찾아내고 교정 후보를 JSON 형식으로 출력하십시오.\n\n"
            "엄격한 근거 중심(Grounding) 검수 원칙:\n"
            "1. 반드시 제공된 증거 목록(Evidences)에 실제로 존재하는 증거에만 기반해야 합니다.\n"
            "2. 제공된 증거에 명시되지 않은 사실, 연대, 시대, 유적 위치를 절대 추측하거나 날조(Hallucination)하지 마십시오.\n"
            "3. 모든 교정 후보는 반드시 관련된 실제 증거 ID 목록(`cited_evidence_ids`)을 정확히 명시해야 합니다.\n"
            "4. 검증할 증거가 불충분하거나 오류가 명확하지 않은 경우 교정 후보를 생성하지 말고 빈 배열 `[]`을 반환하십시오.\n\n"
            "반드시 JSON 형식으로만 응답하십시오:\n"
            "{\n"
            '  "candidates": [\n'
            '    {\n'
            '      "category": "numeric_value" | "figure_plate_table_photo_ref" | "feature_or_artifact_id" | "site_or_area_name" | "direction_period_term" | "annotation_resolution",\n'
            '      "change_type": "modified" | "added" | "deleted" | "moved",\n'
            '      "original_text": "원문 오류 텍스트",\n'
            '      "proposed_text": "수정 제안 텍스트",\n'
            '      "rationale": "교정 제안의 고고학적 근거 및 불일치 설명",\n'
            '      "cited_evidence_ids": ["ev_id_1", "ev_id_2"],\n'
            '      "confidence": 0.95\n'
            '    }\n'
            '  ]\n'
            "}"
        )

        response = await self._client.analyze_text_discrepancy(prompt, context)

        return self._parse_object_candidates(
            response, archaeology_object, evidence_map, analysis_run_id
        )

    async def review_object_bundle(
        self,
        archaeology_object: ArchaeologyObjectData | None = None,
        bundle: ObjectEvidenceBundle | None = None,
        rule_findings: list[CorrectionCandidateData] | None = None,
        project_id: str = "",
        version_stage: str = "",
        analysis_run_id: str | None = None,
    ) -> list[CorrectionCandidateData]:
        """Reviews an ArchaeologyObject against its graph-derived ObjectEvidenceBundle.

        The LLM input is built strictly from bundle fields (object identity,
        text_claims, references, plate_claims, drawing_claims,
        visual_observations, version_claims) plus structured rule findings for
        the object. No full-document text is ever included (plan Task 10 /
        anti-pattern #9). Grounding and pending_review invariants are shared
        with review_object_evidence.
        """
        if archaeology_object is None or bundle is None:
            return []

        valid_evidences = [
            ev
            for ev in bundle.evidences
            if (ev.value is not None and str(ev.value).strip())
            or (ev.rationale is not None and str(ev.rationale).strip())
        ]
        if not valid_evidences:
            return []

        evidence_map: dict[str, EvidenceData] = {}
        for idx, ev in enumerate(valid_evidences):
            evidence_map[ev.id or f"ev_{idx + 1}"] = ev

        def _family_context(evidences: list[EvidenceData]) -> list[dict[str, Any]]:
            return [
                self._evidence_to_context_dict(ev, idx, version_stage)
                for idx, ev in enumerate(evidences)
            ]

        obj_context = {
            "object_id": archaeology_object.object_id,
            "site": archaeology_object.site,
            "point": archaeology_object.point,
            "period": archaeology_object.period,
            "type": archaeology_object.type,
            "number": archaeology_object.number,
            "canonical_name": archaeology_object.canonical_name,
        }

        context: dict[str, Any] = {
            "archaeology_object": obj_context,
            "evidence_bundle": {
                "text_claims": _family_context(bundle.text_claims),
                "references": _family_context(bundle.references),
                "plate_claims": _family_context(bundle.plate_claims),
                "drawing_claims": _family_context(bundle.drawing_claims),
                "visual_observations": _family_context(bundle.visual_observations),
                "version_claims": _family_context(bundle.version_claims),
            },
        }

        if rule_findings:
            context["rule_findings"] = [
                {
                    "rule_category": rf.rule_category,
                    "change_type": rf.change_type,
                    "original_text": rf.original_text,
                    "proposed_text": rf.proposed_text,
                    "confidence": rf.confidence,
                    "evidence_ids": [ev.id for ev in rf.evidences if ev.id],
                }
                for rf in rule_findings
            ]

        prompt = (
            "고고학 발굴보고서의 유구/유물 객체와 관련된 지식 그래프 증거 묶음(Evidence Bundle)과 "
            "규칙 검사 결과(Rule Findings)를 검토하여 서로 모순되거나 잘못된 기술, 수치 불일치, "
            "도면/도판 번호 오류, 용어 오기 등을 찾아내고 교정 후보를 JSON 형식으로 출력하십시오.\n\n"
            "엄격한 근거 중심(Grounding) 검수 원칙:\n"
            "1. 반드시 제공된 증거 묶음(evidence_bundle)에 실제로 존재하는 증거에만 기반해야 합니다.\n"
            "2. 제공된 증거에 명시되지 않은 사실, 연대, 시대, 유적 위치를 절대 추측하거나 날조(Hallucination)하지 마십시오.\n"
            "3. 모든 교정 후보는 반드시 관련된 실제 증거 ID 목록(`cited_evidence_ids`)을 정확히 명시해야 합니다.\n"
            "4. 검증할 증거가 불충분하거나 오류가 명확하지 않은 경우 교정 후보를 생성하지 말고 빈 배열 `[]`을 반환하십시오.\n\n"
            "반드시 JSON 형식으로만 응답하십시오:\n"
            "{\n"
            '  "candidates": [\n'
            '    {\n'
            '      "category": "numeric_value" | "figure_plate_table_photo_ref" | "feature_or_artifact_id" | "site_or_area_name" | "direction_period_term" | "annotation_resolution",\n'
            '      "change_type": "modified" | "added" | "deleted" | "moved",\n'
            '      "original_text": "원문 오류 텍스트",\n'
            '      "proposed_text": "수정 제안 텍스트",\n'
            '      "rationale": "교정 제안의 고고학적 근거 및 불일치 설명",\n'
            '      "cited_evidence_ids": ["ev_id_1", "ev_id_2"],\n'
            '      "confidence": 0.95\n'
            '    }\n'
            '  ]\n'
            "}"
        )

        response = await self._client.analyze_text_discrepancy(prompt, context)

        return self._parse_object_candidates(
            response, archaeology_object, evidence_map, analysis_run_id
        )

