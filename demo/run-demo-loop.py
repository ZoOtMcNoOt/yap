#!/usr/bin/env python3
"""Drive the demo end to end: two identities, real audio, ownership enforced.

Requires the demo identity provider (`run-demo-identity-provider.py serve`) and
the demo server (`run-demo-server.py`) to be up. Exits nonzero if any assertion
fails, so this is a check, not a tour.

What it proves over plain HTTP against the shipping request path:

  1. alice authenticates through OIDC discovery + JWKS and submits a real
     recording — the LibriSpeech fixture WAV, byte-for-byte, chunk-hashed.
  2. bob authenticates the same way and CANNOT see, poll, or delete alice's
     job: the server answers as if it does not exist.
  3. An unauthenticated caller gets 401 for the same URL.
  4. alice still sees her own job afterwards — the refusals above were not
     the job quietly vanishing.

Transcription itself is reported as whatever the server says; against
run-demo-server.py that is a processing failure naming the absent ASR runtime.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from hashlib import sha256
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent
FIXTURE_WAV = REPO_ROOT / "server" / "tests" / "fixtures" / "asr" / "2086-149220-0033.wav"
BASE_URL = "http://127.0.0.1:18765"

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        _FAILURES.append(label)


def _token(identity: str) -> str:
    output = subprocess.run(
        [str(DEMO_DIR / "run-demo-identity-provider.py"), "token", "--identity", identity],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().splitlines()
    return output[-1]


def _request(
    method: str,
    path: str,
    token: str | None,
    body: bytes | None = None,
    content_type: str = "application/json",
    idempotency_key: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    request = urllib.request.Request(BASE_URL + path, data=body, method=method)
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        request.add_header("Content-Type", content_type)
    if idempotency_key is not None:
        request.add_header("Idempotency-Key", idempotency_key)
    for name, value in (extra_headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        payload = error.read()
        try:
            return error.code, json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            return error.code, {}


def _job_request(session_id: str, pcm: bytes, sample_rate: int) -> dict:
    samples = len(pcm) // 2
    duration_ms = samples * 1000 // sample_rate
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    expiry = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7 * 86400))
    track_id = "track-1"
    return {
        "displayName": "Demo loop: LibriSpeech 2086-149220-0033",
        "metadata": {
            "sessionId": session_id,
            "mode": "meeting",
            "origin": "imported_file",
            "triggerMode": "toggle",
            "startedAtUtc": now,
            "utcOffsetMinutesAtStart": 0,
            "localeHintBcp47": "en-US",
            "countryCodeHint": "US",
            "preferredLanguagesBcp47": ["en-US"],
            "appVersion": "0.1.0",
            "platform": "windows",
            "privacyPolicyVersion": "development-only",
            "retentionExpiresAtUtc": expiry,
        },
        "languageDecision": {
            "mode": "fixed",
            "languageBcp47": "en-US",
            "disposition": "primary",
        },
        "tracks": [
            {
                "trackId": track_id,
                "source": {"kind": "imported", "provenance": "unknown"},
                "deviceId": None,
                "originalSampleRateHz": sample_rate,
                "originalChannels": 1,
            }
        ],
        "route": "server_batch",
        "captureManifest": {
            "schemaVersion": 1,
            "sessionId": session_id,
            "sha256": sha256(pcm).hexdigest(),
            "byteLength": len(pcm),
        },
        "chunks": [
            {
                "replayKey": {
                    "schemaVersion": 1,
                    "sessionId": session_id,
                    "trackId": track_id,
                    "sequenceStart": 0,
                    "sequenceEnd": samples - 1,
                },
                "contentIdentity": {
                    "sha256": sha256(pcm).hexdigest(),
                    "byteLength": len(pcm),
                },
                "audioCodec": "pcm_s16le",
                "sampleRateHz": sample_rate,
                "channels": 1,
                "startMs": 0,
                "durationMs": duration_ms,
            }
        ],
    }


def main() -> None:
    with wave.open(str(FIXTURE_WAV)) as reader:
        assert reader.getnchannels() == 1 and reader.getsampwidth() == 2
        sample_rate = reader.getframerate()
        pcm = reader.readframes(reader.getnframes())
    print(f"audio: {FIXTURE_WAV.name} — {len(pcm)} PCM bytes, {sample_rate} Hz")

    alice = _token("alice")
    bob = _token("bob")

    print("\nalice submits the recording:")
    # uuid, not a timestamp: a clock-second session id collides on back-to-back
    # runs and the server rightly refuses the replayed upload keys with 409.
    session = f"s-demo-{uuid.uuid4().hex[:12]}"
    samples = len(pcm) // 2
    status, created = _request(
        "POST",
        "/v1/jobs",
        alice,
        json.dumps(_job_request(session, pcm, sample_rate)).encode(),
        idempotency_key=f"{session}-create",
    )
    _check("job accepted", status == 202, f"status {status}")
    job_id = created.get("jobId", "")
    _check("job id issued", bool(job_id), job_id)

    status, _ = _request(
        "PUT",
        f"/v1/jobs/{job_id}/chunks/track-1/0-{samples - 1}",
        alice,
        pcm,
        content_type="application/octet-stream",
        idempotency_key=f"1/{session}/track-1/0/{samples - 1}",
        extra_headers={
            "X-Yap-Content-SHA256": sha256(pcm).hexdigest(),
            "X-Yap-Audio-Codec": "pcm_s16le",
            "X-Yap-Sample-Rate-Hz": str(sample_rate),
            "X-Yap-Channels": "1",
        },
    )
    _check("audio uploaded byte-for-byte (hash-checked by the server)", status == 201, f"status {status}")

    request_body = _job_request(session, pcm, sample_rate)
    status, committed = _request(
        "POST",
        f"/v1/jobs/{job_id}/commit",
        alice,
        json.dumps(
            {"captureManifest": request_body["captureManifest"], "chunkCount": 1}
        ).encode(),
        idempotency_key=f"{session}-commit",
    )
    _check("commit accepted", status == 202, f"status {status} {committed}")

    deadline = time.monotonic() + 30
    outcome: dict = {}
    while time.monotonic() < deadline:
        status, outcome = _request("GET", f"/v1/jobs/{job_id}", alice)
        if status == 200 and outcome.get("status") not in {"accepted", "processing"}:
            break
        time.sleep(0.5)
    print(f"  server outcome for the job: {outcome.get('status')!r}")

    status, result = _request("GET", f"/v1/jobs/{job_id}/result", alice)
    transcript = result.get("transcript") if status == 200 else None
    if transcript:
        print(f"  transcript: {json.dumps(transcript)[:200]}")
    else:
        print(f"  no transcript (status {status}) — expected against the no-ASR demo server")

    print("\nbob must not see alice's job:")
    status, _ = _request("GET", f"/v1/jobs/{job_id}", bob)
    _check("GET refused", status in {403, 404}, f"status {status}")
    status, _ = _request("GET", f"/v1/jobs/{job_id}/result", bob)
    _check("result refused", status in {403, 404}, f"status {status}")
    status, _ = _request("DELETE", f"/v1/jobs/{job_id}", bob)
    _check("DELETE refused", status in {403, 404}, f"status {status}")

    print("\nno token, same URL:")
    status, _ = _request("GET", f"/v1/jobs/{job_id}", None)
    _check("anonymous refused", status == 401, f"status {status}")

    print("\nalice still owns her job:")
    status, mine = _request("GET", f"/v1/jobs/{job_id}", alice)
    _check(
        "alice sees it after bob's refusals",
        status == 200 and mine.get("jobId") == job_id,
        f"status {status}",
    )

    if _FAILURES:
        print(f"\n{len(_FAILURES)} FAILED: {', '.join(_FAILURES)}")
        raise SystemExit(1)
    print("\nAll ownership and authentication assertions held.")


if __name__ == "__main__":
    main()
