# Retailrocket raw data

Raw CSVs are kept outside Git. The expected source is the [Retailrocket recommender system dataset](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset); its schema and limitations are described in the [dataset card](../../docs/DATASET_CARD.md).

| File | Content |
| :--- | :--- |
| `events.csv` | Timestamped views, cart additions, and transactions |
| `category_tree.csv` | Parent-child category relationships |
| `item_properties_part1.csv` | Time-varying item properties |
| `item_properties_part2.csv` | Time-varying item properties |

Download and extract these files into `data/raw/`, or use the repository helper if the Kaggle CLI is installed and authenticated:

```sh
python scripts/download_data.py
python scripts/download_data.py --verify-only
```

Do not edit raw files in place. The rolling manifest hashes the item-property CSVs and the processed interaction file; changed inputs require a fresh preparation run and benchmark artifact set.
