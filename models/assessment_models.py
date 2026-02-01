"""
Enhanced Assessment Models for BlueAI Assessment System Upgrade
Supports: Classic, Formative, Summative Multi-Question, and GCSE Structured modes
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid
import random
import string

# ==================== QUESTION PART MODEL (for GCSE Structured) ====================

class QuestionPart(BaseModel):
    """Sub-part of a structured GCSE-style question (e.g., 1a, 1b, 1c)"""
    partLabel: str  # "a", "b", "c", "d", etc.
    partPrompt: str
    maxMarks: int
    answerType: str = "TEXT"  # TEXT, NUMERIC, MATHS, MIXED
    markScheme: str
    partStimulus: Optional[Dict[str, Any]] = None  # Optional per-part stimulus
    correctAnswer: Optional[str] = None  # For auto-marking
    
class QuestionPartCreate(BaseModel):
    """Creation model for question parts"""
    partLabel: str
    partPrompt: str
    maxMarks: int
    answerType: str = "TEXT"
    markScheme: str
    partStimulus: Optional[Dict[str, Any]] = None
    correctAnswer: Optional[str] = None

# ==================== MCQ OPTION MODEL ====================

class MCQOption(BaseModel):
    """Multiple choice question option"""
    label: str  # "A", "B", "C", "D"
    text: str
    isCorrect: bool = False

class MCQOptionCreate(BaseModel):
    label: str
    text: str
    isCorrect: bool = False

# ==================== ENHANCED QUESTION MODEL ====================

class EnhancedQuestion(BaseModel):
    """
    Enhanced question model supporting multiple types:
    - SHORT_ANSWER
    - MULTIPLE_CHOICE
    - MULTI_SELECT
    - NUMERIC
    - LONG_RESPONSE
    - STRUCTURED_WITH_PARTS (GCSE-style)
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    questionNumber: int  # Position in assessment (1, 2, 3...)
    questionType: str  # SHORT_ANSWER, MULTIPLE_CHOICE, MULTI_SELECT, NUMERIC, LONG_RESPONSE, STRUCTURED_WITH_PARTS
    
    # Content
    questionBody: str  # Main question text
    stimulusBlock: Optional[Dict[str, Any]] = None  # Shared stimulus: {type: "text"|"image"|"table", content: str, caption: str}
    
    # Marks
    maxMarks: int  # Auto-calculated for structured questions
    
    # Metadata
    subject: str
    topic: str
    difficulty: Optional[str] = "Medium"  # Easy, Medium, Hard
    tags: Optional[List[str]] = []
    
    # For MCQ
    options: Optional[List[MCQOption]] = []  # A, B, C, D options
    allowMultiSelect: bool = False  # Multi-select allowed?
    
    # For Structured (GCSE)
    parts: Optional[List[QuestionPart]] = []  # Sub-parts: a, b, c...
    
    # Answer configuration
    answerType: str = "TEXT"  # TEXT, NUMERIC, MATHS, MIXED
    calculatorAllowed: bool = False
    
    # Mark scheme
    markScheme: str = ""  # General mark scheme (for non-structured)
    modelAnswer: Optional[str] = None
    
    # AI metadata
    source: str = "manual"  # manual or ai_generated
    quality_score: Optional[int] = None
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class EnhancedQuestionCreate(BaseModel):
    """Creation model for enhanced questions"""
    questionNumber: int
    questionType: str
    questionBody: str
    stimulusBlock: Optional[Dict[str, Any]] = None
    maxMarks: int
    subject: str
    topic: str
    difficulty: Optional[str] = "Medium"
    tags: Optional[List[str]] = []
    options: Optional[List[MCQOptionCreate]] = []
    allowMultiSelect: bool = False
    parts: Optional[List[QuestionPartCreate]] = []
    answerType: str = "TEXT"
    calculatorAllowed: bool = False
    markScheme: str = ""
    modelAnswer: Optional[str] = None
    source: str = "manual"

# ==================== ENHANCED ASSESSMENT MODEL ====================

class EnhancedAssessment(BaseModel):
    """
    Enhanced assessment model supporting multiple modes:
    - CLASSIC (backward compatibility)
    - FORMATIVE_SINGLE_LONG_RESPONSE
    - SUMMATIVE_MULTI_QUESTION
    - EXAM_STRUCTURED_GCSE_STYLE
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_teacher_id: str
    
    # Assessment Mode (NEW)
    assessmentMode: str  # CLASSIC, FORMATIVE_SINGLE_LONG_RESPONSE, SUMMATIVE_MULTI_QUESTION, EXAM_STRUCTURED_GCSE_STYLE
    
    # Basic Info
    title: str
    subject: str
    stage: str  # KS3, KS4, KS5
    examBoard: str  # AQA, Edexcel, OCR, WJEC, CIE, Other
    tier: str  # Foundation, Higher, Intermediate, None
    
    # Duration & Instructions
    durationMinutes: int  # 30-60 minutes range
    instructions: str = ""
    
    # Settings
    shuffleQuestions: bool = False  # Only for SUMMATIVE mode
    shuffleOptions: bool = False  # For MCQs
    allowDraftSaving: bool = True
    
    # Questions
    questions: List[EnhancedQuestion] = []  # Multiple questions for new modes
    
    # Legacy support (for CLASSIC mode)
    question_id: Optional[str] = None  # Single question ID (backward compatibility)
    
    # Marks
    totalMarks: int = 0  # Auto-calculated from questions
    
    # Class linkage
    class_id: Optional[str] = None
    
    # Join code
    join_code: str = Field(default_factory=lambda: ''.join(random.choices(string.ascii_uppercase + string.digits, k=6)))
    
    # Status
    status: str = "draft"  # draft, published, started, closed
    started_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    # Auto-close
    auto_close: bool = False
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

class EnhancedAssessmentCreate(BaseModel):
    """Creation model for enhanced assessments"""
    assessmentMode: str
    title: str
    subject: str
    stage: str
    examBoard: str
    tier: str
    durationMinutes: int
    instructions: str = ""
    shuffleQuestions: bool = False
    shuffleOptions: bool = False
    allowDraftSaving: bool = True
    questions: List[EnhancedQuestionCreate] = []
    question_id: Optional[str] = None  # For CLASSIC mode
    class_id: Optional[str] = None
    auto_close: bool = False

# ==================== STUDENT ATTEMPT MODELS ====================

class PartAnswer(BaseModel):
    """Student's answer to a question part"""
    partLabel: str
    answerText: str
    answerLatex: Optional[str] = None
    showWorking: Optional[str] = None
    marks: Optional[int] = None  # Awarded marks
    feedback: Optional[str] = None

class QuestionAnswer(BaseModel):
    """Student's answer to a complete question"""
    questionId: str
    questionNumber: int
    answerText: Optional[str] = None  # For simple questions
    selectedOptions: Optional[List[str]] = []  # For MCQ (e.g., ["A", "C"])
    partAnswers: Optional[List[PartAnswer]] = []  # For structured questions
    showWorking: Optional[str] = None
    graphData: Optional[Dict[str, Any]] = None  # Phase 3 graph data
    stepByStepData: Optional[List[Dict[str, Any]]] = None  # Phase 3 step-by-step
    marks: Optional[int] = None
    feedback: Optional[str] = None

class EnhancedAttempt(BaseModel):
    """Student attempt for enhanced assessments"""
    attempt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    assessment_id: str
    student_id: Optional[str] = None
    student_name: str
    student_email: Optional[str] = None
    
    # Answers
    answers: List[QuestionAnswer] = []  # All question answers
    
    # Legacy support
    answer_text: Optional[str] = None  # For CLASSIC mode compatibility
    show_working: Optional[str] = None
    
    # Status
    status: str = "in_progress"  # in_progress, submitted, marked
    
    # Timing
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: Optional[datetime] = None
    time_taken_seconds: Optional[int] = None
    
    # Marking
    totalScore: Optional[int] = None
    totalMarks: int = 0
    percentage: Optional[float] = None
    
    # Feedback
    www: Optional[str] = None  # What Went Well
    next_steps: Optional[str] = None  # Even Better If
    overall_feedback: Optional[str] = None
    
    # PDF
    pdf_url: Optional[str] = None
    pdf_generated_at: Optional[datetime] = None
    
    # Security
    security_events: List[Dict[str, Any]] = []
    
    # Teacher ownership
    owner_teacher_id: str
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# ==================== AI MULTI-QUESTION GENERATION ====================

class AIMultiQuestionRequest(BaseModel):
    """Request for AI to generate multiple questions at once"""
    subject: str
    key_stage: str
    exam_board: str
    tier: Optional[str] = None
    topic: str
    subtopic: Optional[str] = None
    difficulty: str = "Medium"
    num_questions: int = 5  # How many questions to generate
    question_types: List[str] = []  # Mix of types, e.g., ["SHORT_ANSWER", "MCQ", "LONG_RESPONSE"]
    total_marks: int = 40  # Target total marks
    include_latex: bool = True
    calculator_allowed: bool = False
    context: str = "mock exam"
