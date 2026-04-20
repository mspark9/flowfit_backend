"""
Flowfit — FastAPI 앱 진입점
실행: uvicorn main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from routers.finance import router as finance_router
from routers.auth import router as auth_router
from routers.HR.employee_management import router as hr_employee_router
from routers.HR.issued_employee_ids import router as hr_issued_ids_router
from routers.HR.retirement import router as hr_retirement_router
from routers.HR.regulations import router as hr_router
from routers.HR.recruitment import router as hr_recruitment_router
from routers.HR.hr_evaluation import router as hr_evaluation_router
from routers.HR.hr_team_eval import router as hr_team_eval_router
from routers.CS.cs_response import router as cs_response_router
from routers.CS.cs_faq import router as cs_faq_router
from routers.CS.cs_voc import router as cs_voc_router
from routers.CS.cs_policy import router as cs_policy_router
from routers.marketing.mkt_copy import router as mkt_copy_router
from routers.marketing.mkt_sns import router as mkt_sns_router
from routers.marketing.mkt_press import router as mkt_press_router
from routers.marketing.mkt_image import router as mkt_image_router
from routers.legal import router as legal_router
from routers.strategy import router as strategy_router
from routers.procurement import router as procurement_router
from routers.sales.sales_proposal import router as sales_proposal_router
from routers.sales.sales_performance import router as sales_performance_router
from routers.sales.sales_meeting import router as sales_meeting_router
from routers.dev.dev_log import router as dev_log_router
from routers.dev.dev_docs import router as dev_docs_router
from routers.dev.dev_release import router as dev_release_router
from routers.dev.dev_translate import router as dev_translate_router

app = FastAPI(title="Flowfit API")

# CORS — Frontend 도메인만 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth_router,        prefix="/api/auth",         tags=["auth"])
app.include_router(hr_employee_router, prefix="/api/auth",         tags=["hr"])
app.include_router(hr_issued_ids_router, prefix="/api/auth",      tags=["hr"])
app.include_router(hr_retirement_router, prefix="/api/auth",      tags=["hr"])
app.include_router(finance_router,     prefix="/api/finance")
app.include_router(hr_router,          prefix="/api/hr",           tags=["hr"])
app.include_router(hr_recruitment_router, prefix="/api/hr",        tags=["hr"])
app.include_router(hr_evaluation_router, prefix="/api/hr/evaluation", tags=["hr"])
app.include_router(hr_team_eval_router, prefix="/api/hr/team-eval", tags=["hr"])
app.include_router(cs_response_router, prefix="/api/cs/response",  tags=["cs"])
app.include_router(cs_faq_router,      prefix="/api/cs/faq",       tags=["cs"])
app.include_router(cs_voc_router,      prefix="/api/cs/voc",       tags=["cs"])
app.include_router(cs_policy_router,   prefix="/api/cs/policy",    tags=["cs"])
app.include_router(mkt_copy_router,    prefix="/api/marketing/copy", tags=["marketing"])
app.include_router(mkt_sns_router,     prefix="/api/marketing/sns",  tags=["marketing"])
app.include_router(legal_router,       prefix="/api/legal",           tags=["legal"])
app.include_router(procurement_router, prefix="/api/procurement",     tags=["procurement"])
app.include_router(mkt_press_router,       prefix="/api/marketing/press",       tags=["marketing"])
app.include_router(mkt_image_router,       prefix="/api/marketing/image",       tags=["marketing"])
app.include_router(sales_proposal_router,   prefix="/api/sales/proposal",         tags=["sales"])
app.include_router(sales_performance_router, prefix="/api/sales/performance",     tags=["sales"])
app.include_router(sales_meeting_router,    prefix="/api/sales/meeting",          tags=["sales"])
app.include_router(dev_log_router,         prefix="/api/dev/log",                tags=["dev"])
app.include_router(dev_docs_router,        prefix="/api/dev/docs",               tags=["dev"])
app.include_router(dev_release_router,     prefix="/api/dev/release",            tags=["dev"])
app.include_router(dev_translate_router,   prefix="/api/dev/translate",          tags=["dev"])
app.include_router(strategy_router,        prefix="/api/strategy",               tags=["strategy"])


@app.get("/")
def root():
    return {"status": "ok", "message": "Flowfit API가 실행 중입니다."}


@app.get("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
