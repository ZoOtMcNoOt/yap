from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping

from yap_server.auth.principal import PrincipalKey


_SCOPES = {"organization": 0, "team": 1, "personal": 2}
_SENSITIVITY = {"public", "internal", "confidential", "restricted"}
_LOCALE = re.compile(r"^(?:und|[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?)$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class TerminologyRecord:
    record_id: str
    tenant_id: str
    scope: str
    owner_id: str
    locale: str
    canonical_form: str
    variants: tuple[str, ...]
    sensitivity: str
    version: int
    deleted: bool
    audit_revision: str
    changed_at: str


@dataclass(frozen=True, slots=True)
class TerminologySnapshot:
    tenant_id: str
    subject_id: str
    locale: str
    source_revision: str
    team_ids: tuple[str, ...]
    entries: tuple[TerminologyRecord, ...]
    variant_map: Mapping[str, str]
    snapshot_sha256: str


def freeze_terminology_snapshot(
    records: tuple[TerminologyRecord, ...],
    *,
    principal: PrincipalKey,
    team_ids: tuple[str, ...],
    locale: str,
    source_revision: str,
) -> TerminologySnapshot:
    """Resolve visible terminology once for a job without consulting a model."""

    if not isinstance(records, tuple) or not isinstance(team_ids, tuple):
        raise ValueError("terminology snapshot inputs must be immutable")
    _locale(locale)
    _identity(source_revision, "terminology source revision")
    teams = tuple(sorted({_identity(item, "team ID") for item in team_ids}))
    if len(teams) != len(team_ids):
        raise ValueError("terminology team IDs are duplicated")
    latest = _latest_records(records, principal.tenant_id)
    applicable = tuple(
        record
        for record in latest
        if not record.deleted
        and record.locale in {locale, "und"}
        and _owned_by(record, principal, teams)
    )
    winners: dict[str, tuple[int, str, str]] = {}
    for record in applicable:
        precedence = _SCOPES[record.scope]
        for variant in record.variants:
            key = variant.casefold()
            existing = winners.get(key)
            candidate = (precedence, record.record_id, record.canonical_form)
            if existing is not None and existing[0] == precedence:
                if existing[2] != record.canonical_form:
                    raise ValueError("conflicting terminology has equal precedence")
                continue
            if existing is None or precedence > existing[0]:
                winners[key] = candidate
    ordered_entries = tuple(sorted(applicable, key=lambda item: item.record_id))
    variant_map = {key: value[2] for key, value in sorted(winners.items())}
    identity = _snapshot_identity(
        tenant_id=principal.tenant_id,
        subject_id=principal.subject_id,
        locale=locale,
        source_revision=source_revision,
        team_ids=teams,
        entries=ordered_entries,
        variant_map=variant_map,
    )
    snapshot_sha256 = hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return TerminologySnapshot(
        tenant_id=principal.tenant_id,
        subject_id=principal.subject_id,
        locale=locale,
        source_revision=source_revision,
        team_ids=teams,
        entries=ordered_entries,
        variant_map=MappingProxyType(variant_map),
        snapshot_sha256=snapshot_sha256,
    )


def terminology_snapshot_payload(snapshot: TerminologySnapshot) -> dict[str, object]:
    identity = _snapshot_identity(
        tenant_id=snapshot.tenant_id,
        subject_id=snapshot.subject_id,
        locale=snapshot.locale,
        source_revision=snapshot.source_revision,
        team_ids=snapshot.team_ids,
        entries=snapshot.entries,
        variant_map=dict(snapshot.variant_map),
    )
    return {**identity, "snapshotSha256": snapshot.snapshot_sha256}


def restore_terminology_snapshot(value: object) -> TerminologySnapshot:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "tenantId",
        "subjectId",
        "locale",
        "sourceRevision",
        "teamIds",
        "entries",
        "variantMap",
        "snapshotSha256",
    }:
        raise ValueError("terminology snapshot payload differs from the contract")
    if value["schemaVersion"] != 1 or not isinstance(value["entries"], list):
        raise ValueError("terminology snapshot payload is invalid")
    records = tuple(_record_from_identity(item) for item in value["entries"])
    team_ids = value["teamIds"]
    if not isinstance(team_ids, list) or not all(
        isinstance(item, str) for item in team_ids
    ):
        raise ValueError("terminology snapshot team IDs are invalid")
    snapshot = freeze_terminology_snapshot(
        records,
        principal=PrincipalKey(value["tenantId"], value["subjectId"]),
        team_ids=tuple(team_ids),
        locale=value["locale"],
        source_revision=value["sourceRevision"],
    )
    if (
        snapshot.snapshot_sha256 != value["snapshotSha256"]
        or dict(snapshot.variant_map) != value["variantMap"]
    ):
        raise ValueError("terminology snapshot payload identity is invalid")
    return snapshot


def terminology_record_identity(record: TerminologyRecord) -> dict[str, object]:
    return {
        "recordId": record.record_id,
        "tenantId": record.tenant_id,
        "scope": record.scope,
        "ownerId": record.owner_id,
        "locale": record.locale,
        "canonicalForm": record.canonical_form,
        "variants": list(record.variants),
        "sensitivity": record.sensitivity,
        "version": record.version,
        "auditRevision": record.audit_revision,
        "changedAt": record.changed_at,
    }


def _snapshot_identity(
    *,
    tenant_id: str,
    subject_id: str,
    locale: str,
    source_revision: str,
    team_ids: tuple[str, ...],
    entries: tuple[TerminologyRecord, ...],
    variant_map: dict[str, str],
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "tenantId": tenant_id,
        "subjectId": subject_id,
        "locale": locale,
        "sourceRevision": source_revision,
        "teamIds": list(team_ids),
        "entries": [terminology_record_identity(item) for item in entries],
        "variantMap": variant_map,
    }


def _record_from_identity(value: object) -> TerminologyRecord:
    if not isinstance(value, dict) or set(value) != {
        "recordId",
        "tenantId",
        "scope",
        "ownerId",
        "locale",
        "canonicalForm",
        "variants",
        "sensitivity",
        "version",
        "auditRevision",
        "changedAt",
    }:
        raise ValueError("terminology snapshot entry differs from the contract")
    variants = value["variants"]
    if not isinstance(variants, list):
        raise ValueError("terminology snapshot variants are invalid")
    return TerminologyRecord(
        record_id=value["recordId"],
        tenant_id=value["tenantId"],
        scope=value["scope"],
        owner_id=value["ownerId"],
        locale=value["locale"],
        canonical_form=value["canonicalForm"],
        variants=tuple(variants),
        sensitivity=value["sensitivity"],
        version=value["version"],
        deleted=False,
        audit_revision=value["auditRevision"],
        changed_at=value["changedAt"],
    )


def validate_terminology_record(record: TerminologyRecord, *, tenant_id: str) -> None:
    _validate_record(record, tenant_id)


def _latest_records(
    records: tuple[TerminologyRecord, ...], tenant_id: str
) -> tuple[TerminologyRecord, ...]:
    latest: dict[str, TerminologyRecord] = {}
    seen_versions: set[tuple[str, int]] = set()
    for record in records:
        _validate_record(record, tenant_id)
        version_key = (record.record_id, record.version)
        if version_key in seen_versions:
            raise ValueError("terminology record version is duplicated")
        seen_versions.add(version_key)
        current = latest.get(record.record_id)
        if current is None or record.version > current.version:
            latest[record.record_id] = record
    return tuple(latest[key] for key in sorted(latest))


def _validate_record(record: TerminologyRecord, tenant_id: str) -> None:
    _identity(record.record_id, "terminology record ID")
    if record.tenant_id != tenant_id:
        raise ValueError("terminology record crosses tenants")
    if record.scope not in _SCOPES:
        raise ValueError("terminology scope is invalid")
    _identity(record.owner_id, "terminology owner ID")
    _locale(record.locale)
    _text(record.canonical_form, "canonical terminology form")
    if (
        not isinstance(record.variants, tuple)
        or not record.variants
        or len(record.variants) > 64
    ):
        raise ValueError("terminology variants are invalid")
    variants = tuple(_text(item, "terminology variant") for item in record.variants)
    if len({item.casefold() for item in variants}) != len(variants):
        raise ValueError("terminology variants are duplicated")
    if record.sensitivity not in _SENSITIVITY:
        raise ValueError("terminology sensitivity is invalid")
    if isinstance(record.version, bool) or not 1 <= record.version <= 2**63 - 1:
        raise ValueError("terminology version is invalid")
    if not isinstance(record.deleted, bool):
        raise ValueError("terminology deletion state is invalid")
    _identity(record.audit_revision, "terminology audit revision")
    try:
        changed_at = datetime.fromisoformat(record.changed_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("terminology change timestamp is invalid") from error
    if changed_at.tzinfo is None:
        raise ValueError("terminology change timestamp is invalid")
    if record.scope == "organization" and record.owner_id != tenant_id:
        raise ValueError("organization terminology owner is invalid")


def _owned_by(
    record: TerminologyRecord, principal: PrincipalKey, team_ids: tuple[str, ...]
) -> bool:
    return (
        (record.scope == "organization" and record.owner_id == principal.tenant_id)
        or (record.scope == "team" and record.owner_id in team_ids)
        or (record.scope == "personal" and record.owner_id == principal.subject_id)
    )


def _identity(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


def _locale(value: object) -> str:
    if not isinstance(value, str) or not _LOCALE.fullmatch(value):
        raise ValueError("terminology locale is invalid")
    return value


def _text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or value.strip() != value
        or any(character in value for character in "\r\n\0")
    ):
        raise ValueError(f"{field} is invalid")
    return value


__all__ = [
    "TerminologyRecord",
    "TerminologySnapshot",
    "freeze_terminology_snapshot",
    "restore_terminology_snapshot",
    "terminology_record_identity",
    "terminology_snapshot_payload",
    "validate_terminology_record",
]
