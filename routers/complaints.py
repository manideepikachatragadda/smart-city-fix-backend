import os
from fastapi import APIRouter, Depends, HTTPException, Path, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Annotated, Optional
from starlette import status
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from models import Complaint, Feedback, ComplaintStatus, ComplaintHistory, DepartmentRole, UserRole, User
from database import get_db
from routers.auth import get_current_user
from utils.workflow import process_complaint_ai, calculate_sla_deadline
from utils.email_service import send_alert_email
from config import settings
from sqlalchemy import desc

import cloudinary
import cloudinary.uploader
import shutil

from utils.notifications import send_push_notification_task
import random


cloudinary.config( 
  cloud_name = settings.CLOUDINARY_CLOUD_NAME, 
  api_key = settings.CLOUDINARY_API_KEY, 
  api_secret = settings.CLOUDINARY_API_SECRET,
  secure = True
)

router = APIRouter(prefix="/complaints", tags=["complaints"])

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

class ComplaintSubmitRequest(BaseModel):
    name: Optional[str] = None
    phone_number: str = Field(min_length=10, max_length=15)
    location: str
    category: str
    description: str = Field(min_length=5)
    image_url: Optional[str] = None

class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5, description="Rating from 1 to 5 stars")
    comments: Optional[str] = None


# Change db_session_factory to session_factory
def upload_to_cloudinary_task(complaint_id, temp_path):
    # Use SessionLocal() directly here
    from database import SessionLocal
    db = SessionLocal()
    try:
        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(
            temp_path, 
            folder="smartcity/resolutions/",
            public_id=f"complaint_{complaint_id}_proof"
        )
        secure_url = upload_result.get("secure_url")

        # Update the complaint with the real URL
        complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if complaint:
            complaint.resolved_image_url = secure_url
            db.commit()
        
        # Clean up local file
        if os.path.exists(temp_path):
            os.remove(temp_path)
    except Exception as e:
        print(f"Background upload failed: {e}")
    finally:
        db.close() # Crucial: Always close the connection in background tasks


def upload_citizen_image_task(complaint_id: int, temp_path: str):
    from database import SessionLocal
    db = SessionLocal()
    try:
        upload_result = cloudinary.uploader.upload(
            temp_path, 
            folder="smartcity/complaints/",
            public_id=f"complaint_{complaint_id}_original"
        )
        complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if complaint:
            complaint.image_url = upload_result.get("secure_url")
            db.commit()

        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    except Exception as e:
        print(f"Background upload failed: {e}")
        
    finally:
        db.close()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def submit_complaint(
    db: db_dependency, 
    background_tasks: BackgroundTasks,
    location: str = Form(...),
    description: str = Form(...),
    phone_number: str = Form(...),
    email: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None) 
):
    # 1. AI Analysis
    try:
        # Note: Ensure your process_complaint_ai utility is updated to only require description
        analysis = process_complaint_ai(description)
    except Exception:
        raise HTTPException(status_code=502, detail="AI processing failed.")

    deadline = calculate_sla_deadline(analysis.sla_hours)

    # 2. Smart Auto-Assignment Logic
    assigned_worker = None
    department_workers = db.query(User).filter(
        User.role == UserRole.WORKER.value,
        User.department == analysis.nlp_category,
        User.is_active == True
    ).all()
    
    if department_workers:
        # Try to find workers whose location matches the complaint location
        location_matches = [w for w in department_workers if w.location and w.location.lower() in location.lower()]
        
        if location_matches:
            assigned_worker = random.choice(location_matches) # Pick random from location matches
        else:
            assigned_worker = random.choice(department_workers) # Fallback: random from department
            
    # Automatically move to IN_PROGRESS if we found someone
    initial_status = ComplaintStatus.IN_PROGRESS if assigned_worker else ComplaintStatus.PENDING

    # 3. Create Database Record
    new_complaint = Complaint(
        name=name,
        phone_number=phone_number,
        email=email,
        location=location,
        description=description,
        image_url=None, 
        nlp_category=analysis.nlp_category,
        priority_level=analysis.priority_level,
        priority_score=analysis.priority_score,
        status=initial_status,
        estimated_resolution_time=deadline,
        department_assigned=analysis.nlp_category,
        assigned_user_id=assigned_worker.id if assigned_worker else None
    )

    db.add(new_complaint)
    db.commit()
    db.refresh(new_complaint)

    # 4. Handle Image in Background
    if file:
        temp_dir = "static/temp_citizen"
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = f"{temp_dir}/citizen_{new_complaint.id}_{file.filename}"
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        background_tasks.add_task(upload_citizen_image_task, new_complaint.id, temp_path)

    # 5. Audit Trail
    db.add(ComplaintHistory(
        complaint_id=new_complaint.id,
        old_status=ComplaintStatus.PENDING,
        new_status=initial_status,
        changed_by_user_id=None
    ))
    db.commit()

    # Send Confirmation Email to the Citizen
    if email:
        background_tasks.add_task(
            send_alert_email,
            to_email=email,
            alert_type="COMPLAINT RECEIVED",
            complaint_id=new_complaint.id,
            category=new_complaint.department_assigned.value,
            location=location,
            description=f"You can track your complaint using ID: #{new_complaint.id}"
        )

    # 6. Notifications (Push + Email for Worker and Manager)
    if assigned_worker:
        # A. Alert the Worker
        background_tasks.add_task(
            send_push_notification_task, user_id=assigned_worker.id,
            title="New Task Auto-Assigned 🚨", body=f"A new {analysis.nlp_category.value} issue at {location}."
        )
        background_tasks.add_task(
            send_alert_email, to_email=assigned_worker.email, alert_type="NEW TASK ASSIGNED",
            complaint_id=new_complaint.id, category=analysis.nlp_category.value, location=location, description=description
        )
        
        # B. Alert their Manager
        if assigned_worker.manager_id:
            manager = db.query(User).filter(User.id == assigned_worker.manager_id).first()
            if manager:
                background_tasks.add_task(
                    send_push_notification_task, user_id=manager.id,
                    title="Worker Auto-Assigned 📋", body=f"{assigned_worker.first_name} was auto-assigned to a new {analysis.nlp_category.value} issue."
                )
                background_tasks.add_task(
                    send_alert_email, to_email=manager.email, alert_type="TEAM TASK ASSIGNED",
                    complaint_id=new_complaint.id, category=analysis.nlp_category.value, location=location, description=description
                )

    return {
        "complaint_id": new_complaint.id,
        "classification": analysis.nlp_category,
        "priority": analysis.priority_level,
        "priority_score": analysis.priority_score,
        "assigned_to": assigned_worker.id if assigned_worker else None,
        "status": new_complaint.status,
        "message": "Complaint processing"
    }

@router.put("/{complaint_id}/status", status_code=status.HTTP_200_OK)
async def update_status(
    new_status: ComplaintStatus, 
    user: user_dependency, 
    db: db_dependency, 
    complaint_id: int = Path(gt=0)
):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # Security check: Admins OR users in the matching department
    if user.get("role") != UserRole.ADMIN.value and user.get("department") != complaint.department_assigned.value:
        raise HTTPException(status_code=403, detail="Unauthorized for this department.")

    # --- ENFORCE MANAGEMENT HIERARCHY ---
    
    # Only Managers can CLOSE a ticket
    if new_status == ComplaintStatus.CLOSED and user.get("role") != UserRole.MANAGER.value:
        raise HTTPException(status_code=403, detail="Only Department Managers can officially close a ticket.")
        
    # Only Managers can REJECT a ticket
    if new_status == ComplaintStatus.REJECTED and user.get("role") != UserRole.MANAGER.value:
        raise HTTPException(status_code=403, detail="Only Department Managers can reject a resolved ticket.")
        
    # Prevent Workers from moving a closed ticket back to in_progress
    if complaint.status == ComplaintStatus.CLOSED and user.get("role") != UserRole.MANAGER.value:
         raise HTTPException(status_code=403, detail="Ticket is closed. Only a Manager can reopen it.")

    # Write to Audit Trail
    history = ComplaintHistory(
        complaint_id=complaint.id,
        old_status=complaint.status,
        new_status=new_status,
        changed_by_user_id=user.get("id")
    )
    db.add(history)

    # Auto-assign logic
    if new_status == ComplaintStatus.IN_PROGRESS and complaint.assigned_user_id is None:
        complaint.assigned_user_id = user.get("id")

    # Update Complaint Status
    complaint.status = new_status
    
    # We now mark 'resolved_at' when the MANAGER closes it
    if new_status == ComplaintStatus.CLOSED:
        complaint.resolved_at = datetime.now(timezone.utc)
    
    db.commit()
    return {"message": f"Complaint status updated to {new_status.value}"}

@router.post("/{complaint_id}/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(request: FeedbackRequest, db: db_dependency, complaint_id: int = Path(gt=0)):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint or complaint.status != ComplaintStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Can only provide feedback for resolved complaints.")
        
    existing_feedback = db.query(Feedback).filter(Feedback.complaint_id == complaint_id).first()
    if existing_feedback:
        raise HTTPException(status_code=400, detail="Feedback already submitted.")

    feedback = Feedback(complaint_id=complaint_id, rating=request.rating, comments=request.comments)
    db.add(feedback)
    db.commit()
    return {"message": "Feedback submitted successfully."}

@router.post("/trigger-escalations", status_code=status.HTTP_200_OK)
async def check_and_escalate(db: db_dependency, background_tasks: BackgroundTasks):
    now = datetime.now(timezone.utc)
    delayed_complaints = db.query(Complaint).filter(
        Complaint.status.in_([ComplaintStatus.PENDING, ComplaintStatus.IN_PROGRESS]),
        Complaint.estimated_resolution_time < now,
        Complaint.is_escalated == False
    ).all()

    admin_email = settings.ADMIN_EMAIL
    escalated_count = 0

    for complaint in delayed_complaints:
        complaint.is_escalated = True
        complaint.escalation_reason = "SLA breached"
        escalated_count += 1
        
        if admin_email:
            background_tasks.add_task(
                send_alert_email,
                to_email=admin_email,
                alert_type="ESCALATION (SLA BREACH)",
                complaint_id=complaint.id,
                category=complaint.department_assigned.value,
                location=complaint.location,
                description=complaint.description
            )

    db.commit()
    return {"escalated_count": escalated_count}



@router.get("/", status_code=status.HTTP_200_OK)
async def get_complaints(user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    role = user.get("role")
    user_id = user.get("id")
    department = user.get("department")

    # 1. ADMIN: Can see everything in the city
    if role == UserRole.ADMIN.value:
        return db.query(Complaint).order_by(desc(Complaint.created_at)).all()

    # 2. MANAGER: Can see everything in their specific department
    elif role == UserRole.MANAGER.value:
        return db.query(Complaint).filter(
            Complaint.department_assigned == department
        ).order_by(desc(Complaint.created_at)).all()

    # 3. WORKER: Strictly only sees tickets assigned to THEIR ID
    elif role == UserRole.WORKER.value:
        return db.query(Complaint).filter(
            Complaint.assigned_user_id == user_id
        ).order_by(desc(Complaint.created_at)).all()

    else:
        raise HTTPException(status_code=403, detail="Role not recognized.")

@router.get("/{complaint_id}", status_code=status.HTTP_200_OK)
async def get_single_complaint(user: user_dependency, db: db_dependency, complaint_id: int = Path(gt=0)):
    """Fetch details of a specific complaint, ensuring the department owns it."""
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    
    if user.get("role") != UserRole.ADMIN.value and user.get("department") != complaint.department_assigned.value:
        raise HTTPException(status_code=403, detail="Unauthorized for this department.")

    return complaint

@router.put("/{complaint_id}/assign/{worker_id}", status_code=status.HTTP_200_OK)
async def assign_worker(
    user: user_dependency, 
    db: db_dependency,
    background_tasks: BackgroundTasks, 
    complaint_id: int = Path(gt=0),
    worker_id: int = Path(gt=0)
):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    # 1. Security Check: Only Managers can assign work
    if user.get("role") != UserRole.MANAGER.value:
        raise HTTPException(status_code=403, detail="Only Managers can assign tickets.")

    # 2. Find the complaint
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # 3. Department Check: Manager can only touch their own department's tickets
    if user.get("department") != complaint.department_assigned.value:
        raise HTTPException(status_code=403, detail="You can only assign tickets for your department.")

    # 4. Verify the worker exists AND belongs to this specific manager
    from models import User # Make sure User is imported at the top
    worker = db.query(User).filter(
        User.id == worker_id, 
        User.manager_id == user.get("id"),
        User.is_active == True
    ).first()
    
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found or not assigned to your team.")

    # 5. Make the Assignment
    complaint.assigned_user_id = worker.id
    
    # Optional: Automatically move the status from PENDING to IN_PROGRESS
    if complaint.status == ComplaintStatus.PENDING:
        complaint.status = ComplaintStatus.IN_PROGRESS

    db.commit()

    # TRIGGER THE NOTIFICATION
    background_tasks.add_task(
        send_push_notification_task,
        user_id=worker.id,
        title="New Task Assigned 📋",
        body=f"You have been assigned to a new {complaint.department_assigned.value} issue at {complaint.location}."
    )

    return {
        "message": f"Complaint #{complaint_id} successfully assigned to {worker.first_name} {worker.last_name}.",
        "status": complaint.status.value
    }



@router.put("/{complaint_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_complaint(
    complaint_id: int,
    user: user_dependency,
    db: db_dependency,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    if not user or user.get("role") != UserRole.WORKER.value:
        raise HTTPException(status_code=401, detail='Only assigned workers can resolve tasks.')

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint or complaint.assigned_user_id != user.get("id"):
        raise HTTPException(status_code=403, detail="You are not assigned to this complaint.")

    # 1. Save file locally temporarily (very fast)
    temp_dir = "static/temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = f"{temp_dir}/temp_{complaint_id}_{file.filename}"
    
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 2. Update status immediately so UI updates instantly
    complaint.status = ComplaintStatus.RESOLVED
    db.commit()

    # 3. Queue the Cloudinary upload for the background
    background_tasks.add_task(upload_to_cloudinary_task, complaint_id, temp_path)

    return {"message": "Task marked as resolved. Image is processing in background."}


@router.get("/track/{complaint_id}", status_code=status.HTTP_200_OK)
async def track_complaint(db: db_dependency, complaint_id: int = Path(gt=0)):
    """Public endpoint for citizens to track their complaint status."""
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    return {
        "complaint_id": complaint.id,
        "description": complaint.description,
        "status": complaint.status.value,
        "department": complaint.department_assigned.value,
        "location": complaint.location,
        "estimated_resolution": complaint.estimated_resolution_time,
        "resolved_at": complaint.resolved_at,
        "resolved_image_url": complaint.resolved_image_url, # Show them the proof!
        "created_at": complaint.created_at
    }

@router.put("/{complaint_id}/review", status_code=status.HTTP_200_OK)
async def review_complaint(
    complaint_id: int,
    action: str, # "approve" or "revert"
    user: user_dependency,
    db: db_dependency
):
    if user.get("role") not in [UserRole.MANAGER.value, UserRole.ADMIN.value]:
        raise HTTPException(status_code=403, detail="Only Managers or Admins can review tasks.")

    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if action == "approve":
        # Official Closure
        complaint.status = ComplaintStatus.CLOSED
        complaint.resolved_at = datetime.now(timezone.utc)
        message = "Ticket successfully closed."
    
    elif action == "revert":
        # Send back to the worker
        complaint.status = ComplaintStatus.IN_PROGRESS
        # Clear the proof if it was invalid
        complaint.resolved_image_url = None 
        message = "Ticket reverted to In Progress for further work."
    
    else:
        raise HTTPException(status_code=400, detail="Invalid action.")

    db.commit()
    return {"message": message, "new_status": complaint.status}





@router.post("/{complaint_id}/feedback", status_code=status.HTTP_201_CREATED)
async def submit_customer_review(
    db: db_dependency,
    request: FeedbackRequest,
    complaint_id: int = Path(gt=0)
):
    """Public endpoint for citizens to leave a review on a closed ticket."""
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found.")
        
    # Security: Only allow reviews on CLOSED tickets
    if complaint.status != ComplaintStatus.CLOSED:
        raise HTTPException(status_code=400, detail="You can only review tickets that have been closed.")
        
    # Prevent duplicate reviews
    existing_feedback = db.query(Feedback).filter(Feedback.complaint_id == complaint_id).first()
    if existing_feedback:
        raise HTTPException(status_code=400, detail="A review has already been submitted for this ticket.")

    # Create the dedicated Feedback record
    new_feedback = Feedback(
        complaint_id=complaint.id,
        rating=request.rating,
        comments=request.comments
    )
    
    db.add(new_feedback)
    db.commit()

    return {"message": "Thank you! Your review has been submitted successfully."}