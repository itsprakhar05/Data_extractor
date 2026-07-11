"""
app/pipeline/__init__.py
------------------------
Exposes the `pipeline` singleton so all routes can do:
    from app.pipeline import pipeline
"""

from app.pipeline.orchestrator import RagPipeline

pipeline = RagPipeline()