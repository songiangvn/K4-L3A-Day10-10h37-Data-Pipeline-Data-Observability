# Member Role Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin         | Nội dung                  |
| ------------------ | -------------------------- |
| Họ và tên       | Nguyễn Sơn Giang |
| MSSV               | 2A202602747 |
| Khóa/Lớp         | K4 — K4-L3-DAY10 |
| Tên nhóm         | 10h37 |
| Vai trò chính    | Trưởng nhóm, Pipeline Integrator, Data Foundation, Corruption & Repair owner |
| Repository         | https://github.com/songiangvn/K4-L3A-Day10-Data-Pipeline-Data-Observability |
| Ngày hoàn thành | 2026-09-25 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao  | Trạng thái                                 |
| ------------------ | --------------------- | ---------------- | ----------------- | -------------------------------------------- |
| Raw ingestion | `src/ingestion/crossref.py` (`parse_crossref_payload`, `fetch_source_records`, `load_raw_records`) | Crossref `/works` / snapshot | `data/raw/crossref_response.json`, `crossref_records.json` | Hoàn thành |
| Cleaning & data model | `src/ingestion/cleaning.py` (`build_clean_dataframe`, `add_derived_columns`) | Raw records | `data/clean/papers_clean.{csv,json}` | Hoàn thành |
| Quality gate & freshness | `src/observability/quality.py` | Clean/corrupted/repaired df | `data/quality/*.json` | Hoàn thành |
| Test set | `src/evaluation/testset.py` | Clean df | `data/eval/test_set.json` | Hoàn thành |
| Corruption | `src/ingestion/corruption.py` | Clean df | `papers_clean_corrupted.*`, `corruption_log.json` | Hoàn thành |
| Orchestration & self-healing repair | `src/pipelines/phase1.py`, `src/pipelines/corruption_flow.py` | Settings, artifacts | Metrics 3 trạng thái, `repair_summary.json` | Hoàn thành |
| Reporting & dashboard | `src/observability/reporting.py`, `dashboard.py` | Metrics, quality | `phase1_report.md`, `corruption_report.md`, `dashboard.html` | Hoàn thành |
| Test suite & CI | `tests/`, `script/run_tests.py`, `.github/workflows/ci.yml` | Toàn bộ `src/` | 30 tests, coverage 94% | Hoàn thành |

Vì nhóm chỉ có 2 người, tôi nhận phần lớn các khối code. Output của tôi là đầu vào để chị Thái An kiểm chứng: file `data/quality/*.json`, `test_set.json`, dashboard và báo cáo.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                         | Thành viên/module được hỗ trợ | Kết quả                    |
| ------------------------------------ | ------------------------------------ | ---------------------------- |
| Sửa `persist_path` tuyệt đối trong manifest | `src/retrieval/index.py` (starter) | Manifest portable (`data/chroma`), test load lại pass |
| Thêm alias provider `google` → `gemini` | `src/core/config.py` | Router hỗ trợ đúng tên trong rubric |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao       | Cách xác minh         |
| --------------------------- | ----------------------------- | ------------------------- | ----------------------- |
| Dual-mode ingestion với retry 429/5xx | `crossref.py` | 24 records | `python -c "...fetch_source_records..."` in `Đã tải 24 bài báo`; `tests/test_ingestion.py` mock 429 → 200 và 503 → fallback |
| Cleaning 24 dòng + `text_for_embedding` | `cleaning.py` | `papers_clean.csv` | In `Clean thành công 24 dòng` |
| GX 1.x gate 7 expectations | `quality.py` | Baseline pass 7/7, corrupted fail 4/7 | `data/quality/*_quality_report.json` |
| 6 corruption tất định | `corruption.py` | `corruption_log.json` | `test_corruption_log_has_six_scenarios` |
| Self-healing + idempotent repair | `corruption_flow.py` | `repair_summary.json` | SHA-256 baseline = run1 = run2 |

Output cụ thể: bảng so sánh trong `data/reports/corruption_report.md`. Hit rate 1.0 → 0.7 → 1.0, token F1 1.0 → 0.68 → 1.0, GX PASS → FAIL → PASS, freshness True → False → True.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Dữ liệu bẩn đi vào vector store không làm RAG crash. Nó chỉ làm câu trả lời sai (silent failure). Phần việc của tôi là (1) tạo dữ liệu sạch có lineage, (2) đặt một gate phát hiện dữ liệu bẩn trước khi index, và (3) phục hồi tự động, idempotent từ nguồn tin cậy.

### Cách triển khai

- **Ingestion:** mặc định đọc snapshot để tái lập kết quả. Nếu `REFRESH_SOURCE=1`, gọi API với 4 lần thử, backoff 2s·2^(n−1). Response live chỉ ghi đè snapshot khi parse ra ít nhất 1 record, để một response rỗng hay lỗi không phá mất bản raw tốt.
- **Cleaning:** bỏ thẻ JATS bằng regex rồi `html.unescape`, chuẩn hoá ngày về ISO, drop bản ghi thiếu trường bắt buộc, dedupe `paper_id` và giữ bản `updated` mới nhất, sau đó tính `age_days` và `text_for_embedding`. Hàm `add_derived_columns` dùng chung với corruption để lỗi lan vào embedding.
- **Quality gate:** `gx.get_context(mode="ephemeral")`, `data_sources.add_pandas`, `add_dataframe_asset`, `add_batch_definition_whole_dataframe`, `batch.validate(suite)`. Có 4 expectation bắt buộc, thêm `title_min_length` để bắt `truncate_title`. Freshness được tính riêng thành một SLA.
- **Corruption:** `random.Random(42)`, các tỉ lệ cố định. Log ghi `paper_id` bị ảnh hưởng để báo cáo có thể quy kết tác động theo từng câu hỏi.
- **Self-healing:** `self_healing_gate()` thấy GX hoặc freshness fail thì gọi `repair_from_raw()`, validate lại, và chỉ index khi pass.

### Input, output và contract

| Thành phần                   | Mô tả                                     |
| ------------------------------ | ------------------------------------------- |
| Input                          | `data/raw/crossref_records.json` (list `PaperRecord`) |
| Output                         | DataFrame 16 cột (`CLEAN_COLUMNS`), quality report JSON, metrics JSON |
| Module phụ thuộc             | `core.config`, `core.utils` |
| Module sử dụng output        | `retrieval/index.py`, `evaluation/testset.py`, `evaluation/metrics.py` |
| Điều kiện lỗi cần xử lý | API 429/5xx, response rỗng, thiếu DOI/abstract, DOI trùng, ngày thiếu tháng/ngày, gate fail |

### Cách xác minh

```bash
python script/run_phase1.py
python script/run_corruption_flow.py
python script/run_tests.py
```

- **Kết quả mong đợi:** exit 0; corrupted thấp hơn baseline; repaired bằng baseline; hash repair idempotent.
- **Kết quả thực tế:** đúng như mong đợi (30 passed, coverage 94.3%).
- **Artifact/log:** `data/results/repair_summary.json`, `data/reports/corruption_report.md`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Repair nên "vá" dataframe corrupted hay tái tạo từ raw?
- **Các phương án đã cân nhắc:** (a) Vá tại chỗ: dedupe, drop dòng summary rỗng, sửa title. (b) Rebuild toàn bộ từ raw snapshot bằng cùng hàm cleaning và cùng `run_date`.
- **Phương án đã chọn:** (b).
- **Lý do:** (a) không lấy lại được dữ liệu đã mất (5 bài bị drop, ngày bị lùi), và mỗi lần chạy có thể cho kết quả khác. (b) là hàm thuần của (raw, run_date), nên idempotent và đảm bảo đúng. Đổi lại cần giữ raw bất biến, việc này đã có sẵn nhờ raw preservation.
- **Bằng chứng quyết định phù hợp:** `repair_summary.json` cho hash baseline = run 1 = run 2, và recovery 100% trên mọi metric.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `AssertionError: assert '10.1145/3637528.3671819' == '10.1145/3637528.3671807'` trong `test_index_search_lookup_and_eval`.
- **Lệnh hoặc bước tái hiện:** `python script/run_tests.py`
- **Nguyên nhân gốc:** Corpus có cặp bài gần trùng ("X" và "Advanced Perspectives on X"). Semantic search theo title xếp bài "Advanced" lên top-1. Code không sai; kỳ vọng top-1 trong test là giả định sai.
- **Cách xử lý:** Assert tài liệu đúng nằm trong top-2. Đồng thời ghi nhận trong báo cáo rằng QA dùng exact-title lookup trước semantic search để tránh nhầm cặp này.
- **Cách xác minh sau khi sửa:** 30 passed.
- **Điều học được:** Near-duplicate trong corpus làm retrieval nhiễu. Chính hiện tượng này giải thích vì sao eval_002 mất hit mà F1 vẫn 1.0.

## 7. Hiểu biết về luồng end-to-end

**Câu trả lời:**

1. Crossref JSON được parse thành `PaperRecord` và lưu raw. Sau đó cleaning tạo dataframe có `text_for_embedding`, rồi MiniLM (384 chiều, normalize) sinh vector, lưu vào Chroma collection cosine, metadata gồm title, authors, published, categories, summary.
2. Mỗi câu hỏi có `ground_truth_doc_ids` (DOI). Hit = DOI nằm trong top-k retrieved. Token F1 so câu trả lời trích xuất với `ground_truth`.
3. Quality checks kiểm tra cấu trúc và giá trị tại một thời điểm (null, unique, length, volume). Freshness đo độ tươi theo thời gian (`age_days` so với SLA 180 ngày / 25%). Dữ liệu có thể pass GX mà vẫn stale.
4. Nếu test set thay đổi theo dữ liệu, ground truth cũng bị corrupt theo, và không còn đo được suy giảm.
5. Repair thành công khi `repaired_quality_report.success = True`, `is_fresh = True`, metrics trong `repaired_metrics.json` bằng baseline, và hash repaired bằng baseline.

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal          | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| ---------------------- | -------: | --------: | -------: | ------------------------- |
| `retrieval_hit_rate` | 1.0 | 0.7 | 1.0 | Giảm hoàn toàn do drop 3 tài liệu đích |
| `mean_token_f1`      | 1.0 | 0.68 | 1.0 | Drop, noise, stale date cùng góp phần |
| `judge_accuracy`     | 1.0 | 0.6 | 1.0 | LLM judge (gpt-4o-mini) đánh sai 4 câu, gồm câu noise mà F1 vẫn 0.80 |
| `mean_judge_score`   | 5 | 3.7 | 5 | |
| Quality checks         | 7/7 | 4/7 | 7/7 | Fail unique / summary / title length |
| Freshness status       | Fresh | Stale | Fresh | 0.04 → 0.44 → 0.04 |

### Kết luận từ số liệu

1. `duplicate_rows` (6 dòng) làm `paper_id_unique` fail với 12 dòng vi phạm. Top-k lúc này có thể chứa bản trùng, nhưng trong test set không câu nào mất hit vì lý do này. Tác động chính của duplicate là lên chất lượng dữ liệu, không lên metric.
2. `repair_from_raw` đưa 24 dòng về, GX pass 7/7, stale ratio 0.04, hit rate và F1 về 1.0.

Corruption ảnh hưởng rõ nhất là `drop_latest_records`: bài bị xoá thì không cách retrieval nào lấy lại được. Nó lại không làm fail GX, vì row count 25 vẫn trong khoảng 5–5000, nên đây là corruption nguy hiểm nhất.

Kết quả khác kỳ vọng: `truncate_title` không làm giảm hit (eval_004). Tôi kiểm tra per-question table thì thấy exact-title lookup thất bại nhưng semantic search trên câu hỏi vẫn tìm ra đúng tài liệu nhờ phần categories/summary.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. Raw preservation là điều kiện để có repair idempotent: không có raw bất biến thì chỉ có thể vá tạm.
2. Quality gate cần nhiều chiều (volume, uniqueness, validity, freshness). Mỗi corruption chỉ bị một số check bắt được, và `inject_noise` lọt qua tất cả.
3. RAG không báo lỗi khi dữ liệu hỏng. Metric câu trả lời có thể "đúng nhờ may mắn" (eval_002), nên cần đo cả retrieval hit.

### Nếu có thêm thời gian

Thêm check volume drift: so row count và `latest_published` với lần chạy trước, fail nếu giảm hơn 10%. Mục đích là bắt `drop_latest_records`. Đo bằng cách chạy lại corruption flow và kiểm tra `corrupted_quality_report` fail thêm check này.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Sơn Giang
**Ngày xác nhận:** 2026-09-25
