from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Annotated, Literal

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
SHA256_PATTERN = "^[0-9a-f]{64}$"

KnowledgePurpose = Literal["knowledge.read"]
SearchText = Annotated[
    str, Field(min_length=1, max_length=MAX_SEARCH_TEXT_CHARACTERS)
]
SearchResultLimit = Annotated[
    int, Field(strict=True, ge=1, le=MAX_SEARCH_RESULTS)
]
ConceptId = Annotated[
    str, Field(min_length=1, max_length=MAX_CONCEPT_ID_CHARACTERS)
]
TraversalDepth = Annotated[
    int, Field(strict=True, ge=1, le=MAX_TRAVERSAL_DEPTH)
]
TraversalResultLimit = Annotated[
    int, Field(strict=True, ge=1, le=MAX_TRAVERSAL_RESULTS)
]
GenerationSha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
ProposalType = Literal["summary", "relationship"]
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


class ProposalCitationInput(BaseModel):
    """Strict model/MCP input for one persisted proposal citation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: ConceptId
    source_revision: ConceptId
    content_sha256: GenerationSha256
    char_start: CitationOffset
    char_end: CitationEndOffset

    @model_validator(mode="after")
    def _ordered_span(self) -> ProposalCitationInput:
        if self.char_end <= self.char_start:
            raise ValueError("proposal citation end must follow its start")
        return self


ProposalCitations = Annotated[
    list[ProposalCitationInput],
    Field(min_length=1, max_length=MAX_PROPOSAL_CITATIONS),
]


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
    citation_schema = ProposalCitationInput.model_json_schema()
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
                "Follow visible typed relationships from one concept. Do not use "
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


def validate_integer(
    value: object, *, minimum: int, maximum: int, field: str
) -> int:
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
    if value is not None and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
        raise ValueError("knowledge expected generation is invalid")


def _validate_agent_citations(value: object) -> None:
    if not isinstance(value, list) or not value or len(value) > MAX_PROPOSAL_CITATIONS:
        raise ValueError("agent proposal citations are invalid")
    identities: set[tuple[object, ...]] = set()
    for citation in value:
        try:
            parsed = ProposalCitationInput.model_validate(citation, strict=True)
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
    "ProposalCitationInput",
    "ProposalCitations",
    "KnowledgeToolCancellationFailed",
    "KnowledgeToolCancelled",
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
