# Local inference and public demonstration

## Delivery model

The complete snapshot runs on an operator's local machine. The public
[RecoLens site](https://ecommerce-recsys.vercel.app/) illustrates four warm
examples and one cold example using previously verified outputs.

| Surface | Behavior | Inputs |
| :--- | :--- | :--- |
| Local snapshot API | Computes recommendations from the complete pinned model | Existing environment and private model bundle |
| Public RecoLens | Browses stored examples, ranking alternatives and source evidence | Browser only |
| Local RecoLens preview | Serves the same illustrative frontend/data files | Checkout and Python |
| Interactive shopping illustration | Computes explained suggestions from views, hearts and ratings on 100 photographed sample products | Browser and static files; separate from Retailrocket |

Public visitors can review the examples while the operator's computer is off.
The public site has no connection to the loopback API and does not start a model
process when visited. Public model inference and continuous cloud availability
are outside the release scope. M26/M27 in the [roadmap](ROADMAP.md) cover local
operation and verification under [ADR-40](DECISIONS.md#adr-40--define-a-local-backend-release-with-public-static-demonstrations).

## Start real inference locally

Select `ecommerce-recsys` with Python 3.13 and the compatible dependencies from
the [reproduction guide](REPRODUCIBILITY.md). The original bundle is not in Git;
see the [artifact contract](MODEL_ARTIFACTS.md) for its files and trust boundary.

From the repository root:

```sh
conda activate ecommerce-recsys
python -m scripts.serve_local_snapshot --bundle-path artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --port 8000
```

This explicit launcher selects the [indexed reader](SNAPSHOT_MEMORY_REPORT.md).
It retains one inference worker, cache off, busy rejection, trusted loopback
authorities and the existing header/body/rate guards. The original
`python -m ecommerce_recsys.serving` launcher is preserved with its original
reader. Only the explicit local launcher selects indexed state.

Wait for readiness at `http://127.0.0.1:8000/health/ready`.
With no API credential configured, interactive request docs are available at
`http://127.0.0.1:8000/docs`. If `RECSYS_API_TOKEN` or `RECSYS_API_TOKEN_FILE`
is set, the same existing credential rules apply and anonymous docs are disabled.
Keep credentials outside command-line arguments, source, screenshots and the UI.

A cold-route request from PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/recommendations -ContentType 'application/json' -Body '{"k":5}'
```

Known snapshot users can be selected locally with `user_id`; dynamic histories
are outside this API contract. Retailrocket IDs are anonymized identifiers,
without product names, photographs, prices or current availability.

Stop the foreground server with Ctrl+C and allow accepted work to drain. No
automatic model update, cloud wake-up, external ingress or public tunnel is
configured. The launcher fixes `127.0.0.1` and accepts unprivileged local ports.

## Try a shopping interaction

The [shopping demonstration](SHOPPING_DEMONSTRATION.md) provides a more familiar
storefront with product photographs, search, category filters, hearts, ratings
and a recommendation button. Preview it separately:

```sh
python -m http.server 8766 --bind 127.0.0.1 --directory shop-demo
```

Open `http://127.0.0.1:8766/`. It uses an illustrative content-based policy in the
browser; it does not map sample products to Retailrocket IDs or call the local
snapshot API. Preferences stay in the tab's session. The same shopping
illustration is public at [shoprecome.vercel.app](https://shoprecome.vercel.app/);
the separate RecoLens site continues to show stored model examples.

## Preview the illustration

In another terminal:

```sh
python -m http.server 8765 --bind 127.0.0.1 --directory demo
```

Open `http://127.0.0.1:8765/`. If that port already runs the verified preview,
reuse it. Do not stop an unrelated listener or serve the repository root.
The local preview displays stored examples just like the public site; running
the API beside it does not change the frontend into a live inference client.

## Verification

The [current local release report](LOCAL_RELEASE_REPORT.md) covers the pipe-capable
launcher, real HTTP resource/load measurements, telemetry and clean same-port
stop/restart. Its separately pinned receipt meets all declared local targets on
the measured Windows profile. It does not establish public API or Linux load
qualification. The earlier record below retains its pre-pipe launcher identity.

The [local HTTP record](../benchmarks/deployment/local_demonstration_validation_v1.json)
checks a fresh indexed-reader process against all 100 warm and one cold sealed
reference outputs. Six prefix checks and eight authentication/authority/input
denials pass. The probe uses a private ephemeral bearer credential, then reaps
its child and confirms the owned listener closed. No credential or raw user ID
is included in the public record. Terminating the verification child does not
establish graceful-drain performance.

To repeat with a fresh output path:

```sh
python -m scripts.verify_local_demonstration --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output .local/local-demo-repeat.json
```

Create `.local/` if absent. Existing records are not overwritten. Source changes,
partial references, foreign ownership and failed cleanup prevent publication.
The receipt is functional local HTTP evidence; it does not measure RSS, load
capacity, external latency, Linux compatibility or cloud availability. The
[memory assessment](SNAPSHOT_MEMORY_REPORT.md) separately measures package-reader
RSS on Windows. Historical Linux measurements retain their original outcomes.

The final Windows unit run passed 1,255 cases with three existing symlink-privilege
skips. This includes eight local-launcher/cleanup cases and the 37 indexed-reader
and memory-evidence cases. Ruff lint/format and documentation link checks pass.
Current local additions have not received a new hosted Linux CI run.

The [static hosting record](../benchmarks/demo/static_hosting_validation_v2.json)
independently records the public illustration. Original model-quality evidence
and inspected-fold limitations remain unchanged. This delivery choice is
recorded in [ADR-38](DECISIONS.md#adr-38--deliver-local-inference-with-a-static-public-illustration).
