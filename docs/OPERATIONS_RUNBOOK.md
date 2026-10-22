# Project operations runbook

## Supported surfaces

| Surface | Current use | Ownership and limits |
| :--- | :--- | :--- |
| [RecoLens](https://ecommerce-recsys.vercel.app/) | Public static demonstration | Seven files on Vercel; precomputed examples, no runtime secrets or API |
| Local static preview | Inspect reviewed UI/data changes | Serve `demo/` on loopback; stop the terminal's owned server with Ctrl+C |
| Local snapshot API | Exercise the original bundle and service contract | One process/active inference worker; pinned bundle, optional bounded cache; approximately 2.26 GiB RSS |
| Isolated Linux qualification | Reproduce an explicitly scoped container gate | External bundle/archive, Docker and declared resource limits; no public ports |

Full-model cloud operations are not implemented. This runbook does not turn
the local release controller into a cloud router or approve a host/budget.
For commands and prerequisites start with [reproducibility](REPRODUCIBILITY.md).

## Before changing or publishing a release

1. Read [current status](PROJECT_STATUS.md), [architecture](ARCHITECTURE_CURRENT.md)
   and the relevant contract. Identify whether the change affects presentation,
   inference, service behavior, data, protocol or only documentation.
2. Check the tree and run the relevant test profiles. Preserve published JSON,
   original model pins and the source revision of each prior measurement.
3. Freeze the intended source and record evidence to new paths. Failed resource
   or quality gates remain recorded failures, not reasons to change a lock.
4. Review the exact commit/upload inventory. Keep raw data, model files, secrets,
   local notes and request logs outside Git and static uploads.
5. Publish only an approved release. Verify actual hosted behavior after a static
   deploy; configuration tests alone do not establish provider behavior.

Static releases use the [Vercel runbook](STATIC_DEMO_DEPLOYMENT.md), with manual
CLI delivery and no Git provider connection. The reviewed prior deployment ID is
recorded in each hosting receipt. Restoring a prior static deployment requires
an explicit operator action and fresh checks; a recorded ID is not a completed
rollback exercise. Do not enable paid resources or expand repository access as
part of routine verification.

## Local API start, readiness and stop

Verify the independent manifest pin and compatible numerical environment before
starting the [supported launcher](RECOMMENDATION_API.md#run-locally). Keep the
bundle read-only and use one process. `/health/live` establishes process
liveness; `/health/ready` establishes whether this service accepts model work.
Do not expose the loopback API by changing bind addresses or attaching a public
tunnel; public exposure requires its own contract and qualification.

Cache is off and busy policy is `reject` by default. Health/metrics requests
do not run models. Stop the owned server with Ctrl+C and allow accepted work to
drain; no inference preemption/deadline is implemented. A failed primary makes
readiness false until restart. Never repair model corruption by returning a
successful cold result.

## Failure triage

| Symptom | Action | Avoid |
| :--- | :--- | :--- |
| Static page cannot verify examples | Check hosted asset hashes, JSON identity, console/CSP and absolute download deadline; restore a reviewed deployment if authorized | Fabricated sample results or disabling the checksum |
| Documentation receipt is stale | Identify intentional docs/source changes, rerun checks and publish a new record | Replacing old digest fields to force a pass |
| Model pin or component mismatch | Stop startup; recover the trusted immutable bundle/manifest and verify inventory | Rehashing an unknown download and adopting that digest |
| Busy 503 / quota 429 | Review separate admission and request budgets; preserve outcome counters | Counting fast rejection as inference latency or silently relaxing quotas |
| Model inference error / unready state | Capture safe operational evidence, stop/restart the verified instance, investigate the fault | Hidden popularity success, logging payloads or releasing admission before worker completion |
| RSS above 2 GiB | Retain the failed gate; investigate an independently measured optimization or explicit prospective scope decision | Claiming compliance because the container allows 4 GiB |
| Interrupted isolated release | Use the pinned controller checkout/store and documented journal recovery | Deleting journals/owned processes or guessing active state |

See [input controls](API_HARDENING.md), [cache/fallback](SERVICE_CACHE_AND_FALLBACKS.md),
[observability](OBSERVABILITY.md) and [controlled local recovery](RELEASE_WORKFLOW.md).
Only owned fixed-schema events have the stated redaction guarantee; third-party
streams may differ. Do not copy raw user IDs, bearer credentials, request bodies,
private paths, factor arrays or private traces into public issues or receipts.

## Recovery prerequisites

Keep trusted code/image identities, model components, manifest pins and private
numerical references in independently recoverable storage. The model is not
recoverable from a Git clone alone. A receipt preserves provenance; it cannot
reconstruct a deleted factor array. Rebuilding may require the original dataset,
environment and substantial fitting time, and a fresh version must be verified.

The existing [release workflow](RELEASE_WORKFLOW.md) exercises isolated local
same-model rollback and crash recovery. Native-host/daemon power-loss recovery,
cloud routing, alert delivery, external load and an RTO/RPO remain unqualified.
M26/M27 remain open; static demo availability does not close them.
