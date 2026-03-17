from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from starlette import status

# --- ASYNC SQLALCHEMY IMPORTS ---
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from models import Complaint, ComplaintStatus, DepartmentRole, UserRole
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Updated to AsyncSession
db_dependency = Annotated[AsyncSession, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/metrics", status_code=status.HTTP_200_OK)
async def get_dashboard_metrics(user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    # 1. Base conditions (Filters applied to EVERY query)
    conditions = []
    
    # Apply department filter if the user is NOT an admin
    if user.get("role") != UserRole.ADMIN.value:
        user_dept = user.get("department")
        if not user_dept:
            raise HTTPException(status_code=403, detail="User has no assigned department.")
        
        conditions.append(Complaint.department_assigned == user_dept)

    # Helper function to easily run async count queries
    async def get_count(extra_conditions=None):
        stmt = select(func.count(Complaint.id))
        if conditions:
            stmt = stmt.filter(*conditions)
        if extra_conditions:
            stmt = stmt.filter(*extra_conditions)
            
        result = await db.execute(stmt)
        return result.scalar() or 0

    # 3. Calculate metrics using the async helper
    total = await get_count()
    pending = await get_count([Complaint.status == ComplaintStatus.PENDING])
    escalated = await get_count([Complaint.is_escalated == True])
    in_progress = await get_count([Complaint.status == ComplaintStatus.IN_PROGRESS])
    resolved = await get_count([Complaint.status == ComplaintStatus.RESOLVED])
    rejected = await get_count([Complaint.status == ComplaintStatus.REJECTED])
    closed = await get_count([Complaint.status == ComplaintStatus.CLOSED])

    # 4. Group by Category
    stmt_cat = select(Complaint.department_assigned, func.count(Complaint.id))
    if conditions:
        stmt_cat = stmt_cat.filter(*conditions)
    stmt_cat = stmt_cat.group_by(Complaint.department_assigned)
    
    res_cat = await db.execute(stmt_cat)
    categories = res_cat.all()

    # 5. Group by Priority
    stmt_pri = select(Complaint.priority_level, func.count(Complaint.id))
    if conditions:
        stmt_pri = stmt_pri.filter(*conditions)
    stmt_pri = stmt_pri.group_by(Complaint.priority_level)
    
    res_pri = await db.execute(stmt_pri)
    priorities = res_pri.all()

    return {
        "overview": {
            "total_complaints": total,
            "pending_complaints": pending,
            "escalated_complaints": escalated,
            "in_progress_complaints": in_progress,
            "resolved_complaints": resolved,
            "rejected_complaints": rejected,
            "closed_complaints": closed
        },
        "category_distribution": {cat.value: count for cat, count in categories if cat},
        "priority_distribution": {pri.value: count for pri, count in priorities if pri}
    }