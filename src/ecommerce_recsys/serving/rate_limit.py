"""Bounded, atomic recommendation attempt admission; never waits or queues."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic


@dataclass
class Bucket:
    tokens: float
    updated: float
    touched: float


class RequestAdmission:
    def __init__(self, policy, *, clock=monotonic):
        self.policy, self.clock = policy, clock
        self.lock = Lock()
        now = clock()
        self.global_bucket = Bucket(float(policy.global_burst), now, now)
        self.peers = {}
        self.readers = 0

    @staticmethod
    def refill(bucket, rate, burst, now):
        bucket.tokens = min(burst, bucket.tokens + max(0, now - bucket.updated) * rate)
        bucket.updated = bucket.touched = now

    def attempt(self, peer):
        """Return 0 on atomic charge, otherwise positive seconds until retry."""
        # Scope.client comes from the socket with proxy_headers=False. A missing
        # embedded client shares one bucket, rather than bypassing the budget.
        peer = peer if isinstance(peer, str) and 0 < len(peer) <= 128 else "unknown"
        p = self.policy
        with self.lock:
            now = self.clock()
            self.peers = {
                key: bucket
                for key, bucket in self.peers.items()
                if now - bucket.touched < p.peer_ttl_seconds
            }
            bucket = self.peers.get(peer)
            if bucket is None and len(self.peers) >= p.peer_entries:
                return max(
                    1,
                    ceil(min(p.peer_ttl_seconds - (now - b.touched) for b in self.peers.values())),
                )
            self.refill(self.global_bucket, p.global_rate, p.global_burst, now)
            prospective = bucket or Bucket(float(p.peer_burst), now, now)
            self.refill(prospective, p.peer_rate, p.peer_burst, now)
            delay = max(
                (1 - self.global_bucket.tokens) / p.global_rate,
                (1 - prospective.tokens) / p.peer_rate,
            )
            if delay > 0:
                return max(1, ceil(delay))
            self.global_bucket.tokens -= 1
            prospective.tokens -= 1
            self.peers[peer] = prospective
            return 0

    def enter_reader(self):
        with self.lock:
            if self.readers >= self.policy.body_readers:
                return False
            self.readers += 1
            return True

    def leave_reader(self):
        with self.lock:
            self.readers -= 1
