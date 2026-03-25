import os
import shutil
import random
import asyncio
from datetime import datetime, timezone
from typing import Annotated, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, BackgroundTasks, UploadFile, File, Form
from pydantic import BaseModel, Field
from starlette import status

# --- ASYNC SQLALCHEMY IMPORTS ---
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc

from models import Complaint, Feedback, ComplaintStatus, ComplaintHistory, UserRole, User
from database import get_db, SessionLocal
from routers.auth import get_current_user
from utils.workflow import process_complaint_ai, calculate_sla_deadline
# Updated imports for the new professional templates
from utils.email_service import send_citizen_receipt_email, send_professional_alert_email, send_resolution_email
from utils.notifications import send_push_notification_task
from config import settings

import cloudinary
import cloudinary.uploader

cloudinary.config( 
  cloud_name = settings.CLOUDINARY_CLOUD_NAME, 
  api_key = settings.CLOUDINARY_API_KEY, 
  api_secret = settings.CLOUDINARY_API_SECRET,
  secure = True
)

router = APIRouter(prefix="/complaints", tags=["complaints"])

# Updated to AsyncSession
db_dependency = Annotated[AsyncSession, Depends(get_db)]
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

# --- BACKGROUND TASKS ---

async def upload_to_cloudinary_task(complaint_id: int, temp_path: str):
    async with SessionLocal() as db:
        try:
            upload_result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                temp_path, 
                folder="smartcity/resolutions/",
                public_id=f"complaint_{complaint_id}_proof"
            )
            secure_url = upload_result.get("secure_url")

            stmt = select(Complaint).filter(Complaint.id == complaint_id)
            result = await db.execute(stmt)
            complaint = result.scalar_one_or_none()
            
            if complaint:
                complaint.resolved_image_url = secure_url
                await db.commit()
                
        except Exception as e:
            print(f"Background upload failed: {e}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

async def upload_citizen_image_task(complaint_id: int, temp_path: str):
    async with SessionLocal() as db:
        try:
            upload_result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                temp_path, 
                folder="smartcity/complaints/",
                public_id=f"complaint_{complaint_id}_original"
            )
            
            stmt = select(Complaint).filter(Complaint.id == complaint_id)
            result = await db.execute(stmt)
            complaint = result.scalar_one_or_none()
            
            if complaint:
                complaint.image_url = upload_result.get("secure_url")
                await db.commit()
        except Exception as e:
            print(f"Background upload failed: {e}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

# --- ENDPOINTS ---

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
    try:
        analysis = await process_complaint_ai(description)
    except Exception:
        raise HTTPException(status_code=502, detail="AI processing failed.")

    deadline = calculate_sla_deadline(analysis.sla_hours)

    assigned_worker = None
    stmt_workers = select(User).filter(
        User.role == UserRole.WORKER.value,
        User.department == analysis.nlp_category,
        User.is_active == True
    )
    result_workers = await db.execute(stmt_workers)
    department_workers = result_workers.scalars().all()
    
    if department_workers:
        location_matches = [w for w in department_workers if w.location and w.location.lower() in location.lower()]
        if location_matches:
            assigned_worker = random.choice(location_matches)
        else:
            assigned_worker = random.choice(department_workers) 
            
    initial_status = ComplaintStatus.IN_PROGRESS if assigned_worker else ComplaintStatus.PENDING

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
    await db.commit()
    await db.refresh(new_complaint)

    if file:
        temp_dir = "/tmp/static/temp_citizen"
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = f"{temp_dir}/citizen_{new_complaint.id}_{file.filename}"
        
        def save_file():
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        await asyncio.to_thread(save_file)
        
        background_tasks.add_task(upload_citizen_image_task, new_complaint.id, temp_path)

    db.add(ComplaintHistory(
        complaint_id=new_complaint.id,
        old_status=ComplaintStatus.PENDING,
        new_status=initial_status,
        changed_by_user_id=None
    ))
    await db.commit()

    # Convert the UTC deadline to Indian Standard Time (IST)
    local_deadline = deadline.astimezone(ZoneInfo("Asia/Kolkata"))
    formatted_deadline = local_deadline.strftime("%B %d, %Y by %I:%M %p")

    # Send Confirmation Email to the Citizen
    if email:
        tracking_url = f"{settings.FRONTEND_URL}/track"
        
        background_tasks.add_task(
            send_citizen_receipt_email,
            to_email=email,
            citizen_name=name,
            complaint_id=new_complaint.id,
            category=new_complaint.department_assigned.value,
            location=location,
            estimated_time=formatted_deadline,
            tracking_link=tracking_url
        )

    # Internal Notifications using the new Professional Template
    if assigned_worker:
        background_tasks.add_task(
            send_push_notification_task, user_id=assigned_worker.id,
            title="New Task Auto-Assigned 🚨", body=f"A new {analysis.nlp_category.value} issue at {location}."
        )
        background_tasks.add_task(
            send_professional_alert_email, to_email=assigned_worker.email, alert_type="NEW TASK ASSIGNED",
            complaint_id=new_complaint.id, category=analysis.nlp_category.value, location=location, description=description
        )
        
        if assigned_worker.manager_id:
            stmt_manager = select(User).filter(User.id == assigned_worker.manager_id)
            result_manager = await db.execute(stmt_manager)
            manager = result_manager.scalar_one_or_none()
            
            if manager:
                background_tasks.add_task(
                    send_push_notification_task, user_id=manager.id,
                    title="Worker Auto-Assigned 📋", body=f"{assigned_worker.first_name} was auto-assigned to a new {analysis.nlp_category.value} issue."
                )
                background_tasks.add_task(
                    send_professional_alert_email, to_email=manager.email, alert_type="TEAM TASK ASSIGNED",
                    complaint_id=new_complaint.id, category=analysis.nlp_category.value, location=location, description=description
                )

    return {
        "complaint_id": new_complaint.id,
        "classification": analysis.nlp_category,
        "priority": analysis.priority_level,
        "priority_score": analysis.priority_score,
        "assigned_to": assigned_worker.id if assigned_worker else None,
        "estimated_resolution_time": new_complaint.estimated_resolution_time,
        "status": new_complaint.status,
        "message": "Complaint processing"
    }


@router.put("/{complaint_id}/status", status_code=status.HTTP_200_OK)
async def update_status(
    new_status: ComplaintStatus, 
    user: user_dependency, 
    db: db_dependency, 
    background_tasks: BackgroundTasks, 
    complaint_id: int = Path(gt=0)
):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    stmt = select(Complaint).filter(Complaint.id == complaint_id)
    result = await db.execute(stmt)
    complaint = result.scalar_one_or_none()
    
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if user.get("role") != UserRole.ADMIN.value and user.get("department") != complaint.department_assigned.value:
        raise HTTPException(status_code=403, detail="Unauthorized for this department.")

    if new_status == ComplaintStatus.CLOSED and user.get("role") != UserRole.MANAGER.value:
        raise HTTPException(status_code=403, detail="Only Department Managers can officially close a ticket.")
        
    if new_status == ComplaintStatus.REJECTED and user.get("role") != UserRole.MANAGER.value:
        raise HTTPException(status_code=403, detail="Only Department Managers can reject a resolved ticket.")
        
    if complaint.status == ComplaintStatus.CLOSED and user.get("role") != UserRole.MANAGER.value:
         raise HTTPException(status_code=403, detail="Ticket is closed. Only a Manager can reopen it.")

    # Check if we are freshly closing this ticket
    is_newly_closed = (new_status == ComplaintStatus.CLOSED and complaint.status != ComplaintStatus.CLOSED)

    history = ComplaintHistory(
        complaint_id=complaint.id,
        old_status=complaint.status,
        new_status=new_status,
        changed_by_user_id=user.get("id")
    )
    db.add(history)

    if new_status == ComplaintStatus.IN_PROGRESS and complaint.assigned_user_id is None:
        complaint.assigned_user_id = user.get("id")

    complaint.status = new_status
    if new_status == ComplaintStatus.CLOSED:
        complaint.resolved_at = datetime.now(timezone.utc)
    
    await db.commit()

    # --- Send the Citizen the Review Email ---
    if is_newly_closed and complaint.email:
        feedback_url = f"{settings.FRONTEND_URL}/feedback/{complaint.id}"
        
        background_tasks.add_task(
            send_resolution_email,
            to_email=complaint.email,
            citizen_name=complaint.name,
            complaint_id=complaint.id,
            category=complaint.department_assigned.value,
            location=complaint.location,
            original_image=complaint.image_url,         # Pass the original photo
            resolved_image=complaint.resolved_image_url, # Pass the resolved photo
            feedback_link=feedback_url
        )

    return {"message": f"Complaint status updated to {new_status.value}"}


@router.post("/trigger-escalations", status_code=status.HTTP_200_OK)
async def check_and_escalate(db: db_dependency, background_tasks: BackgroundTasks):
    now = datetime.now(timezone.utc)
    stmt = select(Complaint).filter(
        Complaint.status.in_([ComplaintStatus.PENDING, ComplaintStatus.IN_PROGRESS]),
        Complaint.estimated_resolution_time < now,
        Complaint.is_escalated == False
    )
    result = await db.execute(stmt)
    delayed_complaints = result.scalars().all()

    admin_email = settings.ADMIN_EMAIL
    escalated_count = 0

    for complaint in delayed_complaints:
        complaint.is_escalated = True
        complaint.escalation_reason = "SLA breached"
        escalated_count += 1
        
        if admin_email:
            background_tasks.add_task(
                send_professional_alert_email,
                to_email=admin_email,
                alert_type="ESCALATION (SLA BREACH)",
                complaint_id=complaint.id,
                category=complaint.department_assigned.value,
                location=complaint.location,
                description=complaint.description
            )

    await db.commit()
    return {"escalated_count": escalated_count}


@router.get("/", status_code=status.HTTP_200_OK)
async def get_complaints(user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    role = user.get("role")
    user_id = user.get("id")
    department = user.get("department")

    if role == UserRole.ADMIN.value:
        stmt = select(Complaint).order_by(desc(Complaint.created_at))
    elif role == UserRole.MANAGER.value:
        stmt = select(Complaint).filter(Complaint.department_assigned == department).order_by(desc(Complaint.created_at))
    elif role == UserRole.WORKER.value:
        stmt = select(Complaint).filter(Complaint.assigned_user_id == user_id).order_by(desc(Complaint.created_at))
    else:
        raise HTTPException(status_code=403, detail="Role not recognized.")
        
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{complaint_id}", status_code=status.HTTP_200_OK)
async def get_single_complaint(user: user_dependency, db: db_dependency, complaint_id: int = Path(gt=0)):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    stmt = select(Complaint).filter(Complaint.id == complaint_id)
    result = await db.execute(stmt)
    complaint = result.scalar_one_or_none()
    
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

    if user.get("role") != UserRole.MANAGER.value:
        raise HTTPException(status_code=403, detail="Only Managers can assign tickets.")

    stmt_complaint = select(Complaint).filter(Complaint.id == complaint_id)
    result_complaint = await db.execute(stmt_complaint)
    complaint = result_complaint.scalar_one_or_none()
    
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if user.get("department") != complaint.department_assigned.value:
        raise HTTPException(status_code=403, detail="You can only assign tickets for your department.")

    stmt_worker = select(User).filter(
        User.id == worker_id, 
        User.manager_id == user.get("id"),
        User.is_active == True
    )
    result_worker = await db.execute(stmt_worker)
    worker = result_worker.scalar_one_or_none()
    
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found or not assigned to your team.")

    # --- NEW: Get the Manager's details for their confirmation email ---
    stmt_manager = select(User).filter(User.id == user.get("id"))
    result_manager = await db.execute(stmt_manager)
    manager = result_manager.scalar_one_or_none()

    complaint.assigned_user_id = worker.id
    if complaint.status == ComplaintStatus.PENDING:
        complaint.status = ComplaintStatus.IN_PROGRESS

    await db.commit()

    # --- 1. Notify the Worker (Push + Email) ---
    background_tasks.add_task(
        send_push_notification_task,
        user_id=worker.id,
        title="New Task Assigned 📋",
        body=f"You have been assigned to a new {complaint.department_assigned.value} issue at {complaint.location}."
    )
    
    if worker.email:
        background_tasks.add_task(
            send_professional_alert_email,
            to_email=worker.email,
            alert_type="NEW TASK ASSIGNED",
            complaint_id=complaint.id,
            category=complaint.department_assigned.value,
            location=complaint.location,
            description=complaint.description
        )

    # --- 2. Notify the Manager (Push + Email Confirmation) ---
    if manager:
        background_tasks.add_task(
            send_push_notification_task,
            user_id=manager.id,
            title="Assignment Confirmed ✅",
            body=f"You successfully assigned Ticket #{complaint.id} to {worker.first_name}."
        )
        
        if manager.email:
            background_tasks.add_task(
                send_professional_alert_email,
                to_email=manager.email,
                alert_type="TEAM TASK ASSIGNED",
                complaint_id=complaint.id,
                category=complaint.department_assigned.value,
                location=complaint.location,
                description=f"Confirmation: You manually assigned this ticket to {worker.first_name} {worker.last_name}.\n\nOriginal Issue: {complaint.description}"
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

    stmt = select(Complaint).filter(Complaint.id == complaint_id)
    result = await db.execute(stmt)
    complaint = result.scalar_one_or_none()
    
    if not complaint or complaint.assigned_user_id != user.get("id"):
        raise HTTPException(status_code=403, detail="You are not assigned to this complaint.")

    temp_dir = "/tmp/static/temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = f"{temp_dir}/temp_{complaint_id}_{file.filename}"
    
    def save_file():
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    await asyncio.to_thread(save_file)

    complaint.status = ComplaintStatus.RESOLVED
    await db.commit()

    background_tasks.add_task(upload_to_cloudinary_task, complaint_id, temp_path)

    return {"message": "Task marked as resolved. Image is processing in background."}


@router.get("/track/{complaint_id}", status_code=status.HTTP_200_OK)
async def track_complaint(db: db_dependency, complaint_id: int = Path(gt=0)):
    stmt = select(Complaint).filter(Complaint.id == complaint_id)
    result = await db.execute(stmt)
    complaint = result.scalar_one_or_none()
    
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
        "resolved_image_url": complaint.resolved_image_url,
        "created_at": complaint.created_at
    }


@router.put("/{complaint_id}/review", status_code=status.HTTP_200_OK)
async def review_complaint(
    complaint_id: int,
    action: str, 
    user: user_dependency,
    db: db_dependency,
    background_tasks: BackgroundTasks 
):
    if user.get("role") not in [UserRole.MANAGER.value, UserRole.ADMIN.value]:
        raise HTTPException(status_code=403, detail="Only Managers or Admins can review tasks.")

    stmt = select(Complaint).filter(Complaint.id == complaint_id)
    result = await db.execute(stmt)
    complaint = result.scalar_one_or_none()
    
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if action == "approve":
        complaint.status = ComplaintStatus.CLOSED
        complaint.resolved_at = datetime.now(timezone.utc)
        message = "Ticket successfully closed."
        
        # --- Send the Citizen the Review Email ---
        if complaint.email:
            feedback_url = f"{settings.FRONTEND_URL}/feedback/{complaint.id}"
            background_tasks.add_task(
                send_resolution_email,
                to_email=complaint.email,
                citizen_name=complaint.name,
                complaint_id=complaint.id,
                category=complaint.department_assigned.value,
                location=complaint.location,
                original_image=complaint.image_url,         # Pass the original photo
                resolved_image=complaint.resolved_image_url, # Pass the resolved photo
                feedback_link=feedback_url
            )
            
    elif action == "revert":
        complaint.status = ComplaintStatus.IN_PROGRESS
        complaint.resolved_image_url = None 
        message = "Ticket reverted to In Progress for further work."
    else:
        raise HTTPException(status_code=400, detail="Invalid action.")

    await db.commit()
    return {"message": message, "new_status": complaint.status}


@router.post("/{complaint_id}/feedback", status_code=status.HTTP_201_CREATED)
async def submit_customer_review(
    db: db_dependency,
    request: FeedbackRequest,
    complaint_id: int = Path(gt=0)
):
    stmt = select(Complaint).filter(Complaint.id == complaint_id)
    result = await db.execute(stmt)
    complaint = result.scalar_one_or_none()
    
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found.")
        
    if complaint.status != ComplaintStatus.CLOSED:
        raise HTTPException(status_code=400, detail="You can only review tickets that have been closed.")
        
    stmt_feedback = select(Feedback).filter(Feedback.complaint_id == complaint_id)
    result_feedback = await db.execute(stmt_feedback)
    if result_feedback.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A review has already been submitted for this ticket.")

    new_feedback = Feedback(
        complaint_id=complaint.id,
        rating=request.rating,
        comments=request.comments
    )
    
    db.add(new_feedback)
    await db.commit()

    return {"message": "Thank you! Your review has been submitted successfully."}