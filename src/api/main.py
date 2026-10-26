from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from src.schemas.document import ParsedDocument
from src.schemas.criteria import CriteriaList
from src.schemas.report import VerificationReport
from src.graph_rag.indexer import build_law_index
from src.engines.hsmt_reviewer import review_hsmt
from src.engines.hsdt_checker import check_hsdt

app = FastAPI(
    title="Hệ thống Trợ lý AI Thẩm tra Hồ sơ Đấu thầu (Bidding AI Reviewer)",
    description="API thẩm định tính hợp pháp của HSMT và kiểm tra tính tuân thủ của HSDT",
    version="1.0.0"
)

class HSMTReviewResponse(BaseModel):
    criteria: CriteriaList
    report: VerificationReport

class HSDTCheckRequest(BaseModel):
    hsdt_doc: ParsedDocument
    criteria_list: Optional[CriteriaList] = None
    hsmt_doc: Optional[ParsedDocument] = None
    provider: Optional[str] = None

@app.get("/health", tags=["Health"])
def health_check() -> Dict[str, str]:
    return {"status": "ok", "app": "Bidding AI Reviewer"}

@app.post("/api/v1/graph/reindex", tags=["GraphRAG"])
def reindex_legal_knowledge(
    law_dir: Optional[str] = None,
    storage_dir: Optional[str] = None
) -> Dict[str, Any]:
    """Tạo lại đồ thị tri thức NetworkX và Vector index trong ChromaDB từ văn bản luật."""
    try:
        res = build_law_index(law_dir=law_dir, storage_dir=storage_dir)
        return {"success": True, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi re-index GraphRAG: {str(e)}")

@app.post("/api/v1/hsmt/review", response_model=HSMTReviewResponse, tags=["HSMT Review"])
def review_hsmt_endpoint(
    hsmt_doc: ParsedDocument,
    provider: Optional[str] = Query(None, description="gemini, local, hoặc mock")
) -> HSMTReviewResponse:
    """
    Luồng 1: Thẩm định HSMT
    Bóc tách bộ tiêu chí và phát hiện các điều khoản trái luật hoặc hạn chế nhà thầu.
    """
    try:
        criteria_list, report = review_hsmt(hsmt_doc, provider=provider)
        return HSMTReviewResponse(criteria=criteria_list, report=report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi thẩm định HSMT: {str(e)}")

@app.post("/api/v1/hsdt/check", response_model=VerificationReport, tags=["HSDT Check"])
def check_hsdt_endpoint(
    request: HSDTCheckRequest
) -> VerificationReport:
    """
    Luồng 2: Kiểm tra HSDT
    Đối chiếu HSDT với Bộ tiêu chí HSMT, kết hợp Deterministic Rules và GraphRAG.
    """
    try:
        criteria = request.criteria_list
        if criteria is None and request.hsmt_doc is not None:
            criteria, _ = review_hsmt(request.hsmt_doc, provider=request.provider)
            
        if criteria is None:
            raise HTTPException(status_code=400, detail="Cần cung cấp criteria_list hoặc hsmt_doc để làm cơ sở kiểm tra HSDT.")
            
        report = check_hsdt(
            hsdt_doc=request.hsdt_doc,
            criteria_list=criteria,
            hsmt_doc=request.hsmt_doc,
            provider=request.provider
        )
        return report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi kiểm tra HSDT: {str(e)}")
