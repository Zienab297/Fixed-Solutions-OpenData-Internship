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


def test_numeric_lookup_calibration_boosts_supported_cited_value() -> None:
    service = JudgeService()
    result = service._parse_response(
        {
            "response": """
            {
              "faithfulness": 0.8,
              "faithfulness_rationale": "Mostly supported.",
              "relevance": 0.9,
              "relevance_rationale": "Relevant.",
              "completeness": 0.7,
              "completeness_rationale": "Could include more table details.",
              "citation_accuracy": 0.8,
              "citation_accuracy_rationale": "Likely cited correctly."
            }
            """
        }
    )

    calibrated = service._apply_numeric_lookup_calibration(
        result=result,
        query=(
            "What is the value when the higher-paying job annual wage is "
            "$30,000 - $39,999 and the lower-paying job wage is $20,000 - $29,999?"
        ),
        answer="According to [Source 1], the value is $2,390.",
        context=[
            {
                "source_number": 1,
                "content": (
                    "Higher Paying Job $30,000 - 39,999. "
                    "Lower Paying Job $20,000 - 29,999. $2,390"
                ),
            }
        ],
    )

    assert calibrated.faithfulness == 0.95
    assert calibrated.relevance == 0.95
    assert calibrated.completeness == 0.95
    assert calibrated.citation_accuracy == 0.95
    assert calibrated.raw_response["numeric_lookup_check"]["answer_values"] == ["2390"]


def test_numeric_lookup_calibration_caps_wrong_cited_source() -> None:
    service = JudgeService()
    result = service._parse_response(
        {
            "response": """
            {
              "faithfulness": 1.0,
              "faithfulness_rationale": "Supported.",
              "relevance": 1.0,
              "relevance_rationale": "Relevant.",
              "completeness": 1.0,
              "completeness_rationale": "Complete.",
              "citation_accuracy": 1.0,
              "citation_accuracy_rationale": "All citations correct."
            }
            """
        }
    )

    calibrated = service._apply_numeric_lookup_calibration(
        result=result,
        query="What is the value when the wage is $30,000 - $39,999?",
        answer="According to [Source 1], the value is $2,760.",
        context=[
            {"source_number": 1, "content": "The table value is $2,390."},
            {"source_number": 2, "content": "Another table value is $2,760."},
        ],
    )

    assert calibrated.faithfulness == 0.85
    assert calibrated.citation_accuracy == 0.6
    assert "not in the cited source" in calibrated.rationale["citation_accuracy"]


def test_refusal_calibration_caps_scores_when_context_has_relevant_answer() -> None:
    service = JudgeService()
    result = service._parse_response(
        {
            "response": """
            {
              "faithfulness": 1.0,
              "faithfulness_rationale": "The refusal is grounded.",
              "relevance": 0.0,
              "relevance_rationale": "No relevant context.",
              "completeness": 1.0,
              "completeness_rationale": "It answered with a refusal.",
              "citation_accuracy": 1.0,
              "citation_accuracy_rationale": "No citations needed."
            }
            """
        }
    )

    calibrated = service._apply_refusal_calibration(
        result=result,
        query="what is ismaiel soft skills ?",
        answer="Unfortunately, I don't have enough information in the selected documents to answer that.",
        context=[
            {
                "source_number": 1,
                "content": (
                    "SOFT SKILLS & COLLABORATION: Problem Solving | "
                    "Critical Thinking | Communication"
                ),
            }
        ],
    )

    assert calibrated.faithfulness == 0.6
    assert calibrated.relevance == 0.8
    assert calibrated.completeness == 0.0
    assert calibrated.citation_accuracy == 0.0
    assert calibrated.raw_response["refusal_check"]["context_appears_relevant"] is True


def test_refusal_calibration_never_awards_complete_for_empty_context() -> None:
    service = JudgeService()
    result = service._parse_response(
        {
            "response": """
            {
              "faithfulness": 1.0,
              "faithfulness_rationale": "No unsupported claims.",
              "relevance": 1.0,
              "relevance_rationale": "Relevant.",
              "completeness": 1.0,
              "completeness_rationale": "Complete refusal.",
              "citation_accuracy": 1.0,
              "citation_accuracy_rationale": "No citations needed."
            }
            """
        }
    )

    calibrated = service._apply_refusal_calibration(
        result=result,
        query="what is ismaiel soft skills ?",
        answer="I don't have enough information in the selected documents to answer that.",
        context=[],
    )

    assert calibrated.faithfulness == 1.0
    assert calibrated.relevance == 0.4
    assert calibrated.completeness == 0.0
    assert calibrated.citation_accuracy == 0.0


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
