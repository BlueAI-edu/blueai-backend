"""Models for Classes and Students management"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone
import uuid


# ==================== CLASSES MODELS ====================

class ClassCreate(BaseModel):
    class_name: str
    subject: Optional[str] = None
    year_group: Optional[str] = None


class ClassUpdate(BaseModel):
    class_name: Optional[str] = None
    subject: Optional[str] = None
    year_group: Optional[str] = None


class ClassModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    teacher_owner_id: str
    class_name: str
    subject: Optional[str] = None
    year_group: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==================== STUDENTS MODELS ====================

class StudentCreate(BaseModel):
    class_id: str
    first_name: str
    last_name: str
    preferred_name: Optional[str] = None
    student_code: Optional[str] = None
    email: Optional[str] = None  # For email reports
    dob: Optional[str] = None  # ISO date string
    sen_flag: Optional[bool] = False
    pupil_premium_flag: Optional[bool] = False
    eal_flag: Optional[bool] = False
    notes: Optional[str] = None


class StudentUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    preferred_name: Optional[str] = None
    student_code: Optional[str] = None
    email: Optional[str] = None  # For email reports
    dob: Optional[str] = None
    sen_flag: Optional[bool] = None
    pupil_premium_flag: Optional[bool] = None
    eal_flag: Optional[bool] = None
    notes: Optional[str] = None
    class_id: Optional[str] = None  # Allow moving student to different class


class StudentModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    teacher_owner_id: str
    class_id: str
    first_name: str
    last_name: str
    preferred_name: Optional[str] = None
    student_code: Optional[str] = None
    email: Optional[str] = None  # For email reports
    dob: Optional[str] = None
    sen_flag: bool = False
    pupil_premium_flag: bool = False
    eal_flag: bool = False
    notes: Optional[str] = None
    archived: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==================== CSV IMPORT MODELS ====================

class CSVImportPreview(BaseModel):
    csv_content: str


class CSVImportConfirm(BaseModel):
    rows: List[dict]
