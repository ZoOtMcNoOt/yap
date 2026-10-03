from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Annotated, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


KNOWLEDGE_READ_PURPOSE = "knowledge.read"
MAX_SEARCH_TEXT_CHARACTERS = 1_024
MAX_SEARCH_RESULTS = 10
MAX_STORAGE_RESULTS = 100
MAX_CONCEPT_ID_CHARACTERS = 512
MAX_TRAVERSAL_DEPTH = 4
MAX_TRAVERSAL_RESULTS = 50
MAX_PROPOSAL_CHARACTERS = 100_000
MAX_PROPOSAL_CITATIONS = 100
MAX_CONNECTION_PROPOSAL_CHARACTERS = 16_384
SHA256_PATTERN = "^[0-9a-f]{64}$"

KnowledgePurpose = Literal["knowledge.read"]
SearchText = Annotated[str, Field(min_length=1, max_length=MAX_SEARCH_TEXT_CHARACTERS)]
SearchResultLimit = Annotated[int, Field(strict=True, ge=1, le=MAX_SEARCH_RESULTS)]
ConceptId = Annotated[str, Field(min_length=1, max_length=MAX_CONCEPT_ID_CHARACTERS)]
TraversalDepth = Annotated[int, Field(strict=True, ge=1, le=MAX_TRAVERSAL_DEPTH)]
TraversalResultLimit = Annotated[
    int, Field(strict=True, ge=1, le=MAX_TRAVERSAL_RESULTS)
]
GenerationSha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
ProposalType = Literal["summary", "relationship"]
CanonicalRelationshipAuthority = Literal["asserted", "human_confirmed", "derived"]
ProposalContent = Annotated[
    str, Field(min_length=1, max_length=MAX_PROPOSAL_CHARACTERS)
]
CitationOffset = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
CitationEndOffset = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]

_SHA256 = re.compile(SHA256_PATTERN)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class KnowledgeToolCancelled(RuntimeError):
    pass


class KnowledgeToolCancellationFailed(RuntimeError):
    pass


class KnowledgeToolTimedOut(TimeoutError):
    pass


class KnowledgeGenerationStale(ValueError):
    pass


class ProposalCitation(BaseModel):
    """One strict immutable citation shared by model input and persistence."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    concept_id: ConceptId
    source_revision: ConceptId
    content_sha256: GenerationSha256
    char_start: CitationOffset
    char_end: CitationEndOffset

    @model_validator(mode="after")
    def _ordered_span(self) -> ProposalCitation:
        if self.char_end <= self.char_start:
            raise ValueError("proposal citation end must follow its start")
        return self


ProposalCitations = Annotated[
    list[ProposalCitation],
    Field(min_length=1, max_length=MAX_PROPOSAL_CITATIONS),
]


class ConnectionCandidate(BaseModel):
    """A proposed edge, never a canonical relationship or a reviewer grant."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    source_concept_id: ConceptId
    target_concept_id: ConceptId
    relationship_type: Annotated[str, Field(min_length=1, max_length=128)]
    rationale: Annotated[str, Field(min_length=1, max_length=2_000)]

    @model_validator(mode="after")
    def _valid_edge(self) -> ConnectionCandidate:
        for value in (self.source_concept_id, self.target_concept_id, self.rationale):
            if value.strip() != value or any(
                unicodedata.category(character) in {"Cc", "Cs"} and character != "\n"
                for character in value
            ):
                raise ValueError("connection candidate text is invalid")
        if any(
            "\n" in value for value in (self.source_concept_id, self.target_concept_id)
        ):
            raise ValueError("connection candidate endpoint is invalid")
        if self.source_concept_id == self.target_concept_id:
            raise ValueError("connection candidate endpoints must differ")
        if (
            not self.relationship_type.isascii()
            or not self.relationship_type.isprintable()
            or any(character.isspace() for character in self.relationship_type)
        ):
            raise ValueError("connection candidate relationship type is invalid")
        return self


def canonical_connection_proposal(
    content: str,
    citations: tuple[ProposalCitation, ...],
    expected_generation_sha256: str | None,
) -> tuple[str, tuple[ProposalCitation, ...]]:
    """Bind typed edge intent to both endpoint citations before storage."""

    validate_expected_generation(expected_generation_sha256)
    if expected_generation_sha256 is None:
        raise ValueError("connection proposal requires the reviewed generation")
    validate_bounded_text(
        content, field="connection proposal", maximum=MAX_CONNECTION_PROPOSAL_CHARACTERS
    )
    try:
        value = json.loads(content, object_pairs_hook=_unique_candidate_fields)
        candidate = ConnectionCandidate.model_validate(value, strict=True)
    except (ValueError, RecursionError) as error:
        raise ValueError(
            "connection proposal differs from the typed contract"
        ) from error
    if (
        not isinstance(citations, tuple)
        or len(citations) != 2
        or not all(isinstance(item, ProposalCitation) for item in citations)
        or {item.concept_id for item in citations}
        != {candidate.source_concept_id, candidate.target_concept_id}
    ):
        raise ValueError(
            "connection proposal requires exactly one citation per endpoint"
        )
    canonical = json.dumps(
        candidate.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    # JSON escaping is part of the stored bound, including Unicode rationale.
    if len(canonical) > MAX_CONNECTION_PROPOSAL_CHARACTERS:
        raise ValueError("connection proposal exceeds its stored bound")
    return canonical, tuple(sorted(citations, key=lambda item: item.concept_id))


def _unique_candidate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("connection candidate field is duplicated")
        value[key] = item
    return value


@dataclass(frozen=True, slots=True)
class KnowledgeAgentProfile:
    agent_id: str
    capabilities: frozenset[str]
    purposes: frozenset[str]
    maximum_results: int
    maximum_output_characters: int
    statement_timeout_milliseconds: int


@dataclass(frozen=True, slots=True)
class SearchKnowledgeRequest:
    purpose: str
    search_text: str
    maximum_results: int = 10
    expected_generation_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_knowledge_purpose(self.purpose)
        validate_search_text(self.search_text)
        validate_integer(
            self.maximum_results,
            minimum=1,
            maximum=MAX_SEARCH_RESULTS,
            field="knowledge search result limit",
        )
        validate_expected_generation(self.expected_generation_sha256)


@dataclass(frozen=True, slots=True)
class BrowseKnowledgeRequest:
    purpose: str
    expected_generation_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_knowledge_purpose(self.purpose)
        validate_expected_generation(self.expected_generation_sha256)


@dataclass(frozen=True, slots=True)
class TraverseKnowledgeRequest:
    purpose: str
    start_concept_id: str
    maximum_depth: int = 2
    maximum_results: int = 50
    expected_generation_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_knowledge_purpose(self.purpose)
        validate_bounded_text(
            self.start_concept_id,
            field="knowledge traversal start",
            maximum=MAX_CONCEPT_ID_CHARACTERS,
        )
        validate_integer(
            self.maximum_depth,
            minimum=1,
            maximum=MAX_TRAVERSAL_DEPTH,
            field="knowledge traversal depth",
        )
        validate_integer(
            self.maximum_results,
            minimum=1,
            maximum=MAX_TRAVERSAL_RESULTS,
            field="knowledge traversal result limit",
        )
        validate_expected_generation(self.expected_generation_sha256)


KnowledgeToolRequest = (
    SearchKnowledgeRequest | BrowseKnowledgeRequest | TraverseKnowledgeRequest
)


@dataclass(frozen=True, slots=True)
class KnowledgeToolCitation:
    concept_id: str
    source_revision: str
    content_sha256: str
    char_start: int | None
    char_end: int | None


@dataclass(frozen=True, slots=True)
class KnowledgeToolItem:
    citation: KnowledgeToolCitation
    text: str | None
    relationship_type: str | None
    target_concept_id: str | None
    relationship_authority: CanonicalRelationshipAuthority | None

    def __post_init__(self) -> None:
        if self.relationship_type is None:
            if (
                self.target_concept_id is not None
                or self.relationship_authority is not None
            ):
                raise ValueError(
                    "nonrelationship tool evidence cannot carry an edge authority"
                )
            return
        validate_bounded_text(
            self.relationship_type, field="relationship type", maximum=128
        )
        validate_bounded_text(
            self.target_concept_id,
            field="relationship target",
            maximum=MAX_CONCEPT_ID_CHARACTERS,
        )
        if self.text is not None or self.relationship_authority not in {
            "asserted",
            "human_confirmed",
            "derived",
        }:
            raise ValueError(
                "relationship tool evidence requires canonical source authority"
            )


@dataclass(frozen=True, slots=True)
class KnowledgeToolResponse:
    operation: str
    generation_sha256: str
    permission_hash: str
    authorization_hash: str
    items: tuple[KnowledgeToolItem, ...]
    output_budget_exhausted: bool


def governed_agent_tool_definitions(
    *, require_generation_sha256: bool = False
) -> list[dict[str, object]]:
    """Return the strict model-facing schema for the executing governed tools."""

    generation_required = (
        ["expected_generation_sha256"] if require_generation_sha256 else []
    )
    common = {
        "purpose": {
            "type": "string",
            "enum": [KNOWLEDGE_READ_PURPOSE],
            "description": "Always use the authorized knowledge.read purpose.",
        },
        "expected_generation_sha256": {
            "type": "string",
            "pattern": SHA256_PATTERN,
            "description": (
                "Copy the exact generation SHA-256 supplied by the user; omit it "
                "only when the user did not supply one."
            ),
        },
    }
    citation_schema = ProposalCitation.model_json_schema()
    citation_schema.pop("title", None)
    return [
        _tool_definition(
            "search_knowledge",
            (
                "Search permission-filtered text. Use only for a requested text "
                "search, never for browsing, relationship traversal, or proposals."
            ),
            {
                **common,
                "search_text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_SEARCH_TEXT_CHARACTERS,
                    "description": "The user's requested search text.",
                },
                "maximum_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_SEARCH_RESULTS,
                },
            },
            ["purpose", "search_text", *generation_required],
        ),
        _tool_definition(
            "browse_knowledge",
            (
                "List visible knowledge concepts or areas. Do not use for text "
                "search, relationship traversal, or proposals."
            ),
            common,
            ["purpose", *generation_required],
        ),
        _tool_definition(
            "traverse_knowledge",
            (
                "Follow visible typed relationships with source citations and explicit "
                "asserted, human-confirmed or derived authority. Do not use "
                "for text search, area browsing, or proposals."
            ),
            {
                **common,
                "start_concept_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_CONCEPT_ID_CHARACTERS,
                    "description": "Exact concept ID where traversal starts.",
                },
                "maximum_depth": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_TRAVERSAL_DEPTH,
                    "description": "Exact requested relationship depth.",
                },
                "maximum_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_TRAVERSAL_RESULTS,
                },
            },
            ["purpose", "start_concept_id", *generation_required],
        ),
        _tool_definition(
            "propose_knowledge",
            (
                "Store a cited noncanonical proposal from supplied evidence. Use "
                "only when the user asks to create or store a proposal."
            ),
            {
                **common,
                "proposal_type": {
                    "type": "string",
                    "enum": ["summary", "relationship"],
                },
                "proposed_content": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PROPOSAL_CHARACTERS,
                    "description": (
                        "Summary text, or relationship JSON with exactly schema_version:1, "
                        "source_concept_id, target_concept_id, relationship_type and rationale. "
                        "Relationships require distinct endpoints, a type of at most 128 "
                        "ASCII nonwhitespace characters, rationale of at most 2000 characters, "
                        "one exact citation per endpoint and expected_generation_sha256. "
                        "Relationship JSON is bounded to 16384 characters and remains noncanonical."
                    ),
                },
                "source_citations": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_PROPOSAL_CITATIONS,
                    "items": citation_schema,
                },
            },
            [
                "purpose",
                "proposal_type",
                "proposed_content",
                "source_citations",
                *generation_required,
            ],
        ),
    ]


def validate_governed_agent_tool_arguments(
    name: str, arguments: dict[str, object]
) -> None:
    """Validate model-authored arguments against the executing tool contract."""

    if not isinstance(arguments, dict):
        raise ValueError("agent tool arguments must be an object")
    common = {"purpose", "expected_generation_sha256"}
    required: set[str]
    allowed: set[str]
    if name == "search_knowledge":
        required = {"purpose", "search_text"}
        allowed = common | {"search_text", "maximum_results"}
        validate_search_text(arguments.get("search_text"))
        validate_optional_integer(
            arguments.get("maximum_results"),
            minimum=1,
            maximum=MAX_SEARCH_RESULTS,
            field="agent search result limit",
        )
    elif name == "browse_knowledge":
        required = {"purpose"}
        allowed = common
    elif name == "traverse_knowledge":
        required = {"purpose", "start_concept_id"}
        allowed = common | {"start_concept_id", "maximum_depth", "maximum_results"}
        validate_bounded_text(
            arguments.get("start_concept_id"),
            field="agent traversal start",
            maximum=MAX_CONCEPT_ID_CHARACTERS,
        )
        validate_optional_integer(
            arguments.get("maximum_depth"),
            minimum=1,
            maximum=MAX_TRAVERSAL_DEPTH,
            field="agent traversal depth",
        )
        validate_optional_integer(
            arguments.get("maximum_results"),
            minimum=1,
            maximum=MAX_TRAVERSAL_RESULTS,
            field="agent traversal result limit",
        )
    elif name == "propose_knowledge":
        required = {
            "purpose",
            "proposal_type",
            "proposed_content",
            "source_citations",
        }
        allowed = common | required
        if arguments.get("proposal_type") not in {"summary", "relationship"}:
            raise ValueError("agent proposal type is invalid")
        validate_bounded_text(
            arguments.get("proposed_content"),
            field="agent proposed content",
            maximum=MAX_PROPOSAL_CHARACTERS,
        )
        _validate_agent_citations(arguments.get("source_citations"))
        if arguments["proposal_type"] == "relationship":
            canonical_connection_proposal(
                arguments["proposed_content"],
                tuple(
                    ProposalCitation.model_validate(item, strict=True)
                    for item in arguments["source_citations"]
                ),
                arguments.get("expected_generation_sha256"),
            )
    else:
        raise ValueError("agent selected an unknown tool")
    if set(arguments) - allowed or not required <= set(arguments):
        raise ValueError("agent tool arguments differ from the contract")
    validate_knowledge_purpose(arguments.get("purpose"))
    validate_expected_generation(arguments.get("expected_generation_sha256"))


def validate_knowledge_purpose(value: object) -> None:
    if value != KNOWLEDGE_READ_PURPOSE:
        raise ValueError("knowledge purpose is invalid")


def validate_search_text(value: object) -> str:
    text = validate_bounded_text(
        value,
        field="knowledge search text",
        maximum=MAX_SEARCH_TEXT_CHARACTERS,
    )
    if _TOKEN.search(text) is None:
        raise ValueError("knowledge search text is invalid")
    return text


def validate_bounded_text(value: object, *, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value.strip() != value
    ):
        raise ValueError(f"{field} is invalid")
    return value


def validate_integer(value: object, *, minimum: int, maximum: int, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{field} is invalid")
    return value


def validate_optional_integer(
    value: object, *, minimum: int, maximum: int, field: str
) -> None:
    if value is not None:
        validate_integer(value, minimum=minimum, maximum=maximum, field=field)


def validate_expected_generation(value: object) -> None:
    if value is not None and (
        not isinstance(value, str) or not _SHA256.fullmatch(value)
    ):
        raise ValueError("knowledge expected generation is invalid")


def _validate_agent_citations(value: object) -> None:
    if not isinstance(value, list) or not value or len(value) > MAX_PROPOSAL_CITATIONS:
        raise ValueError("agent proposal citations are invalid")
    identities: set[tuple[object, ...]] = set()
    for citation in value:
        try:
            parsed = ProposalCitation.model_validate(citation, strict=True)
        except ValidationError as error:
            raise ValueError(
                "agent proposal citation differs from the contract"
            ) from error
        identity = (
            parsed.concept_id,
            parsed.source_revision,
            parsed.content_sha256,
            parsed.char_start,
            parsed.char_end,
        )
        if identity in identities:
            raise ValueError("agent proposal citation is duplicated")
        identities.add(identity)


def _tool_definition(
    name: str,
    description: str,
    properties: dict[str, object],
    required: list[str],
) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


__all__ = [
    "BrowseKnowledgeRequest",
    "KnowledgeAgentProfile",
    "KnowledgePurpose",
    "SearchText",
    "SearchResultLimit",
    "ConceptId",
    "TraversalDepth",
    "TraversalResultLimit",
    "GenerationSha256",
    "ProposalType",
    "ProposalContent",
    "ProposalCitation",
    "ProposalCitations",
    "KnowledgeToolCancellationFailed",
    "KnowledgeToolCancelled",
    "KnowledgeGenerationStale",
    "KnowledgeToolCitation",
    "KnowledgeToolItem",
    "KnowledgeToolRequest",
    "KnowledgeToolResponse",
    "KnowledgeToolTimedOut",
    "SearchKnowledgeRequest",
    "TraverseKnowledgeRequest",
    "governed_agent_tool_definitions",
    "validate_bounded_text",
    "validate_expected_generation",
    "validate_governed_agent_tool_arguments",
    "validate_integer",
    "validate_knowledge_purpose",
    "validate_search_text",
]
