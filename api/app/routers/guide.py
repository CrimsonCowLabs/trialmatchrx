"""The first-time guide's pinned runs."""

from fastapi import APIRouter

from app.schemas import GuidePin
from app.trace import store

router = APIRouter(prefix="/api/guide", tags=["guide"])


@router.get("", response_model=list[GuidePin])
async def list_guide_pins() -> list[GuidePin]:
    """Every pinned guide step, in guide order, with whether its run still exists. Reads the
    guide_pins and runs tables only; read-only and not traced, like the runs list (there is
    no write endpoint: pins come from `make guide-pin`)."""
    return store.list_guide_pins()
