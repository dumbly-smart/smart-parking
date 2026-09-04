from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

DASHBOARD_DIRECTORY = Path(__file__).resolve().parents[1] / "dashboard"

router = APIRouter()


@router.get("/dashboard", response_class=FileResponse)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_DIRECTORY / "index.html", media_type="text/html")
