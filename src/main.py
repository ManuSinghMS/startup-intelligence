"""
Startup Intelligence Platform — FastAPI Application Entry Point
"""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from src.db.database import init_db, close_db
from src.routes import startups, content, search, summaries, sources, health, social


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Run migrations first (adds new columns to existing tables)
    try:
        from src.db.migrate import migrate
        migrate()
    except Exception as e:
        print(f"Migration note: {e}")

    # Then initialize (runs CREATE TABLE IF NOT EXISTS for new installs)
    init_db()

    print("Startup Intelligence Platform is ready!")

    # Start scheduler (optional)
    try:
        from src.ingestion.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"Scheduler start failed (non-critical): {e}")

    yield

    # Shutdown
    try:
        from src.ingestion.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    close_db()


app = FastAPI(
    title="Startup Intelligence Platform",
    description="AI-powered startup news, social & newsletter intelligence",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(startups.router)
app.include_router(content.router)
app.include_router(search.router)
app.include_router(summaries.router)
app.include_router(sources.router)
app.include_router(health.router)
app.include_router(social.router)

# Serve static files
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    """Serve the dashboard."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Startup Intelligence Platform API", "docs": "/docs"}


@app.get("/company/{startup_id}")
async def company_page(startup_id: str):
    """Serve the company detail page."""
    page_path = os.path.join(static_dir, "company.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Company page not found"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("src.main:app", host=host, port=port, reload=True)
