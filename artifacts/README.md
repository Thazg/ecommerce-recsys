# Offline model snapshots

Generated model versions live in `artifacts/<bundle-version>/`. Their arrays,
tables and manifests are excluded from Git. The repository tracks the
[bundle contract and reproduction commands](../docs/MODEL_ARTIFACTS.md) and a
small [validation receipt](../benchmarks/artifacts/fold09_v1.json).

Each immutable version contains a `model_manifest.json`, NumPy factor/weight
arrays and Parquet mappings, seen-item history and feature aggregates. The
manifest binds every component to a checksum, snapshot cutoff, model policy,
source-code fingerprint and numerical environment. No pickle is used.

Build from the verified local Retailrocket inputs in the `ecommerce-recsys`
environment:

```sh
python -m scripts.build_model_artifacts --version retailrocket-fold09-local-v1 --receipt .local/model_bundle_validation.json
python -m scripts.verify_model_artifacts artifacts/retailrocket-fold09-local-v1
```

Use the manifest digest in the validation receipt as an external integrity pin
when loading the corresponding version. The bundle is an offline historical
snapshot, not a deployed service or a source of post-cutoff user updates.
Loading requires compatible package inference code, Python major/minor and
exact library versions. A different OS/architecture emits a warning. Separate
[Linux qualification](../docs/LINUX_CONTAINER.md) verifies the original snapshot
under its declared tolerance and isolation; this is not universal platform
compatibility or compliance with the failed 2 GiB memory target. The separate
[loader verification](../benchmarks/artifacts/fold09_loader_v1.json) preserves
the original manifest and records the current reader's reference parity.

The separate [local HTTP API](../docs/RECOMMENDATION_API.md) serves a pinned
snapshot with one active inference call. Its measured process memory exceeds
the charter target; a loadable bundle alone does not satisfy deployment gates.
