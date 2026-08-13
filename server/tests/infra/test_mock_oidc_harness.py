from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest


REPOSITORY = Path(__file__).resolve().parents[3]
LOCK = REPOSITORY / "verification" / "mock-oidc-provider.lock.json"
HARNESS = REPOSITORY / "verification" / "test-mock-oidc-owner-flow.ps1"
FLOW = REPOSITORY / "verification" / "mock-oidc-owner-flow.py"
LOOPBACK_PROXY = REPOSITORY / "verification" / "mock-oidc-loopback-proxy.py"
EXACT_RUNTIME = REPOSITORY / "verification" / "exact-python-runtime.psm1"
DOCKER_OWNER = REPOSITORY / "verification" / "mock-oidc-docker-owner.psm1"
PRIVATE_FILE_OUTPUT = REPOSITORY / "verification" / "private-file-output.psm1"
PRIVATE_GATE_ARTIFACTS = REPOSITORY / "verification" / "private-gate-artifacts.ps1"
FAKE_DOCKER = Path(__file__).with_name("fake_mock_oidc_docker.ps1")
EXPECTED_DIGEST = (
    "sha256:f625692f5bf84939f3d0af4931f2c0f038dca84c4f1bac1171710d544181f97f"
)
EXPECTED_REFERENCE = f"ghcr.io/navikt/mock-oauth2-server:5.0.2@{EXPECTED_DIGEST}"
EXPECTED_ARM64_CONFIG_DIGEST = (
    "sha256:06bfe1111be534917068f27b5424bd64feb0fb2be3d4eace7f34765d6b4be508"
)
EXPECTED_ARM64_PLATFORM_MANIFEST = (
    "sha256:9687bd8fdd9d9ddbbe10de97aac103f7aa6e1b9f9f1426e0cf476945ecdde5b9"
)


class MockOidcHarnessTests(unittest.TestCase):
    @staticmethod
    def _powershell_literal(value: str | Path) -> str:
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    def _run_fake_docker_driver(
        self,
        *,
        mode: str,
        body: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        powershell = shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell Core is unavailable")
        with tempfile.TemporaryDirectory(prefix="yap-fake-docker-") as temporary:
            root = Path(temporary)
            driver = root / "driver.ps1"
            driver.write_text(
                "\n".join(
                    (
                        "#requires -Version 7.4",
                        "#requires -PSEdition Core",
                        "Set-StrictMode -Version Latest",
                        "$ErrorActionPreference = 'Stop'",
                        (
                            "Import-Module "
                            f"{self._powershell_literal(DOCKER_OWNER)} -Force"
                        ),
                        f"$DockerPath = {self._powershell_literal(powershell)}",
                        (
                            "$DockerPrefix = @("
                            "'-NoLogo', '-NoProfile', '-File', "
                            f"{self._powershell_literal(FAKE_DOCKER)})"
                        ),
                        body,
                    )
                ),
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "DOCKER_DEFAULT_PLATFORM": "linux/amd64",
                "YAP_FAKE_DOCKER_MODE": mode,
                "YAP_FAKE_DOCKER_CONFIG_DIGEST": EXPECTED_ARM64_CONFIG_DIGEST,
                "YAP_FAKE_DOCKER_MANIFEST_REFERENCE": EXPECTED_REFERENCE,
                "YAP_FAKE_DOCKER_PLATFORM_MANIFEST_DIGEST": (
                    EXPECTED_ARM64_PLATFORM_MANIFEST
                ),
                "YAP_FAKE_DOCKER_STATE_ROOT": str(root / "state"),
            }
            completed = subprocess.run(
                [
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-File",
                    str(driver),
                ],
                cwd=REPOSITORY,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            trace_path = root / "state" / "trace.log"
            trace = (
                trace_path.read_text(encoding="utf-8").splitlines()
                if trace_path.exists()
                else []
            )
            return completed, trace

    @staticmethod
    def _locked_image_driver_body(follow_up: str) -> str:
        return f"""
$Cancellation = [Threading.CancellationTokenSource]::new()
$PlatformManifestDigests = @{{
    'linux/arm64' = '{EXPECTED_ARM64_PLATFORM_MANIFEST}'
}}
$PlatformConfigDigests = @{{
    'linux/arm64' = '{EXPECTED_ARM64_CONFIG_DIGEST}'
}}
try {{
    $Resolved = Resolve-LockedMockOidcDockerImage `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefix `
        -ManifestReference '{EXPECTED_REFERENCE}' `
        -PlatformManifestDigests $PlatformManifestDigests `
        -PlatformConfigDigests $PlatformConfigDigests `
        -CancellationToken $Cancellation.Token
    if (
        $Resolved.Platform -cne 'linux/arm64' -or
        @(
            '{EXPECTED_ARM64_CONFIG_DIGEST}'
            '{EXPECTED_ARM64_PLATFORM_MANIFEST}'
            '{EXPECTED_REFERENCE}'
        ) -cnotcontains $Resolved.Reference
    ) {{
        throw 'The fake locked-image result changed.'
    }}
{follow_up}
}}
finally {{
    $Cancellation.Dispose()
}}
"""

    def test_provider_is_exact_version_digest_and_mit_provenance_locked(self) -> None:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))

        self.assertEqual(lock["provider"], "navikt/mock-oauth2-server")
        self.assertEqual(lock["version"], "5.0.2")
        self.assertEqual(lock["manifestDigest"], EXPECTED_DIGEST)
        self.assertEqual(
            lock["reference"],
            f"ghcr.io/navikt/mock-oauth2-server:5.0.2@{EXPECTED_DIGEST}",
        )
        self.assertEqual(
            lock["platformManifests"],
            {
                "linux/amd64": (
                    "sha256:"
                    "26c173827c93382eab6543dfc66d5707e39024868618d3c3fd8e6f694717333c"
                ),
                "linux/arm64": EXPECTED_ARM64_PLATFORM_MANIFEST,
            },
        )
        self.assertEqual(
            lock["platformConfigDigests"],
            {
                "linux/amd64": (
                    "sha256:"
                    "9acf7f7170b230703710e7454105b9bd8cd7922460b3403837821b78e1272e17"
                ),
                "linux/arm64": (
                    "sha256:"
                    "06bfe1111be534917068f27b5424bd64feb0fb2be3d4eace7f34765d6b4be508"
                ),
            },
        )
        self.assertEqual(lock["license"], "MIT")
        self.assertEqual(
            lock["releaseSource"],
            "https://github.com/navikt/mock-oauth2-server/releases/tag/5.0.2",
        )
        self.assertEqual(
            lock["licenseSource"],
            "https://github.com/navikt/mock-oauth2-server/blob/5.0.2/LICENSE.md",
        )
        self.assertNotIn(":latest", json.dumps(lock))

    def test_harness_owns_isolation_readiness_timeout_cancel_and_teardown(
        self,
    ) -> None:
        script = HARNESS.read_text(encoding="utf-8")
        owner = DOCKER_OWNER.read_text(encoding="utf-8")

        for expected in (
            "mock-oidc-docker-owner.psm1",
            "$NetworkCreateAttempted = $true",
            "$ContainerRunAttempted = $true",
            "$RunningOnLinux = [OperatingSystem]::IsLinux()",
            "'network',\n            'create',",
            "            '--internal',",
            '"127.0.0.1:${ProviderPort}:8080"',
            "mock-oidc-loopback-proxy.py",
            "synthetic OIDC network identity inspection",
            "synthetic OIDC internal network inspection",
            "'{{.Name}}|{{.Internal}}'",
            "MOCK_OIDC_LOOPBACK_PROXY=READY",
            "$ProxyStartInfo.ArgumentList.Add",
            "'--pull'\n        'never'",
            "$ResolvedImage.Reference",
            "$RunnableImageReference",
            "'--platform'\n        $DockerPlatform",
            "--read-only",
            "'--cap-drop'\n        'ALL'",
            "no-new-privileges=true",
            '"$ProviderBaseUrl/isalive"',
            "[Console]::add_CancelKeyPress",
            "CancellationTokenSource",
            "AddSeconds(30)",
            "AddSeconds(60)",
            "finally {",
            "Remove-OwnedMockOidcDockerResource",
            "-ResourceName $ContainerName",
            "-ResourceName $NetworkName",
            "-OwnerLabelKey $OwnerLabelKey",
            "Remove-Item -LiteralPath $ResolvedStateRoot -Recurse -Force",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, script)
        self.assertNotRegex(script, r"(?im)^\s*--volume\b|^\s*-v\b")
        self.assertNotIn("YAP_AUTH_MODE", script)
        self.assertNotIn("YAP_OIDC_ISSUER", script)
        self.assertNotIn("Get-Content -LiteralPath $FlowErr -Raw", script)
        self.assertIn("$FlowOutput.Length -le 512", script)
        self.assertIn("^MOCK_OIDC_OWNER_FLOW=FAIL:", script)
        self.assertNotIn("Get-Content -LiteralPath $FlowErr", script)
        for expected in (
            "Resolve-LockedMockOidcDockerImage",
            "synthetic OIDC Docker platform inspection",
            "synthetic OIDC staged-image inspection",
            "$ExpectedConfigDigest",
            "$ExpectedPlatformManifest",
            "'{{.Id}}|{{.Os}}/{{.Architecture}}'",
            "-TimeoutMilliseconds 120000",
        ):
            with self.subTest(owner_expected=expected):
                self.assertIn(expected, owner)
        self.assertLess(
            owner.index("synthetic OIDC staged-image inspection"),
            owner.index("synthetic OIDC image pull"),
        )
        self.assertIn("$RunFailure = $null", script)
        self.assertIn("$TeardownFailures", script)
        self.assertNotIn("& $Docker.Source", script)
        self.assertEqual(owner.count("$Process.Start()"), 1)
        self.assertIn("'container', 'rm', '--force', $ResourceName", owner)
        self.assertIn("@('network', 'rm', $ResourceName)", owner)
        self.assertIn("Test-OwnedMockOidcDockerResource", owner)
        self.assertIn("$Names -ccontains $ResourceName", owner)
        self.assertLess(
            script.index("Remove-Item -LiteralPath $ResolvedStateRoot -Recurse -Force"),
            script.index("Write-Output $Result"),
        )
        self.assertLess(
            script.index("[Console]::remove_CancelKeyPress"),
            script.index("Write-Output $Result"),
        )

    def test_flow_failure_marker_is_bounded_and_contains_no_exception_text(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="yap-oidc-marker-") as temporary:
            environment = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    (
                        str(REPOSITORY / "server" / "src"),
                        str(REPOSITORY / "server"),
                    )
                ),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    str(FLOW),
                    "--provider-base-url",
                    "https://not-loopback.invalid",
                    "--state-root",
                    temporary,
                ],
                cwd=REPOSITORY,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(
            completed.stdout.strip(),
            "MOCK_OIDC_OWNER_FLOW=FAIL:authority-validation:runtime",
        )
        self.assertNotIn("not-loopback.invalid", completed.stdout)
        self.assertNotIn("loopback origin", completed.stdout)

    def test_harness_and_exact_runtime_are_cross_platform_powershell(self) -> None:
        script = HARNESS.read_text(encoding="utf-8")
        owner = DOCKER_OWNER.read_text(encoding="utf-8")
        runtime = EXACT_RUNTIME.read_text(encoding="utf-8")

        self.assertIn("[OperatingSystem]::IsWindows()", script)
        self.assertIn("[IO.Path]::DirectorySeparatorChar", script)
        self.assertIn("$PathComparison", script)
        self.assertNotRegex(script, r"(?m)^\s*-WindowStyle\b")
        self.assertNotIn("'server\\src'", script)
        self.assertNotIn("$CanonicalTemp\\yap-mock-oidc-", script)
        self.assertNotIn(".TrimEnd('\\')", script)
        self.assertIn("[Diagnostics.ProcessStartInfo]::new()", owner)
        self.assertIn("$StartInfo.ArgumentList.Add", owner)
        self.assertIn("$Process.Kill($true)", owner)
        self.assertIn("$CancellationToken.IsCancellationRequested", owner)
        self.assertNotIn("-WindowStyle", owner)
        self.assertNotIn("cmd.exe", owner)
        self.assertNotIn("/bin/sh", owner)

        proxy = LOOPBACK_PROXY.read_text(encoding="utf-8")
        self.assertIn('host="127.0.0.1"', proxy)
        self.assertIn("_MAX_CONNECTIONS = 32", proxy)
        self.assertIn("_CONNECTION_TIMEOUT_SECONDS = 10", proxy)
        self.assertIn("if connections.locked():", proxy)
        self.assertIn("asyncio.Semaphore(_MAX_CONNECTIONS)", proxy)
        self.assertIn("backlog=_MAX_CONNECTIONS", proxy)
        self.assertNotIn("0.0.0.0", proxy)
        self.assertNotIn("$LoopbackProxy = Start-Process", script)

        self.assertIn("[OperatingSystem]::IsWindows()", runtime)
        self.assertNotIn("Get-Command uv.exe", runtime)
        self.assertNotIn("Get-Command py.exe", runtime)
        self.assertNotIn("Get-Command python.exe", runtime)
        self.assertNotIn(".venv\\Scripts\\python.exe", runtime)
        self.assertIn("'Scripts'", runtime)
        self.assertIn("'bin'", runtime)

    def test_staged_classic_and_containerd_images_skip_pull(self) -> None:
        expectations = {
            "staged-classic": [
                "docker version",
                f"image inspect reference={EXPECTED_ARM64_CONFIG_DIGEST}",
            ],
            "staged-containerd": [
                "docker version",
                f"image inspect reference={EXPECTED_ARM64_CONFIG_DIGEST}",
                f"image inspect reference={EXPECTED_ARM64_PLATFORM_MANIFEST}",
            ],
        }
        for mode, expected_trace in expectations.items():
            with self.subTest(mode=mode):
                completed, trace = self._run_fake_docker_driver(
                    mode=mode,
                    body=self._locked_image_driver_body(
                        "    Write-Output 'FAKE_STAGED_IMAGE=PASS'",
                    ),
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(
                    completed.stdout.strip(),
                    "FAKE_STAGED_IMAGE=PASS",
                )
                self.assertEqual(trace, expected_trace)

    def test_missing_locked_image_pulls_selected_platform_once_and_reinspects(
        self,
    ) -> None:
        expected_trace = [
            "docker version",
            f"image inspect reference={EXPECTED_ARM64_CONFIG_DIGEST}",
            f"image inspect reference={EXPECTED_ARM64_PLATFORM_MANIFEST}",
            "image pull platform=linux/arm64",
            f"image inspect reference={EXPECTED_REFERENCE}",
        ]
        for mode in ("pull-image", "pull-containerd"):
            with self.subTest(mode=mode):
                completed, trace = self._run_fake_docker_driver(
                    mode=mode,
                    body=self._locked_image_driver_body(
                        "    Write-Output 'FAKE_PULL_IMAGE=PASS'",
                    ),
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(
                    completed.stdout.strip(),
                    "FAKE_PULL_IMAGE=PASS",
                )
                self.assertEqual(trace, expected_trace)

    def test_unlocked_platform_identity_and_architecture_fail_closed(self) -> None:
        expectations = {
            "wrong-platform": ["docker version"],
            "wrong-staged-id": [
                "docker version",
                f"image inspect reference={EXPECTED_ARM64_CONFIG_DIGEST}",
            ],
            "wrong-staged-platform": [
                "docker version",
                f"image inspect reference={EXPECTED_ARM64_CONFIG_DIGEST}",
            ],
            "pull-wrong-image-id": [
                "docker version",
                f"image inspect reference={EXPECTED_ARM64_CONFIG_DIGEST}",
                f"image inspect reference={EXPECTED_ARM64_PLATFORM_MANIFEST}",
                "image pull platform=linux/arm64",
                f"image inspect reference={EXPECTED_REFERENCE}",
            ],
        }
        for mode, expected_trace in expectations.items():
            with self.subTest(mode=mode):
                completed, trace = self._run_fake_docker_driver(
                    mode=mode,
                    body=self._locked_image_driver_body(
                        "    throw 'An invalid image unexpectedly resolved.'",
                    ),
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(trace, expected_trace)

    def test_store_specific_digest_and_platform_are_passed_to_container_run(
        self,
    ) -> None:
        follow_up = """
    $Name = 'yap-mock-oidc-fake-image-run'
    Invoke-MockOidcDockerResourceCreate `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefix `
        -Arguments @(
            'run'
            '--platform'
            $Resolved.Platform
            '--name'
            $Name
            $Resolved.Reference
        ) `
        -TimeoutMilliseconds 5000 `
        -CancellationToken $Cancellation.Token `
        -Operation 'fake exact-image container startup' | Out-Null
    Write-Output 'FAKE_EXACT_IMAGE_RUN=PASS'
"""
        expectations = {
            "staged-classic-and-run": [
                "docker version",
                f"image inspect reference={EXPECTED_ARM64_CONFIG_DIGEST}",
                f"container run image={EXPECTED_ARM64_CONFIG_DIGEST}",
            ],
            "staged-containerd-and-run": [
                "docker version",
                f"image inspect reference={EXPECTED_ARM64_CONFIG_DIGEST}",
                f"image inspect reference={EXPECTED_ARM64_PLATFORM_MANIFEST}",
                f"container run image={EXPECTED_ARM64_PLATFORM_MANIFEST}",
            ],
        }
        for mode, expected_trace in expectations.items():
            with self.subTest(mode=mode):
                completed, trace = self._run_fake_docker_driver(
                    mode=mode,
                    body=self._locked_image_driver_body(follow_up),
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(
                    completed.stdout.strip(),
                    "FAKE_EXACT_IMAGE_RUN=PASS",
                )
                self.assertEqual(trace, expected_trace)

    def test_linux_proxy_marks_ready_rejects_overload_and_releases_port(
        self,
    ) -> None:
        target_connections = 0
        target_connections_lock = threading.Lock()
        target_capacity_reached = threading.Event()

        class EchoHandler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                nonlocal target_connections
                with target_connections_lock:
                    target_connections += 1
                    if target_connections >= 33:
                        target_capacity_reached.set()
                while payload := self.request.recv(4096):
                    self.request.sendall(payload)

        with socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0),
            EchoHandler,
        ) as target:
            target.daemon_threads = True
            target_thread = threading.Thread(target=target.serve_forever)
            target_thread.start()
            reservation = socket.socket()
            reservation.bind(("127.0.0.1", 0))
            proxy_port = reservation.getsockname()[1]
            reservation.close()
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(LOOPBACK_PROXY),
                    "--listen-port",
                    str(proxy_port),
                    "--target-address",
                    target.server_address[0],
                    "--target-port",
                    str(target.server_address[1]),
                ],
                cwd=REPOSITORY,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            marker_queue: queue.Queue[str] = queue.Queue(maxsize=1)
            marker_thread = threading.Thread(
                target=lambda: marker_queue.put(process.stdout.readline()),
            )
            marker_thread.start()
            try:
                try:
                    marker = marker_queue.get(timeout=5)
                except queue.Empty:
                    self.fail("Loopback proxy did not publish its readiness marker.")
                self.assertEqual(marker, "MOCK_OIDC_LOOPBACK_PROXY=READY\n")
                deadline = time.monotonic() + 5
                while True:
                    if process.poll() is not None:
                        stderr = process.stderr.read() if process.stderr else ""
                        self.fail(f"Loopback proxy exited early: {stderr}")
                    try:
                        with socket.create_connection(
                            ("127.0.0.1", proxy_port),
                            timeout=0.2,
                        ) as client:
                            client.sendall(b"bounded-loopback")
                            client.shutdown(socket.SHUT_WR)
                            self.assertEqual(client.recv(4096), b"bounded-loopback")
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            self.fail("Loopback proxy did not become ready.")
                        time.sleep(0.05)
                pinned_clients = [
                    socket.create_connection(
                        ("127.0.0.1", proxy_port),
                        timeout=1,
                    )
                    for _ in range(32)
                ]
                try:
                    self.assertTrue(target_capacity_reached.wait(timeout=3))
                    with socket.create_connection(
                        ("127.0.0.1", proxy_port),
                        timeout=1,
                    ) as overflow:
                        overflow.settimeout(1)
                        self.assertEqual(overflow.recv(1), b"")
                finally:
                    for pinned_client in pinned_clients:
                        pinned_client.close()
            finally:
                process.terminate()
                process.wait(timeout=5)
                target.shutdown()
                target.server_close()
                target_thread.join(timeout=5)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
                marker_thread.join(timeout=5)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", proxy_port), timeout=0.2)

    def test_cancelled_hung_docker_call_is_killed_then_owned_container_is_removed(
        self,
    ) -> None:
        completed, trace = self._run_fake_docker_driver(
            mode="hang-container-run",
            body=r"""
$Name = 'yap-mock-oidc-fake-cancel'
$OwnerKey = 'com.mcnatg1.yap.test-owner'
$OwnerValue = 'mock-oidc'
$RunCancellation = [Threading.CancellationTokenSource]::new()
$CleanupCancellation = [Threading.CancellationTokenSource]::new()
$Cancelled = $false
try {
    $RunCancellation.CancelAfter(1500)
    Invoke-MockOidcDockerResourceCreate `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefix `
        -Arguments @(
            'run',
            '--detach',
            '--name',
            $Name,
            '--label',
            "$OwnerKey=$OwnerValue",
            'locked-image'
        ) `
        -TimeoutMilliseconds 10000 `
        -CancellationToken $RunCancellation.Token `
        -Operation 'fake container startup' | Out-Null
}
catch {
    if ($_.Exception -isnot [OperationCanceledException]) {
        throw
    }
    $Cancelled = $true
}
finally {
    Remove-OwnedMockOidcDockerResource `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefix `
        -ResourceKind container `
        -ResourceName $Name `
        -OwnerLabelKey $OwnerKey `
        -OwnerLabelValue $OwnerValue `
        -TimeoutMilliseconds 5000 `
        -CancellationToken $CleanupCancellation.Token
    $RunCancellation.Dispose()
    $CleanupCancellation.Dispose()
}
if (-not $Cancelled) {
    throw 'The fake hung Docker call was not cancelled.'
}
Write-Output 'FAKE_DOCKER_CANCEL_TEARDOWN=PASS'
""",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "FAKE_DOCKER_CANCEL_TEARDOWN=PASS",
        )
        self.assertEqual(
            trace,
            [
                "container run",
                "container inspect",
                "container rm",
                "container ls",
            ],
        )

    def test_malformed_success_output_still_removes_owned_network_by_exact_name(
        self,
    ) -> None:
        completed, trace = self._run_fake_docker_driver(
            mode="malformed-network-create",
            body=r"""
$Name = 'yap-mock-oidc-fake-malformed'
$OwnerKey = 'com.mcnatg1.yap.test-owner'
$OwnerValue = 'mock-oidc'
$Cancellation = [Threading.CancellationTokenSource]::new()
$Rejected = $false
try {
    Invoke-MockOidcDockerResourceCreate `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefix `
        -Arguments @(
            'network',
            'create',
            '--internal',
            '--label',
            "$OwnerKey=$OwnerValue",
            $Name
        ) `
        -TimeoutMilliseconds 5000 `
        -CancellationToken $Cancellation.Token `
        -Operation 'fake network creation' | Out-Null
}
catch {
    if ($_.Exception.Message -cnotmatch 'output') {
        throw
    }
    $Rejected = $true
}
finally {
    Remove-OwnedMockOidcDockerResource `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefix `
        -ResourceKind network `
        -ResourceName $Name `
        -OwnerLabelKey $OwnerKey `
        -OwnerLabelValue $OwnerValue `
        -TimeoutMilliseconds 5000 `
        -CancellationToken $Cancellation.Token
    $Cancellation.Dispose()
}
if (-not $Rejected) {
    throw 'Malformed successful Docker output was accepted.'
}
Write-Output 'FAKE_DOCKER_MALFORMED_TEARDOWN=PASS'
""",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "FAKE_DOCKER_MALFORMED_TEARDOWN=PASS",
        )
        self.assertEqual(
            trace,
            [
                "network create",
                "network inspect",
                "network rm",
                "network ls",
            ],
        )

    def test_optional_receipt_mode_is_exact_head_bounded_and_post_teardown(
        self,
    ) -> None:
        script = HARNESS.read_text(encoding="utf-8")

        for expected in (
            "[string]$CheckedHead",
            "[string]$ReceiptOutput",
            "Assert-ExactCleanHead",
            "mock-oidc-owner-flow-v1",
            "validatorSources = [ordered]@{",
            "ownerFlowSha256",
            "lockedImageDigest",
            "remainingContainers = 0",
            "remainingNetworks = 0",
            "$ReceiptBytes.Length -gt 4096",
            "receipt publication supports Windows or Linux",
            "Write-NewPrivateFileAtomically",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, script)

        receipt_start = script.index("$Receipt = [ordered]@{")
        receipt_end = script.index("$ReceiptJson =", receipt_start)
        receipt_block = script[receipt_start:receipt_end]
        for forbidden in (
            "$ContainerId",
            "$NetworkId",
            "$StateRoot",
            "$FlowOut",
            "$FlowErr",
            "$PullOut",
            "$PullErr",
            "$Claims",
            "$JsonConfig",
            "Authorization",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, receipt_block)

        self.assertLess(
            script.rindex("if ($TeardownFailures.Count -gt 0)"),
            receipt_start,
        )
        self.assertLess(receipt_start, script.index("Write-Output $Result"))

    def test_private_file_output_is_user_only_and_never_overwrites(self) -> None:
        if os.name != "nt" and not sys.platform.startswith("linux"):
            self.skipTest("Private receipt output supports Windows and Linux")
        powershell = shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell Core is unavailable")
        with tempfile.TemporaryDirectory(prefix="yap-private-output-") as temporary:
            root = Path(temporary)
            destination = root / "receipt.json"
            driver = root / "driver.ps1"
            driver.write_text(
                "\n".join(
                    (
                        "#requires -Version 7.4",
                        "#requires -PSEdition Core",
                        "Set-StrictMode -Version Latest",
                        "$ErrorActionPreference = 'Stop'",
                        # ponytail: Windows temp dirs are Administrators-owned
                        # with inherited ACEs. verify-directory never repairs,
                        # so the caller must protect the parent first.
                        "if ([OperatingSystem]::IsWindows()) {",
                        (
                            "    & "
                            f"{self._powershell_literal(PRIVATE_GATE_ARTIFACTS)} "
                            "-Operation protect-directory "
                            f"-LiteralPath {self._powershell_literal(root)} "
                            "| Out-Null"
                        ),
                        "}",
                        (
                            "Import-Module "
                            f"{self._powershell_literal(PRIVATE_FILE_OUTPUT)} "
                            "-Force"
                        ),
                        "$Content = [Text.Encoding]::UTF8.GetBytes('first')",
                        (
                            "Write-NewPrivateFileAtomically "
                            f"-DestinationPath "
                            f"{self._powershell_literal(destination)} "
                            "-Content $Content"
                        ),
                        (
                            "$EmptyDestination = Join-Path "
                            f"{self._powershell_literal(root)} "
                            "'empty.bin'"
                        ),
                        "$EmptyContent = [byte[]]::new(0)",
                        (
                            "Write-NewPrivateFileAtomically "
                            "-DestinationPath $EmptyDestination "
                            "-Content $EmptyContent"
                        ),
                        "if ((Get-Item -LiteralPath $EmptyDestination).Length -ne 0) {",
                        "    throw 'Private output changed an empty file.'",
                        "}",
                        "$Rejected = $false",
                        "try {",
                        (
                            "    Write-NewPrivateFileAtomically "
                            f"-DestinationPath "
                            f"{self._powershell_literal(destination)} "
                            "-Content ([byte[]](1))"
                        ),
                        "}",
                        "catch {",
                        "    $Rejected = $true",
                        "}",
                        "if (-not $Rejected) {",
                        "    throw 'Private output overwrote an existing file.'",
                        "}",
                        "if (-not [OperatingSystem]::IsWindows()) {",
                        (
                            "    $UnsafeContainer = Join-Path "
                            f"{self._powershell_literal(root)} "
                            "'unsafe-container'"
                        ),
                        ("    $UnsafeParent = Join-Path $UnsafeContainer 'private'"),
                        (
                            "    New-Item -ItemType Directory "
                            "-Path $UnsafeParent | Out-Null"
                        ),
                        (
                            "    $PrivateDirectoryMode = "
                            "[IO.UnixFileMode]::UserRead -bor "
                            "[IO.UnixFileMode]::UserWrite -bor "
                            "[IO.UnixFileMode]::UserExecute"
                        ),
                        (
                            "    [IO.File]::SetUnixFileMode("
                            "$UnsafeParent, $PrivateDirectoryMode)"
                        ),
                        (
                            "    [IO.File]::SetUnixFileMode("
                            "$UnsafeContainer, "
                            "$PrivateDirectoryMode -bor "
                            "[IO.UnixFileMode]::GroupWrite)"
                        ),
                        "    $UnsafeDestination = Join-Path $UnsafeParent 'output'",
                        "    $UnsafeRejected = $false",
                        "    try {",
                        (
                            "        Write-NewPrivateFileAtomically "
                            "-DestinationPath $UnsafeDestination "
                            "-Content ([byte[]](1))"
                        ),
                        "    }",
                        "    catch {",
                        "        $UnsafeRejected = $true",
                        "    }",
                        "    if (-not $UnsafeRejected) {",
                        (
                            "        throw "
                            "'Private output accepted a replaceable ancestor.'"
                        ),
                        "    }",
                        "    if (Test-Path -LiteralPath $UnsafeDestination) {",
                        ("        throw 'Rejected private output left a destination.'"),
                        "    }",
                        (
                            "    $RealContainer = Join-Path "
                            f"{self._powershell_literal(root)} "
                            "'real-container'"
                        ),
                        ("    $RealParent = Join-Path $RealContainer 'private'"),
                        (
                            "    $LinkedContainer = Join-Path "
                            f"{self._powershell_literal(root)} "
                            "'linked-container'"
                        ),
                        (
                            "    New-Item -ItemType Directory "
                            "-Path $RealParent | Out-Null"
                        ),
                        (
                            "    [IO.File]::SetUnixFileMode("
                            "$RealContainer, $PrivateDirectoryMode)"
                        ),
                        (
                            "    [IO.File]::SetUnixFileMode("
                            "$RealParent, $PrivateDirectoryMode)"
                        ),
                        (
                            "    New-Item -ItemType SymbolicLink "
                            "-Path $LinkedContainer "
                            "-Target $RealContainer | Out-Null"
                        ),
                        (
                            "    $LinkedDestination = Join-Path "
                            "$LinkedContainer 'private/output'"
                        ),
                        "    $LinkRejected = $false",
                        "    try {",
                        (
                            "        Write-NewPrivateFileAtomically "
                            "-DestinationPath $LinkedDestination "
                            "-Content ([byte[]](1))"
                        ),
                        "    }",
                        "    catch {",
                        "        $LinkRejected = $true",
                        "    }",
                        "    if (-not $LinkRejected) {",
                        ("        throw 'Private output accepted a linked ancestor.'"),
                        "    }",
                        ("    if (Test-Path -LiteralPath $LinkedDestination) {"),
                        (
                            "        throw "
                            "'Linked-ancestor rejection left a destination.'"
                        ),
                        "    }",
                        "}",
                        "Write-Output 'PRIVATE_FILE_OUTPUT=PASS'",
                    )
                ),
                encoding="utf-8",
            )

            command = [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-File",
                str(driver),
            ]
            if os.name != "nt":
                command = [
                    "/bin/sh",
                    "-c",
                    'umask 0002; exec "$@"',
                    "yap-private-output-test",
                    *command,
                ]
            completed = subprocess.run(
                command,
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                completed.stdout.strip(),
                "PRIVATE_FILE_OUTPUT=PASS",
            )
            self.assertEqual(destination.read_bytes(), b"first")
            self.assertEqual(
                list(root.glob(f".{destination.name}.*.tmp")),
                [],
            )
            if os.name != "nt":
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

        writer = PRIVATE_FILE_OUTPUT.read_text(encoding="utf-8")
        self.assertIn("-ItemType HardLink", writer)
        self.assertNotIn("[IO.File]::Move", writer)

    def test_flow_uses_only_reserved_synthetic_uuid_authority(self) -> None:
        flow = FLOW.read_text(encoding="utf-8")
        identifiers = re.findall(
            r'"(00000000-0000-4000-8000-00000000007[1-5])"',
            flow,
        )

        self.assertEqual(len(set(identifiers)), 5)
        self.assertIn("OidcDiscoveryJwksProvider", flow)
        self.assertIn("OidcAccessTokenAuthenticator", flow)
        self.assertIn("RepositoryBackedRequestAuthenticator", flow)
        self.assertIn('"/v1/jobs"', flow)
        self.assertIn("expires_at_unix", flow)
        self.assertNotIn("access_token)", flow)
        self.assertNotIn("print(token", flow)


if __name__ == "__main__":
    unittest.main()
