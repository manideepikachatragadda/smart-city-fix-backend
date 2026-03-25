import random
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from starlette import status
from jose import jwt, JWTError

# --- ASYNC SQLALCHEMY IMPORTS ---
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from models import User, DepartmentRole, UserRole
from database import get_db
from config import settings
from utils.notifications import send_push_notification_task
from utils.email_service import send_otp_email

router = APIRouter(prefix="/auth", tags=["auth"])

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_bearer = OAuth2PasswordBearer(tokenUrl="auth/token")
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

# --- PYDANTIC MODELS ---

class CreateUserRequest(BaseModel):
    username: str
    email: EmailStr
    first_name: str
    last_name: str
    password: str
    role: UserRole 
    department: Optional[DepartmentRole] = None
    location: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class VerifyOTPRequest(BaseModel):
    email: str
    otp: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    new_password: str

# --- DEPENDENCIES ---

# Updated to use AsyncSession
db_dependency = Annotated[AsyncSession, Depends(get_db)]

# --- HELPER FUNCTIONS ---

# This must be async now because it queries the DB
async def authenticate_user(username: str, password: str, db: AsyncSession):
    stmt = select(User).filter(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or not bcrypt_context.verify(password, user.hashed_password):
        return False
    return user

def create_access_token(username: str, user_id: int, role: str, department: Optional[str], expires_delta: timedelta):
    encode = {'sub': username, 'id': user_id, 'role': role, 'department': department}
    expires = datetime.now(timezone.utc) + expires_delta
    encode.update({'exp': expires})
    return jwt.encode(encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: Annotated[str, Depends(oauth2_bearer)]):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: int = payload.get("id")
        user_role: str = payload.get("role")
        department: str = payload.get("department")
        if username is None or user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return {'username': username, 'id': user_id, 'role': user_role, 'department': department}
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# --- ENDPOINTS ---

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def create_user(db: db_dependency, request: CreateUserRequest):
    if request.role != UserRole.ADMIN and request.department is None:
        raise HTTPException(
            status_code=400, 
            detail="Managers and Workers must be assigned to a specific department."
        )

    # 1. Check if the email already exists
    stmt_email = select(User).filter(User.email == request.email)
    result_email = await db.execute(stmt_email)
    if result_email.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email is already registered.")

    # 2. Check if the username already exists
    stmt_username = select(User).filter(User.username == request.username)
    result_username = await db.execute(stmt_username)
    if result_username.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username is already taken.")

    # 3. Create the user
    new_user = User(
        email=request.email,
        username=request.username,
        first_name=request.first_name,
        last_name=request.last_name,
        hashed_password=bcrypt_context.hash(request.password),
        role=request.role, 
        department=request.department,
        location=request.location,
        is_active=True
    )
    db.add(new_user)
    await db.commit()

@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency):
    # Await the new async authenticate_user function
    user = await authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    dept_val = user.department.value if user.department else None
    token = create_access_token(user.username, user.id, user.role.value, dept_val, timedelta(hours=12))
    return {'access_token': token, 'token_type': 'bearer'}


@router.post("/verify-otp", status_code=status.HTTP_200_OK)
async def verify_otp(request: VerifyOTPRequest, db: db_dependency):
    stmt = select(User).filter(User.email == request.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or user.reset_otp != request.otp:
        raise HTTPException(status_code=400, detail="Invalid or incorrect OTP.")
        
    expiry = user.reset_otp_expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if expiry < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This OTP has expired. Please request a new one.")

    return {"message": "OTP verified successfully. Proceed to reset password."}


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def request_password_reset(
    request: ForgotPasswordRequest,
    db: db_dependency,
    background_tasks: BackgroundTasks
):
    stmt = select(User).filter(User.email == request.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=400, detail="No account found with that email address.")

    otp_code = str(random.randint(100000, 999999))
    user.reset_otp = otp_code
    user.reset_otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    
    await db.commit()

    background_tasks.add_task(
        send_push_notification_task,
        user_id=user.id,
        title="Password Reset Code 🔐",
        body=f"Your OTP is {otp_code}. It will expire in 5 minutes."
    )
    
    background_tasks.add_task(
        send_otp_email,
        to_email=user.email,
        user_name=user.first_name,
        otp_code=otp_code
    )

    return {"message": "OTP has been sent to your email and device."}

@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(request: ResetPasswordRequest, db: db_dependency):
    stmt = select(User).filter(User.email == request.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or user.reset_otp != request.otp:
        raise HTTPException(status_code=400, detail="Invalid or incorrect OTP.")
        
    expiry = user.reset_otp_expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if expiry < datetime.now(timezone.utc):
        user.reset_otp = None
        user.reset_otp_expiry = None
        await db.commit()
        raise HTTPException(status_code=400, detail="This OTP has expired. Please request a new one.")

    user.hashed_password = bcrypt_context.hash(request.new_password)
    user.reset_otp = None
    user.reset_otp_expiry = None
    
    await db.commit()

    return {"message": "Password successfully reset. You can now log in."}