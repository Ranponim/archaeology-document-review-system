from pydantic import ConfigDict, Field

from app.api.schemas import ApiModel


class ReviewRoundRunTriggerRequest(ApiModel):
    """Strict production proofreading-run contract.

    A run starts from exactly one graph-resident ReviewRound. Direct document
    version ids, server file paths, and human stage labels are intentionally
    absent. Unknown fields are rejected instead of silently ignored so a
    client cannot believe it overrode graph authority. Graph review is the
    default authority; AI/VLM deep review is explicitly opt-in.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    review_round_id: str = Field(min_length=1, alias="reviewRoundId")
    enable_vlm: bool = Field(default=False, alias="enableVlm")
    enable_ai_review: bool = Field(default=False, alias="enableAiReview")
