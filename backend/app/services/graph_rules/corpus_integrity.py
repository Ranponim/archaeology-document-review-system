from __future__ import annotations

from .models import CorpusIntegrityError


def enforce_corpus_integrity(repository, project_id: str, corpus_id: str) -> None:
    report = repository.validate_corpus_integrity(project_id, corpus_id)
    if not bool(getattr(report, "ok", False)):
        errors = tuple(getattr(report, "errors", ()) or ("CORPUS_INTEGRITY_FAILED",))
        raise CorpusIntegrityError(errors)
