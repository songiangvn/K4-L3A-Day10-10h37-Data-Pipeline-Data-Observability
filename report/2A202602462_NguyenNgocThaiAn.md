# Member Role Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin         | Nội dung                  |
| ------------------ | -------------------------- |
| Họ và tên       | Nguyễn Ngọc Thái An |
| MSSV               | 2A202602462 |
| Khóa/Lớp         | K4 — K4-L3-DAY10 |
| Tên nhóm         | 10h37 |
| Vai trò chính    | Observability & Evaluation support |
| Repository         | https://github.com/songiangvn/K4-L3A-Day10-Data-Pipeline-Data-Observability |
| Ngày hoàn thành | 2026-09-25 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao  | Trạng thái                                 |
| ------------------ | --------------------- | ---------------- | ----------------- | -------------------------------------------- |
| Review quality gate & freshness | `src/observability/quality.py`, `data/quality/*.json` | Quality reports 3 trạng thái | Xác nhận check nào bắt corruption nào | Hoàn thành |
| Review evaluation set | `src/evaluation/testset.py`, `data/eval/test_set.json` | Clean dataset | Xác nhận 10 câu / 4 loại, ground truth khớp dữ liệu sạch | Hoàn thành |
| Kiểm chứng báo cáo & dashboard | `data/reports/*.md`, `data/reports/dashboard.html` | Metrics JSON | Đối chiếu số liệu báo cáo với `data/results/` | Hoàn thành |
| Chạy test suite | `script/run_tests.py` | `tests/` | Log 30 passed, coverage 94% | Hoàn thành |
| Báo cáo nhóm | `report/group_report.md` | Artifacts | Mục 8–10 của báo cáo nhóm | Hoàn thành |

Tôi không sở hữu code trong `src/`. Phần việc của tôi là kiểm chứng output mà anh Giang bàn giao: đọc artifact và đối chiếu với báo cáo, để báo cáo không ghi sai số liệu.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                         | Thành viên/module được hỗ trợ | Kết quả                    |
| ------------------------------------ | ------------------------------------ | ---------------------------- |
| Đối chiếu bảng 3 trạng thái | Nguyễn Sơn Giang / `corruption_report.md` | Số liệu khớp `baseline/corrupted/repaired_metrics.json` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao       | Cách xác minh         |
| --------------------------- | ----------------------------- | ------------------------- | ----------------------- |
| Kiểm tra quality gate trên dữ liệu sạch | `data/quality/baseline_quality_report.json` | `success=true`, 7/7 | Lệnh CP1 in `Quality check status = True` |
| Kiểm tra gate trên dữ liệu corrupted | `data/quality/corrupted_quality_report.json` | `success=false`: unique (12 dòng), summary length (5), title length (7) | Đọc JSON, so với `corruption_log.json` |
| Kiểm tra test set | `data/eval/test_set.json` | 10 câu: summary 3, authors 3, date 2, categories 2 | Lệnh CP2 in `Sinh được 10 câu hỏi test` |
| Chạy test suite | `tests/` | 30 passed | `python script/run_tests.py` |

Output cụ thể tôi giúp xác minh: số dòng vi phạm trong corrupted report khớp với corruption log. Blank summary 4 dòng cộng 1 bản duplicate của bài 3671818 cho ra 5 dòng fail `summary_min_length`. Truncate title 5 dòng cộng 2 bản duplicate (3671801, 3671803) cho ra 7 dòng fail `title_min_length`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Báo cáo phải phản ánh đúng artifact. Nếu số liệu báo cáo lệch với JSON, nhóm bị trừ điểm vì "bịa số liệu". Ngoài ra cần hiểu vì sao mỗi check pass hay fail để trả lời Q&A.

### Cách triển khai

Với mỗi trạng thái, tôi đọc `*_quality_report.json` (trường `expectations[].success`, `unexpected_count`) và `*_freshness_report.json` (`stale_ratio`, `is_fresh`), rồi so với `corruption_log.json` (số dòng và `paper_id` bị ảnh hưởng). Với test set, tôi kiểm tra mỗi `ground_truth_doc_ids` có trong `papers_clean.json` và `ground_truth` đúng với trường tương ứng (câu đầu summary, authors, published, categories).

### Input, output và contract

| Thành phần                   | Mô tả                                     |
| ------------------------------ | ------------------------------------------- |
| Input                          | `data/quality/*.json`, `data/results/*.json`, `data/eval/test_set.json` |
| Output                         | Xác nhận / chỉnh sửa trong `report/group_report.md` |
| Module phụ thuộc             | `observability/quality.py`, `evaluation/testset.py`, `evaluation/metrics.py` |
| Module sử dụng output        | Báo cáo nhóm, live demo |
| Điều kiện lỗi cần xử lý | Số liệu báo cáo lệch artifact; test set sinh lại làm đổi ground truth |

### Cách xác minh

```bash
python -c "from core.config import load_settings; from observability.quality import run_data_quality_checks; import pandas as pd; s=load_settings(); df=pd.read_json(s.paths.clean_json); res=run_data_quality_checks(df, s, 'test'); print(f'Tín hiệu hoàn thành: Quality check status = {res[\"success\"]}')"
python script/run_tests.py
```

- **Kết quả mong đợi:** `Quality check status = True`; tất cả test pass.
- **Kết quả thực tế:** như mong đợi.
- **Artifact/log:** `data/quality/`, `data/reports/corruption_report.md`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Freshness có nên gộp vào `success` của quality gate không?
- **Các phương án đã cân nhắc:** (a) Gộp: gate fail khi dữ liệu stale. (b) Tách: `success` chỉ phản ánh GX, freshness là SLA riêng, nhưng self-healing gate vẫn xét cả hai.
- **Phương án đã chọn:** (b).
- **Lý do:** Dữ liệu có thể đúng cấu trúc mà vẫn cũ. Hai loại lỗi cần hành động khác nhau: GX fail thì chặn index, stale thì cần re-fetch nguồn. Tách ra giúp báo cáo nói rõ tín hiệu nào bắt lỗi nào. Ngoài ra snapshot sẽ tự "già" theo thời gian; nếu gộp thì baseline sẽ fail khi chấm muộn dù dữ liệu không hỏng.
- **Bằng chứng quyết định phù hợp:** Corrupted report có `stale_date` chỉ bị Freshness bắt (`is_fresh=False`, 0.44), còn `duplicate_rows` chỉ bị GX bắt. Hai tín hiệu bổ sung cho nhau.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Khi chạy với key OpenAI không hợp lệ, `agent_demo_answers.json` chứa `OpenAIAuthenticationError: Error code: 401 - Incorrect API key provided: sk-proj-****…` (có tiền tố và 4 ký tự cuối của key).
- **Lệnh hoặc bước tái hiện:** Đặt key sai trong `.env`, chạy `python script/run_phase1.py`.
- **Nguyên nhân gốc:** Message exception của SDK được ghi nguyên văn vào artifact có commit lên repo.
- **Cách xử lý:** Báo cho anh Giang. Anh thêm `_safe_error()` trong `phase1.py` để redact chuỗi dạng `sk-…`/`AIza…` và cắt message còn 200 ký tự.
- **Cách xác minh sau khi sửa:** Chạy lại phase 1, mở `agent_demo_answers.json` và thấy `[REDACTED]`.
- **Điều học được:** Secret có thể lọt vào repo qua log và artifact, không chỉ qua `.env`.

## 7. Hiểu biết về luồng end-to-end

**Câu trả lời:**

1. Crossref trả JSON, được lưu raw nguyên bản, parse thành records, làm sạch và tạo `text_for_embedding`, rồi MiniLM nhúng thành vector và lưu vào ChromaDB.
2. Test set lưu DOI của tài liệu đúng. Nếu DOI xuất hiện trong top-4 kết quả retrieve thì tính là hit. Token F1 đo độ trùng từ giữa câu trả lời và đáp án.
3. Quality checks (GX) kiểm tra dữ liệu có hợp lệ không: null, trùng, độ dài, số dòng. Freshness kiểm tra dữ liệu có còn mới không (bao nhiêu % bài quá 180 ngày).
4. Nếu đổi test set theo dữ liệu thì không so sánh được. Cùng một đề thi mới cho biết dữ liệu làm điểm thay đổi.
5. Repair thành công khi `repaired_metrics.json` bằng baseline, `repaired_quality_report.json` pass và `repair_summary.json` có hash repaired bằng baseline.

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal          | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| ---------------------- | -------: | --------: | -------: | ------------------------- |
| `retrieval_hit_rate` | 1.0 | 0.7 | 1.0 | 3/10 câu mất tài liệu đích |
| `mean_token_f1`      | 1.0 | 0.68 | 1.0 | |
| `judge_accuracy`     | 1.0 | 0.6 | 1.0 | LLM judge khắt khe hơn F1 ở câu bị noise (eval_005) |
| `mean_judge_score`   | 5 | 3.7 | 5 | |
| Quality checks         | Pass 7/7 | Fail 4/7 | Pass 7/7 | |
| Freshness status       | Fresh | Stale | Fresh | |

### Kết luận từ số liệu

1. `stale_date` lùi 8 bài 365 ngày (11 dòng tính cả duplicate), stale ratio tăng từ 0.04 lên 0.44 và `is_fresh=False`. Câu eval_007 trả lời năm 2025 thay vì 2026 (F1 = 0).
2. Repair rebuild từ raw đưa stale ratio về 0.04 và GX pass 7/7, câu eval_007 trả lời đúng trở lại (F1 = 1.0).

Corruption ảnh hưởng rõ nhất: `drop_latest_records`, vì gây mất hit ở 3 câu mà không làm fail check GX nào.

Kết quả khác kỳ vọng: `blank_summary` không làm giảm metric nào. Tôi kiểm tra bảng per-question thì thấy câu duy nhất có tài liệu bị blank là câu hỏi `authors` (eval_006), không phụ thuộc vào summary. Vậy corruption chỉ ảnh hưởng khi chạm đúng trường mà câu hỏi hỏi tới.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. Data lineage: luôn giữ bản raw để có thể tái tạo.
2. Observability cần nhiều tín hiệu: GX và Freshness bắt các lỗi khác nhau, và có lỗi (noise) cả hai đều không bắt được.
3. RAG không báo lỗi khi dữ liệu sai, nên phải đo bằng test set cố định.

### Nếu có thêm thời gian

Thêm expectation kiểm tra tỉ lệ ký tự đặc biệt trong summary (regex) để bắt `inject_noise`. Đo bằng việc `corrupted_quality_report.json` có thêm check fail, trong khi baseline vẫn pass.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Ngọc Thái An
**Ngày xác nhận:** 2026-09-25
