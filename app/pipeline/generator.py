"""
app/pipeline/generator.py
-------------------------
Groq LLM streaming response generator.
Builds the RAG prompt from retrieved chunks and streams the answer.
"""

import json
import logging
import requests

log = logging.getLogger("RAG_Pipeline")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def build_context(docs: list[dict]) -> tuple[str, list[str]]:
    """
    Build the context string and raw context list from Solr docs.

    Returns:
        context_str:  Formatted string for the LLM prompt
        context_list: Plain list of chunk texts (for RAGAS evaluation)
    """
    context_blocks = []
    context_list = []

    for doc in docs:
        source = f"[Source: {doc.get('source_file', 'Unknown')} | Chunk: {doc.get('chunk_index', 0)}]"
        text = doc.get("content", "")
        context_blocks.append(f"{source}\n{text}")
        context_list.append(text)

    context_str = "\n---\n".join(context_blocks) if context_blocks else "No specific relevant documentation found."
    return context_str, context_list


def build_prompt(context: str, question: str) -> str:
    return f"""You are a precise assistant. Answer ONLY using the context below.
The context may contain markdown tables with | symbols — read them carefully.
If the answer is in a table, extract and present the relevant rows clearly.
If the answer is not in the context, say "I don't have enough information."
Do not make up answers.

CONTEXT:
{context}

QUESTION:
{question}

ANSWER (if data is in a table, present it clearly):"""


def stream_answer(
    prompt: str,
    groq_api_key: str,
    groq_model: str,
    max_tokens: int = 200,
    temperature: float = 0.1,
):
    """
    Generator that streams Groq response tokens.
    Also accumulates and yields the full response at the end as a special sentinel.

    Yields:
        str tokens during streaming
        After [DONE]: yields a special dict {"__full__": full_response_str}
    """
    payload = {
        "model": groq_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }

    full_parts = []

    try:
        response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=300, stream=True)
        response.raise_for_status()

        for line in response.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if not decoded.startswith("data: "):
                continue
            data_str = decoded[len("data: "):]
            if data_str.strip() == "[DONE]":
                break
            chunk = json.loads(data_str)
            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
            if content:
                full_parts.append(content)
                yield content

    except Exception as e:
        log.error("[Generator] Streaming failed: %s", e)
        yield f"Error generating response: {str(e)}"
        return

    # Sentinel — carries the full assembled response back to the orchestrator
    yield {"__full__": "".join(full_parts)}