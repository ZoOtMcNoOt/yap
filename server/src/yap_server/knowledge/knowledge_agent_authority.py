from __future__ import annotations

import re

from .knowledge_tool_contract import KnowledgeAgentProfile


_PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SUPPORTED_CAPABILITIES = frozenset(
    {
        "knowledge.tree",
        "knowledge.search.lexical",
        "knowledge.search.vector",
        "knowledge.search.hybrid",
        "knowledge.relationship.traverse",
        "knowledge.propose",
    }
)


class KnowledgeAgentAuthority:
    """Own immutable server-side agent capabilities, purposes, and budgets."""

    def __init__(self, profiles: tuple[KnowledgeAgentProfile, ...]) -> None:
        if not isinstance(profiles, tuple):
            raise TypeError("knowledge agent profiles must be immutable")
        validated = {_profile(item).agent_id: item for item in profiles}
        if len(validated) != len(profiles):
            raise ValueError("knowledge agent profile is duplicated")
        self._profiles = validated

    def authorize(self, *, agent_id: str, purpose: str) -> KnowledgeAgentProfile:
        profile = self._profiles.get(agent_id)
        if profile is None:
            raise PermissionError("knowledge agent profile is not authorized")
        if purpose not in profile.purposes:
            raise PermissionError("knowledge purpose is not authorized for agent")
        return profile


def _profile(value: KnowledgeAgentProfile) -> KnowledgeAgentProfile:
    if (
        not _PROFILE_ID.fullmatch(value.agent_id)
        or not isinstance(value.capabilities, frozenset)
        or not value.capabilities
        or not value.capabilities <= _SUPPORTED_CAPABILITIES
        or not isinstance(value.purposes, frozenset)
        or not value.purposes
        or len(value.purposes) > 32
        or any(not _PROFILE_ID.fullmatch(item) for item in value.purposes)
    ):
        raise ValueError("knowledge agent profile is invalid")
    if not 1 <= value.maximum_results <= 100:
        raise ValueError("knowledge agent result bound is invalid")
    if not 1 <= value.maximum_output_characters <= 1_000_000:
        raise ValueError("knowledge agent output bound is invalid")
    if not 1 <= value.statement_timeout_milliseconds <= 300_000:
        raise ValueError("knowledge agent timeout is invalid")
    return value


__all__ = ["KnowledgeAgentAuthority"]
