"""Shared linear-interpolation percentiles for offline call timings."""

from collections.abc import Sequence

import numpy as np


def latency_metrics(seconds: Sequence[float]) -> dict[str, float | int]:
    values = np.asarray(seconds, dtype=float) * 1000
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Latency samples must be finite and nonnegative.")
    return {
        "latency_samples": len(values),
        "latency_avg_ms": float(values.mean()) if len(values) else 0.0,
        **{
            f"latency_p{q}_ms": float(np.percentile(values, q, method="linear"))
            if len(values)
            else 0.0
            for q in (50, 95, 99)
        },
    }
