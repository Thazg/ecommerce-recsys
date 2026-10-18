"""Early HTTP policy checks, independent of the model and numerical admission."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Denial:
    status: int
    code: str
    message: str
    headers: tuple[tuple[str, str], ...] = ()


class RequestGuards:
    def __init__(self, policy, admission):
        self.policy, self.admission = policy, admission

    def inspect(self, scope, headers):
        p = self.policy
        target_size = len(scope.get("raw_path", scope["path"].encode()))
        query = scope.get("query_string", b"")
        if target_size + len(query) + bool(query) > p.target_limit:
            return Denial(400, "invalid_request", "Request target exceeds the local limit.")
        size = 2 + sum(len(k) + len(v) + 4 for k, v in scope.get("headers", []))
        if size > p.header_limit:
            return Denial(431, "headers_too_large", "Request headers exceed the local limit.")
        hosts = headers.get(b"host", [])
        if len(hosts) != 1 or not p.valid_host(hosts[0]):
            return Denial(400, "invalid_host", "Host is not a configured local authority.")
        origins = headers.get(b"origin", [])
        if origins and (len(origins) != 1 or not p.valid_origin(origins[0], hosts[0])):
            return Denial(403, "forbidden_origin", "Origin is not permitted.")
        recommendation = scope["path"].rstrip("/") == "/v1/recommendations"
        if recommendation and scope["method"] == "POST":
            client = scope.get("client")
            retry = self.admission.attempt(client[0] if client else None)
            if retry:
                return Denial(
                    429,
                    "rate_limited",
                    "Recommendation request budget exhausted.",
                    (("Retry-After", str(retry)),),
                )
        if scope["path"] != "/health/live" and not p.authenticated(
            headers.get(b"authorization", [])
        ):
            return Denial(
                401,
                "unauthorized",
                "A valid bearer credential is required.",
                (("WWW-Authenticate", "Bearer"),),
            )
        lengths, encodings = (
            headers.get(b"content-length", []),
            headers.get(b"transfer-encoding", []),
        )
        if (
            b"trailer" in headers
            or len(lengths) > 1
            or len(encodings) > 1
            or (lengths and encodings)
            or (encodings and encodings[0].lower() != b"chunked")
        ):
            return Denial(400, "invalid_request", "Ambiguous request framing is not supported.")
        if lengths and (not lengths[0].isdigit() or len(lengths[0]) > 20):
            return Denial(400, "invalid_request", "Invalid content length.")
        canonical_body = scope["path"] == "/v1/recommendations" and scope["method"] == "POST"
        if not canonical_body and (encodings or (lengths and int(lengths[0]) > 0)):
            return Denial(400, "invalid_request", "This endpoint does not accept a request body.")
        coding = headers.get(b"content-encoding", [])
        if coding and (len(coding) != 1 or coding[0].lower() != b"identity"):
            return Denial(415, "unsupported_media_type", "Content encoding is not supported.")
        return None
