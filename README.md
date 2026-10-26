# HỆ THỐNG TRỢ LÝ AI THẨM TRA HỒ SƠ ĐẤU THẦU (BIDDING AI REVIEWER)

Hệ thống thẩm định hồ sơ mời thầu (HSMT) và kiểm tra tính hợp lệ của hồ sơ dự thầu (HSDT) theo quy chuẩn Luật Đấu thầu và Luật Đất đai Việt Nam.

Hệ thống hoạt động theo mô hình **Hybrid Architecture**:
1. **Knowledge Graph + Vector Search (GraphRAG):** Quản lý tri thức pháp luật bằng đồ thị NetworkX kết hợp ChromaDB cục bộ.
2. **Deterministic Rule Engine:** Tính toán toán học, ngày tháng và kiểm tra chữ ký/con dấu đỏ tuyệt đối chính xác bằng Python thuần.
3. **LLM Gateway (Gemini / Local / Mock):** Bóc tách thông tin tự nhiên, tổng hợp lập luận pháp lý và hỗ trợ ra quyết định.

---

## 1. Cài Đặt Môi Trường

Yêu cầu: Python >= 3.10

```bash
# Cài đặt các thư viện cần thiết
pip install -r requirements.txt
```

---

## 2. Kiểm Thử Hệ Thống (Pytest)

Chạy bộ kiểm thử tự động toàn diện kiểm tra tất cả các tầng (Schemas, Deterministic Rules, GraphRAG, Luồng 1 HSMT, Luồng 2 HSDT, và FastAPI REST Endpoints):

```bash
pytest tests/test_workflows.py -v
```

---

## 3. Khởi Chạy Giao Diện Demo (Streamlit)

Giao diện được thiết kế lại gồm 2 phần lớn theo đúng quy trình nghiệp vụ:
- **🗄️ Phần 1: Kho Dữ Liệu:**
  - **1. Dữ liệu Luật & GraphRAG:** Nơi tải lên văn bản luật, bấm nút "Dựng / Cập nhật Đồ thị Tri thức (GraphRAG)", xem thống kê số node/cạnh tham chiếu và tra cứu thử nghiệm điều khoản.
  - **2. Thẩm định HSMT:** Nơi tải lên file HSMT, bóc tách bộ tiêu chí chuẩn và phát hiện các quy định vi phạm trần luật hoặc cài cắm hạn chế nhà thầu.
- **⚖️ Phần 2: Thẩm Định HSDT:**
  - Tải lên Hồ sơ dự thầu của nhà thầu.
  - Tự động đối chiếu với Bộ tiêu chí đã thẩm định từ HSMT ở Phần 1.
  - Xem **Ma trận Tuân thủ (Compliance Matrix)**, trích dẫn số trang, kết quả soi con dấu/chữ ký và nội dung đề xuất gửi nhà thầu giải trình.

```bash
streamlit run ui/app.py
```

*Trong giao diện Streamlit, bạn có thể chọn:*
- **Provider "mock":** Để thử nghiệm tính năng ngay lập tức với dữ liệu giả lập có sẵn, không cần API Key.
- **Provider "gemini":** Nhập `Gemini API Key` để LLM thực hiện trích xuất và lập luận trực tiếp.
- **Provider "local":** Kết nối với local LLM endpoint (vLLM, Ollama, v.v.).

---

## 4. Khởi Chạy REST API (FastAPI)

Nếu bạn muốn tích hợp hệ thống qua REST API độc lập:

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Truy cập tài liệu Swagger UI tại: `http://localhost:8000/docs`

Các endpoints chính:
- `GET /health`: Kiểm tra trạng thái hệ thống.
- `POST /api/v1/graph/reindex`: Nạp lại đồ thị và vector index văn bản luật từ `data/mock_law/`.
- `POST /api/v1/hsmt/review`: Thẩm định HSMT.
- `POST /api/v1/hsdt/check`: Kiểm tra HSDT và xuất báo cáo thẩm tra.

---

## 5. Cấu Trúc Thư Mục Dự Án

```text
├── config/
│   ├── settings.py              # Đọc biến môi trường, đường dẫn CSDL
│   └── prompts.yaml             # Hệ thống Prompts chuẩn hóa
├── data/
│   ├── mock_law/                # JSON văn bản Luật Đấu thầu & Đất đai mẫu
│   ├── mock_hsmt/               # JSON Hồ sơ mời thầu mẫu
│   ├── mock_hsdt/               # JSON Hồ sơ dự thầu mẫu
│   └── storage/                 # Đồ thị law_graph.json và ChromaDB cục bộ
├── src/
│   ├── schemas/                 # Pydantic Schemas (Document, Criteria, Report)
│   ├── llm/                     # Unified LLM Gateway (Gemini / Local / Mock)
│   ├── graph_rag/               # GraphRAG Indexer & Hybrid Retriever
│   ├── engines/                 # Rule Engine, Criteria Extractor, HSMT Reviewer, HSDT Checker
│   └── api/                     # FastAPI App & Endpoints
├── ui/
│   └── app.py                   # Streamlit UI Demo
├── tests/
│   └── test_workflows.py        # 100% Coverage Workflow Tests
├── tasks/                       # Kế hoạch & Checklist triển khai
└── requirements.txt
```
