"""Math equivalence checking and comparison utilities for student answers"""
import re
from sympy import sympify, simplify, expand, factor, latex, N
from sympy.parsing.latex import parse_latex
from sympy.core.sympify import SympifyError


class MathEquivalenceChecker:
    """Check mathematical equivalence between student and model answers"""
    
    def __init__(self):
        self.tolerance = 0.01  # Default 1% tolerance for numeric
    
    def check_equivalence(self, student_answer: str, model_answer: str, answer_type: str = 'maths', tolerance: float = None) -> tuple:
        """
        Check if student answer is mathematically equivalent to model answer
        
        Args:
            student_answer: Student's answer (may contain LaTeX)
            model_answer: Model/correct answer
            answer_type: Type of answer (numeric, maths, mixed)
            tolerance: Tolerance for numeric comparison (optional)
            
        Returns:
            (is_equivalent: bool, explanation: str, confidence: float)
        """
        if tolerance is not None:
            self.tolerance = tolerance
        
        # Clean inputs
        student_clean = self._clean_latex(student_answer)
        model_clean = self._clean_latex(model_answer)
        
        if answer_type == 'numeric':
            return self._check_numeric_equivalence(student_clean, model_clean)
        elif answer_type == 'maths':
            return self._check_algebraic_equivalence(student_clean, model_clean)
        elif answer_type == 'mixed':
            # Try numeric first, then algebraic
            numeric_result = self._check_numeric_equivalence(student_clean, model_clean)
            if numeric_result[0]:
                return numeric_result
            return self._check_algebraic_equivalence(student_clean, model_clean)
        else:
            # Text comparison (exact or close match)
            return self._check_text_equivalence(student_clean, model_clean)
    
    def _clean_latex(self, text: str) -> str:
        """Remove LaTeX formatting and extract mathematical content"""
        if not text:
            return ""
        
        # Remove $ delimiters
        cleaned = text.replace('$$', '').replace('$', '')
        
        # Remove common LaTeX commands that don't affect math
        cleaned = re.sub(r'\\text\{([^}]*)\}', r'\1', cleaned)
        cleaned = re.sub(r'\\mathrm\{([^}]*)\}', r'\1', cleaned)
        
        # Normalize spacing
        cleaned = ' '.join(cleaned.split())
        
        return cleaned.strip()
    
    def _check_numeric_equivalence(self, student: str, model: str) -> tuple:
        """Check numeric equivalence with tolerance"""
        try:
            # Extract numeric values
            student_val = self._extract_number(student)
            model_val = self._extract_number(model)
            
            if student_val is None or model_val is None:
                return (False, "Could not extract numeric value", 0.0)
            
            # Check if within tolerance
            if model_val == 0:
                diff = abs(student_val - model_val)
                is_equiv = diff <= self.tolerance
            else:
                percent_diff = abs((student_val - model_val) / model_val)
                is_equiv = percent_diff <= self.tolerance
            
            if is_equiv:
                return (True, f"Numeric value matches within {self.tolerance*100}% tolerance", 1.0)
            else:
                return (False, f"Numeric value differs by more than tolerance", 0.3)
                
        except Exception as e:
            return (False, f"Error in numeric comparison: {str(e)}", 0.0)
    
    def _check_algebraic_equivalence(self, student: str, model: str) -> tuple:
        """Check algebraic equivalence using SymPy"""
        try:
            # Try to parse as mathematical expressions
            student_expr = sympify(student)
            model_expr = sympify(model)
            
            # Check direct equality
            if student_expr.equals(model_expr):
                return (True, "Algebraically equivalent (direct match)", 1.0)
            
            # Try simplifying both
            student_simp = simplify(student_expr)
            model_simp = simplify(model_expr)
            
            if student_simp.equals(model_simp):
                return (True, "Algebraically equivalent (after simplification)", 0.95)
            
            # Try expanding both
            student_exp = expand(student_expr)
            model_exp = expand(model_expr)
            
            if student_exp.equals(model_exp):
                return (True, "Algebraically equivalent (after expansion)", 0.95)
            
            # Try factoring both
            try:
                student_fact = factor(student_expr)
                model_fact = factor(model_expr)
                
                if student_fact.equals(model_fact):
                    return (True, "Algebraically equivalent (after factoring)", 0.95)
            except:
                pass
            
            # Check if difference is zero
            diff = simplify(student_expr - model_expr)
            if diff == 0:
                return (True, "Algebraically equivalent (difference is zero)", 0.95)
            
            # Not equivalent
            return (False, "Not algebraically equivalent", 0.2)
            
        except SympifyError as e:
            return (False, f"Could not parse mathematical expression: {str(e)}", 0.0)
        except Exception as e:
            return (False, f"Error in algebraic comparison: {str(e)}", 0.0)
    
    def _check_text_equivalence(self, student: str, model: str) -> tuple:
        """Check text equivalence (for text-type answers)"""
        student_lower = student.lower().strip()
        model_lower = model.lower().strip()
        
        if student_lower == model_lower:
            return (True, "Exact match", 1.0)
        
        # Check if one contains the other
        if model_lower in student_lower or student_lower in model_lower:
            return (True, "Partial match", 0.8)
        
        # Calculate simple similarity
        words_student = set(student_lower.split())
        words_model = set(model_lower.split())
        
        if len(words_model) == 0:
            return (False, "Empty model answer", 0.0)
        
        intersection = words_student.intersection(words_model)
        similarity = len(intersection) / len(words_model)
        
        if similarity > 0.7:
            return (True, f"High similarity ({similarity:.0%})", similarity)
        
        return (False, f"Low similarity ({similarity:.0%})", similarity * 0.5)
    
    def _extract_number(self, text: str) -> float:
        """Extract numeric value from text"""
        if not text:
            return None
        
        # Remove common units and text
        text = re.sub(r'[a-zA-Z°]+', '', text)
        
        # Try to find number (including scientific notation)
        pattern = r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?'
        match = re.search(pattern, text)
        
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                pass
        
        # Try using SymPy to evaluate
        try:
            expr = sympify(text)
            return float(N(expr))
        except:
            pass
        
        return None
    
    def check_alternative_forms(self, student: str, acceptable_forms: list, answer_type: str = 'maths') -> tuple:
        """
        Check if student answer matches any acceptable alternative form
        
        Args:
            student: Student answer
            acceptable_forms: List of acceptable answers
            answer_type: Type of answer
            
        Returns:
            (matches: bool, matched_form: str, confidence: float)
        """
        best_match = (False, None, 0.0)
        
        for form in acceptable_forms:
            result = self.check_equivalence(student, form, answer_type)
            if result[0] and result[2] > best_match[2]:
                best_match = (True, form, result[2])
        
        return best_match
    
    def suggest_correction(self, student: str, model: str) -> str:
        """Suggest what might be wrong with student's answer"""
        suggestions = []
        
        try:
            student_expr = sympify(self._clean_latex(student))
            model_expr = sympify(self._clean_latex(model))
            
            # Check for sign errors
            if student_expr == -model_expr:
                suggestions.append("Check the sign - your answer appears to be the negative of the correct answer")
            
            # Check for missing/extra factors
            if simplify(student_expr / model_expr).is_constant():
                suggestions.append("Your answer is off by a constant factor")
            
            # Check for reciprocal
            if simplify(student_expr * model_expr) == 1:
                suggestions.append("Your answer appears to be the reciprocal of the correct answer")
                
        except:
            pass
        
        return " | ".join(suggestions) if suggestions else "Unable to provide specific suggestions"


# Numeric tolerance configuration
TOLERANCE_PRESETS = {
    'strict': 0.001,      # 0.1% - for precise calculations
    'standard': 0.01,     # 1% - default
    'relaxed': 0.05,      # 5% - for rough estimates
    'very_relaxed': 0.10  # 10% - for order of magnitude
}


def get_tolerance_for_question(marks: int, question_type: str) -> float:
    """Get appropriate tolerance based on question characteristics"""
    
    # Higher mark questions typically need more precision
    if marks >= 6:
        return TOLERANCE_PRESETS['strict']
    elif marks >= 3:
        return TOLERANCE_PRESETS['standard']
    else:
        return TOLERANCE_PRESETS['relaxed']


# Global instance
equivalence_checker = MathEquivalenceChecker()
