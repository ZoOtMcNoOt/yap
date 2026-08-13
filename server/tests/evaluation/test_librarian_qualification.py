from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from yap_server.knowledge.okf_compiler import compile_okf_bundle

from yap_server.evaluation.librarian_qualification import (
    bind_librarian_compiled_corpus,
    LibrarianExpectedEvidenceItem,
    LibrarianExpectedView,
    LibrarianQualificationInvocation,
    build_librarian_qualification_invocations,
    compile_librarian_expected_evidence,
    evaluate_librarian_qualification,
    load_librarian_qualification_acceptance,
    load_librarian_qualification_corpus,
    render_librarian_qualification_generations,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = REPOSITORY_ROOT / "server"


@dataclass(frozen=True, slots=True)
class _Item:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True, slots=True)
class _View:
    request_id: str
    status: str
    generation_sha256: str | None
    permission_hash: str | None
    authorization_hash: str | None
    evidence_sha256: str | None
    items: tuple[_Item, ...]
    output_budget_exhausted: bool
    reason: str | None


class _Executor:
    def __init__(
        self,
        expected: dict[str, LibrarianExpectedView],
        overrides: dict[str, _View | BaseException] | None = None,
        *,
        duplicate_request_ids: bool = False,
        require_synchronized_call_count: int | None = None,
    ) -> None:
        self._expected = expected
        self._overrides = overrides or {}
        self._duplicate_request_ids = duplicate_request_ids
        self._synchronized = (
            None
            if require_synchronized_call_count is None
            else threading.Barrier(require_synchronized_call_count)
        )
        self.calls: list[tuple[LibrarianQualificationInvocation, bool]] = []

    def __call__(
        self,
        invocation: LibrarianQualificationInvocation,
        cancellation: threading.Event,
    ) -> _View:
        self.calls.append((invocation, cancellation.is_set()))
        if self._synchronized is not None and invocation.mode == "normal":
            self._synchronized.wait(1.0)
        override = self._overrides.get(invocation.invocation_id)
        if isinstance(override, BaseException):
            raise override
        if override is not None:
            return override
        request_id = (
            "librarian-duplicate-request"
            if self._duplicate_request_ids
            else f"librarian-{invocation.case_id}-{invocation.run_id}"
        )
        return _view(request_id, self._expected[invocation.invocation_id])


class LibrarianQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.acceptance = load_librarian_qualification_acceptance(
            SERVER_ROOT / "librarian-acceptance.json"
        )
        self.corpus = load_librarian_qualification_corpus(
            SERVER_ROOT / "librarian-workload-fixtures.json"
        )
        self.fixture_expected = compile_librarian_expected_evidence(self.corpus)
        self.bound = _bound_corpus(self.corpus)
        self.expected = self.bound.expected_views

    def test_contract_freezes_eight_owners_and_ten_bounded_invocations(self) -> None:
        invocations = build_librarian_qualification_invocations(self.corpus)

        self.assertEqual(len(self.corpus.cases), 8)
        self.assertEqual(len({case.owner_id for case in self.corpus.cases}), 8)
        self.assertEqual(len(invocations), 10)
        self.assertEqual(len(self.expected), 10)
        self.assertEqual(
            {item.mode for item in invocations},
            {"normal", "pre-cancelled", "deadline"},
        )
        self.assertEqual(
            [item.maximum_results for item in invocations if item.case_id == "hidden-filter-before-limit"],
            [1],
        )
        self.assertTrue(
            all(item.purpose == "knowledge.read" for item in invocations)
        )
        primary = [item for item in invocations if item.mode == "normal"]
        controlled = [item for item in invocations if item.mode != "normal"]
        self.assertEqual(len(primary), 8)
        self.assertEqual(len({item.owner_id for item in primary}), 8)
        self.assertEqual(
            [(item.run_id, item.mode) for item in controlled],
            [
                ("client-cancelled", "pre-cancelled"),
                ("deadline-exceeded", "deadline"),
            ],
        )

        acceptance = json.loads(
            (SERVER_ROOT / "librarian-acceptance.json").read_text(
                encoding="utf-8"
            )
        )
        forbidden = ("model", "profile", "minimum", "threshold")
        self.assertFalse(
            any(
                token in key.casefold()
                for key in acceptance
                for token in forbidden
            )
        )

    def test_independent_compiler_freezes_exact_citations_and_pack_hashes(self) -> None:
        visible = self.fixture_expected["visible-exact:normal"]

        self.assertEqual(visible.status, "complete")
        self.assertEqual(
            visible.permission_hash,
            "6c2562dc1088d64e58851109fe17c7a1ecc583aa33410d5a4fb06911dcfc3669",
        )
        self.assertEqual(
            visible.authorization_hash,
            "843fb22a542117a8e3bd39d6e43fd883d7ba3ac95cf1b62c50e87b5336f55cee",
        )
        self.assertEqual(
            visible.evidence_sha256,
            "20808435dd1121815f9fe382fc98a2e2c1d43e45cf85c80e71e8662deb3bccf9",
        )
        self.assertEqual(
            visible.items,
            (
                LibrarianExpectedEvidenceItem(
                    "meetings/atlas-visible",
                    "c" * 64,
                    "1ede579a59515a8666a5d4ec5b12eeb23803e1ab1d5e7c7223fe42c50003ad68",
                    0,
                    60,
                    "The Atlas handoff requires two reviewers before publication.",
                ),
            ),
        )

        hidden = self.fixture_expected["hidden-only-unavailable:normal"]
        absent = self.fixture_expected["absent-unavailable:normal"]
        self.assertEqual(hidden.terminal_shape(), absent.terminal_shape())
        self.assertEqual(hidden.status, "evidence-unavailable")
        self.assertEqual(hidden.reason, "empty-result")
        self.assertIsNone(hidden.generation_sha256)
        self.assertEqual(hidden.items, ())

        linked = self.fixture_expected["hidden-link-suppression:normal"]
        limited = self.fixture_expected["hidden-filter-before-limit:normal"]
        self.assertEqual(
            [item.concept_id for item in linked.items],
            ["indexes/orion-public"],
        )
        self.assertEqual(
            [item.concept_id for item in limited.items],
            ["retention/nimbus-a-reviewed"],
        )
        self.assertNotIn("HIDDEN-", repr(linked))
        self.assertNotIn("HIDDEN-", repr(limited))

    def test_renderer_owns_exact_okf_permission_bytes_and_runtime_rebinding(
        self,
    ) -> None:
        rendered = render_librarian_qualification_generations(
            self.corpus,
            tenant_id="fresh-librarian-tenant",
        )
        successor = next(
            item for item in rendered if item.generation_id == "successor"
        )
        atlas = next(
            item
            for item in successor.sources
            if item.concept_id == "meetings/atlas-visible"
        )
        document = atlas.body.decode("utf-8")
        self.assertEqual(atlas.relative_path, "meetings/atlas-visible.md")
        self.assertNotIn("\r", document)
        self.assertEqual(
            document,
            "---\n"
            "type: Note\n"
            "title: meetings/atlas-visible\n"
            "resource: yap://tenant/fresh-librarian-tenant/meetings/atlas-visible/source\n"
            "timestamp: '2026-08-12T00:00:00Z'\n"
            "yap_schema: 1\n"
            "provenance:\n"
            "  source: librarian-public-synthetic\n"
            f"  source_revision: {'c' * 64}\n"
            "---\n"
            "The Atlas handoff requires two reviewers before publication.\n",
        )
        self.assertEqual(
            atlas.body[0:3],
            b"---",
        )
        self.assertEqual(atlas.char_start, 0)
        self.assertEqual(atlas.char_end, len(atlas.text))
        self.assertEqual(
            atlas.content_sha256,
            "6027558aa695c518336d61361f9ce88d11216673d488fcdd6066aed324e0b1bf",
        )
        permission = next(
            item
            for item in successor.files
            if item.relative_path.startswith("permissions/")
            and b"path_prefix: meetings/atlas-visible/\n" in item.body
        )
        self.assertNotIn(b"\r", permission.body)
        self.assertIn(b"tenant_id: fresh-librarian-tenant\n", permission.body)
        self.assertIn(b"path_prefix: meetings/atlas-visible/\n", permission.body)

        runtime = compile_librarian_expected_evidence(
            self.corpus,
            tenant_id="fresh-librarian-tenant",
            generation_sha256s={
                "predecessor": "1" * 64,
                "successor": "2" * 64,
            },
        )["visible-exact:normal"]
        self.assertEqual(runtime.generation_sha256, "2" * 64)
        self.assertEqual(runtime.items[0].content_sha256, atlas.content_sha256)
        self.assertNotEqual(
            runtime.permission_hash,
            self.fixture_expected["visible-exact:normal"].permission_hash,
        )

    def test_compiled_binding_uses_real_generation_permission_and_source_hashes(
        self,
    ) -> None:
        rendered = render_librarian_qualification_generations(
            self.corpus,
            tenant_id="fresh-librarian-tenant",
        )
        compiled = {}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for generation in rendered:
                generation_root = root / generation.generation_id
                for item in generation.files:
                    path = generation_root / item.relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(item.body)
                compiled[generation.generation_id] = compile_okf_bundle(
                    generation_root,
                    tenant_id=generation.tenant_id,
                    source_revision=generation.source_revision,
                )

        bound = bind_librarian_compiled_corpus(
            self.corpus,
            rendered,
            compiled,
        )
        expected = bound.expected_views["visible-exact:normal"]
        successor = compiled["successor"]
        concept = next(
            item
            for item in successor.concepts
            if item.concept_id == "meetings/atlas-visible"
        )
        chunk = next(
            item
            for item in successor.chunks
            if item.concept_id == concept.concept_id
        )
        self.assertEqual(expected.generation_sha256, successor.generation_sha256)
        self.assertEqual(expected.items[0].source_revision, "c" * 64)
        self.assertEqual(expected.items[0].content_sha256, concept.content_sha256)
        self.assertEqual(
            (expected.items[0].char_start, expected.items[0].char_end),
            (
                chunk.char_start + chunk.text.index(expected.items[0].text),
                chunk.char_start
                + chunk.text.index(expected.items[0].text)
                + len(expected.items[0].text),
            ),
        )
        self.assertNotEqual(expected.permission_hash, "0" * 64)
        with self.assertRaises(TypeError):
            bound.expected_views["forged"] = expected  # type: ignore[index]

        with self.assertRaisesRegex(TypeError, "not compiler-bound"):
            evaluate_librarian_qualification(
                executor=_Executor(bound.expected_views),  # type: ignore[arg-type]
                corpus=self.corpus,  # type: ignore[arg-type]
                acceptance=self.acceptance,
            )

        executor = _Executor(
            bound.expected_views,
            require_synchronized_call_count=8,
        )
        result = evaluate_librarian_qualification(
            executor=executor,
            corpus=bound,
            acceptance=self.acceptance,
        )
        self.assertTrue(result.public_evidence["qualified"])

        forged = replace(
            successor.concepts[0],
            content_sha256="0" * 64,
        )
        bad_successor = replace(
            successor,
            concepts=(forged, *successor.concepts[1:]),
        )
        with self.assertRaisesRegex(ValueError, "concept projection differs"):
            bind_librarian_compiled_corpus(
                self.corpus,
                rendered,
                {**compiled, "successor": bad_successor},
            )

        permission = successor.permissions[0]
        bad_permission = replace(permission, permission_sha256="0" * 64)
        bad_successor = replace(
            successor,
            permissions=(bad_permission, *successor.permissions[1:]),
        )
        with self.assertRaisesRegex(ValueError, "permission digest differs"):
            bind_librarian_compiled_corpus(
                self.corpus,
                rendered,
                {**compiled, "successor": bad_successor},
            )

        bad_successor = replace(successor, source_revision="forged-revision")
        with self.assertRaisesRegex(ValueError, "source revision differs"):
            bind_librarian_compiled_corpus(
                self.corpus,
                rendered,
                {**compiled, "successor": bad_successor},
            )

        chunk = successor.chunks[0]
        bad_chunk = replace(chunk, char_end=chunk.char_end + 1)
        bad_successor = replace(
            successor,
            chunks=(bad_chunk, *successor.chunks[1:]),
        )
        with self.assertRaisesRegex(ValueError, "evidence span differs"):
            bind_librarian_compiled_corpus(
                self.corpus,
                rendered,
                {**compiled, "successor": bad_successor},
            )

        changed_file = replace(rendered[0].files[0], body=b"changed\n")
        changed_generation = replace(
            rendered[0],
            files=(changed_file, *rendered[0].files[1:]),
        )
        with self.assertRaisesRegex(ValueError, "rendered corpus differs"):
            bind_librarian_compiled_corpus(
                self.corpus,
                (changed_generation, *rendered[1:]),
                compiled,
            )

    def test_exact_views_qualify_with_counts_and_booleans_only(self) -> None:
        executor = _Executor(
            self.expected,
            require_synchronized_call_count=8,
        )

        result = evaluate_librarian_qualification(
            executor=executor,
            corpus=self.bound,
            acceptance=self.acceptance,
        )

        self.assertEqual(
            result.public_evidence,
            self.acceptance.expected_public_evidence(),
        )
        self.assertTrue(result.public_evidence["qualified"])
        self.assertEqual(result.public_evidence["synchronizedOwnerWaveCount"], 8)
        self.assertTrue(result.public_evidence["synchronizedOwnerWaveMet"])
        self.assertTrue(result.public_evidence["p95WithinBound"])
        self.assertTrue(
            all(
                isinstance(value, (bool, int))
                for value in result.public_evidence.values()
            )
        )
        self.assertFalse(
            any(isinstance(value, str) for value in result.public_evidence.values())
        )
        serialized = repr(result.public_evidence)
        for marker in (
            "Atlas",
            "HIDDEN-ONLY-MARKER-7419",
            "HIDDEN-LINK-MARKER-2087",
            "HIDDEN-LIMIT-MARKER-9563",
            self.corpus.corpus_sha256,
            self.acceptance.plan_sha256,
        ):
            self.assertNotIn(marker, serialized)

        cancelled = {
            item.invocation_id: was_set
            for item, was_set in executor.calls
        }
        primary_calls = [
            (item, was_set)
            for item, was_set in executor.calls
            if item.mode == "normal"
        ]
        self.assertEqual(len(primary_calls), 8)
        self.assertEqual(len({item.owner_id for item, _ in primary_calls}), 8)
        self.assertTrue(all(not was_set for _, was_set in primary_calls))
        self.assertFalse(cancelled["terminal-cutover:normal"])
        self.assertTrue(cancelled["terminal-cutover:client-cancelled"])
        self.assertFalse(cancelled["terminal-cutover:deadline-exceeded"])

    def test_wave_metric_fails_closed_when_one_primary_submission_fails(self) -> None:
        result = evaluate_librarian_qualification(
            executor=_Executor(
                self.expected,
                {"visible-exact:normal": RuntimeError("submit failed")},
                require_synchronized_call_count=8,
            ),
            corpus=self.bound,
            acceptance=self.acceptance,
        )

        self.assertFalse(result.public_evidence["qualified"])
        self.assertEqual(result.public_evidence["synchronizedOwnerWaveCount"], 7)
        self.assertFalse(result.public_evidence["synchronizedOwnerWaveMet"])

    def test_wave_timeout_cancels_and_contains_workers(self) -> None:
        class _BlockingExecutor:
            def __init__(self) -> None:
                self.started = threading.Barrier(8)
                self.stopped = 0
                self.lock = threading.Lock()

            def __call__(self, invocation, cancellation):
                if invocation.run_id == "deadline-exceeded":
                    raise AssertionError("controlled invocation must not run")
                self.started.wait(1.0)
                cancellation.wait(1.0)
                with self.lock:
                    self.stopped += 1
                raise RuntimeError("contained cancellation")

        executor = _BlockingExecutor()
        with (
            mock.patch(
                "yap_server.evaluation.librarian_qualification._PRIMARY_WAVE_TIMEOUT_SECONDS",
                0.01,
            ),
            self.assertRaisesRegex(TimeoutError, "wave exceeded"),
        ):
            evaluate_librarian_qualification(
                executor=executor,
                corpus=self.bound,
                acceptance=self.acceptance,
            )
        self.assertEqual(executor.stopped, 8)
        self.assertFalse(
            any(
                item.name.startswith("librarian-qualification")
                for item in threading.enumerate()
            )
        )

    def test_uncontained_worker_raises_without_blocking_shutdown(self) -> None:
        release = threading.Event()

        class _UncontainedExecutor:
            def __call__(self, invocation, cancellation):
                del invocation, cancellation
                release.wait(2.0)
                raise RuntimeError("released")

        with (
            mock.patch(
                "yap_server.evaluation.librarian_qualification._PRIMARY_WAVE_TIMEOUT_SECONDS",
                0.01,
            ),
            mock.patch(
                "yap_server.evaluation.librarian_qualification._WORKER_CONTAINMENT_SECONDS",
                0.01,
            ),
            self.assertRaisesRegex(RuntimeError, "not contained"),
        ):
            evaluate_librarian_qualification(
                executor=_UncontainedExecutor(),
                corpus=self.bound,
                acceptance=self.acceptance,
            )
        release.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and any(
            item.name.startswith("librarian-qualification")
            for item in threading.enumerate()
        ):
            time.sleep(0.01)

    def test_forged_pack_identity_or_source_bytes_fail_closed(self) -> None:
        expected = self.expected["visible-exact:normal"]
        base = _view("forged-visible", expected)
        forged_item = replace(base.items[0], text="X" * len(base.items[0].text))
        for field, changed in (
            ("permission_hash", "1" * 64),
            ("authorization_hash", "2" * 64),
            ("evidence_sha256", "3" * 64),
            ("items", (forged_item,)),
        ):
            with self.subTest(field=field):
                result = evaluate_librarian_qualification(
                    executor=_Executor(
                        self.expected,
                        {
                            "visible-exact:normal": replace(
                                base, **{field: changed}
                            )
                        },
                    ),
                    corpus=self.bound,
                    acceptance=self.acceptance,
                )
                self.assertFalse(result.public_evidence["qualified"])
                self.assertEqual(
                    result.public_evidence["exactEvidenceMatchCount"], 9
                )
                self.assertEqual(
                    result.public_evidence["terminalMismatchCount"], 1
                )

    def test_hidden_bytes_partial_failure_and_duplicate_ids_cannot_false_green(
        self,
    ) -> None:
        hidden_item = _Item(
            "vaults/cobalt-hidden",
            "c" * 64,
            "4" * 64,
            0,
            52,
            "The cobalt vault contains HIDDEN-ONLY-MARKER-7419.",
        )
        leaked = _View(
            "leaked-hidden",
            "complete",
            "b" * 64,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            (hidden_item,),
            False,
            None,
        )
        partial = replace(
            _view(
                "partial-stale",
                self.expected["expected-generation-stale:normal"],
            ),
            generation_sha256="b" * 64,
        )
        result = evaluate_librarian_qualification(
            executor=_Executor(
                self.expected,
                {
                    "hidden-only-unavailable:normal": leaked,
                    "expected-generation-stale:normal": partial,
                    "terminal-cutover:deadline-exceeded": RuntimeError(
                        "raw hidden diagnostic"
                    ),
                },
            ),
            corpus=self.bound,
            acceptance=self.acceptance,
        )

        self.assertFalse(result.public_evidence["qualified"])
        self.assertEqual(result.public_evidence["terminalMismatchCount"], 3)
        self.assertFalse(result.public_evidence["hiddenOnlyIndistinguishable"])
        self.assertNotIn("HIDDEN-ONLY", repr(result.public_evidence))
        self.assertNotIn("diagnostic", repr(result.public_evidence))

        duplicate = evaluate_librarian_qualification(
            executor=_Executor(self.expected, duplicate_request_ids=True),
            corpus=self.bound,
            acceptance=self.acceptance,
        )
        self.assertFalse(duplicate.public_evidence["qualified"])
        self.assertEqual(duplicate.public_evidence["uniqueRequestIdCount"], 1)

    def test_fixture_mutations_cannot_turn_permission_failures_green(self) -> None:
        original = json.loads(
            (SERVER_ROOT / "librarian-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        mutations = []

        hidden_visible = json.loads(json.dumps(original))
        hidden_visible["generations"][1]["sources"][1][
            "visibleToOwnerIds"
        ].append("owner-hidden")
        mutations.append(hidden_visible)

        link_visible = json.loads(json.dumps(original))
        link_visible["generations"][1]["sources"][3][
            "visibleToOwnerIds"
        ].append("owner-hidden-link")
        mutations.append(link_visible)

        limit_before_filter = json.loads(json.dumps(original))
        limit_before_filter["cases"][4]["request"]["maximumResults"] = 2
        mutations.append(limit_before_filter)

        stale_rebound = json.loads(json.dumps(original))
        stale_rebound["cases"][5]["request"][
            "expectedGenerationId"
        ] = "successor"
        mutations.append(stale_rebound)

        revoked_visible = json.loads(json.dumps(original))
        revoked_visible["generations"][1]["sources"][9][
            "visibleToOwnerIds"
        ].append("owner-revoked")
        mutations.append(revoked_visible)

        for index, changed in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "fixtures.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError,
                    "frozen evidence map differs|terminal expectation differs",
                ):
                    load_librarian_qualification_corpus(path)

    def test_strict_schema_rejects_compatibility_and_threshold_fields(self) -> None:
        acceptance = json.loads(
            (SERVER_ROOT / "librarian-acceptance.json").read_text(
                encoding="utf-8"
            )
        )
        fixtures = json.loads(
            (SERVER_ROOT / "librarian-workload-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        changed_acceptance = (
            {**acceptance, "schemaVersion": 2},
            {**acceptance, "minimumCaseCount": 8},
            {**acceptance, "modelProfile": "none"},
            {**acceptance, "exactEvidenceMatchCount": 9},
        )
        for index, changed in enumerate(changed_acceptance):
            with self.subTest(acceptance=index), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "acceptance.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_librarian_qualification_acceptance(path)

        changed_fixtures = (
            {**fixtures, "schemaVersion": 2},
            {**fixtures, "legacyCases": fixtures["cases"]},
        )
        for index, changed in enumerate(changed_fixtures):
            with self.subTest(fixtures=index), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "fixtures.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_librarian_qualification_corpus(path)


def _bound_corpus(corpus):
    rendered = render_librarian_qualification_generations(
        corpus,
        tenant_id="fresh-librarian-tenant",
    )
    compiled = {}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for generation in rendered:
            generation_root = root / generation.generation_id
            for item in generation.files:
                path = generation_root / item.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.body)
            compiled[generation.generation_id] = compile_okf_bundle(
                generation_root,
                tenant_id=generation.tenant_id,
                source_revision=generation.source_revision,
            )
    return bind_librarian_compiled_corpus(corpus, rendered, compiled)


def _view(request_id: str, expected: LibrarianExpectedView) -> _View:
    return _View(
        request_id=request_id,
        status=expected.status,
        generation_sha256=expected.generation_sha256,
        permission_hash=expected.permission_hash,
        authorization_hash=expected.authorization_hash,
        evidence_sha256=expected.evidence_sha256,
        items=tuple(
            _Item(
                item.concept_id,
                item.source_revision,
                item.content_sha256,
                item.char_start,
                item.char_end,
                item.text,
            )
            for item in expected.items
        ),
        output_budget_exhausted=expected.output_budget_exhausted,
        reason=expected.reason,
    )


if __name__ == "__main__":
    unittest.main()
