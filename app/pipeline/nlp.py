"""
app/pipeline/nlp.py
────────────────────
All NLP processing in one self-contained module.

Responsibilities
----------------
  SpellCorrector      — fixes typos before embedding
  IntentClassifier    — routes queries to the right prompt template
  EntityExtractor     — spaCy NER: persons, orgs, dates, locations
  KeywordExtractor    — YAKE: top domain keywords per chunk
  Reranker            — CrossEncoder: re-scores retrieved chunks
  ExtractiveQA        — DistilBERT: extracts exact answer span

All models are loaded once at startup and reused across requests.
Hardware profile: designed for 8 GB RAM + 4 GB VRAM (GTX 1650 Ti).
"""

from __future__ import annotations

import logging

import spacy
import yake
from spellchecker import SpellChecker
from sentence_transformers import CrossEncoder
from transformers import pipeline as hf_pipeline

log = logging.getLogger("RAG.NLP")


# ── Spell Corrector ───────────────────────────────────────────────────────────

class SpellCorrector:
    """
    Corrects individual-word typos using pyspellchecker.
    Runs before query embedding so bad spelling does not hurt vector search.
    """

    def __init__(self):
        self._spell = SpellChecker()

    def correct(self, query: str) -> str:
        words     = query.split()
        corrected = [self._spell.correction(w) or w for w in words]
        result    = " ".join(corrected)
        if result != query:
            log.info(f"Spell correction: '{query}' → '{result}'")
        return result


# ── Intent Classifier ─────────────────────────────────────────────────────────

# Each intent maps to a tailored LLM prompt instruction.
INTENT_PROMPTS: dict[str, str] = {
    "definition":  "Define the following term based ONLY on the context below:",
    "comparison":  "Compare and contrast based ONLY on the context below:",
    "date_lookup": "Find the specific date, year, or timeline from the context below:",
    "summary":     "Provide a concise summary based ONLY on the context below:",
    "general":     "Answer the following question using ONLY the context below:",
}

_INTENT_SIGNALS: dict[str, list[str]] = {
    "definition":  ["what is", "define", "meaning of", "what are"],
    "comparison":  ["compare", "difference", "vs", "versus", "better"],
    "date_lookup": ["when", "date", "year", "timeline", "how long"],
    "summary":     ["summarize", "summary", "overview", "brief", "tldr"],
}


class IntentClassifier:
    """
    Lightweight keyword-based intent classifier.
    Returns one of: definition | comparison | date_lookup | summary | general
    """

    def classify(self, query: str) -> str:
        q = query.lower()
        for intent, signals in _INTENT_SIGNALS.items():
            if any(signal in q for signal in signals):
                return intent
        return "general"

    def prompt_for(self, intent: str) -> str:
        return INTENT_PROMPTS.get(intent, INTENT_PROMPTS["general"])


# ── Entity Extractor (spaCy NER) ──────────────────────────────────────────────

class EntityExtractor:
    """
    Extracts named entities from text using spaCy en_core_web_sm.
    Returns a dict of { label: [values] } and a flat list of "LABEL:value" tags
    suitable for storing in a Solr multiValued string field.

    Install: python -m spacy download en_core_web_sm
    """

    _LABELS = {"PERSON", "ORG", "DATE", "GPE"}

    def __init__(self):
        log.info("Loading spaCy NER model...")
        self._nlp = spacy.load("en_core_web_sm")
        log.info("✅ spaCy loaded.")

    def extract(self, text: str) -> dict[str, list[str]]:
        doc = self._nlp(text[:10_000])   # cap: avoid huge-chunk slowdowns
        result: dict[str, list[str]] = {}
        for ent in doc.ents:
            if ent.label_ in self._LABELS:
                key = ent.label_.lower() + "s"   # PERSON → persons
                result.setdefault(key, [])
                if ent.text not in result[key]:
                    result[key].append(ent.text)
        return result

    @staticmethod
    def to_tags(entities: dict[str, list[str]]) -> list[str]:
        """Convert entity dict → ["PERSONS:John Smith", "ORG:Acme", …]"""
        tags = []
        for label, values in entities.items():
            for v in values:
                tags.append(f"{label.upper()}:{v}")
        return tags


# ── Keyword Extractor (YAKE) ──────────────────────────────────────────────────

class KeywordExtractor:
    """
    Extracts top domain keywords from a chunk using YAKE.
    Results feed the autocomplete Trie and are stored in Solr for filtering.

    n=2 → extracts up to 2-word phrases (better than single words for domain text).
    """

    def __init__(self, language: str = "en", n: int = 2, top: int = 10):
        self._extractor = yake.KeywordExtractor(lan=language, n=n, top=top)

    def extract(self, text: str) -> list[str]:
        try:
            return [kw for kw, _ in self._extractor.extract_keywords(text)]
        except Exception as exc:
            log.warning(f"Keyword extraction failed: {exc}")
            return []


# ── Cross-Encoder Reranker ────────────────────────────────────────────────────

class Reranker:
    """
    Re-ranks a list of retrieved chunks using a cross-encoder model.

    Why: bi-encoder cosine similarity (used for initial retrieval) is fast
    but less accurate. Cross-encoder reads query+chunk together and scores
    them jointly — much better precision at the cost of speed.

    Model: ms-marco-MiniLM-L-6-v2  (~80 MB, CPU-friendly)
    """

    def __init__(self, model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        log.info("Loading cross-encoder re-ranker...")
        self._model = CrossEncoder(model)
        log.info("✅ Re-ranker loaded.")

    def rerank(self, query: str, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return chunks

        # ── Fix: ensure content is always a plain string ──────────────────
        def get_content(doc: dict) -> str:
            content = doc.get("content", "")
            # Solr sometimes returns field values as a list
            if isinstance(content, list):
                content = " ".join(content)   # flatten list to string
            return str(content)              # guarantee string type

        pairs  = [(query, get_content(doc)) for doc in chunks]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in ranked]

# ── Extractive QA ─────────────────────────────────────────────────────────────

class ExtractiveQA:
    """
    Extracts the exact phrase that answers a question from a context string.

    Uses DistilBERT fine-tuned on SQuAD — lighter than BERT-large,
    fits comfortably in system RAM alongside Llama3 in VRAM.

    The extracted span is surfaced to the user as a highlighted "quick answer"
    before the full Ollama-generated response finishes streaming.
    """

    def __init__(self, model: str = "distilbert-base-cased-distilled-squad"):
        log.info("Loading extractive QA model (DistilBERT)...")
        try:
            self._qa = hf_pipeline(
                "document-question-answering",   # ← changed from "question-answering"
                model=model
            )
            log.info("✅ Extractive QA loaded.")
        except Exception as exc:
            log.error(f"❌ QA model failed to load: {exc}")
            self._qa = None   # pipeline still works, just no exact answer span

    def extract(self, question: str, context: str, max_answer_len: int = 100) -> str:
    # ── Fix: handle if context comes in as a list ──
        if isinstance(context, list):
            context = " ".join(context)

        if not context.strip():
            return ""
        try:
            result = self._qa(
                question=question,
                context=context[:512],
                max_answer_len=max_answer_len,
            )
            return result.get("answer", "")
        except Exception as exc:
            log.warning(f"Extractive QA failed: {exc}")
            return ""


# ── NLPProcessor: single entry point ─────────────────────────────────────────

class NLPProcessor:
    """
    Composes all NLP components into a single object that RagPipeline uses.

    RagPipeline only imports this class — it does not need to know about
    individual NLP components.
    """

    def __init__(self):
        self.spell_corrector    = SpellCorrector()
        self.intent_classifier  = IntentClassifier()
        self.entity_extractor   = EntityExtractor()
        self.keyword_extractor  = KeywordExtractor()
        self.reranker           = Reranker()
        self.extractive_qa      = ExtractiveQA()

    # ── Convenience pass-throughs ─────────────────────────────────────────────

    def correct_query(self, query: str) -> str:
        return self.spell_corrector.correct(query)

    def classify_intent(self, query: str) -> str:
        return self.intent_classifier.classify(query)

    def intent_prompt(self, intent: str) -> str:
        return self.intent_classifier.prompt_for(intent)

    def extract_entities(self, text: str) -> dict[str, list[str]]:
        return self.entity_extractor.extract(text)

    def entities_to_tags(self, entities: dict) -> list[str]:
        return EntityExtractor.to_tags(entities)

    def extract_keywords(self, text: str) -> list[str]:
        return self.keyword_extractor.extract(text)

    def rerank_chunks(self, query: str, chunks: list[dict]) -> list[dict]:
        return self.reranker.rerank(query, chunks)

    def extract_answer_span(self, question: str, context: str) -> str:
        return self.extractive_qa.extract(question, context)