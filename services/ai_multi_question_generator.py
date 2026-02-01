"""
AI Multi-Question Generator
Generates multiple questions in one API call for summative assessments
"""

import logging
from typing import List, Dict, Any
from emergentintegrations.llm.chat import LlmChat, UserMessage
import uuid

class AIMultiQuestionGenerator:
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    async def generate_multi_questions(
        self,
        subject: str,
        key_stage: str,
        exam_board: str,
        tier: str,
        topic: str,
        subtopic: str,
        difficulty: str,
        num_questions: int,
        question_types: List[str],
        total_marks: int,
        include_latex: bool,
        calculator_allowed: bool,
        context: str = "mock exam"
    ) -> List[Dict[str, Any]]:
        """
        Generate multiple questions at once
        """
        try:
            # Build the prompt
            prompt = self._build_multi_question_prompt(
                subject=subject,
                key_stage=key_stage,
                exam_board=exam_board,
                tier=tier,
                topic=topic,
                subtopic=subtopic,
                difficulty=difficulty,
                num_questions=num_questions,
                question_types=question_types,
                total_marks=total_marks,
                include_latex=include_latex,
                calculator_allowed=calculator_allowed,
                context=context
            )
            
            # Call AI with improved error handling
            try:
                # Initialize LlmChat with proper parameters
                chat = LlmChat(
                    api_key=self.api_key,
                    session_id=f"ai_question_gen_{str(uuid.uuid4())[:8]}",
                    system_message="You are an expert exam question writer for UK GCSE and A-Level assessments. You MUST respond with valid JSON only. Generate high-quality, exam-standard questions with proper mark schemes."
                )
                
                # Set model to GPT-4o
                chat.with_model("openai", "gpt-4o")
                
                # Send the prompt
                user_message = UserMessage(text=prompt)
                response = await chat.send_message(user_message)
                
                # Log the raw response for debugging
                logging.info(f"AI Response (first 500 chars): {response[:500]}")
                
            except Exception as llm_error:
                logging.error(f"LLM API call failed: {str(llm_error)}")
                # Return fallback questions instead of crashing
                return self._generate_fallback_questions(num_questions)
            
            # Parse response with robust error handling
            try:
                questions = self._parse_multi_question_response(response, num_questions)
                
                # Validate that we got actual questions, not fallback
                if questions and len(questions) > 0:
                    first_question_body = questions[0].get("questionBody", "")
                    if "AI generation failed" in first_question_body or "please edit manually" in first_question_body:
                        logging.warning("AI returned fallback questions, likely due to non-JSON response")
                        raise ValueError("AI did not return valid questions")
                
                return questions
                
            except Exception as parse_error:
                logging.error(f"Failed to parse AI response: {str(parse_error)}")
                logging.error(f"Raw response was: {response[:1000]}")
                # Return fallback questions
                return self._generate_fallback_questions(num_questions)
            
        except Exception as e:
            logging.error(f"Multi-question generation error: {str(e)}")
            # Return fallback questions instead of raising
            return self._generate_fallback_questions(num_questions)
    
    def _build_multi_question_prompt(
        self,
        subject: str,
        key_stage: str,
        exam_board: str,
        tier: str,
        topic: str,
        subtopic: str,
        difficulty: str,
        num_questions: int,
        question_types: List[str],
        total_marks: int,
        include_latex: bool,
        calculator_allowed: bool,
        context: str
    ) -> str:
        """Build prompt for multi-question generation"""
        
        prompt = f"""IMPORTANT: You MUST respond with a valid JSON array ONLY. Do not include any explanatory text, apologies, or commentary. Start your response with [ and end with ].

Generate {num_questions} exam-style questions for a {context}.

**Specification:**
- Subject: {subject}
- Key Stage: {key_stage}
- Exam Board: {exam_board}
- Tier: {tier}
- Topic: {topic}
{f'- Subtopic: {subtopic}' if subtopic else ''}
- Difficulty: {difficulty}
- Total Marks Target: {total_marks} marks (distribute across questions)
- Calculator: {'Allowed' if calculator_allowed else 'Not allowed'}
{f'- LaTeX: Use LaTeX notation for mathematical expressions (enclose in $ symbols)' if include_latex else ''}

**Question Types to Include:**
"""
        
        if question_types and len(question_types) > 0:
            for qt in question_types:
                if qt == "SHORT_ANSWER":
                    prompt += "- Short answer questions (1-3 marks)\n"
                elif qt == "MULTIPLE_CHOICE":
                    prompt += "- Multiple choice questions with 4 options (A-D)\n"
                elif qt == "NUMERIC":
                    prompt += "- Numeric calculation questions\n"
                elif qt == "LONG_RESPONSE":
                    prompt += "- Extended response questions (6+ marks)\n"
                elif qt == "STRUCTURED_WITH_PARTS":
                    prompt += "- Structured questions with sub-parts (a, b, c)\n"
        else:
            prompt += "- Mix of short answer, multiple choice, and calculation questions\n"
        
        prompt += f"""
**Output Format:**
Return a JSON array of {num_questions} questions. Each question must follow this exact structure:

```json
[
  {{
    "questionNumber": 1,
    "questionType": "SHORT_ANSWER" | "MULTIPLE_CHOICE" | "NUMERIC" | "LONG_RESPONSE" | "STRUCTURED_WITH_PARTS",
    "questionBody": "The main question text",
    "maxMarks": 3,
    "subject": "{subject}",
    "topic": "{topic}",
    "difficulty": "{difficulty}",
    "tags": ["tag1", "tag2"],
    "markScheme": "Detailed mark scheme",
    "modelAnswer": "Expected answer",
    "answerType": "TEXT" | "NUMERIC" | "MATHS",
    "calculatorAllowed": {str(calculator_allowed).lower()},
    "source": "ai_generated",
    
    // FOR MULTIPLE_CHOICE ONLY:
    "options": [
      {{"label": "A", "text": "Option A text", "isCorrect": false}},
      {{"label": "B", "text": "Option B text", "isCorrect": true}},
      {{"label": "C", "text": "Option C text", "isCorrect": false}},
      {{"label": "D", "text": "Option D text", "isCorrect": false}}
    ],
    
    // FOR STRUCTURED_WITH_PARTS ONLY:
    "parts": [
      {{
        "partLabel": "a",
        "partPrompt": "Part (a) question",
        "maxMarks": 2,
        "answerType": "TEXT",
        "markScheme": "Mark scheme for part a"
      }},
      {{
        "partLabel": "b",
        "partPrompt": "Part (b) question",
        "maxMarks": 3,
        "answerType": "NUMERIC",
        "markScheme": "Mark scheme for part b"
      }}
    ]
  }},
  ...
]
```

**Quality Requirements:**
1. Questions must be exam-standard and realistic
2. Mark schemes must be detailed and clear
3. Questions should cover different aspects of the topic
4. Difficulty should be appropriate for {key_stage} {tier} tier
5. Distribute marks appropriately to reach approximately {total_marks} total marks
6. For MCQs, include exactly 4 options (A-D) with one correct answer
7. For structured questions, use logical sub-parts (a, b, c, d...)
{f'8. Use proper LaTeX notation (enclosed in $ symbols) for all mathematical expressions' if include_latex else ''}

CRITICAL: Your response must be ONLY a valid JSON array. Start with [ and end with ]. Do not add any text before or after the JSON. If you cannot generate questions, return an empty array [].
"""
        
        return prompt
    
    def _parse_multi_question_response(self, response: str, num_questions: int) -> List[Dict[str, Any]]:
        """Parse AI response into question objects"""
        import json
        import re
        
        try:
            # Try to extract JSON from the response
            # Look for JSON array in the response
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                json_str = json_match.group(0)
                questions = json.loads(json_str)
                
                # Validate and clean questions
                validated_questions = []
                for i, q in enumerate(questions):
                    if i >= num_questions:
                        break
                    
                    # Ensure required fields
                    validated_q = {
                        "questionNumber": q.get("questionNumber", i + 1),
                        "questionType": q.get("questionType", "SHORT_ANSWER"),
                        "questionBody": q.get("questionBody", ""),
                        "maxMarks": q.get("maxMarks", 1),
                        "subject": q.get("subject", ""),
                        "topic": q.get("topic", ""),
                        "difficulty": q.get("difficulty", "Medium"),
                        "tags": q.get("tags", []),
                        "markScheme": q.get("markScheme", ""),
                        "modelAnswer": q.get("modelAnswer", ""),
                        "answerType": q.get("answerType", "TEXT"),
                        "calculatorAllowed": q.get("calculatorAllowed", False),
                        "source": "ai_generated",
                        "options": q.get("options", []),
                        "parts": q.get("parts", []),
                        "stimulusBlock": None,
                        "allowMultiSelect": False
                    }
                    
                    validated_questions.append(validated_q)
                
                return validated_questions
            else:
                raise ValueError("No valid JSON array found in response")
                
        except Exception as e:
            logging.error(f"Failed to parse multi-question response: {str(e)}")
            # Return fallback questions
            return self._generate_fallback_questions(num_questions)
    
    def _generate_fallback_questions(self, num_questions: int) -> List[Dict[str, Any]]:
        """Generate fallback questions if AI parsing fails"""
        questions = []
        for i in range(num_questions):
            questions.append({
                "questionNumber": i + 1,
                "questionType": "SHORT_ANSWER",
                "questionBody": f"Question {i + 1}: [AI generation failed - please edit manually]",
                "maxMarks": 1,
                "subject": "",
                "topic": "",
                "difficulty": "Medium",
                "tags": [],
                "markScheme": "",
                "modelAnswer": "",
                "answerType": "TEXT",
                "calculatorAllowed": False,
                "source": "ai_generated",
                "options": [],
                "parts": [],
                "stimulusBlock": None,
                "allowMultiSelect": False
            })
        return questions

# Global instance
multi_question_generator = None

def get_multi_question_generator(api_key: str) -> AIMultiQuestionGenerator:
    """Get or create multi-question generator instance"""
    global multi_question_generator
    if multi_question_generator is None:
        multi_question_generator = AIMultiQuestionGenerator(api_key)
    return multi_question_generator
