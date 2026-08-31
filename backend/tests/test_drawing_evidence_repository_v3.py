from app.graph.drawing_evidence_repository import DrawingEvidenceRepository


class V3ContextDriver:
    def execute_query(self, query, **kwargs):
        if "BODY_DRAWING_V3_CONTEXT" not in query:
            return ([], None, None)
        return (
            [
                {
                    "number": "52",
                    "source_id": "caption-d52",
                    "source_text": "도면 52. 2지점 조선시대 1호 토광묘",
                    "reference_text": "도면 52",
                    "source_sha256": "body-sha",
                    "document_version_id": "version-1",
                    "physical_page": 12,
                    "source_bbox": [10, 20, 110, 220],
                    "neighbor_texts": ["2지점 조사", "평단면"],
                    "neighbor_ids": ["block-1", "block-2"],
                },
                {
                    "number": "52",
                    "source_id": "caption-d52-b",
                    "source_text": "도면 52. 1호 토광묘 평단면",
                    "reference_text": "도면 52",
                    "source_sha256": "body-sha",
                    "document_version_id": "version-1",
                    "physical_page": 13,
                    "source_bbox": [15, 25, 115, 225],
                    "neighbor_texts": ["조선시대"],
                    "neighbor_ids": ["block-3"],
                },
                {
                    "number": "52",
                    "source_id": "caption-i52",
                    "source_text": "삽도 52. 유적 위치",
                    "reference_text": "삽도 52",
                    "source_sha256": "body-sha",
                    "document_version_id": "version-1",
                    "physical_page": 14,
                    "source_bbox": [20, 30, 120, 230],
                    "neighbor_texts": ["위성지도"],
                    "neighbor_ids": ["block-4"],
                },
            ],
            None,
            None,
        )


def test_v3_body_context_returns_page_bbox_version_and_separate_mentions():
    contexts = DrawingEvidenceRepository(V3ContextDriver()).list_body_drawing_v3_contexts(
        "p1"
    )

    assert [(item.publication_kind, item.number) for item in contexts] == [
        ("drawing", "52"),
        ("drawing", "52"),
        ("illustration", "52"),
    ]

    first = contexts[0]
    assert first.raw_texts == (
        "도면 52. 2지점 조선시대 1호 토광묘\n2지점 조사\n평단면",
    )
    assert first.source_node_ids == ("caption-d52",)
    assert first.source_sha256 == "body-sha"
    assert first.document_version_id == "version-1"
    assert first.physical_page == 12
    assert first.source_bbox == (10.0, 20.0, 110.0, 220.0)
    assert first.visual_regions == ()

    second = contexts[1]
    assert second.source_node_ids == ("caption-d52-b",)
    assert second.physical_page == 13

    illustration = contexts[2]
    assert illustration.publication_kind == "illustration"
    assert illustration.source_node_ids == ("caption-i52",)
    assert illustration.physical_page == 14
