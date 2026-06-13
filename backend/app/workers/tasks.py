"""
Celery tasks for async processing.
All heavy operations happen here — never in the request/response cycle.
"""
from app.workers.celery_app import celery_app
import base64


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
    # Evaluation not implemented yet — Sprint 2
    return


@celery_app.task()
def run_nightly_regression():
    # Not implemented yet — Sprint 3
    return