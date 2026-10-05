import pandas as pd

from ecommerce_recsys.data.splitting import rolling_temporal_cutoffs, rolling_temporal_fold


def test_rolling_fold_separates_warm_novel_targets_from_cold_users():
    interactions = pd.DataFrame(
        [
            ("u1", "A", 1),
            ("u3", "E", 2),
            ("u4", "G", 3),
            ("u1", "B", 4),
            ("u2", "D", 4),
            ("u1", "A", 5),
            ("u3", "E", 5),
            ("u3", "F", 6),
            ("u1", "C", 7),
            ("u2", "H", 8),
            ("u4", "I", 9),
            ("u1", "J", 10),
            ("u3", "K", 11),
            ("u2", "L", 12),
        ],
        columns=["user_id", "item_id", "timestamp"],
    )
    cutoffs = rolling_temporal_cutoffs(interactions, n_windows=4)
    assert cutoffs == [3, 6, 9, 12]

    train, warm_targets, cold_targets, window = rolling_temporal_fold(
        interactions, cutoffs, fold_index=1
    )

    assert train["timestamp"].max() == 3
    assert set(window["timestamp"]) == {4, 5, 6}
    assert dict(zip(warm_targets["user_id"], warm_targets["item_id"], strict=True)) == {
        "u1": "B",
        "u3": "F",
    }
    assert cold_targets["user_id"].tolist() == ["u2"]
    assert cold_targets["item_id"].tolist() == ["D"]
