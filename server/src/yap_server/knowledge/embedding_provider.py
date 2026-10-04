"""Deployment-selected, bounded loopback generation of reviewed chunk vectors."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Mapping

from .generation_ledger import serialize_embedding_vector
from yap_server.jobs.contract_values import valid_sha256
from .okf_profile import identity
from .okf_projection import CompiledChunk
from .vllm_reasoning_client import BoundedVllmJsonClient


@dataclass(frozen=True, slots=True)
class ReviewedEmbeddingProvider:
    model_id: str
    model_revision: str
    transport: BoundedVllmJsonClient

    def generate(
        self, chunks: tuple[CompiledChunk, ...]
    ) -> dict[str, tuple[float, ...]]:
        if not chunks:
            return {}
        if (
            len(chunks) > 64
            or sum(len(c.text.encode("utf-8")) for c in chunks) > 262_144
        ):
            raise ValueError("reviewed embedding input exceeds its bound")
        response = self.transport.embed(
            {
                "model": self.model_id,
                "input": [c.text for c in chunks],
                "encoding_format": "float",
            },
            threading.Event(),
        )
        data = response.get("data")
        if (
            response.get("model") != self.model_id
            or response.get("object") != "list"
            or not isinstance(data, list)
            or len(data) != len(chunks)
        ):
            raise ValueError("reviewed embedding response differs from the contract")
        vectors: dict[int, tuple[float, ...]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(
                    "reviewed embedding response differs from the contract"
                )
            index = item.get("index")
            vector = item.get("embedding")
            if (
                type(index) is not int
                or not 0 <= index < len(chunks)
                or index in vectors
                or item.get("object") != "embedding"
                or not isinstance(vector, list)
            ):
                raise ValueError(
                    "reviewed embedding response differs from the contract"
                )
            serialized = tuple(vector)
            serialize_embedding_vector(serialized)
            vectors[index] = serialized
        return {chunk.chunk_id: vectors[index] for index, chunk in enumerate(chunks)}


def configured_embedding_provider(
    environ: Mapping[str, str],
) -> ReviewedEmbeddingProvider | None:
    names = (
        "YAP_KNOWLEDGE_EMBEDDING_ENDPOINT",
        "YAP_KNOWLEDGE_EMBEDDING_MODEL_ID",
        "YAP_KNOWLEDGE_EMBEDDING_MODEL_REVISION",
    )
    values = tuple(environ.get(name) for name in names)
    if all(value is None for value in values):
        return None
    endpoint, model, revision = values
    try:
        model = identity(model, "embedding model")
        if not valid_sha256(revision):
            raise ValueError("embedding revision is invalid")
        transport = BoundedVllmJsonClient(
            endpoint=endpoint, timeout_seconds=10, maximum_response_bytes=2_000_000
        )
        return ReviewedEmbeddingProvider(model, revision, transport)
    except (TypeError, ValueError):
        raise ValueError(
            "reviewed embedding deployment configuration is unavailable"
        ) from None
