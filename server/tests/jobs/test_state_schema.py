from __future__ import annotations

import unittest

from yap_server.jobs.state_schema import persisted_state_metadata


class PersistedStateSchemaTests(unittest.TestCase):
    def test_future_schema_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported schema"):
            persisted_state_metadata({"schemaVersion": 7})

    def test_current_schema_rejects_unrecognized_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "fields"):
            persisted_state_metadata(
                {
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
                    "futureAuthority": {},
                }
            )


if __name__ == "__main__":
    unittest.main()
