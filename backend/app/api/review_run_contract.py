from pydantic import Field

from app.api.schemas import ApiModel


class ReviewRoundRunTriggerRequest(ApiModel):
    """Production proofreading run contract.

    A run is started from one graph-resident ReviewRound. Body/plate/drawing
    version ids, server file paths, and human stage labels are deliberately not
    accepted as authoritative run inputs. Unknown legacy fields are ignored by
    Pydantic, but they cannot establish a run without reviewRoundId.
    """

    review_round_id: str = Field(min_length=1, alias="reviewRoundId")
    enable_vlm: bool = Field(default=True, alias="enableVlm")
    enable_ai_review: bool = Field(default=True, alias="enableAiReview")
