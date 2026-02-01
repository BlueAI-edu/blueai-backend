"""
AI Auto-Marking Service for Enhanced Assessments
Uses Emergent LLM to automatically grade student submissions
"""

import logging
from typing import Dict, List, Any
from emergentintegrations.llm.chat import LlmChat, UserMessage
import json
import re
import uuid

class EnhancedAssessmentMarker:
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    async def mark_submission(
        self,
        assessment: Dict[str, Any],
        attempt: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Mark an entire Enhanced Assessment submission
        Returns scores and feedback
        """
        try:
            questions = assessment.get("questions", [])
            answers = attempt.get("answers", {})
            is_formative = assessment.get("assessmentMode") == "FORMATIVE_SINGLE_LONG_RESPONSE"
            
            question_scores = {}
            question_feedback = []
            total_score = 0
            total_max_marks = 0
            
            # Mark each question
            for question in questions:
                question_result = await self._mark_question(question, answers, is_formative)
                
                # Store scores
                if question.get("questionType") == "STRUCTURED_WITH_PARTS":
                    # For structured questions, store part scores
                    for part_score in question_result["part_scores"]:
                        part_key = part_score["key"]
                        score = part_score["score"]
                        question_scores[part_key] = score
                        total_score += score
                else:
                    # For non-structured questions
                    question_scores[str(question["questionNumber"])] = question_result["score"]
                    total_score += question_result["score"]
                
                total_max_marks += question_result["max_marks"]
                question_feedback.append(question_result["feedback"])
            
            # Generate overall feedback
            overall_feedback_result = await self._generate_overall_feedback(
                questions,
                question_feedback,
                total_score,
                total_max_marks,
                is_formative
            )
            
            return {
                "question_scores": question_scores,
                "total_score": total_score if not is_formative else None,
                "total_max_marks": total_max_marks,
                "www": overall_feedback_result["www"],
                "next_steps": overall_feedback_result["ebi"],
                "overall_feedback": overall_feedback_result["overall"]
            }
            
        except Exception as e:
            logging.error(f"Error in mark_submission: {str(e)}")
            raise Exception(f"Auto-marking failed: {str(e)}")
    
    async def _mark_question(
        self,
        question: Dict[str, Any],
        answers: Dict[str, str],
        is_formative: bool
    ) -> Dict[str, Any]:
        """Mark a single question"""
        
        question_type = question.get("questionType")
        question_number = question["questionNumber"]
        
        # Handle structured questions with parts
        if question_type == "STRUCTURED_WITH_PARTS" and question.get("parts"):
            return await self._mark_structured_question(question, answers, is_formative)
        
        # Handle multiple choice
        elif question_type == "MULTIPLE_CHOICE":
            return await self._mark_mcq_question(question, answers)
        
        # Handle regular questions (SHORT_ANSWER, LONG_RESPONSE)
        else:
            return await self._mark_regular_question(question, answers, is_formative)
    
    async def _mark_structured_question(
        self,
        question: Dict[str, Any],
        answers: Dict[str, str],
        is_formative: bool
    ) -> Dict[str, Any]:
        """Mark a structured question with multiple parts"""
        
        part_scores = []
        total_score = 0
        total_max = 0
        part_feedback_list = []
        
        for part in question.get("parts", []):
            part_label = part["partLabel"]
            part_key = f"{question['questionNumber']}-{part_label}"
            student_answer = answers.get(part_key, "")
            
            # Mark this part
            part_result = await self._mark_single_part(
                question["questionBody"],
                part,
                student_answer,
                is_formative
            )
            
            part_scores.append({
                "key": part_key,
                "label": part_label,
                "score": part_result["score"],
                "max_marks": part["maxMarks"]
            })
            
            total_score += part_result["score"]
            total_max += part["maxMarks"]
            part_feedback_list.append(f"Part {part_label}: {part_result['feedback']}")
        
        combined_feedback = " ".join(part_feedback_list)
        
        return {
            "score": total_score,
            "max_marks": total_max,
            "part_scores": part_scores,
            "feedback": combined_feedback
        }
    
    async def _mark_single_part(
        self,
        main_question: str,
        part: Dict[str, Any],
        student_answer: str,
        is_formative: bool
    ) -> Dict[str, Any]:
        """Mark a single part of a structured question"""
        
        if not student_answer.strip():
            return {
                "score": 0,
                "feedback": "No answer provided."
            }
        
        max_marks = part["maxMarks"]
        part_prompt = part["partPrompt"]
        mark_scheme = part.get("markScheme", "")
        
        prompt = f"""You are an expert examiner marking a student's answer.

**Context:** {main_question}

**Part ({part["partLabel"]}):** {part_prompt}

**Maximum Marks:** {max_marks}

**Student's Answer:** {student_answer}

**Mark Scheme:** {mark_scheme if mark_scheme else "Use your expert judgment to award marks based on correctness, clarity, and completeness."}

Please respond with ONLY a JSON object in this exact format:
{{
  "score": <number between 0 and {max_marks}>,
  "feedback": "<brief feedback explaining the score>"
}}

Consider:
- Accuracy and correctness
- Clarity of explanation
- Completeness of answer
- Appropriate use of terminology

IMPORTANT: Respond with ONLY the JSON object, no other text."""

        try:
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"mark_part_{str(uuid.uuid4())[:8]}",
                system_message="You are an expert examiner. Respond only with valid JSON."
            )
            chat.with_model("openai", "gpt-4o")
            
            user_message = UserMessage(text=prompt)
            response = await chat.send_message(user_message)
            
            # Parse JSON response
            result = self._parse_json_response(response)
            
            # Validate score
            score = min(max(0, result.get("score", 0)), max_marks)
            feedback = result.get("feedback", "Marked by AI")
            
            return {
                "score": score,
                "feedback": feedback
            }
            
        except Exception as e:
            logging.error(f"Error marking part: {str(e)}")
            # Fallback: award partial marks
            return {
                "score": max_marks // 2,
                "feedback": "Auto-marking encountered an error. Please review manually."
            }
    
    async def _mark_mcq_question(
        self,
        question: Dict[str, Any],
        answers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Mark a multiple choice question"""
        
        question_number = question["questionNumber"]
        student_answer = answers.get(str(question_number), "")
        correct_answer = question.get("correctAnswer", "")
        max_marks = question.get("maxMarks", 1)
        
        # Extract option text if it's an object
        if isinstance(correct_answer, dict):
            correct_answer = correct_answer.get("text") or correct_answer.get("label") or str(correct_answer)
        
        is_correct = student_answer.strip() == str(correct_answer).strip()
        score = max_marks if is_correct else 0
        
        feedback = "Correct!" if is_correct else f"Incorrect. The correct answer is: {correct_answer}"
        
        return {
            "score": score,
            "max_marks": max_marks,
            "part_scores": [],
            "feedback": feedback
        }
    
    async def _mark_regular_question(
        self,
        question: Dict[str, Any],
        answers: Dict[str, str],
        is_formative: bool
    ) -> Dict[str, Any]:
        """Mark a regular (non-MCQ, non-structured) question"""
        
        question_number = question["questionNumber"]
        student_answer = answers.get(str(question_number), "")
        
        if not student_answer.strip():
            return {
                "score": 0,
                "max_marks": question.get("maxMarks", 0),
                "part_scores": [],
                "feedback": "No answer provided."
            }
        
        max_marks = question.get("maxMarks", 5)
        mark_scheme = question.get("markScheme", "")
        model_answer = question.get("modelAnswer", "")
        
        prompt = f"""You are an expert examiner marking a student's answer.

**Question:** {question["questionBody"]}

**Maximum Marks:** {max_marks}

**Student's Answer:** {student_answer}

**Mark Scheme:** {mark_scheme if mark_scheme else "Use your expert judgment."}

{f"**Model Answer:** {model_answer}" if model_answer else ""}

Please respond with ONLY a JSON object in this exact format:
{{
  "score": <number between 0 and {max_marks}>,
  "feedback": "<brief feedback explaining the score>"
}}

IMPORTANT: Respond with ONLY the JSON object, no other text."""

        try:
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"mark_q_{str(uuid.uuid4())[:8]}",
                system_message="You are an expert examiner. Respond only with valid JSON."
            )
            chat.with_model("openai", "gpt-4o")
            
            user_message = UserMessage(text=prompt)
            response = await chat.send_message(user_message)
            
            result = self._parse_json_response(response)
            
            score = min(max(0, result.get("score", 0)), max_marks)
            feedback = result.get("feedback", "Marked by AI")
            
            return {
                "score": score,
                "max_marks": max_marks,
                "part_scores": [],
                "feedback": feedback
            }
            
        except Exception as e:
            logging.error(f"Error marking question: {str(e)}")
            return {
                "score": max_marks // 2,
                "max_marks": max_marks,
                "part_scores": [],
                "feedback": "Auto-marking encountered an error. Please review manually."
            }
    
    async def _generate_overall_feedback(
        self,
        questions: List[Dict[str, Any]],
        question_feedback: List[str],
        total_score: int,
        total_max_marks: int,
        is_formative: bool
    ) -> Dict[str, str]:
        """Generate WWW, EBI, and overall feedback"""
        
        score_text = "" if is_formative else f"**Score:** {total_score}/{total_max_marks}\n\n"
        
        prompt = f"""You are a supportive teacher providing feedback on a student's assessment.

{score_text}**Question-by-Question Feedback:**
{chr(10).join([f"{i+1}. {fb}" for i, fb in enumerate(question_feedback)])}

Please provide comprehensive feedback in the following format as a JSON object:

{{
  "www": "<What Went Well - highlight 2-3 specific strengths>",
  "ebi": "<Even Better If / Next Steps - provide 2-3 specific, actionable suggestions>",
  "overall": "<Overall summary and encouragement>"
}}

Guidelines:
- Be specific and constructive
- Highlight genuine strengths in WWW
- Make EBI actionable and achievable
- Keep overall feedback encouraging
- Focus on learning, not just scores

IMPORTANT: Respond with ONLY the JSON object."""

        try:
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"feedback_{str(uuid.uuid4())[:8]}",
                system_message="You are a supportive teacher providing constructive feedback."
            )
            chat.with_model("openai", "gpt-4o")
            
            user_message = UserMessage(text=prompt)
            response = await chat.send_message(user_message)
            
            result = self._parse_json_response(response)
            
            return {
                "www": result.get("www", "You made a good effort on this assessment."),
                "ebi": result.get("ebi", "Focus on reviewing the mark schemes and practicing similar questions."),
                "overall": result.get("overall", "Keep up the good work!")
            }
            
        except Exception as e:
            logging.error(f"Error generating feedback: {str(e)}")
            return {
                "www": "You completed the assessment and showed engagement with the material.",
                "ebi": "Review the mark schemes and practice similar questions to improve your understanding.",
                "overall": "Keep working hard and don't hesitate to ask for help if needed."
            }
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response"""
        try:
            # Try direct JSON parse
            return json.loads(response)
        except:
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            
            # Try to find JSON object in text
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            
            raise ValueError("Could not parse JSON from response")


# Factory function to get marker instance
def get_enhanced_marker(api_key: str) -> EnhancedAssessmentMarker:
    return EnhancedAssessmentMarker(api_key)
