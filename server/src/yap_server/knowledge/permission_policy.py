from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat

from yap_server.auth.principal import PrincipalKey
from yap_server.private_artifact import read_bounded_regular_file

from .okf_source import MAX_OKF_DOCUMENT_BYTES, load_unique_yaml


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
    for path in sorted(permission_root.rglob("*.yml")):
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
        canonical = {
            "pathPrefix": prefix,
            "audience": [principal_record(item) for item in audience],
            "denials": [principal_record(item) for item in denials],
            "purposes": list(purposes),
            "classification": classification,
        }
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


def principal_record(value: PrincipalKey) -> dict[str, str]:
    return {"tenantId": value.tenant_id, "subjectId": value.subject_id}


def _path_prefix(value: object) -> str:
    if not isinstance(value, str) or not value or value.startswith(("/", ".")):
        raise ValueError("OKF permission path_prefix is invalid")
    pure = PurePosixPath(value)
    if ".." in pure.parts or "\\" in value or pure.suffix:
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
