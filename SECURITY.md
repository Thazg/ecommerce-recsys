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
