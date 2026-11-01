import argparse
import io
import sys
from pathlib import Path

# Đảm bảo mã hóa UTF-8 trên Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Thêm thư mục gốc vào sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.schemas.document import DocRole, DocCategory
from src.converters.pdf_converter import convert_pdf_to_parsed_document, save_parsed_document_to_json

def main():
    parser = argparse.ArgumentParser(
        description="Bộ chuyển đổi file PDF sang JSON chuẩn ParsedDocument cho Bidding AI Reviewer"
    )
    parser.add_argument("input_pdf", help="Đường dẫn file PDF đầu vào")
    parser.add_argument("output_json", nargs="?", default=None, help="Đường dẫn file JSON đầu ra (mặc định cùng tên file)")
    parser.add_argument(
        "--role",
        choices=["LAW", "HSMT", "HSDT"],
        default="LAW",
        help="Vai trò văn bản: LAW (Luật), HSMT (Hồ sơ mời thầu), HSDT (Hồ sơ dự thầu)"
    )
    parser.add_argument(
        "--category",
        default="TONG_HOP",
        help="Phân loại danh mục (TONG_HOP, DON_DU_THAU, BAO_LANH_DU_THAU, GIAY_UY_QUYEN...)"
    )
    parser.add_argument("--doc-id", default=None, help="Mã định danh duy nhất (doc_id)")

    args = parser.parse_args()

    input_path = Path(args.input_pdf)
    if not input_path.exists():
        print(f"❌ Lỗi: Không tìm thấy file PDF '{input_path}'", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output_json) if args.output_json else input_path.with_suffix(".json")
    role_enum = DocRole(args.role)

    print(f"📄 Đang xử lý file PDF: {input_path.name} (Role: {role_enum.value})...")
    try:
        parsed_doc = convert_pdf_to_parsed_document(
            pdf_source=input_path,
            doc_role=role_enum,
            file_name=input_path.name,
            doc_id=args.doc_id
        )

        save_parsed_document_to_json(parsed_doc, output_path)
        print(f"✅ Chuyển đổi thành công!")
        print(f"   - Mã tài liệu: {parsed_doc.doc_id}")
        print(f"   - Số trang: {parsed_doc.total_pages}")
        print(f"   - Số phân đoạn bóc tách: {len(parsed_doc.sections)}")
        print(f"   - File JSON đã lưu tại: {output_path}")

    except Exception as e:
        print(f"❌ Lỗi trong quá trình chuyển đổi: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
