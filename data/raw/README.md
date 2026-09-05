# Raw Data Directory

**Milestone:** Milestone 1 — Dataset Selection and Data Contract
**Dataset:** Retailrocket Recommender System Dataset

---

## 1. Directory Policy

* IMMUTABLE: Files in this directory must NEVER be modified in place.
* NO GIT TRACKING: Data files (*.csv, *.zip) are ignored by .gitignore.
* PROVENANCE: All raw data must match the specifications in docs/DATASET_CARD.md.

---

## 2. Expected Files

Once acquired, this directory should contain:

1. events.csv
   - User interaction log (view, addtocart, transaction)
   - Size: ~90 MB uncompressed

2. category_tree.csv
   - Category parent-child relationship table
   - Size: ~30 KB uncompressed

3. item_properties_part1.csv & item_properties_part2.csv
   - Time-varying item attribute snapshots
   - Size: ~1.5 GB uncompressed total

---

## 3. How to Obtain the Data

### Option A: Via Download Script (Recommended)
Run:
    python scripts/download_data.py
(Requires Kaggle API credentials configured in ~/.kaggle/kaggle.json).

### Option B: Manual Download
1. Download from Kaggle:
   https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset
2. Unzip all files directly into this directory (data/raw/).
3. Verify files with:
    python scripts/download_data.py --verify-only
