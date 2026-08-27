from __future__ import annotations

from typing import Any

import httpx

from app.config import CodexDrawingResolverConfig
from app.services.codex_drawing_resolver_openai_client import (
    CodexDrawingDecisionError,
    CodexDrawingResolverClient as OpenAIResponsesDrawingResolverClient,
    _DECISION_SCHEMA,
)


class CodexDrawingResolverClient:
    """Select the transport without changing the resolver/evaluator contract.

    OPENAI_API_KEY present -> OpenAI Responses API (existing production path).
    OPENAI_API_KEY absent  -> local Codex Python SDK using existing Codex auth.
    """

    def __new__(
        cls,
        config: CodexDrawingResolverConfig,
        *,
        http_client: httpx.Client | None = None,
        openai_client: Any | None = None,
    ):
        if config.api_key.strip() or openai_client is not None or http_client is not None:
            return OpenAIResponsesDrawingResolverClient(
                config,
                http_client=http_client,
                openai_client=openai_client,
            )

        from app.services.codex_sdk_drawing_resolver_client import (
            CodexSdkDrawingResolverClient,
        )

        return CodexSdkDrawingResolverClient(model=config.model)


__all__ = [
    "CodexDrawingDecisionError",
    "CodexDrawingResolverClient",
    "OpenAIResponsesDrawingResolverClient",
    "_DECISION_SCHEMA",
]
