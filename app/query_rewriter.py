"""
app/query_rewriter.py
---------------------
Rewrites the user query before retrieval to improve recall.
Uses the same Groq API and model already configured in pipeline.py.
"""

import os
import json
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("RAG_Pipeline")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def rewrite_query(original_query: str, groq_api_key: str, groq_model: str) -> str:
    """
    Rewrite a user query to improve Solr retrieval recall.
    
    Args:
        original_query: Raw question from the user
        groq_api_key:   Taken from pipeline's self.groq_api_key (already loaded from env)
        groq_model:     Taken from pipeline's self.groq_model (from config.json)

    Returns:
        Rewritten query string. Falls back to original if Groq call fails.
    """
    system_prompt = (
        "You are a search query optimizer. "
        "Rewrite the user's question into a concise, keyword-rich search query "
        "that will retrieve the most relevant document chunks. "
        "Expand abbreviations, add synonyms if helpful, remove filler words. "
        "Return ONLY the rewritten query — no explanation, no quotes, no preamble."
    )

    payload = {
        "model": groq_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": original_query}
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 100
    }

    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        rewritten = response.json()["choices"][0]["message"]["content"].strip()
        log.info(f"[QueryRewriter] '{original_query}' → '{rewritten}'")
        return rewritten
    except Exception as e:
        log.warning(f"[QueryRewriter] Failed, using original query. Error: {e}")
        return original_query  # safe fallback — never breaks the pipeline