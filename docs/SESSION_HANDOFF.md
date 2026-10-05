# Handoff: rolling benchmark trước M7

**Đã tiếp tục ngày 2026-10-05 và hoàn tất rolling M4–M6 qua fold ALS 9.** Đây là ghi nhớ quá trình và trạng thái cuối trước M7. Lịch sử commit và trạng thái đồng bộ remote được theo dõi trong Git.

## Bối cảnh và quyết định

- Mục tiêu: sửa các lỗi hiện có trước M7, thống nhất đánh giá M4–M6 trên rolling benchmark.
- v1 là leave-last-out theo từng user với 200.028 test users. Có future data của user khác trong train chung và 86.949 target đã thấy trong lịch sử train của chính user. Giữ artifact/báo cáo v1 như lịch sử, không so điểm trực tiếp với rolling.
- Thử nghiệm single-cutoff 3.590 warm users từng gọi v2 đã bị loại theo yêu cầu. Tên hiện tại là **rolling**, không dùng `v3` nữa.
- Rolling: 10 cửa sổ thời gian, 9 fold đánh giá. Fold 1–4 chọn ItemKNN/ALS bằng pooled HR@20, hòa bằng NDCG@20; fold 5–9 đo cấu hình đã chọn. Đã xem HR/NDCG của fold 5–9 qua lượt reference trước khi lock sweep nên **không phải blind holdout**. Báo cáo và JSON ghi rõ `blind_holdout: false`, reference là **diagnostic, configs transferred**.
- Người dùng yêu cầu dừng sau fold ALS 6, lưu checkpoint, rồi hôm sau yêu cầu tiếp tục. Fold 7–9 đã hoàn tất từ đúng checkpoint; không còn tiến trình Python chạy.

## Trạng thái hoàn tất

- Worktree: `C:\Users\THAZG NGUYEN\.codex\worktrees\9f9d\ecommerce-recsys`
- Conda Python: `D:\Miniconda\envs\ecommerce-recsys\python.exe`
- Tương tác nguồn (chỉ đọc): `E:\ecommerce-recsys\data\processed\interactions.parquet`; raw CSV cũng ở `E:\ecommerce-recsys\data\raw`.
- Fold Parquet: `data/rolling/fold_01` đến `fold_09` (bị Git ignore). Manifest/checkpoint JSON: `benchmarks/rolling/`.
- `benchmarks/rolling/als_sweep.json` có **37 rows**: 32 kết quả selection (8 cấu hình × 4 folds) và 5 kết quả final trên folds 5–9. `final_summary` có 59.323 user-window targets. File JSON hợp lệ, protocol `rolling-temporal`, `blind_holdout: false`.
- ALS chọn `factors=128`, `iterations=40`, `regularization=0.01`; pooled HR@20 trên folds 1–4 là 0.035440, hơn cấu hình 128×20 khoảng một hit. Final folds 5–9 đạt HR@20 **0.027291**, MRR@20 **0.009456**, NDCG@20 **0.013385**. HR@20 từng fold 5–9: 0.030148, 0.029384, 0.027615, 0.026165, 0.024226.
- ItemKNN sweep hoàn tất: lambda 100, HR@20 folds 5–9 = 0.041889 trên 59.323 user-window targets. Category Popularity cùng cohort = 0.041518. Cold cohort 1.262.289 người; Global HR@20 0.011394, Recent 0.011649.
- Lượt reference 9 fold của 6 model hoàn tất ở `benchmarks/rolling/results.json`, chỉ dùng diagnostic vì fold 5–9 đã lộ trước sweep.
- Chạy lại `benchmark_rolling.py` sau hai sweep thành công; artifact giữ đủ 54 kết quả. Báo cáo đã cập nhật bảng folds 5–9 của cả sáu model và công bố giới hạn không blind.

## Kiểm tra và lệnh tái lập

Audit ngày 2026-10-05 đối chiếu cả 9 fold với dữ liệu nguồn, vá checkpoint resume và guard hoàn tất sweep, thêm chế độ legacy rõ ràng cho script v1. Sau review OpenCode, đã dựng lại cả 9 fold từ raw properties: 27/27 file Parquet trùng byte, rồi gắn SHA của raw/fold vào manifest và bốn artifact. Cold runner đã có resume/atomic/empty-fold và `--max-fold 4`; ALS/numeric pools pin một worker. Xem [REPO_AUDIT_2026-10-05.md](REPO_AUDIT_2026-10-05.md). Đã chạy thành công 130 tests trong Conda env, Ruff lint/format và `git diff --check`. Từ thư mục worktree, trong PowerShell có thể tái lập sweep ALS bằng:

```powershell
$env:PYTHONPATH='src'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
& 'D:\Miniconda\envs\ecommerce-recsys\python.exe' scripts/sweep_rolling.py --model als --input-path 'E:\ecommerce-recsys\data\processed\interactions.parquet'
```

Script sẽ bỏ qua cả 37 rows đã lưu và giữ cùng cấu hình. Không cần chạy `prepare_rolling_data.py` lại khi fold Parquet còn nguyên. Các kết quả và giới hạn được tổng hợp tại [ROLLING_BENCHMARK_REPORT.md](ROLLING_BENCHMARK_REPORT.md).

README, code và tài liệu đã đổi mặc định sang `rolling`; không còn thư mục `rolling_v3`. Không push cho tới khi người dùng xác nhận rõ.
