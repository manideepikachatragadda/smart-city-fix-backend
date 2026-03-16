from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from typing import Annotated
from starlette import status

from models import Complaint, DepartmentRole, UserRole
from database import get_db
from .auth import get_current_user

router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/complaints", status_code=status.HTTP_200_OK)
async def read_all_complaints(user: user_dependency, db: db_dependency):
    """Admin-only endpoint to view ALL complaints across ALL departments."""
    if user is None or user.get('role') != UserRole.ADMIN.value:
        raise HTTPException(status_code=401, detail='Authentication Failed: Admin access required.')
    
    return db.query(Complaint).all()

@router.delete("/complaints/{complaint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_complaint(user: user_dependency, db: db_dependency, complaint_id: int = Path(gt=0)):
    """Admin-only endpoint to completely remove a complaint from the database."""
    if user is None or user.get('role') != UserRole.ADMIN.value:
        raise HTTPException(status_code=401, detail='Authentication Failed: Admin access required.')
    
    complaint_model = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if complaint_model is None:
        raise HTTPException(status_code=404, detail='Complaint not found.')
    
    # Because we set up cascade="all, delete" in models.py, 
    # deleting this will also clean up associated Feedback and ComplaintHistory automatically!
    db.delete(complaint_model)
    db.commit()