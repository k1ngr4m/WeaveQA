from __future__ import annotations

from collections import Counter
import math

from .text import tokenize


VECTOR_SIZE = 64


def lexical_embedding(text: str) -> list[float]:
    tokens = tokenize(text)
    vector = [0.0] * VECTOR_SIZE
    for token, count in tokens.items():
        bucket = abs(hash(token)) % VECTOR_SIZE
        vector[bucket] += float(count)
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def cosine_from_tokens(left: Counter[str], right: Counter[str]) -> float:
    shared = set(left) & set(right)
    dot = sum(left[token] * right[token] for token in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
