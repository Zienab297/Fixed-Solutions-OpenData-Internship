"""
Celery tasks for async processing.
All heavy operations happen here — never in the request/response cycle.
"""
from app.workers.celery_app import celery_app
import base64
from uuid import UUID


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_document(self, document_id: str, domain_id: str, file_content: bytes, filename: str):
    try:
        from app.services.ingestion.document_processor import DocumentProcessor
        processor = DocumentProcessor()
        if isinstance(file_content, str):
            file_content = base64.b64decode(file_content)
        processor.process(document_id, domain_id, file_content, filename)
        run_entity_extraction.delay(document_id=document_id, domain_id=domain_id)

    except Exception as exc:
        import traceback
        print("TASK FAILED:", str(exc))
        print(traceback.format_exc())
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2)
def process_web_crawl(self, domain_id: str, seed_urls: list, max_depth: int = 2):
    try:
        from app.services.ingestion.web_crawler import WebCrawler
        import asyncio
        crawler = WebCrawler()
        asyncio.run(crawler.crawl(domain_id, seed_urls, max_depth))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task()
def run_entity_extraction(document_id: str, domain_id: str):
    from app.services.graph.extractor import GraphExtractor
    import asyncio
    extractor = GraphExtractor()
    asyncio.run(extractor.extract_and_store(document_id, domain_id))


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_judge_evaluation(
    self,
    query_id: str,
    audit_log_id: str,
    query: str,
    context: list,
    graph_context: list,
    answer: str,
    user_id: str,
    domain_ids: list,
    llm_route: str,
    confidence_score: float,
):
    if not _judge_enabled():
        return {"status": "disabled", "query_id": query_id}

    try:
        import asyncio
        from app.core.config import settings
        from app.core.database import SessionLocal
        from app.models.db.models import EvaluationResult, ModerationQueue
        from app.services.evaluation.judge import JudgeService

        judge_result = asyncio.run(
            JudgeService().evaluate(
                query=query,
                context=context,
                graph_context=graph_context,
                answer=answer,
            )
        )
        flagged = is_flagged(judge_result, settings.JUDGE_SCORE_THRESHOLD)

        with SessionLocal() as db:
            evaluation = EvaluationResult(
                audit_log_id=UUID(audit_log_id),
                query_id=UUID(query_id),
                judge_model=settings.JUDGE_MODEL,
                faithfulness_score=judge_result.faithfulness,
                relevance_score=judge_result.relevance,
                completeness_score=judge_result.completeness,
                citation_accuracy_score=judge_result.citation_accuracy,
                judge_rationale=judge_result.rationale,
                raw_response=judge_result.raw_response,
                flagged=flagged,
            )
            db.add(evaluation)
            db.flush()

            if flagged:
                moderation_domains = _domain_uuid_list(domain_ids)
                if not moderation_domains:
                    moderation_domains = [None]
                for domain_id in moderation_domains:
                    db.add(
                        ModerationQueue(
                            audit_log_id=UUID(audit_log_id),
                            evaluation_result_id=evaluation.id,
                            domain_id=domain_id,
                            status="pending",
                        )
                    )

            db.commit()

        return {"status": "completed", "query_id": query_id, "flagged": flagged}
    except Exception as exc:
        import traceback

        print("JUDGE TASK FAILED:", str(exc))
        print(traceback.format_exc())
        raise self.retry(exc=exc)


@celery_app.task()
def run_nightly_regression():
    # Not implemented yet — Sprint 3
    return


def is_flagged(judge_result, threshold: float) -> bool:
    return any(
        score < threshold
        for score in (
            judge_result.faithfulness,
            judge_result.relevance,
            judge_result.completeness,
            judge_result.citation_accuracy,
        )
    )


def _domain_uuid_list(domain_ids: list) -> list[UUID]:
    result = []
    for domain_id in domain_ids:
        try:
            result.append(UUID(str(domain_id)))
        except (TypeError, ValueError):
            continue
    return result


def _judge_enabled() -> bool:
    from app.core.config import settings

    return settings.JUDGE_ENABLED
