from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from yap_server.knowledge.knowledge_connections_service import KnowledgeConnectionsError


class KnowledgeConnectionsRequestMixin:
    def _dispatch_knowledge_connections_request(self, path: str) -> None:
        assert self._knowledge_connections_service is not None
        assert self._principal is not None
        try:
            if (
                self.command == "DELETE" or path == "/v1/knowledge/connection-proposals"
            ) and int(self.headers.get("Content-Length", "0")) != 0:
                raise ValueError("proposal journal requests take no body")
            query = parse_qs(
                urlsplit(self.path).query,
                keep_blank_values=True,
                strict_parsing=True,
                errors="strict",
                max_num_fields=2,
            )
            fields = (
                set()
                if path == "/v1/knowledge/connection-proposals"
                else {"proposalId"}
                if path == "/v1/knowledge/connection-proposal"
                else {"search"}
                if path == "/v1/knowledge/concepts"
                else {"conceptId", "generationSha256"}
            )
            if set(query) != fields or any(
                len(values) != 1 for values in query.values()
            ):
                raise ValueError("knowledge query is invalid")
            if path == "/v1/knowledge/connection-proposals":
                result = self._knowledge_connections_service.pending(
                    principal=self._principal
                )
            elif path == "/v1/knowledge/connection-proposal":
                operation = (
                    self._knowledge_connections_service.discard
                    if self.command == "DELETE"
                    else self._knowledge_connections_service.proposal
                )
                result = operation(
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
