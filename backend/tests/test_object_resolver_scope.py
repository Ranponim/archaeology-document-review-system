from typing import Any
import pytest

from app.domain.canonical_models import ArchaeologyObjectData
from app.domain.document_structure import TextBlockData
from app.graph.canonical_repository import CanonicalRepository
from app.services.object_resolver import ObjectResolver


class FakeNeo4jRecord:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeNeo4jDriver:
    def __init__(self, records_by_query_marker: list[tuple[str, list[dict[str, Any]]]] | None = None):
        self.queries: list[dict[str, Any]] = []
        self._records_map = records_by_query_marker or []

    def execute_query(self, query: str, **kwargs):
        self.queries.append({"query": query, "kwargs": kwargs})
        for marker, records in self._records_map:
            if marker in query:
                return [FakeNeo4jRecord(r) for r in records], None, None
        return [], None, None


def test_generate_object_id_project_scoping_distinct_ids():
    """Requirement 1: generate_object_id with different project_id for identical object strings returns distinct IDs."""
    site = "논산 산노리 산17-1번지"
    canonical_name = "1지점 청동기시대 6호 석관묘"

    id_proj_a = ObjectResolver.generate_object_id(
        project_id="proj_aaa",
        site=site,
        canonical_name=canonical_name,
    )
    id_proj_b = ObjectResolver.generate_object_id(
        project_id="proj_bbb",
        site=site,
        canonical_name=canonical_name,
    )

    assert id_proj_a != id_proj_b
    assert id_proj_a.startswith("obj_")
    assert id_proj_b.startswith("obj_")

    # Identical project + site + canonical_name must be deterministic
    id_proj_a_repeat = ObjectResolver.generate_object_id(
        project_id="proj_aaa",
        site=site,
        canonical_name=canonical_name,
    )
    assert id_proj_a == id_proj_a_repeat


def test_resolve_mentions_attaches_project_id_and_scoped_id():
    """Requirement 1: resolve_mentions attaches project_id and project-scoped ID to resolved objects."""
    resolver = ObjectResolver()
    blocks = [
        TextBlockData(
            block_id="b1",
            text="1지점 청동기시대 6호 석관묘가 확인되었다.",
            normalized_text="1지점 청동기시대 6호 석관묘가 확인되었다.",
            order=1,
        )
    ]

    res_a = resolver.resolve_mentions(blocks=blocks, project_id="proj_alpha", site="논산")
    res_b = resolver.resolve_mentions(blocks=blocks, project_id="proj_beta", site="논산")

    assert len(res_a) == 1
    assert len(res_b) == 1

    obj_a = res_a[0].object_data
    obj_b = res_b[0].object_data

    assert obj_a.project_id == "proj_alpha"
    assert obj_b.project_id == "proj_beta"
    assert obj_a.canonical_name == "1지점 청동기시대 6호 석관묘"
    assert obj_b.canonical_name == "1지점 청동기시대 6호 석관묘"
    assert obj_a.object_id != obj_b.object_id
    assert obj_a.object_id == resolver.generate_object_id("proj_alpha", "논산", "1지점 청동기시대 6호 석관묘")
    assert obj_b.object_id == resolver.generate_object_id("proj_beta", "논산", "1지점 청동기시대 6호 석관묘")


def test_resolve_mentions_text_convenience_signature():
    """Requirement 1: resolve_mentions with text parameter attaches project_id and project-scoped ID."""
    resolver = ObjectResolver()
    results = resolver.resolve_mentions(
        text="논산 산노리 산17-1번지 1지점 청동기시대 6호 석관묘 발굴조사 결과",
        project_id="proj_gamma",
    )

    assert len(results) >= 1
    obj = results[0].object_data
    assert obj.project_id == "proj_gamma"
    assert obj.site == "논산 산노리 산17-1번지"
    assert obj.canonical_name == "1지점 청동기시대 6호 석관묘"
    assert obj.object_id == resolver.generate_object_id("proj_gamma", "논산 산노리 산17-1번지", "1지점 청동기시대 6호 석관묘")


def test_canonical_repo_save_archaeology_objects_sets_project_id_and_has_object_edge():
    """Requirement 2: save_archaeology_objects sets projectId on object node and merges (project)-[:HAS_OBJECT]->(obj)."""
    driver = FakeNeo4jDriver()
    repo = CanonicalRepository(driver=driver, database="test_db")

    objs = [
        ArchaeologyObjectData(
            object_id="obj_scoped_1",
            site="논산 산노리",
            point="1지점",
            period="청동기시대",
            type="석관묘",
            number="6호",
            canonical_name="1지점 청동기시대 6호 석관묘",
            project_id="proj_target",
        )
    ]

    repo.save_archaeology_objects(objects=objs, project_id="proj_target")

    assert len(driver.queries) == 1
    q = driver.queries[0]
    cypher = q["query"]
    kwargs = q["kwargs"]

    assert "obj.projectId" in cypher
    assert "HAS_OBJECT" in cypher
    assert kwargs.get("project_id") == "proj_target"
    assert kwargs["objects"][0]["id"] == "obj_scoped_1"
    assert kwargs["objects"][0]["project_id"] == "proj_target"


def test_canonical_repo_get_object_evidence_bundle_version_filtering_and_run_id():
    """Requirement 2: get_object_evidence_bundle filters evidence to document_version_ids and attaches analysis_run_id."""
    # Setup mock responses for identity, text claims, references, visual claims, candidate evidences
    identity_records = [{"obj": {"id": "obj_scoped_1", "canonical_name": "1지점 청동기시대 6호 석관묘", "projectId": "proj_target"}}]
    text_claims_records = [
        {
            "source": {"id": "b1", "text": "1지점 청동기시대 6호 석관묘는 v1에 기술됨", "source_sha256": "sha_v1"},
            "page": {"id": "v1_p1", "physical_page": 1, "printed_page": 1},
            "version": {"id": "ver_v1", "sha256": "sha_v1", "stage": "1차"},
        },
        {
            "source": {"id": "b2", "text": "1지점 청동기시대 6호 석관묘는 v2에 오염됨", "source_sha256": "sha_v2"},
            "page": {"id": "v2_p1", "physical_page": 1, "printed_page": 1},
            "version": {"id": "ver_v2", "sha256": "sha_v2", "stage": "2차"},
        },
    ]
    ref_records = [
        {
            "source": {"id": "b1"},
            "ref": {"id": "ref_plate_6", "ref_type": "plate", "number": "6", "raw_text": "도판 6", "physical_page": 1},
            "page": {"id": "v1_p1", "physical_page": 1},
            "version": {"id": "ver_v1", "sha256": "sha_v1", "stage": "1차"},
        },
        {
            "source": {"id": "b2"},
            "ref": {"id": "ref_plate_99", "ref_type": "plate", "number": "99", "raw_text": "도판 99", "physical_page": 1},
            "page": {"id": "v2_p1", "physical_page": 1},
            "version": {"id": "ver_v2", "sha256": "sha_v2", "stage": "2차"},
        },
    ]
    visual_records = [
        {
            "asset_label": "Plate",
            "asset": {"id": "pl_6", "number": "6", "title": "1지점 청동기시대 6호 석관묘", "document_version_id": "ver_v1", "physical_page": 10},
            "ref": {"id": "ref_plate_6"},
            "page": {"id": "v1_p10"},
            "version": {"id": "ver_v1", "sha256": "sha_v1", "stage": "1차"},
        },
        {
            "asset_label": "Plate",
            "asset": {"id": "pl_99", "number": "99", "title": "1지점 청동기시대 6호 석관묘", "document_version_id": "ver_v2", "physical_page": 20},
            "ref": {"id": "ref_plate_99"},
            "page": {"id": "v2_p20"},
            "version": {"id": "ver_v2", "sha256": "sha_v2", "stage": "2차"},
        },
    ]
    cand_records: list[dict[str, Any]] = []

    records_map = [
        ("RETURN properties(obj) AS obj", identity_records),
        ("-[:REFERENCES]->(ref:Reference)", ref_records),
        ("-[:MENTIONS]->(obj:ArchaeologyObject", text_claims_records),
        ("-[:DEPICTS]->(obj:ArchaeologyObject", visual_records),
        ("CorrectionCandidate", cand_records),
    ]

    driver = FakeNeo4jDriver(records_by_query_marker=records_map)
    repo = CanonicalRepository(driver=driver, database="test_db")

    bundle = repo.get_object_evidence_bundle(
        object_id="obj_scoped_1",
        analysis_run_id="run_test_123",
        document_version_ids=["ver_v1"],
    )

    assert bundle is not None
    assert bundle.object_id == "obj_scoped_1"
    assert bundle.canonical_name == "1지점 청동기시대 6호 석관묘"

    # Only ver_v1 evidences must be in bundle (ver_v2 contaminated evidence filtered out)
    assert len(bundle.text_claims) == 1
    assert bundle.text_claims[0].document_version_id == "ver_v1"
    assert bundle.text_claims[0].analysis_run_id == "run_test_123"

    assert len(bundle.references) == 1
    assert bundle.references[0].document_version_id == "ver_v1"
    assert bundle.references[0].analysis_run_id == "run_test_123"

    assert len(bundle.plate_claims) == 1
    assert bundle.plate_claims[0].document_version_id == "ver_v1"
    assert bundle.plate_claims[0].analysis_run_id == "run_test_123"

    # Check query kwargs passed document_version_ids
    for q in driver.queries:
        if "MENTIONS" in q["query"] or "REFERENCES" in q["query"] or "DEPICTS" in q["query"]:
            assert q["kwargs"].get("document_version_ids") == ["ver_v1"]
