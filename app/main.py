"""
FastAPI REST API for PR Code Review System
"""
from fastapi import FastAPI, HTTPException
import logging
from app.api.middleware import setup_cors
from app.api.routes import review

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Code Review System APIs",
    description="Github PR code review system with multi-agent architecture",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

setup_cors(app)

app.include_router(review.router)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health():
    return {"status":"ok", "service": "pr-review-system"}

@app.on_event("startup")
async def startup():
    logger.info("🚀 PR Review System started — waiting for GitHub webhooks")
