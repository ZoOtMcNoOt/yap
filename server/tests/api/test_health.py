import unittest

from yap_server.api import health


class HealthTests(unittest.TestCase):
    def test_health_matches_the_frozen_health_only_contract(self) -> None:
        self.assertEqual(
            health(),
            {
                "service": "yap-server",
                "status": "ok",
                "apiVersion": "1",
                "auth": "not_configured",
                "capabilities": {
                    "batchJobs": False,
                    "liveStreaming": False,
                    "jobStatus": False,
                },
            },
        )

    def test_authentication_alone_does_not_advertise_job_handlers(self) -> None:
        self.assertEqual(
            health(authentication_required=True),
            {
                "service": "yap-server",
                "status": "ok",
                "apiVersion": "1",
                "auth": "required",
                "capabilities": {
                    "batchJobs": False,
                    "liveStreaming": False,
                    "jobStatus": False,
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
