import json
from pywebpush import webpush, WebPushException
from database import SessionLocal
from models import PushSubscription
from config import settings

def send_push_notification_task(user_id: int, title: str, body: str):
    """Background task to send a web push notification to a specific user."""
    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        payload = json.dumps({"title": title, "body": body})
        
        for sub in subs:
            sub_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
            }
            try:
                webpush(
                    subscription_info=sub_info,
                    data=payload,
                    vapid_private_key=settings.PRIVATE_KEY,
                    vapid_claims={"sub": settings.SUBJECT}
                )
            except WebPushException as ex:
                print(f"Push failed: {ex}")
                # 410 Gone means the user revoked permission or the browser changed the key
                if ex.response and ex.response.status_code == 410:
                    db.delete(sub)
                    db.commit()
    except Exception as e:
        print(f"Error in push task: {e}")
    finally:
        db.close() # Always close the background thread session