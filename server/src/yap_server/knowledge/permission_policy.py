from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

from yap_server.auth.principal import PrincipalKey
from yap_server.private_artifact import read_bounded_regular_file

from .okf_source import (
    MAX_OKF_DOCUMENT_BYTES,
    load_unique_yaml,
    reject_linked_directories,
)


@dataclass(frozen=True, slots=True)
class CompiledPermission:
    path_prefix: str
    audience: tuple[PrincipalKey, ...]
    denials: tuple[PrincipalKey, ...]
    purposes: tuple[str, ...]
    classification: str
    permission_sha256: str


def compile_permissions(root: Path, tenant_id: str) -> tuple[CompiledPermission, ...]:
    permission_root = root / "permissions"
    try:
        metadata = permission_root.lstat()
    except OSError as error:
        raise ValueError("OKF permission directory is required") from error
    is_junction = getattr(permission_root, "is_junction", lambda: False)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or is_junction()
    ):
        raise ValueError("OKF permission directory must be a real directory")

    rules: list[CompiledPermission] = []
    prefixes: set[str] = set()
    for path in _permission_files(permission_root):
        body = read_bounded_regular_file(
            path,
            maximum_bytes=MAX_OKF_DOCUMENT_BYTES,
            field=f"OKF permission {path.relative_to(root).as_posix()}",
            containment_root=root,
        )
        value = load_unique_yaml(body, "OKF permission")
        if not isinstance(value, dict) or set(value) != {
            "path_prefix",
            "audience",
            "purposes",
            "classification",
            "denials",
        }:
            raise ValueError("OKF permission fields differ from the contract")
        prefix = _path_prefix(value["path_prefix"])
        if prefix in prefixes:
            raise ValueError("OKF permission path_prefix is duplicated")
        prefixes.add(prefix)
        audience = _principal_list(value["audience"], tenant_id, "audience")
        denials = _principal_list(value["denials"], tenant_id, "denials")
        purposes = _string_list(value["purposes"], "purposes")
        classification = value["classification"]
        if classification not in {"public", "internal", "confidential", "restricted"}:
            raise ValueError("OKF permission classification is invalid")
        canonical = _permission_identity_record(
            path_prefix=prefix,
            audience=audience,
            denials=denials,
            purposes=purposes,
            classification=classification,
        )
        rules.append(
            CompiledPermission(
                path_prefix=prefix,
                audience=audience,
                denials=denials,
                purposes=purposes,
                classification=classification,
                permission_sha256=_sha256(canonical),
            )
        )
    if not rules:
        raise ValueError("at least one OKF permission is required")
    return tuple(sorted(rules, key=lambda item: item.path_prefix))


def _permission_files(permission_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for directory, names, files in os.walk(
        permission_root, topdown=True, followlinks=False
    ):
        current = Path(directory)
        reject_linked_directories(current, names)
        paths.extend(
            current / name for name in files if name.casefold().endswith(".yml")
        )
        if len(paths) > 10_000:
            raise ValueError("OKF permission set exceeds its file limit")
    return tuple(sorted(paths))


def effective_permission(
    path: Path, permissions: tuple[CompiledPermission, ...]
) -> CompiledPermission:
    concept_id = path.with_suffix("").as_posix()
    matches = tuple(
        permission
        for permission in permissions
        if concept_id == permission.path_prefix.removesuffix("/")
        or concept_id.startswith(permission.path_prefix)
    )
    if not matches:
        raise ValueError(f"OKF concept {concept_id} has no compiled permission")
    return max(matches, key=lambda item: len(item.path_prefix))


def permission_record(value: CompiledPermission) -> dict[str, object]:
    return {
        "pathPrefix": value.path_prefix,
        "audience": [principal_record(item) for item in value.audience],
        "denials": [principal_record(item) for item in value.denials],
        "purposes": list(value.purposes),
        "classification": value.classification,
        "permissionSha256": value.permission_sha256,
    }


def compiled_permission_from_record(
    value: object, *, tenant_id: str
) -> CompiledPermission:
    """Load one persisted canonical permission record without trusting its digest."""

    if not isinstance(value, dict) or set(value) != {
        "pathPrefix",
        "audience",
        "denials",
        "purposes",
        "classification",
        "permissionSha256",
    }:
        raise ValueError("stored permission fields differ from the contract")
    permission = CompiledPermission(
        path_prefix=_path_prefix(value["pathPrefix"]),
        audience=_principal_records(value["audience"], tenant_id, "audience"),
        denials=_principal_records(value["denials"], tenant_id, "denials"),
        purposes=_string_list(value["purposes"], "purposes"),
        classification=value["classification"],
        permission_sha256=value["permissionSha256"],
    )
    validate_compiled_permission(permission, tenant_id=tenant_id)
    return permission


def compiled_permission_sha256(value: CompiledPermission) -> str:
    """Recompute one compiled permission's canonical immutable identity."""

    return _sha256(
        _permission_identity_record(
            path_prefix=value.path_prefix,
            audience=value.audience,
            denials=value.denials,
            purposes=value.purposes,
            classification=value.classification,
        )
    )


def validate_compiled_permission(
    value: CompiledPermission, *, tenant_id: str
) -> None:
    """Reject a compiled permission whose fields or digest are not canonical."""

    if not isinstance(value, CompiledPermission):
        raise TypeError("compiled permission has an invalid type")
    if _path_prefix(value.path_prefix) != value.path_prefix:
        raise ValueError("compiled permission path prefix is not canonical")
    for field, principals in (
        ("audience", value.audience),
        ("denials", value.denials),
    ):
        if not isinstance(principals, tuple):
            raise TypeError(f"compiled permission {field} must be immutable")
        ordered = tuple(
            sorted(set(principals), key=lambda item: (item.tenant_id, item.subject_id))
        )
        if ordered != principals or any(item.tenant_id != tenant_id for item in principals):
            raise ValueError(f"compiled permission {field} is not canonical")
    if not isinstance(value.purposes, tuple) or _string_list(
        list(value.purposes), "purposes"
    ) != value.purposes:
        raise ValueError("compiled permission purposes are not canonical")
    if value.classification not in {
        "public",
        "internal",
        "confidential",
        "restricted",
    }:
        raise ValueError("compiled permission classification is invalid")
    if compiled_permission_sha256(value) != value.permission_sha256:
        raise ValueError("compiled permission digest differs from its fields")


def _permission_identity_record(
    *,
    path_prefix: str,
    audience: tuple[PrincipalKey, ...],
    denials: tuple[PrincipalKey, ...],
    purposes: tuple[str, ...],
    classification: str,
) -> dict[str, object]:
    return {
        "pathPrefix": path_prefix,
        "audience": [principal_record(item) for item in audience],
        "denials": [principal_record(item) for item in denials],
        "purposes": list(purposes),
        "classification": classification,
    }


def principal_record(value: PrincipalKey) -> dict[str, str]:
    return {"tenantId": value.tenant_id, "subjectId": value.subject_id}


def _principal_records(
    value: object, tenant_id: str, field: str
) -> tuple[PrincipalKey, ...]:
    if not isinstance(value, list) or len(value) > 10_000:
        raise ValueError(f"stored permission {field} is invalid")
    principals: list[PrincipalKey] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"tenantId", "subjectId"}:
            raise ValueError(f"stored permission {field} principal is invalid")
        principal = PrincipalKey(item["tenantId"], item["subjectId"])
        if principal.tenant_id != tenant_id:
            raise ValueError(f"stored permission {field} crosses tenants")
        principals.append(principal)
    ordered = tuple(
        sorted(set(principals), key=lambda item: (item.tenant_id, item.subject_id))
    )
    if ordered != tuple(principals):
        raise ValueError(f"stored permission {field} is not canonical")
    return ordered


def _path_prefix(value: object) -> str:
    if not isinstance(value, str) or not value or value.startswith(("/", ".")):
        raise ValueError("OKF permission path_prefix is invalid")
    pure = PurePosixPath(value)
    if ".." in pure.parts or "\\" in value:
        raise ValueError("OKF permission path_prefix is invalid")
    return pure.as_posix().rstrip("/") + "/"


def _principal_list(
    value: object, tenant_id: str, field: str
) -> tuple[PrincipalKey, ...]:
    if not isinstance(value, dict) or set(value) != {"users"}:
        raise ValueError(f"OKF permission {field} is invalid")
    users = value["users"]
    if not isinstance(users, list) or len(users) > 10_000:
        raise ValueError(f"OKF permission {field} users are invalid")
    principals: list[PrincipalKey] = []
    for user in users:
        if not isinstance(user, dict) or set(user) != {"tenant_id", "subject_id"}:
            raise ValueError(f"OKF permission {field} principal is invalid")
        principal = PrincipalKey(user["tenant_id"], user["subject_id"])
        if principal.tenant_id != tenant_id:
            raise ValueError(f"OKF permission {field} crosses tenants")
        principals.append(principal)
    ordered = tuple(
        sorted(set(principals), key=lambda item: (item.tenant_id, item.subject_id))
    )
    if len(ordered) != len(principals):
        raise ValueError(f"OKF permission {field} principals are duplicated")
    return ordered


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ValueError(f"OKF permission {field} are invalid")
    items = tuple(_identity(item, field) for item in value)
    if len(set(items)) != len(items):
        raise ValueError(f"OKF permission {field} are duplicated")
    return tuple(sorted(items))


def _identity(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value.isascii()
        or not value.isprintable()
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


__all__ = [
    "CompiledPermission",
    "compile_permissions",
    "compiled_permission_from_record",
    "compiled_permission_sha256",
    "effective_permission",
    "permission_record",
    "principal_record",
    "validate_compiled_permission",
]
