"""Gate C — Case 6 canonical identity (plan §3 Gate C, §6 Test 2).

With photo files named `4. 조사 후_45.JPG` / `photo_45.JPG` / `조사후_45.JPG`
present as OriginalAsset nodes, the canonical Plate 45 exists only through the
publication identifier 【도판 45】. Reference(plate,45) must RESOLVES_TO
Plate(number=45, raw_identifier="【도판 45】"), and no OriginalAsset / Evidence /
identity path may claim `4. 조사 후_45.JPG` is Plate 45 solely from filename
digits. Scoped ids (it_<uuid8>_) are deleted in finally.
"""
import uuid

from app.domain.canonical_models import PlateData, ReferenceData
from app.domain.document_structure import make_reference_id
from app.domain.models import StoredFile
from app.graph.canonical_repository import CanonicalRepository
from app.graph.project_repository import ProjectRepository

TRAP_FILENAME = "4. 조사 후_45.JPG"
OTHER_FILENAMES = ["photo_45.JPG", "조사후_45.JPG"]


def _stored(scope: str, name: str) -> StoredFile:
    return StoredFile(
        uri=f"incoming/{scope}/{name}",
        sha256=f"sha256_{scope}_{name}",
        size_bytes=1,
        mime_type="image/jpeg",
        original_name=name,
    )


def test_real_neo4j_case6_canonical_identity(neo4j_driver, scoped_prefix, cleanup, create_project):
    """Gate C: Reference(plate,45) resolves to canonical Plate 45 and the trap
    filename never appears in any identity path."""
    scope = scoped_prefix
    project_repo = ProjectRepository(neo4j_driver)
    project_id = create_project(scope, f"{scope} project")
    _plate_doc, plate_ver = project_repo.create_document_with_version(
        project_id=project_id,
        stored=_stored(scope, "plate.pdf"),
        stage="1차",
        kind="plate_book",
    )

    canonical_repo = CanonicalRepository(neo4j_driver)
    plate = PlateData(
        plate_id=f"{scope}_plate45",
        number="45",
        physical_page=47,
        title="1지점 청동기시대 6호 석관묘",
        source_sha256=f"sha256_{scope}_plate",
        document_version_id=plate_ver.id,
        raw_identifier="【도판 45】",
    )
    block_id = f"{scope}_b1"
    reference = ReferenceData(
        ref_type="plate",
        number="45",
        source_block_id=block_id,
        raw_text="【도판 45】",
        source_sha256=f"sha256_{scope}_body",
        physical_page=1,
    )
    ref_id = make_reference_id(block_id, "plate", "45")

    try:
        canonical_repo.save_plates([plate])
        canonical_repo.save_references([reference])
        canonical_repo.link_reference_to_target(ref_id, "Plate", plate.plate_id)

        # Photo files present as OriginalAsset nodes (never linked to Plate 45)
        for idx, filename in enumerate([TRAP_FILENAME] + OTHER_FILENAMES):
            neo4j_driver.execute_query(
                """
                CREATE (oa:OriginalAsset {id: $id, filename: $filename,
                        original_name: $filename, source_kind: 'photo'})
                """,
                id=f"{scope}_asset{idx}",
                filename=filename,
            )

        # Reference(plate,45) -[:RESOLVES_TO]-> Plate(45)
        recs, _, _ = neo4j_driver.execute_query(
            """
            MATCH (r:Reference {id: $ref_id})-[:RESOLVES_TO]->(p:Plate {id: $plate_id})
            RETURN r.ref_type AS ref_type, r.number AS number,
                   p.number AS plate_number, p.raw_identifier AS raw_identifier
            """,
            ref_id=ref_id,
            plate_id=plate.plate_id,
        )
        assert len(recs) == 1, "Reference(plate,45) must RESOLVES_TO Plate 45"
        assert recs[0]["ref_type"] == "plate"
        assert recs[0]["number"] == "45"
        assert recs[0]["plate_number"] == "45"
        assert recs[0]["raw_identifier"] == "【도판 45】"

        # Canonical target identity never contains the trap filename
        recs_id, _, _ = neo4j_driver.execute_query(
            """
            MATCH (p:Plate {id: $plate_id})
            RETURN p.raw_identifier AS raw_identifier, p.title AS title,
                   p.source_kind AS source_kind
            """,
            plate_id=plate.plate_id,
        )
        identity_values = [
            str(v)
            for v in (
                recs_id[0]["raw_identifier"],
                recs_id[0]["title"],
                recs_id[0]["source_kind"],
            )
            if v is not None
        ]
        assert all(TRAP_FILENAME not in v for v in identity_values), (
            "Plate 45 identity must never contain the trap filename"
        )

        # No OriginalAsset with the trap filename is connected to Plate 45
        recs_oa, _, _ = neo4j_driver.execute_query(
            """
            MATCH (oa:OriginalAsset {filename: $filename})
            OPTIONAL MATCH (oa)-[r]-(p:Plate {id: $plate_id})
            RETURN count(r) AS links
            """,
            filename=TRAP_FILENAME,
            plate_id=plate.plate_id,
        )
        assert recs_oa[0]["links"] == 0, (
            "OriginalAsset '4. 조사 후_45.JPG' must not be linked to Plate 45"
        )

        # No Evidence whose value/rationale contains the trap filename is
        # connected to Plate 45
        recs_ev, _, _ = neo4j_driver.execute_query(
            """
            MATCH (ev:Evidence)
            WHERE ev.value CONTAINS $filename OR ev.rationale CONTAINS $filename
            OPTIONAL MATCH (ev)-[r]-(p:Plate {id: $plate_id})
            RETURN count(r) AS links
            """,
            filename=TRAP_FILENAME,
            plate_id=plate.plate_id,
        )
        assert recs_ev[0]["links"] == 0, (
            "no Evidence claiming the trap filename may be linked to Plate 45"
        )
    finally:
        cleanup(scope)