from __future__ import annotations

import os
from pathlib import Path
import re
import stat

import yaml

from yap_server.private_artifact import read_bounded_regular_file


MAX_OKF_DOCUMENT_BYTES = 1_000_000
MAX_OKF_BUNDLE_BYTES = 32_000_000
MAX_OKF_MARKDOWN_FILES = 10_000
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)


class _UniqueSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: object, index: object) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not accepted")
        return super().compose_node(parent, index)


def _construct_unique_mapping(
    loader: _UniqueSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    value: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in value
        except TypeError as error:
            raise yaml.YAMLError("YAML mapping key is not scalar") from error
        if duplicate:
            raise yaml.YAMLError(f"duplicate YAML key: {key}")
        value[key] = loader.construct_object(value_node, deep=deep)
    return value


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def real_bundle_directory(path: Path) -> Path:
    requested = Path(os.path.abspath(path))
    try:
        metadata = requested.lstat()
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise ValueError("OKF bundle root must be a real directory") from error
    is_junction = getattr(requested, "is_junction", lambda: False)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or is_junction()
        or os.path.normcase(str(requested)) != os.path.normcase(str(resolved))
    ):
        raise ValueError("OKF bundle root must be a real directory")
    return resolved


def discover_markdown(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        reject_linked_directories(current, names)
        for name in files:
            relative = (current / name).relative_to(root)
            if name.casefold().endswith(".md"):
                paths.append(relative)
                if len(paths) > MAX_OKF_MARKDOWN_FILES:
                    raise ValueError("OKF bundle exceeds its document limit")
    return tuple(sorted(paths, key=lambda item: item.as_posix()))


def reject_linked_directories(current: Path, names: list[str]) -> None:
    for name in tuple(names):
        child = current / name
        metadata = child.lstat()
        is_junction = getattr(child, "is_junction", lambda: False)
        if stat.S_ISLNK(metadata.st_mode) or is_junction():
            raise ValueError("OKF bundle must not contain linked directories")


def read_okf_document(
    root: Path, relative_path: Path
) -> tuple[dict[str, object], str, bytes]:
    body = read_bounded_regular_file(
        root / relative_path,
        maximum_bytes=MAX_OKF_DOCUMENT_BYTES,
        field=f"OKF document {relative_path.as_posix()}",
        containment_root=root,
    )
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(
            f"OKF document {relative_path.as_posix()} is not UTF-8"
        ) from error
    frontmatter, markdown = parse_okf_document(relative_path, text)
    return frontmatter, markdown, body


def parse_okf_document(path: Path, text: str) -> tuple[dict[str, object], str]:
    match = _FRONTMATTER.match(text)
    reserved = path.name.casefold() in {"index.md", "log.md"}
    if match is None:
        if reserved:
            return {}, text
        raise ValueError(f"OKF concept {path.as_posix()} lacks YAML frontmatter")
    value = load_unique_yaml(match.group(1), f"OKF document {path.as_posix()}")
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(
            f"OKF document {path.as_posix()} frontmatter must be an object"
        )
    return value, text[match.end() :]


def load_unique_yaml(source: str | bytes, field: str) -> object:
    try:
        return yaml.load(source, Loader=_UniqueSafeLoader)
    except yaml.YAMLError as error:
        detail = (
            "duplicate YAML key"
            if "duplicate YAML key" in str(error)
            else "invalid YAML"
        )
        raise ValueError(f"{field} has {detail}") from error
