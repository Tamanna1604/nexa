"""Start the Nexa web app: `python run.py` then open http://127.0.0.1:8000"""

from __future__ import annotations

import uvicorn

from nexa.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "nexa.api.app:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
    )
