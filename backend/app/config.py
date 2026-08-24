import os
import warnings
from pathlib import Path

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "").strip() or "/data")

OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
LEGACY_AI_API_KEY_ENV = "AI_API_KEY"

ALLOW_DEGRADED_MODE_ENV = "ALLOW_DEGRADED_MODE"
DRAWING_EVIDENCE_RESOLVER_VERSION_ENV = "DRAWING_EVIDENCE_RESOLVER_VERSION"


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
    """Select the drawing evidence resolver with a fail-closed rollout gate.

    v1 remains the production default until the local `/src` v2 acceptance
    metrics are reviewed. v2 is available only through an explicit opt-in.
    """
    raw = os.environ.get(DRAWING_EVIDENCE_RESOLVER_VERSION_ENV, "").strip().lower()
    value = raw or "v1"
    aliases = {
        "v1": "v1",
        "drawing-evidence-v1": "v1",
        "v2": "v2",
        "drawing-evidence-v2": "v2",
    }
    normalized = aliases.get(value)
    if normalized is None:
        raise ValueError(
            "DRAWING_EVIDENCE_RESOLVER_VERSION must be v1 or v2"
        )
    return normalized


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
