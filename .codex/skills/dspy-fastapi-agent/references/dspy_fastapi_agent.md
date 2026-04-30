# DSPy FastAPI Notes

```python
import dspy

dspy.configure(lm=dspy.LM(settings.dspy_model), async_max_workers=4)
async_program = dspy.asyncify(program)
```

Core signatures:
- `ClassifyPostContext`
- `GenerateSearchQueries`
- `RerankEvidence`
- `ExplainPost`
- `ValidateExplanation`
- `DetectPromptInjectionRisk`
- `AssessEvidenceTrust`

FastAPI should call a service method and map known upstream errors. The route should not contain prompt construction or broad conditional agent logic.
