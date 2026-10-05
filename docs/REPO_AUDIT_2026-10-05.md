# Repository audit — 2026-10-05

## Scope and result

Audited the M0–M6 offline path, with emphasis on the rolling M4–M6 benchmark: processed interactions, nine fold files, train-time catalogs, warm/cold cohorts, model evaluation, sweep checkpoints, result artifacts, tests, and current documentation. M7 has not started. No new discrepancy was found in the saved rolling cohort or reported pooled scores.

## Checks performed

- Independently compared all nine saved fold files against the processed interaction source. Train/window row counts, time boundaries, warm and cold user counts, unique target users, absence of warm targets from each user's training pairs, and training catalog item sets matched the manifest. The files contain 90,107 warm user-window targets from 71,982 distinct users.
- Verified all four raw Retailrocket files are present. Raw and processed files matched in row count (2,756,101) and row-multiset hash across user, item, time, event type, and transaction ID; the processed file is ordered chronologically.
- Confirmed both sweeps contain 32 selection results and five final results on folds 5–9; the reference artifact contains 54 fold-model results. All use the same processed-interaction SHA-256 and disclose `blind_holdout: false`.
- Re-ran the sweep scripts in resume mode and the reference runner without recomputing model fits. The selected ItemKNN and ALS configurations and saved metrics remained unchanged.
- Confirmed the existing as-of metadata test excludes category values after the train cutoff.
- Independently rebuilt all nine rolling folds from the current raw property CSVs into a temporary directory. All 27 generated Parquet files matched the original benchmark inputs byte for byte. The manifest and four benchmark artifacts were then bound to the verified raw-property and per-file hashes without changing scores.

## Defects repaired during this audit

1. A changed sweep grid could leave final results from an older selected configuration in the checkpoint, then pool them with new final rows. Resume now rejects mixed or duplicate final rows.
2. The reference and cold runners previously treated the mere presence of `final_summary` as proof that both sweeps were complete. They now require exactly folds 5–9, the selected configuration, the manifest target counts, and matching protocol/source/model metadata.
3. Historical leave-last-out benchmark scripts were blocked by the new rolling evaluator guard. They now request an explicit legacy split protocol. Rolling remains the default and still rejects global time overlap and previously seen targets.
4. Core runtime imports (`numpy`, `pandas`, `scipy`, and Parquet support via `pyarrow`) were only supplied through the dev extra or transitive dependencies. They are now declared as direct project dependencies.
5. The historical split CLI did not create a custom output directory before writing Parquet files. It now creates the directory. The M2 data quality report also now points readers to the current rolling cohort rule.
6. Cold evaluation was neither atomic nor resumable, and an empty cold fold caused division by zero or NaN. It now checkpoints each model atomically, handles zero-user folds, and allows folds 1–4 before the sweep gate.
7. Prepare now resumes only matching completed folds and records raw-property and fold-file SHA-256 values. All rolling result artifacts bind to the full manifest fingerprint; changed content with the same row count is rejected.
8. ALS training and rolling benchmark numerical calls now use one worker thread. Educational MF/BPR normalize mixed ID types and break equal-score ties by item ID. Conflicting category values at the same item/timestamp are rejected; none were found in the current Retailrocket raw files.

## Remaining limits and recommended work

- **No blind holdout remains in this dataset run.** Reference metrics for folds 5–9 were visible before sweep selection was locked. The five-fold table is useful for diagnosis but cannot confirm a prospective winner. A new, unseen time period is needed for that claim.
- **ItemKNN versus Category Popularity is unresolved.** Their folds 5–9 pooled HR@20 differs by only 0.000371 and their fold ordering changes. Save per-user predictions and run paired uncertainty analysis, or use a future untouched period, before declaring either superior.
- **Cross-machine bitwise reproduction still depends on package versions and hardware.** Seeds, worker counts, source hashes, and fold hashes are recorded or enforced, but a clean installation and full ALS rerun on another machine have not been exercised.
- **A clean installation was not exercised.** Direct runtime dependencies are now declared and `pip check` passes in the existing Conda environment, but a fresh environment should be tested before release.
- **Historical v1 reruns are archival.** The explicit legacy mode makes those scripts runnable, but their split is globally noncausal and current model fixes can change scores. Do not mix their outputs with rolling results.
- **Serving and production behavior are untested.** Inference latency here measures local Python calls after fitting. M7 candidate generation and an online service have not been implemented.

## Verification

Full Conda test suite: 132 passed. Ruff lint and formatting checks, `pip check` in the existing environment, and `git diff --check` passed.
