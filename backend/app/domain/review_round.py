from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReviewRound:
    id: str
    project_id: str
    sequence: int
    status: str = "reviewing"
    body_version_id: str | None = None
    plate_version_id: str | None = None
    drawing_version_id: str | None = None
    created_at: datetime | str | None = None
    approved_at: datetime | str | None = None
    notes: str | None = None
