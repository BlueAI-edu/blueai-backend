"""
Enhanced Assessment API Endpoints
Supports multi-question assessments, GCSE structured questions, and new assessment modes
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from typing import List, Optional, Dict, Any
import logging
import os
from datetime import datetime, timezone
import json
import base64
from pathlib import Path

from models.assessment_models import (
    EnhancedAssessment, EnhancedAssessmentCreate,
    EnhancedQuestion, EnhancedQuestionCreate,
    QuestionPart, QuestionPartCreate,
    MCQOption, MCQOptionCreate,
    AIMultiQuestionRequest
)

# This will be imported in server.py
enhanced_router = APIRouter()

# ==================== MIGRATION ENDPOINT ====================

async def migrate_classic_assessments(db, user_id: str = None):
    """
    Migrate existing single-question assessments to CLASSIC mode
    Adds assessmentMode field to all existing assessments
    """
    query = {"assessmentMode": {"$exists": False}}
    if user_id:
        query["owner_teacher_id"] = user_id
    
    # Find assessments without assessmentMode
    assessments = await db.assessments.find(query, {"_id": 0}).to_list(10000)
    
    migrated_count = 0
    for assessment in assessments:
        # Get the single question
        question = await db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0})
        
        if question:
            # Create enhanced question from old question
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
            
            # Update assessment with CLASSIC mode
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
    
    return migrated_count

# ==================== ENHANCED ASSESSMENT CRUD ====================

@enhanced_router.post("/teacher/assessments/enhanced")
async def create_enhanced_assessment(assessment: EnhancedAssessmentCreate, db, user):
    """
    Create a new enhanced assessment (Formative, Summative, or GCSE Structured)
    """
    # Validate assessment mode
    valid_modes = ["CLASSIC", "FORMATIVE_SINGLE_LONG_RESPONSE", "SUMMATIVE_MULTI_QUESTION", "EXAM_STRUCTURED_GCSE_STYLE"]
    if assessment.assessmentMode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid assessmentMode. Must be one of: {valid_modes}")
    
    # Validate duration
    if not (30 <= assessment.durationMinutes <= 60):
        raise HTTPException(status_code=400, detail="Duration must be between 30 and 60 minutes")
    
    # Validate question count based on mode
    if assessment.assessmentMode == "FORMATIVE_SINGLE_LONG_RESPONSE":
        if len(assessment.questions) != 1:
            raise HTTPException(status_code=400, detail="Formative mode requires exactly 1 question")
    elif assessment.assessmentMode == "SUMMATIVE_MULTI_QUESTION":
        if not (3 <= len(assessment.questions) <= 20):
            raise HTTPException(status_code=400, detail="Summative mode requires 3-20 questions")
    elif assessment.assessmentMode == "EXAM_STRUCTURED_GCSE_STYLE":
        if len(assessment.questions) < 1:
            raise HTTPException(status_code=400, detail="GCSE mode requires at least 1 structured question")
    
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
        question_id=assessment.question_id,  # For CLASSIC mode
        class_id=assessment.class_id,
        auto_close=assessment.auto_close,
        totalMarks=total_marks,
        status="draft"
    )
    
    doc = new_assessment.model_dump()
    doc['created_at'] = doc['created_at'].isoformat() if isinstance(doc['created_at'], datetime) else doc['created_at']
    
    await db.assessments.insert_one(doc)
    
    return {"success": True, "assessment": new_assessment, "message": "Assessment created successfully"}

@enhanced_router.put("/teacher/assessments/{assessment_id}/questions")
async def update_assessment_questions(
    assessment_id: str,
    questions: List[EnhancedQuestionCreate],
    db,
    user
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

@enhanced_router.post("/teacher/assessments/{assessment_id}/publish")
async def publish_assessment(assessment_id: str, db, user):
    """Publish an assessment (make it available for students)"""
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

# ==================== STIMULUS UPLOAD ====================

@enhanced_router.post("/teacher/assessments/{assessment_id}/upload-stimulus")
async def upload_stimulus(
    assessment_id: str,
    file: UploadFile = File(...),
    question_number: int = Form(...),
    caption: str = Form(""),
    db = None,
    user = None
):
    """
    Upload stimulus image (diagram, circuit, graph) for a question
    """
    assessment = await db.assessments.find_one({"id": assessment_id}, {"_id": 0})
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    # RBAC
    if user.role != "admin" and assessment["owner_teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Validate file type
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/gif", "image/svg+xml"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    
    # Read and encode file
    contents = await file.read()
    
    # Limit file size to 5MB
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be less than 5MB")
    
    # Encode to base64
    base64_image = base64.b64encode(contents).decode('utf-8')
    data_url = f"data:{file.content_type};base64,{base64_image}"
    
    # Create stimulus block
    stimulus_block = {
        "type": "image",
        "content": data_url,
        "caption": caption,
        "filename": file.filename
    }
    
    # Update the specific question
    questions = assessment.get("questions", [])
    question_found = False
    
    for q in questions:
        if q.get("questionNumber") == question_number:
            q["stimulusBlock"] = stimulus_block
            question_found = True
            break
    
    if not question_found:
        raise HTTPException(status_code=404, detail=f"Question {question_number} not found")
    
    # Update assessment
    await db.assessments.update_one(
        {"id": assessment_id},
        {"$set": {"questions": questions, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {
        "success": True,
        "stimulusBlock": stimulus_block,
        "message": "Stimulus uploaded successfully"
    }

# ==================== GET ENHANCED ASSESSMENT ====================

@enhanced_router.get("/teacher/assessments/{assessment_id}/enhanced")
async def get_enhanced_assessment(assessment_id: str, db, user):
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
