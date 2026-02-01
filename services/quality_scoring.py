"""Quality scoring rubric for AI-generated questions"""


class QuestionQualityScorer:
    """Score question quality based on multiple criteria"""
    
    CRITERIA = {
        "curriculum_alignment": {
            "weight": 25,
            "description": "Alignment with curriculum objectives and exam board specifications"
        },
        "clarity": {
            "weight": 20,
            "description": "Question is clear, unambiguous, and well-structured"
        },
        "mark_scheme_quality": {
            "weight": 20,
            "description": "Mark scheme is detailed, specific, and fair"
        },
        "difficulty_appropriateness": {
            "weight": 15,
            "description": "Difficulty matches the specified level and key stage"
        },
        "assessment_value": {
            "weight": 10,
            "description": "Question effectively assesses understanding, not just recall"
        },
        "originality": {
            "weight": 10,
            "description": "Question is original and not derivative of common exam questions"
        }
    }
    
    def score_question(self, question: dict, context: dict) -> tuple:
        """
        Score a question and provide detailed feedback
        
        Args:
            question: The generated question dict
            context: Generation context (subject, key_stage, difficulty, etc.)
            
        Returns:
            (overall_score, quality_notes)
        """
        scores = {}
        notes = []
        
        # 1. Curriculum Alignment (25 points)
        curriculum_score = self._score_curriculum_alignment(question, context)
        scores["curriculum_alignment"] = curriculum_score
        if curriculum_score >= 20:
            notes.append("✓ Strong curriculum alignment")
        elif curriculum_score >= 15:
            notes.append("~ Adequate curriculum alignment")
        else:
            notes.append("✗ Weak curriculum alignment - check specification")
        
        # 2. Clarity (20 points)
        clarity_score = self._score_clarity(question)
        scores["clarity"] = clarity_score
        if clarity_score >= 16:
            notes.append("✓ Clear and well-structured")
        elif clarity_score >= 12:
            notes.append("~ Generally clear, minor ambiguities")
        else:
            notes.append("✗ Needs improvement for clarity")
        
        # 3. Mark Scheme Quality (20 points)
        mark_scheme_score = self._score_mark_scheme(question)
        scores["mark_scheme_quality"] = mark_scheme_score
        if mark_scheme_score >= 16:
            notes.append("✓ Detailed, specific mark scheme")
        elif mark_scheme_score >= 12:
            notes.append("~ Adequate mark scheme")
        else:
            notes.append("✗ Mark scheme needs more detail")
        
        # 4. Difficulty Appropriateness (15 points)
        difficulty_score = self._score_difficulty(question, context)
        scores["difficulty_appropriateness"] = difficulty_score
        if difficulty_score >= 12:
            notes.append("✓ Appropriate difficulty level")
        elif difficulty_score >= 9:
            notes.append("~ Difficulty may need adjustment")
        else:
            notes.append("✗ Difficulty mismatch")
        
        # 5. Assessment Value (10 points)
        assessment_score = self._score_assessment_value(question, context)
        scores["assessment_value"] = assessment_score
        if assessment_score >= 8:
            notes.append("✓ Assesses higher-order skills")
        elif assessment_score >= 6:
            notes.append("~ Mix of recall and understanding")
        else:
            notes.append("✗ Focuses mainly on recall")
        
        # 6. Originality (10 points)
        originality_score = self._score_originality(question)
        scores["originality"] = originality_score
        if originality_score >= 8:
            notes.append("✓ Original question design")
        elif originality_score >= 6:
            notes.append("~ Fairly standard question type")
        else:
            notes.append("~ Very common question format")
        
        # Calculate overall score
        overall_score = sum(scores.values())
        
        # Add overall grade
        if overall_score >= 85:
            notes.insert(0, "🌟 Excellent quality - ready to use")
        elif overall_score >= 70:
            notes.insert(0, "✓ Good quality - minor edits recommended")
        elif overall_score >= 55:
            notes.insert(0, "~ Acceptable - review before use")
        else:
            notes.insert(0, "⚠ Needs significant improvement")
        
        return overall_score, notes
    
    def _score_curriculum_alignment(self, question: dict, context: dict) -> int:
        """Score curriculum alignment (max 25 points)"""
        score = 0
        
        # Base score for having required fields
        if question.get("subject") == context.get("subject"):
            score += 5
        if question.get("key_stage") == context.get("key_stage"):
            score += 5
        if question.get("topic_tags"):
            score += 5
        
        # Check if question type matches curriculum expectations
        question_type = question.get("question_type", "")
        if context.get("question_type") in question_type or question_type in context.get("question_type", ""):
            score += 5
        
        # Check for appropriate command words
        text = question.get("question_text", "").lower()
        command_words = ["calculate", "explain", "describe", "evaluate", "analyse", "assess", "compare", "discuss"]
        if any(word in text for word in command_words):
            score += 5
        
        return min(score, 25)
    
    def _score_clarity(self, question: dict) -> int:
        """Score question clarity (max 20 points)"""
        score = 0
        text = question.get("question_text", "")
        
        # Length check - not too short, not too long
        if 50 <= len(text) <= 500:
            score += 5
        elif 20 <= len(text) < 50 or 500 < len(text) <= 800:
            score += 3
        
        # Has clear instruction
        if any(word in text.lower() for word in ["calculate", "find", "show", "explain", "describe", "state", "give"]):
            score += 5
        
        # Mentions marks allocation (if multi-part)
        if "marks" in text.lower() or any(f"({i})" in text or f"[{i}]" in text for i in range(1, 6)):
            score += 3
        
        # Not overly complex sentence structure
        sentences = text.split(".")
        if len(sentences) <= 5:
            score += 4
        elif len(sentences) <= 8:
            score += 2
        
        # Has necessary context
        if len(text.split()) >= 15:  # At least 15 words
            score += 3
        
        return min(score, 20)
    
    def _score_mark_scheme(self, question: dict) -> int:
        """Score mark scheme quality (max 20 points)"""
        score = 0
        mark_scheme = question.get("mark_scheme", [])
        
        if not mark_scheme:
            return 0
        
        # Check if mark_scheme is a list (structured)
        if isinstance(mark_scheme, list):
            score += 5
            
            # Check each mark point
            total_marks = 0
            for item in mark_scheme:
                if isinstance(item, dict):
                    # Has mark value
                    if "mark" in item:
                        total_marks += item.get("mark", 0)
                        score += 2
                    # Has clear credit point
                    if "point" in item and len(item.get("point", "")) > 10:
                        score += 2
                    # Has alternatives
                    if item.get("allowable_equivalents"):
                        score += 1
            
            # Marks add up correctly
            if total_marks == question.get("marks_total", 0):
                score += 3
        else:
            # String mark scheme - basic scoring
            if len(str(mark_scheme)) > 50:
                score += 5
            if len(str(mark_scheme)) > 100:
                score += 5
        
        return min(score, 20)
    
    def _score_difficulty(self, question: dict, context: dict) -> int:
        """Score difficulty appropriateness (max 15 points)"""
        score = 10  # Base score
        
        difficulty = context.get("difficulty", "Medium")
        text = question.get("question_text", "")
        marks = question.get("marks_total", 0)
        
        # Check marks align with difficulty
        if difficulty == "Easy" and 1 <= marks <= 3:
            score += 5
        elif difficulty == "Medium" and 3 <= marks <= 6:
            score += 5
        elif difficulty == "Hard" and marks >= 5:
            score += 5
        else:
            score += 2  # Partial credit
        
        return min(score, 15)
    
    def _score_assessment_value(self, question: dict, context: dict) -> int:
        """Score assessment value (max 10 points)"""
        score = 0
        text = question.get("question_text", "").lower()
        
        # Check for higher-order thinking skills
        higher_order = ["explain", "analyse", "evaluate", "compare", "assess", "justify", "discuss"]
        lower_order = ["state", "name", "list", "identify"]
        
        if any(word in text for word in higher_order):
            score += 6
        elif any(word in text for word in lower_order):
            score += 3
        
        # Multi-step questions are better
        if "show" in text or "hence" in text or any(f"({chr(i)})" in text for i in range(ord('a'), ord('e'))):
            score += 4
        
        return min(score, 10)
    
    def _score_originality(self, question: dict) -> int:
        """Score originality (max 10 points)"""
        score = 7  # Base score - assume reasonable originality
        
        # Check for specific, contextual scenarios
        text = question.get("question_text", "")
        if any(word in text for word in ["student", "scientist", "engineer", "researcher", "investigation"]):
            score += 2
        
        # Has a diagram prompt (shows creativity)
        if question.get("diagram_prompt"):
            score += 1
        
        return min(score, 10)


# Global instance
quality_scorer = QuestionQualityScorer()
