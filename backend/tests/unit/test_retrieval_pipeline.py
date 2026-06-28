from app.services.retrieval.pipeline import _apply_lexical_rerank


def test_lexical_rerank_promotes_direct_phrase_match() -> None:
    chunks = [
        {"id": "later", "content": "Education and certifications", "rrf_score": 0.5},
        {
            "id": "skills",
            "content": (
                "SOFT SKILLS & COLLABORATION: Problem Solving | "
                "Critical Thinking | Communication"
            ),
            "rrf_score": 0.1,
        },
    ]

    reranked, changed = _apply_lexical_rerank(
        chunks,
        "what is ismaiel soft skills ?",
    )

    assert changed is True
    assert reranked[0]["id"] == "skills"
    assert reranked[0]["lexical_boost"] > 0
