# Checklist Triển Khai Bidding AI Reviewer (Dành cho 3.8 Flash)

- [x] **Task 1: Thiết lập Môi trường, Cấu hình & Pydantic Schemas**
  - [x] Tạo `requirements.txt`
  - [x] Tạo `config/__init__.py`, `config/settings.py`, `config/prompts.yaml`
  - [x] Tạo `src/__init__.py`, `src/schemas/__init__.py`
  - [x] Tạo `src/schemas/document.py` (`ParsedDocument`, `DocumentMetadata`, `DocumentSection`, `TableItem`, `VisualCues`, cùng `ExtractedGuaranteeFacts` & `ExtractedAuthFacts` để LLM bóc tách biến số/ngày tháng từ văn bản)
  - [x] Tạo `src/schemas/criteria.py` (`EvaluationCriterion`, `CriteriaList`, `CriterionCategory`)
  - [x] Tạo `src/schemas/report.py` (`ComplianceStatus`, `EvidenceItem`, `LegalReference`, `CriterionAssessment`, `VerificationReport`)

- [x] **Task 2: Khởi tạo Bộ Dữ liệu JSON Mẫu Tối giản (`data/mock_*`)**
  - [x] Tạo `data/mock_law/land_bidding_laws.json` (các điều khoản Luật Đấu thầu & Đất đai có tham chiếu chéo)
  - [x] Tạo `data/mock_hsmt/hsmt_sample.json` (HSMT có cài 1 tiêu chí vi phạm trần bảo lãnh dự thầu 5% > 3%)
  - [x] Tạo `data/mock_hsdt/hsdt_sample.json` (HSDT có 1 tiêu chí đạt, 1 tiêu chí bảo lãnh thiếu ngày hiệu lực, 1 tiêu chí ủy quyền bị mờ con dấu)

- [x] **Task 3: Xây dựng Unified LLM Gateway (`src/llm/gateway.py`)**
  - [x] Tạo `src/llm/__init__.py` và `src/llm/gateway.py`
  - [x] Hỗ trợ `provider="gemini"` (`google-genai` Structured Outputs)
  - [x] Hỗ trợ `provider="local"` (`openai` client kết nối Local LLM endpoint)
  - [x] Hỗ trợ `provider="mock"` / fallback để chạy test offline ổn định

- [x] **Task 4: Xây dựng GraphRAG cho Tri thức Pháp luật (`src/graph_rag/`)**
  - [x] Tạo `src/graph_rag/__init__.py`
  - [x] Tạo `src/graph_rag/indexer.py` (bóc tách điều khoản, dựng `networkx.DiGraph` với cạnh `REFERENCES`, lưu `data/storage/law_graph.json`, nạp vector vào ChromaDB)
  - [x] Tạo `src/graph_rag/retriever.py` (truy xuất lai Vector Search Top-K + 1-hop Graph traversal)

- [x] **Task 5: Xây dựng Deterministic Rules Engine (`src/engines/deterministic_rules.py`)**
  - [x] Tạo `src/engines/__init__.py` và `src/engines/deterministic_rules.py`
  - [x] Hiện thực `check_guarantee_validity`
  - [x] Hiện thực `check_authorization_dates`
  - [x] Hiện thực `verify_visual_stamps`

- [x] **Task 6: Luồng 1 — Thẩm định HSMT (`src/engines/criteria_extractor.py`, `src/engines/hsmt_reviewer.py`)**
  - [x] Tạo `src/engines/criteria_extractor.py`
  - [x] Tạo `src/engines/hsmt_reviewer.py` (đối chiếu tiêu chí HSMT với GraphRAG Luật, xuất `VerificationReport`)

- [x] **Task 7: Luồng 2 — Kiểm tra HSDT (`src/engines/hsdt_checker.py`)**
  - [x] Tạo `src/engines/hsdt_checker.py` (dùng LLM Structured Output bóc tách các biến ngày tháng/số tiền từ `content_markdown` -> truyền vào `deterministic_rules.py` tính toán -> kết hợp `GraphRAG` + `LLM Gateway` xuất `VerificationReport` với 3 trạng thái `HOP_LE`, `KHONG_HOP_LE`, `CHUA_DU_CAN_CU`)

- [x] **Task 8: FastAPI Layer (`src/api/main.py`) & Kiểm thử (`tests/test_workflows.py`)**
  - [x] Tạo `src/api/__init__.py` và `src/api/main.py`
  - [x] Tạo `tests/__init__.py` và `tests/test_workflows.py`
  - [x] Chạy `pytest tests/test_workflows.py -v` đảm bảo pass 100%

- [x] **Task 9: Giao diện Demo Streamlit (`ui/app.py`) & Tài liệu (`README.md`)**
  - [x] Tạo `ui/app.py` (Sidebar cấu hình LLM & Re-index GraphRAG, Tab 1 Thẩm định HSMT, Tab 2 Kiểm tra HSDT & Ma trận tuân thủ)
  - [x] Cập nhật `README.md` hướng dẫn cài đặt và chạy Demo
