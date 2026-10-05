from __future__ import annotations

from contextlib import ExitStack
import dataclasses
import threading
import time
import unittest
from unittest.mock import patch

from yap_server.knowledge.embedding_provider import configured_embedding_provider
from yap_server.knowledge.knowledge_publication_service import (
    build_knowledge_publication_service,
)
from yap_server.knowledge.okf_projection import CompiledChunk
from yap_server.knowledge.agent_reasoning_routes import ReasoningRetryableError
from yap_server.knowledge.vllm_reasoning_client import (
    BoundedVllmJsonClient,
    VllmRequestRejected,
)
from .embedding_provider_fixtures import embedding_server


def chunk(index, text="Private source café 🌱"):
    return CompiledChunk(str(index), "concept", "p" * 64, 0, len(text), text, ())


class ReviewedEmbeddingProviderTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        endpoint, self.requests, self.settings = stack.enter_context(embedding_server())
        self.environ = {
            "YAP_KNOWLEDGE_EMBEDDING_ENDPOINT": endpoint,
            "YAP_KNOWLEDGE_EMBEDDING_MODEL_ID": "organization/model",
            "YAP_KNOWLEDGE_EMBEDDING_MODEL_REVISION": "a" * 64,
        }
        self.provider = configured_embedding_provider(self.environ)

    def test_exact_unicode_input_indexed_response_and_server_selected_model(self):
        chunks = (chunk(0), chunk(1, "Second source"))
        self.settings["transform"] = lambda value: {
            **value,
            "data": list(reversed(value["data"])),
        }
        vectors = self.provider.generate(chunks)
        self.assertEqual(vectors, {"0": (0.25,) * 768, "1": (0.26,) * 768})
        self.assertEqual(
            self.requests,
            [
                (
                    "/v1/embeddings",
                    {
                        "model": "organization/model",
                        "input": [c.text for c in chunks],
                        "encoding_format": "float",
                    },
                )
            ],
        )

    def test_larger_generation_preserves_exact_text_and_batch_local_indexes(self):
        chunks = tuple(
            chunk(index, f"Synthetic source {index} café 🌱") for index in range(129)
        )
        self.settings["transform"] = lambda value: {
            **value,
            "data": list(reversed(value["data"])),
        }
        vectors = self.provider.generate(chunks)
        self.assertEqual(len(vectors), 129)
        self.assertEqual(
            [len(body["input"]) for _path, body in self.requests], [64, 64, 1]
        )
        self.assertEqual(
            [text for _path, body in self.requests for text in body["input"]],
            [c.text for c in chunks],
        )
        for index, c in enumerate(chunks):
            self.assertEqual(vectors[c.chunk_id], (0.25 + (index % 64) / 100,) * 768)

    def test_larger_generation_packs_by_utf8_bytes_without_splitting_source(self):
        chunks = (chunk(0, "é" * 70_000), chunk(1, "é" * 70_000))
        vectors = self.provider.generate(chunks)
        self.assertEqual(set(vectors), {"0", "1"})
        self.assertEqual(
            [body["input"] for _path, body in self.requests],
            [[chunks[0].text], [chunks[1].text]],
        )

    def test_larger_generation_shares_one_transport_budget_across_batches(self):
        def slow_response(value):
            time.sleep(0.65)
            return value

        self.settings["transform"] = slow_response
        short = dataclasses.replace(
            self.provider,
            transport=BoundedVllmJsonClient(
                endpoint=self.environ["YAP_KNOWLEDGE_EMBEDDING_ENDPOINT"],
                timeout_seconds=1,
                maximum_response_bytes=2_000_000,
            ),
        )
        started = time.monotonic()
        with self.assertRaises(ReasoningRetryableError):
            short.generate(tuple(chunk(index) for index in range(65)))
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(len(self.requests), 2)

    def test_larger_generation_refuses_a_later_invalid_response(self):
        def response(value):
            return {**value, "model": "other"} if len(self.requests) == 2 else value

        self.settings["transform"] = response
        with self.assertRaises(ValueError):
            self.provider.generate(tuple(chunk(index) for index in range(65)))
        self.assertEqual(len(self.requests), 2)

    def test_generation_preflight_refuses_duplicates_and_total_bytes_before_io(self):
        for chunks in (
            (chunk(0), chunk(0)),
            tuple(chunk(index, "é" * 70_000) for index in range(30)),
        ):
            with self.subTest(chunks=len(chunks)):
                self.requests.clear()
                with self.assertRaises(ValueError):
                    self.provider.generate(chunks)
                self.assertEqual(self.requests, [])

    def test_empty_generation_needs_no_provider_dispatch(self):
        self.assertEqual(self.provider.generate(()), {})
        self.assertEqual(self.requests, [])

    def test_input_bounds_refuse_before_dispatch(self):
        for chunks in (tuple(chunk(i) for i in range(1025)), (chunk(0, "é" * 131073),)):
            with self.assertRaises(ValueError):
                self.provider.generate(chunks)
        self.assertEqual(self.requests, [])

    def test_malformed_projection_refuses_complete_response(self):
        def changed_item(value, **fields):
            return {**value, "data": [{**value["data"][0], **fields}]}

        transformations = [
            lambda value: {**value, "model": "other-model"},
            lambda value: {**value, "object": "other"},
            lambda value: {**value, "data": []},
            lambda value: {**value, "data": [None]},
            lambda value: changed_item(value, index=True),
            lambda value: changed_item(value, index=1),
            lambda value: changed_item(value, object="other"),
            lambda value: changed_item(value, embedding=[0.5] * 767),
            lambda value: changed_item(value, embedding=[True] * 768),
            lambda value: changed_item(value, embedding=[float("nan")] * 768),
            lambda value: changed_item(value, embedding=[float("inf")] * 768),
            lambda value: changed_item(value, embedding=[10**400] * 768),
        ]
        for transform in transformations:
            with self.subTest(transform=transform):
                self.settings["transform"] = transform
                with self.assertRaises(ValueError):
                    self.provider.generate((chunk(0),))
        self.settings["transform"] = lambda value: {
            **value,
            "data": [value["data"][0], value["data"][0]],
        }
        with self.assertRaises(ValueError):
            self.provider.generate((chunk(0), chunk(1)))

    def test_http_rejection_never_returns_vectors(self):
        for status, error in (
            (400, VllmRequestRejected),
            (503, ReasoningRetryableError),
        ):
            self.settings["status"] = status
            with self.assertRaises(error):
                self.provider.generate((chunk(0),))

    def test_timeout_is_contained_and_following_request_recovers(self):
        self.settings["release"] = threading.Event()
        short = dataclasses.replace(
            self.provider,
            transport=BoundedVllmJsonClient(
                endpoint=self.environ["YAP_KNOWLEDGE_EMBEDDING_ENDPOINT"],
                timeout_seconds=1,
                maximum_response_bytes=2_000_000,
            ),
        )
        with self.assertRaises(ReasoningRetryableError):
            short.generate((chunk(0),))
        self.settings["release"].set()
        self.settings["release"] = None
        self.assertEqual(short.generate((chunk(0),))["0"], (0.25,) * 768)

    def test_response_byte_bound_is_enforced(self):
        short = dataclasses.replace(
            self.provider,
            transport=BoundedVllmJsonClient(
                endpoint=self.environ["YAP_KNOWLEDGE_EMBEDDING_ENDPOINT"],
                timeout_seconds=1,
                maximum_response_bytes=100,
            ),
        )
        with self.assertRaises(ValueError):
            short.generate((chunk(0),))

    def test_incomplete_invalid_and_external_configuration_refuses_without_io(self):
        with patch(
            "yap_server.knowledge.knowledge_publication_service.private_postgres_connection_factory",
            side_effect=AssertionError("unexpected database access"),
        ):
            self.assertIsNone(configured_embedding_provider({}))
            for name in self.environ:
                with self.assertRaises(ValueError):
                    configured_embedding_provider({name: self.environ[name]})
            for field, values in (
                (
                    "YAP_KNOWLEDGE_EMBEDDING_ENDPOINT",
                    (
                        "https://private.example",
                        "http://localhost:1234",
                        "http://127.0.0.1:1234/path",
                        "http://10.0.0.1:1234",
                    ),
                ),
                (
                    "YAP_KNOWLEDGE_EMBEDDING_MODEL_ID",
                    ("", " private-model ", "x" * 257),
                ),
                ("YAP_KNOWLEDGE_EMBEDDING_MODEL_REVISION", ("", "mutable", "A" * 64)),
            ):
                for value in values:
                    with self.assertRaisesRegex(
                        ValueError,
                        "^reviewed embedding deployment configuration is unavailable$",
                    ):
                        configured_embedding_provider({**self.environ, field: value})
            for mode, auth in ((None, True), ("disabled", True), ("postgres", False)):
                with self.assertRaises(ValueError):
                    build_knowledge_publication_service(
                        {**self.environ, "YAP_KNOWLEDGE_PUBLICATION_RUNTIME": mode},
                        authenticated_team_mode=auth,
                    )
        self.assertEqual(self.requests, [])
