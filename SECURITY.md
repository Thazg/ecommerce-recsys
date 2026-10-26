# Security policy

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/Thazg/ecommerce-recsys/security/advisories/new)
when available. If the private form is unavailable, open an issue requesting a
private reporting channel, without exploit details or sensitive attachments.

Include the affected revision, component, prerequisites, impact and a minimal
reproduction using synthetic data. Do not send credentials, raw user histories,
private model files or unredacted request logs. No response-time SLA is promised.

## Supported scope

Reports should target the current `main` implementation. Historical benchmark
and verification records describe their pinned source revisions; they are not
maintained service releases.

The recommendation API is supported on loopback with a verified historical
snapshot. Shared operator credentials do not provide per-user authorization.
Public exposure, tunnels and untrusted request-time histories are outside its
current contract. The two hosted demos are static and do not call this API.
See the [input/access contract](docs/API_HARDENING.md) and
[operations runbook](docs/OPERATIONS_RUNBOOK.md) for supported behavior.

## Credential handling

Keep credentials in operator-managed environment variables or external files.
Example configuration must use placeholders. If a credential is exposed, revoke
or rotate it before considering cleanup; removing a file does not invalidate
the credential. Never post it in an issue or a public test report.

## Dependency advisory assessment

Reviewed on 2026-10-26. Dependabot reports ten alerts across the Windows
development and Linux CI locks, covering the five advisories below. These exact
locks retain historical numerical and build compatibility. Alerts remain open;
the controls below are scoped mitigations, not patched dependency versions.

| Advisory | Project exposure and handling |
| :--- | :--- |
| [Arrow IPC pre-buffering](https://github.com/advisories/GHSA-rgxp-2hwp-jwgg) | The advisory explicitly excludes Python bindings. This project uses Python Parquet APIs and does not call the affected C++ IPC pre-buffering API. |
| [pytest temporary directories](https://github.com/advisories/GHSA-6w46-j5rx-g56g) | The advisory concerns UNIX temporary-directory handling. Hosted CI creates a fresh, owner-only temporary parent before pytest. Use the same isolation on shared UNIX hosts; do not run historical test environments with elevated privileges. |
| [wheel unpack path traversal](https://github.com/advisories/GHSA-8rrh-rw8j-w5fx) | The project does not invoke `wheel unpack`. Installation uses checksum-pinned binary wheels through pip. Do not unpack untrusted distributions with the historical tooling. |
| [setuptools sdist exclusions](https://github.com/advisories/GHSA-h35f-9h28-mq5c) | The affected path concerns Unicode exclusions in source distributions, especially on macOS. No source distribution is published by these workflows; source-package publication needs a separately reviewed toolchain. |
| [setuptools legacy wheel installation](https://github.com/advisories/GHSA-xmj3-9gf7-h52w) | The affected path is legacy `install_as_egg` on Windows. It is not called by project code or supported installation commands. Install only the pinned distributions and trusted local checkout. |

Do not reuse these environments as general-purpose package-building services.
Dependency modernization remains maintenance work: introduce separately tested
locks and reconcile package constraints, numerical bundle compatibility and CI
policy together. Preserve published receipts and their original environment
identities rather than editing historical hashes or dismissing alerts to obtain
an empty dashboard.
