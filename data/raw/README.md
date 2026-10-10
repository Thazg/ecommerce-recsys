# Retailrocket dataset

This project uses the
[Retailrocket recommender system dataset](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset),
a timestamped record of anonymized e-commerce activity. Its event log contains
product views, cart additions and transactions; separate files provide category
relationships and item-property snapshots. The [dataset card](../../docs/DATASET_CARD.md)
records the schema, source, limitations and benchmark input hashes.

## Why this dataset

The event timestamps support chronological training and evaluation. Repeated
visitor and item IDs support collaborative and history-based retrieval. The
time-varying item properties allow category features to be built as of each
training cutoff, while the category tree supplies parent-child relationships.
The mix of returning and first-time visitors permits separate warm- and
cold-user evaluation. These properties match the project's offline
implicit-feedback and candidate-retrieval tasks.

The IDs are anonymized, interactions are sparse, and the public files do not
include recommendation exposure logs. An unobserved item is therefore not a
confirmed negative preference. Results describe this offline dataset and its
stated evaluation protocol, not performance on future traffic or a production
recommendation service.

## Raw files

The CSVs are obtained separately and are not committed to Git.

| File | Content |
| :--- | :--- |
| `events.csv` | Timestamped views, cart additions, and transactions |
| `category_tree.csv` | Parent-child category relationships |
| `item_properties_part1.csv` | Time-varying item properties |
| `item_properties_part2.csv` | Time-varying item properties |

Download and extract these files into `data/raw/`, or use the repository helper
if the Kaggle CLI is installed and authenticated. Run the commands from the
repository root:

```sh
python scripts/download_data.py
python scripts/download_data.py --verify-only
```

The `--verify-only` command checks that the expected files exist and reports
their sizes and line counts; it does not validate their content hashes.

Do not edit raw files in place. The
[rolling manifest](../../benchmarks/rolling/manifest.json) hashes the
item-property CSVs and the processed interaction file; changed inputs require
a fresh preparation run and benchmark artifact set.
