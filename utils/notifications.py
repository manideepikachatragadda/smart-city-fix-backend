import json
import asyncio
from pywebpush import webpush, WebPushException
from sqlalchemy.future import select
from database import SessionLocal
from models import PushSubscription
from config import settings

async def send_push_notification_task(user_id: int, title: str, body: str):
    """Background task to send a web push notification to a specific user asynchronously."""
    
    # Using 'async with' handles the setup and teardown automatically (no more db.close() needed)
    async with SessionLocal() as db:
        try:
            # 1. Async Select Query
            stmt = select(PushSubscription).filter(PushSubscription.user_id == user_id)
            result = await db.execute(stmt)
            subs = result.scalars().all()
            
            payload = json.dumps({"title": title, "body": body})
            
            for sub in subs:
                sub_info = {
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
                }
                
                try:
                    # 2. Run the synchronous pywebpush network call in a separate thread
                    # so it doesn't block FastAPI's async event loop
                    await asyncio.to_thread(
                        webpush,
                        subscription_info=sub_info,
                        data=payload,
                        vapid_private_key=settings.PRIVATE_KEY,
                        vapid_claims={"sub": settings.SUBJECT}
                    )
                except WebPushException as ex:
                    print(f"Push failed: {ex}")
                    # 410 Gone means the user revoked permission or the browser changed the key
                    if ex.response and ex.response.status_code == 410:
                        # 3. Async Delete and Commit
                        await db.delete(sub)
                        await db.commit()
                        
        except Exception as e:
            print(f"Error in async push task: {e}")