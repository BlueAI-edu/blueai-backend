"""
Backward Compatibility Migration Service
Converts Classic assessments to Enhanced Assessment format
"""

import logging
from typing import Dict, List, Any
from datetime import datetime, timezone

class AssessmentMigrationService:
    def __init__(self, db):
        self.db = db
    
    async def migrate_all_classic_assessments(self) -> Dict[str, Any]:
        """
        Migrate all Classic assessments to Enhanced format
        Returns summary of migration
        """
        try:
            # Find all Classic assessments (those without assessmentMode or with CLASSIC)
            classic_assessments = await self.db.assessments.find({
                "$or": [
                    {"assessmentMode": {"$exists": False}},
                    {"assessmentMode": "CLASSIC"}
                ]
            }, {"_id": 0}).to_list(10000)
            
            total_count = len(classic_assessments)
            migrated_count = 0
            failed_count = 0
            skipped_count = 0
            errors = []
            
            logging.info(f"Found {total_count} Classic assessments to migrate")
            
            for assessment in classic_assessments:
                try:
                    result = await self.migrate_single_assessment(assessment)
                    
                    if result["status"] == "migrated":
                        migrated_count += 1
                    elif result["status"] == "skipped":
                        skipped_count += 1
                    
                except Exception as e:
                    failed_count += 1
                    error_msg = f"Failed to migrate {assessment.get('id')}: {str(e)}"
                    errors.append(error_msg)
                    logging.error(error_msg)
            
            summary = {
                "total": total_count,
                "migrated": migrated_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "errors": errors
            }
            
            logging.info(f"Migration complete: {summary}")
            return summary
            
        except Exception as e:
            logging.error(f"Migration process error: {str(e)}")
            raise Exception(f"Migration failed: {str(e)}")
    
    async def migrate_single_assessment(self, assessment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Migrate a single Classic assessment to Enhanced format
        """
        assessment_id = assessment.get("id")
        
        # Check if already migrated
        if assessment.get("assessmentMode") and assessment["assessmentMode"] != "CLASSIC":
            logging.info(f"Assessment {assessment_id} already migrated")
            return {"status": "skipped", "reason": "already_migrated"}
        
        # Get the linked question
        question_id = assessment.get("question_id")
        if not question_id:
            logging.warning(f"Assessment {assessment_id} has no question_id")
            return {"status": "skipped", "reason": "no_question"}
        
        question = await self.db.questions.find_one({"id": question_id}, {"_id": 0})
        if not question:
            logging.warning(f"Question {question_id} not found for assessment {assessment_id}")
            return {"status": "skipped", "reason": "question_not_found"}
        
        # Convert question to Enhanced format
        enhanced_question = self._convert_question_to_enhanced(question, question_number=1)
        
        # Build Enhanced Assessment structure
        update_data = {
            "assessmentMode": "FORMATIVE_SINGLE_LONG_RESPONSE",
            "title": question.get("subject", "Assessment"),
            "subject": question.get("subject", "General"),
            "stage": question.get("key_stage", "KS4"),
            "examBoard": question.get("exam_board", "AQA"),
            "tier": question.get("tier", "Higher"),
            "instructions": f"Answer the question below. This assessment was migrated from the classic format.",
            "shuffleQuestions": False,
            "shuffleOptions": False,
            "allowDraftSaving": True,
            "questions": [enhanced_question],
            "totalMarks": question.get("marks", 5),
            "migrated_from_classic": True,
            "original_question_id": question_id,
            "migrated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Update assessment
        await self.db.assessments.update_one(
            {"id": assessment_id},
            {"$set": update_data}
        )
        
        logging.info(f"Successfully migrated assessment {assessment_id}")
        return {"status": "migrated", "assessment_id": assessment_id}
    
    def _convert_question_to_enhanced(self, question: Dict[str, Any], question_number: int) -> Dict[str, Any]:
        """
        Convert a Classic question to Enhanced question format
        """
        # Determine question type
        question_type = "SHORT_ANSWER"  # Default
        
        if question.get("answer_type") == "MULTIPLE_CHOICE":
            question_type = "MULTIPLE_CHOICE"
        elif question.get("answer_type") == "LONG_TEXT":
            question_type = "LONG_RESPONSE"
        
        # Extract options if MCQ
        options = []
        if question_type == "MULTIPLE_CHOICE":
            options = question.get("options", [])
        
        # Build enhanced question structure
        enhanced_question = {
            "questionNumber": question_number,
            "questionType": question_type,
            "questionBody": question.get("question_text", ""),
            "maxMarks": question.get("marks", 5),
            "subject": question.get("subject", "General"),
            "topic": question.get("topic", ""),
            "difficulty": question.get("difficulty", "Medium"),
            "tags": question.get("tags", []),
            "options": options,
            "correctAnswer": question.get("correct_answer", "") if question_type == "MULTIPLE_CHOICE" else None,
            "allowMultiSelect": False,
            "parts": [],  # No parts for Classic questions
            "answerType": question.get("answer_type", "TEXT"),
            "calculatorAllowed": question.get("calculator_allowed", False),
            "markScheme": question.get("mark_scheme", ""),
            "modelAnswer": question.get("model_answer", ""),
            "source": "migrated_from_classic"
        }
        
        return enhanced_question
    
    async def get_migration_status(self) -> Dict[str, Any]:
        """
        Get current migration status
        """
        # Count Classic assessments
        classic_count = await self.db.assessments.count_documents({
            "$or": [
                {"assessmentMode": {"$exists": False}},
                {"assessmentMode": "CLASSIC"}
            ]
        })
        
        # Count Enhanced assessments
        enhanced_count = await self.db.assessments.count_documents({
            "assessmentMode": {"$exists": True, "$ne": "CLASSIC"}
        })
        
        # Count migrated assessments
        migrated_count = await self.db.assessments.count_documents({
            "migrated_from_classic": True
        })
        
        return {
            "classic_remaining": classic_count,
            "enhanced_total": enhanced_count,
            "migrated_total": migrated_count,
            "needs_migration": classic_count > 0
        }
    
    async def rollback_migration(self, assessment_id: str) -> Dict[str, Any]:
        """
        Rollback a single assessment migration (restore to Classic)
        """
        assessment = await self.db.assessments.find_one({"id": assessment_id}, {"_id": 0})
        
        if not assessment:
            raise Exception("Assessment not found")
        
        if not assessment.get("migrated_from_classic"):
            raise Exception("Assessment was not migrated from Classic")
        
        original_question_id = assessment.get("original_question_id")
        if not original_question_id:
            raise Exception("Original question ID not found")
        
        # Restore to Classic format
        restore_data = {
            "assessmentMode": "CLASSIC",
            "question_id": original_question_id
        }
        
        # Remove Enhanced fields
        unset_fields = {
            "questions": "",
            "title": "",
            "subject": "",
            "stage": "",
            "examBoard": "",
            "tier": "",
            "instructions": "",
            "shuffleQuestions": "",
            "shuffleOptions": "",
            "allowDraftSaving": "",
            "totalMarks": "",
            "migrated_from_classic": "",
            "original_question_id": "",
            "migrated_at": ""
        }
        
        await self.db.assessments.update_one(
            {"id": assessment_id},
            {
                "$set": restore_data,
                "$unset": unset_fields
            }
        )
        
        logging.info(f"Rolled back migration for assessment {assessment_id}")
        return {"status": "rolled_back", "assessment_id": assessment_id}


# Factory function
def get_migration_service(db):
    return AssessmentMigrationService(db)
