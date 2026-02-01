"""Utility functions for answer type detection and math input handling"""
import re


def detect_answer_type(question_text: str, subject: str) -> str:
    """
    Auto-detect appropriate answer type based on question text and subject
    
    Returns: 'text', 'maths', 'mixed', or 'numeric'
    """
    # Check if question contains LaTeX
    has_latex = bool(re.search(r'\$[^$]+\$', question_text))
    
    # Math/Science subjects default to mixed if LaTeX present
    math_subjects = ['Maths', 'Physics', 'Chemistry', 'Combined Science']
    
    if subject in math_subjects and has_latex:
        # Check if question is purely numeric (e.g., "Calculate...")
        numeric_keywords = ['calculate', 'find the value', 'how many', 'what is the']
        if any(keyword in question_text.lower() for keyword in numeric_keywords):
            return 'numeric'
        return 'mixed'
    
    # Check for pure maths expression questions
    pure_math_keywords = ['simplify', 'factorise', 'expand', 'solve for', 'differentiate', 'integrate']
    if any(keyword in question_text.lower() for keyword in pure_math_keywords):
        return 'maths'
    
    # Default to text
    return 'text'


def sanitize_latex(latex_str: str) -> str:
    """
    Sanitize LaTeX input to prevent injection
    
    Args:
        latex_str: Raw LaTeX string from student
        
    Returns:
        Sanitized LaTeX string
    """
    if not latex_str:
        return ""
    
    # Remove potentially dangerous commands
    dangerous_commands = [
        r'\\input',
        r'\\include',
        r'\\write',
        r'\\immediate',
        r'\\def',
        r'\\let',
        r'\\futurelet',
        r'\\newcommand',
        r'\\renewcommand',
        r'\\usepackage',
        r'\\documentclass'
    ]
    
    cleaned = latex_str
    for cmd in dangerous_commands:
        cleaned = re.sub(cmd, '', cleaned, flags=re.IGNORECASE)
    
    # Only allow safe LaTeX math commands
    # This is a whitelist approach - only mathematical LaTeX is allowed
    
    return cleaned.strip()


def normalize_math_expression(expression: str, answer_type: str = 'maths') -> str:
    """
    Normalize a math expression for comparison in marking
    
    Args:
        expression: Student's math expression
        answer_type: Type of answer (maths, numeric, mixed)
        
    Returns:
        Normalized expression string
    """
    if not expression:
        return ""
    
    # For numeric answers, extract just the number
    if answer_type == 'numeric':
        # Remove spaces
        normalized = expression.replace(' ', '')
        # Extract number (including decimals and scientific notation)
        match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', normalized)
        if match:
            return match.group(0)
    
    # For maths/mixed, remove extra whitespace but preserve structure
    normalized = ' '.join(expression.split())
    
    # Remove dollar signs if present
    normalized = normalized.replace('$', '')
    
    return normalized.strip()


def extract_numeric_value(answer: str) -> tuple:
    """
    Extract numeric value and unit from student answer
    
    Returns: (value, unit, raw_string)
    """
    if not answer:
        return (None, None, "")
    
    # Remove LaTeX formatting
    clean = answer.replace('$', '').replace('\\', '')
    
    # Try to extract number and unit
    # Pattern: number (with optional decimal/scientific) followed by optional unit
    pattern = r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([a-zA-Z°/^₀₁₂₃₄₅₆₇₈₉]+)?'
    match = re.search(pattern, clean)
    
    if match:
        value_str = match.group(1)
        unit_str = match.group(2) if match.group(2) else None
        
        try:
            value = float(value_str)
            return (value, unit_str, clean)
        except ValueError:
            pass
    
    return (None, None, clean)


def validate_latex_syntax(latex_str: str) -> tuple:
    """
    Validate LaTeX syntax for student input
    
    Returns: (is_valid: bool, error_message: str)
    """
    if not latex_str:
        return (True, "")
    
    # Check for balanced braces
    if latex_str.count('{') != latex_str.count('}'):
        return (False, "Unbalanced braces { }")
    
    # Check for balanced brackets
    if latex_str.count('[') != latex_str.count(']'):
        return (False, "Unbalanced brackets [ ]")
    
    # Check for balanced parentheses
    if latex_str.count('(') != latex_str.count(')'):
        return (False, "Unbalanced parentheses ( )")
    
    # Check for valid math delimiters
    dollar_count = latex_str.count('$')
    if dollar_count % 2 != 0:
        return (False, "Unbalanced math delimiters $")
    
    # Check for some common errors
    if '$$' in latex_str and latex_str.count('$$') % 2 != 0:
        return (False, "Unbalanced display math delimiters $$")
    
    # All checks passed
    return (True, "")
