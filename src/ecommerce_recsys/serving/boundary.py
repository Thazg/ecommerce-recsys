"""Bound JSON request size before parsing and avoid echoing invalid inputs."""

from __future__ import annotations

import asyncio
import json
import math
from uuid import uuid4

from starlette.responses import JSONResponse

from ecommerce_recsys.serving.contracts import ErrorDetail, ErrorResponse
from ecommerce_recsys.serving.rate_limit import RequestAdmission
from ecommerce_recsys.serving.security import SecuritySettings
from ecommerce_recsys.serving.security_boundary import RequestGuards

BODY_LIMIT = 8192
RECOMMENDATION_PATH = "/v1/recommendations"


def error_response(request_id, status, code, message, *, fields=(), headers=None):
    payload = ErrorResponse(
        request_id=request_id, error=ErrorDetail(code=code, message=message, fields=list(fields))
    )
    return JSONResponse(
        payload.model_dump(),
        status_code=status,
        headers={
            "X-Request-ID": request_id,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            **(headers or {}),
        },
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _no_constant(value):
    raise ValueError("Nonfinite JSON constant.")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite JSON number.")
    return result


class RequestBoundary:
    def __init__(self, app, *, security=None, admission=None):
        self.app = app
        self.security = security or SecuritySettings()
        self.admission = admission or RequestAdmission(self.security)
        self.guards = RequestGuards(self.security, self.admission)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def tagged_send(message):
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower()
                    not in {b"x-request-id", b"cache-control", b"x-content-type-options"}
                ]
                message = {
                    **message,
                    "headers": [
                        *headers,
                        (b"x-request-id", request_id.encode()),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ],
                }
            await send(message)

        async def reject(status, code, message, headers=None):
            scope["state"]["telemetry_error"] = code
            await error_response(
                request_id,
                status,
                code,
                message,
                headers={"Connection": "close", **(headers or {})},
            )(scope, receive, tagged_send)

        headers = {}
        for name, value in scope.get("headers", []):
            headers.setdefault(name.lower(), []).append(value)
        denial = self.guards.inspect(scope, headers)
        if denial:
            return await reject(denial.status, denial.code, denial.message, dict(denial.headers))

        if scope["path"] == RECOMMENDATION_PATH and scope["method"] == "POST":
            if scope.get("query_string"):
                return await reject(
                    422,
                    "validation_error",
                    "Recommendation inputs belong in the JSON body; query parameters are not supported.",
                )
            media = headers.get(b"content-type", [b""])
            if len(media) != 1 or media[0].split(b";", 1)[0].strip().lower() != b"application/json":
                return await reject(
                    415, "unsupported_media_type", "Use application/json encoded as UTF-8."
                )
            lengths = headers.get(b"content-length", [])
            declared = None
            if lengths:
                if len(lengths) != 1 or not lengths[0].isdigit() or len(lengths[0]) > 20:
                    return await reject(400, "invalid_request", "Invalid content length.")
                declared = int(lengths[0])
                if declared > BODY_LIMIT:
                    return await reject(413, "body_too_large", "Request body exceeds 8192 bytes.")
            if not self.admission.enter_reader():
                return await reject(
                    503, "request_overloaded", "Request readers are busy.", {"Retry-After": "1"}
                )
            body = bytearray()
            disconnected = oversized = False
            try:
                async with asyncio.timeout(self.security.body_timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            disconnected = True
                            break
                        chunk = message.get("body", b"")
                        if len(chunk) > BODY_LIMIT - len(body):
                            oversized = True
                            break
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                timed_out = True
            else:
                timed_out = False
            finally:
                self.admission.leave_reader()
            if timed_out:
                return await reject(408, "body_timeout", "Request body deadline exceeded.")
            if disconnected:
                return
            if oversized:
                return await reject(413, "body_too_large", "Request body exceeds 8192 bytes.")
            if declared is not None and declared != len(body):
                return await reject(400, "invalid_request", "Content length differs from the body.")
            try:
                json.loads(
                    body.decode("utf-8"),
                    object_pairs_hook=_unique_object,
                    parse_constant=_no_constant,
                    parse_float=_finite_float,
                )
            except (ValueError, UnicodeError, RecursionError):
                return await reject(
                    400,
                    "invalid_json",
                    "Request body must contain valid UTF-8 JSON with unique keys and finite values.",
                )

            supplied = False

            async def replay():
                nonlocal supplied
                if not supplied:
                    supplied = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, tagged_send)
        return await self.app(scope, receive, tagged_send)
