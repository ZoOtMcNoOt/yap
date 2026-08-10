from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
from tempfile import TemporaryDirectory
import unittest

from yap_server.knowledge.okf_compiler import (
    compile_okf_bundle,
    validate_compiled_generation,
)
from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey
from yap_server.knowledge.knowledge_source_admission import (
    review_curated_knowledge_generation,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "okf" / "pinned-v0.1"


class OkfCompilerTests(unittest.TestCase):
    def test_curated_review_requires_authenticated_fixed_role_and_derives_manifest(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_linked_bundle(root)
            generation = compile_okf_bundle(
                root,
                tenant_id="tenant-a",
                source_revision="reviewed-revision",
            )
        unprivileged = AuthenticatedPrincipal(
            tenant_id="tenant-a",
            subject_id="alice",
            client_id="okf-tests",
            scopes=frozenset(),
        )
        with self.assertRaisesRegex(PermissionError, "cannot review"):
            review_curated_knowledge_generation(
                unprivileged,
                repository_revision=generation.source_revision,
                source_path="knowledge/voiceos",
                generation=generation,
            )
        authorized = replace(
            unprivileged,
            roles=frozenset({"knowledge.curator"}),
        )
        first = review_curated_knowledge_generation(
            authorized,
            repository_revision=generation.source_revision,
            source_path="knowledge/voiceos",
            generation=generation,
        )
        second = review_curated_knowledge_generation(
            authorized,
            repository_revision=generation.source_revision,
            source_path="knowledge/voiceos",
            generation=generation,
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first.source_manifest_sha256, generation.generation_sha256)

    def test_rejects_mutated_compiled_projection_identities(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_linked_bundle(root)
            generation = compile_okf_bundle(
                root,
                tenant_id="tenant-a",
                source_revision="reviewed-revision",
            )

        permission = generation.permissions[0]
        concept = generation.concepts[0]
        chunk = generation.chunks[0]
        relationship = generation.relationships[0]
        mutations = (
            replace(
                generation,
                permissions=(
                    replace(
                        permission,
                        audience=(PrincipalKey("tenant-a", "mallory"),),
                    ),
                    *generation.permissions[1:],
                ),
            ),
            replace(
                generation,
                permissions=(
                    replace(permission, permission_sha256="0" * 64),
                    *generation.permissions[1:],
                ),
            ),
            replace(
                generation,
                concepts=(replace(concept, body=concept.body + "\nmutated"),)
                + generation.concepts[1:],
            ),
            replace(
                generation,
                concepts=(
                    replace(
                        concept,
                        frontmatter={**concept.frontmatter, "title": "Mutated"},
                    ),
                )
                + generation.concepts[1:],
            ),
            replace(
                generation,
                chunks=(replace(chunk, text=chunk.text + " mutated"),)
                + generation.chunks[1:],
            ),
            replace(
                generation,
                relationships=(
                    replace(relationship, target_concept_id="projects/other"),
                )
                + generation.relationships[1:],
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    validate_compiled_generation(mutation)

    def test_compiles_the_pinned_synthetic_conformance_fixture(self) -> None:
        generation = compile_okf_bundle(
            FIXTURE_ROOT,
            tenant_id="fixture-tenant",
            source_revision="fixture-commit",
        )

        self.assertEqual(generation.okf_version, "0.1")
        self.assertEqual(generation.concepts[0].concept_id, "projects/voiceos")
        self.assertEqual(
            generation.concepts[0].frontmatter["fixture_extension"],
            {"preserve": True},
        )

    def test_compiles_pinned_okf_and_preserves_unknown_frontmatter(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.md").write_text(
                "---\nokf_version: '0.1'\n---\n# Knowledge\n",
                encoding="utf-8",
            )
            (root / "projects").mkdir()
            (root / "projects" / "voiceos.md").write_text(
                """---
type: Project
title: VoiceOS
resource: yap://tenant/tenant-a/project/voiceos
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance:
  source: meeting-result
  source_revision: result-7
producer_extension:
  retained: true
redirects: [projects/voiceos-old]
---
# VoiceOS

See the [release decision](/decisions/release.md).
""",
                encoding="utf-8",
            )
            (root / "permissions").mkdir()
            (root / "permissions" / "projects.yml").write_text(
                """path_prefix: projects/
audience:
  users:
    - tenant_id: tenant-a
      subject_id: alice
purposes: [knowledge.read]
classification: internal
denials: {users: []}
""",
                encoding="utf-8",
            )

            first = compile_okf_bundle(
                root,
                tenant_id="tenant-a",
                source_revision="commit-a",
            )
            second = compile_okf_bundle(
                root,
                tenant_id="tenant-a",
                source_revision="commit-a",
            )

        self.assertEqual(first, second)
        self.assertEqual(first.okf_version, "0.1")
        self.assertEqual(first.generation_sha256, second.generation_sha256)
        self.assertEqual(len(first.concepts), 1)
        concept = first.concepts[0]
        self.assertEqual(concept.concept_id, "projects/voiceos")
        self.assertEqual(concept.frontmatter["producer_extension"], {"retained": True})
        self.assertEqual(concept.broken_links, ("decisions/release",))
        self.assertEqual(concept.redirect_history, ("projects/voiceos-old",))

    def test_compiles_tenant_scoped_permissions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.md").write_text(
                "---\nokf_version: '0.1'\n---\n# Knowledge\n",
                encoding="utf-8",
            )
            (root / "projects").mkdir()
            (root / "projects" / "voiceos.md").write_text(
                """---
type: Project
title: VoiceOS
resource: yap://tenant/tenant-a/project/voiceos
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {source: reviewed-document, source_revision: revision-1}
---
# VoiceOS
""",
                encoding="utf-8",
            )
            (root / "permissions").mkdir()
            (root / "permissions" / "projects.yml").write_text(
                """path_prefix: projects/
audience:
  users:
    - tenant_id: tenant-a
      subject_id: alice
purposes: [knowledge.read]
classification: internal
denials: {users: []}
""",
                encoding="utf-8",
            )

            generation = compile_okf_bundle(
                root,
                tenant_id="tenant-a",
                source_revision="commit-a",
            )

        self.assertEqual(len(generation.permissions), 1)
        permission = generation.permissions[0]
        self.assertEqual(permission.path_prefix, "projects/")
        self.assertEqual(permission.audience, (PrincipalKey("tenant-a", "alice"),))
        self.assertEqual(permission.denials, ())
        self.assertEqual(permission.purposes, ("knowledge.read",))

    def test_rejects_duplicate_yaml_keys_instead_of_silently_overwriting(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.md").write_text(
                "---\nokf_version: '0.1'\n---\n# Knowledge\n",
                encoding="utf-8",
            )
            (root / "projects").mkdir()
            (root / "projects" / "voiceos.md").write_text(
                """---
type: Project
type: Policy
title: VoiceOS
resource: yap://tenant/tenant-a/project/voiceos
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {source: reviewed-document, source_revision: revision-1}
---
# VoiceOS
""",
                encoding="utf-8",
            )
            (root / "permissions").mkdir()
            (root / "permissions" / "projects.yml").write_text(
                """path_prefix: projects/
audience: {users: [{tenant_id: tenant-a, subject_id: alice}]}
purposes: [knowledge.read]
classification: internal
denials: {users: []}
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate YAML key"):
                compile_okf_bundle(
                    root,
                    tenant_id="tenant-a",
                    source_revision="commit-a",
                )

    def test_compiles_deterministic_chunks_and_relationship_authority(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.md").write_text(
                "---\nokf_version: '0.1'\n---\n# Knowledge\n", encoding="utf-8"
            )
            for folder in ("decisions", "projects", "permissions"):
                (root / folder).mkdir()
            (root / "decisions" / "release.md").write_text(
                """---
type: Decision
title: Release
resource: yap://tenant/tenant-a/decision/release
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {source: reviewed-document, source_revision: revision-1}
relationships:
  - {type: affects, target: /projects/voiceos.md, authority: human_confirmed}
  - {type: suggests, target: /projects/voiceos.md, authority: agent_proposed}
---
# Release

The approved release affects [VoiceOS](/projects/voiceos.md).
""",
                encoding="utf-8",
            )
            (root / "projects" / "voiceos.md").write_text(
                """---
type: Project
title: VoiceOS
resource: yap://tenant/tenant-a/project/voiceos
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {source: reviewed-document, source_revision: revision-1}
---
# VoiceOS
""",
                encoding="utf-8",
            )
            for name, prefix in (
                ("decisions", "decisions/"),
                ("projects", "projects/"),
            ):
                (root / "permissions" / f"{name}.yml").write_text(
                    f"""path_prefix: {prefix}
audience: {{users: [{{tenant_id: tenant-a, subject_id: alice}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
""",
                    encoding="utf-8",
                )

            first = compile_okf_bundle(root, tenant_id="tenant-a", source_revision="r1")
            second = compile_okf_bundle(
                root, tenant_id="tenant-a", source_revision="r1"
            )

        self.assertEqual(first.chunks, second.chunks)
        self.assertEqual(len(first.chunks), 1)
        self.assertEqual(first.chunks[0].linked_concept_ids, ("projects/voiceos",))
        authorities = {item.authority: item.canonical for item in first.relationships}
        self.assertEqual(
            authorities,
            {"asserted": True, "human_confirmed": True, "agent_proposed": False},
        )

    def test_allows_dotted_permission_prefixes_but_rejects_linked_directories(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as external:
            root = Path(directory)
            (root / "index.md").write_text(
                "---\nokf_version: '0.1'\n---\n# Knowledge\n", encoding="utf-8"
            )
            (root / "team.v1").mkdir()
            (root / "team.v1" / "term.md").write_text(
                """---
type: Term
title: Term
resource: yap://tenant/tenant-a/term/one
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {source: reviewed-document, source_revision: revision-1}
---
# Term
""",
                encoding="utf-8",
            )
            (root / "permissions").mkdir()
            (root / "permissions" / "term.yml").write_text(
                """path_prefix: team.v1/
audience: {users: [{tenant_id: tenant-a, subject_id: alice}]}
purposes: [knowledge.read]
classification: internal
denials: {users: []}
""",
                encoding="utf-8",
            )
            generation = compile_okf_bundle(
                root, tenant_id="tenant-a", source_revision="revision-1"
            )
            self.assertEqual(generation.concepts[0].concept_id, "team.v1/term")

            linked = root / "permissions" / "linked"
            try:
                os.symlink(external, linked, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable on this host")
            with self.assertRaisesRegex(ValueError, "linked directories"):
                compile_okf_bundle(
                    root, tenant_id="tenant-a", source_revision="revision-1"
                )


def _write_linked_bundle(root: Path) -> None:
    (root / "index.md").write_text(
        "---\nokf_version: '0.1'\n---\n# Knowledge\n", encoding="utf-8"
    )
    for folder in ("projects", "decisions", "permissions"):
        (root / folder).mkdir()
    (root / "projects" / "voiceos.md").write_text(
        """---
type: Project
title: VoiceOS
resource: yap://tenant/tenant-a/project/voiceos
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {source: reviewed-document, source_revision: reviewed-revision}
---
# VoiceOS

See the [release decision](/decisions/release.md).
""",
        encoding="utf-8",
    )
    (root / "decisions" / "release.md").write_text(
        """---
type: Decision
title: Release
resource: yap://tenant/tenant-a/decision/release
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {source: reviewed-document, source_revision: reviewed-revision}
---
# Release
""",
        encoding="utf-8",
    )
    for name in ("projects", "decisions"):
        (root / "permissions" / f"{name}.yml").write_text(
            f"""path_prefix: {name}/
audience: {{users: [{{tenant_id: tenant-a, subject_id: alice}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
""",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
