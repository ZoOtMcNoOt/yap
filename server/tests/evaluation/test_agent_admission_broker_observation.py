from __future__ import annotations

import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

from yap_server.evaluation import agent_admission_broker_observation as observation


class AgentAdmissionBrokerObservationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Unix peer credentials are POSIX-only")
    def test_observation_binds_socket_process_and_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            path = root / "admission.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            path.chmod(0o600)
            server.listen(1)

            def accept_once() -> None:
                connection, _address = server.accept()
                connection.close()

            thread = threading.Thread(target=accept_once)
            thread.start()
            try:
                expected = observation.process_binary_sha256(os.getpid())
                with mock.patch.object(
                    observation,
                    "_validate_broker_command_line",
                ):
                    observed = observation.observe_admission_broker(
                        path,
                        expected_binary_sha256=expected,
                        expected_candidate_lock_sha256="a" * 64,
                        expected_rapid_profile_sha256="b" * 64,
                        expected_rapid_state_path=root,
                    )
            finally:
                thread.join(timeout=2)
                server.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual(observed["processId"], os.getpid())
            self.assertEqual(observed["binarySha256"], expected)
            self.assertGreater(observed["processStartTicks"], 0)


if __name__ == "__main__":
    unittest.main()
