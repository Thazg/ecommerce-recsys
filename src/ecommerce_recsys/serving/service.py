"""One loaded snapshot and bounded inference, independent of HTTP routing."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from threading import BoundedSemaphore
from time import perf_counter

from ecommerce_recsys.artifacts import Recommendation, load_bundle
from ecommerce_recsys.serving.contracts import (
    ModelIdentity,
    RecommendationRequest,
    RecommendationResponse,
    ServiceSettings,
)

logger = logging.getLogger(__name__)
# Numerical thread limits in the frozen adapter affect the entire process.
_PROCESS_PERMIT = BoundedSemaphore(1)


class State(StrEnum):
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    STOPPED = "stopped"


class NotReady(Exception):
    pass


class Busy(Exception):
    pass


class InferenceFailed(Exception):
    pass


class StartupFailed(RuntimeError):
    pass


class RecommendationService:
    def __init__(self, settings: ServiceSettings, *, loader=load_bundle):
        self.settings = settings
        self.loader = loader
        self.state = State.STARTING
        self.bundle = None
        self.identity = None
        self.catalog = frozenset()
        self.executor = None
        self.load_seconds = None
        self._stop_task = None

    def _load(self):
        # Startup smoke and predictions share the same process-wide boundary.
        with _PROCESS_PERMIT:
            started = perf_counter()
            self.bundle = self.loader(
                self.settings.bundle_path, expected_manifest_sha256=self.settings.manifest_sha256
            )
            self.identity = ModelIdentity(
                bundle_version=self.bundle.manifest["bundle_version"],
                cutoff=self.bundle.manifest["snapshot"]["cutoff"],
            )
            self.catalog = frozenset(self.bundle.items)
            if not self.catalog or any(
                not isinstance(item, str) or not item for item in self.catalog
            ):
                raise ValueError("Snapshot requires a nonempty string catalog.")
            self._predict(None, 20, "startup")
            user = next(iter(self.bundle.user_index), None)
            if user is not None:
                self._predict(user, 20, "startup")
            self.load_seconds = perf_counter() - started

    async def start(self):
        if self.executor is not None or self.state != State.STARTING:
            raise StartupFailed("Service lifecycle cannot be restarted.")
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recommendation")
        try:
            await asyncio.get_running_loop().run_in_executor(self.executor, self._load)
        except BaseException as error:
            self.state = State.FAILED
            await self._shutdown_executor()
            self.bundle = None
            self.catalog = frozenset()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise StartupFailed("Recommendation model startup failed.") from error
        self.state = State.READY

    def _predict(self, user_id, k, request_id):
        result = self.bundle.recommend(user_id, k=k)
        if not isinstance(result, Recommendation) or type(result.items) is not tuple:
            raise ValueError("Model returned an unsupported recommendation object.")
        response = RecommendationResponse(
            request_id=request_id,
            items=list(result.items),
            route=result.route,
            bundle_version=result.bundle_version,
            cutoff=result.cutoff,
        )
        expected_route = (
            "hybrid_learned" if user_id in self.bundle.user_index else "recent_popularity"
        )
        if (
            len(response.items) > k
            or response.route != expected_route
            or response.bundle_version != self.identity.bundle_version
            or response.cutoff != self.identity.cutoff
            or not set(response.items).issubset(self.catalog)
            or set(response.items).intersection(self.bundle.context(user_id).history)
        ):
            raise ValueError("Model output violates the snapshot recommendation contract.")
        return response

    def _execute(self, user_id, k, request_id):
        try:
            return self._predict(user_id, k, request_id)
        except Exception as error:
            if self.state == State.READY:
                self.state = State.FAILED
            logger.exception("Recommendation execution failed; service requires restart.")
            raise InferenceFailed() from error
        finally:
            _PROCESS_PERMIT.release()

    async def recommend(self, user_id, k, request_id):
        request = RecommendationRequest(user_id=user_id, k=k)
        user_id, k = request.user_id, request.k
        if self.state != State.READY or self.bundle is None or self.executor is None:
            raise NotReady()
        if not _PROCESS_PERMIT.acquire(blocking=False):
            raise Busy()
        try:
            future = asyncio.get_running_loop().run_in_executor(
                self.executor, self._execute, user_id, k, request_id
            )
        except Exception as error:
            _PROCESS_PERMIT.release()
            self.state = State.FAILED
            raise InferenceFailed() from error
        # Cancelled HTTP tasks do not release admission while their worker runs.
        # Retrieve late exceptions even if the original HTTP waiter was cancelled.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(future)

    async def _shutdown_executor(self):
        if self.executor is not None:
            executor, self.executor = self.executor, None
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=False)

    async def _close(self):
        await self._shutdown_executor()
        self.bundle = None
        self.catalog = frozenset()

    async def stop(self):
        if self._stop_task is None:
            self.state = State.STOPPED
            self._stop_task = asyncio.create_task(self._close())
        # Multiple/cancelled shutdown waiters must not clear an active worker's model.
        await asyncio.shield(self._stop_task)
