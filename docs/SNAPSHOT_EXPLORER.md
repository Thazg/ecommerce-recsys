# RecoLens snapshot explorer

Explore [RecoLens](https://ecommerce-recsys.vercel.app/), a static demonstration
of verified Retailrocket model outputs. It shows four returning-user profiles
and one first-visit context from the immutable fold-9 snapshot. It makes no API
calls and performs no model inference in the browser. The
[hosting runbook](STATIC_DEMO_DEPLOYMENT.md) records static publication and its
verification scope; the recommendation API remains local.

## Run locally

From the repository root, use the existing `ecommerce-recsys` environment:

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory demo
```

Open `http://127.0.0.1:8765/`. Stop the server with Ctrl+C. Serve only `demo/`,
not the repository root. Binding to loopback keeps this preview local. No cloud
account, model download, dependency install, API token or model startup is needed
to browse the included examples. Opening `index.html` directly as a `file:` URL
does not support the required JSON fetch and integrity check.

## What can be explored

- Choose four anonymous returning-user profiles or the first-visit context.
- Compare learned ranking with RRF retrieval order from the **same** warm
  1,000-item full-hybrid candidate pool.
- Display Top-5/10/20 prefixes without changing model output.
- Expand a product to inspect its fused-pool position and contributing source ranks.
- Inspect model version, historical cutoff and manifest digest; download example data.

First visits use recent popularity only. The interface does not simulate history
updates, training, latency, overload, cache events or live API health. Source-list
ranks are retrieval evidence, not feature contributions, probabilities or causal
reasons why the learned ranker selected an item.
The RRF comparison is labelled separately from the locked warm/cold routes.

Retailrocket supplies anonymous item/category codes without verified product
names, prices, photographs or semantic category names. Unknown categories stay
explicit. Original user IDs, full histories, future targets, private paths,
credentials, factors and full candidate pools are not exported.

## Export and provenance

[Example data](../demo/data/showcase_v1.json) binds the unchanged model manifest,
sealed-reference file, exporter and inference implementation. Four warm examples
use fixed zero-based positions `0, 25, 50, 75` of the 100 sealed warm references;
the final sealed reference is the explicit cold context. No future outcome or
quality score selects examples. All four warm examples have **one previously
seen item**; this is not representative activity coverage or an accuracy estimate.

The exporter loads the original bundle in its compatible producer environment,
checks inventory against the external manifest pin, and requires exact
pool/output/route/evidence/feature/score trace equality for each sealed reference.
It regenerates candidate evidence and checks catalog membership and the full
seen set before projecting allowlisted public fields. Publication is atomic and
non-overwriting.
Output paths must resolve outside the immutable input bundle; this is checked
before loading and again before publication, including aliases through symlink
parents. Exporting examples cannot add files to the sealed bundle inventory.

```powershell
python scripts/export_snapshot_demo.py --bundle artifacts/retailrocket-fold09-v1 --output .local/showcase-repeat.json
python scripts/verify_project_documentation.py
pytest tests/unit/test_snapshot_demo.py tests/unit/test_snapshot_demo_verification.py
node --test --test-isolation=none tests/web/test_snapshot_demo.mjs
```

The download has one 10-second deadline spanning response headers and body.
Streamed content is capped at 256,000 bytes before it is retained; an absent or
understated Content-Length does not bypass that cap. Timeout and overflow abort
the request and cancel the owned reader without waiting for cancellation to finish.
The browser checks strict schema and canonical SHA-256 content identity before
showing examples. It renders text nodes and uses no external fonts, analytics,
account inputs or arbitrary backend URL. Bad/missing data hides results and
shows an error; methodology remains readable. Without JavaScript, a notice links
downloadable data. This digest detects inconsistent content; it is not a signature
against someone able to replace both page and data. A static host still observes
ordinary HTTP connection metadata; no hosting privacy guarantee is inferred.

The [released presentation record](../benchmarks/demo/showcase_presentation_validation_v1.json)
pins the deployed public files, export identity and original documentation. The
[original validation](../benchmarks/demo/showcase_validation_v1.json) retains
sealed-trace checks and original interface identity. These receipts keep their
historical documentation fingerprints. The current
[documentation gate](REPRODUCIBILITY.md#check-the-current-documentation) checks
the released asset pins, evidence bytes and evolving docs without loading the
model. It does not rerun browser review, sealed references or model quality.
To check an original broad demo receipt, use its original source checkout;
do not update that receipt's SHA fields for later documentation changes.
Unlisted files/directories and symlinks in the served `demo/` directory are
rejected, so private material cannot silently expand the verified public inventory.
Historical local prototypes are private scratch material, not published releases.
Python tests cover trace mismatches,
seen/foreign/duplicate candidates, cold routing, privacy projection, finite
evidence and non-overwriting publication. Node's built-in tests exercise the
actual public data, schema/checksum failures and Top-K prefixes. Web tests use
the explicit local command; existing hosted Python CI does not execute them.
Transport tests cover stalled headers/body, byte overflow, invalid UTF-8 and HTTP
errors. The directory-symlink regression may skip on Windows when the account
lacks link privileges; the validation record reports that skip explicitly.
Browser review covers controls, row expansion, keyboard operation and responsive
layouts. External static-host checks are recorded separately; no new full-fold
quality evaluation is claimed.

## Hosting boundary

Vercel serves the seven reviewed files under `demo/` without Python, a model
bundle, database or runtime secret. The CLI upload is restricted by
`.vercelignore`; root `vercel.json` declares static output and security headers.
The [hosting runbook](STATIC_DEMO_DEPLOYMENT.md) identifies measured releases and
public checks. Static publication does not deploy the recommendation API or
satisfy its approximately 2.26 GiB process-memory requirement. See the separate
[full-model deployment design](DEPLOYMENT_DESIGN.md).

The [offline assessment](../benchmarks/deployment/deployment_assessment_v1.json)
and hosting catalog remain unchanged dated design evidence. Full-model host
selection, deployment and target-host verification remain open. Static demo
publication does not mark those milestones complete. Later offline folds
remain post-selection diagnostics, not blind validation; these examples do not
establish online benefit or production readiness.
