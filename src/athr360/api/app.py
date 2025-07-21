"""
FastAPI application entry-point.

All runtime wiring (middleware, routers, startup/shutdown) lives here so tests
can import `app` without side-effects.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import asyncio
import os

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from athr360.api.routers import admin, feedback, health, chat
from athr360.config.settings import settings
from athr360.utils.di import get_vector_store         
from athr360.infrastructure.ingest import refresh_vector_index 
from athr360.utils.error import BaseError, ErrorSeverity
from athr360.services.session_tracker import SessionTracker   
from athr360.services.gemini_service import GeminiService
from athr360.infrastructure.embeddings import VertexDirectEmbeddings

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("athar360.app")

session_tracker = SessionTracker(idle_minutes=settings.session_idle_minutes)

# Store temporary credentials path for cleanup
_temp_credentials_path = None

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise expensive singletons once per process and dispose on exit."""
    global _temp_credentials_path
    
    logger.info("ATHAR360 starting up…")

    # Initialize database connections first
    try:
        from athr360.db.session import init_database
        await init_database()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        # Check if we should fail on DB errors
        if os.environ.get("SKIP_DB_INIT", "").lower() not in ("true", "1", "yes"):
            raise
        else:
            logger.warning("Continuing without database (SKIP_DB_INIT=true)")

    # Store temporary credentials path for cleanup
    if settings.gemini.use_aws_secrets and settings.gemini.credentials_path:
        _temp_credentials_path = settings.gemini.credentials_path
        logger.info("Using AWS Secrets Manager for Gemini credentials")

    # Warm-up heavyweight services so the first request is brisk
    vector_store = get_vector_store()
    await vector_store.warmup()           # no-op if your store doesn't need it

    # If no embeddings OR there are new files, build them now
    new_docs = await refresh_vector_index(vector_store)
    if new_docs:
        logger.info("Indexed %d fresh document(s) on startup", new_docs)

    # Initialize LLM service in background to reduce first-request latency
    asyncio.create_task(_warmup_services())

    # Log current app instance
    try:
        from athr360.config.app_config import get_current_app_config, detect_app_instance_from_hostname, detect_app_instance_from_env
        
        # Show detection methods
        hostname_instance = detect_app_instance_from_hostname()
        env_instance = detect_app_instance_from_env()
        
        logger.info("App Instance Detection:")
        logger.info(f"   • Hostname detection: {hostname_instance if hostname_instance else 'None'}")
        logger.info(f"   • Environment variable: {env_instance if env_instance else 'None'}")
        
        # Show current hostname for debugging
        hostname = (
            os.environ.get("HOSTNAME") or
            os.environ.get("HOST") or
            os.environ.get("SERVER_NAME") or
            os.environ.get("INGRESS_HOST")
        )
        if hostname:
            logger.info(f"   • Current hostname: {hostname}")
        
        # Get final configuration
        app_config = get_current_app_config()
        logger.info(f"Using app instance: {app_config.instance_id} ({app_config.name})")
        logger.info(f"Knowledge base: {app_config.knowledge_base_dir}")
        logger.info(f"Embeddings: {app_config.embeddings_dir}")
        logger.info(f"Prompts: {app_config.prompt_dir}")
        
    except Exception as e:
        logger.error(f"Error during app instance detection: {e}")
        logger.info("Continuing with default configuration")

    logger.info("✅  Startup complete")
    try:
        yield
    finally:
        logger.info("👋  Shutting down...")
        
        # Clean up temporary credentials if using AWS Secrets Manager
        if _temp_credentials_path:
            try:
                from athr360.utils.secret_manager import cleanup_temp_credentials
                cleanup_temp_credentials(_temp_credentials_path)
                logger.info("Cleaned up temporary AWS credentials")
            except Exception as e:
                logger.warning(f"Failed to cleanup temporary credentials: {e}")
        
        # Clean up database connections
        try:
            from athr360.db.session import close_database
            await close_database()
        except Exception as e:
            logger.error(f"Database cleanup failed: {e}")
        logger.info("👋  Goodbye")


async def _warmup_services():
    """Warm up LLM and embedding services in the background."""
    try:
        # Initialize Gemini
        logger.info("Warming up Gemini service...")
        gemini = GeminiService()
        await gemini.test_connection()
        
        # Initialize embeddings
        logger.info("Warming up embeddings service...")
        embeddings = VertexDirectEmbeddings()
        # Force initialization by embedding a test string
        await asyncio.to_thread(embeddings.embed_query, "warmup")
        
        logger.info("Service warmup complete")
    except Exception as e:
        logger.warning(f"Service warmup failed (non-critical): {e}")


app = FastAPI(
    title=settings.app_name,
    description="ATHAR360 Compliance PDPL Assistant backend",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
    redirect_slashes=False,
)

# Custom CORS middleware to handle OPTIONS requests consistently
@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    """Handle CORS for all requests, especially OPTIONS."""
    # Handle OPTIONS requests immediately
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept, Origin, X-Requested-With",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "86400",
            }
        )
    
    # Process the request
    response = await call_next(request)
    
    # Add CORS headers to all responses
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, Origin, X-Requested-With"
    
    return response

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(admin.router,  prefix="/admin", tags=["admin"])
app.include_router(chat.router, prefix="/api", tags=["chat"])

@app.exception_handler(BaseError)
async def athar360_error_handler(_: Request, exc: BaseError) -> JSONResponse:
    """Return structured JSON for domain errors; fall back to FastAPI default
    for everything else.
    """
    status_code = (
        status.HTTP_400_BAD_REQUEST
        if exc.severity in {ErrorSeverity.INFO, ErrorSeverity.WARNING}
        else status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    return JSONResponse(status_code=status_code, content=exc.to_dict())
