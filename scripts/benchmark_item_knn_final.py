from __future__ import annotations

import pandas as pd

from ecommerce_recsys.evaluation.benchmark import evaluate_recommender
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender

TRAIN_PATH = "data/processed/train.parquet"
TEST_PATH = "data/processed/test.parquet"
ITEMS_PATH = "data/processed/items.parquet"

OUTPUT_PATH = "benchmarks/item_knn_final.csv"


def main() -> None:
    train = pd.read_parquet(TRAIN_PATH)
    test = pd.read_parquet(TEST_PATH)
    items = pd.read_parquet(ITEMS_PATH)

    recommender = ItemKNNRecommender(
        n_neighbors=20,
        min_item_interactions=5,
        shrinkage_lambda=0.0,
    )

    print("Fitting ItemKNN...")
    recommender.fit(train)

    results = []

    for shrinkage_lambda in (0.0, 100.0):
        recommender.set_shrinkage_lambda(shrinkage_lambda)

        print(f"\nEvaluating lambda={shrinkage_lambda}...")

        metrics = evaluate_recommender(
            recommender=recommender,
            train=train,
            test=test,
            items=items,
            k_values=(5, 10, 20),
            total_catalog_items=len(items),
            fit=False,
        )

        row = {
            "model": "ItemKNN",
            "shrinkage_lambda": shrinkage_lambda,
            **metrics,
        }

        results.append(row)

        print(
            f"HR@10={metrics['HR@10']:.6f} | "
            f"MRR@10={metrics['MRR@10']:.6f} | "
            f"NDCG@10={metrics['NDCG@10']:.6f} | "
            f"coverage={metrics['coverage']:.6f}"
        )

    results_df = pd.DataFrame(results)

    print("\nFinal benchmark:")
    print(results_df.to_string(index=False))

    results_df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
