from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[3]
LOCK = REPOSITORY / "verification" / "mock-oidc-provider.lock.json"
HARNESS = REPOSITORY / "verification" / "test-mock-oidc-owner-flow.ps1"
FLOW = REPOSITORY / "verification" / "mock-oidc-owner-flow.py"
EXACT_RUNTIME = REPOSITORY / "verification" / "exact-python-runtime.psm1"
DOCKER_OWNER = REPOSITORY / "verification" / "mock-oidc-docker-owner.psm1"
FAKE_DOCKER = Path(__file__).with_name("fake_mock_oidc_docker.ps1")
EXPECTED_DIGEST = (
    "sha256:f625692f5bf84939f3d0af4931f2c0f038dca84c4f1bac1171710d544181f97f"
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
        self.assertIsNotNone(powershell, "PowerShell Core is required")
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
                "YAP_FAKE_DOCKER_MODE": mode,
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

    def test_provider_is_exact_version_digest_and_mit_provenance_locked(self) -> None:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))

        self.assertEqual(lock["provider"], "navikt/mock-oauth2-server")
        self.assertEqual(lock["version"], "5.0.2")
        self.assertEqual(lock["manifestDigest"], EXPECTED_DIGEST)
        self.assertEqual(
            lock["reference"],
            f"ghcr.io/navikt/mock-oauth2-server:5.0.2@{EXPECTED_DIGEST}",
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
            "'network',\n            'create',",
            '"127.0.0.1:${ProviderPort}:8080"',
            "'--pull',\n            'never'",
            "--read-only",
            "'--cap-drop',\n            'ALL'",
            "no-new-privileges=true",
            '"$ProviderBaseUrl/isalive"',
            "[Console]::add_CancelKeyPress",
            "CancellationTokenSource",
            "-TimeoutMilliseconds 120000",
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

        self.assertIn("[OperatingSystem]::IsWindows()", runtime)
        self.assertNotIn("Get-Command uv.exe", runtime)
        self.assertNotIn("Get-Command py.exe", runtime)
        self.assertNotIn("Get-Command python.exe", runtime)
        self.assertNotIn(".venv\\Scripts\\python.exe", runtime)
        self.assertIn("'Scripts'", runtime)
        self.assertIn("'bin'", runtime)

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
            "[IO.File]::Move(",
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
