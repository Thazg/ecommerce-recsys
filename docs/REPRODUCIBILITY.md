# Reproducing the project

## Choose a verification level

The repository includes source, finite example data and historical experiment
records. Raw Retailrocket CSVs, prepared Parquet, fitted model bundles and private
numerical archives are not included. These verification levels require different
inputs and establish different things.

| Level | Inputs | Result | Does not establish |
| :--- | :--- | :--- | :--- |
| Static explorer | Checkout and Python 3.13 | Browse five stored model examples locally | Live inference or current product information |
| Documentation integrity | Checkout and Python standard library | Links, fragments, evidence pins and released demo assets match | External URL availability, fresh tests or model quality |
| Unit and fitted integration | Installed package and optional test dependencies | Current code tests; synthetic models actually fit, export, load and serve | Retailrocket accuracy, original bundle identity or full-model memory |
| Real snapshot | Original external bundle, trusted manifest pin and compatible numerical environment | Explicit producer/reference regression parity | New full-fold quality, blind validation or public deployment |
| Historical experiment reproduction | Correct Git revision, source datasets, prepared inputs and original environment | Re-run a particular experiment under its original contract | Compatibility with every later checkout or byte-identical timings |

## Browse without datasets or a model

The public [RecoLens demo](https://ecommerce-recsys.vercel.app/) displays stored
outputs. To serve the same seven files locally, run from the repository root:

```sh
python -m http.server 8765 --bind 127.0.0.1 --directory demo
```

Open `http://127.0.0.1:8765/`; stop with Ctrl+C. Serve `demo/`, never the
repository root. Do not open `index.html` as a `file:` URL: the browser needs an
HTTP origin for module loading, JSON retrieval and its integrity check.
No Kaggle credentials, cloud account, model files or package install are needed
for this profile. The [explorer contract](SNAPSHOT_EXPLORER.md) explains its
four fixed warm references, one cold example and narrow activity sample.

## Check the current documentation

This standard-library command has no network or model access:

```sh
python scripts/verify_project_documentation.py
```

It validates the explicit
[documentation inventory](../benchmarks/release/documentation_inventory_v1.json),
local Markdown links and heading fragments, pinned historical JSON bytes and the
seven released static assets. External links are counted, not fetched. The
verifier never runs commands copied from Markdown. It rejects unknown static
files, symlinks, unsafe paths, duplicate JSON keys and nonfinite numbers.

To compare against the completed documentation record:

```sh
python scripts/verify_project_documentation.py --check benchmarks/release/project_documentation_validation_v1.json
```

After an intentional source or documentation change, write a new record using
a fresh path; the old record should fail the current-checkout comparison:

```sh
python scripts/verify_project_documentation.py --output .local/documentation-repeat.json
```

Create `.local/` first if absent and choose an unused output name. Publication
does not overwrite files. It fsyncs the JSON file and uses an atomic exclusive
link; this does not claim directory-entry durability through power loss.
The receipt records integrity only. Execution results belong in the separate
verification report and original measured receipts.

## Install and test the Python project

Use the existing `ecommerce-recsys` environment. For a new checkout, the declared
development baseline is Python 3.13; the qualified producer uses 3.13.15.

```sh
conda env create -f environment.yml
conda activate ecommerce-recsys
python -m pip install -e ".[dev]" -r requirements/serving-test.txt -r requirements/release-test.txt
python -m pip check
python -c "import implicit, fastapi, uvicorn, httpx2, yaml, torch, faiss"
python -m ruff check .
python -m ruff format --check .
python -m pytest tests/unit -q
python -m pytest tests/integration -m "not real_bundle" -q
node --test --test-isolation=none tests/web/test_snapshot_demo.mjs
```

Skip `conda env create` when the environment already exists. Native wheels and
package availability are platform-specific; ANN's historical Windows build
failure is documented in the [ANN report](ANN_RETRIEVAL_REPORT.md). The hashed
Linux CI lock in `requirements/ci-linux.txt` is for the pinned Linux CPU lane,
not a Windows install recipe. The fitted-process tests bind loopback ports and
create small synthetic snapshots in temporary directories. They do not need
Retailrocket data, the private full bundle, Docker or cloud credentials.

Node's tests are a separate command; a Python-only test run does not execute
them. Missing optional test dependencies must be installed rather than treated
as evidence that a skipped profile passed. See the
[functional gate contract](TESTING_AND_RELEASE_GATES.md) for explicit real-bundle
opt-in and the [verification report](PROJECT_VERIFICATION_REPORT.md) for commands
actually executed in this documentation pass.

## Run the original local snapshot

The full bundle is outside Git and is not required to review the project. If
you have the trusted original producer bundle and compatible environment:

```sh
python -m scripts.verify_model_artifacts artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --quality-receipt benchmarks/artifacts/fold09_v1.json
python -m ecommerce_recsys.serving --bundle-path artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe
```

These are actual model load/serve commands, unlike the documentation gate.
Run the server in a dedicated terminal and stop with Ctrl+C. The supported API
is loopback-only, one process and one active inference call. Use
`/health/live` and `/health/ready` as specified in the
[API contract](RECOMMENDATION_API.md); a live process alone is not readiness.
Do not copy model IDs, credentials or request bodies into public logs.

The manifest pin comes from independent trusted evidence. Do not replace it
with the digest of an unknown download. A new build gets a new version and its
own receipt/pin; it must not overwrite `retailrocket-fold09-v1` or be claimed
as the original bundle. See the [model contract](MODEL_ARTIFACTS.md),
[bundle directory guide](../artifacts/README.md) and
[operations runbook](OPERATIONS_RUNBOOK.md).

## Re-run historical experiments deliberately

Start with the [evidence index](EVIDENCE_INDEX.md), then the relevant report's
reproduction section. Dataset downloads and exact SHA-256 requirements are
described in the [raw-data guide](../data/raw/README.md). Long model sweeps are
not a documentation check. Use a separate full-history checkout and new scratch
outputs, preserving every frozen JSON file and its serialization.

| Evidence | Reproduction boundary |
| :--- | :--- |
| Historical leave-last-out | Different task/cohort from rolling; preserve the baseline record and do not compare its scores directly |
| Rolling and candidate experiments | Shared cutoff-time catalogs, manifest-bound data and development-only selection; inspected folds 5–9 remain diagnostic |
| Exact Two-Tower and ANN v1 | Reproduce at `7b27f141f8d1a331bc4ebe0e924db59eeeef9e42`; semantic script renames change fingerprints |
| Ranking dataset | Rebuild source at `c80cebee3378ea9af7c9757802fa40e2c8594ae2`, with matching prepared folds and current frozen M10/M11 JSON bytes |
| Original functional gate | Source-bound record at `d8e4a31`; it is not a receipt for all later tests/docs |
| Current static presentation | Released assets/export are pinned separately from the evolving documentation; no model refit is needed for a docs-only change |

See [ranking reproduction](RANKING_DATASET_REPORT.md),
[Two-Tower](TWO_TOWER_REPORT.md), [ANN](ANN_RETRIEVAL_REPORT.md),
[model policy](MODEL_POLICY_REPORT.md) and
[Linux qualification](LINUX_CONTAINER.md). Numerical portability, full-fold
quality, HTTP parity and current-checkout integrity are separate claims.

## Remaining release limits

The public release is a static demo; the API remains local. Full-model hosting,
native target-host recovery and external workload verification remain open.
The approximately 2.26 GiB serving RSS exceeds the 2 GiB target. No clean-room
installation, newly blind evaluation, live cloud API, production workload SLO
or business impact is certified by the documentation gate.
