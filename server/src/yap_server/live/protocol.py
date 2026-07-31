from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import re
import threading
import time
from typing import Callable, Literal, Mapping
from uuid import uuid4

from yap_server.auth import AuthenticatedPrincipal, PrincipalKey


MAX_JSON_MESSAGE_BYTES = 64 * 1024
MAX_BINARY_MESSAGE_BYTES = 256 * 1024
MAX_TRACKS_PER_SESSION = 8
MAX_EVENTS_PER_SESSION = 512
MAX_REPLAY_KEYS_PER_SESSION = 128
MAX_ACTIVE_SESSIONS = 32
MAX_ACTIVE_SESSIONS_PER_PRINCIPAL = 4
MAX_TERMINAL_TOMBSTONES = 64
RECONNECT_RETENTION_SECONDS = 30.0

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TRACK_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BCP47_HINT = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
_GAP_CAUSES = frozenset(
    {
        "callback_pool_exhausted",
        "oversized_callback",
        "device_discontinuity",
        "sink_unavailable",
    }
)


class LiveProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PendingAudioChunk:
    event: dict[str, object]
    event_digest: str
    replay_key: tuple[object, ...]
    content_sha256: str
    byte_length: int


@dataclass(frozen=True, slots=True)
class ProtocolResult:
    outbound: tuple[dict[str, object], ...] = ()
    close: bool = False


@dataclass(slots=True)
class _LiveSession:
    owner: PrincipalKey
    start_digest: str
    tracks: frozenset[str]
    active_connection_id: str | None
    last_client_sequence: int = 0
    next_server_sequence: int = 1
    last_audio_event_sequence: int | None = None
    disconnected_at: float | None = None
    event_digests: dict[int, str] = field(default_factory=dict)
    replay_contents: dict[tuple[object, ...], tuple[str, int]] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class _TerminalTombstone:
    owner: PrincipalKey
    start_digest: str
    final_event: dict[str, object]
    expires_at: float


class LiveSessionRegistry:
    """Bounded in-memory reconnect authority without retaining audio bytes."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._lock = threading.RLock()
        self._sessions: dict[str, _LiveSession] = {}
        self._tombstones: dict[str, _TerminalTombstone] = {}

    @property
    def active_session_count(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._sessions)

    @property
    def terminal_tombstone_count(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._tombstones)

    def start(
        self,
        principal: AuthenticatedPrincipal,
        connection_id: str,
        event: dict[str, object],
    ) -> ProtocolResult:
        session_id, tracks = _validate_session_start(event)
        event_digest = _event_digest(event)
        with self._lock:
            self._prune_locked()
            tombstone = self._tombstones.get(session_id)
            if tombstone is not None:
                self._require_owner(tombstone.owner, principal.key)
                if tombstone.start_digest != event_digest:
                    raise LiveProtocolError(
                        "CONFLICTING_SESSION_REPLAY",
                        "The session start replay conflicts with prior state.",
                    )
                return ProtocolResult((dict(tombstone.final_event),), close=True)

            session = self._sessions.get(session_id)
            if session is not None:
                self._require_owner(session.owner, principal.key)
                if session.start_digest != event_digest:
                    raise LiveProtocolError(
                        "CONFLICTING_SESSION_REPLAY",
                        "The session start replay conflicts with prior state.",
                    )
                if (
                    session.active_connection_id is not None
                    and session.active_connection_id != connection_id
                ):
                    raise LiveProtocolError(
                        "SESSION_ALREADY_CONNECTED",
                        "The live session already has an active connection.",
                    )
                session.active_connection_id = connection_id
                session.disconnected_at = None
                return ProtocolResult((self._accepted_event(session_id, session),))

            if len(self._sessions) >= MAX_ACTIVE_SESSIONS:
                raise LiveProtocolError(
                    "LIVE_CAPACITY_EXCEEDED",
                    "Live session capacity is temporarily unavailable.",
                )
            owned = sum(
                existing.owner == principal.key for existing in self._sessions.values()
            )
            if owned >= MAX_ACTIVE_SESSIONS_PER_PRINCIPAL:
                raise LiveProtocolError(
                    "PRINCIPAL_LIVE_CAPACITY_EXCEEDED",
                    "Live session capacity is temporarily unavailable.",
                )
            session = _LiveSession(
                owner=principal.key,
                start_digest=event_digest,
                tracks=tracks,
                active_connection_id=connection_id,
                event_digests={0: event_digest},
            )
            self._sessions[session_id] = session
            return ProtocolResult((self._accepted_event(session_id, session),))

    def prepare_audio_chunk(
        self,
        principal: AuthenticatedPrincipal,
        connection_id: str,
        event: dict[str, object],
    ) -> PendingAudioChunk:
        session_id = _event_session_id(event)
        replay_key, content_sha256, byte_length = _validate_audio_chunk(event)
        event_digest = _event_digest(event)
        with self._lock:
            session = self._owned_active_session(
                session_id,
                principal.key,
                connection_id,
            )
            if str(replay_key[1]) not in session.tracks:
                raise LiveProtocolError(
                    "TRACK_NOT_IN_SESSION",
                    "The audio chunk track isn't part of this session.",
                )
            classification = self._classify_event_locked(
                session,
                event,
                event_digest,
            )
            existing = session.replay_contents.get(replay_key)
            if existing is not None and existing != (content_sha256, byte_length):
                raise LiveProtocolError(
                    "CONFLICTING_CHUNK_REPLAY",
                    "The replay key was reused with different content.",
                )
            if (
                classification == "new"
                and existing is None
                and len(session.replay_contents) >= MAX_REPLAY_KEYS_PER_SESSION
            ):
                raise LiveProtocolError(
                    "SESSION_REPLAY_LIMIT",
                    "The live session replay ledger reached its bounded limit.",
                )
        return PendingAudioChunk(
            event,
            event_digest,
            replay_key,
            content_sha256,
            byte_length,
        )

    def commit_audio_chunk(
        self,
        principal: AuthenticatedPrincipal,
        connection_id: str,
        pending: PendingAudioChunk,
        payload: bytes,
    ) -> None:
        if len(payload) != pending.byte_length:
            raise LiveProtocolError(
                "CHUNK_LENGTH_MISMATCH",
                "The binary audio length doesn't match its declared identity.",
            )
        if hashlib.sha256(payload).hexdigest() != pending.content_sha256:
            raise LiveProtocolError(
                "CHUNK_HASH_MISMATCH",
                "The binary audio hash doesn't match its declared identity.",
            )
        session_id = _event_session_id(pending.event)
        with self._lock:
            session = self._owned_active_session(
                session_id,
                principal.key,
                connection_id,
            )
            classification = self._classify_event_locked(
                session,
                pending.event,
                pending.event_digest,
            )
            existing = session.replay_contents.get(pending.replay_key)
            if existing is not None and existing != (
                pending.content_sha256,
                pending.byte_length,
            ):
                raise LiveProtocolError(
                    "CONFLICTING_CHUNK_REPLAY",
                    "The replay key was reused with different content.",
                )
            if classification == "new":
                self._apply_event_locked(
                    session,
                    pending.event,
                    pending.event_digest,
                )
                if existing is None:
                    session.replay_contents[pending.replay_key] = (
                        pending.content_sha256,
                        pending.byte_length,
                    )
                    session.last_audio_event_sequence = _event_sequence(pending.event)

    def apply_gap(
        self,
        principal: AuthenticatedPrincipal,
        connection_id: str,
        event: dict[str, object],
    ) -> None:
        session_id, track_id = _validate_audio_gap(event)
        event_digest = _event_digest(event)
        with self._lock:
            session = self._owned_active_session(
                session_id,
                principal.key,
                connection_id,
            )
            if track_id not in session.tracks:
                raise LiveProtocolError(
                    "TRACK_NOT_IN_SESSION",
                    "The audio gap track isn't part of this session.",
                )
            if self._classify_event_locked(session, event, event_digest) == "new":
                self._apply_event_locked(session, event, event_digest)
                session.last_audio_event_sequence = _event_sequence(event)

    def ping(
        self,
        principal: AuthenticatedPrincipal,
        connection_id: str,
        event: dict[str, object],
    ) -> ProtocolResult:
        session_id, nonce = _validate_ping(event)
        event_digest = _event_digest(event)
        with self._lock:
            session = self._owned_active_session(
                session_id,
                principal.key,
                connection_id,
            )
            if self._classify_event_locked(session, event, event_digest) != "new":
                return ProtocolResult()
            self._apply_event_locked(session, event, event_digest)
            return ProtocolResult(
                (
                    {
                        "schemaVersion": 1,
                        "sessionId": session_id,
                        "eventSequence": self._server_sequence_locked(session),
                        "eventType": "pong",
                        "nonce": nonce,
                    },
                )
            )

    def cancel(
        self,
        principal: AuthenticatedPrincipal,
        connection_id: str,
        event: dict[str, object],
    ) -> ProtocolResult:
        session_id = _validate_cancel(event)
        event_digest = _event_digest(event)
        with self._lock:
            session = self._owned_active_session(
                session_id,
                principal.key,
                connection_id,
            )
            classification = self._classify_event_locked(
                session,
                event,
                event_digest,
            )
            if classification != "new":
                return ProtocolResult()
            self._apply_event_locked(session, event, event_digest)
            final_event = self._terminalize_locked(session_id, session, "cancelled")
            return ProtocolResult((final_event,), close=True)

    def finish(
        self,
        principal: AuthenticatedPrincipal,
        connection_id: str,
        event: dict[str, object],
        *,
        request_id: str,
    ) -> ProtocolResult:
        session_id, last_audio_sequence = _validate_finish(event)
        event_digest = _event_digest(event)
        with self._lock:
            session = self._owned_active_session(
                session_id,
                principal.key,
                connection_id,
            )
            classification = self._classify_event_locked(
                session,
                event,
                event_digest,
            )
            if classification != "new":
                return ProtocolResult()
            if last_audio_sequence != (session.last_audio_event_sequence or 0):
                raise LiveProtocolError(
                    "LAST_AUDIO_SEQUENCE_MISMATCH",
                    "The finish event doesn't match the accepted audio timeline.",
                )
            self._apply_event_locked(session, event, event_digest)
            error_event = {
                "schemaVersion": 1,
                "sessionId": session_id,
                "eventSequence": self._server_sequence_locked(session),
                "eventType": "session.error",
                "error": {
                    "code": "LIVE_ASR_UNAVAILABLE",
                    "message": (
                        "Authenticated live transport is available, but live ASR "
                        "inference isn't implemented."
                    ),
                    "retryable": False,
                    "requestId": request_id,
                },
                "final": True,
            }
            final_event = self._terminalize_locked(session_id, session, "failed")
            return ProtocolResult((error_event, final_event), close=True)

    def error_event(
        self,
        principal: AuthenticatedPrincipal,
        connection_id: str,
        *,
        code: str,
        message: str,
        request_id: str,
    ) -> dict[str, object] | None:
        with self._lock:
            for session_id, session in self._sessions.items():
                if (
                    session.owner == principal.key
                    and session.active_connection_id == connection_id
                ):
                    return {
                        "schemaVersion": 1,
                        "sessionId": session_id,
                        "eventSequence": self._server_sequence_locked(session),
                        "eventType": "session.error",
                        "error": {
                            "code": code,
                            "message": message,
                            "retryable": False,
                            "requestId": request_id,
                        },
                        "final": True,
                    }
        return None

    def disconnect(self, connection_id: str) -> None:
        with self._lock:
            now = self._monotonic()
            for session in self._sessions.values():
                if session.active_connection_id == connection_id:
                    session.active_connection_id = None
                    session.disconnected_at = now

    def abort(self, connection_id: str) -> None:
        """Discard a protocol-invalid session instead of making it resumable."""
        with self._lock:
            aborted = [
                session_id
                for session_id, session in self._sessions.items()
                if session.active_connection_id == connection_id
            ]
            for session_id in aborted:
                self._sessions.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._tombstones.clear()

    def _accepted_event(
        self,
        session_id: str,
        session: _LiveSession,
    ) -> dict[str, object]:
        sequence = (
            0
            if session.next_server_sequence == 1
            else self._server_sequence_locked(session)
        )
        return {
            "schemaVersion": 1,
            "sessionId": session_id,
            "eventSequence": sequence,
            "eventType": "session.accepted",
            "acceptedAtUtc": self._utc_now()
            .astimezone(UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }

    @staticmethod
    def _require_owner(actual: PrincipalKey, expected: PrincipalKey) -> None:
        if actual != expected:
            raise LiveProtocolError(
                "LIVE_SESSION_NOT_FOUND",
                "The live session wasn't found.",
            )

    def _owned_active_session(
        self,
        session_id: str,
        owner: PrincipalKey,
        connection_id: str,
    ) -> _LiveSession:
        session = self._sessions.get(session_id)
        if (
            session is None
            or session.owner != owner
            or session.active_connection_id != connection_id
        ):
            raise LiveProtocolError(
                "LIVE_SESSION_NOT_FOUND",
                "The live session wasn't found.",
            )
        return session

    @staticmethod
    def _classify_event_locked(
        session: _LiveSession,
        event: Mapping[str, object],
        event_digest: str,
    ) -> Literal["new", "replay", "stale"]:
        sequence = _event_sequence(event)
        existing = session.event_digests.get(sequence)
        if existing is not None:
            if existing == event_digest:
                return "replay"
            raise LiveProtocolError(
                "CONFLICTING_EVENT_REPLAY",
                "The event sequence was replayed with different content.",
            )
        if sequence < session.last_client_sequence:
            return "stale"
        if len(session.event_digests) >= MAX_EVENTS_PER_SESSION:
            raise LiveProtocolError(
                "SESSION_EVENT_LIMIT",
                "The live session reached its bounded event limit.",
            )
        return "new"

    @staticmethod
    def _apply_event_locked(
        session: _LiveSession,
        event: Mapping[str, object],
        event_digest: str,
    ) -> None:
        sequence = _event_sequence(event)
        session.event_digests[sequence] = event_digest
        session.last_client_sequence = sequence

    @staticmethod
    def _server_sequence_locked(session: _LiveSession) -> int:
        sequence = session.next_server_sequence
        session.next_server_sequence += 1
        return sequence

    def _terminalize_locked(
        self,
        session_id: str,
        session: _LiveSession,
        status: Literal["cancelled", "failed"],
    ) -> dict[str, object]:
        final_event = {
            "schemaVersion": 1,
            "sessionId": session_id,
            "eventSequence": self._server_sequence_locked(session),
            "eventType": "session.finished",
            "finalEventId": f"final-{uuid4().hex}",
            "status": status,
        }
        self._sessions.pop(session_id, None)
        if len(self._tombstones) >= MAX_TERMINAL_TOMBSTONES:
            oldest = min(
                self._tombstones,
                key=lambda key: self._tombstones[key].expires_at,
            )
            self._tombstones.pop(oldest, None)
        self._tombstones[session_id] = _TerminalTombstone(
            session.owner,
            session.start_digest,
            dict(final_event),
            self._monotonic() + RECONNECT_RETENTION_SECONDS,
        )
        return final_event

    def _prune_locked(self) -> None:
        now = self._monotonic()
        expired_sessions = [
            session_id
            for session_id, session in self._sessions.items()
            if session.active_connection_id is None
            and session.disconnected_at is not None
            and now - session.disconnected_at >= RECONNECT_RETENTION_SECONDS
        ]
        for session_id in expired_sessions:
            self._sessions.pop(session_id, None)
        expired_tombstones = [
            session_id
            for session_id, tombstone in self._tombstones.items()
            if tombstone.expires_at <= now
        ]
        for session_id in expired_tombstones:
            self._tombstones.pop(session_id, None)


class LiveConnectionProtocol:
    def __init__(
        self,
        registry: LiveSessionRegistry,
        principal: AuthenticatedPrincipal,
        connection_id: str,
    ) -> None:
        self._registry = registry
        self._principal = principal
        self._connection_id = connection_id
        self._session_id: str | None = None
        self._pending: PendingAudioChunk | None = None

    def receive(self, message: str | bytes, *, request_id: str) -> ProtocolResult:
        if isinstance(message, bytes):
            return self._receive_binary(message)
        if self._pending is not None:
            raise LiveProtocolError(
                "BINARY_AUDIO_REQUIRED",
                "Binary audio must immediately follow its chunk declaration.",
            )
        event = _decode_event(message)
        event_type = event.get("eventType")
        if self._session_id is None:
            if event_type != "session.start":
                raise LiveProtocolError(
                    "SESSION_START_REQUIRED",
                    "The first live event must start a session.",
                )
            result = self._registry.start(
                self._principal,
                self._connection_id,
                event,
            )
            self._session_id = _event_session_id(event)
            return result
        if _event_session_id(event) != self._session_id:
            raise LiveProtocolError(
                "SESSION_ID_MISMATCH",
                "The event session doesn't match the connection session.",
            )
        if event_type == "audio.chunk":
            self._pending = self._registry.prepare_audio_chunk(
                self._principal,
                self._connection_id,
                event,
            )
            return ProtocolResult()
        if event_type == "audio.gap":
            self._registry.apply_gap(
                self._principal,
                self._connection_id,
                event,
            )
            return ProtocolResult()
        if event_type == "ping":
            return self._registry.ping(
                self._principal,
                self._connection_id,
                event,
            )
        if event_type == "session.cancel":
            return self._registry.cancel(
                self._principal,
                self._connection_id,
                event,
            )
        if event_type == "session.finish":
            return self._registry.finish(
                self._principal,
                self._connection_id,
                event,
                request_id=request_id,
            )
        raise LiveProtocolError(
            "CLIENT_EVENT_NOT_ALLOWED",
            "The client event type isn't allowed.",
        )

    def error_event(
        self,
        error: LiveProtocolError,
        *,
        request_id: str,
    ) -> dict[str, object] | None:
        return self._registry.error_event(
            self._principal,
            self._connection_id,
            code=error.code,
            message=error.message,
            request_id=request_id,
        )

    def disconnect(self) -> None:
        self._pending = None
        self._registry.disconnect(self._connection_id)

    def abort(self) -> None:
        self._pending = None
        self._registry.abort(self._connection_id)

    def _receive_binary(self, payload: bytes) -> ProtocolResult:
        pending = self._pending
        self._pending = None
        if pending is None:
            raise LiveProtocolError(
                "UNEXPECTED_BINARY_MESSAGE",
                "Binary audio requires a preceding chunk declaration.",
            )
        if len(payload) > MAX_BINARY_MESSAGE_BYTES:
            raise LiveProtocolError(
                "BINARY_MESSAGE_TOO_LARGE",
                "The binary audio message exceeds the bounded limit.",
            )
        self._registry.commit_audio_chunk(
            self._principal,
            self._connection_id,
            pending,
            payload,
        )
        return ProtocolResult()


def _decode_event(message: str) -> dict[str, object]:
    encoded = message.encode("utf-8")
    if len(encoded) > MAX_JSON_MESSAGE_BYTES:
        raise LiveProtocolError(
            "JSON_MESSAGE_TOO_LARGE",
            "The live event exceeds the bounded JSON limit.",
        )

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LiveProtocolError(
                    "INVALID_LIVE_EVENT",
                    "The live event contains a duplicate property.",
                )
            result[key] = value
        return result

    try:
        value = json.loads(message, object_pairs_hook=unique_object)
    except LiveProtocolError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LiveProtocolError(
            "INVALID_LIVE_EVENT",
            "The live event isn't valid JSON.",
        ) from error
    if not isinstance(value, dict):
        raise LiveProtocolError(
            "INVALID_LIVE_EVENT",
            "The live event must be a JSON object.",
        )
    _validate_envelope(value)
    return value


def _validate_envelope(event: Mapping[str, object]) -> None:
    if event.get("schemaVersion") != 1:
        raise LiveProtocolError(
            "UNSUPPORTED_LIVE_SCHEMA",
            "The live event schema version isn't supported.",
        )
    _event_session_id(event)
    _event_sequence(event)
    event_type = event.get("eventType")
    if not isinstance(event_type, str) or len(event_type) > 64:
        raise LiveProtocolError(
            "INVALID_LIVE_EVENT",
            "The live event type is invalid.",
        )


def _validate_session_start(
    event: Mapping[str, object],
) -> tuple[str, frozenset[str]]:
    _require_exact_keys(
        event,
        {
            "schemaVersion",
            "sessionId",
            "eventSequence",
            "eventType",
            "metadata",
            "tracks",
            "route",
        },
    )
    if event.get("eventType") != "session.start" or _event_sequence(event) != 0:
        raise LiveProtocolError(
            "INVALID_SESSION_START",
            "A new live session must start at event sequence zero.",
        )
    if event.get("route") != "server_live":
        raise LiveProtocolError(
            "INVALID_SESSION_START",
            "The live session route is invalid.",
        )
    session_id = _event_session_id(event)
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        raise LiveProtocolError(
            "INVALID_SESSION_START",
            "The live session metadata is invalid.",
        )
    metadata_keys = {
        "sessionId",
        "mode",
        "origin",
        "triggerMode",
        "startedAtUtc",
        "utcOffsetMinutesAtStart",
        "localeHintBcp47",
        "countryCodeHint",
        "preferredLanguagesBcp47",
        "appVersion",
        "platform",
        "privacyPolicyVersion",
        "retentionExpiresAtUtc",
    }
    _require_exact_keys(metadata, metadata_keys)
    locale_hint = metadata.get("localeHintBcp47")
    country_hint = metadata.get("countryCodeHint")
    languages = metadata.get("preferredLanguagesBcp47")
    utc_offset = metadata.get("utcOffsetMinutesAtStart")
    if (
        metadata.get("sessionId") != session_id
        or metadata.get("mode") not in {"dictation", "meeting"}
        or metadata.get("origin") != "live_capture"
        or metadata.get("triggerMode") not in {"push_to_talk", "toggle"}
        or not _utc_datetime(metadata.get("startedAtUtc"))
        or (
            utc_offset is not None
            and (not _signed_int(utc_offset) or not -840 <= utc_offset <= 840)
        )
        or not _optional_pattern(locale_hint, _BCP47_HINT, maximum=35)
        or not _optional_pattern(country_hint, _COUNTRY_CODE, maximum=2)
        or not isinstance(languages, list)
        or len(languages) > 8
        or any(
            not _bounded_pattern(language, _BCP47_HINT, maximum=35)
            for language in languages
        )
        or not _bounded_text(metadata.get("appVersion"), maximum=64)
        or not _bounded_text(metadata.get("platform"), maximum=64)
        or not _bounded_text(metadata.get("privacyPolicyVersion"), maximum=128)
        or (
            metadata.get("retentionExpiresAtUtc") is not None
            and not _utc_datetime(metadata.get("retentionExpiresAtUtc"))
        )
    ):
        raise LiveProtocolError(
            "INVALID_SESSION_START",
            "The live session metadata is invalid.",
        )
    tracks = event.get("tracks")
    if (
        not isinstance(tracks, list)
        or not tracks
        or len(tracks) > MAX_TRACKS_PER_SESSION
    ):
        raise LiveProtocolError(
            "INVALID_SESSION_TRACKS",
            "The live session tracks are invalid.",
        )
    track_ids: list[str] = []
    for track in tracks:
        if not isinstance(track, dict):
            raise LiveProtocolError(
                "INVALID_SESSION_TRACKS",
                "The live session track is invalid.",
            )
        _require_exact_keys(
            track,
            {
                "trackId",
                "source",
                "deviceId",
                "originalSampleRateHz",
                "originalChannels",
            },
        )
        track_id = track.get("trackId")
        source = track.get("source")
        device_id = track.get("deviceId")
        original_channels = track.get("originalChannels")
        if (
            not isinstance(track_id, str)
            or _TRACK_IDENTIFIER.fullmatch(track_id) is None
            or not isinstance(source, dict)
            or set(source) != {"kind", "source"}
            or source.get("kind") != "captured"
            or source.get("source") not in {"microphone", "system_loopback"}
            or (device_id is not None and not _bounded_text(device_id, maximum=128))
            or not _positive_int(track.get("originalSampleRateHz"))
            or not _positive_int(original_channels)
            or original_channels > 64
        ):
            raise LiveProtocolError(
                "INVALID_SESSION_TRACKS",
                "The live session track identity or source is invalid.",
            )
        track_ids.append(track_id)
    if len(set(track_ids)) != len(track_ids):
        raise LiveProtocolError(
            "INVALID_SESSION_TRACKS",
            "The live session track identities must be unique.",
        )
    return session_id, frozenset(track_ids)


def _validate_audio_chunk(
    event: Mapping[str, object],
) -> tuple[tuple[object, ...], str, int]:
    _require_exact_keys(
        event,
        {
            "schemaVersion",
            "sessionId",
            "eventSequence",
            "eventType",
            "replayKey",
            "contentIdentity",
            "audioCodec",
            "sampleRateHz",
            "channels",
            "binaryFollows",
        },
    )
    if (
        event.get("eventType") != "audio.chunk"
        or event.get("audioCodec") != "pcm_s16le"
        or event.get("sampleRateHz") != 16_000
        or event.get("channels") != 1
        or event.get("binaryFollows") is not True
    ):
        raise LiveProtocolError(
            "INVALID_AUDIO_CHUNK",
            "The audio chunk encoding contract is invalid.",
        )
    session_id = _event_session_id(event)
    replay = event.get("replayKey")
    content = event.get("contentIdentity")
    if not isinstance(replay, dict) or not isinstance(content, dict):
        raise LiveProtocolError(
            "INVALID_AUDIO_CHUNK",
            "The audio chunk identity is invalid.",
        )
    _require_exact_keys(
        replay,
        {"schemaVersion", "sessionId", "trackId", "sequenceStart", "sequenceEnd"},
    )
    _require_exact_keys(content, {"sha256", "byteLength"})
    track_id = replay.get("trackId")
    sequence_start = replay.get("sequenceStart")
    sequence_end = replay.get("sequenceEnd")
    if (
        replay.get("schemaVersion") != 1
        or replay.get("sessionId") != session_id
        or not isinstance(track_id, str)
        or _TRACK_IDENTIFIER.fullmatch(track_id) is None
        or not _non_negative_int(sequence_start)
        or not _non_negative_int(sequence_end)
        or sequence_end < sequence_start
    ):
        raise LiveProtocolError(
            "INVALID_AUDIO_CHUNK",
            "The audio chunk replay identity is invalid.",
        )
    content_sha256 = content.get("sha256")
    byte_length = content.get("byteLength")
    if (
        not isinstance(content_sha256, str)
        or _SHA256.fullmatch(content_sha256) is None
        or not _positive_int(byte_length)
        or byte_length > MAX_BINARY_MESSAGE_BYTES
    ):
        raise LiveProtocolError(
            "INVALID_AUDIO_CHUNK",
            "The audio chunk content identity is invalid.",
        )
    return (
        (session_id, track_id, sequence_start, sequence_end),
        content_sha256,
        byte_length,
    )


def _validate_audio_gap(event: Mapping[str, object]) -> tuple[str, str]:
    _require_exact_keys(
        event,
        {"schemaVersion", "sessionId", "eventSequence", "eventType", "gap"},
    )
    if event.get("eventType") != "audio.gap":
        raise LiveProtocolError("INVALID_AUDIO_GAP", "The audio gap event is invalid.")
    session_id = _event_session_id(event)
    gap = event.get("gap")
    if not isinstance(gap, dict):
        raise LiveProtocolError("INVALID_AUDIO_GAP", "The audio gap is invalid.")
    _require_exact_keys(
        gap,
        {
            "sessionId",
            "trackId",
            "startMs",
            "durationMs",
            "sourcePositionFrames",
            "droppedFrames",
            "cause",
            "generation",
        },
    )
    track_id = gap.get("trackId")
    if (
        gap.get("sessionId") != session_id
        or not isinstance(track_id, str)
        or _TRACK_IDENTIFIER.fullmatch(track_id) is None
        or not _non_negative_int(gap.get("startMs"))
        or not _positive_int(gap.get("durationMs"))
        or not _non_negative_int(gap.get("sourcePositionFrames"))
        or not _positive_int(gap.get("droppedFrames"))
        or gap.get("cause") not in _GAP_CAUSES
        or not _non_negative_int(gap.get("generation"))
    ):
        raise LiveProtocolError("INVALID_AUDIO_GAP", "The audio gap is invalid.")
    return session_id, track_id


def _validate_ping(event: Mapping[str, object]) -> tuple[str, str]:
    _require_exact_keys(
        event,
        {"schemaVersion", "sessionId", "eventSequence", "eventType", "nonce"},
    )
    nonce = event.get("nonce")
    if (
        event.get("eventType") != "ping"
        or not isinstance(nonce, str)
        or not 1 <= len(nonce) <= 128
        or not nonce.isprintable()
    ):
        raise LiveProtocolError("INVALID_PING", "The live ping event is invalid.")
    return _event_session_id(event), nonce


def _validate_cancel(event: Mapping[str, object]) -> str:
    _require_exact_keys(
        event,
        {"schemaVersion", "sessionId", "eventSequence", "eventType", "reason"},
    )
    reason = event.get("reason")
    if (
        event.get("eventType") != "session.cancel"
        or not isinstance(reason, str)
        or not 1 <= len(reason) <= 512
        or not reason.isprintable()
    ):
        raise LiveProtocolError(
            "INVALID_SESSION_CANCEL",
            "The live session cancellation is invalid.",
        )
    return _event_session_id(event)


def _validate_finish(event: Mapping[str, object]) -> tuple[str, int]:
    _require_exact_keys(
        event,
        {
            "schemaVersion",
            "sessionId",
            "eventSequence",
            "eventType",
            "lastAudioEventSequence",
        },
    )
    last_audio_sequence = event.get("lastAudioEventSequence")
    if event.get("eventType") != "session.finish" or not _non_negative_int(
        last_audio_sequence
    ):
        raise LiveProtocolError(
            "INVALID_SESSION_FINISH",
            "The live session finish event is invalid.",
        )
    return _event_session_id(event), last_audio_sequence


def _event_session_id(event: Mapping[str, object]) -> str:
    session_id = event.get("sessionId")
    if not isinstance(session_id, str) or _IDENTIFIER.fullmatch(session_id) is None:
        raise LiveProtocolError(
            "INVALID_SESSION_ID",
            "The live session identity is invalid.",
        )
    return session_id


def _event_sequence(event: Mapping[str, object]) -> int:
    sequence = event.get("eventSequence")
    if not _non_negative_int(sequence):
        raise LiveProtocolError(
            "INVALID_EVENT_SEQUENCE",
            "The live event sequence is invalid.",
        )
    return sequence


def _event_digest(event: Mapping[str, object]) -> str:
    canonical = json.dumps(
        event,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
) -> None:
    if set(value) != expected:
        raise LiveProtocolError(
            "INVALID_LIVE_EVENT",
            "The live event properties don't match the protocol contract.",
        )


def _non_negative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _signed_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def _bounded_text(value: object, *, maximum: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= maximum and value.isprintable()


def _bounded_pattern(
    value: object,
    pattern: re.Pattern[str],
    *,
    maximum: int,
) -> bool:
    return (
        _bounded_text(value, maximum=maximum) and pattern.fullmatch(value) is not None
    )


def _optional_pattern(
    value: object,
    pattern: re.Pattern[str],
    *,
    maximum: int,
) -> bool:
    return value is None or _bounded_pattern(value, pattern, maximum=maximum)


def _utc_datetime(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


__all__ = [
    "LiveConnectionProtocol",
    "LiveProtocolError",
    "LiveSessionRegistry",
    "MAX_BINARY_MESSAGE_BYTES",
    "MAX_JSON_MESSAGE_BYTES",
    "ProtocolResult",
]
