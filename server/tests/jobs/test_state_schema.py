from __future__ import annotations

import unittest

from yap_server.jobs.state_schema import persisted_state_metadata


class PersistedStateSchemaTests(unittest.TestCase):
    def test_only_the_current_schema_is_accepted(self) -> None:
        for schema_version in (1, 2, 3, 4, 5, 7):
            with self.subTest(schema_version=schema_version):
                with self.assertRaisesRegex(ValueError, "unsupported schema"):
                    persisted_state_metadata({"schemaVersion": schema_version})

        metadata = persisted_state_metadata(_current_state())
        self.assertEqual(metadata.owner.tenant_id, "development-loopback")
        self.assertTrue(metadata.stage_history_complete)
        self.assertEqual(metadata.projection_revision, 1)

    def test_current_schema_rejects_unrecognized_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "fields"):
            persisted_state_metadata({**_current_state(), "futureAuthority": {}})


def _current_state() -> dict[str, object]:
    return {
        "schemaVersion": 6,
        "owner": {
            "tenantId": "development-loopback",
            "subjectId": "local-server",
        },
        "createIdempotencyKey": None,
        "cancellationRequested": False,
        "creation": {},
        "projection": {},
        "receipts": [],
        "asrRouting": None,
        "stageHistoryComplete": True,
        "stageAttempts": [],
        "projectionRevision": 1,
    }


if __name__ == "__main__":
    unittest.main()
