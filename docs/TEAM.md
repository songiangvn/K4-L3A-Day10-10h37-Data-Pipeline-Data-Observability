# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `10h37`
- **Mã Nhóm / Lớp:** `K4-L3-DAY10`
- **Tên Repository Nộp Bài:** `K4-L3-DAY10-10h37-DataPipeline`

---

## # Thành viên

| STT | Họ và tên | MSSV | Email | Vai trò & Phân công công việc | Báo cáo cá nhân |
|---:|---|---|---|---|---|
| 1 | Nguyễn Sơn Giang | 2A202602747 | giang.nguyen25@imperial.ac.uk | Trưởng nhóm / Pipeline Integrator + Data Foundation + RAG + Corruption & Repair (`core/`, `crossref.py`, `cleaning.py`, `retrieval/`, `corruption.py`, `phase1.py`, `corruption_flow.py`) | `report/2A202602747_NguyenSonGiang.md` |
| 2 | Nguyễn Ngọc Thái An | 2A202602462 | — | Observability & Evaluation support (`quality.py` review, `testset.py` review, `reporting.py`/dashboard verification, test suite & CI, group report) | `report/2A202602462_NguyenNgocThaiAn.md` |

*(Nhóm 2 thành viên: thành viên 1 sở hữu phần lớn module code; thành viên 2 phụ trách kiểm chứng observability/evaluation, test và báo cáo. Phân công checkpoint ở bảng dưới.)*

### Phân công theo Checkpoint

| Checkpoint | Nội dung | Owner chính | Hỗ trợ |
|---|---|---|---|
| CP0 | Môi trường, `.env`, Crossref ingestion + fallback snapshot | Nguyễn Sơn Giang | Nguyễn Ngọc Thái An (kiểm tra smoke test) |
| CP1 | Cleaning (`cleaning.py`) + GX 1.x quality gate & Freshness SLA (`quality.py`) | Nguyễn Sơn Giang | Nguyễn Ngọc Thái An (review expectations, đối chiếu `data/quality/`) |
| CP2 | Test set 10 câu (`testset.py`) + ChromaDB `papers-baseline` | Nguyễn Sơn Giang | Nguyễn Ngọc Thái An (review câu hỏi & ground truth) |
| CP3 | Baseline end-to-end (`phase1.py`) + `phase1_report.md` | Nguyễn Sơn Giang | Nguyễn Ngọc Thái An (đối chiếu metrics với báo cáo) |
| CP4 | 6 corruption scenarios (`corruption.py`) + corrupted metrics | Nguyễn Sơn Giang | — |
| CP5 | Idempotent / self-healing repair (`corruption_flow.py`) + `corruption_report.md` + dashboard | Nguyễn Sơn Giang | Nguyễn Ngọc Thái An (kiểm tra dashboard, test suite, CI) |
| CP6 | Live demo, Q&A, nộp LMS | Cả nhóm | Cả nhóm |

---

## # Cá nhân

### ## NguyenSonGiang-2A202602747
- **Vai trò:** Trưởng nhóm, Pipeline Integrator, Data Foundation, RAG & Corruption/Repair owner.
- **Công việc chi tiết đã hoàn thành:**
  - `src/ingestion/crossref.py`: parse Crossref payload (DOI, title, abstract bỏ thẻ JATS, authors, subject, dates, URLs), gọi API với retry/backoff cho 429/5xx, dual-mode live/snapshot, lưu 2 raw artifacts.
  - `src/ingestion/cleaning.py`: chuẩn hoá text, parse ngày, dedupe theo `paper_id`, tính `age_days`, sinh `text_for_embedding` 5 phần.
  - `src/observability/quality.py`: Quality gate GX 1.x (`gx.get_context(mode="ephemeral")`, `data_sources.add_pandas`, 7 expectations gồm 4 expectation bắt buộc) + Freshness SLA (`age_days > 180`, ngưỡng 25%).
  - `src/evaluation/testset.py`: bộ 10 câu hỏi cố định trải đều 4 loại `summary/authors/date/categories`.
  - `src/ingestion/corruption.py`: 6 kịch bản corruption tất định (seed 42) + `corruption_log.json`.
  - `src/pipelines/phase1.py`, `src/pipelines/corruption_flow.py`: orchestration, self-healing gate tự repair từ raw, chứng minh idempotent bằng SHA-256.
  - `src/observability/reporting.py`, `src/observability/dashboard.py`: báo cáo Markdown 3 trạng thái và dashboard HTML.
  - `tests/` + `.github/workflows/ci.yml`: pytest end-to-end, coverage > 80%.
- **Điều học được / Đóng góp chính:**
  - Silent failure của RAG: agent vẫn trả lời trơn tru trên dữ liệu bẩn; chỉ có data-quality layer phát hiện được. Repair phải tái tạo từ raw bất biến (idempotent) chứ không vá tay dữ liệu hỏng.

### ## NguyenNgocThaiAn-2A202602462
- **Vai trò:** Observability & Evaluation support.
- **Công việc chi tiết đã hoàn thành:**
  - Review bộ expectations GX 1.x và ngưỡng Freshness SLA; đối chiếu `data/quality/*.json` với kết luận trong báo cáo.
  - Review bộ test set (câu hỏi, ground truth, `ground_truth_doc_ids`) và xác nhận dùng chung cho 3 trạng thái.
  - Kiểm tra dashboard `data/reports/dashboard.html`, chạy `python script/run_tests.py` để xác minh test suite.
  - Hoàn thiện báo cáo nhóm `report/group_report.md` và báo cáo cá nhân.
- **Điều học được / Đóng góp chính:**
  - Phân biệt quality checks (schema/validity/uniqueness) với freshness monitoring (độ tươi theo thời gian), và cách metric hit rate / token F1 phản ánh tác động của dữ liệu bẩn.
