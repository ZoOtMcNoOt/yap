from copy import deepcopy
import unittest

from tests.recording_job_fixtures import (
    batch_api_recording_job_request,
    provenance_contract_job_request,
    service_recording_job_request,
)


class RecordingJobFixtureTests(unittest.TestCase):
    def test_service_request_uses_one_session_identity(self) -> None:
        request = service_recording_job_request(session_id="session-under-test")

        self.assertEqual(request["metadata"]["sessionId"], "session-under-test")
        self.assertEqual(request["captureManifest"]["schemaVersion"], 2)
        self.assertEqual(request["captureManifest"]["sessionId"], "session-under-test")
        self.assertEqual(request["preprocessingEvidence"]["schemaVersion"], 2)
        self.assertIn("asrCatalogRevision", request)
        self.assertEqual(
            request["chunks"][0]["replayKey"]["sessionId"],
            "session-under-test",
        )

    def test_behavior_builders_return_fresh_nested_values(self) -> None:
        first = batch_api_recording_job_request()
        second = batch_api_recording_job_request()
        first["metadata"]["preferredLanguagesBcp47"].append("fr-FR")

        self.assertEqual(first["displayName"], "Batch API fixture")
        self.assertEqual(first["metadata"]["sessionId"], "s-batch-api")
        self.assertEqual(second["metadata"]["preferredLanguagesBcp47"], ["en-US"])

    def test_provenance_request_copies_track_source(self) -> None:
        track_source = {
            "kind": "captured",
            "device": {"deviceId": "input-1", "label": "Microphone"},
        }
        expected_source = deepcopy(track_source)

        request = provenance_contract_job_request("live_capture", track_source)
        track_source["device"]["label"] = "Changed"

        self.assertEqual(request["metadata"]["origin"], "live_capture")
        self.assertEqual(request["tracks"][0]["source"], expected_source)


if __name__ == "__main__":
    unittest.main()
