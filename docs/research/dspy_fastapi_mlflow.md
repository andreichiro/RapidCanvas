# DSPy FastAPI MLflow Research

## Source links
- DSPy docs and API index: https://dspy.ai/
- DSPy deployment tutorial: https://dspy.ai/tutorials/deployment/
- DSPy `asyncify`: https://dspy.ai/api/utils/asyncify/
- DSPy GEPA overview: https://dspy.ai/api/optimizers/GEPA/overview/
- MLflow DSPy flavor: https://mlflow.org/docs/latest/genai/flavors/dspy/
- MLflow DSPy API: https://mlflow.org/docs/latest/python_api/mlflow.dspy.html

## Exact syntax snippets
```python
import dspy

class ExplainPost(dspy.Signature):
    post_text: str = dspy.InputField()
    evidence: str = dspy.InputField()
    bullets: list[dict[str, object]] = dspy.OutputField()

dspy.configure(lm=dspy.LM(settings.dspy_model), async_max_workers=4)
async_program = dspy.asyncify(program)
```

```python
import mlflow

mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
mlflow.set_experiment("bluesky-post-explainer")
mlflow.dspy.log_model(program, name="bluesky-explainer", task="llm/v1/chat")
```

## Selected default
- DSPy owns classification, query planning, evidence reranking, explanation, validation, prompt-injection judgment, and trust assessment.
- FastAPI receives a service boundary and calls the asyncified DSPy program when Dev C replaces the Gate 3 adapter.
- MLflow logs eval parameters, metrics, reports, provider comparison, optimized program, and model package.

## Rejected alternatives
- Do not use LangChain or LlamaIndex for orchestration.
- Do not put raw retrieved text in executable instructions.
- Do not require live MLflow for local tests; file tracking is enough.

## Implementation consequence
Dev D eval reports already expose DSPy-judge-shaped scores and JSONL artifacts. Dev C can replace deterministic judge proxies with DSPy modules and log the same artifacts without changing the report contract.

