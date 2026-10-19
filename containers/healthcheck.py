"""Bounded internal-loopback readiness; no model work or secret output."""

import http.client
import json

from ecommerce_recsys.serving.security import SecuritySettings


def ready():
    policy = SecuritySettings.from_environment(authorities=("127.0.0.1:8000", "localhost:8000"))
    headers = {"Authorization": "Bearer " + policy.token.decode("ascii")} if policy.token else {}
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=3)
    try:
        connection.request("GET", "/health/ready", headers=headers)
        response = connection.getresponse()
        raw = response.read(16385)
        if response.status != 200 or len(raw) > 16384:
            return False
        result = json.loads(raw)
        return (
            isinstance(result, dict)
            and result.get("state") == "ready"
            and result.get("status") == "ready"
        )
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        healthy = ready()
    except (OSError, ValueError, UnicodeError, RecursionError, http.client.HTTPException):
        healthy = False
    raise SystemExit(0 if healthy else 1)
