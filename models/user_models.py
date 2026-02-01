from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import Optional
from datetime import datetime

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    role: str  # teacher or admin
    auth_provider: Optional[str] = None  # email, google, microsoft
    picture: Optional[str] = None
    display_name: Optional[str] = None
    school_name: Optional[str] = None
    department: Optional[str] = None
    tenant_id: Optional[str] = None  # Azure AD tenant ID for Microsoft auth
    created_at: datetime

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str
    school_name: Optional[str] = None
    department: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class PasswordReset(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

class UpdateProfile(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    school_name: Optional[str] = None
    department: Optional[str] = None
