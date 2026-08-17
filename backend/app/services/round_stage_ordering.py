from __future__ import annotations

import re


_STAGE_RE = re.compile(r"^(\d+)차$")


def _rank(stage: str) -> tuple[int, int | str]:
    match = _STAGE_RE.match(str(stage).strip())
    if match:
        return (0, int(match.group(1)))
    if stage == "final":
        return (1, 0)
    return (2, str(stage))


def ordered_round_stage_versions(version_pages, version_ids):
    missing = [stage for stage in version_pages if stage not in version_ids]
    if missing:
        raise ValueError(
            "version_ids missing entries for stages: " + ", ".join(sorted(missing))
        )
    ordered = sorted(
        ((version_ids[stage], stage) for stage in version_pages),
        key=lambda pair: _rank(pair[1]),
    )
    for index in range(len(ordered) - 1):
        current_stage = ordered[index][1]
        next_stage = ordered[index + 1][1]
        current_match = _STAGE_RE.match(str(current_stage))
        next_match = _STAGE_RE.match(str(next_stage))
        if current_match and next_match:
            current_sequence = int(current_match.group(1))
            next_sequence = int(next_match.group(1))
            if next_sequence != current_sequence + 1:
                raise ValueError(
                    "Cannot build PRECEDES across a missing round: "
                    f"'{current_stage}' -> '{next_stage}'"
                )
    return ordered
