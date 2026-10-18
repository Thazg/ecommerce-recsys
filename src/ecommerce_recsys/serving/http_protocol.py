"""Narrow guards for the pinned HTTP/1.1 adapter, before ASGI dispatch."""

from __future__ import annotations

import h11
import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol


def guarded_http_protocol(policy, telemetry):
    """Create one listener's protocol class; fail closed on an unaudited upgrade."""
    if uvicorn.__version__ != "0.54.0" or h11.__version__ != "0.16.0":
        raise ValueError("HTTP guards require Uvicorn 0.54.0 and h11 0.16.0.")

    class GuardedConnection(h11.Connection):
        def __init__(self, owner):
            super().__init__(h11.SERVER, max_incomplete_event_size=policy.header_limit)
            self.owner = owner

        def next_event(self):
            event = super().next_event()
            if isinstance(event, h11.Request):
                self.owner.cancel_header_timer()
                if event.http_version != b"1.1":
                    raise h11.RemoteProtocolError("HTTP/1.1 is required.")
                # HTTP field bytes: name + ': ' + value + CRLF, plus final CRLF.
                fields = 2 + sum(len(k) + len(v) + 4 for k, v in event.headers)
                if fields > policy.header_limit or len(event.target) > policy.target_limit:
                    self.owner.input_limit = True
                    telemetry.transport("input_limit")
                    raise h11.RemoteProtocolError("HTTP input limit exceeded.")
            if (
                isinstance(event, h11.Request)
                and any(name == b"trailer" for name, _ in event.headers)
            ) or (isinstance(event, h11.EndOfMessage) and event.headers):
                # Trailers are not model inputs. Reject declarations before body
                # reads and undeclared trailers before publishing EndOfMessage.
                self.owner.trailers_rejected = True
                telemetry.transport("trailers_rejected")
                raise h11.RemoteProtocolError("Request trailers are not supported.")
            return event

    class HeaderGuardH11Protocol(H11Protocol):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.conn = GuardedConnection(self)
            self.header_timer = None
            self.header_generation = 0
            self.rejected = self.input_limit = False
            self.trailers_rejected = False

        def connection_made(self, transport):
            full = len(self.connections) >= policy.max_connections
            super().connection_made(transport)
            if full:
                self.rejected = True
                telemetry.transport("connection_limit")
                transport.close()
            else:
                self.arm_header_timer()

        def cancel_header_timer(self):
            self.header_generation += 1
            if self.header_timer is not None:
                self.header_timer.cancel()
                self.header_timer = None

        def arm_header_timer(self):
            self.cancel_header_timer()
            generation = self.header_generation
            self.header_timer = self.loop.call_later(
                policy.header_timeout_seconds, self.expire_headers, generation
            )

        def expire_headers(self, generation):
            if generation == self.header_generation and not self.transport.is_closing():
                telemetry.transport("header_timeout")
                self.cancel_header_timer()
                self.transport.close()

        def data_received(self, data):
            if not self.rejected and not self.transport.is_closing():
                super().data_received(data)

        def send_400_response(self, msg):
            self.cancel_header_timer()
            if not (self.input_limit or self.trailers_rejected):
                telemetry.transport("invalid_http")
            super().send_400_response(msg)

        def on_response_complete(self):
            super().on_response_complete()
            # A buffered pipelined Request may already have started a new cycle.
            # Only an idle parser is waiting for a new request's headers.
            if self.conn.their_state is h11.IDLE and not self.transport.is_closing():
                self.arm_header_timer()

        def connection_lost(self, exc):
            self.cancel_header_timer()
            super().connection_lost(exc)

        def shutdown(self):
            self.cancel_header_timer()
            super().shutdown()

    return HeaderGuardH11Protocol
