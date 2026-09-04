"""Deterministic hash embeddings — stdlib only, no torch.

Per ECC iterative-retrieval: retrieval must be refinable across passes.
This module gives us a vector interface behind which chromadb/sentence-transformers
can be swapped later (see pyproject `rag` extra). For CI/zero-cost prod we use
hash-based embeddings: deterministic, no download, good enough for 4-doc demo
when combined with TF overlap + staleness ranking.

Production path: set EMBEDDINGS_BACKEND=chromadb to use real model (see RagStore).
"""
from __future__ import annotations

import hashlib
import math
import re

DIM = 64


def embed(text: str, dim: int = DIM) -> list[float]:
    tokens = re.findall(r"\w+", text.lower())
    vec = [0.0] * dim
    for tok in tokens:
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
