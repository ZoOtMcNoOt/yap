#!/usr/bin/env python3
"""A yap-server that trusts the demo identity provider, and stays up.

There is deliberately no environment that does this. `ServerAuthenticationSettings
.from_environment` refuses issuer overrides ("test-only and cannot enter server
configuration"), so a server that trusts a loopback issuer has to be constructed
in code, the way `verification/authenticated-connector-server.py` is. That
harness exits after its assertion; this host is the same construction, kept
alive for a demo.

What is real here: the OIDC discovery and JWKS fetch against the demo provider,
the token validation policy (identical to the one CI proves in
`verification/mock-oidc-owner-flow.py`), the identity repository, the job
store, chunk upload, commit, and ownership enforcement.

What is absent, and says so: an ASR runtime. Jobs are accepted, stored, and
owned; processing fails with a message naming this script. Attaching real
transcription is the node-setup runbook's job (a vLLM/NeMo worker pool), not a
demo's.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
import threading
from concurrent.futures import Future
from pathlib import Path

_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEMO_DIR.parent
_SERVER_SRC = _REPO_ROOT / "server" / "src"
_SERVER_VENV_PYTHON = _REPO_ROOT / "server" / ".venv" / "bin" / "python"


def _reexec_under_server_venv_if_needed() -> None:
    # Unconditional when the venv exists. Probing for individual imports was
    # wrong the first time: the system interpreter happened to have jwt, so the
    # probe passed and the process then died importing websockets — a module
    # the probe never mentioned. The venv is the environment the server is
    # developed against; if it is there, run in it.
    if _SERVER_VENV_PYTHON.exists():
        # Compare sys.prefix, not executables: uv symlinks .venv/bin/python to
        # the system interpreter, so resolved executable paths look identical
        # from both sides and the exec never fires.
        if Path(sys.prefix).resolve() != _SERVER_VENV_PYTHON.parent.parent.resolve():
            os.execv(str(_SERVER_VENV_PYTHON), [str(_SERVER_VENV_PYTHON), *sys.argv])
        return
    try:
        import jwt  # noqa: F401
        import websockets  # noqa: F401
    except ModuleNotFoundError:
        raise SystemExit(
            "The server dependencies are missing. Run `uv sync` in server/ first."
        )


_reexec_under_server_venv_if_needed()
sys.path.insert(0, str(_SERVER_SRC))

from yap_server.api.app import create_server  # noqa: E402
from yap_server.auth import RepositoryBackedRequestAuthenticator  # noqa: E402
from yap_server.auth.identity_repository import SqliteIdentityRepository  # noqa: E402
from yap_server.auth.oidc_access_tokens import (  # noqa: E402
    OidcAccessTokenAuthenticator,
    OidcAccessTokenPolicy,
)
from yap_server.auth.oidc_metadata import OidcDiscoveryJwksProvider  # noqa: E402
from yap_server.config import (  # noqa: E402
    ServerAuthenticationSettings,
    ServerSettings,
)
from yap_server.jobs import RecordingJobService  # noqa: E402
from yap_server.live import PrivateLiveWebSocketServer  # noqa: E402
from yap_server.pools.batch_contract import AsrRouteDecision  # noqa: E402


def _demo_identity_constants():
    """The tenant/client/audience/issuer the demo IdP mints for.

    Imported from the provider script rather than duplicated, so the two demo
    halves cannot drift apart silently.
    """
    spec = importlib.util.spec_from_file_location(
        "demo_identity_provider", _DEMO_DIR / "run-demo-identity-provider.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The revision is bookkeeping the job store requires (a lowercase SHA-256).
# This one is a deterministic digest naming the absent runtime — it is not a
# verified ASR catalog and does not pretend to be one.
_DEMO_CATALOG_REVISION = hashlib.sha256(b"yap-demo-server-no-asr-runtime").hexdigest()
# Route model revisions are validated as full immutable commits (40 hex), not
# content digests — truncate the naming digest to that shape.
_DEMO_MODEL_REVISION = hashlib.sha256(b"yap-demo-server-no-asr-model").hexdigest()[:40]

_NO_RUNTIME_MESSAGE = (
    "The demo server has no ASR runtime attached. The job, its audio, and its "
    "ownership are real; transcription needs the provisioned worker pool from "
    "the yap-server-node runbook."
)


class _GrantedReservation:
    """A pool slot that always grants, whose work always reports the absence."""

    def __init__(self) -> None:
        self._aborted = False

    def start(self, factory) -> Future[dict[str, object]]:
        if self._aborted:
            raise RuntimeError("demo reservation was aborted")
        factory(threading.Event())
        future: Future[dict[str, object]] = Future()
        future.set_exception(RuntimeError(_NO_RUNTIME_MESSAGE))
        return future

    def abort(self) -> None:
        self._aborted = True


class DemoUnprovisionedAsrProcessor:
    """Real intake with no transcription behind it.

    Not a mock of success: every submitted job fails its processing stage with
    a message naming this script, so nothing downstream can mistake the demo
    for a transcribing deployment.
    """

    asr_catalog_revision = _DEMO_CATALOG_REVISION

    def resolve_route(self, catalog_language_bcp47: str) -> AsrRouteDecision:
        return AsrRouteDecision(
            provider_id="demo-unprovisioned",
            pool_id="demo-unprovisioned-pool",
            execution_mode="fixedBatch",
            model_revision=_DEMO_MODEL_REVISION,
            provider_language=catalog_language_bcp47.split("-", 1)[0].lower(),
        )

    def reserve(self, job_id: str, *, pcm_byte_length: int) -> _GrantedReservation:
        if pcm_byte_length < 1:
            raise ValueError("PCM reservation must be positive")
        return _GrantedReservation()

    def cancel(self, job_id: str) -> bool:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument(
        "--live-port",
        type=int,
        default=18766,
        help="the private live WebSocket transport (same default as production)",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path.home() / ".yap-demo-server",
        help="identity database and job storage live here (created 0700)",
    )
    arguments = parser.parse_args()

    identity = _demo_identity_constants()
    issuer = f"http://127.0.0.1:{identity.DEFAULT_PORT}/{identity.ISSUER_ID}"

    state_root = arguments.state_root
    state_root.mkdir(mode=0o700, exist_ok=True)
    identity_root = state_root / "identity"
    identity_root.mkdir(mode=0o700, exist_ok=True)
    jobs_root = state_root / "jobs"
    jobs_root.mkdir(mode=0o700, exist_ok=True)

    # The exact policy CI proves against this same provider image in
    # verification/mock-oidc-owner-flow.py.
    policy = OidcAccessTokenPolicy(
        issuer=issuer,
        audience=identity.AUDIENCE,
        tenant_id_claim="tid",
        subject_id_claim="oid",
        client_id_claim="azp",
        scope_claim="scp",
        roles_claim="roles",
        identity_format="uuid",
        allowed_tenant_ids=frozenset({identity.TENANT_ID}),
        allowed_client_ids=frozenset({identity.CLIENT_ID}),
        required_scopes=frozenset({"access_as_user"}),
        allowed_roles=frozenset({identity.ADMIN_ROLE}),
    )
    signing_keys = OidcDiscoveryJwksProvider(
        issuer,
        allowed_algorithms=policy.allowed_algorithms,
        allow_insecure_loopback=True,
    )
    # Fail here, loudly, if the provider is not up — not on the first request.
    signing_keys.refresh()

    repository = SqliteIdentityRepository(identity_root / "identity.sqlite3")
    authenticator = RepositoryBackedRequestAuthenticator(
        OidcAccessTokenAuthenticator(policy, signing_keys),
        repository,
    )

    settings = ServerSettings(
        host="127.0.0.1",
        port=arguments.port,
        authentication=ServerAuthenticationSettings(
            mode="entra",
            tenant_id=identity.TENANT_ID,
            audience=identity.AUDIENCE,
            required_scope="access_as_user",
            allowed_client_ids=(identity.CLIENT_ID,),
            identity_storage_dir=identity_root,
        ),
    )
    service = RecordingJobService(
        jobs_root,
        processor=DemoUnprovisionedAsrProcessor(),
        supported_languages=("en-US",),
        now=_utc_now,
        # Entra mode derives ownership from the validated principal; a
        # development fallback owner must not exist here.
        development_principal=None,
    )
    server = create_server(settings, request_authenticator=authenticator, job_service=service)
    # The live transport is a separate loopback listener, exactly as in
    # production and in verification/authenticated-connector-server.py. The
    # client does not discover this port; it connects to an approved origin, so
    # a laptop reaches it by adding one more line to the SSH forward.
    live_server = PrivateLiveWebSocketServer(authenticator, port=arguments.live_port)

    print(f"Demo yap-server on http://127.0.0.1:{arguments.port}")
    print(f"  live     ws://127.0.0.1:{arguments.live_port}")
    print(f"  issuer   {issuer}")
    print(f"  state    {state_root}")
    print(f"  asr      none attached — jobs fail processing with a message saying so")
    live_started = False
    try:
        live_server.start()
        live_started = True
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if live_started:
            live_server.close()
        server.server_close()
        repository.close()


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    main()
