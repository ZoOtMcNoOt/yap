from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from yap_server.auth.principal import PrincipalKey
from yap_server.knowledge.knowledge_retrieval import search_compiled_knowledge
from yap_server.knowledge.okf_compiler import compile_okf_bundle


class PermissionSafeRetrievalTests(unittest.TestCase):
    def test_filters_before_scoring_and_omits_paragraphs_linking_hidden_concepts(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.md").write_text(
                "---\nokf_version: '0.1'\n---\n# Knowledge\n",
                encoding="utf-8",
            )
            for folder in ("projects", "secret", "permissions"):
                (root / folder).mkdir()
            public_body = (
                "# VoiceOS\n\n"
                "Alpha roadmap details are approved.\n\n"
                "See [Hidden Launch](/secret/launch.md) for private material.\n"
            )
            (root / "projects" / "voiceos.md").write_text(
                _concept("Project", "VoiceOS", "project/voiceos", public_body),
                encoding="utf-8",
            )
            (root / "secret" / "launch.md").write_text(
                _concept(
                    "Decision",
                    "Hidden Launch",
                    "decision/hidden-launch",
                    "# Hidden Launch\n\nProject codenamed Zircon.\n",
                ),
                encoding="utf-8",
            )
            _permission(root, "projects.yml", "projects/", "alice")
            _permission(root, "secret.yml", "secret/", "charlie")
            generation = compile_okf_bundle(
                root,
                tenant_id="tenant-a",
                source_revision="commit-a",
            )

        alpha = search_compiled_knowledge(
            generation,
            principal=PrincipalKey("tenant-a", "alice"),
            purpose="knowledge.read",
            query="alpha roadmap",
        )
        hidden = search_compiled_knowledge(
            generation,
            principal=PrincipalKey("tenant-a", "alice"),
            purpose="knowledge.read",
            query="hidden zircon",
        )

        self.assertEqual(len(alpha), 1)
        self.assertEqual(alpha[0].concept_id, "projects/voiceos")
        self.assertEqual(alpha[0].text, "Alpha roadmap details are approved.")
        self.assertEqual(
            generation.concepts[0].body[alpha[0].char_start : alpha[0].char_end],
            alpha[0].text,
        )
        self.assertEqual(hidden, ())
        self.assertNotIn("Hidden Launch", repr(alpha))
        self.assertNotIn("secret/launch", repr(alpha))


def _concept(kind: str, title: str, resource_suffix: str, body: str) -> str:
    return f"""---
type: {kind}
title: {title}
resource: yap://tenant/tenant-a/{resource_suffix}
timestamp: 2026-08-09T12:00:00Z
yap_schema: 1
provenance: {{source: reviewed-document, source_revision: revision-1}}
---
{body}"""


def _permission(root: Path, name: str, prefix: str, subject: str) -> None:
    (root / "permissions" / name).write_text(
        f"""path_prefix: {prefix}
audience: {{users: [{{tenant_id: tenant-a, subject_id: {subject}}}]}}
purposes: [knowledge.read]
classification: internal
denials: {{users: []}}
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
