"""
app/pipeline/rewriter.py
------------------------
Rewrites user queries before retrieval to improve Solr recall.
Uses a lightweight Groq call with low temperature.
Always falls back to the original query on failure — never blocks the pipeline.
"""

import logging
import requests

log = logging.getLogger("RAG_Pipeline")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a search query optimizer. "
    "Rewrite the user's question into a concise, keyword-rich search query "
    "that will retrieve the most relevant document chunks. "
    "Expand abbreviations, add synonyms if helpful, remove filler words. "
    "Return ONLY the rewritten query — no explanation, no quotes, no preamble."
)


def rewrite_query(question: str, groq_api_key: str, groq_model: str) -> str:
    """
    Rewrite a user question for better retrieval recall.

    Returns:
        Rewritten query string, or original question if Groq call fails.
    """
    try:
        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": groq_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": question},
                ],
                "stream": False,
                "temperature": 0.2,
                "max_tokens": 100,
            },
            timeout=10,
        )
        response.raise_for_status()
        rewritten = response.json()["choices"][0]["message"]["content"].strip()
        log.info("[Rewriter] '%s' → '%s'", question, rewritten)
        return rewritten
    except Exception as e:
        log.warning("[Rewriter] Failed, using original query. Error: %s", e)
        return question  # safe fallback