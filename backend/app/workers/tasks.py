"""
Celery tasks for async processing.
All heavy operations happen here — never in the request/response cycle.
"""
from app.workers.celery_app import celery_app
import base64

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_document(self, document_id: str, domain_id: str, file_content: bytes, filename: str):
    try:
        import base64
        from app.services.ingestion.document_processor import DocumentProcessor
        processor = DocumentProcessor()
        # Decode if it was base64 encoded
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
    """
    Web crawl pipeline:
    1. Crawl URLs respecting whitelist and depth
    2. Extract HTML to clean text
    3. Chunk, embed, store
    4. Detect changes — skip unchanged pages
    """
    try:
        from app.services.ingestion.web_crawler import WebCrawler
        import asyncio
        crawler = WebCrawler()
        asyncio.run(crawler.crawl(domain_id, seed_urls, max_depth))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task()
def run_entity_extraction(document_id: str, domain_id: str):
    """
    Entity & relation extraction for knowledge graph (§2.5).
    Runs after chunking — graph lags vector index by one cycle (acceptable for MVP).
    """
    from app.services.graph.extractor import GraphExtractor
    import asyncio
    extractor = GraphExtractor()
    asyncio.run(extractor.extract_and_store(document_id, domain_id))


@celery_app.task()
def run_judge_evaluation(
    query_id: str,
    query: str,
    context: list,
    answer: str,
    user_id: str,
    domain_ids: list,
    llm_route: str,
    confidence_score: float,
):
    """
    Async judge LLM evaluation (§4.1).
    Fires after answer delivery — never blocks user response.
    Stores scores in audit log and flags if below threshold.
    """
    from app.services.evaluation.judge import JudgeService
    from app.services.evaluation.audit_writer import AuditWriter
    import asyncio

    async def _evaluate():
        judge = JudgeService()
        result = await judge.evaluate(query=query, context=context, answer=answer)

        writer = AuditWriter()
        await writer.write_evaluation(
            query_id=query_id,
            user_id=user_id,
            domain_ids=domain_ids,
            llm_route=llm_route,
            confidence_score=confidence_score,
            evaluation=result,
        )

    asyncio.run(_evaluate())


@celery_app.task()
def run_nightly_regression():
    """
    Nightly regression against golden dataset (§4.5).
    """
    from app.services.evaluation.regression import RegressionRunner
    import asyncio
    runner = RegressionRunner()
    asyncio.run(runner.run_all_domains())