from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Annotated, List
from starlette import status
from pydantic import BaseModel, Field
from passlib.context import CryptContext

from models import User
from database import get_db
from .auth import get_current_user

from pydantic import BaseModel, EmailStr
from typing import Optional
from models import UserRole, DepartmentRole

from sqlalchemy import or_ 




router = APIRouter(prefix="/user", tags=["user"])

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]
bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserVerification(BaseModel):
    password: str
    new_password: str = Field(min_length=6)

class CreateStaffRequest(BaseModel):
    username: str
    email: EmailStr
    first_name: str
    last_name: str
    password: str
    role: UserRole
    department: Optional[DepartmentRole] = None

class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    first_name: str
    last_name: str
    role: UserRole
    department: DepartmentRole | None
    is_active: bool
    manager_id: Optional[int] = None

    class Config:
        from_attributes = True

@router.get("/me", status_code=status.HTTP_200_OK)
async def get_user(user: user_dependency, db: db_dependency):
    if user is None:
        raise HTTPException(status_code=401, detail='Authentication Failed')
    return db.query(User).filter(User.id == user.get('id')).first()

@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(user: user_dependency, db: db_dependency, req: UserVerification):
    if user is None:
        raise HTTPException(status_code=401, detail='Authentication Failed')
    
    user_model = db.query(User).filter(User.id == user.get('id')).first()
    if not bcrypt_context.verify(req.password, user_model.hashed_password):
        raise HTTPException(status_code=401, detail='Incorrect current password')
        
    user_model.hashed_password = bcrypt_context.hash(req.new_password)
    db.add(user_model)
    db.commit()


@router.post("/create-staff", status_code=status.HTTP_201_CREATED)
async def create_staff(
    request: CreateStaffRequest,
    user: user_dependency, 
    db: db_dependency
):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    current_role = user.get("role")
    current_dept = user.get("department")

    # 1. WORKERS cannot create accounts
    if current_role == UserRole.WORKER.value:
        raise HTTPException(status_code=403, detail="Workers do not have permission to create accounts.")

    # 2. MANAGER Rules
    if current_role == UserRole.MANAGER.value:
        if request.role != UserRole.WORKER:
            raise HTTPException(status_code=403, detail="Managers can only create Worker accounts.")
        
        # Force the new worker's department to match the manager's department
        if request.department is None or request.department.value != current_dept:
            raise HTTPException(
                status_code=403, 
                detail=f"As a manager, you can only add workers to the '{current_dept}' department."
            )

    # 3. ADMIN Rules (Admins can create anyone, but we enforce department logic)
    if current_role == UserRole.ADMIN.value:
        if request.role != UserRole.ADMIN and request.department is None:
             raise HTTPException(status_code=400, detail="Managers and Workers must have an assigned department.")

    # --- Proceed with Account Creation ---
    
    # Check for duplicates
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status_code=400, detail="Email is already registered.")
    if db.query(User).filter(User.username == request.username).first():
        raise HTTPException(status_code=400, detail="Username is already taken.")

    assigned_manager_id = user.get("id")

    new_user = User(
        email=request.email,
        username=request.username,
        first_name=request.first_name,
        last_name=request.last_name,
        hashed_password=bcrypt_context.hash(request.password),
        role=request.role, 
        department=request.department,
        manager_id=assigned_manager_id,
        is_active=True
    )
    db.add(new_user)
    db.commit()

    return {"message": f"Successfully created {request.role.value} account for {request.username}."}

@router.get("/my-team", response_model=List[UserResponse], status_code=status.HTTP_200_OK)
async def get_my_team(user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    role = user.get("role")

    # 1. Admin gets everyone
    if role == UserRole.ADMIN.value:
        team = db.query(User).filter(User.is_active == True).all()
        return team

    # 2. Manager gets their direct reports
    elif role == UserRole.MANAGER.value:
        team = db.query(User).filter(
            User.manager_id == user.get("id"),
            User.is_active == True
        ).all()
        return team

    # 3. Workers get blocked
    else:
        raise HTTPException(
            status_code=403, 
            detail="Workers do not have permission to view teams."
        )


@router.get("/hierarchy", response_model=List[UserResponse], status_code=status.HTTP_200_OK)
async def get_staff_hierarchy(user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    role = user.get("role")

    # 1. ADMIN View: Return absolutely everyone to build the massive city graph
    if role == UserRole.ADMIN.value:
        hierarchy = db.query(User).all()
        return hierarchy

    # 2. MANAGER View: Return the manager + their direct workers
    elif role == UserRole.MANAGER.value:
        my_id = user.get("id")
        # Use or_ to get the manager themselves AND anyone who reports to them
        hierarchy = db.query(User).filter(
            or_(User.id == my_id, User.manager_id == my_id)
        ).all()
        return hierarchy

    # 3. WORKER View: Deny access
    else:
        raise HTTPException(
            status_code=403, 
            detail="Workers do not have permission to view the organizational hierarchy."
        )


@router.delete("/{target_user_id}", status_code=status.HTTP_200_OK)
async def remove_staff(target_user_id: int, user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    # 1. Find the user to delete
    user_to_delete = db.query(User).filter(User.id == target_user_id).first()
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found.")

    current_role = user.get("role")
    current_id = user.get("id")

    # 2. Hierarchy Security Checks
    if current_role == UserRole.WORKER.value:
        raise HTTPException(status_code=403, detail="Workers do not have permission to delete accounts.")

    if current_role == UserRole.MANAGER.value:
        # Managers can ONLY delete workers who directly report to them
        if user_to_delete.manager_id != current_id:
            raise HTTPException(
                status_code=403, 
                detail="You can only remove workers that are assigned to your specific team."
            )

    # 3. Prevent deleting yourself
    if user_to_delete.id == current_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    # 4. Perform a Soft Delete (Deactivation)
    user_to_delete.is_active = False
    
    # Optional: If you want to unassign them from their manager so they disappear from the React Flow graph
    user_to_delete.manager_id = None 
    
    db.commit()

    return {"message": f"User {user_to_delete.username} has been successfully deactivated and removed from the active roster."}