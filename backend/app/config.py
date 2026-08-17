import os
import warnings
from pathlib import Path

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "").strip() or "/data")

OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
LEGACY_AI_API_KEY_ENV = "AI_API_KEY"


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
