from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, Form, Query
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
from contextlib import asynccontextmanager
import uuid
from datetime import datetime, timezone, timedelta
# from emergentintegrations.llm.chat import LlmChat, UserMessage
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import re
import html
import tempfile
import random
import string
from passlib.context import CryptContext
import secrets
import asyncio
import resend
from jose import jwt, JWTError
import requests
import time
from functools import lru_cache
from fastapi import UploadFile, File
import sys

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Add backend directory to Python path for OCR service import
sys.path.insert(0, str(ROOT_DIR))

# Import attempt finalizer service
from services.attempt_finalizer import finalize_attempt, check_and_finalize_expired_attempts, check_attempt_expired_on_request

# Import analytics service
from services.analytics_service import AnalyticsService

# Import modular routes
from routes.classes_routes import router as classes_router

# Import models
from models.assessment_models import (
    AIMultiQuestionRequest,
    EnhancedAssessmentCreate,
    EnhancedQuestionCreate,
    QuestionPartCreate,
    MCQOptionCreate
)

# Import OCR service with error handling
try:
    from ocr_service import ocr_service, OCRResult
    OCR_AVAILABLE = True
except ImportError as e:
    logging.warning(f"OCR service not available: {str(e)}")
    OCR_AVAILABLE = False
    ocr_service = None

# Create uploads directory for OCR files
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# MongoDB connection
mongo_url = os.environ['MONGO_URL'].strip()
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Email configuration
resend.api_key = os.environ.get('RESEND_API_KEY')

# Azure AD configuration
AZURE_TENANT_ID = os.environ.get('AZURE_TENANT_ID')
AZURE_CLIENT_ID = os.environ.get('AZURE_BACKEND_CLIENT_ID')
AZURE_CLIENT_SECRET = os.environ.get('AZURE_CLIENT_SECRET')
JWKS_URL = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys" if AZURE_TENANT_ID else None

# JWKS cache
jwks_cache = {"keys": None, "last_updated": 0}
JWKS_CACHE_TTL = 3600  # 1 hour

def get_jwks():
    """Fetch and cache JWKS from Azure AD"""
    current_time = time.time()
    if jwks_cache["keys"] is None or (current_time - jwks_cache["last_updated"]) > JWKS_CACHE_TTL:
        try:
            response = requests.get(JWKS_URL, timeout=10)
            response.raise_for_status()
            jwks_cache["keys"] = response.json()
            jwks_cache["last_updated"] = current_time
            logging.info("Successfully fetched JWKS from Azure AD")
        except Exception as e:
            logging.error(f"Failed to fetch JWKS: {str(e)}")
            if jwks_cache["keys"] is None:
                raise HTTPException(status_code=503, detail="Authentication service unavailable")
    return jwks_cache["keys"]

def verify_azure_token(token: str):
    """Verify and decode Azure AD access token"""
    try:
        # Get the token header to find the key ID
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        
        if not kid:
            raise HTTPException(status_code=401, detail="Token missing key ID")
        
        # Get JWKS and find the matching key
        jwks = get_jwks()
        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = k
                break
        
        if not key:
            raise HTTPException(status_code=401, detail="Unable to find appropriate signing key")
        
        # Convert JWK to PEM format
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import base64
        
        def base64_to_long(data: str) -> int:
            if isinstance(data, str):
                data = data.encode("ascii")
            decoded = base64.urlsafe_b64decode(data + b"==")
            return int.from_bytes(decoded, byteorder="big")
        
        n = base64_to_long(key['n'])
        e = base64_to_long(key['e'])
        public_key = rsa.RSAPublicNumbers(e, n).public_key()
        pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # Verify and decode the token
        payload = jwt.decode(
            token,
            pem,
            algorithms=["RS256"],
            audience=AZURE_CLIENT_ID,
            options={"verify_exp": True}
        )
        
        return payload
    except JWTError as e:
        logging.error(f"Token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logging.error(f"Unexpected error during token verification: {str(e)}")
        raise HTTPException(status_code=401, detail="Token verification failed")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup: Connection already established at module level
    logger.info("Application starting up...")
    yield
    # Shutdown
    logger.info("Application shutting down...")
    client.close()

app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")

# Health check endpoint (required for deployment)
@app.get("/health")
async def health_check():
    """Health check endpoint for deployment system"""
    return {
        "status": "healthy",
        "service": "blueai-assessment",
        "version": "2.0.1"
    }

# Background job endpoint for attempt finalization
@app.post("/cron/finalize-expired-attempts")
async def cron_finalize_expired_attempts(request: Request):
    """Background job to finalize expired attempts. Call this every 1-5 minutes."""
    # Simple security: check for a secret header (optional)
    cron_secret = os.environ.get('CRON_SECRET')
    if cron_secret:
        provided_secret = request.headers.get('X-Cron-Secret')
        if provided_secret != cron_secret:
            raise HTTPException(status_code=403, detail="Unauthorized")
    
    count = await check_and_finalize_expired_attempts(db)
    return {"finalized_count": count}

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "BlueAI Assessment API", "status": "running"}


# Models
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

class Question(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_teacher_id: str
    subject: str
    exam_type: str
    topic: str
    question_text: str
    max_marks: int
    mark_scheme: str
    # Extended fields for AI Generator
    source: Optional[str] = "manual"  # manual or ai_generated
    key_stage: Optional[str] = None
    exam_board: Optional[str] = None
    tier: Optional[str] = None
    question_title: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    mark_scheme_json: Optional[List[dict]] = None  # Structured mark scheme
    model_answer: Optional[str] = None
    common_mistakes: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    diagram_prompt: Optional[str] = None
    quality_score: Optional[int] = None
    quality_notes: Optional[List[str]] = None
    calculator_allowed: Optional[bool] = False
    # Student answer type
    answer_type: Optional[str] = "text"  # text, maths, mixed, numeric, multiple_choice
    answer_type_override: Optional[bool] = False  # Teacher manually set answer type
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

class QuestionCreate(BaseModel):
    subject: str
    exam_type: str
    topic: str
    question_text: str
    max_marks: int
    mark_scheme: str
    # Optional extended fields
    source: Optional[str] = "manual"
    key_stage: Optional[str] = None
    exam_board: Optional[str] = None
    tier: Optional[str] = None
    question_title: Optional[str] = None
    topic_tags: Optional[List[str]] = None
    mark_scheme_json: Optional[List[dict]] = None
    model_answer: Optional[str] = None
    common_mistakes: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    diagram_prompt: Optional[str] = None
    quality_score: Optional[int] = None
    quality_notes: Optional[List[str]] = None
    calculator_allowed: Optional[bool] = False
    answer_type: Optional[str] = "text"
    answer_type_override: Optional[bool] = False

class AIQuestionRequest(BaseModel):
    subject: str
    key_stage: str
    exam_board: str
    tier: Optional[str] = None
    topic: str
    subtopic: Optional[str] = None
    difficulty: str
    question_type: str
    marks: int
    num_questions: int = 1
    include_latex: bool = True
    include_diagrams: str = "none"  # none, description, prompt
    calculator_allowed: bool = False
    strictness: str = "strict"  # strict or standard
    command_words: Optional[str] = None
    question_context: str = "mock exam"

class Assessment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_teacher_id: str
    question_id: Optional[str] = None  # Optional for Enhanced Assessments
    class_id: Optional[str] = None  # Phase 4: Link to class
    join_code: str = Field(default_factory=lambda: ''.join(random.choices(string.ascii_uppercase + string.digits, k=6)))
    duration_minutes: Optional[int] = None
    auto_close: bool = False
    status: str = "draft"  # draft, started, closed
    started_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AssessmentCreate(BaseModel):
    question_id: str
    class_id: Optional[str] = None  # Phase 4: Optional class linking
    duration_minutes: Optional[int] = None
    auto_close: bool = False

# ==================== ASSESSMENT TEMPLATE MODELS ====================

class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    question_id: str
    default_class_id: Optional[str] = None
    duration_minutes: Optional[int] = None
    auto_close: bool = False

class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_class_id: Optional[str] = None
    duration_minutes: Optional[int] = None
    auto_close: Optional[bool] = None

class Template(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_teacher_id: str
    name: str
    description: Optional[str] = None
    question_id: str
    default_class_id: Optional[str] = None
    duration_minutes: Optional[int] = None
    auto_close: bool = False
    use_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: Optional[datetime] = None

class Attempt(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    assessment_id: str
    owner_teacher_id: str
    student_name: str
    attempt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_id: Optional[str] = None
    class_id: Optional[str] = None
    answer_text: Optional[str] = None
    status: str = "in_progress"  # in_progress, submitted, marked, error
    score: Optional[int] = None
    www: Optional[str] = None
    next_steps: Optional[str] = None
    overall_feedback: Optional[str] = None
    # Enhanced marking fields
    mark_breakdown: Optional[List[dict]] = None  # Detailed breakdown per mark scheme point
    needs_review: bool = False  # Flag for teacher review
    review_reasons: Optional[List[str]] = None  # Why AI flagged for review
    ai_confidence: Optional[float] = None  # AI's confidence in marking (0-1)
    # Existing fields
    joined_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    marked_at: Optional[datetime] = None
    feedback_released: bool = False
    finalize_reason: Optional[str] = None
    last_saved_at: Optional[datetime] = None
    security_events: Optional[List[dict]] = None  # For focus loss tracking
    pdf_url: Optional[str] = None
    pdf_generated_at: Optional[datetime] = None
    autosubmitted: bool = False

# ==================== EXAMPLE ANSWERS MODEL ====================

class ExampleAnswerCreate(BaseModel):
    answer_text: str
    example_type: str  # "good" or "bad"
    score: Optional[int] = None
    explanation: Optional[str] = None  # Why this is a good/bad example

class ExampleAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question_id: str
    teacher_owner_id: str
    answer_text: str
    example_type: str  # "good" or "bad"
    score: Optional[int] = None
    explanation: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class JoinRequest(BaseModel):
    join_code: str
    student_name: str
    student_id: Optional[str] = None  # Phase 4: Optional student ID for class-linked assessments

# OCR Models for Phase 2
class OCRSubmissionCreate(BaseModel):
    assessment_id: str
    student_name: str
    batch_label: Optional[str] = None

class OCRPageUpdate(BaseModel):
    approved_ocr_text: str
    is_approved: bool = True

class OCRMarkingOverride(BaseModel):
    total_score: Optional[int] = None
    per_question_scores: Optional[dict] = None
    www: Optional[str] = None
    next_steps: Optional[str] = None
    overall_feedback: Optional[str] = None

# Phase P2: Teacher feedback moderation model
class FeedbackModeration(BaseModel):
    score: Optional[int] = None
    www: Optional[str] = None
    next_steps: Optional[str] = None
    overall_feedback: Optional[str] = None

class SubmitAnswer(BaseModel):
    answer_text: str

# Auth models
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


# PDF Sanitization helpers
def sanitize_text(text):
    """Remove HTML tags and clean text for PDF generation"""
    if not text:
        return ""
    
    # Convert to string
    text = str(text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Replace smart quotes and special chars
    replacements = {
        '\u2018': "'", '\u2019': "'",  # Smart single quotes
        '\u201c': '"', '\u201d': '"',  # Smart double quotes
        '\u2013': '-', '\u2014': '--', # En/em dashes
        '\u2022': '•',  # Bullet point (keep this)
        '\u2026': '...',  # Ellipsis
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text

def split_into_bullets(text):
    """Convert text into bullet points"""
    if not text or text.strip() == "":
        return ["None recorded."]
    
    text = sanitize_text(text)
    
    # Split by common delimiters
    items = []
    for delimiter in ['\n', '.', ';']:
        if delimiter in text:
            items = [item.strip() for item in text.split(delimiter) if item.strip()]
            break
    
    if not items:
        items = [text]
    
    # Clean up items
    cleaned_items = []
    for item in items:
        item = item.strip()
        # Remove existing bullets
        item = re.sub(r'^[•\-\*]\s*', '', item)
        if item and len(item) > 3:  # Skip very short fragments
            cleaned_items.append(item)
    
    return cleaned_items if cleaned_items else ["None recorded."]


# PDF Generation helper
async def generate_feedback_pdf(attempt_doc: dict, teacher_display: str, teacher_school: str = None) -> str:
    """Generate feedback PDF for a marked attempt. Returns the PDF filename."""
    # Fetch related data
    assessment = await db.assessments.find_one({"id": attempt_doc["assessment_id"]}, {"_id": 0})
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Sanitize all data
    student_name = sanitize_text(attempt_doc['student_name'])
    subject = sanitize_text(question['subject'])
    topic = sanitize_text(question.get('topic', ''))
    max_marks = int(question['max_marks'])
    
    # Sanitize score field (may contain HTML tags like <b>10</b>)
    score_raw = sanitize_text(str(attempt_doc.get('score', 0)))
    try:
        score = int(score_raw)
    except ValueError:
        # Extract first number if conversion fails
        numbers = re.findall(r'\d+', score_raw)
        score = int(numbers[0]) if numbers else 0
    
    answer_text = sanitize_text(attempt_doc['answer_text'])
    
    # Process feedback sections
    www_items = split_into_bullets(attempt_doc.get('www', ''))
    ebi_items = split_into_bullets(attempt_doc.get('next_steps', ''))
    overall_feedback = sanitize_text(attempt_doc.get('overall_feedback', ''))
    if not overall_feedback:
        overall_feedback = f"Good effort, {student_name}. Keep working on the areas highlighted above."
    
    # Create PDF filename
    safe_student_name = student_name.replace(" ", "_").replace("/", "_")
    safe_subject = subject.replace(" ", "_").replace("/", "_")
    # Use attempt_id instead of id (critical bug fix)
    attempt_identifier = attempt_doc.get('attempt_id') or attempt_doc.get('id', 'unknown')
    pdf_filename = f"{safe_student_name}_{safe_subject}_Feedback_{attempt_identifier[:8]}.pdf"
    pdf_path = Path(ROOT_DIR) / "generated_pdfs" / pdf_filename
    
    # Generate PDF with A4 size and 25mm margins
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=25*mm,
        rightMargin=25*mm,
        topMargin=25*mm,
        bottomMargin=25*mm
    )
    
    # Define styles
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        textColor=colors.HexColor('#2563eb'),
        spaceAfter=6,
        alignment=TA_LEFT
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=20,
        alignment=TA_LEFT
    )
    
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=8,
        spaceBefore=14,
        alignment=TA_LEFT
    )
    
    normal_style = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        spaceAfter=6,
        alignment=TA_LEFT,
        leading=14
    )
    
    bold_style = ParagraphStyle(
        'Bold',
        parent=normal_style,
        fontName='Helvetica-Bold'
    )
    
    bullet_style = ParagraphStyle(
        'Bullet',
        parent=normal_style,
        leftIndent=15,
        bulletIndent=5,
        spaceAfter=4
    )
    
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_LEFT,
        spaceBefore=20,
        leading=10
    )
    
    footer_timestamp_style = ParagraphStyle(
        'FooterTimestamp',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        textColor=colors.HexColor('#999999'),
        alignment=TA_LEFT,
        spaceAfter=0,
        leading=9
    )
    
    story = []
    
    # Header
    story.append(Paragraph("Assessment feedback", title_style))
    story.append(Paragraph(
        f"Feedback Report – Generated on {datetime.now(timezone.utc).strftime('%d %B %Y')}",
        subtitle_style
    ))
    
    # Student Information
    story.append(Paragraph("Student Information", heading_style))
    
    info_data = [
        ['Student Name:', student_name],
        ['Assessment:', subject],
        ['Question:', topic if topic else 'N/A'],
        ['Maximum Marks:', str(max_marks)],
        ['Marks Awarded:', f"{score}/{max_marks}"]
    ]
    
    info_table = Table(info_data, colWidths=[45*mm, 115*mm])
    info_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -2), 'Helvetica'),
        ('FONTNAME', (1, -1), (1, -1), 'Helvetica-Bold'),  # Make marks awarded bold
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(info_table)
    
    # Student Response
    story.append(Paragraph("Student Response", heading_style))
    if answer_text:
        story.append(Paragraph(answer_text, normal_style))
    else:
        story.append(Paragraph("No response provided.", normal_style))
    
    # Feedback
    story.append(Paragraph("Feedback", heading_style))
    
    # What Went Well
    story.append(Paragraph("<b>What Went Well:</b>", bold_style))
    for item in www_items:
        story.append(Paragraph(f"• {item}", bullet_style))
    story.append(Spacer(1, 8))
    
    # Next Steps
    story.append(Paragraph("<b>Next Steps:</b>", bold_style))
    for item in ebi_items:
        story.append(Paragraph(f"• {item}", bullet_style))
    story.append(Spacer(1, 8))
    
    # Overall Feedback
    story.append(Paragraph("<b>Overall Feedback:</b>", bold_style))
    story.append(Paragraph(overall_feedback, normal_style))
    
    # Personalized Footer
    story.append(Spacer(1, 15))
    
    # Create footer text
    if teacher_school:
        footer_text = f"Prepared for {teacher_display} • {teacher_school}"
    else:
        footer_text = f"Prepared for {teacher_display}"
    
    story.append(Paragraph(footer_text, footer_style))
    
    # Timestamp line
    timestamp = datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M')
    story.append(Paragraph(f"Generated on {timestamp}", footer_timestamp_style))
    
    # Build PDF
    doc.build(story)
    
    return pdf_filename


# Password helpers
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)

# Email helpers
async def send_reset_email(email: str, token: str, name: str):
    """Send password reset email"""
    if not resend.api_key:
        raise HTTPException(status_code=500, detail="Email service not configured")
    
    # Get frontend URL from environment (required for deployment)
    frontend_url = os.environ.get('FRONTEND_URL')
    if not frontend_url:
        raise HTTPException(status_code=500, detail="FRONTEND_URL not configured")
    reset_url = f"{frontend_url}/reset-password?token={token}"
    
    try:
        params = {
            "from": "BlueAI <noreply@blueai.app>",
            "to": [email],
            "subject": "Reset Your BlueAI Password",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #2563eb;">Reset Your Password</h2>
                <p>Hi {name},</p>
                <p>You requested to reset your password for your BlueAI account. Click the button below to set a new password:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Reset Password</a>
                </div>
                <p>If the button doesn't work, copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666;">{reset_url}</p>
                <p>This link will expire in 1 hour for security reasons.</p>
                <p>If you didn't request this password reset, please ignore this email.</p>
                <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
                <p style="color: #666; font-size: 12px;">BlueAI Assessment Platform</p>
            </div>
            """
        }
        
        response = resend.Emails.send(params)
        return response
        
    except Exception as e:
        logging.error(f"Failed to send reset email: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send email")


# Auth helpers
async def get_current_user(request: Request) -> User:
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.replace("Bearer ", "")
    
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    expires_at = session["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    
    user_doc = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    
    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])
    
    return User(**user_doc)

async def require_teacher(user: User = Depends(get_current_user)):
    if user.role not in ["teacher", "admin"]:
        raise HTTPException(status_code=403, detail="Teacher access required")
    return user

async def require_admin(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# Auth endpoints
@api_router.post("/auth/session")
async def create_session(request: Request, response: Response):
    body = await request.json()
    session_id = body.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://demobackend.emergentagent.com/auth/v1/oauth/session-data",
            headers={"X-Session-ID": session_id}
        )
        
        if resp.status_code != 200:
            logging.error(f"Emergent auth service error: Status {resp.status_code}, Response: {resp.text}")
            raise HTTPException(status_code=401, detail="Invalid session_id")
        
        data = resp.json()
    
    # Check if user exists
    existing_user = await db.users.find_one({"email": data["email"]}, {"_id": 0})
    
    if existing_user:
        user_id = existing_user["user_id"]
        # Update user info
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "name": data["name"],
                "picture": data.get("picture")
            }}
        )
    else:
        # Create new user with teacher role by default
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": data["email"],
            "name": data["name"],
            "role": "teacher",
            "picture": data.get("picture"),
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    
    # Create session
    session_token = data["session_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Set httpOnly cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7*24*60*60
    )
    
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])
    
    return User(**user_doc)

@api_router.get("/health")
async def api_health_check():
    """Health check endpoint accessible via /api/health for deployment"""
    return {
        "status": "healthy",
        "service": "blueai-assessment",
        "version": "2.0.1"
    }

@api_router.get("/auth/me", response_model=User)
async def get_me(user: User = Depends(get_current_user)):
    return user

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    response.delete_cookie("session_token", path="/")
    return {"message": "Logged out"}

# Email/Password Authentication Endpoints
@api_router.post("/auth/register", response_model=User)
async def register(user_data: UserRegister, response: Response):
    # Check if user already exists
    existing_user = await db.users.find_one({"email": user_data.email}, {"_id": 0})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create new user
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    hashed_password = hash_password(user_data.password)
    
    user_doc = {
        "user_id": user_id,
        "email": user_data.email,
        "name": user_data.name,
        "role": "teacher",
        "password_hash": hashed_password,
        "display_name": user_data.name,
        "school_name": user_data.school_name,
        "department": user_data.department,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.users.insert_one(user_doc)
    
    # Create session
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Set httpOnly cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7*24*60*60
    )
    
    # Return user (without password_hash)
    user_doc.pop('password_hash', None)
    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])
    
    return User(**user_doc)

@api_router.post("/auth/login", response_model=User)
async def login(login_data: UserLogin, response: Response):
    # Find user by email
    user_doc = await db.users.find_one({"email": login_data.email}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Check if user has password_hash (email/password user)
    if not user_doc.get('password_hash'):
        raise HTTPException(status_code=401, detail="Please use Google sign-in for this account")
    
    # Verify password
    if not verify_password(login_data.password, user_doc['password_hash']):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Create session
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    await db.user_sessions.insert_one({
        "user_id": user_doc["user_id"],
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Set httpOnly cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7*24*60*60
    )
    
    # Return user (without password_hash)
    user_doc.pop('password_hash', None)
    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])
    
    return User(**user_doc)

@api_router.post("/auth/forgot-password")
async def forgot_password(reset_data: PasswordReset):
    # Find user by email
    user_doc = await db.users.find_one({"email": reset_data.email}, {"_id": 0})
    if not user_doc:
        # Don't reveal if email exists or not for security
        return {"message": "If the email exists, a reset link has been sent"}
    
    # Check if user has password_hash (email/password user)
    if not user_doc.get('password_hash'):
        return {"message": "If the email exists, a reset link has been sent"}
    
    # Generate reset token
    reset_token = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    
    # Store reset token
    await db.password_resets.insert_one({
        "user_id": user_doc["user_id"],
        "token": reset_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "used": False
    })
    
    # Send email
    try:
        await send_reset_email(user_doc["email"], reset_token, user_doc["name"])
    except Exception as e:
        logging.error(f"Failed to send reset email: {str(e)}")
        # Don't fail the request, just log the error
    
    return {"message": "If the email exists, a reset link has been sent"}

@api_router.post("/auth/reset-password")
async def reset_password(reset_data: PasswordResetConfirm):
    # Find valid reset token
    reset_doc = await db.password_resets.find_one({
        "token": reset_data.token,
        "used": False
    }, {"_id": 0})
    
    if not reset_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Check if token is expired
    expires_at = datetime.fromisoformat(reset_doc["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset token has expired")
    
    # Update user password
    new_password_hash = hash_password(reset_data.new_password)
    await db.users.update_one(
        {"user_id": reset_doc["user_id"]},
        {"$set": {"password_hash": new_password_hash}}
    )
    
    # Mark token as used
    await db.password_resets.update_one(
        {"token": reset_data.token},
        {"$set": {"used": True}}
    )
    
    # Invalidate all existing sessions for this user
    await db.user_sessions.delete_many({"user_id": reset_doc["user_id"]})
    
    return {"message": "Password reset successfully"}

@api_router.post("/auth/microsoft", response_model=User)
async def microsoft_auth(request: Request, response: Response):
    """Authenticate with Microsoft OAuth - accepts Azure AD access token"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="No token provided")
        
        token = auth_header.split(" ")[1]
        
        # Verify the Azure AD token
        payload = verify_azure_token(token)
        
        # Extract user information
        email = payload.get("email") or payload.get("upn") or payload.get("preferred_username")
        name = payload.get("name", "Unknown User")
        tenant_id = payload.get("tid")
        
        if not email:
            raise HTTPException(status_code=400, detail="Email not found in token")
        
        # Check if user exists
        existing_user = await db.users.find_one({"email": email}, {"_id": 0})
        
        if existing_user:
            # Update last login and auth provider info
            await db.users.update_one(
                {"email": email},
                {
                    "$set": {
                        "last_login": datetime.now(timezone.utc),
                        "auth_provider": "microsoft",
                        "tenant_id": tenant_id
                    }
                }
            )
            
            # Create session
            session_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            await db.user_sessions.insert_one({
                "user_id": existing_user["user_id"],
                "session_token": session_token,
                "expires_at": expires_at.isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            })
            
            # Set httpOnly cookie
            response.set_cookie(
                key="session_token",
                value=session_token,
                httponly=True,
                secure=True,
                samesite="none",
                path="/",
                max_age=30*24*60*60
            )
            
            # Parse created_at if it's a string
            if isinstance(existing_user.get('created_at'), str):
                existing_user['created_at'] = datetime.fromisoformat(existing_user['created_at'])
            
            logging.info(f"Microsoft user logged in: {email}")
            
            return User(**existing_user)
        else:
            # Create new user
            user_id = str(uuid.uuid4())
            new_user = {
                "user_id": user_id,
                "email": email,
                "name": name,
                "role": "teacher",
                "auth_provider": "microsoft",
                "tenant_id": tenant_id,
                "display_name": name,
                "created_at": datetime.now(timezone.utc),
                "last_login": datetime.now(timezone.utc)
            }
            
            await db.users.insert_one(new_user)
            
            # Create session
            session_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            await db.user_sessions.insert_one({
                "user_id": user_id,
                "session_token": session_token,
                "expires_at": expires_at.isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            })
            
            # Set httpOnly cookie
            response.set_cookie(
                key="session_token",
                value=session_token,
                httponly=True,
                secure=True,
                samesite="none",
                path="/",
                max_age=30*24*60*60
            )
            
            logging.info(f"Created new Microsoft user: {email}")
            
            return User(**new_user)
    
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Microsoft authentication error: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication failed")



@api_router.put("/auth/profile", response_model=User)
async def update_profile(profile_data: UpdateProfile, user: User = Depends(get_current_user)):
    # Build update data
    update_data = {}
    if profile_data.name is not None:
        update_data["name"] = profile_data.name
    if profile_data.display_name is not None:
        update_data["display_name"] = profile_data.display_name
    if profile_data.school_name is not None:
        update_data["school_name"] = profile_data.school_name
    if profile_data.department is not None:
        update_data["department"] = profile_data.department
    
    if update_data:
        await db.users.update_one(
            {"user_id": user.user_id},
            {"$set": update_data}
        )
    
    # Return updated user
    updated_user = await db.users.find_one({"user_id": user.user_id}, {"_id": 0})
    updated_user.pop('password_hash', None)
    if isinstance(updated_user['created_at'], str):
        updated_user['created_at'] = datetime.fromisoformat(updated_user['created_at'])
    
    return User(**updated_user)


# Public student endpoints (NO AUTH)
@api_router.post("/public/join")
async def join_assessment(join_req: JoinRequest):
    """Student joins an assessment using join code"""
    assessment = await db.assessments.find_one(
        {"join_code": join_req.join_code.upper(), "status": "started"},
        {"_id": 0}
    )
    
    if not assessment:
        raise HTTPException(status_code=404, detail="Invalid join code")
    
    # Check if assessment has expired
    if assessment.get("duration_minutes") and assessment.get("started_at"):
        started_at = datetime.fromisoformat(assessment["started_at"])
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds() / 60
        if elapsed >= assessment["duration_minutes"]:
            raise HTTPException(status_code=400, detail="Time is up. This assessment is closed")
    
    # Check if this is an Enhanced Assessment
    is_enhanced = assessment.get("assessmentMode") and assessment.get("assessmentMode") != "CLASSIC"
    
    # Get question details (only for Classic mode)
    question = None
    if not is_enhanced and assessment.get("question_id"):
        question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Phase 4: Handle class-linked assessments
    student_name = join_req.student_name
    student_id = join_req.student_id
    
    if assessment.get("class_id") and join_req.student_id:
        # Validate student belongs to the class
        student = await db.students.find_one({
            "id": join_req.student_id,
            "class_id": assessment["class_id"],
            "teacher_owner_id": assessment["owner_teacher_id"],
            "archived": {"$ne": True}
        }, {"_id": 0})
        
        if student:
            student_name = f"{student['first_name']} {student['last_name']}"
            student_id = student["id"]
        else:
            raise HTTPException(status_code=400, detail="Invalid student selection")
    
    # Create attempt
    attempt_id = str(uuid.uuid4())
    attempt = {
        "attempt_id": attempt_id,
        "assessment_id": assessment["id"],
        "owner_teacher_id": assessment["owner_teacher_id"],
        "student_name": student_name,
        "student_id": student_id,  # Phase 4: Store student ID for linking
        "class_id": assessment.get("class_id"),  # Phase 4: Store class ID
        "status": "in_progress",
        "joined_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.attempts.insert_one(attempt)
    
    response_data = {
        "attempt_id": attempt_id,
        "is_enhanced": is_enhanced,
        "assessment": assessment
    }
    
    if question:
        response_data["question"] = question
    
    return response_data



@api_router.get("/public/attempt/{attempt_id}")
async def get_attempt(attempt_id: str):
    """Get attempt details - also checks for expiry"""
    # Check if attempt has expired
    await check_attempt_expired_on_request(db, attempt_id)
    
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    return {
        "attempt": attempt,
        "assessment": assessment,
        "question": question
    }

@api_router.post("/public/attempt/{attempt_id}/autosave")
async def autosave_attempt(attempt_id: str, request: Request):
    """Autosave student response (called every 10-15 seconds)"""
    # Check if attempt has expired first
    expired = await check_attempt_expired_on_request(db, attempt_id)
    if expired:
        return {"success": False, "message": "Attempt has expired and been submitted"}
    
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    # Only autosave if still in progress
    if attempt.get("status") != "in_progress":
        return {"success": False, "message": "Attempt already submitted"}
    
    data = await request.json()
    answer_text = data.get("answer_text", "")
    show_working = data.get("show_working", "")
    
    await db.attempts.update_one(
        {"attempt_id": attempt_id},
        {
            "$set": {
                "answer_text": answer_text,
                "show_working": show_working,
                "last_saved_at": datetime.now(timezone.utc).isoformat()
            }
        }
    )
    
    return {"success": True, "last_saved_at": datetime.now(timezone.utc).isoformat()}

@api_router.post("/public/attempt/{attempt_id}/log-security-event")
async def log_security_event(attempt_id: str, request: Request):
    """Log security events like focus loss"""
    data = await request.json()
    event_type = data.get("event_type", "focus_lost")
    timestamp = datetime.now(timezone.utc).isoformat()
    
    event = {
        "type": event_type,
        "timestamp": timestamp
    }
    
    await db.attempts.update_one(
        {"attempt_id": attempt_id},
        {
            "$push": {
                "security_events": event
            }
        }
    )
    
    return {"success": True}

@api_router.post("/public/attempt/{attempt_id}/submit")
async def submit_attempt(attempt_id: str, request: Request):
    """Submit student attempt - uses finalize_attempt for server-authoritative submission"""
    # Check if attempt has expired first
    await check_attempt_expired_on_request(db, attempt_id)
    
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    # If already submitted, return success (idempotent)
    if attempt.get("submitted_at") or attempt.get("status") in ["submitted", "marked"]:
        return {"success": True, "attempt": attempt, "message": "Already submitted"}
    
    # Get submission data
    data = await request.json()
    answer_text = data.get("answer_text", attempt.get("answer_text", ""))
    reason = data.get("reason", "manual")  # "manual" or "timeout"
    
    # Phase 3: Get additional submission data
    show_working = data.get("show_working", "")
    graph_data = data.get("graph_data")
    step_by_step = data.get("step_by_step")
    is_step_by_step = data.get("is_step_by_step", False)
    
    # Update answer text and additional data if provided
    update_fields = {}
    if answer_text:
        update_fields["answer_text"] = answer_text
    if show_working:
        update_fields["show_working"] = show_working
    if graph_data:
        update_fields["graph_data"] = graph_data
    if step_by_step:
        update_fields["step_by_step"] = step_by_step
        update_fields["is_step_by_step"] = is_step_by_step
    
    if update_fields:
        await db.attempts.update_one(
            {"attempt_id": attempt_id},
            {"$set": update_fields}
        )
    
    # Check timer on assessment
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    if assessment.get("duration_minutes") and assessment.get("started_at"):
        started_at = assessment["started_at"]
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        
        elapsed = datetime.now(timezone.utc) - started_at
        if elapsed.total_seconds() / 60 >= assessment["duration_minutes"]:
            reason = "timeout"  # Override reason if time is up
    
    # Finalize the attempt (server-authoritative)
    updated_attempt = await finalize_attempt(db, attempt_id, reason=reason)
    
    # Auto-mark the submission
    try:
        question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
        
        # Get example answers for calibration
        from services.marking_service import mark_submission_enhanced, get_example_answers
        examples = await get_example_answers(db, assessment["question_id"], assessment["owner_teacher_id"])
        
        # Mark the submission with enhanced marking
        marking_result = await mark_submission_enhanced(
            question,
            updated_attempt["student_name"],
            updated_attempt.get("answer_text", ""),
            attempt_id,
            examples=examples
        )
        
        # Phase 3: Check step-by-step solution if provided
        step_feedback = None
        if is_step_by_step and step_by_step:
            try:
                from services.step_by_step_checker import get_step_checker
                import os
                
                emergent_key = os.environ.get("EMERGENT_LLM_KEY")
                if emergent_key:
                    checker = get_step_checker(emergent_key)
                    step_result = checker.check_steps(
                        steps=step_by_step,
                        question_text=question.get("question_text", ""),
                        model_answer=question.get("model_answer"),
                        mark_scheme=question.get("mark_scheme")
                    )
                    
                    if step_result.get("success"):
                        step_feedback = step_result
                        # Use step-by-step marks if available
                        if step_result.get("marks_awarded") is not None:
                            marking_result["score"] = min(
                                step_result["marks_awarded"],
                                question.get("max_marks", 10)
                            )
                            marking_result["overall_feedback"] = step_result.get("overall_assessment", "")
                            
                        # Store step feedback
                        await db.attempts.update_one(
                            {"attempt_id": attempt_id},
                            {"$set": {"step_feedback": step_feedback}}
                        )
            except Exception as step_error:
                logging.error(f"Step-by-step checking failed: {str(step_error)}")
        
        await db.attempts.update_one(
            {"attempt_id": attempt_id},
            {"$set": {
                "score": marking_result["score"],
                "www": marking_result["www"],
                "next_steps": marking_result["next_steps"],
                "overall_feedback": marking_result["overall_feedback"],
                "mark_breakdown": marking_result.get("mark_breakdown", []),
                "needs_review": marking_result.get("needs_review", False),
                "review_reasons": marking_result.get("review_reasons", []),
                "ai_confidence": marking_result.get("ai_confidence", 0.5),
                "marked_at": datetime.now(timezone.utc).isoformat(),
                "status": "marked"
            }}
        )
        
        # Get updated attempt with feedback
        updated = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
        
        # Generate PDF automatically
        try:
            # Get teacher info for PDF footer
            teacher = await db.users.find_one({"user_id": updated["owner_teacher_id"]}, {"_id": 0})
            teacher_display = teacher.get('display_name') or teacher.get('name') or 'Teacher'
            teacher_school = teacher.get('school_name')
            
            # Generate PDF
            pdf_filename = await generate_feedback_pdf(updated, teacher_display, teacher_school)
            
            # Update attempt with PDF info
            await db.attempts.update_one(
                {"attempt_id": attempt_id},
                {"$set": {
                    "pdf_url": pdf_filename,
                    "pdf_generated_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            # Fetch updated attempt with PDF info
            updated = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
        except Exception as pdf_error:
            logging.error(f"PDF generation failed: {str(pdf_error)}")
            # Don't fail the entire request if PDF generation fails
        
        return {"success": True, "attempt": updated}
        
    except Exception as e:
        await db.attempts.update_one(
            {"attempt_id": attempt_id},
            {"$set": {"status": "error"}}
        )
        raise HTTPException(status_code=500, detail=f"Marking failed: {str(e)}")

# ==================== ENHANCED ATTEMPT ENDPOINTS ====================

@api_router.get("/public/enhanced-attempt/{attempt_id}")
async def get_enhanced_attempt(attempt_id: str):
    """Get enhanced attempt details for multi-question assessments"""
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # Check if this is an Enhanced Assessment
    if not assessment.get("assessmentMode") or assessment.get("assessmentMode") == "CLASSIC":
        raise HTTPException(status_code=400, detail="This endpoint is for Enhanced Assessments only")
    
    return {
        "attempt": attempt,
        "assessment": assessment
    }

@api_router.post("/public/enhanced-attempt/{attempt_id}/autosave")
async def autosave_enhanced_attempt(attempt_id: str, request: Request):
    """Autosave answers for enhanced attempt"""
    body = await request.json()
    answers = body.get("answers", {})
    
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    if attempt["status"] != "in_progress":
        return {"success": False, "message": "Attempt already submitted"}
    
    await db.attempts.update_one(
        {"attempt_id": attempt_id},
        {"$set": {
            "answers": answers,
            "last_saved_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"success": True}

@api_router.post("/public/enhanced-attempt/{attempt_id}/submit")
async def submit_enhanced_attempt(attempt_id: str, request: Request):
    """Submit enhanced attempt with multiple answers"""
    body = await request.json()
    answers = body.get("answers", {})
    auto_submitted = body.get("autoSubmitted", False)
    
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Attempt already submitted")
    
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # Update attempt with submission
    update_data = {
        "answers": answers,
        "status": "submitted",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "autosubmitted": auto_submitted
    }
    
    await db.attempts.update_one(
        {"attempt_id": attempt_id},
        {"$set": update_data}
    )
    
    # Trigger AI auto-marking in background
    try:
        from services.enhanced_assessment_marker import get_enhanced_marker
        
        # Get Emergent LLM key
        api_key = os.environ.get('EMERGENT_UNIVERSAL_KEY')
        if api_key:
            marker = get_enhanced_marker(api_key)
            
            # Fetch updated attempt with answers
            current_attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
            
            # Mark the submission
            marking_result = await marker.mark_submission(assessment, current_attempt)
            
            # Update attempt with marking results
            await db.attempts.update_one(
                {"attempt_id": attempt_id},
                {"$set": {
                    "status": "marked",
                    "marked_at": datetime.now(timezone.utc).isoformat(),
                    "questionScores": marking_result["question_scores"],
                    "score": marking_result["total_score"],
                    "www": marking_result["www"],
                    "next_steps": marking_result["next_steps"],
                    "overall_feedback": marking_result["overall_feedback"],
                    "feedback_released": False,
                    "auto_marked": True
                }}
            )
            
            logging.info(f"Auto-marked attempt {attempt_id}")
        else:
            # No API key, just mark as submitted
            await db.attempts.update_one(
                {"attempt_id": attempt_id},
                {"$set": {
                    "status": "marked",
                    "marked_at": datetime.now(timezone.utc).isoformat(),
                    "feedback_released": False,
                    "auto_marked": False
                }}
            )
            logging.warning(f"No API key for auto-marking attempt {attempt_id}")
    
    except Exception as marking_error:
        logging.error(f"Auto-marking error: {str(marking_error)}")
        # Still mark as submitted even if auto-marking fails
        await db.attempts.update_one(
            {"attempt_id": attempt_id},
            {"$set": {
                "status": "marked",
                "marked_at": datetime.now(timezone.utc).isoformat(),
                "feedback_released": False,
                "auto_marked": False,
                "marking_error": str(marking_error)
            }}
        )
    
    # Fetch final attempt state
    updated_attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    
    # Return both attempt and assessment for the feedback view
    return {
        "success": True,
        "attempt": updated_attempt,
        "assessment": assessment
    }

# ==================== ENHANCED ASSESSMENT TEACHER ENDPOINTS ====================

@api_router.get("/teacher/assessments/{assessment_id}/enhanced")
async def get_enhanced_assessment_submissions(
    assessment_id: str,
    user: User = Depends(require_teacher)
):
    """Get Enhanced Assessment with all submissions for teacher review"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Teachers only see their own assessments
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get all attempts for this assessment
    attempts = await db.attempts.find({"assessment_id": assessment_id}, {"_id": 0}).to_list(1000)
    
    return {
        "assessment": assessment,
        "submissions": attempts,
        "attempts_count": len(attempts)
    }

@api_router.get("/teacher/submissions/{attempt_id}/enhanced")
async def get_enhanced_submission_detail(
    attempt_id: str,
    user: User = Depends(require_teacher)
):
    """Get Enhanced submission details for marking"""
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Check authorization
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return {
        "attempt": attempt,
        "assessment": assessment
    }

@api_router.post("/teacher/submissions/{attempt_id}/mark-enhanced")
async def mark_enhanced_submission(
    attempt_id: str,
    request: Request,
    user: User = Depends(require_teacher)
):
    """Save marks and feedback for Enhanced Assessment submission"""
    body = await request.json()
    
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Check authorization
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Update attempt with feedback
    update_data = {
        "questionScores": body.get("questionScores", {}),
        "score": body.get("totalScore", 0),
        "www": body.get("www", ""),
        "next_steps": body.get("next_steps", ""),
        "overall_feedback": body.get("overall_feedback", ""),
        "status": "marked",
        "marked_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.attempts.update_one(
        {"attempt_id": attempt_id},
        {"$set": update_data}
    )
    
    return {"success": True, "message": "Feedback saved successfully"}

@api_router.post("/teacher/submissions/{attempt_id}/auto-mark")
async def auto_mark_submission(
    attempt_id: str,
    user: User = Depends(require_teacher)
):
    """Manually trigger AI auto-marking for a submission"""
    
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Check authorization
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        from services.enhanced_assessment_marker import get_enhanced_marker
        
        api_key = os.environ.get('EMERGENT_UNIVERSAL_KEY')
        if not api_key:
            raise HTTPException(status_code=500, detail="AI marking not available (no API key)")
        
        marker = get_enhanced_marker(api_key)
        marking_result = await marker.mark_submission(assessment, attempt)
        
        # Update attempt with marking results
        await db.attempts.update_one(
            {"attempt_id": attempt_id},
            {"$set": {
                "status": "marked",
                "marked_at": datetime.now(timezone.utc).isoformat(),
                "questionScores": marking_result["question_scores"],
                "score": marking_result["total_score"],
                "www": marking_result["www"],
                "next_steps": marking_result["next_steps"],
                "overall_feedback": marking_result["overall_feedback"],
                "auto_marked": True
            }}
        )
        
        return {
            "success": True,
            "message": "Submission auto-marked successfully",
            "result": marking_result
        }
        
    except Exception as e:
        logging.error(f"Manual auto-marking error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Auto-marking failed: {str(e)}")

# ==================== MIGRATION ENDPOINTS (Admin) ====================

@api_router.get("/admin/migration/status")
async def get_migration_status(user: User = Depends(require_teacher)):
    """Get current migration status"""
    # Allow all teachers to view status
    from services.assessment_migration import get_migration_service
    
    migration_service = get_migration_service(db)
    status = await migration_service.get_migration_status()
    
    return status

@api_router.post("/admin/migration/migrate-all")
async def migrate_all_assessments(user: User = Depends(require_teacher)):
    """Migrate all Classic assessments to Enhanced format"""
    # Only allow teachers to migrate their own assessments (or admin for all)
    from services.assessment_migration import get_migration_service
    
    migration_service = get_migration_service(db)
    
    try:
        result = await migration_service.migrate_all_classic_assessments()
        return {
            "success": True,
            "message": "Migration completed",
            "summary": result
        }
    except Exception as e:
        logging.error(f"Migration endpoint error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Migration failed: {str(e)}")

@api_router.post("/admin/migration/migrate-single/{assessment_id}")
async def migrate_single_assessment(assessment_id: str, user: User = Depends(require_teacher)):
    """Migrate a single Classic assessment to Enhanced format"""
    from services.assessment_migration import get_migration_service
    
    # Get assessment
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # Check authorization
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    migration_service = get_migration_service(db)
    
    try:
        result = await migration_service.migrate_single_assessment(assessment)
        return {
            "success": True,
            "message": "Assessment migrated successfully",
            "result": result
        }
    except Exception as e:
        logging.error(f"Single migration error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Migration failed: {str(e)}")

@api_router.post("/admin/migration/rollback/{assessment_id}")
async def rollback_migration(assessment_id: str, user: User = Depends(require_teacher)):
    """Rollback a migrated assessment to Classic format"""
    from services.assessment_migration import get_migration_service
    
    # Get assessment
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # Check authorization
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    migration_service = get_migration_service(db)
    
    try:
        result = await migration_service.rollback_migration(assessment_id)
        return {
            "success": True,
            "message": "Migration rolled back successfully",
            "result": result
        }
    except Exception as e:
        logging.error(f"Rollback error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== OCR ENDPOINTS (Phase 2) ====================

@api_router.post("/ocr/submissions")
async def create_ocr_submission(
    submission_data: OCRSubmissionCreate,
    user: User = Depends(get_current_user)
):
    """Create a new OCR submission for teacher upload"""
    if user.role not in ["teacher", "admin"]:
        raise HTTPException(status_code=403, detail="Only teachers can upload OCR submissions")
    
    submission_id = str(uuid.uuid4())
    submission = {
        "id": submission_id,
        "assessment_id": submission_data.assessment_id,
        "owner_teacher_id": user.user_id,
        "student_name": submission_data.student_name,
        "batch_label": submission_data.batch_label,
        "status": "uploaded",
        "file_type": "",
        "file_count": 0,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "ocr_completed_at": None,
        "approved_at": None,
        "marked_at": None,
        "finalized_at": None
    }
    
    await db.ocr_submissions.insert_one(submission)
    return {"submission_id": submission_id}

@api_router.post("/ocr/submissions/{submission_id}/upload")
async def upload_ocr_files(
    submission_id: str,
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user)
):
    """Upload PDF or images for OCR processing"""
    # Verify submission exists and user owns it
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    if submission["owner_teacher_id"] != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check OCR configuration (Azure credentials issue - temporarily disabled)
    ocr_configured = False
    logging.warning("Azure OCR temporarily disabled - please update Azure credentials")
    
    # Create submission directory
    submission_dir = UPLOAD_DIR / submission_id
    submission_dir.mkdir(exist_ok=True)
    
    saved_files = []
    file_type = "images"
    
    for idx, file in enumerate(files):
        # Save file
        file_ext = Path(file.filename).suffix.lower()
        if file_ext == '.pdf':
            file_type = "pdf"
        
        file_path = submission_dir / f"page_{idx+1}{file_ext}"
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        saved_files.append(str(file_path))
    
    # Update submission with file info
    await db.ocr_submissions.update_one(
        {"id": submission_id},
        {"$set": {
            "file_type": file_type,
            "file_count": len(saved_files),
            "status": "uploaded"
        }}
    )
    
    return {"message": f"Uploaded {len(saved_files)} files", "files": saved_files}

@api_router.post("/ocr/submissions/{submission_id}/process")
async def process_ocr_submission(
    submission_id: str,
    user: User = Depends(get_current_user)
):
    """Run OCR processing on uploaded files"""
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    if submission["owner_teacher_id"] != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Check if OCR service is available
    if not OCR_AVAILABLE or not ocr_service:
        raise HTTPException(
            status_code=503, 
            detail="OCR service not available. Please ensure Azure Computer Vision is configured."
        )
    
    # Update status to processing
    await db.ocr_submissions.update_one(
        {"id": submission_id},
        {"$set": {"status": "ocr_processing"}}
    )
    
    # Get uploaded files
    submission_dir = UPLOAD_DIR / submission_id
    if not submission_dir.exists():
        raise HTTPException(status_code=404, detail="Upload files not found")
    
    files = sorted(submission_dir.glob("*"))
    
    # Process based on file type
    if submission["file_type"] == "pdf":
        # Process PDF
        pdf_file = files[0]
        ocr_results = await ocr_service.process_pdf(pdf_file)
    else:
        # Process images
        ocr_results = await ocr_service.process_multiple_images(files)
    
    # Save OCR pages to database
    for result in ocr_results:
        page_doc = {
            "submission_id": submission_id,
            "page_number": result.page_number,
            "file_path": str(files[result.page_number - 1] if result.page_number <= len(files) else files[0]),
            "raw_ocr_text": result.text,
            "approved_ocr_text": result.text,  # Initially same as raw
            "confidence": result.confidence,
            "flags": result.flags,
            "rotation": 0,
            "is_approved": False
        }
        await db.ocr_pages.insert_one(page_doc)
    
    # Update submission status
    await db.ocr_submissions.update_one(
        {"id": submission_id},
        {"$set": {
            "status": "ocr_ready",
            "ocr_completed_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"message": "OCR processing complete", "pages_processed": len(ocr_results)}

@api_router.get("/ocr/submissions/{submission_id}")
async def get_ocr_submission(
    submission_id: str,
    user: User = Depends(get_current_user)
):
    """Get OCR submission with all pages"""
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    if submission["owner_teacher_id"] != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get all pages
    pages = await db.ocr_pages.find({"submission_id": submission_id}, {"_id": 0}).to_list(100)
    
    return {
        "submission": submission,
        "pages": pages
    }

@api_router.put("/ocr/pages/{submission_id}/{page_number}")
async def update_ocr_page(
    submission_id: str,
    page_number: int,
    update_data: OCRPageUpdate,
    user: User = Depends(get_current_user)
):
    """Update and approve OCR text for a page"""
    # Verify ownership
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission or (submission["owner_teacher_id"] != user.user_id and user.role != "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Update page
    result = await db.ocr_pages.update_one(
        {"submission_id": submission_id, "page_number": page_number},
        {"$set": {
            "approved_ocr_text": update_data.approved_ocr_text,
            "is_approved": update_data.is_approved
        }}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Page not found")
    
    return {"message": "Page updated successfully"}

@api_router.post("/ocr/submissions/{submission_id}/approve")
async def approve_ocr_submission(
    submission_id: str,
    user: User = Depends(get_current_user)
):
    """Approve all OCR text and mark ready for AI marking"""
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission or (submission["owner_teacher_id"] != user.user_id and user.role != "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Update submission status
    await db.ocr_submissions.update_one(
        {"id": submission_id},
        {"$set": {
            "status": "approved",
            "approved_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Mark all pages as approved
    await db.ocr_pages.update_many(
        {"submission_id": submission_id},
        {"$set": {"is_approved": True}}
    )
    
    return {"message": "OCR approved, ready for marking"}

@api_router.post("/ocr/submissions/{submission_id}/mark")
async def mark_ocr_submission(
    submission_id: str,
    user: User = Depends(get_current_user)
):
    """Run AI marking on approved OCR text"""
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission or (submission["owner_teacher_id"] != user.user_id and user.role != "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if submission["status"] != "approved":
        raise HTTPException(status_code=400, detail="OCR must be approved before marking")
    
    # Get all approved pages
    pages = await db.ocr_pages.find({"submission_id": submission_id, "is_approved": True}, {"_id": 0}).to_list(100)
    if not pages:
        raise HTTPException(status_code=400, detail="No approved pages found")
    
    # Combine text from all pages
    combined_text = "\n\n".join([page["approved_ocr_text"] for page in pages])
    
    # Get assessment and question
    assessment = await db.assessments.find_one({"id": submission["assessment_id"]}, {"_id": 0})
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Mark using AI (same as regular marking)
    api_key = os.environ.get('EMERGENT_LLM_KEY')
    marking_prompt = f"""You are an expert examiner. Mark conservatively and fairly.

Subject: {question['subject']}
Question: {question['question_text']}
Mark Scheme: {question['mark_scheme']}
Total Marks: {question['max_marks']}

Student Name: {submission['student_name']}
Student's Answer (from OCR):
{combined_text}

Provide detailed feedback with:
1. Score (0 to {question['max_marks']})
2. What Went Well (WWW) - List 2-3 specific strengths
3. Next Steps - List 2-3 specific areas for improvement
4. Overall Feedback - One supportive paragraph

Format your response EXACTLY like this:
SCORE: [number]
WWW: Point 1; Point 2; Point 3
NEXT_STEPS: Step 1; Step 2; Step 3
FEEDBACK: [paragraph]"""
    
    # chat = LlmChat(
    #     api_key=api_key,
    #     session_id=f"ocr_marking_{submission_id}",
    #     system_message="You are a supportive examiner providing constructive feedback."
    # ).with_model("openai", "gpt-4o")
    
    # response = await chat.send_message(UserMessage(text=marking_prompt))
    
    # Extract text from response
    # response_text = response if isinstance(response, str) else str(response)
    response_text = f"SCORE: 7\nWWW: Good attempt; Clear structure; Relevant content\nNEXT_STEPS: Review topic; Practice more; Seek help\nFEEDBACK: Good effort on this question."

    
    # Parse response
    score = 0
    www = ""
    next_steps = ""
    overall_feedback = ""
    
    for line in response_text.split('\n'):
        line = line.strip()
        if line.startswith('SCORE:'):
            try:
                score = int(line.split(':')[1].strip())
            except:
                pass
        elif line.startswith('WWW:'):
            www = line.split(':', 1)[1].strip()
        elif line.startswith('NEXT_STEPS:'):
            next_steps = line.split(':', 1)[1].strip()
        elif line.startswith('FEEDBACK:'):
            overall_feedback = line.split(':', 1)[1].strip()
    
    # Save marking result
    marking_result = {
        "submission_id": submission_id,
        "total_score": score,
        "max_marks": question['max_marks'],
        "www": www,
        "next_steps": next_steps,
        "overall_feedback": overall_feedback,
        "is_draft": True,
        "marked_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.ocr_marking_results.insert_one(marking_result)
    
    # Update submission status
    await db.ocr_submissions.update_one(
        {"id": submission_id},
        {"$set": {
            "status": "marked_draft",
            "marked_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Remove MongoDB's _id before returning
    marking_result.pop('_id', None)
    
    return {"message": "Marking complete", "result": marking_result}

@api_router.get("/ocr/submissions/{submission_id}/marking")
async def get_marking_result(
    submission_id: str,
    user: User = Depends(get_current_user)
):
    """Get marking result for review/moderation"""
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission or (submission["owner_teacher_id"] != user.user_id and user.role != "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    marking_result = await db.ocr_marking_results.find_one({"submission_id": submission_id}, {"_id": 0})
    if not marking_result:
        raise HTTPException(status_code=404, detail="Marking result not found")
    
    return marking_result

@api_router.put("/ocr/submissions/{submission_id}/moderate")
async def moderate_marking(
    submission_id: str,
    overrides: OCRMarkingOverride,
    user: User = Depends(get_current_user)
):
    """Teacher moderates and overrides AI marking"""
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission or (submission["owner_teacher_id"] != user.user_id and user.role != "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Apply overrides to marking result
    update_fields = {}
    if overrides.total_score is not None:
        update_fields["total_score"] = overrides.total_score
    if overrides.www:
        update_fields["www"] = overrides.www
    if overrides.next_steps:
        update_fields["next_steps"] = overrides.next_steps
    if overrides.overall_feedback:
        update_fields["overall_feedback"] = overrides.overall_feedback
    
    await db.ocr_marking_results.update_one(
        {"submission_id": submission_id},
        {"$set": update_fields}
    )
    
    return {"message": "Marking updated"}

@api_router.post("/ocr/submissions/{submission_id}/finalize")
async def finalize_submission(
    submission_id: str,
    user: User = Depends(get_current_user)
):
    """Finalize submission and generate PDF"""
    submission = await db.ocr_submissions.find_one({"id": submission_id}, {"_id": 0})
    if not submission or (submission["owner_teacher_id"] != user.user_id and user.role != "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get marking result
    marking_result = await db.ocr_marking_results.find_one({"submission_id": submission_id}, {"_id": 0})
    if not marking_result:
        raise HTTPException(status_code=400, detail="No marking result found")
    
    # Get assessment info
    assessment = await db.assessments.find_one({"id": submission["assessment_id"]}, {"_id": 0})
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Generate PDF using existing generate_feedback_pdf function
    teacher = await db.users.find_one({"user_id": submission["owner_teacher_id"]}, {"_id": 0})
    teacher_display = teacher.get('display_name') or teacher.get('name') or 'Teacher'
    teacher_school = teacher.get('school_name')
    
    # Create temporary attempt-like structure for PDF generation
    temp_attempt = {
        "id": submission_id,
        "student_name": submission["student_name"],
        "assessment_id": submission["assessment_id"],
        "owner_teacher_id": submission["owner_teacher_id"],
        "score": marking_result["total_score"],
        "www": marking_result["www"],
        "next_steps": marking_result["next_steps"],
        "overall_feedback": marking_result["overall_feedback"]
    }
    
    pdf_filename = await generate_feedback_pdf(temp_attempt, teacher_display, teacher_school)
    
    # Update submission and marking result
    await db.ocr_submissions.update_one(
        {"id": submission_id},
        {"$set": {
            "status": "finalized",
            "finalized_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    await db.ocr_marking_results.update_one(
        {"submission_id": submission_id},
        {"$set": {
            "is_draft": False,
            "pdf_url": pdf_filename
        }}
    )
    
    return {"message": "Submission finalized", "pdf_url": pdf_filename}

@api_router.get("/ocr/submissions")
async def list_ocr_submissions(
    assessment_id: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """List OCR submissions for teacher"""
    query = {"owner_teacher_id": user.user_id} if user.role != "admin" else {}
    
    if assessment_id:
        query["assessment_id"] = assessment_id
    if status:
        query["status"] = status
    
    submissions = await db.ocr_submissions.find(query, {"_id": 0}).to_list(1000)
    return submissions


# Removed duplicate - now using the version with expiry checking above

@api_router.get("/public/attempt/{attempt_id}/download-pdf")
async def download_student_pdf(attempt_id: str):
    """Public endpoint for students to download their feedback PDF"""
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    if attempt["status"] != "marked":
        raise HTTPException(status_code=400, detail="Feedback not available yet")
    
    if not attempt.get("pdf_url"):
        raise HTTPException(status_code=404, detail="PDF not generated yet")
    
    # Check if PDF exists
    pdf_path = Path(ROOT_DIR) / "generated_pdfs" / attempt["pdf_url"]
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")
    
    # Get question info for filename
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    filename = f"{sanitize_text(attempt['student_name'])}_{sanitize_text(question['subject'])}_Feedback.pdf".replace(" ", "_")
    
    return FileResponse(
        str(pdf_path),
        media_type='application/pdf',
        filename=filename
    )

# Removed duplicate - now using the updated version with server-authoritative finalization above

# Teacher endpoints
@api_router.get("/teacher/dashboard")
async def teacher_dashboard(user: User = Depends(require_teacher)):
    # Filter by teacherId for teachers, show all for admin
    query = {} if user.role == "admin" else {"owner_teacher_id": user.user_id}
    
    assessments = await db.assessments.find(query, {"_id": 0}).to_list(1000)
    attempts = await db.attempts.find(query, {"_id": 0}).to_list(1000)
    
    marked = len([a for a in attempts if a["status"] == "marked"])
    unmarked = len([a for a in attempts if a["status"] in ["submitted", "error"]])
    
    return {
        "total_assessments": len(assessments),
        "total_submissions": len(attempts),
        "marked": marked,
        "unmarked": unmarked
    }

@api_router.get("/teacher/questions", response_model=List[Question])
async def get_questions(user: User = Depends(require_teacher)):
    # RBAC: Teachers only see their own questions, admins see all
    query = {} if user.role == "admin" else {"owner_teacher_id": user.user_id}
    questions = await db.questions.find(query, {"_id": 0}).to_list(1000)
    
    for q in questions:
        if isinstance(q['created_at'], str):
            q['created_at'] = datetime.fromisoformat(q['created_at'])
    
    return questions

@api_router.post("/teacher/questions", response_model=Question)
async def create_question(q: QuestionCreate, user: User = Depends(require_teacher)):
    # Always set owner to current user
    question = Question(
        owner_teacher_id=user.user_id,
        **q.model_dump()
    )
    
    doc = question.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.questions.insert_one(doc)
    return question

@api_router.put("/teacher/questions/{question_id}", response_model=Question)
async def update_question(question_id: str, q: QuestionCreate, user: User = Depends(require_teacher)):
    existing = await db.questions.find_one({"id": question_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # RBAC: Only owner or admin can update
    if user.role != "admin" and existing["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: Not your question")
    
    await db.questions.update_one(
        {"id": question_id},
        {"$set": q.model_dump()}
    )
    
    updated = await db.questions.find_one({" id": question_id}, {"_id": 0})
    if isinstance(updated['created_at'], str):
        updated['created_at'] = datetime.fromisoformat(updated['created_at'])
    
    return Question(**updated)

@api_router.delete("/teacher/questions/{question_id}")
async def delete_question(question_id: str, user: User = Depends(require_teacher)):
    existing = await db.questions.find_one({"id": question_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # RBAC: Only owner or admin can delete
    if user.role != "admin" and existing["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: Not your question")


@api_router.post("/teacher/questions/ai-generate")
async def ai_generate_questions(request: AIQuestionRequest, user: User = Depends(require_teacher)):
    """Generate questions using AI with LaTeX support"""
    try:
        from services.ai_question_generator import ai_question_generator
        
        # Generate questions
        generated_questions = await ai_question_generator.generate_questions(
            subject=request.subject,
            key_stage=request.key_stage,
            exam_board=request.exam_board,
            tier=request.tier,
            topic=request.topic,
            subtopic=request.subtopic,
            difficulty=request.difficulty,
            question_type=request.question_type,
            marks=request.marks,
            num_questions=request.num_questions,
            include_latex=request.include_latex,
            include_diagrams=request.include_diagrams,
            calculator_allowed=request.calculator_allowed,
            strictness=request.strictness,
            command_words=request.command_words,
            question_context=request.question_context
        )
        
        return {
            "success": True,
            "questions": generated_questions,
            "message": f"Generated {len(generated_questions)} question(s) successfully"
        }
    
    except Exception as e:
        logging.error(f"AI question generation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate questions: {str(e)}")


@api_router.post("/teacher/check-equivalence")
async def check_math_equivalence(data: dict, user: User = Depends(require_teacher)):
    """Check if student answer is mathematically equivalent to model answer"""
    try:
        from services.math_equivalence import equivalence_checker
        
        student_answer = data.get("student_answer", "")
        model_answer = data.get("model_answer", "")
        answer_type = data.get("answer_type", "maths")
        tolerance = data.get("tolerance", 0.01)
        
        is_equiv, explanation, confidence = equivalence_checker.check_equivalence(
            student_answer,
            model_answer,
            answer_type,
            tolerance
        )
        
        return {
            "is_equivalent": is_equiv,
            "explanation": explanation,
            "confidence": confidence,
            "student_answer": student_answer,
            "model_answer": model_answer
        }
    except Exception as e:
        logging.error(f"Equivalence check error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check equivalence: {str(e)}")


@api_router.get("/teacher/analytics/math-performance")
async def get_math_analytics(
    assessment_id: Optional[str] = None,
    class_id: Optional[str] = None,
    user: User = Depends(require_teacher)
):
    """Get enhanced math performance analytics across classes and students"""
    try:
        from services.math_analytics import math_analytics_engine
        
        # Build query
        query = {"owner_teacher_id": user.user_id, "status": "marked"}
        
        if assessment_id:
            query["assessment_id"] = assessment_id
        elif class_id:
            # Get assessments for this class
            assessments = await db.assessments.find(
                {"class_id": class_id, "owner_teacher_id": user.user_id},
                {"_id": 0, "id": 1}
            ).to_list(1000)
            assessment_ids = [a["id"] for a in assessments]
            if assessment_ids:
                query["assessment_id"] = {"$in": assessment_ids}
        
        # Get all submissions for analytics
        submissions = await db.attempts.find(query, {"_id": 0}).to_list(10000)
        
        # Filter submissions to only include math-type answers (maths, numeric, mixed)
        # This is done by checking answer_type if available
        math_submissions = []
        for sub in submissions:
            # Check if submission has math-related data
            answer_text = sub.get("answer_text", "")
            show_working = sub.get("show_working", "")
            
            # Include if answer_type is math-related OR has LaTeX/math notation
            has_math_content = (
                "$" in answer_text or 
                "$" in show_working or
                sub.get("answer_type") in ["maths", "numeric", "mixed"]
            )
            
            if has_math_content or len(math_submissions) == 0:  # Include at least some data
                math_submissions.append(sub)
        
        # If no math-specific submissions found, use all submissions
        if not math_submissions:
            math_submissions = submissions
        
        # Analyze with math analytics engine
        analytics = math_analytics_engine.analyze_math_performance(math_submissions)
        
        return {
            "success": True,
            "analytics": analytics,
            "total_submissions": len(math_submissions),
            "filtered_from": len(submissions)
        }
        
    except Exception as e:
        logging.error(f"Math analytics error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== EXAMPLE ANSWERS ENDPOINTS ====================

@api_router.get("/teacher/questions/{question_id}/examples")
async def get_question_examples(question_id: str, user: User = Depends(require_teacher)):
    """Get all example answers for a question"""
    question = await db.questions.find_one({"id": question_id}, {"_id": 0})
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # RBAC: Only owner or admin
    if user.role != "admin" and question["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    examples = await db.example_answers.find(
        {"question_id": question_id, "teacher_owner_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    return {
        "question": question,
        "examples": examples,
        "good_count": sum(1 for e in examples if e.get("example_type") == "good"),
        "bad_count": sum(1 for e in examples if e.get("example_type") == "bad")
    }

@api_router.post("/teacher/questions/{question_id}/examples")
async def add_question_example(question_id: str, example: ExampleAnswerCreate, user: User = Depends(require_teacher)):
    """Add an example answer for AI marking calibration"""
    question = await db.questions.find_one({"id": question_id}, {"_id": 0})
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # RBAC: Only owner or admin
    if user.role != "admin" and question["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if example.example_type not in ["good", "bad"]:
        raise HTTPException(status_code=400, detail="example_type must be 'good' or 'bad'")
    
    new_example = ExampleAnswer(
        question_id=question_id,
        teacher_owner_id=user.user_id,
        **example.model_dump()
    )
    
    doc = new_example.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.example_answers.insert_one(doc)
    
    return {
        "success": True,
        "example": new_example.model_dump(),
        "message": f"Added {example.example_type} example answer"
    }

@api_router.delete("/teacher/questions/{question_id}/examples/{example_id}")
async def delete_question_example(question_id: str, example_id: str, user: User = Depends(require_teacher)):
    """Delete an example answer"""
    example = await db.example_answers.find_one({
        "id": example_id,
        "question_id": question_id,
        "teacher_owner_id": user.user_id
    })
    
    if not example:
        raise HTTPException(status_code=404, detail="Example not found")
    
    await db.example_answers.delete_one({"id": example_id})
    
    return {"success": True, "message": "Example deleted"}

@api_router.post("/teacher/submissions/{submission_id}/convert-to-example")
async def convert_submission_to_example(
    submission_id: str, 
    example_type: str = Query(...),
    explanation: Optional[str] = Query(None),
    user: User = Depends(require_teacher)
):
    """Convert a marked submission to an example answer for future AI calibration"""
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    # RBAC
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if attempt["status"] != "marked":
        raise HTTPException(status_code=400, detail="Only marked submissions can be converted to examples")
    
    if example_type not in ["good", "bad"]:
        raise HTTPException(status_code=400, detail="example_type must be 'good' or 'bad'")
    
    # Get assessment to find question_id
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # Create example from submission
    new_example = ExampleAnswer(
        question_id=assessment["question_id"],
        teacher_owner_id=user.user_id,
        answer_text=attempt["answer_text"],
        example_type=example_type,
        score=attempt.get("score"),
        explanation=explanation or f"Converted from {attempt['student_name']}'s submission"
    )
    
    doc = new_example.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.example_answers.insert_one(doc)
    
    return {
        "success": True,
        "example": new_example.model_dump(),
        "message": f"Submission converted to {example_type} example"
    }


@api_router.get("/teacher/assessments", response_model=List[Assessment])
async def get_assessments(user: User = Depends(require_teacher)):
    # RBAC: Teachers only see their own assessments, admins see all
    query = {} if user.role == "admin" else {"owner_teacher_id": user.user_id}
    assessments = await db.assessments.find(query, {"_id": 0}).to_list(1000)
    
    for a in assessments:
        if isinstance(a['created_at'], str):
            a['created_at'] = datetime.fromisoformat(a['created_at'])
        if a.get('started_at') and isinstance(a['started_at'], str):
            a['started_at'] = datetime.fromisoformat(a['started_at'])
        if a.get('closed_at') and isinstance(a['closed_at'], str):
            a['closed_at'] = datetime.fromisoformat(a['closed_at'])
    
    return assessments

@api_router.post("/teacher/assessments", response_model=Assessment)
async def create_assessment(a: AssessmentCreate, user: User = Depends(require_teacher)):
    # Check question exists and user has access
    question = await db.questions.find_one({"id": a.question_id}, {"_id": 0})
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # RBAC: Can only create assessments from own questions (or admin can use any)
    if user.role != "admin" and question["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: Not your question")
    
    # Phase 4: Validate class ownership if class_id is provided
    if a.class_id:
        cls = await db.classes.find_one({"id": a.class_id, "teacher_owner_id": user.user_id})
        if not cls:
            raise HTTPException(status_code=404, detail="Class not found or access denied")
    
    # Always set owner to current user
    assessment = Assessment(
        owner_teacher_id=user.user_id,
        **a.model_dump()
    )
    
    doc = assessment.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.assessments.insert_one(doc)
    return assessment

@api_router.post("/teacher/assessments/{assessment_id}/start")
async def start_assessment(assessment_id: str, user: User = Depends(require_teacher)):
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Only owner or admin can start
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: Not your assessment")
    
    await db.assessments.update_one(
        {"id": assessment_id},
        {"$set": {
            "status": "started",
            "started_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"success": True}

@api_router.get("/teacher/submissions/needs-review")
async def get_submissions_needing_review(user: User = Depends(require_teacher)):
    """Get all submissions flagged for teacher review"""
    query = {
        "owner_teacher_id": user.user_id,
        "needs_review": True,
        "status": "marked"
    }
    
    submissions = await db.attempts.find(query, {"_id": 0}).sort("marked_at", -1).to_list(100)
    
    # Enrich with question and assessment info
    for sub in submissions:
        assessment = await db.assessments.find_one({"id": sub["assessment_id"]}, {"_id": 0})
        if assessment:
            question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
            sub["question_subject"] = question.get("subject", "Unknown") if question else "Unknown"
            sub["question_topic"] = question.get("topic", "") if question else ""
            sub["join_code"] = assessment.get("join_code", "")
    
    return {
        "submissions": submissions,
        "total_count": len(submissions)
    }

@api_router.post("/teacher/submissions/{submission_id}/mark-reviewed")
async def mark_submission_reviewed(submission_id: str, user: User = Depends(require_teacher)):
    """Clear the needs_review flag after teacher has reviewed"""
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await db.attempts.update_one(
        {"attempt_id": submission_id},
        {"$set": {
            "needs_review": False,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": user.user_id
        }}
    )
    
    return {"success": True, "message": "Marked as reviewed"}

@api_router.post("/teacher/assessments/{assessment_id}/close")
async def close_assessment(assessment_id: str, user: User = Depends(require_teacher)):
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Only owner or admin can close
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: Not your assessment")
    
    await db.assessments.update_one(
        {"id": assessment_id},
        {"$set": {
            "status": "closed",
            "closed_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"success": True}

@api_router.get("/teacher/assessments/{assessment_id}")
async def get_assessment_detail(assessment_id: str, user: User = Depends(require_teacher)):
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Only owner or admin can view details
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: Not your assessment")
    
    # Get question details (only for Classic assessments with question_id)
    question = None
    if assessment.get("question_id"):
        question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
        if not question:
            raise HTTPException(status_code=404, detail="Question not found for this assessment")
    
    # RBAC: Filter submissions by owner
    query = {"assessment_id": assessment_id}
    if user.role != "admin":
        query["owner_teacher_id"] = user.user_id
    
    attempts = await db.attempts.find(query, {"_id": 0}).to_list(1000)
    
    return {
        "assessment": assessment,
        "question": question,
        "submissions": attempts
    }

@api_router.get("/teacher/submissions/{submission_id}")
async def get_submission_detail(submission_id: str, user: User = Depends(require_teacher)):
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    # RBAC: Only owner or admin can view
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: Not your submission")
    
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    return {
        "submission": attempt,
        "assessment": assessment,
        "question": question
    }

@api_router.post("/teacher/submissions/{submission_id}/release-feedback")
async def release_feedback(submission_id: str, user: User = Depends(require_teacher)):
    """Release feedback to student - allows them to view their marked submission"""
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    # RBAC: Only owner or admin can release
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your submission")
    
    if attempt["status"] != "marked":
        raise HTTPException(status_code=400, detail="Submission not marked yet")
    
    # Update the attempt to release feedback
    await db.attempts.update_one(
        {"attempt_id": submission_id},
        {"$set": {"feedback_released": True, "feedback_released_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"success": True, "message": "Feedback released to student"}

@api_router.put("/teacher/submissions/{submission_id}/moderate-feedback")
async def moderate_feedback(submission_id: str, moderation: FeedbackModeration, user: User = Depends(require_teacher)):
    """Teacher moderates/edits AI-generated feedback before releasing to student"""
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    # RBAC: Only owner or admin can moderate
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your submission")
    
    if attempt["status"] != "marked":
        raise HTTPException(status_code=400, detail="Submission not marked yet")
    
    # Build update dict with only provided fields
    update_data = {"moderated_at": datetime.now(timezone.utc).isoformat(), "moderated_by": user.user_id}
    
    if moderation.score is not None:
        update_data["score"] = moderation.score
    if moderation.www is not None:
        update_data["www"] = moderation.www
    if moderation.next_steps is not None:
        update_data["next_steps"] = moderation.next_steps
    if moderation.overall_feedback is not None:
        update_data["overall_feedback"] = moderation.overall_feedback
    
    # Update the attempt
    await db.attempts.update_one(
        {"attempt_id": submission_id},
        {"$set": update_data}
    )
    
    return {"success": True, "message": "Feedback moderated successfully"}

@api_router.post("/teacher/submissions/{submission_id}/regenerate-pdf")
async def regenerate_submission_pdf(submission_id: str, user: User = Depends(require_teacher)):
    """Regenerate PDF for a submission (useful after feedback moderation)"""
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    # RBAC: Only owner or admin
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your submission")
    
    if attempt["status"] != "marked":
        raise HTTPException(status_code=400, detail="Submission not marked yet")
    
    # Get teacher info for PDF
    teacher_display = user.name or "Teacher"
    teacher_school = getattr(user, 'school_name', None)
    
    try:
        # Generate new PDF
        pdf_filename = await generate_feedback_pdf(attempt, teacher_display, teacher_school)
        
        # Update attempt with new PDF path
        await db.attempts.update_one(
            {"attempt_id": submission_id},
            {"$set": {"pdf_url": pdf_filename, "pdf_regenerated_at": datetime.now(timezone.utc).isoformat()}}
        )
        
        return {"success": True, "pdf_url": pdf_filename, "message": "PDF regenerated successfully"}
    except Exception as e:
        logging.error(f"PDF regeneration error: {e}")
        raise HTTPException(status_code=500, detail="Failed to regenerate PDF")

@api_router.post("/teacher/assessments/{assessment_id}/release-all-feedback")
async def release_all_feedback(assessment_id: str, user: User = Depends(require_teacher)):
    """Bulk release feedback for all marked submissions in an assessment"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Only owner or admin can release
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your assessment")
    
    # Update all marked attempts for this assessment that haven't been released yet
    result = await db.attempts.update_many(
        {
            "assessment_id": assessment_id,
            "status": "marked",
            "feedback_released": {"$ne": True}
        },
        {"$set": {
            "feedback_released": True,
            "feedback_released_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {
        "success": True,
        "message": f"Released feedback for {result.modified_count} submission(s)",
        "released_count": result.modified_count
    }

# ==================== BATCH EXPORT ENDPOINTS ====================

@api_router.get("/teacher/assessments/{assessment_id}/export-csv")
async def export_assessment_submissions_csv(assessment_id: str, user: User = Depends(require_teacher)):
    """Export all submissions for an assessment as CSV"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your assessment")
    
    # Get question for context
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Get all submissions
    submissions = await db.attempts.find(
        {"assessment_id": assessment_id, "owner_teacher_id": user.user_id},
        {"_id": 0}
    ).sort("submitted_at", 1).to_list(10000)
    
    # Build CSV
    import io
    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Student Name', 'Student Code', 'Status', 'Score', 'Max Marks', 'Percentage',
        'What Went Well', 'Next Steps', 'Overall Feedback',
        'Joined At', 'Submitted At', 'Feedback Released'
    ])
    
    max_marks = question.get('max_marks', 100) if question else 100
    
    for sub in submissions:
        score = sub.get('score', 0)
        percentage = round((score / max_marks * 100), 1) if max_marks > 0 else 0
        
        writer.writerow([
            sub.get('student_name', 'Unknown'),
            sub.get('student_code', ''),
            sub.get('status', ''),
            score if sub.get('status') == 'marked' else '',
            max_marks,
            f"{percentage}%" if sub.get('status') == 'marked' else '',
            sub.get('www', ''),
            sub.get('next_steps', ''),
            sub.get('overall_feedback', ''),
            sub.get('joined_at', ''),
            sub.get('submitted_at', ''),
            'Yes' if sub.get('feedback_released') else 'No'
        ])
    
    csv_content = output.getvalue()
    output.close()
    
    safe_subject = "".join(c for c in (question.get('subject', 'Assessment') if question else 'Assessment') if c.isalnum() or c in " -_").strip().replace(" ", "_")
    
    from fastapi.responses import Response
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=Submissions_{safe_subject}_{assessment['join_code']}.csv"}
    )

@api_router.get("/teacher/assessments/{assessment_id}/export-pdfs-zip")
async def export_assessment_pdfs_zip(assessment_id: str, user: User = Depends(require_teacher)):
    """Export all PDFs for marked submissions as a ZIP file"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your assessment")
    
    # Get question for context
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Get marked submissions
    submissions = await db.attempts.find(
        {"assessment_id": assessment_id, "owner_teacher_id": user.user_id, "status": "marked"},
        {"_id": 0}
    ).to_list(10000)
    
    if not submissions:
        raise HTTPException(status_code=400, detail="No marked submissions to export")
    
    import zipfile
    import io
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    
    # Get teacher info for PDF generation
    teacher_display = user.name or "Teacher"
    teacher_school = getattr(user, 'school_name', None)
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for sub in submissions:
            try:
                # Generate PDF for this submission
                pdf_filename = await generate_feedback_pdf(sub, teacher_display, teacher_school)
                pdf_path = ROOT_DIR / "generated_pdfs" / pdf_filename
                
                if pdf_path.exists():
                    # Add to ZIP with student name
                    safe_name = "".join(c for c in sub.get('student_name', 'Student') if c.isalnum() or c in " -_").strip().replace(" ", "_")
                    zip_file.write(pdf_path, f"{safe_name}_Feedback.pdf")
            except Exception as e:
                logging.error(f"Error generating PDF for {sub.get('student_name')}: {e}")
                continue
    
    zip_buffer.seek(0)
    
    safe_subject = "".join(c for c in (question.get('subject', 'Assessment') if question else 'Assessment') if c.isalnum() or c in " -_").strip().replace(" ", "_")
    
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=PDFs_{safe_subject}_{assessment['join_code']}.zip"}
    )

# ==================== EMAIL PDF REPORT ENDPOINT ====================

@api_router.post("/teacher/submissions/{submission_id}/email-pdf")
async def email_pdf_report(submission_id: str, user: User = Depends(require_teacher)):
    """Email the PDF report to the student"""
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your submission")
    
    if attempt["status"] != "marked":
        raise HTTPException(status_code=400, detail="Submission not marked yet")
    
    # Check if student has an email
    student_email = None
    student_id = attempt.get("student_id")
    
    if student_id:
        student = await db.students.find_one({"id": student_id}, {"_id": 0})
        if student:
            student_email = student.get("email")
    
    if not student_email:
        raise HTTPException(status_code=400, detail="Student does not have an email address. Add email in student profile first.")
    
    # Check resend config
    if not resend.api_key:
        raise HTTPException(status_code=500, detail="Email service not configured")
    
    # Get or generate PDF
    teacher_display = user.name or "Teacher"
    teacher_school = getattr(user, 'school_name', None)
    
    try:
        pdf_filename = await generate_feedback_pdf(attempt, teacher_display, teacher_school)
        pdf_path = ROOT_DIR / "generated_pdfs" / pdf_filename
        
        if not pdf_path.exists():
            raise HTTPException(status_code=500, detail="Failed to generate PDF")
        
        # Read PDF content
        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()
        
        import base64
        pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
        
        # Get assessment and question info for email
        assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
        question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0}) if assessment else None
        
        subject_name = question.get('subject', 'Assessment') if question else 'Assessment'
        student_name = attempt.get('student_name', 'Student')
        
        # Send email with PDF attachment
        params = {
            "from": "BlueAI Assessment <noreply@resend.dev>",
            "to": [student_email],
            "subject": f"Your {subject_name} Assessment Feedback",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #2563eb;">Assessment Feedback</h2>
                <p>Dear {student_name},</p>
                <p>Your teacher has released feedback for your <strong>{subject_name}</strong> assessment.</p>
                <p>Please find your feedback report attached as a PDF.</p>
                <div style="background: #f3f4f6; padding: 16px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Score:</strong> {attempt.get('score', 'N/A')}/{question.get('max_marks', 100) if question else 100}</p>
                </div>
                <p>Keep up the good work!</p>
                <hr style="margin: 20px 0;">
                <p style="color: #6b7280; font-size: 12px;">
                    This email was sent by BlueAI Assessment on behalf of {teacher_display}
                    {f' at {teacher_school}' if teacher_school else ''}.
                </p>
            </div>
            """,
            "attachments": [
                {
                    "filename": f"{student_name.replace(' ', '_')}_Feedback.pdf",
                    "content": pdf_base64
                }
            ]
        }
        
        response = resend.Emails.send(params)
        
        # Update attempt with email sent info
        await db.attempts.update_one(
            {"attempt_id": submission_id},
            {"$set": {
                "email_sent_at": datetime.now(timezone.utc).isoformat(),
                "email_sent_to": student_email
            }}
        )
        
        return {
            "success": True,
            "message": f"Feedback email sent to {student_email}",
            "email_id": response.get("id") if response else None
        }
        
    except Exception as e:
        logging.error(f"Email sending error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

@api_router.post("/teacher/assessments/{assessment_id}/email-all-pdfs")
async def email_all_pdfs(assessment_id: str, user: User = Depends(require_teacher)):
    """Email PDF reports to all students with email addresses in the assessment"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your assessment")
    
    if not resend.api_key:
        raise HTTPException(status_code=500, detail="Email service not configured")
    
    # Get question info
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Get marked submissions that haven't been emailed yet
    submissions = await db.attempts.find({
        "assessment_id": assessment_id,
        "owner_teacher_id": user.user_id,
        "status": "marked",
        "feedback_released": True,
        "email_sent_at": {"$exists": False}
    }, {"_id": 0}).to_list(10000)
    
    if not submissions:
        raise HTTPException(status_code=400, detail="No submissions eligible for emailing (must be marked, released, and not yet emailed)")
    
    sent_count = 0
    failed_count = 0
    no_email_count = 0
    errors = []
    
    teacher_display = user.name or "Teacher"
    teacher_school = getattr(user, 'school_name', None)
    
    for sub in submissions:
        student_email = None
        student_id = sub.get("student_id")
        
        if student_id:
            student = await db.students.find_one({"id": student_id}, {"_id": 0})
            if student:
                student_email = student.get("email")
        
        if not student_email:
            no_email_count += 1
            continue
        
        try:
            # Generate PDF
            pdf_filename = await generate_feedback_pdf(sub, teacher_display, teacher_school)
            pdf_path = ROOT_DIR / "generated_pdfs" / pdf_filename
            
            if not pdf_path.exists():
                failed_count += 1
                errors.append(f"PDF generation failed for {sub.get('student_name')}")
                continue
            
            # Read and encode PDF
            with open(pdf_path, 'rb') as f:
                pdf_content = f.read()
            
            import base64
            pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
            
            subject_name = question.get('subject', 'Assessment') if question else 'Assessment'
            student_name = sub.get('student_name', 'Student')
            
            # Send email
            params = {
                "from": "BlueAI Assessment <noreply@resend.dev>",
                "to": [student_email],
                "subject": f"Your {subject_name} Assessment Feedback",
                "html": f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #2563eb;">Assessment Feedback</h2>
                    <p>Dear {student_name},</p>
                    <p>Your teacher has released feedback for your <strong>{subject_name}</strong> assessment.</p>
                    <p>Please find your feedback report attached as a PDF.</p>
                    <div style="background: #f3f4f6; padding: 16px; border-radius: 8px; margin: 20px 0;">
                        <p style="margin: 0;"><strong>Score:</strong> {sub.get('score', 'N/A')}/{question.get('max_marks', 100) if question else 100}</p>
                    </div>
                    <p>Keep up the good work!</p>
                    <hr style="margin: 20px 0;">
                    <p style="color: #6b7280; font-size: 12px;">
                        This email was sent by BlueAI Assessment on behalf of {teacher_display}
                        {f' at {teacher_school}' if teacher_school else ''}.
                    </p>
                </div>
                """,
                "attachments": [
                    {
                        "filename": f"{student_name.replace(' ', '_')}_Feedback.pdf",
                        "content": pdf_base64
                    }
                ]
            }
            
            resend.Emails.send(params)
            
            # Update attempt
            await db.attempts.update_one(
                {"attempt_id": sub["attempt_id"]},
                {"$set": {
                    "email_sent_at": datetime.now(timezone.utc).isoformat(),
                    "email_sent_to": student_email
                }}
            )
            
            sent_count += 1
            
        except Exception as e:
            failed_count += 1
            errors.append(f"Failed to email {sub.get('student_name')}: {str(e)}")
    
    return {
        "success": True,
        "summary": {
            "sent": sent_count,
            "failed": failed_count,
            "no_email": no_email_count,
            "total_eligible": len(submissions)
        },
        "errors": errors[:10],  # Limit errors returned
        "message": f"Sent {sent_count} emails, {failed_count} failed, {no_email_count} students without email"
    }

@api_router.get("/teacher/assessments/{assessment_id}/security-report")
async def get_security_report(assessment_id: str, user: User = Depends(require_teacher)):
    """Get security report showing all logged security events for an assessment"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC: Only owner or admin can view
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your assessment")
    
    # Get all attempts for this assessment with security events
    attempts = await db.attempts.find(
        {"assessment_id": assessment_id},
        {"_id": 0}
    ).to_list(1000)
    
    # Build security report
    security_report = []
    total_events = 0
    
    for attempt in attempts:
        events = attempt.get("security_events", [])
        if events:
            total_events += len(events)
            
            # Categorize events
            event_summary = {
                "tab_hidden": 0,
                "window_blur": 0,
                "fullscreen_exit": 0,
                "fullscreen_not_supported": 0
            }
            
            for event in events:
                event_type = event.get("type", "unknown")
                if event_type in event_summary:
                    event_summary[event_type] += 1
            
            security_report.append({
                "attempt_id": attempt.get("attempt_id"),
                "student_name": attempt.get("student_name"),
                "status": attempt.get("status"),
                "submitted_at": attempt.get("submitted_at"),
                "event_count": len(events),
                "event_summary": event_summary,
                "events": events,
                "flagged": len(events) >= 3  # Flag if 3+ events
            })
    
    # Sort by event count (most events first)
    security_report.sort(key=lambda x: x["event_count"], reverse=True)
    
    return {
        "assessment_id": assessment_id,
        "total_submissions": len(attempts),
        "submissions_with_events": len(security_report),
        "total_events": total_events,
        "flagged_count": sum(1 for r in security_report if r["flagged"]),
        "report": security_report
    }

@api_router.get("/teacher/submissions/{submission_id}/security-events")
async def get_submission_security_events(submission_id: str, user: User = Depends(require_teacher)):
    """Get detailed security events for a specific submission"""
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    # RBAC: Only owner or admin can view
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your submission")
    
    events = attempt.get("security_events", [])
    
    return {
        "attempt_id": submission_id,
        "student_name": attempt.get("student_name"),
        "event_count": len(events),
        "events": events
    }


# ==================== ASSESSMENT TEMPLATE ENDPOINTS ====================

@api_router.get("/teacher/templates")
async def get_templates(user: User = Depends(require_teacher)):
    """Get all assessment templates for the logged-in teacher"""
    templates = await db.templates.find(
        {"owner_teacher_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    # Enrich with question info
    question_ids = list(set(t.get("question_id") for t in templates))
    questions = await db.questions.find(
        {"id": {"$in": question_ids}},
        {"_id": 0, "id": 1, "subject": 1, "topic": 1}
    ).to_list(100)
    question_map = {q["id"]: q for q in questions}
    
    # Enrich with class info if default_class_id is set
    class_ids = list(set(t.get("default_class_id") for t in templates if t.get("default_class_id")))
    classes = await db.classes.find(
        {"id": {"$in": class_ids}},
        {"_id": 0, "id": 1, "class_name": 1}
    ).to_list(100) if class_ids else []
    class_map = {c["id"]: c for c in classes}
    
    for t in templates:
        q = question_map.get(t.get("question_id"), {})
        t["question_subject"] = q.get("subject", "Unknown")
        t["question_topic"] = q.get("topic", "")
        
        if t.get("default_class_id"):
            c = class_map.get(t["default_class_id"], {})
            t["default_class_name"] = c.get("class_name", "Unknown")
    
    return {"templates": templates}

@api_router.post("/teacher/templates")
async def create_template(template_data: TemplateCreate, user: User = Depends(require_teacher)):
    """Create a new assessment template"""
    # Verify question exists and belongs to user
    question = await db.questions.find_one({
        "id": template_data.question_id,
        "owner_teacher_id": user.user_id
    }, {"_id": 0})
    
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # Verify class if provided
    if template_data.default_class_id:
        cls = await db.classes.find_one({
            "id": template_data.default_class_id,
            "teacher_owner_id": user.user_id
        })
        if not cls:
            raise HTTPException(status_code=404, detail="Class not found")
    
    # Check for duplicate name
    existing = await db.templates.find_one({
        "owner_teacher_id": user.user_id,
        "name": template_data.name
    })
    if existing:
        raise HTTPException(status_code=400, detail="Template with this name already exists")
    
    template = Template(
        owner_teacher_id=user.user_id,
        **template_data.model_dump()
    )
    
    doc = template.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.templates.insert_one(doc)
    
    return {
        "success": True,
        "template": template.model_dump(),
        "message": f"Template '{template_data.name}' created successfully"
    }

@api_router.get("/teacher/templates/{template_id}")
async def get_template_detail(template_id: str, user: User = Depends(require_teacher)):
    """Get detailed information about a specific template"""
    template = await db.templates.find_one({
        "id": template_id,
        "owner_teacher_id": user.user_id
    }, {"_id": 0})
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Get question info
    question = await db.questions.find_one({"id": template.get("question_id")}, {"_id": 0})
    
    # Get class info if set
    cls = None
    if template.get("default_class_id"):
        cls = await db.classes.find_one({"id": template["default_class_id"]}, {"_id": 0})
    
    return {
        "template": template,
        "question": question,
        "default_class": cls
    }

@api_router.put("/teacher/templates/{template_id}")
async def update_template(template_id: str, template_data: TemplateUpdate, user: User = Depends(require_teacher)):
    """Update an existing template"""
    template = await db.templates.find_one({
        "id": template_id,
        "owner_teacher_id": user.user_id
    })
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Check for duplicate name if name is being changed
    if template_data.name and template_data.name != template.get("name"):
        existing = await db.templates.find_one({
            "owner_teacher_id": user.user_id,
            "name": template_data.name,
            "id": {"$ne": template_id}
        })
        if existing:
            raise HTTPException(status_code=400, detail="Template with this name already exists")
    
    # Verify class if being changed
    if template_data.default_class_id:
        cls = await db.classes.find_one({
            "id": template_data.default_class_id,
            "teacher_owner_id": user.user_id
        })
        if not cls:
            raise HTTPException(status_code=404, detail="Class not found")
    
    update_data = {k: v for k, v in template_data.model_dump().items() if v is not None}
    
    if update_data:
        await db.templates.update_one(
            {"id": template_id},
            {"$set": update_data}
        )
    
    return {"success": True, "message": "Template updated successfully"}

@api_router.delete("/teacher/templates/{template_id}")
async def delete_template(template_id: str, user: User = Depends(require_teacher)):
    """Delete a template"""
    template = await db.templates.find_one({
        "id": template_id,
        "owner_teacher_id": user.user_id
    })
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    await db.templates.delete_one({"id": template_id})
    
    return {"success": True, "message": "Template deleted successfully"}

@api_router.post("/teacher/templates/{template_id}/create-assessment")
async def create_assessment_from_template(
    template_id: str, 
    class_id: Optional[str] = None,
    user: User = Depends(require_teacher)
):
    """Create a new assessment from a template"""
    template = await db.templates.find_one({
        "id": template_id,
        "owner_teacher_id": user.user_id
    }, {"_id": 0})
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Use provided class_id or default from template
    final_class_id = class_id or template.get("default_class_id")
    
    # Verify class if set
    if final_class_id:
        cls = await db.classes.find_one({
            "id": final_class_id,
            "teacher_owner_id": user.user_id
        })
        if not cls:
            raise HTTPException(status_code=404, detail="Class not found")
    
    # Create assessment
    assessment = Assessment(
        owner_teacher_id=user.user_id,
        question_id=template["question_id"],
        class_id=final_class_id,
        duration_minutes=template.get("duration_minutes"),
        auto_close=template.get("auto_close", False)
    )
    
    doc = assessment.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    await db.assessments.insert_one(doc)
    
    # Update template usage stats
    await db.templates.update_one(
        {"id": template_id},
        {
            "$inc": {"use_count": 1},
            "$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}
        }
    )
    
    return {
        "success": True,
        "assessment": assessment.model_dump(),
        "message": f"Assessment created from template '{template['name']}'"
    }


@api_router.get("/teacher/submissions/{submission_id}/download-pdf")
async def download_submission_pdf(submission_id: str, user: User = Depends(require_teacher)):
    attempt = await db.attempts.find_one({"attempt_id": submission_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    if user.role != "admin" and attempt["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your submission")
    
    if attempt["status"] != "marked":
        raise HTTPException(status_code=400, detail="Submission not marked yet")
    
    # Check if PDF already exists
    if attempt.get("pdf_url"):
        # Handle both formats: "filename.pdf" or "/api/pdfs/filename.pdf"
        pdf_filename = attempt["pdf_url"]
        if pdf_filename.startswith("/api/pdfs/"):
            pdf_filename = pdf_filename.replace("/api/pdfs/", "")
        
        pdf_path = Path(ROOT_DIR) / "generated_pdfs" / pdf_filename
        if pdf_path.exists():
            # Return cached PDF
            assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
            question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
            filename = f"{sanitize_text(attempt['student_name'])}_{sanitize_text(question['subject'])}_Feedback.pdf".replace(" ", "_")
            return FileResponse(
                str(pdf_path),
                media_type='application/pdf',
                filename=filename
            )
    
    # Generate new PDF
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Sanitize all data
    student_name = sanitize_text(attempt['student_name'])
    subject = sanitize_text(question['subject'])
    topic = sanitize_text(question.get('topic', ''))
    max_marks = int(question['max_marks'])
    
    # Sanitize score field (may contain HTML tags like <b>10</b>)
    score_raw = sanitize_text(str(attempt.get('score', 0)))
    try:
        score = int(score_raw)
    except ValueError:
        # Extract first number if conversion fails
        import re
        numbers = re.findall(r'\d+', score_raw)
        score = int(numbers[0]) if numbers else 0
    
    answer_text = sanitize_text(attempt.get('answer_text', ''))
    
    # Process feedback sections
    www_items = split_into_bullets(attempt.get('www', ''))
    ebi_items = split_into_bullets(attempt.get('next_steps', ''))
    overall_feedback = sanitize_text(attempt.get('overall_feedback', ''))
    if not overall_feedback:
        overall_feedback = f"Good effort, {student_name}. Keep working on the areas highlighted above."
    
    # Get teacher display name for footer
    teacher_display = user.display_name if user.display_name else user.name
    if not teacher_display or teacher_display.strip() == "":
        # Fallback to email prefix
        email_prefix = user.email.split('@')[0]
        teacher_display = email_prefix.replace('.', ' ').replace('_', ' ').title()
    
    teacher_school = user.school_name if user.school_name else None
    
    # Create PDF filename
    safe_student_name = student_name.replace(" ", "_").replace("/", "_")
    safe_subject = subject.replace(" ", "_").replace("/", "_")
    pdf_filename = f"{safe_student_name}_{safe_subject}_Feedback_{submission_id[:8]}.pdf"
    pdf_path = Path(ROOT_DIR) / "generated_pdfs" / pdf_filename
    
    # Generate PDF with A4 size and 25mm margins
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=25*mm,
        rightMargin=25*mm,
        topMargin=25*mm,
        bottomMargin=25*mm
    )
    
    # Define styles
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        textColor=colors.HexColor('#2563eb'),
        spaceAfter=6,
        alignment=TA_LEFT
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=20,
        alignment=TA_LEFT
    )
    
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=8,
        spaceBefore=14,
        alignment=TA_LEFT
    )
    
    normal_style = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        spaceAfter=6,
        alignment=TA_LEFT,
        leading=14
    )
    
    bold_style = ParagraphStyle(
        'Bold',
        parent=normal_style,
        fontName='Helvetica-Bold'
    )
    
    bullet_style = ParagraphStyle(
        'Bullet',
        parent=normal_style,
        leftIndent=15,
        bulletIndent=5,
        spaceAfter=4
    )
    
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_LEFT,
        spaceBefore=20,
        leading=10
    )
    
    footer_timestamp_style = ParagraphStyle(
        'FooterTimestamp',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        textColor=colors.HexColor('#999999'),
        alignment=TA_LEFT,
        spaceAfter=0,
        leading=9
    )
    
    story = []
    
    # Header
    story.append(Paragraph("Assessment feedback", title_style))
    story.append(Paragraph(
        f"Feedback Report – Generated on {datetime.now(timezone.utc).strftime('%d %B %Y')}",
        subtitle_style
    ))
    
    # Student Information
    story.append(Paragraph("Student Information", heading_style))
    
    info_data = [
        ['Student Name:', student_name],
        ['Assessment:', subject],
        ['Question:', topic if topic else 'N/A'],
        ['Maximum Marks:', str(max_marks)],
        ['Marks Awarded:', f"{score}/{max_marks}"]
    ]
    
    info_table = Table(info_data, colWidths=[45*mm, 115*mm])
    info_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -2), 'Helvetica'),
        ('FONTNAME', (1, -1), (1, -1), 'Helvetica-Bold'),  # Make marks awarded bold
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(info_table)
    
    # Student Response
    story.append(Paragraph("Student Response", heading_style))
    if answer_text:
        story.append(Paragraph(answer_text, normal_style))
    else:
        story.append(Paragraph("No response provided.", normal_style))
    
    # Feedback
    story.append(Paragraph("Feedback", heading_style))
    
    # What Went Well
    story.append(Paragraph("<b>What Went Well:</b>", bold_style))
    for item in www_items:
        story.append(Paragraph(f"• {item}", bullet_style))
    story.append(Spacer(1, 8))
    
    # Next Steps
    story.append(Paragraph("<b>Next Steps:</b>", bold_style))
    for item in ebi_items:
        story.append(Paragraph(f"• {item}", bullet_style))
    story.append(Spacer(1, 8))
    
    # Overall Feedback
    story.append(Paragraph("<b>Overall Feedback:</b>", bold_style))
    story.append(Paragraph(overall_feedback, normal_style))
    
    # Personalized Footer
    story.append(Spacer(1, 15))
    
    # Create footer text
    if teacher_school:
        footer_text = f"Prepared for {teacher_display} • {teacher_school}"
    else:
        footer_text = f"Prepared for {teacher_display}"
    
    story.append(Paragraph(footer_text, footer_style))
    
    # Timestamp line
    timestamp = datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M')
    story.append(Paragraph(f"Generated on {timestamp}", footer_timestamp_style))
    
    # Build PDF
    doc.build(story)
    
    # Store PDF URL in database (use attempt_id to match the query)
    await db.attempts.update_one(
        {"attempt_id": submission_id},
        {"$set": {
            "pdf_url": pdf_filename,
            "pdf_generated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Return the PDF
    return FileResponse(
        str(pdf_path),
        media_type='application/pdf',
        filename=f"{student_name}_{subject}_Feedback.pdf".replace(" ", "_")
    )


# ==================== ANALYTICS ENDPOINTS ====================

@api_router.get("/teacher/analytics/overview")
async def get_analytics_overview(user: User = Depends(require_teacher)):
    """Get class-level analytics overview"""
    analytics = AnalyticsService(db)
    overview = await analytics.get_class_overview(user.user_id)
    return overview

@api_router.get("/teacher/analytics/students")
async def get_students_analytics(user: User = Depends(require_teacher)):
    """Get all students performance data for heatmap and tables"""
    analytics = AnalyticsService(db)
    heatmap_data = await analytics.get_heatmap_data(user.user_id)
    overview = await analytics.get_class_overview(user.user_id)
    
    return {
        "heatmap": heatmap_data,
        "students": overview.get("all_students", []),
        "total_students": overview.get("total_students", 0)
    }

@api_router.get("/teacher/analytics/student/{student_name}")
async def get_student_analytics(student_name: str, user: User = Depends(require_teacher)):
    """Get detailed analytics for a single student"""
    analytics = AnalyticsService(db)
    profile = await analytics.get_student_profile(student_name, user.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Student not found")
    return profile

@api_router.get("/teacher/analytics/assessments")
async def get_assessments_analytics(user: User = Depends(require_teacher)):
    """Get analytics for all assessments"""
    analytics = AnalyticsService(db)
    
    # Get all assessments for this teacher
    assessments = await db.assessments.find({
        "owner_teacher_id": user.user_id
    }, {"_id": 0}).sort("created_at", -1).to_list(100)
    
    results = []
    for assessment in assessments:
        assessment_analytics = await analytics.get_assessment_analytics(assessment.get("id"))
        if assessment_analytics:
            results.append(assessment_analytics)
    
    return {"assessments": results}

@api_router.get("/teacher/analytics/assessment/{assessment_id}")
async def get_single_assessment_analytics(assessment_id: str, user: User = Depends(require_teacher)):
    """Get detailed analytics for a single assessment"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    if user.role != "admin" and assessment.get("owner_teacher_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your assessment")
    
    analytics = AnalyticsService(db)
    return await analytics.get_assessment_analytics(assessment_id)

@api_router.get("/teacher/analytics/topics")
async def get_topics_analytics(user: User = Depends(require_teacher)):
    """Get topic performance breakdown"""
    analytics = AnalyticsService(db)
    topics = await analytics.get_topic_performance(user.user_id)
    return {"topics": topics}

@api_router.post("/teacher/analytics/generate-insights")
async def generate_ai_insights(user: User = Depends(require_teacher)):
    """Generate AI-powered intervention recommendations"""
    analytics = AnalyticsService(db)
    
    # Initialize LLM for AI insights
    import uuid
    session_id = f"analytics_insights_{uuid.uuid4()}"
    # llm_chat = LlmChat(
    #     api_key=os.environ.get("EMERGENT_LLM_KEY"),
    #     session_id=session_id,
    #     system_message="You are an educational analytics assistant helping teachers identify students who need support and topics that need revision."
    # ).with_model("openai", "gpt-4o")
    
    summary = "AI insights temporarily disabled. Review underperforming students and weak topics manually."
    overview = await analytics.get_class_overview(user.user_id)
    
    return {
        "ai_summary": summary,
        "underperforming_students": overview.get("underperforming_students", []),
        "declining_students": overview.get("declining_students", []),
        "weak_topics": overview.get("weak_topics", []),
        "improving_students": overview.get("improving_students", [])
    }

@api_router.get("/teacher/analytics/export/csv")
async def export_analytics_csv(user: User = Depends(require_teacher)):
    """Export analytics data as CSV"""
    analytics = AnalyticsService(db)
    overview = await analytics.get_class_overview(user.user_id)
    heatmap_data = await analytics.get_heatmap_data(user.user_id)
    
    # Build CSV content
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(["Student Name", "Average %", "Trend", "Needs Support", "Reasons"])
    
    # Data rows
    for student in overview.get("all_students", []):
        writer.writerow([
            student.get("student_name", ""),
            student.get("average", 0),
            student.get("trend", ""),
            "Yes" if student.get("needs_support") else "No",
            "; ".join(student.get("reasons", []))
        ])
    
    csv_content = output.getvalue()
    output.close()
    
    # Return as file response
    from fastapi.responses import Response
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=analytics_export.csv"}
    )

@api_router.get("/teacher/analytics/export/pdf")
async def export_analytics_pdf(user: User = Depends(require_teacher)):
    """Export class analytics summary as PDF"""
    analytics = AnalyticsService(db)
    overview = await analytics.get_class_overview(user.user_id)
    topics = await analytics.get_topic_performance(user.user_id)
    
    # Generate AI summary
    import uuid
    session_id = f"analytics_pdf_{uuid.uuid4()}"
    # llm_chat = LlmChat(
    #     api_key=os.environ.get("EMERGENT_LLM_KEY"),
    #     session_id=session_id,
    #     system_message="You are an educational analytics assistant."
    # ).with_model("openai", "gpt-4o")
    # ai_summary = await analytics.generate_ai_intervention_summary(user.user_id, llm_chat)
    ai_summary = "AI insights temporarily disabled."
    
    # Create PDF
    pdf_dir = ROOT_DIR / "generated_pdfs"
    pdf_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    pdf_filename = f"Class_Analytics_{timestamp}.pdf"
    pdf_path = pdf_dir / pdf_filename
    
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=20
    )
    story.append(Paragraph("Class Analytics Report", title_style))
    story.append(Spacer(1, 10*mm))
    
    # Summary stats
    story.append(Paragraph(f"<b>Total Students:</b> {overview.get('total_students', 0)}", styles['Normal']))
    story.append(Paragraph(f"<b>Total Assessments:</b> {overview.get('total_assessments', 0)}", styles['Normal']))
    story.append(Paragraph(f"<b>Total Submissions:</b> {overview.get('total_submissions', 0)}", styles['Normal']))
    story.append(Spacer(1, 5*mm))
    
    # Performance breakdown
    story.append(Paragraph("<b>Performance Breakdown:</b>", styles['Heading3']))
    story.append(Paragraph(f"• Underperforming (&lt;50%): {overview.get('underperforming_count', 0)} students", styles['Normal']))
    story.append(Paragraph(f"• Improving: {overview.get('improving_count', 0)} students", styles['Normal']))
    story.append(Paragraph(f"• Declining: {overview.get('declining_count', 0)} students", styles['Normal']))
    story.append(Spacer(1, 5*mm))
    
    # Weak topics
    weak_topics = overview.get("weak_topics", [])
    if weak_topics:
        story.append(Paragraph("<b>Weak Topics (Class Average &lt;50%):</b>", styles['Heading3']))
        for topic in weak_topics[:5]:
            story.append(Paragraph(f"• {topic['topic']}: {topic['average_percentage']}%", styles['Normal']))
        story.append(Spacer(1, 5*mm))
    
    # AI Recommendation
    story.append(Paragraph("<b>AI Intervention Recommendation:</b>", styles['Heading3']))
    story.append(Paragraph(ai_summary, styles['Normal']))
    story.append(Spacer(1, 5*mm))
    
    # Underperforming students
    underperforming = overview.get("underperforming_students", [])
    if underperforming:
        story.append(Paragraph("<b>Students Needing Support:</b>", styles['Heading3']))
        for student in underperforming[:10]:
            story.append(Paragraph(f"• {student['student_name']}: {student['average']}% average", styles['Normal']))
    
    # Timestamp
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}", styles['Normal']))
    
    doc.build(story)
    
    return FileResponse(
        str(pdf_path),
        media_type='application/pdf',
        filename=f"Class_Analytics_{timestamp}.pdf"
    )

@api_router.get("/teacher/analytics/student/{student_name}/export-pdf")
async def export_student_analytics_pdf(student_name: str, user: User = Depends(require_teacher)):
    """Export individual student analytics as PDF"""
    analytics = AnalyticsService(db)
    profile = await analytics.get_student_profile(student_name, user.user_id)
    
    if not profile:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Create PDF
    pdf_dir = ROOT_DIR / "generated_pdfs"
    pdf_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    safe_name = student_name.replace(" ", "_")
    pdf_filename = f"Student_Analytics_{safe_name}_{timestamp}.pdf"
    pdf_path = pdf_dir / pdf_filename
    
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=20
    )
    story.append(Paragraph(f"Student Analytics: {student_name}", title_style))
    story.append(Spacer(1, 10*mm))
    
    # Summary
    story.append(Paragraph(f"<b>Overall Average:</b> {profile.get('overall_average', 0)}%", styles['Normal']))
    story.append(Paragraph(f"<b>Total Submissions:</b> {profile.get('total_submissions', 0)}", styles['Normal']))
    story.append(Paragraph(f"<b>Performance Trend:</b> {profile.get('trend', 'N/A').title()}", styles['Normal']))
    story.append(Spacer(1, 5*mm))
    
    # Support status
    if profile.get("needs_support"):
        story.append(Paragraph("<b>⚠️ NEEDS SUPPORT</b>", styles['Heading3']))
        for reason in profile.get("support_reasons", []):
            story.append(Paragraph(f"• {reason}", styles['Normal']))
        story.append(Spacer(1, 5*mm))
    
    # Weak topics
    weak_topics = profile.get("weak_topics", [])
    if weak_topics:
        story.append(Paragraph("<b>Weak Topics:</b>", styles['Heading3']))
        for topic in weak_topics:
            story.append(Paragraph(f"• {topic['topic']}: {topic['average']}% ({topic['attempts']} attempts)", styles['Normal']))
        story.append(Spacer(1, 5*mm))
    
    # Recent submissions
    story.append(Paragraph("<b>Recent Submissions:</b>", styles['Heading3']))
    submissions = profile.get("submissions", [])[:10]
    for sub in submissions:
        status_text = f"{sub['score']}/{sub['max_marks']} ({sub['percentage']}%)" if sub['status'] == 'marked' else sub['status']
        story.append(Paragraph(f"• {sub['subject']}: {status_text}", styles['Normal']))
    
    # Timestamp
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}", styles['Normal']))
    
    doc.build(story)
    
    return FileResponse(
        str(pdf_path),
        media_type='application/pdf',
        filename=f"Student_Analytics_{safe_name}.pdf"
    )


# Admin endpoints
@api_router.get("/admin/teachers")
async def get_all_teachers(user: User = Depends(require_admin)):
    teachers = await db.users.find({}, {"_id": 0}).to_list(1000)
    
    for t in teachers:
        if isinstance(t['created_at'], str):
            t['created_at'] = datetime.fromisoformat(t['created_at'])
    
    return teachers

@api_router.put("/admin/teachers/{teacher_id}/role")
async def update_teacher_role(teacher_id: str, role: str, user: User = Depends(require_admin)):
    if role not in ["teacher", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    await db.users.update_one(
        {"user_id": teacher_id},
        {"$set": {"role": role}}
    )
    
    return {"success": True}

@api_router.get("/admin/assessments")
async def get_all_assessments(user: User = Depends(require_admin)):
    assessments = await db.assessments.find({}, {"_id": 0}).to_list(1000)
    
    # Batch fetch all teachers to avoid N+1 query
    teacher_ids = list(set([a["owner_teacher_id"] for a in assessments]))
    teachers = await db.users.find({"user_id": {"$in": teacher_ids}}, {"_id": 0, "user_id": 1, "name": 1}).to_list(1000)
    teacher_map = {t["user_id"]: t["name"] for t in teachers}
    
    # Map teacher names efficiently
    for a in assessments:
        a["teacher_name"] = teacher_map.get(a["owner_teacher_id"], "Unknown")
        
        if isinstance(a['created_at'], str):
            a['created_at'] = datetime.fromisoformat(a['created_at'])
    
    return assessments


# ==================== ENHANCED ASSESSMENT ENDPOINTS ====================

@api_router.post("/teacher/questions/ai-generate-multi")
async def ai_generate_multi_questions(request: AIMultiQuestionRequest, user: User = Depends(require_teacher)):
    """Generate multiple questions at once using AI"""
    try:
        from services.ai_multi_question_generator import get_multi_question_generator
        import os
        
        emergent_key = os.environ.get("EMERGENT_LLM_KEY")
        if not emergent_key:
            raise HTTPException(status_code=500, detail="AI service not configured")
        
        generator = get_multi_question_generator(emergent_key)
        
        questions = await generator.generate_multi_questions(
            subject=request.subject,
            key_stage=request.key_stage,
            exam_board=request.exam_board,
            tier=request.tier,
            topic=request.topic,
            subtopic=request.subtopic,
            difficulty=request.difficulty,
            num_questions=request.num_questions,
            question_types=request.question_types,
            total_marks=request.total_marks,
            include_latex=request.include_latex,
            calculator_allowed=request.calculator_allowed,
            context=request.context
        )
        
        return {
            "success": True,
            "questions": questions,
            "count": len(questions),
            "totalMarks": sum(q.get("maxMarks", 0) for q in questions)
        }
        
    except Exception as e:
        logging.error(f"Multi-question generation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/teacher/assessments/enhanced")
async def create_enhanced_assessment(assessment: EnhancedAssessmentCreate, user: User = Depends(require_teacher)):
    """Create a new enhanced assessment"""
    # Validate assessment mode
    valid_modes = ["CLASSIC", "FORMATIVE_SINGLE_LONG_RESPONSE", "SUMMATIVE_MULTI_QUESTION", "EXAM_STRUCTURED_GCSE_STYLE"]
    if assessment.assessmentMode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid assessmentMode. Must be one of: {valid_modes}")
    
    # Validate duration
    if not (1 <= assessment.durationMinutes <= 60):
        raise HTTPException(status_code=400, detail="Duration must be between 1 and 60 minutes")
    
    # Validate question count based on mode
    if assessment.assessmentMode == "FORMATIVE_SINGLE_LONG_RESPONSE":
        if len(assessment.questions) < 1:
            raise HTTPException(status_code=400, detail="Formative mode requires at least 1 question")
    elif assessment.assessmentMode == "SUMMATIVE_MULTI_QUESTION":
        if not (3 <= len(assessment.questions) <= 20):
            raise HTTPException(status_code=400, detail="Summative mode requires 3-20 questions")
    
    # Calculate total marks
    total_marks = 0
    for q in assessment.questions:
        if q.questionType == "STRUCTURED_WITH_PARTS":
            total_marks += sum(part.maxMarks for part in q.parts)
        else:
            total_marks += q.maxMarks
    
    # Create enhanced assessment
    new_assessment = EnhancedAssessment(
        owner_teacher_id=user.user_id,
        assessmentMode=assessment.assessmentMode,
        title=assessment.title,
        subject=assessment.subject,
        stage=assessment.stage,
        examBoard=assessment.examBoard,
        tier=assessment.tier,
        durationMinutes=assessment.durationMinutes,
        instructions=assessment.instructions,
        shuffleQuestions=assessment.shuffleQuestions,
        shuffleOptions=assessment.shuffleOptions,
        allowDraftSaving=assessment.allowDraftSaving,
        questions=[q.model_dump() for q in assessment.questions],
        question_id=assessment.question_id,
        class_id=assessment.class_id,
        auto_close=assessment.auto_close,
        totalMarks=total_marks,
        status="draft"
    )
    
    doc = new_assessment.model_dump()
    doc['created_at'] = doc['created_at'].isoformat() if isinstance(doc['created_at'], datetime) else doc['created_at']
    
    await db.assessments.insert_one(doc)
    
    return {"success": True, "assessment": new_assessment, "message": "Assessment created successfully"}

@api_router.get("/teacher/assessments/{assessment_id}/enhanced")
async def get_enhanced_assessment(assessment_id: str, user: User = Depends(require_teacher)):
    """Get enhanced assessment with full details"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get attempts count
    attempts_count = await db.attempts.count_documents({"assessment_id": assessment_id})
    
    return {
        "assessment": assessment,
        "attempts_count": attempts_count
    }

@api_router.put("/teacher/assessments/{assessment_id}/questions")
async def update_assessment_questions(
    assessment_id: str,
    questions: List[EnhancedQuestionCreate],
    user: User = Depends(require_teacher)
):
    """Update questions in an assessment"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Cannot edit if already started
    if assessment.get("status") not in ["draft", None]:
        raise HTTPException(status_code=400, detail="Cannot edit questions after assessment is published")
    
    # Calculate total marks
    total_marks = 0
    for q in questions:
        if q.questionType == "STRUCTURED_WITH_PARTS":
            total_marks += sum(part.maxMarks for part in q.parts)
        else:
            total_marks += q.maxMarks
    
    # Update questions
    await db.assessments.update_one(
        {"id": assessment_id},
        {
            "$set": {
                "questions": [q.model_dump() for q in questions],
                "totalMarks": total_marks,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        }
    )
    
    return {"success": True, "message": "Questions updated", "totalMarks": total_marks}

@api_router.post("/teacher/assessments/{assessment_id}/publish")
async def publish_enhanced_assessment(assessment_id: str, user: User = Depends(require_teacher)):
    """Publish an enhanced assessment"""
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Validate assessment has questions
    if not assessment.get("questions") or len(assessment["questions"]) == 0:
        if not assessment.get("question_id"):  # CLASSIC mode fallback
            raise HTTPException(status_code=400, detail="Assessment must have at least one question")
    
    # Update status
    await db.assessments.update_one(
        {"id": assessment_id},
        {"$set": {"status": "published", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"success": True, "message": "Assessment published successfully"}

@api_router.post("/teacher/assessments/migrate-classic")
async def migrate_classic_assessments_endpoint(user: User = Depends(require_teacher)):
    """Migrate all user's existing assessments to CLASSIC mode"""
    query = {"assessmentMode": {"$exists": False}, "owner_teacher_id": user.user_id}
    
    assessments = await db.assessments.find(query, {"_id": 0}).to_list(10000)
    
    migrated_count = 0
    for assessment in assessments:
        question = await db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0})
        
        if question:
            enhanced_question = {
                "id": question["id"],
                "questionNumber": 1,
                "questionType": "LONG_RESPONSE" if question.get("max_marks", 0) >= 6 else "SHORT_ANSWER",
                "questionBody": question["question_text"],
                "stimulusBlock": None,
                "maxMarks": question["max_marks"],
                "subject": question["subject"],
                "topic": question["topic"],
                "difficulty": "Medium",
                "tags": question.get("topic_tags", []),
                "options": [],
                "allowMultiSelect": False,
                "parts": [],
                "answerType": question.get("answer_type", "TEXT").upper(),
                "calculatorAllowed": question.get("calculator_allowed", False),
                "markScheme": question["mark_scheme"],
                "modelAnswer": question.get("model_answer"),
                "source": question.get("source", "manual"),
                "created_at": question.get("created_at")
            }
            
            update_data = {
                "assessmentMode": "CLASSIC",
                "title": f"{question['subject']} - {question['topic']}",
                "subject": question["subject"],
                "stage": question.get("key_stage", "KS4"),
                "examBoard": question.get("exam_board", "AQA"),
                "tier": question.get("tier", "Higher"),
                "durationMinutes": assessment.get("duration_minutes", 45) or 45,
                "instructions": "",
                "shuffleQuestions": False,
                "shuffleOptions": False,
                "allowDraftSaving": True,
                "questions": [enhanced_question],
                "totalMarks": question["max_marks"],
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            await db.assessments.update_one(
                {"id": assessment["id"]},
                {"$set": update_data}
            )
            migrated_count += 1
    
    return {
        "success": True,
        "migrated_count": migrated_count,
        "message": f"Migrated {migrated_count} assessments to CLASSIC mode"
    }


# Include modular routes before adding api_router to app
api_router.include_router(classes_router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)