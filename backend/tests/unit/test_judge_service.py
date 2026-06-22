from types import SimpleNamespace

from app.services.evaluation.judge import JudgeService
from app.workers.tasks import is_flagged


def test_judge_parse_clamps_scores_and_keeps_rationales() -> None:
    result = JudgeService()._parse_response(
        {
            "response": """
            ```json
            {
              "faithfulness": 1.2,
              "faithfulness_rationale": "Grounded.",
              "relevance": 0.8,
              "relevance_rationale": "Relevant context.",
              "completeness": -0.1,
              "completeness_rationale": "Misses details.",
              "citation_accuracy": 0.7,
              "citation_accuracy_rationale": "Citations mostly match."
            }
            ```
            """
        }
    )

    assert result.faithfulness == 1.0
    assert result.relevance == 0.8
    assert result.completeness == 0.0
    assert result.citation_accuracy == 0.7
    assert result.rationale["faithfulness"] == "Grounded."
    assert result.raw_response["response"]


def test_judge_parse_extracts_json_from_extra_text() -> None:
    result = JudgeService()._parse_response(
        'Here is the score: {"faithfulness": 0.9, "faithfulness_rationale": "ok", '
        '"relevance": 0.8, "relevance_rationale": "ok", '
        '"completeness": 0.75, "completeness_rationale": "ok", '
        '"citation_accuracy": 0.6, "citation_accuracy_rationale": "weak"}'
    )

    assert result.citation_accuracy == 0.6
    assert result.rationale["citation_accuracy"] == "weak"


def test_judge_parse_rejects_missing_scores() -> None:
    try:
        JudgeService()._parse_response({"response": '{"faithfulness": "not-a-score"}'})
    except Exception as exc:
        assert "Failed to parse judge response" in str(exc)
    else:
        raise AssertionError("Expected invalid judge response to raise")


def test_is_flagged_when_any_score_is_below_threshold() -> None:
    result = SimpleNamespace(
        faithfulness=0.9,
        relevance=0.7,
        completeness=0.69,
        citation_accuracy=1.0,
    )

    assert is_flagged(result, 0.7) is True


def test_is_not_flagged_when_scores_meet_threshold() -> None:
    result = SimpleNamespace(
        faithfulness=0.9,
        relevance=0.7,
        completeness=0.7,
        citation_accuracy=1.0,
    )

    assert is_flagged(result, 0.7) is False
