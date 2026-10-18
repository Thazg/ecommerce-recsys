"""Explicit embedded authority and burst budget for pre-hardening regressions.

Those tests exercise model/cache races rather than request quotas. Security tests
use the production factory and prospective defaults directly.
"""

from fastapi.testclient import TestClient as FastAPITestClient

from ecommerce_recsys.serving.app import create_app
from ecommerce_recsys.serving.security import SecuritySettings


def create_fixture_app(*args, **kwargs):
    kwargs.setdefault(
        "security",
        SecuritySettings(
            global_rate=1000,
            global_burst=1000,
            peer_rate=1000,
            peer_burst=1000,
        ),
    )
    return create_app(*args, **kwargs)


class TestClient(FastAPITestClient):
    __test__ = False

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("base_url", "http://127.0.0.1:8000")
        super().__init__(*args, **kwargs)
