from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from app.services.asset_cache import AssetHashCache
from app.services.asset_matcher import AssetMatcher, MatchedAssetResult, AssetMatchStatus
from app.services.vlm_review_service import VLMReviewService


@dataclass(frozen=True, slots=True)
class AssetPipelineSummary:
    total_references: int
    status_counts: dict[str, int] = field(default_factory=dict)
    results: list[MatchedAssetResult] = field(default_factory=list)


class AssetReviewPipeline:
    def __init__(
        self,
        matcher: AssetMatcher,
        vlm_service: VLMReviewService,
        cache: AssetHashCache | None = None,
    ) -> None:
        self.matcher = matcher
        self.vlm = vlm_service
        self.cache = cache or AssetHashCache()

    async def review_references(
        self, references: list[dict[str, Any]]
    ) -> AssetPipelineSummary:
        status_counts = {
            "exact": 0,
            "multiple": 0,
            "missing": 0,
            "semantic_review": 0,
        }
        results: list[MatchedAssetResult] = []

        for ref in references:
            ref_type = ref.get("type", "drawing")
            number = str(ref.get("number", ""))
            context = ref.get("context", {})

            # 1. Local zero-cost matching
            match_res = self.matcher.match_reference(
                ref_type=ref_type,
                number=number,
                context=context,
            )

            # 2. If multiple or semantic_review, can optionally resolve via VLM or mark for expert review
            # The baseline status reflects this exact categorization
            results.append(match_res)
            if match_res.status in status_counts:
                status_counts[match_res.status] += 1

        return AssetPipelineSummary(
            total_references=len(references),
            status_counts=status_counts,
            results=results,
        )
