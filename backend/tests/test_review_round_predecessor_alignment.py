from pathlib import Path

import pytest

from app.domain.models import VersionInput
from app.jobs.run_inputs import resolve_round_body_versions_for_alignment


class NoStageLookupRepository:
    def resolve_version_input(self, *args, **kwargs):
        raise AssertionError("ReviewRound alignment must not perform stage lookup")


class RecordingParser:
    def __init__(self):
        self.calls = []

    def parse_pdf(self, path: Path, *, version_id: str):
        self.calls.append((Path(path), version_id))
        return [object()]


@pytest.mark.anyio
async def test_round_alignment_uses_explicit_previous_and_current_versions(tmp_path):
    previous_pdf = tmp_path / "body-v2.pdf"
    current_pdf = tmp_path / "body-v3.pdf"
    previous_pdf.write_bytes(b"%PDF-1.4 previous")
    current_pdf.write_bytes(b"%PDF-1.4 current")

    previous = VersionInput(
        version_id="body_v2",
        document_id="doc_body",
        project_id="p1",
        kind="report_body",
        stage="source",
        uri=str(previous_pdf),
        sha256="sha-v2",
    )
    current = VersionInput(
        version_id="body_v3",
        document_id="doc_body",
        project_id="p1",
        kind="report_body",
        stage="source",
        uri=str(current_pdf),
        sha256="sha-v3",
    )
    parser = RecordingParser()

    pages, version_ids = await resolve_round_body_versions_for_alignment(
        project_repository=NoStageLookupRepository(),
        project_id="p1",
        current_body=current,
        previous_body=previous,
        current_pdf_path=None,
        pdf_parser=parser,
    )

    assert list(pages) == ["previous", "current"]
    assert version_ids == {"previous": "body_v2", "current": "body_v3"}
    assert [version_id for _, version_id in parser.calls] == ["body_v2", "body_v3"]


@pytest.mark.anyio
async def test_first_round_alignment_has_only_current_body(tmp_path):
    current_pdf = tmp_path / "body-v1.pdf"
    current_pdf.write_bytes(b"%PDF-1.4 current")
    current = VersionInput(
        version_id="body_v1",
        document_id="doc_body",
        project_id="p1",
        kind="report_body",
        stage="source",
        uri=str(current_pdf),
        sha256="sha-v1",
    )
    parser = RecordingParser()

    pages, version_ids = await resolve_round_body_versions_for_alignment(
        project_repository=NoStageLookupRepository(),
        project_id="p1",
        current_body=current,
        previous_body=None,
        current_pdf_path=None,
        pdf_parser=parser,
    )

    assert list(pages) == ["current"]
    assert version_ids == {"current": "body_v1"}
