from app.graph.drawing_evidence_repository import DrawingEvidenceRepository


class ContextDriver:
    def execute_query(self, query, **kwargs):
        if "BODY_DRAWING_CONTEXT" not in query:
            return ([], None, None)
        return ([
            {
                "number": "3",
                "source_id": "caption-d3",
                "source_text": "도면 3. 2지점 유구현황도",
                "reference_text": "도면 3",
                "source_sha256": "body-sha",
                "neighbor_texts": ["2지점 조사", "조선시대 유구 현황"],
                "neighbor_ids": ["b1", "b2"],
            },
            {
                "number": "3",
                "source_id": "caption-i3",
                "source_text": "삽도 3. 2지점 그리드",
                "reference_text": "삽도 3",
                "source_sha256": "body-sha",
                "neighbor_texts": ["2지점 S1E1", "조사구역"],
                "neighbor_ids": ["b3", "b4"],
            },
        ], None, None)


def test_v2_body_context_preserves_one_mention_per_reference_and_kind_namespace():
    contexts = DrawingEvidenceRepository(ContextDriver()).list_body_drawing_contexts("p1")

    assert [(item.publication_kind, item.number) for item in contexts] == [
        ("drawing", "3"),
        ("illustration", "3"),
    ]

    drawing = contexts[0]
    assert drawing.raw_texts == (
        "도면 3. 2지점 유구현황도\n2지점 조사\n조선시대 유구 현황",
    )
    assert drawing.mention_context_ids == ("caption-d3",)
    assert drawing.source_node_ids == ("caption-d3",)

    illustration = contexts[1]
    assert illustration.raw_texts == (
        "삽도 3. 2지점 그리드\n2지점 S1E1\n조사구역",
    )
    assert illustration.mention_context_ids == ("caption-i3",)
