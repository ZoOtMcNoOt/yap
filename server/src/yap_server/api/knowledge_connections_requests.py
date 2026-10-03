from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from yap_server.knowledge.knowledge_connections_service import KnowledgeConnectionsError


class KnowledgeConnectionsRequestMixin:
    def _dispatch_knowledge_connections_request(self, path: str) -> None:
        assert self._knowledge_connections_service is not None
        assert self._principal is not None
        try:
            query = parse_qs(
                urlsplit(self.path).query,
                keep_blank_values=True,
                strict_parsing=True,
                errors="strict",
                max_num_fields=2,
            )
            fields = (
                {"proposalId"}
                if path == "/v1/knowledge/connection-proposal"
                else {"search"}
                if path == "/v1/knowledge/concepts"
                else {"conceptId", "generationSha256"}
            )
            if set(query) != fields or any(
                len(values) != 1 for values in query.values()
            ):
                raise ValueError("knowledge query is invalid")
            if path == "/v1/knowledge/connection-proposal":
                result = self._knowledge_connections_service.proposal(
                    principal=self._principal, proposal_id=query["proposalId"][0]
                )
            elif path == "/v1/knowledge/concepts":
                result = self._knowledge_connections_service.browse(
                    principal=self._principal,
                    search_text=query["search"][0],
                )
            else:
                result = self._knowledge_connections_service.read(
                    principal=self._principal,
                    concept_id=query["conceptId"][0],
                    expected_generation_sha256=query["generationSha256"][0],
                )
            self._send_json(HTTPStatus.OK, result)
        except KnowledgeConnectionsError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_KNOWLEDGE_CONNECTIONS",
                message="Knowledge connections request is invalid.",
            )
