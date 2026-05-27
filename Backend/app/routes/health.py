from fastapi import APIRouter, Header, HTTPException
from app.database import supabase
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    try:
        supabase.table("cities").select("id").limit(1).execute()
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "db": db_status}


@router.post("/jobs/auto-confirm")
async def trigger_auto_confirm(x_cron_secret: str = Header(...)):
    if x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    from app.jobs.auto_confirm import run_auto_confirm
    confirmed = run_auto_confirm()
    return {"confirmed": confirmed}
