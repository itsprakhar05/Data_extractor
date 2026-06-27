from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision
import mlflow

router = APIRouter(prefix="/evaluate", tags=["evaluation"])

class EvalSample(BaseModel):
    question: str
    answer: str
    contexts: List[str]
    ground_truth: str

class EvalRequest(BaseModel):
    samples: List[EvalSample]

@router.post("/")
async def evaluate_pipeline(request: EvalRequest):
    try:
        data = {
            "question":    [s.question    for s in request.samples],
            "answer":      [s.answer      for s in request.samples],
            "contexts":    [s.contexts    for s in request.samples],
            "ground_truth":[s.ground_truth for s in request.samples],
        }
        dataset = Dataset.from_dict(data)
        result = evaluate(
            dataset,
            metrics=[faithfulness, answer_relevancy, context_precision]
        )
        scores = {
            "faithfulness":      result["faithfulness"],
            "answer_relevancy":  result["answer_relevancy"],
            "context_precision": result["context_precision"],
        }

        # log to MLflow
        with mlflow.start_run(run_name="rag_eval"):
            for metric, value in scores.items():
                mlflow.log_metric(metric, value)

        return {"status": "success", "scores": scores}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))