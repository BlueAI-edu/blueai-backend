from pydantic import BaseModel
from typing import Optional

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
