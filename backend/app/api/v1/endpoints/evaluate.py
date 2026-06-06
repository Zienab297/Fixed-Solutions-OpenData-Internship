"""/evaluate endpoint stub — implement in sprint."""
from fastapi import APIRouter, Depends
from app.api.v1.dependencies.auth import get_current_user
from app.models.schemas.auth import CurrentUser

router = APIRouter(prefix="/evaluate", tags=["evaluate"])

@router.get("")
async def list_items(current_user: CurrentUser = Depends(get_current_user)):
    return {"message": "implement in sprint", "endpoint": "/evaluate"}
