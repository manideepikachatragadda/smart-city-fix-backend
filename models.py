import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    DateTime,
    Text,
    Enum,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from database import Base

# ===============================
# ENUMS (DB-safe & Postgres-ready)
# ===============================
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    WORKER = "worker"

class DepartmentRole(str, enum.Enum):
    WATER = "water"
    ELECTRICITY = "electricity"
    CLEANLINESS = "cleanliness"
    INFRASTRUCTURE = "infrastructure"
    OTHERS = "others"

class PriorityLevel(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class ComplaintStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"  # This now means "Worker finished, waiting for Manager"
    REJECTED = "rejected"
    CLOSED = "closed"      # NEW: This means "Manager verified and closed it"

# ===============================
# BASE MIXIN
# ===============================
class TimestampMixin:
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

# ===============================
# USERS
# ===============================
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # --- NEW: Split Role and Department ---
    role = Column(
        Enum(UserRole, name="user_role_enum", native_enum=True),
        default=UserRole.WORKER,
        nullable=False,
        index=True,
    )
    
    department = Column(
        Enum(DepartmentRole, name="department_role_enum", native_enum=True),
        nullable=True, # Admins might not have a specific department
        index=True,
    )

    manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # SQLAlchemy relationship to easily access user.manager or manager.workers
    manager = relationship("User", remote_side=[id], backref="workers")


    assigned_complaints = relationship(
        "Complaint",
        back_populates="assigned_user",
        cascade="all, delete",
    )

    reset_otp = Column(String(6), nullable=True)
    reset_otp_expiry = Column(DateTime(timezone=True), nullable=True)

# ===============================
# COMPLAINTS
# ===============================
class Complaint(Base, TimestampMixin):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True)

    # Reporter Info
    name = Column(String(150))
    phone_number = Column(String(20), nullable=False, index=True)
    email = Column(String, nullable=True)
    location = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    image_url = Column(String(500)) 
    resolved_image_url = Column(String, nullable=True)
    # AI Output
    nlp_category = Column(
        Enum(DepartmentRole, name="department_role_enum", native_enum=True),
        index=True,
    )
    priority_level = Column(
        Enum(PriorityLevel, name="priority_level_enum", native_enum=True),
        nullable=False,
        index=True,
    )
    priority_score = Column(Integer, nullable=False)
    status = Column(
        Enum(ComplaintStatus, name="complaint_status_enum", native_enum=True),
        default=ComplaintStatus.PENDING,
        nullable=False,
        index=True,
    )

    estimated_resolution_time = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))

    # Assignment
    assigned_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    assigned_user = relationship("User", back_populates="assigned_complaints")

    # Escalation
    department_assigned = Column(
        Enum(DepartmentRole, name="department_role_enum", native_enum=True),
        index=True,
    )
    is_escalated = Column(Boolean, default=False, nullable=False, index=True)
    escalation_reason = Column(String(255))

    # Relationships
    feedback = relationship(
        "Feedback",
        back_populates="complaint",
        uselist=False,
        cascade="all, delete-orphan",
    )
    history = relationship(
        "ComplaintHistory",
        back_populates="complaint",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_status_priority", "status", "priority_level"),
        Index("idx_department_status", "department_assigned", "status"),
    )

# ===============================
# FEEDBACK
# ===============================
class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True)
    complaint_id = Column(
        Integer,
        ForeignKey("complaints.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    rating = Column(Integer, nullable=False)
    comments = Column(Text)
    complaint = relationship("Complaint", back_populates="feedback")

# ===============================
# STATUS HISTORY (Audit Trail)
# ===============================
class ComplaintHistory(Base):
    __tablename__ = "complaint_history"

    id = Column(Integer, primary_key=True)
    complaint_id = Column(
        Integer,
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_status = Column(
        Enum(ComplaintStatus, name="complaint_status_enum", native_enum=True),
        nullable=False,
    )
    new_status = Column(
        Enum(ComplaintStatus, name="complaint_status_enum", native_enum=True),
        nullable=False,
    )
    changed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    changed_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    complaint = relationship("Complaint", back_populates="history")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    endpoint = Column(String, unique=True, index=True)
    p256dh = Column(String)
    auth = Column(String)