# athar360/api/__main__.py
"""
Package entry-point.

`python -m athr360.api` ➜ starts Uvicorn with the FastAPI app declared in
`athr360.api.app`.

All heavyweight initialisation (vector-store warm-up, etc.) is handled by the
lifespan context inside `app.py`, so we only need to start the server.
"""

from __future__ import annotations

import uvicorn
from athr360.config.settings import settings


def main() -> None:  
    """Boot Uvicorn with sane defaults taken from settings."""
    uvicorn.run(
        "athr360.api.app:app",         
        host=settings.host,  
        port=settings.port, 
        reload=settings.debug,        # hot-reload in dev
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__": 
    main()
