"""Embeddings for the search index, carried in the OMP record.

The search system embeds each memory's title and text through OpenRouter and
exports the vector in `attributes.embedding`:

  {"model": "baai/bge-base-en-v1.5", "dimensions": 768,
   "text_checksum": "sha256:…", "vector": [...]}

`text_checksum` is the hash of exactly the text that was embedded, so any
system can tell whether a carried vector still describes the record. Systems
that cannot use a vector (the wiki) drop it; the sync carries a still-valid
vector over when such a system revises the record without touching the text.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request

DEFAULT_MODEL = "baai/bge-base-en-v1.5"
KEY = "embedding"


def model_name() -> str:
    return os.environ.get("OMP_EMBEDDING_MODEL", DEFAULT_MODEL)


def embed_text(record: dict) -> str:
    title = record.get("title") or ""
    return f"{title}\n\n{record.get('body') or ''}".strip()


def text_checksum(record: dict) -> str:
    return "sha256:" + hashlib.sha256(embed_text(record).encode("utf-8")).hexdigest()


def carried(record: dict) -> dict | None:
    emb = (record.get("attributes") or {}).get(KEY)
    return emb if isinstance(emb, dict) and isinstance(emb.get("vector"), list) else None


def valid(record: dict, model: str | None = None) -> bool:
    """The record carries a vector of its current text (and of `model`, if given)."""
    emb = carried(record)
    return bool(emb and emb.get("text_checksum") == text_checksum(record) and (model is None or emb.get("model") == model))


def without(record: dict) -> dict:
    """The record with no embedding attribute."""
    attrs = record.get("attributes")
    if not isinstance(attrs, dict) or KEY not in attrs:
        return record
    return {**record, "attributes": {k: v for k, v in attrs.items() if k != KEY}}


def attach(record: dict, model: str, vector: list[float]) -> dict:
    attrs = dict(record.get("attributes") or {})
    attrs[KEY] = {"model": model, "dimensions": len(vector), "text_checksum": text_checksum(record), "vector": vector}
    return {**record, "attributes": attrs}


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** .5
    nb = sum(y * y for y in b) ** .5
    return dot / (na * nb) if na and nb else 0.0


class OpenRouterEmbedder:
    URL = "https://openrouter.ai/api/v1/embeddings"

    def __init__(self, model: str | None = None, key: str | None = None):
        self.model = model or model_name()
        self.key = key or os.environ.get("OPENROUTER_API_KEY", "")

    def embed(self, texts: list[str], timeout: float = 30) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": texts}).encode()
        req = urllib.request.Request(self.URL, data=body, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            data = json.loads(e.read() or b"{}")
        if "data" not in data:
            raise RuntimeError((data.get("error") or {}).get("message") or "embedding request failed")
        return [d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))]
