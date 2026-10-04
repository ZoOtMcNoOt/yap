from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from yap_server.jobs import JobServiceError
from yap_server.knowledge.knowledge_publication_service import (
    KnowledgePublicationError,
    SOURCE_PREPARATION_PATH,
    ROLLBACK_PATH,
    EMBEDDING_PREPARATION_PATH,
)


class KnowledgePublicationRequestMixin:
    def _dispatch_knowledge_publication_request(self) -> None:
        assert self._knowledge_publication_service is not None
        assert self._principal is not None
        source_request = urlsplit(self.path).path == SOURCE_PREPARATION_PATH
        try:
            query = parse_qs(
                urlsplit(self.path).query,
                keep_blank_values=True,
                strict_parsing=True,
                errors="strict",
                max_num_fields=1,
            )
            if source_request:
                if query:
                    raise ValueError("source preparation takes no query")
                if self.command == "GET":
                    if int(self.headers.get("Content-Length", "0")) != 0:
                        raise ValueError("source inspection takes no body")
                    result = self._knowledge_publication_service.inspect_source(
                        principal=self._principal
                    )
                else:
                    result = self._knowledge_publication_service.prepare_source(
                        principal=self._principal,
                        request=self._request_body.read_json(),
                    )
            elif urlsplit(self.path).path == EMBEDDING_PREPARATION_PATH:
                if query:
                    raise ValueError("embedding preparation takes no query")
                result = self._knowledge_publication_service.prepare_embeddings(
                    principal=self._principal, request=self._request_body.read_json()
                )
            elif self.command == "GET":
                if (
                    set(query) != {"generationSha256"}
                    or len(query["generationSha256"]) != 1
                ):
                    raise ValueError("publication inspection query is invalid")
                if int(self.headers.get("Content-Length", "0")) != 0:
                    raise ValueError("publication inspection takes no body")
                result = self._knowledge_publication_service.inspect(
                    principal=self._principal,
                    generation_sha256=query["generationSha256"][0],
                )
            else:
                if query:
                    raise ValueError("publication takes no query")
                activate = (
                    self._knowledge_publication_service.rollback
                    if urlsplit(self.path).path == ROLLBACK_PATH
                    else self._knowledge_publication_service.publish
                )
                result = activate(
                    principal=self._principal, request=self._request_body.read_json()
                )
            self._send_json(HTTPStatus.OK, result)
        except KnowledgePublicationError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
        except JobServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_KNOWLEDGE_SOURCE_PREPARATION"
                if source_request
                else "INVALID_KNOWLEDGE_PUBLICATION",
                message="Knowledge source preparation request is invalid."
                if source_request
                else "Knowledge publication request is invalid.",
            )
