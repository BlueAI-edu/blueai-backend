import os
import logging
import json
import openai

async def get_example_answers(db, question_id: str, teacher_owner_id: str) -> dict:
    """Get example answers for a question"""
    examples = await db.example_answers.find(
        {"question_id": question_id, "teacher_owner_id": teacher_owner_id},
        {"_id": 0}
    ).to_list(20)  # Limit to 20 examples
    
    good_examples = [e for e in examples if e.get("example_type") == "good"]
    bad_examples = [e for e in examples if e.get("example_type") == "bad"]
    
    return {
        "good": good_examples[:5],  # Use up to 5 good examples
        "bad": bad_examples[:5]      # Use up to 5 bad examples
    }

def format_examples_for_prompt(examples: dict, max_marks: int) -> str:
    """Format example answers for the AI prompt"""
    if not examples["good"] and not examples["bad"]:
        return ""
    
    example_text = "\n\n=== CALIBRATION EXAMPLES ===\n"
    example_text += "Use these examples to calibrate your marking. They show what the teacher considers good and poor answers.\n"
    
    if examples["good"]:
        example_text += "\n--- GOOD ANSWER EXAMPLES (aim for this quality) ---\n"
        for i, ex in enumerate(examples["good"], 1):
            example_text += f"\nGood Example {i}:\n"
            example_text += f"Answer: {ex['answer_text'][:500]}{'...' if len(ex['answer_text']) > 500 else ''}\n"
            if ex.get("score") is not None:
                example_text += f"Score: {ex['score']}/{max_marks}\n"
            if ex.get("explanation"):
                example_text += f"Why good: {ex['explanation']}\n"
    
    if examples["bad"]:
        example_text += "\n--- POOR ANSWER EXAMPLES (mark these low) ---\n"
        for i, ex in enumerate(examples["bad"], 1):
            example_text += f"\nPoor Example {i}:\n"
            example_text += f"Answer: {ex['answer_text'][:500]}{'...' if len(ex['answer_text']) > 500 else ''}\n"
            if ex.get("score") is not None:
                example_text += f"Score: {ex['score']}/{max_marks}\n"
            if ex.get("explanation"):
                example_text += f"Why poor: {ex['explanation']}\n"
    
    return example_text

async def mark_submission_enhanced(question: dict, student_name: str, answer_text: str, attempt_id: str, examples: dict = None) -> dict:
    """Enhanced marking with detailed breakdown, confidence scores, and review flags"""
    api_key = os.environ.get('OPENAI_API_KEY')
    
    # Format examples if provided
    examples_section = ""
    if examples:
        examples_section = format_examples_for_prompt(examples, question['max_marks'])
    
    # Parse mark scheme into points for detailed breakdown
    mark_scheme = question['mark_scheme']
    
    marking_prompt = f"""You are an expert examiner providing detailed, calibrated marking.

=== QUESTION DETAILS ===
Subject: {question['subject']}
Exam Type: {question['exam_type']}
Question: {question['question_text']}
Total Marks Available: {question['max_marks']}

=== MARK SCHEME ===
{mark_scheme}
{examples_section}

=== STUDENT'S ANSWER ===
Student Name: {student_name}
Answer:
{answer_text}

=== YOUR TASK ===
Provide detailed marking with:

1. **MARK_BREAKDOWN**: For EACH point in the mark scheme, state whether the student achieved it.
   Format as JSON array: [{{"point": "mark scheme point", "marks_available": X, "marks_awarded": Y, "evidence": "quote from student answer or 'not addressed'"}}]

2. **TOTAL_SCORE**: Sum of marks awarded (0 to {question['max_marks']})

3. **CONFIDENCE**: Your confidence in this marking (0.0 to 1.0). Lower if:
   - Answer is ambiguous or unclear
   - Answer is borderline between grades
   - Answer uses unconventional approaches
   - Mark scheme interpretation is unclear
   - Very short or very long answer

4. **NEEDS_REVIEW**: true/false - Flag for teacher review if:
   - Confidence below 0.7
   - Answer may contain copied content
   - Unusual or creative interpretation
   - Borderline score (within 10% of pass/fail threshold)
   - Student may need pastoral support (concerning content)

5. **REVIEW_REASONS**: If NEEDS_REVIEW is true, list specific reasons as JSON array

6. **WWW**: 2-3 specific strengths (semicolon-separated). Use {student_name}'s name. Be specific.

7. **NEXT_STEPS**: 2-3 specific improvements (semicolon-separated). Use {student_name}'s name. Be specific.

8. **FEEDBACK**: One supportive paragraph for {student_name}.

=== RESPONSE FORMAT (follow exactly) ===
MARK_BREAKDOWN: [JSON array of mark allocation]
TOTAL_SCORE: [number]
CONFIDENCE: [0.0-1.0]
NEEDS_REVIEW: [true/false]
REVIEW_REASONS: [JSON array or empty array]
WWW: [Point 1; Point 2; Point 3]
NEXT_STEPS: [Step 1; Step 2; Step 3]
FEEDBACK: [paragraph]"""
    
    if not api_key:
        logging.error("OPENAI_API_KEY not set - AI marking unavailable")
        return {
            "score": 0, "www": "", "next_steps": "", "overall_feedback": "AI marking unavailable - OPENAI_API_KEY not configured",
            "mark_breakdown": [], "needs_review": True, "review_reasons": ["AI marking unavailable"], "ai_confidence": 0.0
        }

    try:
        client = openai.AsyncOpenAI(api_key=api_key)
        llm_response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a meticulous examiner who provides detailed, fair marking with clear justifications."},
                {"role": "user", "content": marking_prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )
        response = llm_response.choices[0].message.content
    except Exception as e:
        logging.error(f"AI marking failed: {str(e)}")
        return {
            "score": 0, "www": "", "next_steps": "", "overall_feedback": f"AI marking failed: {str(e)}",
            "mark_breakdown": [], "needs_review": True, "review_reasons": [f"AI error: {str(e)}"], "ai_confidence": 0.0
        }

    # Parse response
    result = {
        "score": 0,
        "www": "",
        "next_steps": "",
        "overall_feedback": "",
        "mark_breakdown": [],
        "needs_review": False,
        "review_reasons": [],
        "ai_confidence": 0.5
    }
    
    for line in response.split('\n'):
        line = line.strip()
        
        if line.startswith('MARK_BREAKDOWN:'):
            try:
                json_str = line.replace('MARK_BREAKDOWN:', '').strip()
                result["mark_breakdown"] = json.loads(json_str)
            except:
                # Try to find JSON in the line
                start = line.find('[')
                end = line.rfind(']') + 1
                if start != -1 and end > start:
                    try:
                        result["mark_breakdown"] = json.loads(line[start:end])
                    except:
                        pass
                        
        elif line.startswith('TOTAL_SCORE:'):
            try:
                result["score"] = int(line.replace('TOTAL_SCORE:', '').strip())
            except:
                pass
                
        elif line.startswith('CONFIDENCE:'):
            try:
                conf = float(line.replace('CONFIDENCE:', '').strip())
                result["ai_confidence"] = max(0.0, min(1.0, conf))
            except:
                pass
                
        elif line.startswith('NEEDS_REVIEW:'):
            val = line.replace('NEEDS_REVIEW:', '').strip().lower()
            result["needs_review"] = val == 'true'
            
        elif line.startswith('REVIEW_REASONS:'):
            try:
                json_str = line.replace('REVIEW_REASONS:', '').strip()
                result["review_reasons"] = json.loads(json_str)
            except:
                pass
                
        elif line.startswith('WWW:'):
            result["www"] = line.replace('WWW:', '').strip()
            
        elif line.startswith('NEXT_STEPS:'):
            result["next_steps"] = line.replace('NEXT_STEPS:', '').strip()
            
        elif line.startswith('FEEDBACK:'):
            result["overall_feedback"] = line.replace('FEEDBACK:', '').strip()
    
    # Auto-flag for review if confidence is low
    if result["ai_confidence"] < 0.7 and not result["needs_review"]:
        result["needs_review"] = True
        if "Low AI confidence" not in result["review_reasons"]:
            result["review_reasons"].append(f"Low AI confidence: {result['ai_confidence']:.2f}")
    
    # Ensure score is within bounds
    result["score"] = max(0, min(question['max_marks'], result["score"]))
    
    return result


# Keep original function for backward compatibility
async def mark_submission(question: dict, student_name: str, answer_text: str, attempt_id: str) -> dict:
    """Original marking function - calls enhanced version with no examples"""
    result = await mark_submission_enhanced(question, student_name, answer_text, attempt_id, examples=None)
    
    # Return only the original fields for backward compatibility
    return {
        "score": result["score"],
        "www": result["www"],
        "next_steps": result["next_steps"],
        "overall_feedback": result["overall_feedback"],
        "mark_breakdown": result.get("mark_breakdown", []),
        "needs_review": result.get("needs_review", False),
        "review_reasons": result.get("review_reasons", []),
        "ai_confidence": result.get("ai_confidence", 0.5)
    }
