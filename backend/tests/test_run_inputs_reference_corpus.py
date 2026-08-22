from __future__ import annotations

import pytest

from app.jobs import run_inputs
from app.jobs.run_inputs import resolve_reference_corpus_indexes_for_run


class FakeDriver:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []
        self.responses = [
            [
                {
                    "plate": {
                        "id": "plate:corpus-1:45",
                        "number": "45",
                        "physical_page": 1,
                        "title": "6호 석관묘",
                        "referenceCorpusId": "corpus-1",
                        "raw_identifier": "【도판 45】",
                        "source_kind": "indesign_source",
                    },
                    "panels": [
                        {
                            "id": "plate-panel:corpus-1:45:1",
                            "plate_id": "plate:corpus-1:45",
                            "panel_index": 1,
                            "caption": "조사 후",
                            "sourceAssetId": "asset-photo",
                        }
                    ],
                }
            ],
            [
                {
                    "drawing": {
                        "id": "drawing:corpus-1:30",
                        "number": "30",
                        "physical_page": 1,
                        "title": "6호 석관묘 실측도",
                        "referenceCorpusId": "corpus-1",
                        "raw_identifier": "【도면 30】",
                        "source_kind": "illustrator_source",
                    },
                    "regions": [],
                }
            ],
        ]

    def execute_query(self, query: str, **kwargs):
        self.queries.append((query, kwargs))
        return self.responses.pop(0), None, None


class FakeCanonicalRepository:
    def __init__(self) -> None:
        self._driver = FakeDriver()
        self._database = None

    def _query_config(self):
        return {}


@pytest.mark.asyncio
async def test_corpus_visual_indexes_are_loaded_only_from_selected_corpus_graph(monkeypatch):
    repository = FakeCanonicalRepository()

    def forbidden_pdf_fallback(*args, **kwargs):
        raise AssertionError("corpus mode must never resolve a visual PDF path")

    monkeypatch.setattr(run_inputs, "_resolve_asset_pdf_path", forbidden_pdf_fallback)

    plates, drawings = await resolve_reference_corpus_indexes_for_run(
        canonical_repo=repository,
        project_id="p1",
        reference_corpus_id="corpus-1",
    )

    assert plates.get_plate("45").plate_id == "plate:corpus-1:45"
    assert plates.get_plate("45").reference_corpus_id == "corpus-1"
    assert plates.get_plate("45").panels[0].source_asset_id == "asset-photo"
    assert drawings.get_drawing("30").drawing_id == "drawing:corpus-1:30"
    assert drawings.get_drawing("30").reference_corpus_id == "corpus-1"
    queries = "\n".join(query for query, _kwargs in repository._driver.queries)
    assert "HAS_REFERENCE_CORPUS" in queries
    assert "HAS_PLATE" in queries
    assert "HAS_DRAWING" in queries
    assert "DocumentVersion" not in queries


@pytest.mark.asyncio
async def test_corpus_visual_index_loader_fails_closed_without_graph_repository():
    with pytest.raises(ValueError, match="canonical graph"):
        await resolve_reference_corpus_indexes_for_run(
            canonical_repo=None,
            project_id="p1",
            reference_corpus_id="corpus-1",
        )
