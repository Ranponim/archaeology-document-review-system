import os
import warnings
from dataclasses import dataclass
from pathlib import Path

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "").strip() or "/data")

OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
LEGACY_AI_API_KEY_ENV = "AI_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

ALLOW_DEGRADED_MODE_ENV = "ALLOW_DEGRADED_MODE"
DRAWING_EVIDENCE_RESOLVER_VERSION_ENV = "DRAWING_EVIDENCE_RESOLVER_VERSION"
DRAWING_EVIDENCE_V3_AUTO_PROMOTE_ENV = "DRAWING_EVIDENCE_V3_AUTO_PROMOTE"


@dataclass(frozen=True, slots=True)
class CodexDrawingResolverConfig:
    api_key: str
    model: str = "gpt-5.3-codex"
    base_url: str = "https://api.openai.com/v1/responses"
    timeout_seconds: float = 60.0
    auto_confidence: float = 0.95
    max_candidates: int = 10
    max_expansions: int = 1

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OPENAI_API_KEY is required for drawing-evidence-v3")
        if not self.model.strip():
            raise ValueError("DRAWING_CODEX_MODEL must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("DRAWING_CODEX_TIMEOUT_SECONDS must be positive")
        if not 0.0 <= self.auto_confidence <= 1.0:
            raise ValueError("DRAWING_CODEX_AUTO_CONFIDENCE must be between 0 and 1")
        if self.max_candidates <= 0:
            raise ValueError("DRAWING_CODEX_MAX_CANDIDATES must be positive")
        if self.max_expansions < 0:
            raise ValueError("DRAWING_CODEX_MAX_EXPANSIONS must be non-negative")

    @classmethod
    def from_env(cls) -> "CodexDrawingResolverConfig":
        api_key = os.environ.get(OPENAI_API_KEY_ENV, "").strip()
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for drawing-evidence-v3")
        try:
            timeout_seconds = float(
                os.environ.get("DRAWING_CODEX_TIMEOUT_SECONDS", "60").strip() or "60"
            )
            auto_confidence = float(
                os.environ.get("DRAWING_CODEX_AUTO_CONFIDENCE", "0.95").strip()
                or "0.95"
            )
            max_candidates = int(
                os.environ.get("DRAWING_CODEX_MAX_CANDIDATES", "10").strip() or "10"
            )
            max_expansions = int(
                os.environ.get("DRAWING_CODEX_MAX_EXPANSIONS", "1").strip() or "1"
            )
        except ValueError as exc:
            raise ValueError("Invalid drawing Codex numeric configuration") from exc
        return cls(
            api_key=api_key,
            model=(
                os.environ.get("DRAWING_CODEX_MODEL", "gpt-5.3-codex").strip()
                or "gpt-5.3-codex"
            ),
            timeout_seconds=timeout_seconds,
            auto_confidence=auto_confidence,
            max_candidates=max_candidates,
            max_expansions=max_expansions,
        )


def get_allow_degraded_mode() -> bool:
    """Production default is False: Neo4j is a mandatory operational dependency
    of the proofreading flow (review P0-2 / anti-pattern #6).

    When False the orchestrator fails closed — a missing graph DB or a missing
    required object evidence bundle never silently falls back to in-memory
    evidence. Degraded mode (explicit in-memory fallback with a recorded
    warning) exists ONLY for local development / explicit tests and must be
    opted into via ALLOW_DEGRADED_MODE=true.
    """
    return os.environ.get(ALLOW_DEGRADED_MODE_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def get_drawing_evidence_resolver_version() -> str:
    """Select the drawing evidence resolver with an explicit rollout gate.

    v1 remains the production default. v2 and v3 require explicit opt-in; v3
    additionally defaults to shadow persistence with auto-promotion disabled.
    """
    raw = os.environ.get(DRAWING_EVIDENCE_RESOLVER_VERSION_ENV, "").strip().lower()
    value = raw or "v1"
    aliases = {
        "v1": "v1",
        "drawing-evidence-v1": "v1",
        "v2": "v2",
        "drawing-evidence-v2": "v2",
        "v3": "v3",
        "drawing-evidence-v3": "v3",
    }
    normalized = aliases.get(value)
    if normalized is None:
        raise ValueError(
            "DRAWING_EVIDENCE_RESOLVER_VERSION must be v1, v2, or v3"
        )
    return normalized


def get_drawing_evidence_v3_auto_promote() -> bool:
    """Return the explicit v3 promotion gate; safe default is shadow-only."""
    return os.environ.get(DRAWING_EVIDENCE_V3_AUTO_PROMOTE_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def get_openrouter_api_key() -> str:
    """Read the unified OpenRouter API key.

    The canonical environment variable is OPENROUTER_API_KEY. The legacy
    AI_API_KEY is honored as an optional alias with a deprecation warning so
    existing deployments keep working while migrating.
    """
    key = os.environ.get(OPENROUTER_API_KEY_ENV, "").strip()
    if key:
        return key
    legacy = os.environ.get(LEGACY_AI_API_KEY_ENV, "").strip()
    if legacy:
        warnings.warn(
            "AI_API_KEY is deprecated; use OPENROUTER_API_KEY instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy
    return ""
