from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Annotated
from starlette import status

from models import Complaint, ComplaintStatus, DepartmentRole, UserRole
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/metrics", status_code=status.HTTP_200_OK)
async def get_dashboard_metrics(user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    # 1. Initialize the base query
    base_query = db.query(Complaint)

    # 2. Apply department filter if the user is NOT an admin
    if user.get("role") != UserRole.ADMIN.value:
        user_dept = user.get("department")
        if not user_dept:
            raise HTTPException(status_code=403, detail="User has no assigned department.")
        
        base_query = base_query.filter(Complaint.department_assigned == user_dept)

    # 3. Calculate metrics using the dynamic base_query
    total = base_query.count()
    pending = base_query.filter(Complaint.status == ComplaintStatus.PENDING).count()
    escalated = base_query.filter(Complaint.is_escalated == True).count()
    in_progress = base_query.filter(Complaint.status == ComplaintStatus.IN_PROGRESS).count()
    resolved = base_query.filter(Complaint.status == ComplaintStatus.RESOLVED).count()
    rejected = base_query.filter(Complaint.status == ComplaintStatus.REJECTED).count()

    categories = base_query.with_entities(
        Complaint.department_assigned, func.count(Complaint.id)
    ).group_by(Complaint.department_assigned).all()

    priorities = base_query.with_entities(
        Complaint.priority_level, func.count(Complaint.id)
    ).group_by(Complaint.priority_level).all()

    return {
        "overview": {
            "total_complaints": total,
            "pending_complaints": pending,
            "escalated_complaints": escalated,
            "in_progress_complaints": in_progress,
            "resolved_complaints": resolved,
            "rejected_complaints": rejected
        },
        "category_distribution": {cat.value: count for cat, count in categories if cat},
        "priority_distribution": {pri.value: count for pri, count in priorities if pri}
    }