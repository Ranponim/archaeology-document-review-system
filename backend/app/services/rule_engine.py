import difflib
import re
from app.domain.document_structure import ParsedPage
from app.domain.review_models import (
    CorrectionCandidateData,
    EvidenceData,
    RuleCategory,
    ChangeType,
    ReviewStatus,
    RuleCheckResult,
)
from app.services.page_aligner import AlignedPageRow


class RuleEngine:
    HEADER_PATTERN = re.compile(
        r"^(?:\d+\s*\|\s*(?:백제문화유산연구원|문화유적\s*보고서)|(?:백제문화유산연구원|문화유적\s*보고서)\s*\|\s*\d+)$"
    )
    
    FEATURE_ID_PATTERN = re.compile(
        r"(?:\d+호\s*(?:토광묘|주거지|수혈유구|함정유구|유구|유물))"
    )

    def _is_header_noise(self, line: str) -> bool:
        return bool(self.HEADER_PATTERN.match(line.strip()))

    def _classify_rule_category(
        self, old_text: str | None, new_text: str | None
    ) -> RuleCategory:
        combined = f"{old_text or ''} {new_text or ''}"
        
        # 1. Figure / Plate / Photo / Table references
        if "도면" in combined or "도판" in combined or "표 " in combined:
            return "figure_plate_table_photo_ref"
        
        # 2. Feature / Artifact ID
        if self.FEATURE_ID_PATTERN.search(combined):
            # If the only difference is spacing, prioritize annotation_resolution
            if old_text and new_text and (old_text.replace(" ", "") == new_text.replace(" ", "")):
                return "annotation_resolution"
            return "feature_or_artifact_id"
        
        # 3. Annotation / spacing / punctuation / arrows
        if "→" in combined or "괄호" in combined or "(" in combined:
            return "annotation_resolution"
        if old_text and new_text and (old_text.replace(" ", "") == new_text.replace(" ", "")):
            return "annotation_resolution"
            
        return "annotation_resolution"

    def compare_pages(
        self,
        page_a: ParsedPage,
        page_b: ParsedPage,
        stage_from: str,
        stage_to: str,
    ) -> list[CorrectionCandidateData]:
        lines_a = [b.text for b in page_a.text_blocks if not self._is_header_noise(b.text)]
        lines_b = [b.text for b in page_b.text_blocks if not self._is_header_noise(b.text)]

        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
        candidates: list[CorrectionCandidateData] = []
        cand_idx = 1

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue

            chunk_a = lines_a[i1:i2]
            chunk_b = lines_b[j1:j2]

            old_str = " ".join(chunk_a) if chunk_a else None
            new_str = " ".join(chunk_b) if chunk_b else None

            if tag == "replace":
                change_type: ChangeType = "modified"
            elif tag == "insert":
                change_type = "added"
            elif tag == "delete":
                change_type = "deleted"
            else:
                change_type = "modified"

            category = self._classify_rule_category(old_str, new_str)
            status: ReviewStatus = "confirmed"

            evidence = EvidenceData(
                version_from=stage_from,
                version_to=stage_to,
                physical_page_from=page_a.physical_page,
                physical_page_to=page_b.physical_page,
                printed_page_from=page_a.printed_page,
                printed_page_to=page_b.printed_page,
                rule_name=category,
                rationale=f"Diff detected between {stage_from} and {stage_to}: [{change_type}]",
            )

            cand = CorrectionCandidateData(
                candidate_id=f"cand_{stage_from}_{stage_to}_p{page_a.physical_page}_{cand_idx}",
                rule_category=category,
                change_type=change_type,
                status=status,
                original_text=old_str,
                proposed_text=new_str,
                evidence=evidence,
            )
            candidates.append(cand)
            cand_idx += 1

        return candidates

    def analyze_alignment_rows(
        self, rows: list[AlignedPageRow]
    ) -> RuleCheckResult:
        all_candidates: list[CorrectionCandidateData] = []

        summary = {
            "total": 0,
            "status": {
                "confirmed": 0,
                "layout_noise": 0,
                "manual_review": 0,
                "unresolved": 0,
            },
            "rule": {
                "site_or_area_name": 0,
                "feature_or_artifact_id": 0,
                "figure_plate_table_photo_ref": 0,
                "numeric_value": 0,
                "direction_period_term": 0,
                "annotation_resolution": 0,
            },
            "change_type": {
                "added": 0,
                "deleted": 0,
                "modified": 0,
                "moved": 0,
            },
        }

        # Compare 3 paths: (1차->2차), (2차->3차), (1차->3차)
        paths = [("1차", "2차"), ("2차", "3차"), ("1차", "3차")]

        for row in rows:
            for st_from, st_to in paths:
                if st_from in row.pages and st_to in row.pages:
                    cands = self.compare_pages(
                        row.pages[st_from],
                        row.pages[st_to],
                        st_from,
                        st_to,
                    )
                    all_candidates.extend(cands)

        summary["total"] = len(all_candidates)
        for c in all_candidates:
            if c.status in summary["status"]:
                summary["status"][c.status] += 1
            if c.rule_category in summary["rule"]:
                summary["rule"][c.rule_category] += 1
            if c.change_type in summary["change_type"]:
                summary["change_type"][c.change_type] += 1

        return RuleCheckResult(candidates=all_candidates, summary=summary)
