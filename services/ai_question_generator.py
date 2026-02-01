"""AI Question Generator Service with LaTeX Support"""
import os
import json
import logging
from typing import Dict, List, Any, Optional
from emergentintegrations.llm.chat import LlmChat, UserMessage
from services.mark_scheme_templates import get_mark_scheme_template, format_mark_scheme_guidance
from services.quality_scoring import quality_scorer

logger = logging.getLogger(__name__)


class AIQuestionGenerator:
    """Generate curriculum-aligned questions with LaTeX formatting"""
    
    def __init__(self):
        self.api_key = os.environ.get('EMERGENT_LLM_KEY')
        if not self.api_key:
            raise ValueError("EMERGENT_LLM_KEY not found in environment")
    
    async def generate_questions(
        self,
        subject: str,
        key_stage: str,
        exam_board: str,
        tier: Optional[str],
        topic: str,
        subtopic: Optional[str],
        difficulty: str,
        question_type: str,
        marks: int,
        num_questions: int,
        include_latex: bool,
        include_diagrams: str,
        calculator_allowed: bool,
        strictness: str,
        command_words: Optional[str],
        question_context: str
    ) -> List[Dict[str, Any]]:
        """Generate questions based on teacher specifications"""
        
        # Build comprehensive prompt
        prompt = self._build_prompt(
            subject=subject,
            key_stage=key_stage,
            exam_board=exam_board,
            tier=tier,
            topic=topic,
            subtopic=subtopic,
            difficulty=difficulty,
            question_type=question_type,
            marks=marks,
            num_questions=num_questions,
            include_latex=include_latex,
            include_diagrams=include_diagrams,
            calculator_allowed=calculator_allowed,
            strictness=strictness,
            command_words=command_words,
            question_context=question_context
        )
        
        # Create LLM chat session
        chat = LlmChat(
            api_key=self.api_key,
            session_id=f"question_gen_{topic}_{key_stage}",
            system_message=self._get_system_message(subject, include_latex, strictness)
        ).with_model("openai", "gpt-4o")
        
        # Get AI response
        response = await chat.send_message(UserMessage(text=prompt))
        
        # Parse and validate response
        questions = self._parse_response(response, subject, key_stage, exam_board, tier, topic, marks)
        
        return questions
    
    def _get_system_message(self, subject: str, include_latex: bool, strictness: str) -> str:
        """Get system message for AI"""
        latex_instruction = ""
        if include_latex and subject.lower() in ['maths', 'physics', 'chemistry', 'combined science']:
            latex_instruction = """

LATEX FORMATTING RULES:
- Use inline math: $x^2$, $3\\times10^4$, $\\sqrt{3}$
- Use display math: $$ ... $$ for multi-step solutions
- Fractions: \\frac{a}{b}
- Indices: a^n, x^{-2}, $10^{-3}$
- Vectors: \\vec{v}, column vectors with \\begin{pmatrix} a \\\\ b \\end{pmatrix}
- Inequalities: \\le, \\ge, <, >
- Trig functions: \\sin, \\cos, \\tan
- Chemistry: CO_2, H_2O, CH_3COOH
- Physics equations: $v = u + at$, $F = ma$
- Scientific notation: $3.2 \\times 10^5$
"""
        
        strictness_instruction = ""
        if strictness == "strict":
            strictness_instruction = """

STRICTNESS: STRICT MODE
- Follow exact exam board specifications
- Use precise command words from the specification
- Match mark scheme detail to real exam standards
- Include all required assessment objectives
- NO copyrighted or real past-paper content
"""
        
        return f"""You are an expert {subject} teacher and examiner creating high-quality assessment questions.

You MUST:
1. Generate original questions (NEVER copy real past papers)
2. Align with UK {subject} curriculum requirements
3. Create detailed, mark-scheme aligned questions
4. Include model answers and common mistakes
5. Provide quality scoring and notes{latex_instruction}{strictness_instruction}

Output format: Valid JSON array only."""
    
    def _build_prompt(self, **kwargs) -> str:
        """Build detailed generation prompt with mark scheme templates"""
        subject = kwargs['subject']
        key_stage = kwargs['key_stage']
        exam_board = kwargs['exam_board']
        tier = kwargs.get('tier', 'N/A')
        topic = kwargs['topic']
        subtopic = kwargs.get('subtopic', '')
        difficulty = kwargs['difficulty']
        question_type = kwargs['question_type']
        marks = kwargs['marks']
        num_questions = kwargs['num_questions']
        include_latex = kwargs['include_latex']
        include_diagrams = kwargs['include_diagrams']
        calculator_allowed = kwargs['calculator_allowed']
        command_words = kwargs.get('command_words', '')
        question_context = kwargs['question_context']
        
        # Get subject-specific mark scheme template
        mark_scheme_template = get_mark_scheme_template(subject, question_type)
        mark_scheme_guidance = format_mark_scheme_guidance(mark_scheme_template)
        
        diagram_instruction = ""
        if include_diagrams != "none":
            if include_diagrams == "description":
                diagram_instruction = """\n- Include a 'diagram_prompt' field with a detailed text description of any required diagram
  Example: "Draw a right-angled triangle ABC where angle B = 90°, AB = 8cm, BC = 6cm. Label all sides and angles."
  OR: "Sketch a velocity-time graph showing: constant acceleration 0-3s (v: 0 to 15 m/s), constant velocity 3-5s, deceleration 5-8s (v: 15 to 0 m/s). Label axes with units.\""""
            else:
                diagram_instruction = """\n- Include a 'diagram_prompt' field with structured instructions for generating/drawing the diagram
  Focus on: shapes, measurements, labels, axes, scales, annotations
  Be specific about what to show but do not include copyrighted images"""
        
        command_word_instruction = ""
        if command_words:
            command_word_instruction = f"\n- Use these command words: {command_words}"
        
        mark_scheme_instruction = ""
        if mark_scheme_guidance:
            mark_scheme_instruction = f"""\n\nMARK SCHEME TEMPLATE FOR THIS QUESTION TYPE:
{mark_scheme_guidance}

Follow this template when creating your mark scheme. Use the specified mark types and structure."""
        
        prompt = f"""Generate {num_questions} original {subject} question(s) with these specifications:

SUBJECT: {subject}
KEY STAGE: {key_stage}
EXAM BOARD: {exam_board}
TIER: {tier}
TOPIC: {topic}
SUBTOPIC: {subtopic or 'General'}
DIFFICULTY: {difficulty}
QUESTION TYPE: {question_type}
MARKS: {marks}
CALCULATOR: {'Allowed' if calculator_allowed else 'Not allowed'}
CONTEXT: {question_context}{command_word_instruction}{diagram_instruction}{mark_scheme_instruction}

For each question, provide this EXACT JSON structure:
{{
  "question_title": "Brief title",
  "question_text": "{'LaTeX-formatted' if include_latex else 'Plain text'} question",
  "marks_total": {marks},
  "question_type": "{question_type}",
  "subject": "{subject}",
  "key_stage": "{key_stage}",
  "exam_board": "{exam_board}",
  "tier": "{tier}",
  "topic_tags": ["{topic}"{', "' + subtopic + '"' if subtopic else ''}],
  "mark_scheme": [
    {{
      "mark": 1,
      "point": "Credit point with {'LaTeX if needed' if include_latex else 'clear description'}",
      "allowable_equivalents": ["alternative answers"],
      "notes": "Examiner notes"
    }}
  ],
  "model_answer": "{'LaTeX-enabled' if include_latex else 'Clear'} model answer",
  "common_mistakes": ["mistake 1", "mistake 2"],
  "keywords": ["key", "terms"],
  {'"diagram_prompt": "Diagram description",' if include_diagrams != 'none' else ''}
  "quality_score": 85,
  "quality_notes": ["Meets curriculum objectives", "Clear progression"]
}}

Return ONLY a valid JSON array: [{{}}, {{}}, ...]
NO markdown, NO code blocks, ONLY the JSON array."""
        
        return prompt
    
    def _parse_response(self, response: str, subject: str, key_stage: str, exam_board: str, tier: Optional[str], topic: str, marks: int) -> List[Dict[str, Any]]:
        """Parse and validate AI response"""
        try:
            # Clean response - remove markdown code blocks if present
            response = response.strip()
            if response.startswith('```'):
                # Remove ```json and ``` markers
                lines = response.split('\n')
                response = '\n'.join(lines[1:-1] if len(lines) > 2 else lines)
            
            questions = json.loads(response)
            
            # Ensure it's a list
            if isinstance(questions, dict):
                questions = [questions]
            
            # Validate, score, and normalize each question
            validated_questions = []
            for q in questions:
                validated_q = self._validate_question(q, subject, key_stage, exam_board, tier, topic, marks)
                if validated_q:
                    # Add quality scoring
                    context = {
                        'subject': subject,
                        'key_stage': key_stage,
                        'difficulty': validated_q.get('difficulty', 'Medium'),
                        'question_type': validated_q.get('question_type', '')
                    }
                    quality_score, quality_notes = quality_scorer.score_question(validated_q, context)
                    validated_q['quality_score'] = quality_score
                    validated_q['quality_notes'] = quality_notes
                    
                    validated_questions.append(validated_q)
            
            return validated_questions
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Response was: {response[:500]}")
            raise ValueError("AI generated invalid JSON. Please try again.")
        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
            raise ValueError(f"Failed to process AI response: {str(e)}")
    
    def _validate_question(self, q: Dict[str, Any], subject: str, key_stage: str, exam_board: str, tier: Optional[str], topic: str, marks: int) -> Optional[Dict[str, Any]]:
        """Validate and normalize a single question"""
        required_fields = ['question_text', 'marks_total', 'mark_scheme']
        
        for field in required_fields:
            if field not in q:
                logger.warning(f"Question missing required field: {field}")
                return None
        
        # Normalize structure
        normalized = {
            'question_title': q.get('question_title', f"{subject} - {topic}"),
            'question_text': q['question_text'],
            'marks_total': q['marks_total'],
            'question_type': q.get('question_type', 'general'),
            'subject': subject,
            'key_stage': key_stage,
            'exam_board': exam_board,
            'tier': tier or 'N/A',
            'topic_tags': q.get('topic_tags', [topic]),
            'mark_scheme': q['mark_scheme'],
            'model_answer': q.get('model_answer', ''),
            'common_mistakes': q.get('common_mistakes', []),
            'keywords': q.get('keywords', []),
            'diagram_prompt': q.get('diagram_prompt', ''),
            'quality_score': q.get('quality_score', 0),
            'quality_notes': q.get('quality_notes', []),
            'source': 'ai_generated',
            'calculator_allowed': q.get('calculator_allowed', False)
        }
        
        return normalized


# Global instance
ai_question_generator = AIQuestionGenerator()
