# Static demo deployment

## Scope

The [snapshot explorer](SNAPSHOT_EXPLORER.md) is hosted at
[ecommerce-recsys.vercel.app](https://ecommerce-recsys.vercel.app/).
The first static release was verified on 2026-10-22 using the Hobby workspace.
The [hosting verification record](../benchmarks/demo/static_hosting_validation_v1.json)
records deployment identity, file hashes and the checks below.
Subsequent releases receive separate verification records in the
[demo evidence directory](../benchmarks/demo/).

The hosted application consists of seven frontend/data files. Recommendations
are precomputed outputs from the unchanged model snapshot; no Python inference,
model weights, API service, user lookup, database or runtime secret is deployed.
Full-model hosting and target-host qualification remain separate open milestones.

## Project settings

Use the personal Hobby plan for this non-commercial portfolio demonstration,
subject to current account eligibility and usage limits. See
[Vercel plans](https://vercel.com/docs/plans). Do not enable paid resources or
purchase a domain as part of this setup.

The root [configuration](../vercel.json) explicitly selects static output:

| Setting | Value |
| :--- | :--- |
| Root Directory | Repository root (`.`) |
| Framework Preset | Other (`framework: null`) |
| Install Command | Empty; dependency installation skipped |
| Build Command | Empty; existing files served without building |
| Output Directory | `demo` |
| Automatic Git deployments | Disabled; publish reviewed deployments explicitly |
| Runtime environment variables | None required |

The project root must contain `vercel.json`. Choosing `demo/` as the project root
would bypass this root-level configuration, including its response headers.
See [static configuration](https://vercel.com/docs/project-configuration/vercel-json)
and [manual Git deployment policy](https://vercel.com/docs/project-configuration/git-configuration).

## Delivery and headers

The [.vercelignore allowlist](../.vercelignore) permits only `vercel.json` and the
seven reviewed files under `demo/` for CLI upload. All other root and nested
paths remain excluded, including private plans, raw data, model artifacts, source,
test reports and local Vercel project metadata. Keep `.vercel/` outside Git.
See [Vercel ignore semantics](https://vercel.com/docs/deployments/vercel-ignore).

CLI filtering does not prove that a Git integration cannot read repository
source. Review provider permissions separately; grant access only to the intended
repository when an integration is needed. Only `demo/` is configured as served
output. This configuration does not make the source repository public.

Responses request a same-origin Content Security Policy, anti-framing,
`nosniff`, no referrer, disabled camera/microphone/geolocation and cache
revalidation. No wildcard CORS, external backend proxy, application fallback
rewrite, serverless function or API credential is configured. CSP is a browser
control, not authentication. Verify actual headers after deployment; a local
JSON policy check cannot establish provider behavior.

## Local preflight

Use the `ecommerce-recsys` environment:

```powershell
python scripts/verify_snapshot_demo.py --check benchmarks/demo/showcase_presentation_validation_v1.json
pytest tests/unit/test_static_demo_deployment.py
node --test --test-isolation=none tests/web/test_snapshot_demo.mjs
```

The Python policy tests check static-only settings, response-header intent and
upload exclusions using Git's ignore semantics with representative private and
nested canaries. They also require the current presentation receipt and public
inventory to match. The original export and hosting receipts remain historical
evidence. Git-based tests do not replace the Vercel CLI dry-run: the CLI
must include exactly the seven demo files and `vercel.json` before publication.
Directory exceptions omit trailing slashes so the reviewed CLI version includes
the parent directories during traversal. No previous model/demo receipt is
rewritten for hosting configuration changes.

## Initial verified static release

| Field | Value |
| :--- | :--- |
| Production URL | <https://ecommerce-recsys.vercel.app/> |
| Deployment ID | `dpl_DZj9QZxGcQYtiQxZHrVygWQUWfNX` |
| Frontend source commit | `340e3332094789a2fa14c7362517852fe0219987` |
| Delivery | Vercel CLI 65.1.0; no Git provider connection |
| Upload | Eight files, 90,380 bytes, confirmed by CLI dry-run |
| Hosted assets | Seven of seven byte-identical to the reviewed local files |
| Browser controls | All 27 profile/order/Top-K combinations matched exported item IDs |
| Exposure checks | Eight private or missing paths returned HTTP 404 |
| Transport | Public access without authentication; HTTP redirects to HTTPS |
| Browser evidence | Source details expanded successfully; no captured console warnings or errors |

The frontend/data files come from the source commit above. Deployment configuration
was added separately; its exact bytes are pinned in the hosting record. That record
does not claim these configuration changes were present in the source commit.
The CLI upload omitted model files, raw data, private notes, credentials and source
code outside the static allowlist. Production access was tested without cookies
or authorization headers; preview-deployment access may retain Vercel protection.

The first deployment establishes a known-good static release. Its verification
did not exercise rollback or a narrow mobile viewport. Later checks are recorded
in the subsequent release record. Browser checks and static asset parity do not
establish full accessibility, a load SLO, live model availability or production
readiness.

## Publish and verify

1. Verify a successful source CI run and current presentation identity. Review the
   exact source revision, configuration, upload manifest and account/plan.
2. Configure the project settings above, with no environment secrets or backend
   services. Keep Git-triggered deployment disabled; publish only the reviewed
   revision after operator approval.
3. Record the resulting HTTPS URL, deployment/release identity and source revision.
   Verify all seven hosted asset/data files against reviewed bytes and compare
   downloaded JSON content identity with the original export.
4. Check page loading, all profiles, learned/RRF/cold labels, Top-K prefixes,
   evidence expansion and a narrow mobile viewport. Inspect console failures,
   MIME types, security headers and HTTP-to-HTTPS behavior.
5. Require missing asset and private paths to return an actual 404 without source
   disclosure: `/AGENTS.md`, `/.local/`, `/data/raw/events.csv`, `/model_manifest.json`
   and `/v1/recommendations` are outside the static output. Test the published
   behavior; do not infer isolation only from configuration text.
6. Preserve the prior known-good deployment for rollback; after restoring it,
   recheck its output and identity. Static rollback is separate from model-service
   journal recovery, process draining or native-host recovery.

Do not report a public URL, successful external checks or rollback until those
actions have actually completed. Any later update to the served application needs
fresh source/export identity and appropriate local/hosted checks. A public static
demo does not establish serving latency, online recommendation quality, production
readiness or compliance with the full model's outstanding memory budget.
