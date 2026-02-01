"""Routes for Classes and Students management - Phase 1, 2 & 3"""
from fastapi import APIRouter, HTTPException, Depends, Response
from typing import Optional, List, Dict, Any
import csv
import io
import logging
import statistics
from datetime import datetime, timezone
import tempfile
from pathlib import Path

from models.classes_models import (
    ClassCreate, ClassUpdate, ClassModel,
    StudentCreate, StudentUpdate, StudentModel,
    CSVImportPreview, CSVImportConfirm
)
from utils.database import db
from utils.dependencies import get_current_user, require_teacher

router = APIRouter(tags=["classes"])

# PDF imports for analytics export
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


# ==================== CLASSES ENDPOINTS ====================

@router.get("/teacher/classes")
async def get_classes(user = Depends(require_teacher)):
    """Get all classes for the logged-in teacher with student counts and stats"""
    classes = await db.classes.find(
        {"teacher_owner_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    # Enrich with student counts and stats
    for cls in classes:
        # Count students
        student_count = await db.students.count_documents({
            "teacher_owner_id": user.user_id,
            "class_id": cls["id"],
            "archived": {"$ne": True}
        })
        cls["student_count"] = student_count
        
        # Get assessment stats for this class
        assessments = await db.assessments.find({
            "teacher_owner_id": user.user_id,
            "class_id": cls["id"]
        }, {"_id": 0, "id": 1, "created_at": 1}).sort("created_at", -1).to_list(10)
        
        cls["assessment_count"] = len(assessments)
        cls["last_assessment_date"] = assessments[0]["created_at"] if assessments else None
        
        # Calculate average score if there are marked submissions
        if assessments:
            assessment_ids = [a["id"] for a in assessments]
            pipeline = [
                {"$match": {
                    "assessment_id": {"$in": assessment_ids},
                    "status": "marked",
                    "owner_teacher_id": user.user_id
                }},
                {"$group": {"_id": None, "avg_score": {"$avg": "$score"}}}
            ]
            result = await db.attempts.aggregate(pipeline).to_list(1)
            cls["average_score"] = round(result[0]["avg_score"], 1) if result else None
        else:
            cls["average_score"] = None
    
    return {"classes": classes}


@router.post("/teacher/classes")
async def create_class(class_data: ClassCreate, user = Depends(require_teacher)):
    """Create a new class"""
    new_class = ClassModel(
        teacher_owner_id=user.user_id,
        class_name=class_data.class_name,
        subject=class_data.subject,
        year_group=class_data.year_group
    )
    
    await db.classes.insert_one(new_class.model_dump())
    
    return {
        "success": True,
        "class": new_class.model_dump(),
        "message": f"Class '{class_data.class_name}' created successfully"
    }


@router.get("/teacher/classes/{class_id}")
async def get_class_detail(class_id: str, user = Depends(require_teacher)):
    """Get detailed information about a specific class"""
    cls = await db.classes.find_one(
        {"id": class_id, "teacher_owner_id": user.user_id},
        {"_id": 0}
    )
    
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get students
    students = await db.students.find(
        {"class_id": class_id, "teacher_owner_id": user.user_id, "archived": {"$ne": True}},
        {"_id": 0}
    ).sort("last_name", 1).to_list(500)
    
    # Get assessments for this class
    assessments = await db.assessments.find(
        {"class_id": class_id, "teacher_owner_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    # Enrich assessments with submission counts
    for assessment in assessments:
        submission_count = await db.attempts.count_documents({
            "assessment_id": assessment["id"],
            "owner_teacher_id": user.user_id
        })
        marked_count = await db.attempts.count_documents({
            "assessment_id": assessment["id"],
            "owner_teacher_id": user.user_id,
            "status": "marked"
        })
        assessment["submission_count"] = submission_count
        assessment["marked_count"] = marked_count
    
    return {
        "class": cls,
        "students": students,
        "assessments": assessments,
        "student_count": len(students)
    }


@router.put("/teacher/classes/{class_id}")
async def update_class(class_id: str, class_data: ClassUpdate, user = Depends(require_teacher)):
    """Update a class"""
    cls = await db.classes.find_one({"id": class_id, "teacher_owner_id": user.user_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    update_data = {k: v for k, v in class_data.model_dump().items() if v is not None}
    
    if update_data:
        await db.classes.update_one(
            {"id": class_id, "teacher_owner_id": user.user_id},
            {"$set": update_data}
        )
    
    return {"success": True, "message": "Class updated successfully"}


@router.delete("/teacher/classes/{class_id}")
async def delete_class(class_id: str, user = Depends(require_teacher)):
    """Delete a class (archives students, doesn't delete them)"""
    cls = await db.classes.find_one({"id": class_id, "teacher_owner_id": user.user_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Archive students in this class
    await db.students.update_many(
        {"class_id": class_id, "teacher_owner_id": user.user_id},
        {"$set": {"archived": True}}
    )
    
    # Delete the class
    await db.classes.delete_one({"id": class_id, "teacher_owner_id": user.user_id})
    
    return {"success": True, "message": "Class deleted successfully"}


# ==================== STUDENTS ENDPOINTS ====================

@router.get("/teacher/students")
async def get_all_students(user = Depends(require_teacher), class_id: Optional[str] = None):
    """Get all students for the teacher, optionally filtered by class"""
    query = {"teacher_owner_id": user.user_id, "archived": {"$ne": True}}
    if class_id:
        query["class_id"] = class_id
    
    students = await db.students.find(query, {"_id": 0}).sort("last_name", 1).to_list(1000)
    
    # Enrich with class names
    class_ids = list(set(s["class_id"] for s in students))
    classes = await db.classes.find(
        {"id": {"$in": class_ids}, "teacher_owner_id": user.user_id},
        {"_id": 0, "id": 1, "class_name": 1}
    ).to_list(100)
    class_map = {c["id"]: c["class_name"] for c in classes}
    
    for student in students:
        student["class_name"] = class_map.get(student["class_id"], "Unknown")
    
    return {"students": students}


@router.post("/teacher/students")
async def create_student(student_data: StudentCreate, user = Depends(require_teacher)):
    """Create a new student"""
    # Verify class ownership
    cls = await db.classes.find_one({
        "id": student_data.class_id,
        "teacher_owner_id": user.user_id
    })
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Check for duplicates by student_code if provided
    if student_data.student_code:
        existing = await db.students.find_one({
            "teacher_owner_id": user.user_id,
            "student_code": student_data.student_code
        })
        if existing:
            raise HTTPException(status_code=400, detail="Student code already exists")
    
    # Check for name duplicates in same class
    existing_name = await db.students.find_one({
        "teacher_owner_id": user.user_id,
        "class_id": student_data.class_id,
        "first_name": student_data.first_name,
        "last_name": student_data.last_name,
        "archived": {"$ne": True}
    })
    if existing_name:
        raise HTTPException(status_code=400, detail="Student with same name already exists in this class")
    
    new_student = StudentModel(
        teacher_owner_id=user.user_id,
        **student_data.model_dump()
    )
    
    await db.students.insert_one(new_student.model_dump())
    
    return {
        "success": True,
        "student": new_student.model_dump(),
        "message": f"Student '{student_data.first_name} {student_data.last_name}' added successfully"
    }


# ==================== CSV IMPORT ENDPOINTS (must be before {student_id} routes) ====================

@router.get("/teacher/students/csv-template")
async def download_csv_template(user = Depends(require_teacher)):
    """Download CSV template for student import"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow([
        'class_name',
        'first_name', 
        'last_name',
        'preferred_name',
        'student_code',
        'email',
        'sen_flag',
        'pupil_premium_flag',
        'eal_flag'
    ])
    
    # Example rows
    writer.writerow(['10X1 Science', 'John', 'Smith', 'Johnny', 'STU001', 'john.smith@school.edu', 'FALSE', 'FALSE', 'FALSE'])
    writer.writerow(['10X1 Science', 'Jane', 'Doe', '', 'STU002', 'jane.doe@school.edu', 'TRUE', 'FALSE', 'FALSE'])
    writer.writerow(['11Y2 Physics', 'Alex', 'Johnson', 'AJ', '', '', 'FALSE', 'TRUE', 'TRUE'])
    
    csv_content = output.getvalue()
    output.close()
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=student_import_template.csv"}
    )


@router.post("/teacher/students/csv-preview")
async def preview_csv_import(data: CSVImportPreview, user = Depends(require_teacher)):
    """Preview CSV import - validate and show what will happen"""
    # Parse CSV
    reader = csv.DictReader(io.StringIO(data.csv_content))
    
    # Get existing classes for this teacher
    existing_classes = await db.classes.find(
        {"teacher_owner_id": user.user_id},
        {"_id": 0}
    ).to_list(1000)
    class_map = {c["class_name"].lower(): c for c in existing_classes}
    
    # Get existing students for this teacher
    existing_students = await db.students.find(
        {"teacher_owner_id": user.user_id},
        {"_id": 0}
    ).to_list(10000)
    
    # Build lookup maps
    student_by_code = {}
    student_by_name_class = {}
    for s in existing_students:
        if s.get("student_code"):
            student_by_code[s["student_code"].lower()] = s
        key = f"{s['first_name'].lower()}_{s['last_name'].lower()}_{s['class_id']}"
        student_by_name_class[key] = s
    
    preview_rows = []
    errors = []
    new_classes = set()
    
    row_num = 0
    for row in reader:
        row_num += 1
        
        # Normalize keys (handle different CSV formats)
        row = {(k.strip().lower().replace(' ', '_') if k else ''): (v.strip() if v else '') for k, v in row.items()}
        
        class_name = row.get('class_name', '')
        first_name = row.get('first_name', '')
        last_name = row.get('last_name', '')
        preferred_name = row.get('preferred_name', '')
        student_code = row.get('student_code', '')
        email = row.get('email', '')
        sen_flag = row.get('sen_flag', '').upper() == 'TRUE'
        pupil_premium_flag = row.get('pupil_premium_flag', '').upper() == 'TRUE'
        eal_flag = row.get('eal_flag', '').upper() == 'TRUE'
        
        # Validate required fields
        row_errors = []
        if not class_name:
            row_errors.append("Missing class_name")
        if not first_name:
            row_errors.append("Missing first_name")
        if not last_name:
            row_errors.append("Missing last_name")
        
        if row_errors:
            errors.append({
                "row": row_num,
                "errors": row_errors,
                "data": row
            })
            preview_rows.append({
                "row_num": row_num,
                "class_name": class_name,
                "first_name": first_name,
                "last_name": last_name,
                "preferred_name": preferred_name,
                "student_code": student_code,
                "email": email,
                "sen_flag": sen_flag,
                "pupil_premium_flag": pupil_premium_flag,
                "eal_flag": eal_flag,
                "action": "skip",
                "reason": "; ".join(row_errors),
                "valid": False
            })
            continue
        
        # Check if class exists or will be created
        class_exists = class_name.lower() in class_map
        if not class_exists:
            new_classes.add(class_name)
        
        # Determine action (create, update, or skip)
        action = "create"
        reason = ""
        existing_student = None
        
        # Check by student_code first
        if student_code and student_code.lower() in student_by_code:
            existing_student = student_by_code[student_code.lower()]
            action = "update"
            reason = f"Matched by student_code: {student_code}"
        else:
            # Check by name + class
            class_id = class_map.get(class_name.lower(), {}).get("id", "new")
            if class_id != "new":
                key = f"{first_name.lower()}_{last_name.lower()}_{class_id}"
                if key in student_by_name_class:
                    existing_student = student_by_name_class[key]
                    action = "update"
                    reason = f"Matched by name in class"
        
        if action == "create":
            reason = "New student" + (" (new class)" if not class_exists else "")
        
        preview_rows.append({
            "row_num": row_num,
            "class_name": class_name,
            "first_name": first_name,
            "last_name": last_name,
            "preferred_name": preferred_name,
            "student_code": student_code,
            "email": email,
            "sen_flag": sen_flag,
            "pupil_premium_flag": pupil_premium_flag,
            "eal_flag": eal_flag,
            "action": action,
            "reason": reason,
            "valid": True,
            "existing_student_id": existing_student["id"] if existing_student else None
        })
    
    # Count actions
    create_count = sum(1 for r in preview_rows if r["action"] == "create" and r["valid"])
    update_count = sum(1 for r in preview_rows if r["action"] == "update" and r["valid"])
    skip_count = sum(1 for r in preview_rows if r["action"] == "skip" or not r["valid"])
    
    return {
        "total_rows": row_num,
        "preview": preview_rows,
        "summary": {
            "will_create": create_count,
            "will_update": update_count,
            "will_skip": skip_count,
            "new_classes": list(new_classes)
        },
        "errors": errors
    }


@router.post("/teacher/students/csv-import")
async def import_csv_students(data: CSVImportConfirm, user = Depends(require_teacher)):
    """Execute CSV import after preview confirmation"""
    
    created_count = 0
    updated_count = 0
    skipped_count = 0
    created_classes = []
    errors = []
    
    # Get existing classes
    existing_classes = await db.classes.find(
        {"teacher_owner_id": user.user_id},
        {"_id": 0}
    ).to_list(1000)
    class_map = {c["class_name"].lower(): c for c in existing_classes}
    
    for row in data.rows:
        if not row.get("valid", False) or row.get("action") == "skip":
            skipped_count += 1
            continue
        
        try:
            class_name = row["class_name"]
            
            # Get or create class
            class_key = class_name.lower()
            if class_key not in class_map:
                # Create new class
                new_class = ClassModel(
                    teacher_owner_id=user.user_id,
                    class_name=class_name
                )
                await db.classes.insert_one(new_class.model_dump())
                class_map[class_key] = new_class.model_dump()
                created_classes.append(class_name)
            
            class_id = class_map[class_key]["id"]
            
            if row["action"] == "update" and row.get("existing_student_id"):
                # Update existing student
                await db.students.update_one(
                    {"id": row["existing_student_id"], "teacher_owner_id": user.user_id},
                    {"$set": {
                        "first_name": row["first_name"],
                        "last_name": row["last_name"],
                        "preferred_name": row.get("preferred_name") or None,
                        "student_code": row.get("student_code") or None,
                        "email": row.get("email") or None,
                        "sen_flag": row.get("sen_flag", False),
                        "pupil_premium_flag": row.get("pupil_premium_flag", False),
                        "eal_flag": row.get("eal_flag", False),
                        "class_id": class_id
                    }}
                )
                updated_count += 1
            else:
                # Create new student
                new_student = StudentModel(
                    teacher_owner_id=user.user_id,
                    class_id=class_id,
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    preferred_name=row.get("preferred_name") or None,
                    student_code=row.get("student_code") or None,
                    email=row.get("email") or None,
                    sen_flag=row.get("sen_flag", False),
                    pupil_premium_flag=row.get("pupil_premium_flag", False),
                    eal_flag=row.get("eal_flag", False)
                )
                await db.students.insert_one(new_student.model_dump())
                created_count += 1
                
        except Exception as e:
            errors.append({
                "row": row.get("row_num"),
                "error": str(e)
            })
            skipped_count += 1
    
    return {
        "success": True,
        "summary": {
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "classes_created": created_classes
        },
        "errors": errors,
        "message": f"Import complete: {created_count} created, {updated_count} updated, {skipped_count} skipped"
    }


# ==================== STUDENT DETAIL ENDPOINTS (with {student_id} parameter) ====================

@router.get("/teacher/students/{student_id}")
async def get_student_detail(student_id: str, user = Depends(require_teacher)):
    """Get detailed information about a specific student including their submissions"""
    student = await db.students.find_one(
        {"id": student_id, "teacher_owner_id": user.user_id},
        {"_id": 0}
    )
    
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Get class info
    cls = await db.classes.find_one(
        {"id": student["class_id"], "teacher_owner_id": user.user_id},
        {"_id": 0}
    )
    
    # Get submissions linked to this student
    submissions = await db.attempts.find(
        {"student_id": student_id, "owner_teacher_id": user.user_id},
        {"_id": 0}
    ).sort("submitted_at", -1).to_list(100)
    
    # Calculate stats
    marked_submissions = [s for s in submissions if s.get("status") == "marked"]
    total_score = sum(s.get("score", 0) for s in marked_submissions)
    
    return {
        "student": student,
        "class": cls,
        "submissions": submissions,
        "stats": {
            "total_submissions": len(submissions),
            "marked_submissions": len(marked_submissions),
            "average_score": round(total_score / len(marked_submissions), 1) if marked_submissions else None
        }
    }


@router.put("/teacher/students/{student_id}")
async def update_student(student_id: str, student_data: StudentUpdate, user = Depends(require_teacher)):
    """Update a student"""
    student = await db.students.find_one({
        "id": student_id,
        "teacher_owner_id": user.user_id
    })
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # If changing class, verify new class ownership
    if student_data.class_id:
        cls = await db.classes.find_one({
            "id": student_data.class_id,
            "teacher_owner_id": user.user_id
        })
        if not cls:
            raise HTTPException(status_code=404, detail="Target class not found")
    
    update_data = {k: v for k, v in student_data.model_dump().items() if v is not None}
    
    if update_data:
        await db.students.update_one(
            {"id": student_id, "teacher_owner_id": user.user_id},
            {"$set": update_data}
        )
    
    return {"success": True, "message": "Student updated successfully"}


@router.delete("/teacher/students/{student_id}")
async def archive_student(student_id: str, user = Depends(require_teacher)):
    """Archive a student (soft delete)"""
    student = await db.students.find_one({
        "id": student_id,
        "teacher_owner_id": user.user_id
    })
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    await db.students.update_one(
        {"id": student_id, "teacher_owner_id": user.user_id},
        {"$set": {"archived": True}}
    )
    
    return {"success": True, "message": "Student archived successfully"}


# ==================== CLASS-ASSESSMENT LINKING ENDPOINTS ====================

@router.get("/teacher/classes/{class_id}/students-dropdown")
async def get_class_students_dropdown(class_id: str, user = Depends(require_teacher)):
    """Get students in a class for dropdown selection during assessment join"""
    cls = await db.classes.find_one({
        "id": class_id,
        "teacher_owner_id": user.user_id
    })
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    students = await db.students.find(
        {"class_id": class_id, "teacher_owner_id": user.user_id, "archived": {"$ne": True}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "preferred_name": 1, "student_code": 1}
    ).sort("last_name", 1).to_list(500)
    
    # Format for dropdown
    dropdown_options = []
    for s in students:
        display_name = s.get("preferred_name") or f"{s['first_name']} {s['last_name']}"
        dropdown_options.append({
            "id": s["id"],
            "display_name": display_name,
            "full_name": f"{s['first_name']} {s['last_name']}",
            "student_code": s.get("student_code")
        })
    
    return {
        "class": cls,
        "students": dropdown_options
    }


# ==================== CLASS ANALYTICS ENDPOINTS (Phase 3) ====================

@router.get("/teacher/classes/{class_id}/analytics")
async def get_class_analytics(class_id: str, user = Depends(require_teacher)):
    """Get comprehensive analytics for a specific class"""
    # Verify class ownership
    cls = await db.classes.find_one({
        "id": class_id,
        "teacher_owner_id": user.user_id
    }, {"_id": 0})
    
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get students in this class
    students = await db.students.find(
        {"class_id": class_id, "teacher_owner_id": user.user_id, "archived": {"$ne": True}},
        {"_id": 0}
    ).to_list(500)
    
    student_ids = [s["id"] for s in students]
    student_names = {s["id"]: f"{s['first_name']} {s['last_name']}" for s in students}
    
    # Get assessments linked to this class
    assessments = await db.assessments.find(
        {"class_id": class_id, "owner_teacher_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    # Get questions for max_marks lookup
    question_ids = list(set(a.get("question_id") for a in assessments))
    questions = await db.questions.find(
        {"id": {"$in": question_ids}},
        {"_id": 0, "id": 1, "max_marks": 1}
    ).to_list(100)
    question_max_marks = {q["id"]: q.get("max_marks", 100) for q in questions}
    
    # Create assessment to max_marks mapping
    assessment_max_marks = {}
    for a in assessments:
        assessment_max_marks[a["id"]] = question_max_marks.get(a.get("question_id"), 100)
    
    # Get all attempts for these assessments
    assessment_ids = [a["id"] for a in assessments]
    all_attempts = await db.attempts.find({
        "assessment_id": {"$in": assessment_ids},
        "owner_teacher_id": user.user_id
    }, {"_id": 0}).to_list(10000)
    
    # Calculate student performance
    student_performance = []
    students_needing_support = []
    improving_students = []
    declining_students = []
    
    for student in students:
        student_id = student["id"]
        student_name = f"{student['first_name']} {student['last_name']}"
        
        # Get attempts for this student (match by student_id or student_name)
        student_attempts = [
            a for a in all_attempts 
            if a.get("student_id") == student_id or a.get("student_name") == student_name
        ]
        marked_attempts = [a for a in student_attempts if a.get("status") == "marked"]
        
        if not marked_attempts:
            student_performance.append({
                "student_id": student_id,
                "student_name": student_name,
                "total_attempts": len(student_attempts),
                "marked_attempts": 0,
                "average_score": None,
                "trend": "no_data",
                "needs_support": False,
                "support_reasons": [],
                "sen_flag": student.get("sen_flag", False),
                "pupil_premium_flag": student.get("pupil_premium_flag", False)
            })
            continue
        
        # Calculate average as percentage (not raw score)
        percentages = []
        for a in marked_attempts:
            max_marks = assessment_max_marks.get(a.get("assessment_id"), 100)
            score = a.get("score", 0)
            pct = (score / max_marks * 100) if max_marks > 0 else 0
            percentages.append(pct)
        average = sum(percentages) / len(percentages) if percentages else 0
        
        # Calculate trend (simple: compare first half vs second half) using percentages
        trend = "stable"
        slope = 0
        if len(marked_attempts) >= 3:
            # Sort by submission date
            sorted_attempts = sorted(marked_attempts, key=lambda x: x.get("submitted_at", ""))
            mid = len(sorted_attempts) // 2
            
            # Calculate percentages for first half
            first_half_pcts = []
            for a in sorted_attempts[:mid]:
                mm = assessment_max_marks.get(a.get("assessment_id"), 100)
                first_half_pcts.append((a.get("score", 0) / mm * 100) if mm > 0 else 0)
            first_half_avg = sum(first_half_pcts) / len(first_half_pcts) if first_half_pcts else 0
            
            # Calculate percentages for second half
            second_half_pcts = []
            for a in sorted_attempts[mid:]:
                mm = assessment_max_marks.get(a.get("assessment_id"), 100)
                second_half_pcts.append((a.get("score", 0) / mm * 100) if mm > 0 else 0)
            second_half_avg = sum(second_half_pcts) / len(second_half_pcts) if second_half_pcts else 0
            
            if second_half_avg > first_half_avg + 5:
                trend = "improving"
                slope = second_half_avg - first_half_avg
            elif second_half_avg < first_half_avg - 5:
                trend = "declining"
                slope = second_half_avg - first_half_avg
        
        # Check if needs support (using percentage average)
        support_reasons = []
        needs_support = False
        
        if average < 50:
            support_reasons.append(f"Average below 50% ({average:.1f}%)")
            needs_support = True
        
        # Check recent failures using percentages
        recent_attempts = sorted(marked_attempts, key=lambda x: x.get("submitted_at", ""), reverse=True)[:3]
        failures = 0
        for a in recent_attempts:
            mm = assessment_max_marks.get(a.get("assessment_id"), 100)
            pct = (a.get("score", 0) / mm * 100) if mm > 0 else 0
            if pct < 50:
                failures += 1
        if failures >= 2:
            support_reasons.append(f"Failed {failures} of last 3 assessments")
            needs_support = True
        
        if trend == "declining":
            support_reasons.append("Declining performance trend")
            needs_support = True
        
        perf_data = {
            "student_id": student_id,
            "student_name": student_name,
            "total_attempts": len(student_attempts),
            "marked_attempts": len(marked_attempts),
            "average_score": round(average, 1),
            "trend": trend,
            "trend_slope": round(slope, 1),
            "needs_support": needs_support,
            "support_reasons": support_reasons,
            "sen_flag": student.get("sen_flag", False),
            "pupil_premium_flag": student.get("pupil_premium_flag", False),
            "recent_scores": [a.get("score", 0) for a in recent_attempts]
        }
        
        student_performance.append(perf_data)
        
        if needs_support:
            students_needing_support.append(perf_data)
        if trend == "improving":
            improving_students.append(perf_data)
        if trend == "declining":
            declining_students.append(perf_data)
    
    # Calculate class-level stats
    marked_students = [s for s in student_performance if s.get("marked_attempts", 0) > 0]
    class_average = sum(s.get("average_score", 0) for s in marked_students) / len(marked_students) if marked_students else 0
    
    # Topic analysis
    topic_stats = {}
    for assessment in assessments:
        question = await db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0})
        if not question:
            continue
        
        topic = question.get("topic") or question.get("subject", "General")
        max_marks = question.get("max_marks", 100)
        
        assessment_attempts = [a for a in all_attempts if a.get("assessment_id") == assessment["id"] and a.get("status") == "marked"]
        
        if assessment_attempts:
            scores = [(a.get("score", 0) / max_marks * 100) if max_marks > 0 else 0 for a in assessment_attempts]
            avg_percentage = sum(scores) / len(scores)
            
            if topic not in topic_stats:
                topic_stats[topic] = {"scores": [], "students_struggling": set()}
            
            topic_stats[topic]["scores"].extend(scores)
            for a in assessment_attempts:
                score_pct = (a.get("score", 0) / max_marks * 100) if max_marks > 0 else 0
                if score_pct < 50:
                    topic_stats[topic]["students_struggling"].add(a.get("student_name", "Unknown"))
    
    topics_to_reteach = []
    for topic, data in topic_stats.items():
        if data["scores"]:
            avg = sum(data["scores"]) / len(data["scores"])
            if avg < 60:  # Topics with average below 60% need reteaching
                topics_to_reteach.append({
                    "topic": topic,
                    "average_percentage": round(avg, 1),
                    "attempts": len(data["scores"]),
                    "struggling_students": list(data["students_struggling"])[:10]
                })
    
    topics_to_reteach.sort(key=lambda x: x["average_percentage"])
    
    # Assessment breakdown
    assessment_analytics = []
    for assessment in assessments[:10]:  # Last 10 assessments
        question = await db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0})
        assessment_attempts = [a for a in all_attempts if a.get("assessment_id") == assessment["id"]]
        marked = [a for a in assessment_attempts if a.get("status") == "marked"]
        
        avg_score = sum(a.get("score", 0) for a in marked) / len(marked) if marked else 0
        
        assessment_analytics.append({
            "assessment_id": assessment["id"],
            "subject": question.get("subject", "Unknown") if question else "Unknown",
            "topic": question.get("topic") if question else None,
            "total_submissions": len(assessment_attempts),
            "marked_count": len(marked),
            "average_score": round(avg_score, 1),
            "status": assessment.get("status"),
            "created_at": assessment.get("created_at")
        })
    
    return {
        "class": cls,
        "summary": {
            "total_students": len(students),
            "students_with_submissions": len(marked_students),
            "class_average": round(class_average, 1),
            "students_needing_support": len(students_needing_support),
            "improving_count": len(improving_students),
            "declining_count": len(declining_students),
            "total_assessments": len(assessments),
            "total_marked_submissions": sum(s.get("marked_attempts", 0) for s in student_performance)
        },
        "students": {
            "all": sorted(student_performance, key=lambda x: x.get("average_score") or 0),
            "needing_support": students_needing_support,
            "improving": improving_students,
            "declining": declining_students
        },
        "topics_to_reteach": topics_to_reteach,
        "assessments": assessment_analytics
    }


@router.get("/teacher/classes/{class_id}/analytics/heatmap")
async def get_class_heatmap(class_id: str, user = Depends(require_teacher)):
    """Get performance heatmap data (Students x Assessments matrix)"""
    # Verify class ownership
    cls = await db.classes.find_one({
        "id": class_id,
        "teacher_owner_id": user.user_id
    }, {"_id": 0})
    
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get students in this class
    students = await db.students.find(
        {"class_id": class_id, "teacher_owner_id": user.user_id, "archived": {"$ne": True}},
        {"_id": 0}
    ).sort("last_name", 1).to_list(500)
    
    # Get assessments linked to this class (most recent first)
    assessments = await db.assessments.find(
        {"class_id": class_id, "owner_teacher_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(20)  # Limit to 20 most recent
    
    if not assessments:
        return {
            "class": cls,
            "students": [],
            "assessments": [],
            "matrix": [],
            "message": "No assessments linked to this class yet"
        }
    
    # Get questions for assessment names
    question_ids = [a.get("question_id") for a in assessments]
    questions = await db.questions.find(
        {"id": {"$in": question_ids}},
        {"_id": 0, "id": 1, "subject": 1, "topic": 1, "max_marks": 1}
    ).to_list(100)
    question_map = {q["id"]: q for q in questions}
    
    # Build assessment headers
    assessment_headers = []
    for a in assessments:
        q = question_map.get(a.get("question_id"), {})
        assessment_headers.append({
            "assessment_id": a["id"],
            "subject": q.get("subject", "Unknown"),
            "topic": q.get("topic", ""),
            "max_marks": q.get("max_marks", 100),
            "join_code": a.get("join_code", ""),
            "created_at": a.get("created_at")
        })
    
    # Get all attempts for these assessments
    assessment_ids = [a["id"] for a in assessments]
    all_attempts = await db.attempts.find({
        "assessment_id": {"$in": assessment_ids},
        "owner_teacher_id": user.user_id,
        "status": "marked"
    }, {"_id": 0}).to_list(10000)
    
    # Build matrix
    matrix = []
    for student in students:
        student_id = student["id"]
        student_name = f"{student['first_name']} {student['last_name']}"
        
        row = {
            "student_id": student_id,
            "student_name": student_name,
            "preferred_name": student.get("preferred_name"),
            "sen_flag": student.get("sen_flag", False),
            "pupil_premium_flag": student.get("pupil_premium_flag", False),
            "scores": []
        }
        
        total_score = 0
        score_count = 0
        
        for assessment in assessments:
            # Find attempt for this student in this assessment
            attempt = None
            for a in all_attempts:
                if a.get("assessment_id") == assessment["id"]:
                    if a.get("student_id") == student_id or a.get("student_name") == student_name:
                        attempt = a
                        break
            
            if attempt:
                score = attempt.get("score", 0)
                max_marks = question_map.get(assessment.get("question_id"), {}).get("max_marks", 100)
                percentage = round((score / max_marks * 100), 1) if max_marks > 0 else 0
                
                row["scores"].append({
                    "assessment_id": assessment["id"],
                    "score": score,
                    "max_marks": max_marks,
                    "percentage": percentage,
                    "status": "marked"
                })
                total_score += percentage
                score_count += 1
            else:
                # Check if there's an unmarked attempt
                row["scores"].append({
                    "assessment_id": assessment["id"],
                    "score": None,
                    "percentage": None,
                    "status": "no_submission"
                })
        
        # Calculate row average
        row["average"] = round(total_score / score_count, 1) if score_count > 0 else None
        row["submission_count"] = score_count
        
        matrix.append(row)
    
    # Sort matrix by average (lowest first to highlight struggling students)
    matrix.sort(key=lambda x: x.get("average") or 0)
    
    return {
        "class": cls,
        "assessments": assessment_headers,
        "matrix": matrix,
        "stats": {
            "total_students": len(students),
            "total_assessments": len(assessments),
            "students_with_submissions": sum(1 for m in matrix if m["submission_count"] > 0)
        }
    }


@router.get("/teacher/classes/{class_id}/analytics/export-csv")
async def export_class_analytics_csv(class_id: str, user = Depends(require_teacher)):
    """Export class analytics as CSV"""
    # Get analytics data
    cls = await db.classes.find_one({
        "id": class_id,
        "teacher_owner_id": user.user_id
    }, {"_id": 0})
    
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get students
    students = await db.students.find(
        {"class_id": class_id, "teacher_owner_id": user.user_id, "archived": {"$ne": True}},
        {"_id": 0}
    ).to_list(500)
    
    # Get assessments for this class
    assessments = await db.assessments.find(
        {"class_id": class_id, "owner_teacher_id": user.user_id},
        {"_id": 0}
    ).to_list(100)
    
    assessment_ids = [a["id"] for a in assessments]
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Student Name', 'Student Code', 'Total Assessments', 'Marked', 
        'Average Score', 'Trend', 'Needs Support', 'Support Reasons',
        'SEN', 'Pupil Premium', 'EAL'
    ])
    
    for student in students:
        student_name = f"{student['first_name']} {student['last_name']}"
        
        # Get attempts for this student
        attempts = await db.attempts.find({
            "assessment_id": {"$in": assessment_ids},
            "$or": [
                {"student_id": student["id"]},
                {"student_name": student_name}
            ]
        }, {"_id": 0}).to_list(1000)
        
        marked = [a for a in attempts if a.get("status") == "marked"]
        scores = [a.get("score", 0) for a in marked]
        average = sum(scores) / len(scores) if scores else None
        
        # Simple trend calculation
        trend = "N/A"
        if len(marked) >= 3:
            sorted_attempts = sorted(marked, key=lambda x: x.get("submitted_at", ""))
            mid = len(sorted_attempts) // 2
            first_avg = sum(a.get("score", 0) for a in sorted_attempts[:mid]) / mid if mid > 0 else 0
            second_avg = sum(a.get("score", 0) for a in sorted_attempts[mid:]) / (len(sorted_attempts) - mid) if (len(sorted_attempts) - mid) > 0 else 0
            
            if second_avg > first_avg + 5:
                trend = "Improving"
            elif second_avg < first_avg - 5:
                trend = "Declining"
            else:
                trend = "Stable"
        
        needs_support = average is not None and average < 50
        support_reasons = []
        if needs_support:
            support_reasons.append(f"Avg < 50%")
        
        writer.writerow([
            student_name,
            student.get("student_code", ""),
            len(attempts),
            len(marked),
            f"{average:.1f}" if average else "N/A",
            trend,
            "Yes" if needs_support else "No",
            "; ".join(support_reasons),
            "Yes" if student.get("sen_flag") else "No",
            "Yes" if student.get("pupil_premium_flag") else "No",
            "Yes" if student.get("eal_flag") else "No"
        ])
    
    csv_content = output.getvalue()
    output.close()
    
    safe_class_name = "".join(c for c in cls["class_name"] if c.isalnum() or c in " -_").strip().replace(" ", "_")
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=Class_Analytics_{safe_class_name}.csv"}
    )


@router.get("/teacher/classes/{class_id}/analytics/export-pdf")
async def export_class_analytics_pdf(class_id: str, user = Depends(require_teacher)):
    """Export class analytics as PDF report"""
    from fastapi.responses import FileResponse
    
    if not PDF_AVAILABLE:
        raise HTTPException(status_code=500, detail="PDF generation not available")
    
    # Get class data
    cls = await db.classes.find_one({
        "id": class_id,
        "teacher_owner_id": user.user_id
    }, {"_id": 0})
    
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get analytics (reuse the logic)
    students = await db.students.find(
        {"class_id": class_id, "teacher_owner_id": user.user_id, "archived": {"$ne": True}},
        {"_id": 0}
    ).to_list(500)
    
    assessments = await db.assessments.find(
        {"class_id": class_id, "owner_teacher_id": user.user_id},
        {"_id": 0}
    ).to_list(100)
    
    assessment_ids = [a["id"] for a in assessments]
    
    # Calculate student stats
    student_stats = []
    for student in students:
        student_name = f"{student['first_name']} {student['last_name']}"
        
        attempts = await db.attempts.find({
            "assessment_id": {"$in": assessment_ids},
            "$or": [
                {"student_id": student["id"]},
                {"student_name": student_name}
            ],
            "status": "marked"
        }, {"_id": 0}).to_list(1000)
        
        if attempts:
            scores = [a.get("score", 0) for a in attempts]
            average = sum(scores) / len(scores)
            student_stats.append({
                "name": student_name,
                "attempts": len(attempts),
                "average": round(average, 1),
                "needs_support": average < 50
            })
        else:
            student_stats.append({
                "name": student_name,
                "attempts": 0,
                "average": None,
                "needs_support": False
            })
    
    # Generate PDF
    ROOT_DIR = Path(__file__).parent.parent
    pdf_dir = ROOT_DIR / "generated_pdfs"
    pdf_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in cls["class_name"] if c.isalnum() or c in " -_").strip().replace(" ", "_")
    pdf_filename = f"Class_Analytics_{safe_name}_{timestamp}.pdf"
    pdf_path = pdf_dir / pdf_filename
    
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=18, spaceAfter=10*mm)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontSize=14, spaceAfter=5*mm, spaceBefore=8*mm)
    
    story = []
    
    # Title
    story.append(Paragraph(f"Class Analytics Report", title_style))
    story.append(Paragraph(f"Class: {cls['class_name']}", styles['Normal']))
    if cls.get('subject'):
        story.append(Paragraph(f"Subject: {cls['subject']}", styles['Normal']))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%d %B %Y at %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 10*mm))
    
    # Summary
    story.append(Paragraph("Summary", heading_style))
    active_students = [s for s in student_stats if s["attempts"] > 0]
    avg_of_avgs = sum(s["average"] for s in active_students if s["average"]) / len(active_students) if active_students else 0
    support_count = sum(1 for s in student_stats if s.get("needs_support"))
    
    summary_data = [
        ["Total Students", str(len(students))],
        ["Total Assessments", str(len(assessments))],
        ["Class Average", f"{avg_of_avgs:.1f}%" if active_students else "N/A"],
        ["Students Needing Support", str(support_count)]
    ]
    
    summary_table = Table(summary_data, colWidths=[120, 100])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10*mm))
    
    # Student Performance Table
    story.append(Paragraph("Student Performance", heading_style))
    
    table_data = [["Student Name", "Assessments", "Average", "Status"]]
    for s in sorted(student_stats, key=lambda x: x.get("average") or 0):
        status = "Needs Support" if s.get("needs_support") else ("Active" if s["attempts"] > 0 else "No submissions")
        table_data.append([
            s["name"][:30],
            str(s["attempts"]),
            f"{s['average']:.1f}%" if s["average"] else "N/A",
            status
        ])
    
    student_table = Table(table_data, colWidths=[150, 70, 70, 90])
    student_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3B82F6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
    ]))
    
    # Highlight students needing support
    for i, s in enumerate(sorted(student_stats, key=lambda x: x.get("average") or 0), 1):
        if s.get("needs_support"):
            student_table.setStyle(TableStyle([
                ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FEE2E2')),
            ]))
    
    story.append(student_table)
    
    # Build PDF
    doc.build(story)
    
    return FileResponse(
        str(pdf_path),
        media_type='application/pdf',
        filename=pdf_filename
    )


# ==================== PUBLIC ENDPOINT FOR STUDENT JOIN WITH CLASS ROSTER ====================

@router.get("/public/assessment/{join_code}/class-roster")
async def get_assessment_class_roster(join_code: str):
    """Get student roster for class-linked assessment (public endpoint)"""
    assessment = await db.assessments.find_one({"join_code": join_code}, {"_id": 0})
    
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    if assessment.get("status") != "started":
        raise HTTPException(status_code=400, detail="Assessment is not active")
    
    class_id = assessment.get("class_id")
    if not class_id:
        return {"has_roster": False, "students": [], "class_name": None}
    
    # Get students for this class
    students = await db.students.find(
        {"class_id": class_id, "teacher_owner_id": assessment["owner_teacher_id"], "archived": {"$ne": True}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "preferred_name": 1}
    ).sort("last_name", 1).to_list(500)
    
    # Get class name
    cls = await db.classes.find_one({"id": class_id}, {"_id": 0, "class_name": 1})
    
    dropdown = []
    for s in students:
        display_name = s.get("preferred_name") or f"{s['first_name']} {s['last_name']}"
        dropdown.append({
            "id": s["id"],
            "display_name": display_name
        })
    
    return {
        "has_roster": True,
        "students": dropdown,
        "class_name": cls["class_name"] if cls else None
    }
