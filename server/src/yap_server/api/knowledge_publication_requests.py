from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from yap_server.jobs import JobServiceError
from yap_server.knowledge.knowledge_publication_service import KnowledgePublicationError


class KnowledgePublicationRequestMixin:
    def _dispatch_knowledge_publication_request(self) -> None:
        assert self._knowledge_publication_service is not None
        assert self._principal is not None
        try:
            query = parse_qs(
                urlsplit(self.path).query,
                keep_blank_values=True,
                strict_parsing=True,
                errors="strict",
                max_num_fields=1,
            )
            if self.command == "GET":
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
                result = self._knowledge_publication_service.publish(
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
                code="INVALID_KNOWLEDGE_PUBLICATION",
                message="Knowledge publication request is invalid.",
            )
