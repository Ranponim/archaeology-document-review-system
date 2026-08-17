from app.domain.models import StoredFile
from app.graph.review_project_repository import ReviewProjectRepository


class FakeResult:
    def single(self):
        return {
            "document_id": "doc_1",
            "kind": "report_body",
            "title": "본문",
            "version_id": "ver_4",
        }


class FakeTransaction:
    def __init__(self):
        self.query = ""
        self.params = {}

    def run(self, query, **params):
        self.query = query
        self.params = params
        return FakeResult()


def test_document_version_creation_does_not_create_stage_based_precedes_edges():
    tx = FakeTransaction()
    stored = StoredFile(
        uri="body-v4.pdf",
        sha256="sha",
        size_bytes=10,
        mime_type="application/pdf",
        original_name="본문 수정본.pdf",
    )

    ReviewProjectRepository._create_document_and_version(
        tx,
        "project_1",
        "doc_1",
        "ver_4",
        "ingest_1",
        stored,
        "4차",
        "report_body",
        "본문",
    )

    # ReviewRound.sequence/PRECEDES is the only revision lineage authority.
    assert "[:PRECEDES]" not in tx.query
    assert "prev_stage" not in tx.params
    assert "next_stage" not in tx.params
    # The old stage value may remain as compatibility metadata only.
    assert tx.params["stage"] == "4차"
