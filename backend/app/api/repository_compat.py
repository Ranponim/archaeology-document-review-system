from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any


class ProjectRepositoryCompatibilityAdapter:
    """Compatibility only for explicitly injected repository implementations."""

    KIND_ALIASES = {
        "plate_book": ("plate_book", "plate_pdf"),
        "drawing_book": ("drawing_book", "drawing_pdf"),
        "report_body": ("report_body",),
    }

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def resolve_version_input(
        self,
        project_id: str,
        kind: str,
        stage: str | None = None,
        version_id: str | None = None,
    ):
        resolver = getattr(self._delegate, "resolve_version_input", None)
        if resolver is not None:
            for candidate_kind in self.KIND_ALIASES.get(kind, (kind,)):
                resolved = resolver(project_id, candidate_kind, stage, version_id)
                if resolved is not None:
                    return resolved
            return None

        getter = getattr(self._delegate, "get_document_version_by_id", None)
        if getter is not None and version_id:
            version = getter(version_id)
            if version is None:
                return None
            detail = self._delegate.get_project(project_id)
            documents = detail.get("documents", []) if isinstance(detail, dict) else []
            doc_by_id = {getattr(doc, "id", None): doc for doc in documents}
            document = doc_by_id.get(getattr(version, "document_id", None))
            actual_kind = getattr(document, "kind", None)
            allowed = self.KIND_ALIASES.get(kind, (kind,))
            if actual_kind not in allowed:
                return None
            if stage is not None and getattr(version, "stage", None) != stage:
                return None
            return SimpleNamespace(
                version_id=getattr(version, "id", version_id),
                document_id=getattr(version, "document_id", None),
                project_id=project_id,
                kind=kind,
                stage=getattr(version, "stage", stage),
                uri=getattr(version, "uri", None),
                sha256=getattr(version, "sha256", None),
                mime_type=getattr(version, "mime_type", "application/pdf"),
            )

        if version_id:
            return SimpleNamespace(version_id=version_id, kind=kind, stage=stage)
        return None


class ReviewRepositoryCompatibilityAdapter:
    """Translate strict project-scoped calls for injected legacy repositories."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    @staticmethod
    def _supports_parameter(fn: Any, name: str) -> bool:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return True
        if name in signature.parameters:
            return True
        return any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )

    def create_analysis_run(self, *args, **kwargs):
        fn = self._delegate.create_analysis_run
        if not self._supports_parameter(fn, "review_round_id"):
            if kwargs.get("review_round_id") is not None:
                raise TypeError("Injected review repository does not support ReviewRound runs")
            kwargs.pop("review_round_id", None)
        return fn(*args, **kwargs)

    def get_candidate(self, project_id: str, candidate_id: str):
        fn = self._delegate.get_candidate
        if self._supports_parameter(fn, "project_id"):
            return fn(project_id, candidate_id)
        candidate = fn(candidate_id)
        if candidate and candidate.get("project_id") not in (None, project_id):
            return None
        return candidate

    def save_review_decision(self, *, project_id: str, candidate_id: str, **kwargs):
        fn = self._delegate.save_review_decision
        if self._supports_parameter(fn, "project_id"):
            return fn(project_id=project_id, candidate_id=candidate_id, **kwargs)
        candidate = self.get_candidate(project_id, candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        return fn(candidate_id=candidate_id, **kwargs)

    def get_candidate_traceability(self, project_id: str, candidate_id: str):
        fn = self._delegate.get_candidate_traceability
        if self._supports_parameter(fn, "project_id"):
            return fn(project_id, candidate_id)
        trace = fn(candidate_id)
        candidate = trace.get("candidate") if isinstance(trace, dict) else None
        if candidate and candidate.get("project_id") not in (None, project_id):
            return {}
        return trace


class VisualAssetServiceCompatibilityAdapter:
    """Adapt legacy injected VisualAssetService to the project-scoped bundle call."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def get_candidate_visual_bundle(self, candidate_id: str, project_id: str | None = None):
        fn = self._delegate.get_candidate_visual_bundle
        try:
            return fn(candidate_id, project_id)
        except TypeError:
            return fn(candidate_id)


class VisualBundleReviewCompatibilityRepository:
    """Ownership shim only when tests inject a visual service without a review repo."""

    def __init__(self, visual_service: Any) -> None:
        self._visual_service = visual_service

    def get_candidate(self, project_id: str, candidate_id: str):
        bundle = self._visual_service.get_candidate_visual_bundle(candidate_id, project_id)
        if bundle is None:
            return None
        return {"id": candidate_id, "project_id": project_id}


def adapt_project_repository(repository: Any | None) -> Any | None:
    if repository is None or isinstance(repository, ProjectRepositoryCompatibilityAdapter):
        return repository
    return ProjectRepositoryCompatibilityAdapter(repository)


def adapt_review_repository(repository: Any | None) -> Any | None:
    if repository is None or isinstance(repository, ReviewRepositoryCompatibilityAdapter):
        return repository
    return ReviewRepositoryCompatibilityAdapter(repository)


def adapt_visual_asset_service(service: Any | None) -> Any | None:
    if service is None or isinstance(service, VisualAssetServiceCompatibilityAdapter):
        return service
    return VisualAssetServiceCompatibilityAdapter(service)
