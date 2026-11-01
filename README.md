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

## 2. Tiện Ích Chuyển Đổi File PDF ➔ JSON ParsedDocument

Hệ thống tích hợp sẵn bộ chuyển đổi PDF chuyên dụng bóc tách cấu trúc văn bản pháp luật và hồ sơ đấu thầu:

### A. Chuyển đổi qua dòng lệnh (CLI):
```bash
# Chuyển đổi văn bản Luật (tự động phân mảnh theo Điều/Khoản)
python scripts/convert_pdf.py data_law/43-2024-qh15.pdf data/mock_law/43-2024-qh15.json --role LAW

# Chuyển đổi Hồ sơ mời thầu (HSMT)
python scripts/convert_pdf.py path/to/hsmt.pdf path/to/hsmt.json --role HSMT

# Chuyển đổi Hồ sơ dự thầu (HSDT)
python scripts/convert_pdf.py path/to/hsdt.pdf path/to/hsdt.json --role HSDT
```

### B. Tải trực tiếp file PDF trên Giao diện Streamlit:
- **Tại tab Dữ liệu Luật:** Cho phép upload trực tiếp file `.pdf`, tự động bóc tách Điều/Khoản và lưu vào kho CSDL Luật để dựng GraphRAG.
- **Tại tab Thẩm định HSMT:** Cho phép upload trực tiếp file `.pdf`, tự động bóc tách tiêu chí và thẩm định.
- **Tại tab Thẩm định HSDT:** Cho phép upload trực tiếp file `.pdf`, tự động trích xuất các thành phần hồ sơ và lập Ma trận Tuân thủ.
- **Tab Tiện ích chuyên biệt:** "🛠️ Bộ chuyển đổi PDF ➔ JSON" giúp xem trước, tải file JSON hoặc lưu vào dự án với 1 cú click.

---

## 3. Các Module Tri Thức Nâng Cao (Thừa Kế Từ Legal Retrieval Lab)

Dự án được kế thừa và tối ưu hóa 3 module chuyên sâu từ dự án [Legal Retrieval Lab (test-kg-rag)](file:///D:/GitHub/test-kg-rag):

1. **Bộ bóc tách dẫn chiếu pháp luật chuyên sâu (`LegalCitationParser`):**
   - Định vị: [src/graph_rag/citation_parser.py](file:///D:/GitHub/test-dau-thau/src/graph_rag/citation_parser.py)
   - Tự động nhận diện và bóc tách các loại quan hệ pháp lý: `REFERENCES` (dẫn chiếu thông thường), `DETAILS` (hướng dẫn thi hành, quy định chi tiết), `AMENDS` (sửa đổi, bổ sung), `REPEALS` (bãi bỏ).
   - Tự động phân tích các số hiệu văn bản quy phạm pháp luật chuẩn (Luật, Nghị định, Thông tư) và làm giàu đồ thị liên văn bản.

2. **Phân mảnh có tiêm ngữ cảnh Cha-Con theo Chiến lược A3 (`StructureChunker`):**
   - Định vị: [src/converters/structure_chunker.py](file:///D:/GitHub/test-dau-thau/src/converters/structure_chunker.py)
   - Áp dụng kỹ thuật **Context Header Injection**: Tiêm tiền tố `[Văn bản: {doc_title} | {Chương} > {Điều}]\n{Tiêu đề}` vào từng chunk Khoản/Điểm con.
   - Ngăn chặn hoàn toàn hiện tượng mất ngữ cảnh khi nhúng vector và tra cứu trong kho tài liệu đấu thầu khổng lồ.

3. **Bộ mở rộng đồ thị & đường đi chứng minh (`GraphExpander`):**
   - Định vị: [src/graph_rag/expander.py](file:///D:/GitHub/test-dau-thau/src/graph_rag/expander.py)
   - Hỗ trợ duyệt đồ thị đa tầng (1-hop, 2-hop) kèm hệ số suy giảm (`hop_decay = 0.7`) và ma trận trọng số quan hệ pháp luật.
   - Thưởng điểm tương đồng từ khóa (`lexical overlap bonus`) giữa câu hỏi thẩm định và điều luật mở rộng.
   - Tự động xây dựng đường đi giải trình (`expansion_path`) và căn cứ chứng minh (`evidence_text`) giúp báo cáo thẩm định minh bạch 100%.

---

## 4. Kiểm Thử Hệ Thống (Pytest)

Chạy bộ kiểm thử tự động toàn diện kiểm tra tất cả các tầng (Schemas, Deterministic Rules, GraphRAG, Luồng 1 HSMT, Luồng 2 HSDT, Các module chuyển đổi A3 & Legal Parser, và FastAPI REST Endpoints):

```bash
pytest tests/ -v
# 20/20 test cases passed
```

---

## 5. Khởi Chạy Giao Diện Demo (Streamlit)

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
