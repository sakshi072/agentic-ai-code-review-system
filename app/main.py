"""
FastAPI REST API for PR Code Review System
"""
from fastapi import FastAPI, HTTPException
import logging
from app.api.middleware import setup_cors
from app.api.routes import review
from app.clients.github_mcp_client import github_mcp_session
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)

@asynccontextmanager
async def lifespan(app:FastAPI):
    logger.info("Starting Code Review System...")
    try:
        # Initialize MongoDB
        await github_mcp_session.start()
        logger.info("Started GitHub MCP session")

        logger.info("Application startup complete")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise

    yield

    logger.info("Shutting down Code Review System...")
    try:
        await github_mcp_session.stop()
        logger.info("Graceful shutdown complete")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Code Review System APIs",
    description="Github PR code review system with multi-agent architecture",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

setup_cors(app)

app.include_router(review.router)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health():
    return {"status":"ok", "service": "pr-review-system"}
