"""
app/pipeline/config.py
──────────────────────
Loads config/config.json and exposes a typed dataclass.

Expected config.json shape
--------------------------
{
  "solr_url":          "http://localhost:8983/solr/rag_chunks",
  "solr_signals_url":  "http://localhost:8983/solr/signals",   ← optional
  "ollama_url":        "http://localhost:11434/api/generate",
  "ollama_model":      "llama3",
  "chunk_target_words": 300,                                   ← optional
  "ollama_options": {                                          ← optional
      "num_ctx": 2048, "num_predict": 400,
      "num_gpu": 99,   "num_thread": 4,
      "temperature": 0.1, "low_vram": true
  }
}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("RAG.Config")


@dataclass
class AppConfig:
    solr_url:           str
    ollama_url:         str
    ollama_model:       str
    solr_signals_url:   str              = ""
    chunk_target_words: int              = 300
    ollama_options:     dict             = field(default_factory=lambda: {
        "num_ctx":     2048,
        "num_predict": 400,
        "num_gpu":     99,
        "num_thread":  4,
        "temperature": 0.1,
        "low_vram":    True,
    })

    @classmethod
    def load(cls, path: str = "config/config.json") -> "AppConfig":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found at '{path}'. "
                "Create config/config.json — see docstring for expected shape."
            )

        with open(config_path) as f:
            raw = json.load(f)

        # Required fields
        for key in ("solr_url", "ollama_url", "ollama_model"):
            if key not in raw:
                raise KeyError(f"Missing required config key: '{key}'")

        # Derive signals URL if not explicitly set
        if not raw.get("solr_signals_url"):
            base = raw["solr_url"].rstrip("/").rsplit("/", 1)[0]
            raw["solr_signals_url"] = f"{base}/signals"

        cfg = cls(
            solr_url           = raw["solr_url"],
            ollama_url         = raw["ollama_url"],
            ollama_model       = raw["ollama_model"],
            solr_signals_url   = raw["solr_signals_url"],
            chunk_target_words = raw.get("chunk_target_words", 300),
            ollama_options     = raw.get("ollama_options", cls.__dataclass_fields__[  # type: ignore
                "ollama_options"].default_factory()),
        )
        log.info(f"✅ Config loaded from '{path}'")
        return cfg