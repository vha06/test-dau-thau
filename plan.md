# HỆ THỐNG TRỢ LÝ AI THẨM TRA HỒ SƠ ĐẤU THẦU (BIDDING AI REVIEWER)

## Technical Specification & Implementation Plan

Tài liệu đặc tả kiến trúc kỹ thuật, hợp đồng dữ liệu với đội Data OCR/Parsing, và kế hoạch phát triển chi tiết từng pha cho Coding Agent thực hiện xây dựng bản Demo (MVP).

> **Lưu ý khi triển khai:** Các ví dụ pháp lý và dữ liệu giả lập trong kế hoạch dùng để kiểm thử kỹ thuật. Trước khi dùng trong nghiệp vụ thực tế, cần xác minh căn cứ pháp lý, phiên bản văn bản và logic đánh giá với nguồn chính thức/chuyên gia phù hợp.

## 1. ĐẶC TẢ ĐẦU RA BÀN GIAO CHO ĐỘI DATA (OCR & PARSING CONTRACT)

Đội Data chịu trách nhiệm xử lý các file PDF/Word/Scan và trả về cho hệ thống các file JSON có cấu trúc. Để phục vụ vòng kiểm tra tính hợp lệ và năng lực cơ bản, dữ liệu đầu ra cần đảm bảo 4 tiêu chuẩn bắt buộc:

1.  **Giữ cấu trúc phân cấp (Hierarchical Structure):** Bóc tách phân cấp Chương, Mục, Tiểu mục để làm tọa độ đối chiếu và trích dẫn.

2.  **Bảo toàn bảng biểu (Table Preservation):** Chuyển đổi bảng biểu về định dạng Markdown Table hoặc HTML Table chuẩn, giữ nguyên liên kết hàng - cột (đặc biệt đối với báo cáo tài chính, bảng kê hợp đồng tương tự, danh sách nhân sự).

3.  **Nhận diện yếu tố xác thực vật lý (Visual Cues):** Nhận diện sự hiện diện của chữ ký, con dấu đỏ và nội dung chữ trên con dấu (nếu đọc được) để hỗ trợ kiểm tra tính hợp lệ pháp lý.

4.  **Truy vết vị trí trang (Page Grounding):** Gắn kèm số trang gốc (page_number, page_start, page_end) vào từng phân đoạn nội dung.

### JSON Schema chuẩn: parsed_document_schema.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ParsedDocument",
  "type": "object",
  "required": ["doc_id", "doc_role", "file_name", "total_pages", "sections"],
  "properties": {
    "doc_id": {
      "type": "string",
      "description": "Mã định danh duy nhất của tài liệu (VD: HSMT_GOI_DAT_DAI_01, HSDT_NHA_THAU_A)"
    },
    "doc_role": {
      "type": "string",
      "enum": ["LAW", "HSMT", "HSDT"],
      "description": "Vai trò văn bản: Luật/Quy chế, Hồ sơ mời thầu, hoặc Hồ sơ dự thầu"
    },
    "doc_category": {
      "type": "string",
      "enum": [
        "TONG_HOP",
        "DON_DU_THAU",
        "BAO_LANH_DU_THAU",
        "THOA_THUAN_LIEN_DANH",
        "GIAY_UY_QUYEN",
        "DANG_KY_KINH_DOANH",
        "BAO_CAO_TAI_CHINH",
        "HOP_DONG_TUONG_TU",
        "NHAN_SU_CHU_CHOT",
        "KHAC"
      ],
      "description": "Phân loại thành phần hồ sơ"
    },
    "file_name": {
      "type": "string",
      "description": "Tên file gốc kèm phần mở rộng"
    },
    "total_pages": {
      "type": "integer"
    },
    "metadata": {
      "type": "object",
      "properties": {
        "bidding_package_name": { "type": "string" },
        "bidder_name": { "type": "string" },
        "submission_date": { "type": "string", "format": "date" }
      }
    },
    "sections": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["section_id", "heading", "page_start", "page_end", "content_markdown"],
        "properties": {
          "section_id": { "type": "string" },
          "parent_id": { "type": ["string", "null"] },
          "heading": { "type": "string" },
          "page_start": { "type": "integer" },
          "page_end": { "type": "integer" },
          "content_markdown": {
            "type": "string",
            "description": "Toàn văn nội dung đoạn văn bản được định dạng Markdown"
          },
          "tables": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "table_id": { "type": "string" },
                "page_number": { "type": "integer" },
                "caption": { "type": "string" },
                "markdown_table": { "type": "string" }
              }
            }
          },
          "visual_cues": {
            "type": "object",
            "properties": {
              "has_signature": { "type": "boolean" },
              "has_red_stamp": { "type": "boolean" },
              "stamp_text_ocr": { "type": "string" },
              "page_numbers": {
                "type": "array",
                "items": { "type": "integer" }
              }
            }
          }
        }
      }
    }
  }
}
```


## 2. KIẾN TRÚC TỔNG THỂ HỆ THỐNG (SYSTEM ARCHITECTURE)

Hệ thống hoạt động theo mô hình Hybrid: kết hợp **Knowledge Graph + Vector Search (GraphRAG)** cho dữ liệu quy định pháp lý, **Deterministic Rule Engine** cho các kiểm tra số học/ngày tháng, và **LLM Gateway** (hỗ trợ chuyển đổi giữa Local API và Cloud API) để tổng hợp đánh giá.

```text
+-----------------------------------------------------------------------------------+
|                                  USER INTERFACE                                   |
|       (Streamlit: Cấu hình Model, Thẩm định HSMT, Kiểm tra HSDT, Xem Báo cáo)     |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                                   CORE API LAYER                                  |
|                                     (FastAPI)                                     |
+-----------------------------------------------------------------------------------+
         |                                |                                 |
         v                                v                                 v
+------------------+             +------------------+             +-----------------+
|  GraphRAG Engine |             | Criteria Engine  |             | Rule Engine     |
| (NetworkX+Chroma)|             | (HSMT Extractor) |             | (Date/Math/Cues)|
+------------------+             +------------------+             +-----------------+
         |                                |                                 |
         +--------------------------------+---------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                                 LLM GATEWAY LAYER                                 |
|  +-------------------------------------+   +------------------------------------+ |
|  |       Google Gemini API Client      |   |       Local LLM Client (OpenAI)    | |
|  |       (gemini-3.5-flash-lite)       |   |  (vLLM / LiteLLM / Ollama Endpoint)| |
|  +-------------------------------------+   +------------------------------------+ |
+-----------------------------------------------------------------------------------+
```


### Các Luồng Xử lý Dữ liệu

1.  **Luồng 0: Xây dựng Knowledge Graph Luật (Offline Indexing):**

    - Nạp các văn bản Luật Đấu thầu, Luật Đất đai, Nghị định hướng dẫn.

    - Node: LegalArticle (Điều/Khoản), Condition (Điều kiện bắt buộc), BiddingType (Loại dự án/gói thầu).

    - Edge: REFERENCES (Dẫn chiếu), APPLIES_TO (Áp dụng cho), REQUIRES (Yêu cầu).

2.  **Luồng 1: Thẩm định HSMT & Tạo Bộ Tiêu chí (Online Flow 1):**

    - Nhận JSON của HSMT.

    - Dùng LLM trích xuất danh sách các tiêu chí đánh giá thành cấu trúc chuẩn.

    - Đối chiếu tiêu chí HSMT với GraphRAG Luật để phát hiện các quy định trái luật hoặc mang tính hạn chế nhà thầu.

3.  **Luồng 2: Kiểm tra HSDT (Online Flow 2):**

    - Nhận JSON của HSDT và Bộ tiêu chí đã thẩm định từ Luồng 1.

    - Chạy song song:

      - **Deterministic Rules:** So khớp số tiền, thời hạn bảo lãnh, ngày ký ủy quyền, kiểm tra cờ chữ ký/con dấu.

      - **LLM Semantic Review:** Đánh giá nội dung pháp lý, tư cách hợp lệ dựa trên ngữ cảnh và trích dẫn từ GraphRAG.

    - Tạo báo cáo chi tiết hỗ trợ chuyên viên ra quyết định.

## 3. CẤU TRÚC THƯ MỤC DỰ ÁN (PROJECT DIRECTORY)

```text
bidding-ai-reviewer/
├── config/
│   ├── __init__.py
│   ├── settings.py              # Đọc biến môi trường, cấu hình URL Local LLM, API Key
│   └── prompts.yaml             # Hệ thống System/User prompts chuẩn hóa
├── data/
│   ├── mock_law/                # JSON giả lập điều khoản Luật Đấu thầu & Đất đai
│   ├── mock_hsmt/               # JSON giả lập Hồ sơ mời thầu mẫu
│   ├── mock_hsdt/               # JSON giả lập Hồ sơ dự thầu mẫu
│   └── storage/                 # Nơi lưu đồ thị NetworkX (.graphml) và ChromaDB
├── src/
│   ├── __init__.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── document.py          # Pydantic Schemas khớp với hợp đồng Data
│   │   ├── criteria.py          # Pydantic Schemas danh mục tiêu chí
│   │   └── report.py            # Pydantic Schemas báo cáo thẩm tra
│   ├── llm/
│   │   ├── __init__.py
│   │   └── gateway.py           # Unified Interface cho Gemini API & Local LLM
│   ├── graph_rag/
│   │   ├── __init__.py
│   │   ├── indexer.py           # Trích xuất thực thể, tạo Graph và Vector Index
│   │   └── retriever.py         # Truy xuất lai: Vector Search + 1-2 hop Graph traversal
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── deterministic_rules.py # Logic kiểm tra ngày tháng, số học, con dấu
│   │   ├── criteria_extractor.py  # Trích xuất tiêu chí từ HSMT
│   │   ├── hsmt_reviewer.py       # Đối chiếu HSMT với Luật
│   │   └── hsdt_checker.py        # Đối chiếu HSDT với HSMT và Luật
│   └── api/
│       ├── __init__.py
│       └── main.py              # FastAPI endpoints
├── ui/
│   └── app.py                   # Giao diện Streamlit Demo
├── tests/
│   └── test_workflows.py        # Kiểm thử luồng chạy tổng thể
├── requirements.txt
└── README.md
```


## 4. ĐẶC TẢ PYDANTIC SCHEMAS ĐẦU RA BÁO CÁO (src/schemas/report.py)

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class ComplianceStatus(str, Enum):
    VALID = "HOP_LE"                         # Đạt / Hợp lệ
    INVALID = "KHONG_HOP_LE"                 # Không đạt / Vi phạm
    INSUFFICIENT_BASIS = "CHUA_DU_CAN_CU"    # Chưa đủ căn cứ / Cần làm rõ bổ sung

class EvidenceItem(BaseModel):
    doc_id: str = Field(..., description="Mã tài liệu được trích xuất")
    file_name: str = Field(..., description="Tên file nguồn chứa bằng chứng")
    page_number: int = Field(..., description="Số trang chứa bằng chứng")
    extracted_quote: str = Field(..., description="Đoạn văn bản hoặc số liệu trích xuất nguyên văn")
    visual_check_note: Optional[str] = Field(None, description="Ghi chú về chữ ký/con dấu nếu có")

class LegalReference(BaseModel):
    law_name: str = Field(..., description="Tên văn bản (VD: Luật Đấu thầu 2023, HSMT Mục 2)")
    clause_id: str = Field(..., description="Điều, khoản, điểm tham chiếu")
    summary: str = Field(..., description="Tóm tắt nội dung quy định áp dụng")

class CriterionAssessment(BaseModel):
    criterion_id: str = Field(..., description="Mã định danh tiêu chí (VD: CRIT_BAO_LANH_01)")
    criterion_name: str = Field(..., description="Tên tiêu chí (VD: Tính hợp lệ của Bảo lãnh dự thầu)")
    requirement_summary: str = Field(..., description="Tóm tắt yêu cầu quy định trong HSMT và Luật")
    status: ComplianceStatus = Field(..., description="Kết luận sơ bộ của hệ thống")
    evidences: List[EvidenceItem] = Field(default_factory=list, description="Danh sách bằng chứng tìm thấy")
    references: List[LegalReference] = Field(default_factory=list, description="Căn cứ pháp lý đối chiếu")
    reasoning: str = Field(..., description="Lập luận phân tích chi tiết dẫn đến kết luận")
    missing_or_unclear_points: List[str] = Field(default_factory=list, description="Các điểm mâu thuẫn, thiếu căn cứ")
    recommendation: str = Field(..., description="Đề xuất hành động cho chuyên viên thẩm định")

class VerificationReport(BaseModel):
    report_id: str
    workflow_type: str = Field(..., description="THAM_DINH_HSMT hoặc KIEM_TRA_HSDT")
    package_name: str
    target_entity_name: str = Field(..., description="Tên bên mời thầu hoặc tên nhà thầu dự thầu")
    llm_provider_used: str = Field(..., description="gemini hoặc local")
    overall_summary: str = Field(..., description="Tóm lược tổng thể hồ sơ")
    total_criteria: int
    valid_count: int
    invalid_count: int
    insufficient_count: int
    assessments: List[CriterionAssessment]
```


## 5. KẾ HOẠCH TRIỂN KHAI CHI TIẾT (PHASED EXECUTION PLAN)

### Phase 1: Môi trường, Schemas & Unified LLM Gateway

- **Mục tiêu:** Cài đặt project, định nghĩa dữ liệu và xây dựng module chuyển đổi mô hình ngôn ngữ linh hoạt.

- **Nhiệm vụ:**

  1.  Tạo file `requirements.txt`:

      ```text
      pydantic>=2.0.0
      fastapi>=0.100.0
      uvicorn>=0.22.0
      google-genai>=0.1.1
      openai>=1.0.0
      networkx>=3.0
      chromadb>=0.4.0
      streamlit>=1.28.0
      pyyaml>=6.0
      pytest>=7.0.0
      ```

  2.  Hiện thực hóa các schema trong src/schemas/document.py, criteria.py, và report.py.

  3.  Xây dựng src/llm/gateway.py:

      - Cung cấp interface `generate_structured_output(prompt: str, response_model: Type[BaseModel], provider: str)`.

      - Nếu provider == "gemini": Gọi SDK google-genai với gemini-2.5-pro hoặc gemini-2.5-flash, sử dụng thuộc tính response_schema.

      - Nếu provider == "local": Gọi qua openai.AsyncOpenAI kết nối tới Base URL nội bộ, thực thi Structured Outputs hoặc JSON Schema enforcement.

### Phase 2: GraphRAG cho Tri thức Pháp luật (src/graph_rag/)

- **Mục tiêu:** Xây dựng cơ sở tri thức đồ thị gọn nhẹ cho quy chuẩn đấu thầu dự án đất đai.

- **Nhiệm vụ:**

  1.  indexer.py:

      - Đọc các file JSON trong data/mock_law/.

      - Phân rã văn bản thành các điều khoản, đưa vector embedding vào ChromaDB.

      - Phân tích các liên kết tham chiếu (ví dụ: *"theo quy định tại Điều X"*, *"ngoại trừ trường hợp quy định tại Khoản Y"*) và biểu diễn bằng networkx.DiGraph.

      - Lưu đồ thị ra data/storage/law_graph.json.

  2.  retriever.py:

      - Hiện thực hóa hàm retrieve_legal_context(query: str, top_k=3, hop_depth=1):

        1.  Dùng ChromaDB lấy ra Top-K điều khoản tương đồng nhất theo vector.

        2.  Từ các node này, duyệt qua các cạnh REFERENCES trong NetworkX với độ sâu 1 hop để gom các điều khoản liên quan trực tiếp.

        3.  Trả về khối văn bản pháp luật tích hợp kèm quan hệ phân cấp.

### Phase 3: Luồng 1 — Thẩm định HSMT (src/engines/)

- **Mục tiêu:** Rút trích tiêu chí từ HSMT và rà soát lỗi cài cắm so với Luật.

- **Nhiệm vụ:**

  1.  Xây dựng criteria_extractor.py: Sử dụng LLM Gateway bóc tách HSMT thành danh sách các tiêu chí kiểm tra:

      - Tư cách hợp lệ của nhà thầu.

      - Yêu cầu về Đơn dự thầu và Thời hạn hiệu lực.

      - Yêu cầu về Bảo lãnh dự thầu (giá trị, thời hạn, hình thức).

      - Yêu cầu về Năng lực tài chính (vốn chủ sở hữu, doanh thu).

      - Yêu cầu về Kinh nghiệm thực hiện dự án tương tự.

  2.  Xây dựng hsmt_reviewer.py:

      - Với mỗi tiêu chí, gọi GraphRAG để lấy điều khoản pháp luật tương ứng.

      - Kiểm tra sự tuân thủ (ví dụ: phát hiện HSMT yêu cầu tỷ lệ bảo lãnh vượt mức trần quy định của Luật Đấu thầu).

      - Trả về VerificationReport cho HSMT.

### Phase 4: Luồng 2 — Kiểm tra HSDT (src/engines/)

- **Mục tiêu:** Đối chiếu hồ sơ dự thầu với tiêu chí HSMT và quy định pháp luật.

- **Nhiệm vụ:**

  1.  Xây dựng deterministic_rules.py:

      - check_guarantee_validity(issue_date, expiry_date, bid_close_date, required_days, required_amount, actual_amount): Kiểm tra độ dài hiệu lực và giá trị bảo lãnh.

      - check_authorization_dates(auth_date, bid_sign_date, bid_close_date): Kiểm tra tính hợp lệ về thời gian của giấy ủy quyền so với đơn dự thầu.

      - verify_visual_stamps(visual_cues): Kiểm tra cờ chữ ký và con dấu pháp nhân.

  2.  Xây dựng hsdt_checker.py:

      - Đọc JSON HSDT. Với từng tiêu chí trong bộ tiêu chí HSMT:

        1.  Lấy phân đoạn hồ sơ liên quan bằng trích xuất mục/từ khóa.

        2.  Chạy hàm kiểm tra số học/ngày tháng tương ứng từ deterministic_rules.py.

        3.  Đưa bằng chứng, kết quả kiểm tra định lượng và bối cảnh từ GraphRAG vào LLM Gateway để lập luận logic.

        4.  Gán nhãn trạng thái (HOP_LE, KHONG_HOP_LE, CHUA_DU_CAN_CU), tổng hợp trích dẫn số trang và sinh khuyến nghị làm rõ.

### Phase 5: Dữ liệu Giả lập (Mock Data) & Giao diện Demo (ui/app.py)

- **Mục tiêu:** Hoàn thiện bộ kịch bản mẫu và giao diện tương tác trực quan.

- **Nhiệm vụ:**

  1.  Tạo dữ liệu giả lập trong data/:

      - data/mock_law/land_bidding_laws.json: Trích dẫn các điều khoản chọn lọc về đấu thầu dự án đất đai từ Luật Đấu thầu và Luật Đất đai.

      - data/mock_hsmt/hsmt_sample.json: HSMT dự án khu đô thị, cố tình cài 1 tiêu chí vi phạm trần bảo lãnh dự thầu.

      - data/mock_hsdt/hsdt_sample.json: HSDT của nhà thầu, gồm 1 tiêu chí đạt, 1 tiêu chí bảo lãnh thiếu ngày hiệu lực, và 1 tiêu chí ủy quyền bị mờ con dấu (dẫn đến trạng thái chưa đủ căn cứ).

  2.  Xây dựng giao diện Streamlit ui/app.py:

      - **Sidebar:** Lựa chọn LLM Engine (Google Gemini API vs Local LLM), nhập URL/Key, nút Re-index GraphRAG.

      - **Tab 1: Thẩm định HSMT:** Tải file HSMT, xem bảng bóc tách tiêu chí và cảnh báo các điểm bất hợp lý so với Luật.

      - **Tab 2: Kiểm tra HSDT:** Tải file HSDT, hiển thị bảng ma trận tuân thủ (Compliance Matrix), xem chi tiết trích dẫn số trang, đoạn văn bản bằng chứng, điểm còn thiếu căn cứ và nội dung đề xuất gửi nhà thầu làm rõ.
