import asyncio

from app.schemas.query import ContextChunk
from app.services.llm.router import LLMRouter


class StubLLM:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def generate(self, *args, **kwargs) -> str:
        return self.answer


def test_defaults_to_local_when_no_domains_are_selected() -> None:
    router = LLMRouter()

    assert router.determine_route([], {}) == "local"


def test_defaults_to_local_when_route_is_missing() -> None:
    router = LLMRouter()

    assert router.determine_route(["hr"], {}) == "local"


def test_defaults_to_local_when_route_is_invalid() -> None:
    router = LLMRouter()

    assert router.determine_route(["hr"], {"hr": "unknown"}) == "local"


def test_local_wins_for_mixed_domain_query() -> None:
    router = LLMRouter()

    route = router.determine_route(
        ["hr", "public"],
        {"hr": "local", "public": "api"},
    )

    assert route == "local"


def test_api_route_when_all_domains_allow_api() -> None:
    router = LLMRouter()

    route = router.determine_route(
        ["public", "faq"],
        {"public": "api", "faq": "api"},
    )

    assert route == "api"


def test_generate_uses_selected_api_route() -> None:
    router = LLMRouter(
        local_llm=StubLLM("local answer"),
        external_llm=StubLLM("api answer"),
    )

    result = asyncio.run(
        router.generate(
            query="What is the leave policy?",
            context=[ContextChunk(content="Policy text", document_title="HR Policy")],
            domain_ids=["public"],
            domain_routes={"public": "api"},
        )
    )

    assert result.llm_route == "api"
    assert result.answer == "api answer"


def test_generate_extracts_soft_skills_section_before_llm_call() -> None:
    router = LLMRouter(
        local_llm=StubLLM("fallback"),
        external_llm=StubLLM("fallback"),
    )

    result = asyncio.run(
        router.generate(
            query="what is ismaiel soft skills ?",
            context=[
                ContextChunk(content="Education and certificates", document_title="CV"),
                ContextChunk(
                    content=(
                        "SOFT SKILLS & COLLABORATION: Problem Solving | "
                        "Critical Thinking | Communication | Cross-Functional "
                        "Collaboration | Adaptability | Presentation | "
                        "Arabic ( Native ) | English ( Fluent )"
                    ),
                    document_title="CV",
                ),
            ],
            domain_ids=["cv"],
            domain_routes={"cv": "local"},
        )
    )

    assert result.llm_route == "local"
    assert "Problem Solving" in result.answer
    assert "Critical Thinking" in result.answer
    assert "Cross-Functional Collaboration" in result.answer
    assert "Arabic" not in result.answer
    assert "[Source 2]" in result.answer
