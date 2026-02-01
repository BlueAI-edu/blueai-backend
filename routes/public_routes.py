from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from datetime import datetime, timezone
from pathlib import Path
import uuid
import logging
from models.assessment_models import JoinRequest, SubmitAnswer
from services.marking_service import mark_submission
from services.pdf_service import generate_feedback_pdf, sanitize_text
from utils.database import db

ROOT_DIR = Path(__file__).parent.parent

router = APIRouter(prefix="/public", tags=["public"])

@router.post("/join")
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
    
    # Get question details
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Create attempt
    attempt_id = str(uuid.uuid4())
    attempt = {
        "attempt_id": attempt_id,
        "assessment_id": assessment["id"],
        "owner_teacher_id": assessment["owner_teacher_id"],
        "student_name": join_req.student_name,
        "status": "in_progress",
        "joined_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.attempts.insert_one(attempt)
    
    return {
        "attempt_id": attempt_id,
        "assessment": assessment,
        "question": question
    }

@router.get("/attempt/{attempt_id}")
async def get_attempt(attempt_id: str):
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

@router.get("/attempt/{attempt_id}/download-pdf")
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

@router.post("/attempt/{attempt_id}/submit")
async def submit_attempt(attempt_id: str, submit: SubmitAnswer):
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    if attempt["status"] in ["submitted", "marked"]:
        raise HTTPException(status_code=400, detail="Already submitted")
    
    # Check timer
    assessment = await db.assessments.find_one({"id": attempt["assessment_id"]}, {"_id": 0})
    if assessment.get("duration_minutes") and assessment.get("started_at"):
        started_at = assessment["started_at"]
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        
        elapsed = datetime.now(timezone.utc) - started_at
        if elapsed.total_seconds() / 60 >= assessment["duration_minutes"]:
            raise HTTPException(status_code=400, detail="Time is up")
    
    # Update attempt
    await db.attempts.update_one(
        {"attempt_id": attempt_id},
        {"$set": {
            "answer_text": submit.answer_text,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "status": "submitted"
        }}
    )
    
    # Auto-mark
    try:
        question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
        
        # Mark the submission
        marking_result = await mark_submission(
            question,
            attempt["student_name"],
            submit.answer_text,
            attempt_id
        )
        
        await db.attempts.update_one(
            {"attempt_id": attempt_id},
            {"$set": {
                "score": marking_result["score"],
                "www": marking_result["www"],
                "next_steps": marking_result["next_steps"],
                "overall_feedback": marking_result["overall_feedback"],
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
