# """
# app/api/routes/evaluate.py
# --------------------------
# Evaluation endpoints backed by SQLite query logs.

# Endpoints:
#     GET  /api/v1/queries              → list recent logged queries
#     GET  /api/v1/queries/{query_id}   → get a single logged query
#     POST /api/v1/evaluate/{query_id}  → run RAGAS on one query
#     POST /api/v1/evaluate/all         → run RAGAS on last N queries
# """

# import logging
# import mlflow
# from fastapi import APIRouter, HTTPException, Query
# from datasets import Dataset, Features, Sequence, Value
# from ragas import evaluate
# from ragas.metrics import faithfulness, answer_relevancy, context_precision

# from app.db.database import get_query, get_recent_queries

# log = logging.getLogger("RAG_Pipeline")
# router = APIRouter(prefix="/api/v1", tags=["Evaluation"])


# # ------------------------------------------------------------------
# # Query log endpoints
# # ------------------------------------------------------------------

# @router.get("/queries")
# def list_queries(limit: int = Query(default=20, ge=1, le=100)):
#     """List the most recent RAG query logs."""
#     rows = get_recent_queries(limit=limit)
#     return {"count": len(rows), "queries": rows}


# @router.get("/queries/{query_id}")
# def get_single_query(query_id: str):
#     """Fetch a single query log by query_id."""
#     row = get_query(query_id)
#     if not row:
#         raise HTTPException(status_code=404, detail=f"query_id '{query_id}' not found.")
#     return row


# # ------------------------------------------------------------------
# # Evaluation endpoints
# # ------------------------------------------------------------------

# def _run_ragas(samples: list[dict], run_name: str) -> dict:
#     """
#     Core RAGAS evaluation logic.

#     Args:
#         samples: List of dicts with keys: question, answer, contexts, ground_truth
#         run_name: MLflow run label

#     Returns:
#         dict of metric scores
#     """
#     # RAGAS needs a ground_truth — for auto-eval we use the answer itself
#     # as a proxy when no human ground truth exists.
#     # This measures internal consistency (faithfulness + relevancy) not factual accuracy.
#     data = {
#         "question":     [s["question"]     for s in samples],
#         "answer":       [s["answer"]       for s in samples],
#         "contexts":     [s["contexts"]     for s in samples],
#         "ground_truth": [s.get("ground_truth") or s["answer"] for s in samples],
#     }
    
#     features = Features({
#     "question":     Value("string"),
#     "answer":       Value("string"),
#     "contexts":     Sequence(Value("string")),
#     "ground_truth": Value("string"),
# })

#     dataset = Dataset.from_dict(data,features=features)
#     result  = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_precision])

#     scores = {
#         "faithfulness":      round(result["faithfulness"],      4),
#         "answer_relevancy":  round(result["answer_relevancy"],  4),
#         "context_precision": round(result["context_precision"], 4),
#     }

#     # Log to MLflow
#     try:
#         with mlflow.start_run(run_name=run_name):
#             mlflow.log_metrics(scores)
#             mlflow.log_param("sample_count", len(samples))
#         log.info("[Eval] MLflow logged: %s", scores)
#     except Exception as e:
#         log.warning("[Eval] MLflow logging failed (non-fatal): %s", e)

#     return scores


# @router.post("/evaluate/{query_id}")
# def evaluate_single(query_id: str):
#     """
#     Run RAGAS evaluation on a single logged query.

#     - Fetches question + answer + contexts from the DB by query_id
#     - No manual payload needed
#     """
#     row = get_query(query_id)
#     if not row:
#         raise HTTPException(status_code=404, detail=f"query_id '{query_id}' not found.")

#     if not row["answer"]:
#         raise HTTPException(status_code=400, detail="This query has no stored answer to evaluate.")

#     if not row["contexts"]:
#         raise HTTPException(
#             status_code=400,
#             detail="This query was a cache hit — no contexts stored. Evaluate a non-cached query."
#         )

#     scores = _run_ragas(
#         samples=[row],
#         run_name=f"eval_single_{query_id[:8]}"
#     )

#     return {
#         "query_id": query_id,
#         "question": row["question"],
#         "scores":   scores,
#     }


# @router.post("/evaluate/all")
# def evaluate_all(limit: int = Query(default=10, ge=1, le=50)):
#     """
#     Run RAGAS evaluation on the last N logged queries.
#     Skips cache hits (no contexts stored) and empty answers.
#     """
#     rows = get_recent_queries(limit=limit)

#     # Filter out cache hits and empty answers
#     valid = [r for r in rows if r["answer"] and r["contexts"]]

#     if not valid:
#         raise HTTPException(
#             status_code=400,
#             detail="No valid (non-cached) queries found to evaluate."
#         )

#     scores = _run_ragas(
#         samples=valid,
#         run_name=f"eval_batch_{len(valid)}_queries"
#     )

#     return {
#         "evaluated_count": len(valid),
#         "skipped_count":   len(rows) - len(valid),
#         "scores":          scores,
#     }



"""
app/api/routes/evaluate.py
--------------------------
Evaluation endpoints backed by SQLite query logs.

Endpoints:
    GET  /api/v1/queries              → list recent logged queries
    GET  /api/v1/queries/{query_id}   → get a single logged query
    POST /api/v1/evaluate/{query_id}  → run RAGAS on one query
    POST /api/v1/evaluate/all         → run RAGAS on last N queries
"""

import os
import logging
import mlflow
from fastapi import APIRouter, HTTPException, Query
from datasets import Dataset, Features, Sequence, Value
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision
from langchain_groq import ChatGroq
from langchain_community.embeddings import HuggingFaceEmbeddings

from app.db.database import get_query, get_recent_queries

log = logging.getLogger("RAG_Pipeline")
router = APIRouter(prefix="/api/v1", tags=["Evaluation"])

# Created once at module load (app startup) instead of per-request —
# avoids reloading the embeddings model on every /evaluate call.
_groq_llm = ChatGroq(
    groq_api_key=os.getenv("GROQ_API_KEY"),
    model_name="llama-3.3-70b-versatile",
)
_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")


# ------------------------------------------------------------------
# Query log endpoints
# ------------------------------------------------------------------

@router.get("/queries")
def list_queries(limit: int = Query(default=20, ge=1, le=100)):
    """List the most recent RAG query logs."""
    rows = get_recent_queries(limit=limit)
    return {"count": len(rows), "queries": rows}


@router.get("/queries/{query_id}")
def get_single_query(query_id: str):
    """Fetch a single query log by query_id."""
    row = get_query(query_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"query_id '{query_id}' not found.")
    return row


# ------------------------------------------------------------------
# Evaluation endpoints
# ------------------------------------------------------------------

def _run_ragas(samples: list[dict], run_name: str) -> dict:
    """
    Core RAGAS evaluation logic.

    Args:
        samples: List of dicts with keys: question, answer, contexts, ground_truth
        run_name: MLflow run label

    Returns:
        dict of metric scores
    """
    # RAGAS needs a ground_truth — for auto-eval we use the answer itself
    # as a proxy when no human ground truth exists.
    # This measures internal consistency (faithfulness + relevancy) not factual accuracy.
    data = {
        "question":     [s["question"]     for s in samples],
        "answer":       [s["answer"]       for s in samples],
        "contexts":     [s["contexts"]     for s in samples],
        "ground_truth": [s.get("ground_truth") or s["answer"] for s in samples],
    }

    features = Features({
        "question":     Value("string"),
        "answer":       Value("string"),
        "contexts":     Sequence(Value("string")),
        "ground_truth": Value("string"),
    })

    dataset = Dataset.from_dict(data, features=features)
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision],
        llm=_groq_llm,
        embeddings=_embeddings,
    )

    scores = {
        "faithfulness":      round(result["faithfulness"],      4),
        "answer_relevancy":  round(result["answer_relevancy"],  4),
        "context_precision": round(result["context_precision"], 4),
    }

    # Log to MLflow
    try:
        with mlflow.start_run(run_name=run_name):
            mlflow.log_metrics(scores)
            mlflow.log_param("sample_count", len(samples))
        log.info("[Eval] MLflow logged: %s", scores)
    except Exception as e:
        log.warning("[Eval] MLflow logging failed (non-fatal): %s", e)

    return scores


@router.post("/evaluate/{query_id}")
def evaluate_single(query_id: str):
    """
    Run RAGAS evaluation on a single logged query.

    - Fetches question + answer + contexts from the DB by query_id
    - No manual payload needed
    """
    row = get_query(query_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"query_id '{query_id}' not found.")

    if not row["answer"]:
        raise HTTPException(status_code=400, detail="This query has no stored answer to evaluate.")

    if not row["contexts"]:
        raise HTTPException(
            status_code=400,
            detail="This query was a cache hit — no contexts stored. Evaluate a non-cached query."
        )

    scores = _run_ragas(
        samples=[row],
        run_name=f"eval_single_{query_id[:8]}"
    )

    return {
        "query_id": query_id,
        "question": row["question"],
        "scores":   scores,
    }


@router.post("/evaluate/all")
def evaluate_all(limit: int = Query(default=10, ge=1, le=50)):
    """
    Run RAGAS evaluation on the last N logged queries.
    Skips cache hits (no contexts stored) and empty answers.
    """
    rows = get_recent_queries(limit=limit)

    # Filter out cache hits and empty answers
    valid = [r for r in rows if r["answer"] and r["contexts"]]

    if not valid:
        raise HTTPException(
            status_code=400,
            detail="No valid (non-cached) queries found to evaluate."
        )

    scores = _run_ragas(
        samples=valid,
        run_name=f"eval_batch_{len(valid)}_queries"
    )

    return {
        "evaluated_count": len(valid),
        "skipped_count":   len(rows) - len(valid),
        "scores":          scores,
    }