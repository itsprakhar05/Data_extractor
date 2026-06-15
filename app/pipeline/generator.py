"""
app/pipeline/generator.py
──────────────────────────
Builds the final LLM prompt and streams the Ollama response.

Responsibilities
----------------
  PromptBuilder   — assembles context + intent instruction + exact-answer hint
                    into the final prompt string sent to Ollama.
  OllamaGenerator — posts the prompt to the Ollama API and yields response
                    tokens as they arrive (true streaming).

Streaming protocol
------------------
The generator yields two types of values in order:

  1. A JSON string (type="meta") containing:
       corrected_query, intent, exact_answer, sources[]
     Clients should parse this first line as JSON.

  2. Plain text tokens — the actual LLM response, streamed word by word.
     Clients concat these to build the final answer.
"""

from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger("RAG.Generator")

# ── Default Ollama generation options ─────────────────────────────────────────
# Tuned for 8 GB RAM + GTX 1650 Ti (4 GB VRAM).
# num_ctx 2048 gives enough context for 5 chunks without truncation.
_DEFAULT_OPTIONS = {
    "num_ctx":     2048,
    "num_predict": 400,
    "num_gpu":     99,
    "num_thread":  4,
    "temperature": 0.1,
    "low_vram":    True,
}

# ── Prompt templates per intent ───────────────────────────────────────────────
_TABLE_INSTRUCTION = (
    "The context may contain markdown tables (| symbols) — read them carefully. "
    "If the answer is in a table, extract and present the relevant rows clearly."
)
_NO_INFO_INSTRUCTION = (
    'If the answer is not in the context, say "I don\'t have enough information." '
    "Do not make up answers."
)

_PROMPT_TEMPLATE = """{instruction}
{table_instruction}
{no_info_instruction}{exact_hint}

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:"""


# ── PromptBuilder ─────────────────────────────────────────────────────────────

class PromptBuilder:
    """Assembles the full prompt from retrieved chunks and NLP metadata."""

    def build(
        self,
        question:     str,
        intent:       str,
        instruction:  str,
        chunks:       list[dict],
        exact_answer: str = "",
    ) -> str:
        context       = self._build_context(chunks)
        exact_hint    = (
            f'\n\nNote: The most likely direct answer is: "{exact_answer}"'
            if exact_answer else ""
        )
        return _PROMPT_TEMPLATE.format(
            instruction        = instruction,
            table_instruction  = _TABLE_INSTRUCTION,
            no_info_instruction= _NO_INFO_INSTRUCTION,
            exact_hint         = exact_hint,
            context            = context,
            question           = question,
        )

    @staticmethod
    def _build_context(chunks: list[dict]) -> str:
        if not chunks:
            return "No relevant documentation found."
        blocks = []
        for doc in chunks:
            # ── Fix: handle Solr list values ──
            content = doc.get("content", "")
            if isinstance(content, list):
                content = " ".join(content)

            source = (
                f"[Source: {doc.get('source_file', '?')} "
                f"| Chunk: {doc.get('chunk_index', 0)}]"
            )
            blocks.append(f"{source}\n{content}")
        return "\n---\n".join(blocks)
    @staticmethod
    def build_meta(
        corrected_query: str,
        intent:          str,
        exact_answer:    str,
        chunks:          list[dict],
    ) -> str:
        """Build the JSON metadata line yielded before the streamed answer."""
        return json.dumps({
            "type":            "meta",
            "corrected_query": corrected_query,
            "intent":          intent,
            "exact_answer":    exact_answer,
            "sources": [
                {
                    "file":  d.get("source_file", "?"),
                    "chunk": d.get("chunk_index", 0),
                    "id":    d.get("id", ""),
                }
                for d in chunks
            ],
        })


# ── OllamaGenerator ──────────────────────────────────────────────────────────

class OllamaGenerator:
    """
    Posts a prompt to the Ollama /api/generate endpoint and yields
    response tokens as they stream back.
    """

    def __init__(
        self,
        ollama_url:  str,
        model_name:  str,
        options:     dict | None = None,
    ):
        self._url     = ollama_url
        self._model   = model_name
        self._options = options or _DEFAULT_OPTIONS

    def stream(self, prompt: str):
        # ── Fix: sanitise prompt before sending to Ollama ──
        prompt = prompt.encode("utf-8", errors="ignore").decode("utf-8")

        payload = {
            "model":   self._model,
            "prompt":  prompt,
            "stream":  True,
            "options": self._options,
        }
        try:
            response = requests.post(
                self._url,
                json=payload,
                timeout=300,
                stream=True
            )

            # ── Fix: log the actual Ollama error instead of just 500 ──
            if not response.ok:
                error_detail = response.text[:500]
                log.error(f"Ollama error {response.status_code}: {error_detail}")
                yield f"[Ollama error: {error_detail}]"
                return

            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line.decode("utf-8"))
                yield chunk.get("response", "")
                if chunk.get("done", False):
                    break

        except Exception as exc:
            log.error(f"Ollama streaming failed: {exc}")
            yield f"[Error generating response: {exc}]"