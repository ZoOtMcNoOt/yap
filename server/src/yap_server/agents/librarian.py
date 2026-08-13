from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import threading

from yap_server.auth import AuthenticatedPrincipal
from yap_server.knowledge.governed_knowledge_tools import GovernedKnowledgeTools
from yap_server.knowledge.knowledge_agent_authority import KnowledgeAgentAuthority
from yap_server.knowledge.knowledge_tool_contract import (
    MAX_CONCEPT_ID_CHARACTERS,
    KnowledgeAgentProfile,
    KnowledgeToolResponse,
    SearchKnowledgeRequest,
    validate_bounded_text,
    validate_expected_generation,
    validate_integer,
    validate_search_text,
)
from yap_server.private_postgres_connection import (
    PrivatePostgresConnectionFactory,
)


LIBRARIAN_AGENT_ID = "librarian"
LIBRARIAN_KNOWLEDGE_PURPOSE = "knowledge.read"
LIBRARIAN_MAXIMUM_RESULTS = 5
LIBRARIAN_MAXIMUM_OUTPUT_CHARACTERS = 2_000
LIBRARIAN_MAXIMUM_WIRE_BYTES = 8_192
LIBRARIAN_STATEMENT_TIMEOUT_MILLISECONDS = 5_000

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAXIMUM_SOURCE_REVISION_CHARACTERS = 512
_MAXIMUM_CITATION_OFFSET = 2**63 - 1


class LibrarianStaleGeneration(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LibrarianRequest:
    search_text: str
    maximum_results: int
    expected_generation_sha256: str | None

    def __post_init__(self) -> None:
        text = validate_search_text(self.search_text)
        _utf8(text, "librarian search text")
        if "\0" in text:
            raise ValueError("librarian search text is invalid")
        validate_integer(
            self.maximum_results,
            minimum=1,
            maximum=LIBRARIAN_MAXIMUM_RESULTS,
            field="librarian result limit",
        )
        validate_expected_generation(self.expected_generation_sha256)

    @classmethod
    def from_wire(cls, value: object) -> LibrarianRequest:
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "searchText",
            "maximumResults",
            "expectedGenerationSha256",
        }:
            raise ValueError("librarian request fields differ from the contract")
        if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
            raise ValueError("librarian request schema is unsupported")
        return cls(
            search_text=value["searchText"],
            maximum_results=value["maximumResults"],
            expected_generation_sha256=value["expectedGenerationSha256"],
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "searchText": self.search_text,
            "maximumResults": self.maximum_results,
            "expectedGenerationSha256": self.expected_generation_sha256,
        }


@dataclass(frozen=True, slots=True)
class LibrarianEvidenceItem:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int
    char_end: int
    text: str

    def __post_init__(self) -> None:
        validate_bounded_text(
            self.concept_id,
            field="librarian evidence concept",
            maximum=MAX_CONCEPT_ID_CHARACTERS,
        )
        validate_bounded_text(
            self.source_revision,
            field="librarian evidence revision",
            maximum=_MAXIMUM_SOURCE_REVISION_CHARACTERS,
        )
        _utf8(self.concept_id, "librarian evidence concept")
        _utf8(self.source_revision, "librarian evidence revision")
        _utf8(self.text, "librarian evidence text")
        if (
            not isinstance(self.content_sha256, str)
            or _SHA256.fullmatch(self.content_sha256) is None
            or isinstance(self.char_start, bool)
            or not isinstance(self.char_start, int)
            or isinstance(self.char_end, bool)
            or not isinstance(self.char_end, int)
            or not 0 <= self.char_start <= _MAXIMUM_CITATION_OFFSET
            or self.char_end <= self.char_start
            or self.char_end > _MAXIMUM_CITATION_OFFSET
            or not isinstance(self.text, str)
            or not self.text
            or self.char_end - self.char_start != len(self.text)
        ):
            raise ValueError("librarian evidence span is invalid")

    def to_wire(self) -> dict[str, object]:
        return {
            "conceptId": self.concept_id,
            "sourceRevision": self.source_revision,
            "contentSha256": self.content_sha256,
            "charStart": self.char_start,
            "charEnd": self.char_end,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class LibrarianEvidencePack:
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    items: tuple[LibrarianEvidenceItem, ...]
    output_budget_exhausted: bool
    evidence_sha256: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in (
                self.generation_sha256,
                self.permission_hash,
                self.authorization_hash,
                self.evidence_sha256,
            )
        ):
            raise ValueError("librarian evidence identity is invalid")
        if (
            not isinstance(self.items, tuple)
            or len(self.items) > LIBRARIAN_MAXIMUM_RESULTS
            or any(not isinstance(item, LibrarianEvidenceItem) for item in self.items)
            or len({_item_identity(item) for item in self.items}) != len(self.items)
            or not isinstance(self.output_budget_exhausted, bool)
            or _evidence_character_count(self.items)
            > LIBRARIAN_MAXIMUM_OUTPUT_CHARACTERS
            or _evidence_wire_bytes(self) > LIBRARIAN_MAXIMUM_WIRE_BYTES
        ):
            raise ValueError("librarian evidence pack is invalid")

    @classmethod
    def create(
        cls,
        *,
        generation_sha256: str,
        permission_hash: str,
        authorization_hash: str,
        items: tuple[LibrarianEvidenceItem, ...],
        output_budget_exhausted: bool,
    ) -> LibrarianEvidencePack:
        provisional = cls(
            generation_sha256,
            permission_hash,
            authorization_hash,
            items,
            output_budget_exhausted,
            "0" * 64,
        )
        return cls(
            generation_sha256,
            permission_hash,
            authorization_hash,
            items,
            output_budget_exhausted,
            librarian_evidence_sha256(provisional),
        )

    @classmethod
    def from_tool_response(
        cls,
        response: KnowledgeToolResponse,
    ) -> LibrarianEvidencePack:
        if not isinstance(response, KnowledgeToolResponse) or response.operation != "search":
            raise ValueError("librarian tool response differs from the contract")
        items: list[LibrarianEvidenceItem] = []
        for item in response.items:
            citation = item.citation
            if (
                item.text is None
                or item.relationship_type is not None
                or item.target_concept_id is not None
                or citation.char_start is None
                or citation.char_end is None
            ):
                raise ValueError("librarian tool item differs from the contract")
            items.append(
                LibrarianEvidenceItem(
                    concept_id=citation.concept_id,
                    source_revision=citation.source_revision,
                    content_sha256=citation.content_sha256,
                    char_start=citation.char_start,
                    char_end=citation.char_end,
                    text=item.text,
                )
            )
        return cls.create(
            generation_sha256=response.generation_sha256,
            permission_hash=response.permission_hash,
            authorization_hash=response.authorization_hash,
            items=tuple(items),
            output_budget_exhausted=response.output_budget_exhausted,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "operation": "search",
            "generationSha256": self.generation_sha256,
            "permissionHash": self.permission_hash,
            "authorizationHash": self.authorization_hash,
            "evidenceSha256": self.evidence_sha256,
            "items": [item.to_wire() for item in self.items],
            "outputBudgetExhausted": self.output_budget_exhausted,
        }


class PostgresLibrarianEvidenceReader:
    """Execute one fixed permission-safe lexical query for Librarian."""

    def __init__(self, connection_factory: PrivatePostgresConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self._tools = GovernedKnowledgeTools(
            KnowledgeAgentAuthority(
                (
                    KnowledgeAgentProfile(
                        agent_id=LIBRARIAN_AGENT_ID,
                        capabilities=frozenset({"knowledge.search.lexical"}),
                        purposes=frozenset({LIBRARIAN_KNOWLEDGE_PURPOSE}),
                        maximum_results=LIBRARIAN_MAXIMUM_RESULTS,
                        maximum_output_characters=(
                            LIBRARIAN_MAXIMUM_OUTPUT_CHARACTERS
                        ),
                        statement_timeout_milliseconds=(
                            LIBRARIAN_STATEMENT_TIMEOUT_MILLISECONDS
                        ),
                    ),
                )
            )
        )

    def read(
        self,
        request: LibrarianRequest,
        *,
        principal: AuthenticatedPrincipal,
        cancellation: threading.Event,
    ) -> LibrarianEvidencePack:
        if not isinstance(request, LibrarianRequest):
            raise TypeError("librarian request type is invalid")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise TypeError("librarian principal type is invalid")
        if not isinstance(cancellation, threading.Event):
            raise TypeError("librarian cancellation type is invalid")
        with self._connection_factory() as connection:
            try:
                response = self._tools.execute(
                    connection,
                    principal=principal.key,
                    agent_id=LIBRARIAN_AGENT_ID,
                    request=SearchKnowledgeRequest(
                        purpose=LIBRARIAN_KNOWLEDGE_PURPOSE,
                        search_text=request.search_text,
                        maximum_results=request.maximum_results,
                        expected_generation_sha256=(
                            request.expected_generation_sha256
                        ),
                    ),
                    cancellation=cancellation,
                )
            except ValueError as error:
                if str(error) == "knowledge generation is stale":
                    raise LibrarianStaleGeneration(
                        "librarian generation is stale"
                    ) from error
                raise
        evidence = LibrarianEvidencePack.from_tool_response(response)
        validate_librarian_evidence(request, evidence)
        return evidence


def librarian_request_sha256(request: LibrarianRequest) -> str:
    if not isinstance(request, LibrarianRequest):
        raise TypeError("librarian request type is invalid")
    return _sha256(
        {
            "expectedGenerationSha256": request.expected_generation_sha256,
            "maximumResults": request.maximum_results,
            "searchText": request.search_text,
        }
    )


def librarian_evidence_sha256(evidence: LibrarianEvidencePack) -> str:
    if not isinstance(evidence, LibrarianEvidencePack):
        raise TypeError("librarian evidence type is invalid")
    return _sha256(
        {
            "authorizationHash": evidence.authorization_hash,
            "generationSha256": evidence.generation_sha256,
            "items": [item.to_wire() for item in evidence.items],
            "operation": "search",
            "outputBudgetExhausted": evidence.output_budget_exhausted,
            "permissionHash": evidence.permission_hash,
        }
    )


def librarian_work_sha256(
    request: LibrarianRequest,
    evidence: LibrarianEvidencePack,
) -> str:
    validate_librarian_evidence(request, evidence)
    return _sha256(
        {
            "evidenceSha256": evidence.evidence_sha256,
            "requestSha256": librarian_request_sha256(request),
        }
    )


def validate_librarian_evidence(
    request: LibrarianRequest,
    evidence: LibrarianEvidencePack,
) -> None:
    if (
        not isinstance(request, LibrarianRequest)
        or not isinstance(evidence, LibrarianEvidencePack)
        or (
            request.expected_generation_sha256 is not None
            and evidence.generation_sha256
            != request.expected_generation_sha256
        )
        or len(evidence.items) > request.maximum_results
        or evidence.evidence_sha256 != librarian_evidence_sha256(evidence)
    ):
        raise ValueError("librarian evidence differs from the request")


def _item_identity(item: LibrarianEvidenceItem) -> tuple[object, ...]:
    return (
        item.concept_id,
        item.source_revision,
        item.content_sha256,
        item.char_start,
        item.char_end,
    )


def _evidence_character_count(items: tuple[LibrarianEvidenceItem, ...]) -> int:
    return sum(
        len(item.concept_id)
        + len(item.source_revision)
        + len(item.content_sha256)
        + len(item.text)
        for item in items
    )


def _evidence_wire_bytes(evidence: LibrarianEvidencePack) -> int:
    value = {
        "operation": "search",
        "generationSha256": evidence.generation_sha256,
        "permissionHash": evidence.permission_hash,
        "authorizationHash": evidence.authorization_hash,
        "evidenceSha256": evidence.evidence_sha256,
        "items": [item.to_wire() for item in evidence.items],
        "outputBudgetExhausted": evidence.output_budget_exhausted,
    }
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _utf8(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} is invalid") from error


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "LIBRARIAN_AGENT_ID",
    "LIBRARIAN_KNOWLEDGE_PURPOSE",
    "LIBRARIAN_MAXIMUM_OUTPUT_CHARACTERS",
    "LIBRARIAN_MAXIMUM_RESULTS",
    "LIBRARIAN_MAXIMUM_WIRE_BYTES",
    "LIBRARIAN_STATEMENT_TIMEOUT_MILLISECONDS",
    "LibrarianEvidenceItem",
    "LibrarianEvidencePack",
    "LibrarianRequest",
    "LibrarianStaleGeneration",
    "PostgresLibrarianEvidenceReader",
    "librarian_evidence_sha256",
    "librarian_request_sha256",
    "librarian_work_sha256",
    "validate_librarian_evidence",
]
