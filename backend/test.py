import asyncio
from app.services.ner import ner_client
from app.core.config import settings
print("NER_SERVICE_URL is:", settings.NER_SERVICE_URL)
async def test():
    entities = await ner_client.extract_entities(
        text="المريض يعاني من التهاب رئوي ويأخذ الأموكسيسيلين",
        domain="medical",
    )
    for e in entities:
        print(e)

asyncio.run(test())