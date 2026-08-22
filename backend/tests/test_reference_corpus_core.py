import importlib
import importlib.util

import pytest

from app.domain.source_assets import OriginalAssetData


@pytest.mark.parametrize(
    "module_name",
    [
        "app.domain.reference_corpus",
        "app.domain.adobe_manifest",
        "app.services.adobe_conversion_client",
        "app.services.reference_canonicalizer",
    ],
)
def test_reference_corpus_core_modules_exist(module_name: str) -> None:
    assert importlib.util.find_spec(module_name) is not None


def _load_core():
    corpus = importlib.import_module("app.domain.reference_corpus")
    manifest = importlib.import_module("app.domain.adobe_manifest")
    canonicalizer = importlib.import_module("app.services.reference_canonicalizer")
    return corpus, manifest, canonicalizer


def _asset(asset_id: str, relative_path: str, kind: str = "linked_photo") -> OriginalAssetData:
    return OriginalAssetData(
        id=asset_id,
        project_id="00000000-0000-0000-0000-000000000001",
        uri=f"incoming/source/{asset_id}",
        sha256=f"sha-{asset_id}",
        size_bytes=10,
        mime_type="image/jpeg" if kind == "linked_photo" else "application/octet-stream",
        original_name=relative_path.rsplit("/", 1)[-1],
        relative_path=relative_path,
        asset_kind=kind,
        source_root_name="source",
        import_batch_id="batch-1",
        parse_status="stored",
        provenance_status="unlinked",
    )


def test_build_identity_is_stable_and_version_sensitive() -> None:
    corpus, _manifest, _canonicalizer = _load_core()
    first = corpus.compute_build_identity("sources", "converter-1", "manifest-1", "canon-1")
    again = corpus.compute_build_identity("sources", "converter-1", "manifest-1", "canon-1")
    changed = corpus.compute_build_identity("sources", "converter-1", "manifest-1", "canon-2")
    assert first == again
    assert first != changed


def test_indesign_manifest_preserves_dom_text_and_link_identity() -> None:
    _corpus, manifest_module, _canonicalizer = _load_core()
    manifest = manifest_module.AdobeManifestV1.from_dict(
        {
            "schemaVersion": 1,
            "application": "indesign",
            "sourceAssetId": "indd-1",
            "sourceSha256": "indd-sha",
            "pages": [
                {
                    "index": 0,
                    "label": "1",
                    "textFrames": [
                        {"objectId": "t1", "text": "【도판 45】", "bounds": [0, 0, 10, 10]},
                    ],
                    "graphics": [
                        {
                            "objectId": "g1",
                            "linkId": "link-301",
                            "linkPath": "Links/photo.jpg",
                            "bounds": [10, 10, 90, 90],
                        }
                    ],
                }
            ],
        }
    )
    assert manifest.pages[0].text_frames[0].text == "【도판 45】"
    assert manifest.pages[0].graphics[0].link_id == "link-301"


def test_filename_number_never_creates_canonical_identity() -> None:
    _corpus, _manifest, canonicalizer_module = _load_core()
    result = canonicalizer_module.ReferenceCanonicalizer().canonicalize(
        "corpus-1",
        manifests=[],
        assets=[_asset("photo-45", "Links/조사후_45.JPG")],
    )
    assert result.plates == []
    assert result.drawings == []


def test_indesign_internal_identifier_and_placement_create_plate_panel_provenance() -> None:
    _corpus, manifest_module, canonicalizer_module = _load_core()
    manifest = manifest_module.AdobeManifestV1.from_dict(
        {
            "schemaVersion": 1,
            "application": "indesign",
            "sourceAssetId": "indd-1",
            "sourceSha256": "indd-sha",
            "pages": [
                {
                    "index": 44,
                    "label": "45",
                    "textFrames": [
                        {"objectId": "header", "text": "【도판 45】 1지점 6호 석관묘", "bounds": [0, 0, 90, 10]},
                        {"objectId": "caption", "text": "① 조사 후", "bounds": [20, 20, 25, 25]},
                    ],
                    "graphics": [
                        {
                            "objectId": "photo-frame",
                            "linkId": "link-301",
                            "linkPath": "Links/photo.jpg",
                            "bounds": [10, 10, 90, 90],
                        }
                    ],
                }
            ],
        }
    )
    result = canonicalizer_module.ReferenceCanonicalizer().canonicalize(
        "corpus-1",
        manifests=[manifest],
        assets=[_asset("photo-1", "Links/photo.jpg")],
    )
    assert [plate.number for plate in result.plates] == ["45"]
    assert result.plates[0].plate_id == "plate:corpus-1:45"
    assert result.plates[0].panels[0].panel_index == 1
    assert result.plates[0].panels[0].source_asset_id == "photo-1"


def test_duplicate_internal_drawing_identifier_fails_closed() -> None:
    _corpus, manifest_module, canonicalizer_module = _load_core()
    def drawing_manifest(asset_id: str):
        return manifest_module.AdobeManifestV1.from_dict(
            {
                "schemaVersion": 1,
                "application": "illustrator",
                "sourceAssetId": asset_id,
                "sourceSha256": f"sha-{asset_id}",
                "artboards": [
                    {
                        "index": 0,
                        "name": "Artboard 1",
                        "textFrames": [
                            {"objectId": f"{asset_id}-t", "text": "【도면 30】 1지점 6호 석관묘 평단면도", "bounds": [0, 0, 100, 10]},
                        ],
                    }
                ],
            }
        )

    with pytest.raises(canonicalizer_module.CanonicalizationError) as error:
        canonicalizer_module.ReferenceCanonicalizer().canonicalize(
            "corpus-1",
            manifests=[drawing_manifest("ai-1"), drawing_manifest("ai-2")],
            assets=[],
        )
    assert error.value.code == "DUPLICATE_CANONICAL_IDENTIFIER"
