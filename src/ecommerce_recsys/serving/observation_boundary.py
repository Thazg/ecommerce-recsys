"""Observe ASGI completion, including validation rejects and cancelled waiters."""

from __future__ import annotations

import asyncio
from time import perf_counter

from ecommerce_recsys.serving.boundary import error_response


class ObservationBoundary:
    def __init__(self, app, *, telemetry):
        self.app, self.telemetry = app, telemetry

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = perf_counter()
        status, outcome, completed_at = None, "aborted", None
        response_started = disconnected = False

        async def observed_receive():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def observed_send(message):
            nonlocal status, response_started, completed_at, outcome
            await send(message)
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                completed_at, outcome = perf_counter(), "completed"

        try:
            return await self.app(scope, observed_receive, observed_send)
        except asyncio.CancelledError:
            if completed_at is None:
                outcome = "cancelled"
            raise
        except Exception:
            if response_started:
                # Do not include backend exception text in a server-level traceback.
                raise RuntimeError("HTTP response could not complete.") from None
            state = scope.setdefault("state", {})
            state["telemetry_error"] = "internal_error"
            return await error_response(
                state.get("request_id", "unavailable"),
                500,
                "internal_error",
                "The request could not be completed.",
            )(scope, observed_receive, observed_send)
        finally:
            if completed_at is None and disconnected and outcome != "cancelled":
                outcome = "disconnected"
            self.telemetry.http(scope, status, outcome, (completed_at or perf_counter()) - started)
