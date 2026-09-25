# Group Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin         | Nội dung                  |
| ------------------ | -------------------------- |
| Khóa/Lớp         | K4 — K4-L3-DAY10 |
| Tên nhóm         | 10h37 |
| Repository         | https://github.com/songiangvn/K4-L3A-Day10-Data-Pipeline-Data-Observability |
| Ngày hoàn thành | 2026-09-25 |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu |
| --: | --- | --- | --- | --- |
| 1 | Nguyễn Sơn Giang | 2A202602747 | Trưởng nhóm, Pipeline Integrator, Data Foundation, RAG, Corruption & Repair | `core/`, `ingestion/crossref.py`, `ingestion/cleaning.py`, `ingestion/corruption.py`, `retrieval/index.py`, `observability/quality.py`, `evaluation/testset.py`, `pipelines/phase1.py`, `pipelines/corruption_flow.py`, `observability/reporting.py`, `observability/dashboard.py`, `tests/`, CI |
| 2 | Nguyễn Ngọc Thái An | 2A202602462 | Observability & Evaluation support | Review GX expectations / Freshness SLA, review test set, kiểm chứng artifacts `data/quality/`, `data/results/`, dashboard, chạy test suite, báo cáo nhóm |

## 2. Tóm tắt kết quả

**Tóm tắt của nhóm:**

Nhóm đã hoàn thành đủ 7 tầng pipeline: ingestion từ Crossref (dual-mode live API có retry/backoff 429/5xx và snapshot offline), cleaning thành 24 bản ghi với `text_for_embedding` 5 phần, quality gate Great Expectations 1.23.1 (7 expectations, gồm 4 expectation bắt buộc) cùng Freshness SLA, index ChromaDB bằng `all-MiniLM-L6-v2`, bộ test 10 câu thuộc 4 loại, 6 kịch bản corruption và repair idempotent. Baseline đạt `retrieval_hit_rate = 1.0` và `mean_token_f1 = 1.0`, GX pass 7/7, và `is_fresh = True` (1/24 bản ghi stale).

Trên dữ liệu bị corrupt, agent vẫn trả lời bình thường, không báo lỗi. Đó chính là silent failure: hit rate giảm còn **0.70**, token F1 còn **0.68**. Chỉ có tầng observability phát hiện ra vấn đề: GX fail 3 check (`paper_id_unique`, `summary_min_length`, `title_min_length`) và freshness chuyển sang `False` (stale ratio 0.44). Corruption ảnh hưởng mạnh nhất là `drop_latest_records`: cả 3 câu hỏi có tài liệu đích bị xoá đều mất retrieval hit. Self-healing gate tự phát hiện gate fail và rebuild dữ liệu từ raw snapshot, phục hồi **100%** mọi metric. Hash SHA-256 chứng minh lần repair 1 = lần repair 2 = baseline, tức repair idempotent.

Giới hạn chính: `inject_noise` không bị GX bắt vì độ dài summary vẫn hợp lệ, và LLM judge cần API key hợp lệ. Khi không có key, pipeline dùng heuristic judge (có ghi rõ ở `judge_mode`).

## 3. Kiến trúc và luồng dữ liệu

### Luồng end-to-end

```text
Crossref API (REFRESH_SOURCE=1)  ──┐ retry/backoff 429/5xx, fallback
Snapshot data/raw/crossref_response.json ─┘
    -> parse_crossref_payload -> data/raw/crossref_records.json      (raw lineage, bất biến)
    -> build_clean_dataframe  -> data/clean/papers_clean.{csv,json}  (24 rows)
    -> GX 1.x quality gate + Freshness SLA -> data/quality/*.json     (gate chặn index nếu fail)
    -> MiniLM embeddings + Chroma "papers-baseline"
    -> test_set.json (10 câu cố định) -> baseline_metrics.json + phase1_report.md
    -> corrupt_clean_dataframe (6 lỗi, seed 42) -> "papers-corrupted" -> corrupted_metrics.json
    -> self-healing gate: GX fail -> repair_from_raw(crossref_records.json) -> "papers-repaired"
    -> repaired_metrics.json + repair_summary.json (SHA-256 idempotency)
    -> corruption_report.md + dashboard.html
```

### Trách nhiệm của từng khối

| Khối             | Input          | Xử lý chính             | Output/artifact          | Owner          |
| ----------------- | -------------- | -------------------------- | ------------------------ | -------------- |
| Ingestion         | Crossref `/works` hoặc snapshot | Retry/backoff, parse DOI/title/abstract/author/subject/date, bỏ thẻ JATS, dedupe DOI | `data/raw/crossref_response.json`, `crossref_records.json` | Nguyễn Sơn Giang |
| Cleaning          | `crossref_records.json` | Chuẩn hoá text, ISO date, drop bản ghi thiếu trường bắt buộc, dedupe `paper_id`, `age_days`, `text_for_embedding` | `data/clean/papers_clean.*` | Nguyễn Sơn Giang |
| Embedding/index   | Clean dataframe | `all-MiniLM-L6-v2` (normalize), Chroma cosine, 3 collection tách biệt | `data/chroma/`, `data/embeddings/*.json` | Nguyễn Sơn Giang |
| Evaluation        | Clean dataframe, index | 10 câu / 4 loại, hit rate, token F1, LLM judge (fallback heuristic) | `data/eval/test_set.json`, `data/results/*_metrics.json` | Nguyễn Sơn Giang (review: Nguyễn Ngọc Thái An) |
| Observability     | Clean/corrupted/repaired df | GX 1.x ephemeral context, 7 expectations, Freshness SLA | `data/quality/*.json`, `data/reports/dashboard.html` | Nguyễn Sơn Giang (kiểm chứng: Nguyễn Ngọc Thái An) |
| Corruption/repair | Clean df, raw records | 6 corruption tất định; repair = rebuild từ raw | `corruption_log.json`, `repair_summary.json` | Nguyễn Sơn Giang |
| Orchestration     | Settings | `phase1.py` → `corruption_flow.py` | `phase1_report.md`, `corruption_report.md` | Nguyễn Sơn Giang |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình             | Giá trị sử dụng |
| ---------------------------- | ------------------- |
| `LLM_PROVIDER`             | `openai` (không có key hợp lệ thì dùng heuristic judge; test dùng `mock`) |
| `LLM_MODEL`                | `gpt-4o-mini` |
| Embedding model              | `sentence-transformers/all-MiniLM-L6-v2` |
| Số lượng Crossref records | 24 (snapshot) |
| Retrieval`top_k`           | 4 |
| Freshness threshold          | 180 ngày, tối đa 25% bản ghi stale |
| Random seed, nếu có        | 42 (corruption) |

### Lệnh cài đặt

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows (Linux/macOS: source .venv/bin/activate)
python -m pip install -e ".[dev]"
```

### Lệnh chạy

```bash
python script/run_phase1.py
python script/run_corruption_flow.py
python script/run_tests.py          # pytest + coverage (>= 80%)
python script/build_dashboard.py    # render lại dashboard từ artifacts
```

### Kết quả tái hiện

| Lệnh             | Trạng thái                                    | Thời điểm chạy gần nhất | Bằng chứng                         |
| ----------------- | ----------------------------------------------- | ----------------------------- | ------------------------------------ |
| Baseline pipeline | Thành công (exit 0) | 2026-09-25 | `data/reports/phase1_report.md`, `data/results/baseline_metrics.json` |
| Corruption flow   | Thành công (exit 0) | 2026-09-25 | `data/reports/corruption_report.md`, `data/results/repair_summary.json` |
| Test suite        | 30 passed, coverage 94% | 2026-09-25 | `python script/run_tests.py`, `.github/workflows/ci.yml` |

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính                | Giá trị                             |
| --------------------------- | ------------------------------------- |
| Source                      | `https://api.crossref.org/works` (Crossref REST API); mặc định dùng snapshot `data/raw/crossref_response.json` |
| Query/filter                | query `agentic retrieval augmented generation large language model`, filter `from-pub-date:<today-180d>,has-abstract:true`, rows 24 |
| Thời điểm lấy dữ liệu | Snapshot đi kèm repo; run gần nhất 2026-09-25 (mode `snapshot`, xem `phase1_report.md`) |
| Số record nhận được    | 24 items → 24 records |
| Cơ chế retry/backoff      | 4 lần thử, backoff 2s·2^(n-1) cho 429/500/502/503/504 và lỗi mạng; thất bại hoặc 0 record thì fallback về snapshot |

### Raw và clean schema

| Trường        | Kiểu dữ liệu | Bắt buộc?  | Ý nghĩa   | Xử lý khi thiếu/sai |
| --------------- | --------------- | ------------ | ----------- | ---------------------- |
| `paper_id` | str (DOI lowercase) | Có | Khoá tài liệu, dùng cho ground truth | Thiếu thì bỏ record; trùng thì giữ bản `updated` mới nhất |
| `title` | str | Có | Tiêu đề, dùng cho exact lookup | Thiếu thì bỏ; bỏ thẻ và khoảng trắng thừa |
| `summary` | str | Có | Abstract đã bỏ `<jats:*>` | Thiếu thì bỏ record |
| `authors` | list[str] | Không | `given family` hoặc `name` | Rỗng thì `[]` |
| `categories` / `primary_category` | list[str] / str | Không | Crossref `subject` | Rỗng thì `Uncategorized` |
| `published` / `updated` | str `YYYY-MM-DD` | `published` bắt buộc | Từ `date-parts` (thiếu tháng/ngày thì lấy 01) | Không parse được thì bỏ; `updated` fallback bằng `published` |
| `age_days` | int | Có | `(run_date - published).days` | Tính lại mỗi lần chạy |
| `text_for_embedding` | str | Có | Ghép 5 phần Title/Authors/Published/Categories/Summary | Sinh lại sau corruption |

### Quy tắc cleaning

| Quy tắc                                 | Quality dimension liên quan | Số record bị tác động | Cách xác minh      |
| ---------------------------------------- | ---------------------------- | -------------------------: | -------------------- |
| Bỏ thẻ JATS/HTML + unescape entity trong abstract | Validity | 24 (mọi abstract snapshot đều bọc `<jats:p>`) | `tests/test_ingestion.py::test_snapshot_parses_to_24_records` |
| Drop record thiếu DOI/title/abstract/published | Completeness | 0 trên snapshot | `test_parse_payload_normalises_and_filters` (dữ liệu tổng hợp: loại 3/5) |
| Dedupe theo `paper_id` (giữ bản `updated` mới nhất) | Uniqueness | 0 trên snapshot | `test_cleaning_dedupes_strips_tags_and_drops_bad_rows` |
| Chuẩn hoá ngày ISO + `age_days` | Timeliness | 24 | `data/quality/freshness_report.json` |

Cách tạo `text_for_embedding`, document ID và `age_days`:

`paper_id` là DOI viết thường, ổn định qua mọi lần chạy nên dùng được làm `ground_truth_doc_ids`. Trong Chroma, record id là `paper_id::index` để các dòng duplicate (khi bị corruption) vẫn index được. `age_days = (run_date − published).days`, trong đó `run_date` là ngày chạy phase 1 và được lưu vào `data/results/phase1_run.json`, để repair dùng lại đúng ngày đó và tái tạo bit-by-bit. `text_for_embedding` có dạng `Title: …\nAuthors: …\nPublished: …\nCategories: …\nSummary: …`, nên khi một trường bị corrupt thì vector cũng thay đổi theo.

## 6. Evaluation setup

| Thành phần                             | Cấu hình thực tế          |
| ---------------------------------------- | ----------------------------- |
| Số câu hỏi                            | 10 |
| Các`question_type`                    | summary (3), authors (3), date (2), categories (2) |
| Ground-truth document ID                 | DOI của paper được chọn ở vị trí cách đều trong corpus (sắp xếp theo ngày mới nhất), mỗi câu một paper khác nhau |
| Embedding model                          | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector store/collection                  | ChromaDB persistent `data/chroma`, cosine; `papers-baseline`, `papers-corrupted`, `papers-repaired` |
| Retrieval`top_k`                       | 4 |
| LLM provider/model                       | openai / gpt-4o-mini cho judge; `judge_mode` trong metrics ghi rõ heuristic fallback khi không có key |
| Test set dùng chung cho ba trạng thái | `data/eval/test_set.json` (chỉ sinh lại khi `REFRESH_TEST_SET=1`) |

Vì sao giữ nguyên test set: test set là thước đo cố định. Nếu sinh lại test set từ dữ liệu corrupted thì ground truth cũng bị corrupt theo (ví dụ summary rỗng thì đáp án cũng rỗng), và metric sẽ không giảm, che mất silent failure. Dùng cùng một file cho cả 3 trạng thái thì mọi chênh lệch metric chỉ còn do dữ liệu gây ra.

## 7. Kết quả baseline

### Artifact checklist

| Artifact                 | Đường dẫn thực tế                | Trạng thái | Ghi chú   |
| ------------------------ | -------------------------------------- | ------------ | ---------- |
| Raw response/records     | `data/raw/`                          | Có | 24 items / 24 records |
| Cleaned dataset          | `data/clean/`                        | Có | `papers_clean.{csv,json}` + bản corrupted/repaired |
| Embedding manifest/index | `data/embeddings/`, `data/chroma/` | Có | 3 manifest, `persist_path` tương đối |
| Evaluation set           | `data/eval/test_set.json` | Có | 10 câu |
| Baseline metrics         | `data/results/baseline_metrics.json` | Có | kèm `by_question_type` |
| Quality/freshness        | `data/quality/`                      | Có | baseline/corrupted/repaired |
| Baseline report          | `data/reports/phase1_report.md`      | Có | |

### Baseline metrics

| Metric                 |       Giá trị | Diễn giải                             |
| ---------------------- | --------------: | --------------------------------------- |
| `retrieval_hit_rate` | 1.0 | Cả 10 câu đều có tài liệu đích trong top-4 (exact-title lookup + semantic search) |
| `mean_token_f1`      | 1.0 | Câu trả lời trích xuất trùng khớp ground truth |
| `judge_accuracy`     | 1.0 | Heuristic judge (F1 ≥ 0.5 được coi là đúng) |
| `mean_judge_score`   | 5 | |
| Ragas, nếu có        | N/A | Bỏ qua mặc định (`RUN_RAGAS=1` để bật), vì chậm và cần LLM key |

## 8. Data quality và freshness

### Quality checks

| Check        | Quality dimension | Ngưỡng/kỳ vọng | Kết quả baseline      | Bằng chứng |
| ------------ | ----------------- | ------------------ | ----------------------- | ------------ |
| `ExpectTableRowCountToBeBetween` | Volume | 5–5000 dòng | Pass (24) | `data/quality/baseline_quality_report.json` |
| `ExpectColumnValuesToNotBeNull` × 3 | Completeness | `paper_id`, `title`, `text_for_embedding` không null | Pass (0 null) | idem |
| `ExpectColumnValuesToBeUnique` | Uniqueness | `paper_id` duy nhất | Pass | idem |
| `ExpectColumnValueLengthsToBeBetween` (summary) | Validity | ≥ 30 ký tự | Pass | idem |
| `ExpectColumnValueLengthsToBeBetween` (title) | Validity | ≥ 8 ký tự | Pass | idem |

### Freshness

| Thuộc tính               | Giá trị                           |
| -------------------------- | ----------------------------------- |
| Freshness được đo tại | Clean dataset (`age_days`) → `data/quality/freshness_report.json` |
| Timestamp mới nhất       | 2026-07-22 (cũ nhất 2026-03-28) |
| Ngưỡng freshness         | `age_days > 180` là stale; fresh khi stale ratio ≤ 25% |
| Trạng thái baseline      | Fresh |
| Lý do                     | 1/24 bản ghi stale (0.0417 ≤ 0.25) |

## 9. Corruption scenarios và repair

| Corruption         | Cách tạo | Record bị tác động | Quality signal kỳ vọng | Tác động thực tế | Cách repair   |
| ------------------ | ---------- | ---------------------: | ------------------------ | --------------------- | -------------- |
| `drop_latest_records` | Bỏ 20% bài mới nhất | 5 | `latest_published` lùi lại | latest 2026-07-22 → 2026-06-11; eval_001/002/003 mất hit | Rebuild từ raw |
| `blank_summary` | summary = "" | 4 (5 dòng tính cả duplicate) | `summary_min_length` fail | GX fail, 5 dòng vi phạm | Rebuild từ raw |
| `inject_noise` | Bọc summary bằng chuỗi rác | 3 | Không có (độ dài vẫn hợp lệ) | eval_005 F1 1.00 → 0.80 | Rebuild từ raw |
| `truncate_title` | title[:7] | 5 (7 dòng) | `title_min_length` fail | GX fail, 7 dòng vi phạm | Rebuild từ raw |
| `stale_date` | published −365 ngày | 8 (11 dòng) | Freshness `is_fresh=False` | stale ratio 0.44; eval_007 trả lời sai năm (F1 0) | Rebuild từ raw |
| `duplicate_rows` | Nhân đôi 30% dòng | 6 | `paper_id_unique` fail | 12 dòng vi phạm, 24 → 25 dòng | Rebuild từ raw (dedupe) |

Corruption log:

- Đường dẫn: `data/results/corruption_log.json`
- Trạng thái: Có
- Nhận xét: Log ghi đủ 6 loại corruption, kèm tham số (ratio, shift_days, noise_token, seed 42), số dòng bị tác động và danh sách `paper_id` cụ thể.

Cách repair đảm bảo dữ liệu được phục hồi từ nguồn đáng tin cậy:

Repair không sửa trên dataframe bị corrupt. `repair_from_raw()` đọc lại `data/raw/crossref_records.json` (raw bất biến, được lưu trước mọi bước biến đổi) rồi chạy lại đúng `build_clean_dataframe()` với `run_date` của baseline. Vì là hàm thuần của (raw, run_date), chạy N lần luôn cho cùng kết quả. `repair_summary.json` ghi lại SHA-256: baseline = repair run 1 = repair run 2 = `f0be02afc5d4360f…`, còn corrupted = `0625190a6dec882e…`. Repair được kích hoạt tự động bởi `self_healing_gate()` khi GX hoặc freshness fail (`auto_repair_triggered = True`), sau đó dữ liệu repair được validate lại (pass 7/7) trước khi index.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal            | Baseline | Corrupted | Repaired | Thay đổi do corruption | Mức phục hồi | Nhận xét   |
| ------------------------ | -------: | --------: | -------: | -----------------------: | --------------: | ------------ |
| `retrieval_hit_rate`   | 1.0 | 0.7 | 1.0 | −0.30 | 100% | 3 câu mất tài liệu đích do `drop_latest_records` |
| `mean_token_f1`        | 1.0 | 0.68 | 1.0 | −0.32 | 100% | Do drop (eval_001, eval_003), noise (eval_005), stale date (eval_007) |
| `judge_accuracy`       | 1.0 | 0.7 | 1.0 | −0.30 | 100% | Heuristic judge |
| `mean_judge_score`     | 5 | 3.6 | 5 | −1.4 | 100% | |
| Quality checks pass/fail | Pass 7/7 | Fail 4/7 | Pass 7/7 | 3 check fail | Phục hồi | unique, summary length, title length |
| Freshness status         | Fresh (0.04) | Stale (0.44) | Fresh (0.04) | +0.40 stale ratio | Phục hồi | stale_date + duplicate |

Kết luận nhân quả:

1. `stale_date` + `duplicate_rows` làm 11/25 dòng có `age_days > 180`, khiến Freshness SLA chuyển `is_fresh=False` (0.44 > 0.25). Câu eval_007 (date) trả lời `2025-06-04` thay vì `2026-06-04`, F1 1.0 → 0.0. Agent vẫn trả lời tự tin, không báo lỗi.
2. `drop_latest_records` xoá 5 bài mới nhất, khiến 3 câu (eval_001–003) mất retrieval hit và hit rate giảm 1.0 → 0.7. Repair từ raw khôi phục 24 bài, GX pass 7/7, freshness fresh, hit rate và F1 về lại 1.0 (recovery 100%, hash trùng baseline).

Kết quả khác kỳ vọng: eval_002 (authors) mất retrieval hit nhưng F1 vẫn 1.0, vì corpus có bài "Advanced Perspectives on …" trùng tác giả với bài bị xoá. Agent trả lời "đúng" nhưng dựa trên tài liệu sai. Đây là minh chứng rằng metric chỉ đo câu trả lời thì có thể che lỗi retrieval. `truncate_title` (eval_004) không làm mất hit vì semantic search trên câu hỏi vẫn tìm ra đúng tài liệu.

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** Manifest `data/embeddings/*.json` của starter lưu `persist_path` là đường dẫn tuyệt đối của máy chạy (`D:\...\data\chroma`). Khi clone sang máy khác và gọi `LocalEmbeddingIndex.load()`, Chroma trỏ vào thư mục không tồn tại. Việc này còn dính lỗi "hardcode đường dẫn tuyệt đối".
- **Nguyên nhân:** `str(persist_path)` được ghi thẳng vào artifact có commit lên repo.
- **Cách xử lý:** Thêm `_portable_path()` / `_resolve_path()` trong `src/retrieval/index.py` để lưu đường dẫn tương đối với project root (`data/chroma`) và resolve lại khi load.
- **Cách xác minh:** `tests/test_retrieval_eval.py::test_index_search_lookup_and_eval` assert `persist_path == "data/chroma"` và load lại index thành công trong thư mục tạm.

Vấn đề thứ hai: key OpenAI không hợp lệ làm lỗi 401 kèm key đã che một phần bị ghi vào `agent_demo_answers.json`. Nhóm đã thêm `_safe_error()` để redact mọi chuỗi giống API key trước khi ghi artifact.

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng   | Hướng cải thiện có thể kiểm chứng |
| --------------------- | -------------- | ----------------------------------------- |
| GX không bắt được `inject_noise` | Nhiễu chỉ lộ ra qua F1, sau khi đã serve | Thêm expectation regex / tỉ lệ ký tự không phải chữ trong summary; kiểm chứng `corrupted_quality_report` fail thêm check này |
| `drop_latest_records` không fail GX (24 → 25 dòng vẫn trong 5–5000) | Mất dữ liệu mới mà gate vẫn pass | So row count / `latest_published` với lần chạy trước (volume + freshness drift); test bằng corrupted run |
| Judge dùng heuristic khi thiếu key | `judge_accuracy` gần như trùng hit/F1 | Chạy với key LLM hợp lệ, so `judge_mode=llm:*` |
| Corpus nhỏ, có cặp bài gần trùng | Hit rate có thể nhiễu | Mở rộng `max_results`, thêm metric MRR |

## 13. Checklist trước khi nộp

- [x] Thông tin nhóm và repository chính xác.
- [x] Phân công khớp với module, artifact và kết quả thực tế.
- [x] Lệnh tái hiện đã được chạy lại trên phiên bản dùng để nộp.
- [x] Baseline, corrupted và repaired dùng cùng evaluation set.
- [x] Bảng metrics khớp với các file trong `data/results/`.
- [x] Quality/freshness conclusions khớp với `data/quality/`.
- [x] Các đường dẫn báo cáo và artifact truy cập được.
- [x] Mỗi thành viên đã hoàn thành báo cáo vai trò riêng.
- [x] Không có `.env`, API key, token hoặc secret trong source, report, log hay ảnh.
