from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated, List, Optional
from starlette import status
from pydantic import BaseModel, Field, EmailStr
from passlib.context import CryptContext

# --- ASYNC SQLALCHEMY IMPORTS ---
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_

from models import User, UserRole, DepartmentRole
from database import get_db
from .auth import get_current_user

router = APIRouter(prefix="/user", tags=["user"])

# Updated to use AsyncSession
db_dependency = Annotated[AsyncSession, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]
bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- PYDANTIC MODELS ---

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

# --- ENDPOINTS ---

@router.get("/me", status_code=status.HTTP_200_OK)
async def get_user(user: user_dependency, db: db_dependency):
    if user is None:
        raise HTTPException(status_code=401, detail='Authentication Failed')
        
    stmt = select(User).filter(User.id == user.get('id'))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(user: user_dependency, db: db_dependency, req: UserVerification):
    if user is None:
        raise HTTPException(status_code=401, detail='Authentication Failed')
    
    stmt = select(User).filter(User.id == user.get('id'))
    result = await db.execute(stmt)
    user_model = result.scalar_one_or_none()
    
    if not bcrypt_context.verify(req.password, user_model.hashed_password):
        raise HTTPException(status_code=401, detail='Incorrect current password')
        
    user_model.hashed_password = bcrypt_context.hash(req.new_password)
    db.add(user_model)
    await db.commit()


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

    if current_role == UserRole.WORKER.value:
        raise HTTPException(status_code=403, detail="Workers do not have permission to create accounts.")

    if current_role == UserRole.MANAGER.value:
        if request.role != UserRole.WORKER:
            raise HTTPException(status_code=403, detail="Managers can only create Worker accounts.")
        
        if request.department is None or request.department.value != current_dept:
            raise HTTPException(
                status_code=403, 
                detail=f"As a manager, you can only add workers to the '{current_dept}' department."
            )

    if current_role == UserRole.ADMIN.value:
        if request.role != UserRole.ADMIN and request.department is None:
             raise HTTPException(status_code=400, detail="Managers and Workers must have an assigned department.")

    # Check for duplicates asynchronously
    stmt_email = select(User).filter(User.email == request.email)
    result_email = await db.execute(stmt_email)
    if result_email.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email is already registered.")
        
    stmt_username = select(User).filter(User.username == request.username)
    result_username = await db.execute(stmt_username)
    if result_username.scalar_one_or_none():
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
    await db.commit()

    return {"message": f"Successfully created {request.role.value} account for {request.username}."}


@router.get("/my-team", response_model=List[UserResponse], status_code=status.HTTP_200_OK)
async def get_my_team(user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    role = user.get("role")

    if role == UserRole.ADMIN.value:
        stmt = select(User).filter(User.is_active == True)
    elif role == UserRole.MANAGER.value:
        stmt = select(User).filter(User.manager_id == user.get("id"), User.is_active == True)
    else:
        raise HTTPException(status_code=403, detail="Workers do not have permission to view teams.")

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/hierarchy", response_model=List[UserResponse], status_code=status.HTTP_200_OK)
async def get_staff_hierarchy(user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    role = user.get("role")

    if role == UserRole.ADMIN.value:
        stmt = select(User)
    elif role == UserRole.MANAGER.value:
        my_id = user.get("id")
        stmt = select(User).filter(or_(User.id == my_id, User.manager_id == my_id))
    else:
        raise HTTPException(status_code=403, detail="Workers do not have permission to view the organizational hierarchy.")

    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/{target_user_id}", status_code=status.HTTP_200_OK)
async def remove_staff(target_user_id: int, user: user_dependency, db: db_dependency):
    if not user:
        raise HTTPException(status_code=401, detail='Authentication Failed')

    stmt = select(User).filter(User.id == target_user_id)
    result = await db.execute(stmt)
    user_to_delete = result.scalar_one_or_none()
    
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found.")

    current_role = user.get("role")
    current_id = user.get("id")

    if current_role == UserRole.WORKER.value:
        raise HTTPException(status_code=403, detail="Workers do not have permission to delete accounts.")

    if current_role == UserRole.MANAGER.value:
        if user_to_delete.manager_id != current_id:
            raise HTTPException(
                status_code=403, 
                detail="You can only remove workers that are assigned to your specific team."
            )

    if user_to_delete.id == current_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    user_to_delete.is_active = False
    user_to_delete.manager_id = None 
    
    await db.commit()

    return {"message": f"User {user_to_delete.username} has been successfully deactivated and removed from the active roster."}