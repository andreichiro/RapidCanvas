# RAG Qdrant Reranking Research

## Source links
- Qdrant Python client local mode: https://github.com/qdrant/qdrant-client
- Qdrant quickstart: https://qdrant.tech/documentation/quick-start/
- Hugging Face cross-encoder model: https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2
- Ragas metrics: https://docs.ragas.io/en/stable/concepts/metrics/

## Exact syntax snippets
```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

client = QdrantClient(path=settings.qdrant_path)
client.recreate_collection(
    collection_name="rapidcanvas_context",
    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
)
```

```python
from sentence_transformers import CrossEncoder

model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2")
scores = model.predict([(query, passage) for passage in passages])
```

## Selected default
- Chunk variants: `500/100`, `700/100`, and `900/150` character overlap windows.
- Retrieve top 30 by vector similarity, rerank to top 6 evidence chunks.
- Use Qdrant local mode for reproducible development and allow an optional HF cross-encoder reranker.

## Rejected alternatives
- Do not treat Qdrant cache or generated vector stores as tracked artifacts.
- Do not hand-roll nearest-neighbor search when Qdrant is available.
- Do not pass unsanitized HTML, scripts, or comments into embeddings.

## Implementation consequence
Dev D metrics include retrieval recall at 6, Ragas-shaped faithfulness/context precision/context recall, citation coverage, and source leakage checks. Dev B can plug real retrieval outputs into the same eval runner.

