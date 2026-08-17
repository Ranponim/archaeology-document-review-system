import os
import warnings
from pathlib import Path

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "").strip() or "/data")

OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
LEGACY_AI_API_KEY_ENV = "AI_API_KEY"

ALLOW_DEGRADED_MODE_ENV = "ALLOW_DEGRADED_MODE"


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
