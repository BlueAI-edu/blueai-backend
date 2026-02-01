"""Attempt Finalization Service - Server-authoritative submission handling"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

async def finalize_attempt(db, attempt_id: str, reason: str = "timeout") -> dict:
    """
    Finalize an attempt (make it submitted).
    
    This function is idempotent - calling it multiple times will not create duplicates.
    
    Args:
        db: MongoDB database connection
        attempt_id: The attempt ID to finalize
        reason: Reason for finalization ("timeout", "manual", "offline_reconnect")
    
    Returns:
        dict: Updated attempt document
    """
    # Fetch the attempt
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    
    if not attempt:
        logger.error(f"Attempt {attempt_id} not found")
        raise ValueError(f"Attempt {attempt_id} not found")
    
    # Idempotency check - if already submitted, return as-is
    if attempt.get("submitted_at") or attempt.get("status") in ["submitted", "marked"]:
        logger.info(f"Attempt {attempt_id} already finalized, returning existing state")
        return attempt
    
    # Mark as submitted
    now = datetime.now(timezone.utc)
    update_data = {
        "submitted_at": now.isoformat(),
        "status": "submitted",
        "autosubmitted": reason == "timeout",
        "finalize_reason": reason
    }
    
    await db.attempts.update_one(
        {"attempt_id": attempt_id},
        {"$set": update_data}
    )
    
    # Log the finalization
    logger.info(
        f"Finalized attempt {attempt_id} for assessment {attempt.get('assessment_id')} "
        f"student: {attempt.get('student_name')}, reason: {reason}, "
        f"last_saved: {attempt.get('last_saved_at', 'never')}"
    )
    
    # Return updated attempt
    updated_attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    return updated_attempt


async def check_and_finalize_expired_attempts(db) -> int:
    """
    Background job to finalize attempts that have expired.
    Should be called by a cron job or scheduler every 1-5 minutes.
    
    Returns:
        int: Number of attempts finalized
    """
    now = datetime.now(timezone.utc)
    finalized_count = 0
    
    # Find all in-progress attempts
    attempts_cursor = db.attempts.find({
        "status": "in_progress",
        "submitted_at": None
    }, {"_id": 0})
    
    attempts = await attempts_cursor.to_list(length=1000)
    
    for attempt in attempts:
        try:
            # Get the assessment to check duration
            assessment = await db.assessments.find_one(
                {"id": attempt["assessment_id"]},
                {"_id": 0}
            )
            
            if not assessment:
                continue
            
            # Check if assessment has a time limit
            duration_minutes = assessment.get("duration_minutes")
            started_at = assessment.get("started_at")
            
            if not duration_minutes or not started_at:
                continue
            
            # Parse start time
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at)
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            
            # Calculate if expired
            elapsed = (now - started_at).total_seconds() / 60
            
            if elapsed >= duration_minutes:
                # This attempt has expired, finalize it
                await finalize_attempt(db, attempt["attempt_id"], reason="timeout")
                finalized_count += 1
                logger.info(f"Auto-finalized expired attempt {attempt['attempt_id']}")
        
        except Exception as e:
            logger.error(f"Error finalizing attempt {attempt.get('attempt_id')}: {str(e)}")
    
    if finalized_count > 0:
        logger.info(f"Background job finalized {finalized_count} expired attempts")
    
    return finalized_count


async def check_attempt_expired_on_request(db, attempt_id: str) -> bool:
    """
    Check if an attempt has expired when the student makes any request.
    If expired, finalize it automatically.
    
    Returns:
        bool: True if attempt was expired and finalized, False otherwise
    """
    attempt = await db.attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    
    if not attempt or attempt.get("status") != "in_progress":
        return False
    
    assessment = await db.assessments.find_one(
        {"id": attempt["assessment_id"]},
        {"_id": 0}
    )
    
    if not assessment:
        return False
    
    duration_minutes = assessment.get("duration_minutes")
    started_at = assessment.get("started_at")
    
    if not duration_minutes or not started_at:
        return False
    
    # Parse start time
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    
    # Check if expired
    now = datetime.now(timezone.utc)
    elapsed = (now - started_at).total_seconds() / 60
    
    if elapsed >= duration_minutes:
        # Expired! Finalize it
        await finalize_attempt(db, attempt_id, reason="timeout")
        return True
    
    return False
