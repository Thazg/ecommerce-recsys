"""One loaded snapshot and bounded inference, independent of HTTP routing."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from threading import BoundedSemaphore
from time import perf_counter

from ecommerce_recsys.artifacts import Recommendation, load_bundle
from ecommerce_recsys.artifacts.contract import POLICY, digest
from ecommerce_recsys.retrieval.base import RetrievalContext
from ecommerce_recsys.serving.cache import ResultCache
from ecommerce_recsys.serving.contracts import (
    CacheHealth,
    ModelIdentity,
    RecommendationRequest,
    RecommendationResponse,
    ServedRecommendationResponse,
    ServiceSettings,
    valid_identifier,
)
from ecommerce_recsys.serving.observability import Telemetry

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
        self._cleanup_task = None
        self._startup_started = None
        self._startup_outcome = None
        self._startup_observed = False
        self.cache = None
        self.cache_failures = 0
        self.primary_calls = 0
        self.fallback_calls = 0
        self.fallback_pool = ()
        self.telemetry = Telemetry()

    def _load(self):
        # Startup smoke and predictions share the same process-wide boundary.
        with _PROCESS_PERMIT:
            if self.state != State.STARTING:
                return
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
            if self.settings.busy_policy == "recent_popularity":
                if self.bundle.cold.name != POLICY["cold"]:
                    raise ValueError("Fallback requires the snapshot recent-popularity source.")
                self.fallback_pool = tuple(
                    candidate.item_id
                    for candidate in self.bundle.cold.generate(
                        RetrievalContext(), POLICY["candidate_budget"]
                    )
                )
                if (
                    len(self.fallback_pool) > POLICY["candidate_budget"]
                    or len(set(self.fallback_pool)) != len(self.fallback_pool)
                    or not set(self.fallback_pool).issubset(self.catalog)
                ):
                    raise ValueError("Invalid prepared fallback inventory.")
                for item in self.fallback_pool:
                    if type(item) is not str or not 1 <= len(item) <= 128:
                        raise ValueError("Fallback requires bounded string IDs.")
                    valid_identifier(item)
            if self.settings.cache_max_entries:
                namespace = digest(
                    {
                        "manifest_sha256": self.settings.manifest_sha256,
                        "policy": POLICY,
                        "context": "snapshot-user-or-cold",
                        "output_limit": 20,
                    }
                )
                self.cache = ResultCache(
                    namespace,
                    max_entries=self.settings.cache_max_entries,
                    max_bytes=self.settings.cache_max_bytes,
                    ttl_seconds=self.settings.cache_ttl_seconds,
                    on_event=self.telemetry.cache_event,
                )
            self.load_seconds = perf_counter() - started

    async def start(self):
        if self.executor is not None or self.state != State.STARTING:
            raise StartupFailed("Service lifecycle cannot be restarted.")
        self._startup_started = perf_counter()
        try:
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recommendation")
            await asyncio.get_running_loop().run_in_executor(self.executor, self._load)
        except BaseException as error:
            if self.state != State.STOPPED:
                self.state = State.FAILED
            if self._startup_outcome is None:
                self._startup_outcome = (
                    "startup_cancelled"
                    if isinstance(error, asyncio.CancelledError)
                    else "startup_failed"
                )
            # The owned drain records this even if its caller is cancelled again.
            await self._cleanup()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise StartupFailed("Recommendation model startup failed.") from error
        if self.state != State.STARTING or self._cleanup_task is not None:
            await self._cleanup()
            raise StartupFailed("Recommendation startup stopped before readiness.")
        self.state = State.READY
        self.telemetry.bind_model(self.identity.bundle_version, self.settings.manifest_sha256)
        self._record_startup("startup_ready")

    def _record_startup(self, outcome):
        if self._startup_started is not None and not self._startup_observed:
            self._startup_outcome = outcome
            self._startup_observed = True
            self.telemetry.event(outcome, duration=perf_counter() - self._startup_started)

    def readiness(self):
        # One state sample keeps HTTP readiness status/body consistent on worker failure.
        state = self.state
        healthy = (
            state == State.READY
            and self.bundle is not None
            and self.identity is not None
            and self.executor is not None
        )
        return state, healthy

    def _require_ready(self):
        if not self.readiness()[1]:
            self.telemetry.admission("not_ready")
            raise NotReady()

    def _mark_failed(self):
        if self.state != State.STOPPED:
            self.state = State.FAILED
        self.cache = None
        self.fallback_pool = ()

    def _predict(self, user_id, k, request_id):
        result = self.bundle.recommend(user_id, k=k)
        return self._validate_result(user_id, result, k, request_id)

    def _validate_result(self, user_id, result, k, request_id):
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

    def _deliver(self, value, k, request_id, cache_status, *, degraded=False):
        return ServedRecommendationResponse(
            request_id=request_id,
            items=list(value.items[:k]),
            route=value.route,
            bundle_version=value.bundle_version,
            cutoff=value.cutoff,
            manifest_sha256=self.settings.manifest_sha256,
            cache_status=cache_status,
            degraded=degraded,
            degraded_reason="busy" if degraded else None,
        )

    def _disable_cache(self):
        self.cache = None
        self.cache_failures += 1
        self.telemetry.event("cache_disabled")

    def _fallback(self, user_id, k, request_id):
        self._require_ready()
        try:
            seen = frozenset(self.bundle.context(user_id).history)
            items = tuple(item for item in self.fallback_pool if item not in seen)[:k]
            if not set(items).issubset(self.catalog):
                raise ValueError("Prepared fallback returned an out-of-catalog item.")
            result = Recommendation(
                items,
                "recent_popularity_fallback",
                self.identity.bundle_version,
                self.identity.cutoff,
            )
            response = self._deliver(result, k, request_id, "bypass", degraded=True)
            self._require_ready()
        except NotReady:
            raise
        except Exception as error:
            self._mark_failed()
            self.telemetry.event("fallback_failed", request_id=request_id)
            # Admission belongs to the already running primary worker, not this path.
            raise InferenceFailed() from error
        self.fallback_calls += 1
        return response

    def cache_info(self):
        def validated(stats, enabled):
            return CacheHealth(
                enabled=enabled,
                **stats,
                failures=self.cache_failures,
                max_entries=self.settings.cache_max_entries,
                max_bytes=self.settings.cache_max_bytes,
                ttl_seconds=float(self.settings.cache_ttl_seconds),
            ).model_dump()

        cache = self.cache
        if cache is not None:
            try:
                return validated(cache.snapshot(), True)
            except Exception:
                self._disable_cache()
        return validated(
            dict.fromkeys(
                (
                    "entries",
                    "charged_bytes",
                    "hits",
                    "misses",
                    "evictions",
                    "expirations",
                    "oversized",
                ),
                0,
            ),
            False,
        )

    def _execute(self, user_id, k, request_id, cache_status):
        started, outcome = perf_counter(), "failed"
        self.telemetry.primary_started()
        try:
            self.primary_calls += 1
            response = self._predict(user_id, 20 if cache_status == "miss" else k, request_id)
            value = Recommendation(
                tuple(response.items), response.route, response.bundle_version, response.cutoff
            )
            cache = self.cache
            if cache is not None and cache_status == "miss" and self.state == State.READY:
                try:
                    cache.put(user_id, value)
                except Exception:
                    self._disable_cache()
                    cache_status = "bypass"
            response = self._deliver(value, k, request_id, cache_status)
            if self.state == State.FAILED:
                outcome = "invalidated"
                raise NotReady()
            outcome = "success"
            return response
        except NotReady:
            raise
        except Exception as error:
            self._mark_failed()
            self.telemetry.event("primary_failed", request_id=request_id)
            raise InferenceFailed() from error
        finally:
            self.telemetry.primary_finished(outcome, perf_counter() - started)
            _PROCESS_PERMIT.release()

    async def recommend(self, user_id, k, request_id):
        request = RecommendationRequest(user_id=user_id, k=k)
        user_id, k = request.user_id, request.k
        self._require_ready()
        # Unknown IDs share one immutable, history-free cold snapshot context.
        user_id = user_id if user_id in self.bundle.user_index else None
        cache_status = "disabled" if not self.settings.cache_max_entries else "bypass"
        cache = self.cache
        if cache is not None:
            try:
                value = cache.get(user_id)
                if value is not None:
                    self._validate_result(user_id, value, 20, request_id)
                    self._require_ready()
                    return self._deliver(value, k, request_id, "hit")
                cache_status = "miss"
            except NotReady:
                raise
            except Exception:
                self._disable_cache()
                cache_status = "bypass"
        if not _PROCESS_PERMIT.acquire(blocking=False):
            if self.settings.busy_policy == "recent_popularity":
                self.telemetry.admission("busy_fallback")
                return self._fallback(user_id, k, request_id)
            self.telemetry.admission("busy_rejected")
            raise Busy()
        # A previous worker may fail during cache lookup, before releasing admission.
        # Recheck after owning its permit; never submit fresh work in FAILED state.
        if not self.readiness()[1]:
            _PROCESS_PERMIT.release()
            self.telemetry.admission("not_ready")
            raise NotReady()
        self.telemetry.admission("accepted")
        try:
            future = asyncio.get_running_loop().run_in_executor(
                self.executor, self._execute, user_id, k, request_id, cache_status
            )
        except Exception as error:
            _PROCESS_PERMIT.release()
            self._mark_failed()
            self.telemetry.event("submission_failed", request_id=request_id)
            raise InferenceFailed() from error
        # Cancelled HTTP tasks do not release admission while their worker runs.
        # Retrieve late exceptions even if the original HTTP waiter was cancelled.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(future)

    async def _close(self):
        executor, self.executor = self.executor, None
        if executor is not None:
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=False)
        self.bundle = None
        self.identity = None
        self.catalog = frozenset()
        self.cache = None
        self.fallback_pool = ()
        self.telemetry.event("cleanup_complete")
        self._record_startup(self._startup_outcome or "startup_stopped")
        self.telemetry.clear_model()

    async def _cleanup(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._close())
        # Startup failure, cancellation and stop share one uncancellable drain.
        await asyncio.shield(self._cleanup_task)

    async def stop(self):
        self.state = State.STOPPED
        if self._startup_started is not None and self._startup_outcome is None:
            self._startup_outcome = "startup_stopped"
        await self._cleanup()
