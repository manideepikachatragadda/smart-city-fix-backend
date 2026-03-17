from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Annotated
from starlette import status
from pydantic import BaseModel

# --- ASYNC SQLALCHEMY IMPORTS ---
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete

from models import PushSubscription, User, UserRole
from database import get_db
from routers.auth import get_current_user
from utils.notifications import send_push_notification_task

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Updated to use AsyncSession
db_dependency = Annotated[AsyncSession, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

# --- PYDANTIC MODELS ---

class PushKeys(BaseModel):
    p256dh: str
    auth: str

class SubscriptionRequest(BaseModel):
    endpoint: str
    keys: PushKeys

class UnsubscribeRequest(BaseModel):
    endpoint: str

class CustomMessageRequest(BaseModel):
    target_user_id: int
    title: str
    message: str

# --- ENDPOINTS ---

@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
async def subscribe_to_push(
    subscription: SubscriptionRequest, 
    db: db_dependency, 
    user: user_dependency
):
    """
    Saves the browser's Web Push subscription keys to the database 
    so the server can send alerts to this specific user later.
    """
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    # 1. Async Select Query
    stmt = select(PushSubscription).filter(PushSubscription.endpoint == subscription.endpoint)
    result = await db.execute(stmt)
    exists = result.scalar_one_or_none()
    
    if not exists:
        new_sub = PushSubscription(
            user_id=user.get("id"),
            endpoint=subscription.endpoint,
            p256dh=subscription.keys.p256dh,
            auth=subscription.keys.auth
        )
        db.add(new_sub)
        await db.commit() # Await commit
        return {"message": "Successfully subscribed to push notifications."}
        
    return {"message": "Already subscribed."}


@router.delete("/unsubscribe", status_code=status.HTTP_200_OK)
async def unsubscribe_from_push(
    request: UnsubscribeRequest, 
    db: db_dependency, 
    user: user_dependency
):
    """Removes the push subscription (e.g., when a user logs out)."""
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    # 2. Async Delete Statement
    stmt = delete(PushSubscription).filter(
        PushSubscription.endpoint == request.endpoint,
        PushSubscription.user_id == user.get("id")
    )
    result = await db.execute(stmt)
    await db.commit()

    # In async SQLAlchemy, we check rowcount to see how many were deleted
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Subscription not found.")

    return {"message": "Successfully unsubscribed from notifications."}


@router.post("/send-message", status_code=status.HTTP_200_OK)
async def send_custom_message(
    request: CustomMessageRequest,
    user: user_dependency,
    db: db_dependency,
    background_tasks: BackgroundTasks
):
    """Allows Managers/Admins to send direct alerts."""
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    if user.get("role") not in [UserRole.MANAGER.value, UserRole.ADMIN.value]:
        raise HTTPException(status_code=403, detail="Only Managers and Admins can send direct alerts.")

    # 3. Async Select for Target User
    stmt = select(User).filter(User.id == request.target_user_id)
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Hierarchy Check (Managers can only message their own team)
    if user.get("role") == UserRole.MANAGER.value and target_user.manager_id != user.get("id"):
        raise HTTPException(status_code=403, detail="You can only message workers assigned to your team.")

    # Fire the notification
    background_tasks.add_task(
        send_push_notification_task,
        user_id=target_user.id,
        title=request.title,
        body=request.message
    )

    return {"message": f"Push notification queued for {target_user.first_name}."}