from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, unquote, urlsplit

from yap_server.knowledge.terminology_service import TerminologyServiceError
from .routes import TERMINOLOGY_PATH, TERMINOLOGY_RECORD_PATH, TERMINOLOGY_SCOPES_PATH


class TerminologyRequestMixin:
    def _dispatch_terminology_request(self, path: str) -> None:
        assert self._terminology_service is not None
        assert self._principal is not None
        try:
            raw_query = urlsplit(self.path).query
            if path == TERMINOLOGY_SCOPES_PATH:
                if raw_query:
                    raise ValueError("terminology query is invalid")
                self._send_json(
                    HTTPStatus.OK,
                    self._terminology_service.scopes(principal=self._principal),
                )
                return
            query = parse_qs(
                raw_query, keep_blank_values=True, strict_parsing=True, max_num_fields=3
            )
            fields = (
                {"scopeId", "locale", "after"}
                if path == TERMINOLOGY_PATH and self.command == "GET"
                else {"scopeId"}
            )
            if (
                "scopeId" not in query
                or set(query) - fields
                or any(len(values) != 1 for values in query.values())
            ):
                raise ValueError("terminology query is invalid")
            scope_id = query["scopeId"][0]
            if path == TERMINOLOGY_PATH:
                if self.command == "GET":
                    if "locale" not in query:
                        raise ValueError("terminology query is invalid")
                    result = self._terminology_service.list(
                        principal=self._principal,
                        locale=query["locale"][0],
                        after=query.get("after", [""])[0],
                        scope_id=scope_id,
                    )
                    self._send_json(HTTPStatus.OK, result)
                    return
                if self.command == "POST":
                    result = self._terminology_service.create(
                        self._request_body.read_json(),
                        principal=self._principal,
                        scope_id=scope_id,
                    )
                    self._send_json(HTTPStatus.CREATED, result)
                    return
            match = TERMINOLOGY_RECORD_PATH.fullmatch(path)
            if match is not None:
                record_id = unquote(match.group("record_id"))
                if self.command == "GET":
                    self._send_json(
                        HTTPStatus.OK,
                        self._terminology_service.get(
                            record_id, principal=self._principal, scope_id=scope_id
                        ),
                    )
                    return
                if self.command == "PUT":
                    self._send_json(
                        HTTPStatus.OK,
                        self._terminology_service.update(
                            record_id,
                            self._request_body.read_json(),
                            principal=self._principal,
                            scope_id=scope_id,
                        ),
                    )
                    return
                if self.command == "DELETE":
                    self._send_json(
                        HTTPStatus.OK,
                        self._terminology_service.delete(
                            record_id,
                            self._request_body.read_json(),
                            principal=self._principal,
                            scope_id=scope_id,
                        ),
                    )
                    return
        except TerminologyServiceError as error:
            self._send_error(
                HTTPStatus(error.status),
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            return
        except (TypeError, ValueError):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                code="INVALID_TERMINOLOGY",
                message="Terminology request is invalid.",
            )
            return
