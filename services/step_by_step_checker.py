"""
Step-by-Step Solution Checker Service
Evaluates multi-step mathematical solutions with AI-powered feedback
"""

import logging
from typing import List, Dict, Any
from emergentintegrations import chat

class StepByStepChecker:
    def __init__(self, api_key: str):
        self.api_key = api_key
        
    def check_steps(
        self,
        steps: List[Dict[str, Any]],
        question_text: str,
        model_answer: str = None,
        mark_scheme: str = None
    ) -> Dict[str, Any]:
        """
        Check each step of a student's solution
        
        Args:
            steps: List of step dictionaries with stepNumber, description, calculation, explanation
            question_text: The original question
            model_answer: Expected final answer (optional)
            mark_scheme: Marking criteria (optional)
            
        Returns:
            Dictionary with step-by-step feedback and overall assessment
        """
        try:
            # Prepare the prompt for AI checking
            prompt = self._build_checking_prompt(
                steps, question_text, model_answer, mark_scheme
            )
            
            # Call AI to check the solution
            response = chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert mathematics teacher checking student solutions step by step. Provide constructive, encouraging feedback."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                llm_key=self.api_key,
                model="gpt-4o"
            )
            
            # Parse the AI response
            feedback = self._parse_ai_response(response, len(steps))
            
            return {
                "success": True,
                "step_feedback": feedback["steps"],
                "overall_assessment": feedback["overall"],
                "total_marks": feedback["total_marks"],
                "marks_awarded": feedback["marks_awarded"],
                "percentage": round((feedback["marks_awarded"] / feedback["total_marks"]) * 100, 1) if feedback["total_marks"] > 0 else 0
            }
            
        except Exception as e:
            logging.error(f"Step-by-step checking error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "step_feedback": [{"stepNumber": i+1, "isCorrect": None, "feedback": "Unable to check this step"} for i in range(len(steps))]
            }
    
    def _build_checking_prompt(
        self,
        steps: List[Dict],
        question: str,
        model_answer: str,
        mark_scheme: str
    ) -> str:
        """Build the prompt for AI checking"""
        
        prompt = f"""# Question
{question}

"""
        
        if model_answer:
            prompt += f"""# Expected Answer
{model_answer}

"""
        
        if mark_scheme:
            prompt += f"""# Mark Scheme
{mark_scheme}

"""
        
        prompt += """# Student's Step-by-Step Solution

"""
        
        for step in steps:
            prompt += f"""**Step {step['stepNumber']}: {step['description']}**
Calculation: {step['calculation']}
"""
            if step.get('explanation'):
                prompt += f"Explanation: {step['explanation']}\n"
            prompt += "\n"
        
        prompt += """
# Task
Check each step of the student's solution. For each step, provide:
1. Is the step correct? (Yes/No/Partial)
2. Feedback (1-2 sentences explaining what's right/wrong)
3. Marks for this step (if applicable)

Format your response as:

STEP 1:
Correct: [Yes/No/Partial]
Feedback: [Your feedback]
Marks: [X/Y]

STEP 2:
...

OVERALL:
Total Steps Correct: X
Total Steps: Y
Overall Feedback: [2-3 sentences of overall assessment]
Marks Awarded: X
Total Marks: Y

Be encouraging and constructive. Highlight what the student did well, even if there are errors.
"""
        
        return prompt
    
    def _parse_ai_response(self, response: str, num_steps: int) -> Dict:
        """Parse the AI's feedback response"""
        
        step_feedback = []
        overall_feedback = ""
        marks_awarded = 0
        total_marks = num_steps  # Default: 1 mark per step
        
        try:
            lines = response.split('\n')
            current_step = None
            
            for line in lines:
                line = line.strip()
                
                if line.startswith('STEP '):
                    if current_step:
                        step_feedback.append(current_step)
                    
                    step_num = int(line.split(':')[0].replace('STEP', '').strip())
                    current_step = {
                        "stepNumber": step_num,
                        "isCorrect": None,
                        "feedback": "",
                        "marks": 0
                    }
                
                elif current_step and line.startswith('Correct:'):
                    correctness = line.replace('Correct:', '').strip().lower()
                    if 'yes' in correctness:
                        current_step["isCorrect"] = True
                        current_step["marks"] = 1
                    elif 'no' in correctness:
                        current_step["isCorrect"] = False
                        current_step["marks"] = 0
                    else:  # Partial
                        current_step["isCorrect"] = "partial"
                        current_step["marks"] = 0.5
                
                elif current_step and line.startswith('Feedback:'):
                    current_step["feedback"] = line.replace('Feedback:', '').strip()
                
                elif current_step and line.startswith('Marks:'):
                    try:
                        marks_text = line.replace('Marks:', '').strip()
                        if '/' in marks_text:
                            awarded, total = marks_text.split('/')
                            current_step["marks"] = float(awarded)
                    except:
                        pass
                
                elif line.startswith('OVERALL:'):
                    if current_step:
                        step_feedback.append(current_step)
                        current_step = None
                
                elif line.startswith('Overall Feedback:'):
                    overall_feedback = line.replace('Overall Feedback:', '').strip()
                
                elif line.startswith('Marks Awarded:'):
                    try:
                        marks_awarded = float(line.split(':')[1].strip())
                    except:
                        pass
                
                elif line.startswith('Total Marks:'):
                    try:
                        total_marks = float(line.split(':')[1].strip())
                    except:
                        pass
            
            # Add last step if exists
            if current_step:
                step_feedback.append(current_step)
            
            # Calculate marks if not provided
            if marks_awarded == 0:
                marks_awarded = sum(s.get("marks", 0) for s in step_feedback)
            
        except Exception as e:
            logging.error(f"Error parsing AI response: {str(e)}")
            # Return basic feedback
            step_feedback = [
                {
                    "stepNumber": i + 1,
                    "isCorrect": None,
                    "feedback": "Unable to parse feedback for this step",
                    "marks": 0
                }
                for i in range(num_steps)
            ]
        
        return {
            "steps": step_feedback,
            "overall": overall_feedback or "Solution checked. See individual step feedback above.",
            "marks_awarded": marks_awarded,
            "total_marks": total_marks
        }

# Global instance
step_checker = None

def get_step_checker(api_key: str) -> StepByStepChecker:
    """Get or create step checker instance"""
    global step_checker
    if step_checker is None:
        step_checker = StepByStepChecker(api_key)
    return step_checker
