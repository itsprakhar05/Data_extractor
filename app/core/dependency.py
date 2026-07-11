"""
app/core/dependencies.py
------------------------
Singleton RagPipeline instance, initialized once at app startup.
Injected into routes via FastAPI dependency.
"""

from app.pipeline.orchestrator import RagPipeline

_pipeline: RagPipeline | None = None


def init_pipeline(config_path: str = "config/config.json"):
    global _pipeline
    _pipeline = RagPipeline(config_path)


def get_pipeline() -> RagPipeline:
    if _pipeline is None:
        raise RuntimeError("Pipeline not initialized. Call init_pipeline() at startup.")
    return _pipeline