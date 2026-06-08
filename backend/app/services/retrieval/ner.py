"""
Named Entity Recognition service.
Used at BOTH ingestion time and query time (§3.3).
Shared model instance for consistency.
"""
from typing import List, Tuple
import spacy

# Multilingual model — supports all 5 required languages
NER_MODEL = "xx_ent_wiki_sm"  # multilingual spaCy model
# For production: replace with domain-specific fine-tuned model


class NERService:
    def __init__(self):
        try:
            self.nlp = spacy.load(NER_MODEL)
        except OSError:
            # Fallback for development without model downloaded
            self.nlp = None

    async def extract_entities(self, text: str) -> List[Tuple[str, str]]:
        """
        Extract (entity_text, entity_type) pairs from text.
        Returns list like: [("Vodafone", "ORG"), ("2024", "DATE")]
        Used by retrieval router to activate graph signal.
        """
        if not self.nlp:
            return []

        doc = self.nlp(text)
        entities = [(ent.text, ent.label_) for ent in doc.ents]
        return entities

    async def extract_triples(self, text: str, ontology_schema: dict) -> List[dict]:
        """
        Extract subject → predicate → object triples from text.
        Constrained to declared ontology schema (§2.5).
        Used during ingestion to populate the graph DB.
        """
        entities = await self.extract_entities(text)
        # TODO: Implement relation extraction
        # For MVP: use local LLM prompt to extract relations between detected entities
        # constrained to ontology_schema node_types and relation_types
        return []
