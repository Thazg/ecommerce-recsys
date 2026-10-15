"""Immutable offline recommendation snapshots; no training dependency at inference."""

from ecommerce_recsys.artifacts.runtime import Recommendation, load_bundle

__all__ = ["Recommendation", "load_bundle"]
