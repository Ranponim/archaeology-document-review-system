from __future__ import annotations

from app.domain.canonical_models import ArchaeologyObjectData
from app.services.corpus_object_linker import CorpusObjectLinker


class FakeRepository:
    def __init__(self, descriptors):
        self.descriptors = descriptors
        self.persisted = []
        self.ambiguous = []

    def list_visual_descriptors(self, project_id: str, corpus_id: str):
        assert (project_id, corpus_id) == ("p1", "c1")
        return self.descriptors

    def link_depicts(self, project_id: str, corpus_id: str, links):
        assert (project_id, corpus_id) == ("p1", "c1")
        self.persisted.extend(links)

    def mark_depicts_ambiguous(self, project_id: str, corpus_id: str, assets):
        assert (project_id, corpus_id) == ("p1", "c1")
        self.ambiguous.extend(assets)


def _object(object_id: str, *, canonical_name: str, point: str = "", number: str = "", type_: str = ""):
    return ArchaeologyObjectData(
        object_id=object_id,
        site="산노리",
        point=point,
        number=number,
        type=type_,
        canonical_name=canonical_name,
        project_id="p1",
    )


def test_unique_strong_identifier_creates_depicts_link():
    repository = FakeRepository(
        [{"label": "Plate", "id": "plate:c1:45", "text": "1지점 청동기시대 6호 석관묘"}]
    )
    linker = CorpusObjectLinker(repository)

    result = linker.link(
        "p1",
        "c1",
        [_object("obj6", canonical_name="1지점 청동기시대 6호 석관묘", point="1지점", number="6호", type_="석관묘")],
    )

    assert [(item.asset_label, item.asset_id, item.object_id) for item in result.created] == [
        ("Plate", "plate:c1:45", "obj6")
    ]
    assert repository.persisted == result.created
    assert result.ambiguous == []


def test_multiple_strong_matches_remain_ambiguous_without_edge():
    repository = FakeRepository(
        [{"label": "Drawing", "id": "drawing:c1:30", "text": "1지점 6호 석관묘 실측도"}]
    )
    linker = CorpusObjectLinker(repository)
    objects = [
        _object("obj-a", canonical_name="1지점 6호 석관묘", point="1지점", number="6호", type_="석관묘"),
        _object("obj-b", canonical_name="1지점 6호 석관묘", point="1지점", number="6호", type_="석관묘"),
    ]

    result = linker.link("p1", "c1", objects)

    assert result.created == []
    assert result.ambiguous == [("Drawing", "drawing:c1:30")]
    assert repository.persisted == []
    assert repository.ambiguous == result.ambiguous


def test_weak_number_and_type_match_alone_never_creates_depicts():
    repository = FakeRepository(
        [{"label": "PlatePanel", "id": "panel:c1:45:1", "text": "6호 석관묘 조사 후"}]
    )
    linker = CorpusObjectLinker(repository)
    obj = _object(
        "obj6",
        canonical_name="산노리 1지점 청동기시대 6호 석관묘",
        point="1지점",
        number="6호",
        type_="석관묘",
    )

    result = linker.link("p1", "c1", [obj])

    assert result.created == []
    assert result.ambiguous == []
    assert result.unmatched == [("PlatePanel", "panel:c1:45:1")]
    assert repository.persisted == []
