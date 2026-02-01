"""Subject-specific mark scheme templates for AI Question Generator"""

# Maths Mark Scheme Templates
MATHS_TEMPLATES = {
    "structured_calculation": {
        "mark_types": ["M", "A", "B"],
        "guidelines": """
M marks (Method): Award for correct method or formula
A marks (Accuracy): Award for correct numerical answer (dependent on M mark)
B marks (Basic): Award for recall of facts, formulae, or simple procedures

Example 4-mark calculation:
M1: Correct substitution into formula
M1: Correct rearrangement/algebraic manipulation
A1: Intermediate result correct (depends on M1)
A1: Final answer correct (depends on previous marks)
        """,
        "common_deductions": [
            "No units: -1 mark",
            "Wrong number of significant figures: -1 mark",
            "Arithmetic error without method: no credit",
            "Premature rounding: may lose final A mark"
        ]
    },
    "proof_derivation": {
        "mark_types": ["M", "A", "R"],
        "guidelines": """
M marks: Key steps in proof
A marks: Accurate statement/result
R marks: Reasoning/explanation

Award marks for:
- Clear logical progression
- Correct mathematical notation
- Justification of steps
- Final QED statement
        """,
        "common_deductions": [
            "Assuming what needs to be proved: 0 marks",
            "Lack of clear reasoning: lose R marks",
            "Algebraic errors: lose A marks but may retain M marks"
        ]
    },
    "graph_interpretation": {
        "mark_types": ["B", "M", "A"],
        "guidelines": """
B1: Reading values from graph
M1: Method for gradient/area calculation
A1: Accurate calculation
A1: Interpretation in context
        """,
        "common_deductions": [
            "Reading off graph incorrectly: lose dependent marks",
            "No units on final answer: -1 mark",
            "Lack of context in interpretation: lose final A mark"
        ]
    }
}

# Physics Mark Scheme Templates
PHYSICS_TEMPLATES = {
    "calculation": {
        "mark_types": ["M", "A", "U"],
        "guidelines": """
M marks: Correct formula selection and substitution
A marks: Accurate calculation
U marks: Correct units

Example 3-mark physics calculation:
M1: Correct formula (e.g., F = ma)
M1: Correct substitution with units
A1: Correct answer with correct units (3 sf)
        """,
        "common_deductions": [
            "No units or wrong units: -1 mark",
            "More than 3 sf when not specified: -1 mark",
            "Wrong formula but correct method: may get follow-through",
            "Inconsistent units: 0 marks unless corrected"
        ]
    },
    "explain_describe": {
        "mark_types": ["K", "A"],
        "guidelines": """
K marks: Key physics knowledge points
A marks: Application to the context

Award marks for:
- Correct physics terminology
- Clear cause-and-effect relationships
- Reference to relevant physics principles
- Application to the specific scenario
        """,
        "indicative_points": [
            "Each distinct physics concept = 1 mark",
            "Link between concepts = 1 mark",
            "Quantitative reasoning = 1 mark",
            "Conclusion related to context = 1 mark"
        ]
    },
    "experimental_design": {
        "mark_types": ["M", "D", "S"],
        "guidelines": """
M marks: Identification of variables/apparatus
D marks: Detailed procedure
S marks: Safety/accuracy considerations

Expect:
- Independent, dependent, control variables identified
- Clear step-by-step method
- How to ensure accuracy/precision
- Safety precautions
        """,
        "common_deductions": [
            "Missing control variables: -1 mark",
            "Vague method: lose D marks",
            "No mention of repeats/averages: -1 mark",
            "Safety not addressed: may lose S mark"
        ]
    }
}

# Chemistry Mark Scheme Templates
CHEMISTRY_TEMPLATES = {
    "calculation": {
        "mark_types": ["M", "A"],
        "guidelines": """
M marks: Correct method (mole calculations, Mr, formula)
A marks: Correct answer

Example mole calculation (3 marks):
M1: n = m/M or equivalent
M1: Correct use of M or ratio
A1: Final answer with units to 3 sf
        """,
        "common_deductions": [
            "Wrong Mr used: lose A marks but may keep M marks",
            "Unit conversion error: lose A mark",
            "Premature rounding leading to error: lose A mark",
            "No units: -1 mark"
        ]
    },
    "equation_balancing": {
        "mark_types": ["B", "A"],
        "guidelines": """
B marks: Basic equation written
A marks: Correct balancing

Award:
B1: Correct formulae for reactants and products
A1: Correctly balanced equation
A1: State symbols correct (if required)
        """,
        "common_deductions": [
            "Incorrect formula: 0 marks",
            "Unbalanced: lose A marks",
            "Missing/incorrect state symbols: -1 mark",
            "Changing subscripts instead of coefficients: 0 marks"
        ]
    },
    "explain_mechanism": {
        "mark_types": ["K", "L"],
        "guidelines": """
K marks: Knowledge of chemistry concepts
L marks: Logical sequence/linkage

Each of these = 1 mark:
- Identification of type of reaction/mechanism
- Role of reagent/catalyst
- Curly arrow showing electron movement
- Intermediate structure
- Final product
- Explanation of rate/yield factors
        """,
        "indicative_points": [
            "Use of correct chemical terminology",
            "Reference to electron movement",
            "Structural formulae where appropriate",
            "Link between structure and reactivity"
        ]
    }
}

# Biology Mark Scheme Templates
BIOLOGY_TEMPLATES = {
    "describe_explain": {
        "mark_types": ["K", "A", "E"],
        "guidelines": """
K marks: Key biological knowledge
A marks: Application to context
E marks: Extended explanation/linking

Award marks for:
- Each distinct biological concept
- Correct use of terminology
- Cause and effect relationships
- Link to the specific organism/system in question
        """,
        "indicative_content": [
            "Define key terms",
            "Describe the process/structure",
            "Explain why/how it occurs",
            "Reference to specific examples",
            "Conclude with significance/effect"
        ]
    },
    "data_analysis": {
        "mark_types": ["D", "C", "E"],
        "guidelines": """
D marks: Data manipulation (calculations, graphs)
C marks: Correct conclusion from data
E marks: Evaluation of data/method

Example 4-mark data question:
D1: Calculation correct (e.g., percentage change)
D1: Data interpretation correct
C1: Valid conclusion drawn
E1: Evaluation of reliability or method
        """,
        "common_deductions": [
            "Quoting data without interpretation: no C mark",
            "Conclusion not supported by data: 0 marks for C",
            "No quantitative comparison: -1 mark",
            "Vague evaluation: may lose E mark"
        ]
    }
}

# English Language Mark Scheme Templates
ENGLISH_LANG_TEMPLATES = {
    "analysis": {
        "levels": True,
        "max_marks": 20,
        "guidelines": """
Level 4 (16-20): Perceptive, detailed analysis
- Analyses language/structure with precision
- Uses sophisticated subject terminology
- Selects judicious textual references
- Shows convincing understanding of writer's methods

Level 3 (11-15): Clear, explained analysis
- Clear analysis of language/structure
- Uses subject terminology appropriately
- Selects relevant textual references
- Shows clear understanding of writer's methods

Level 2 (6-10): Some understanding
- Some analysis, mostly descriptive
- Limited use of subject terminology
- Some relevant references
- Shows simple awareness of methods

Level 1 (1-5): Simple comments
- Simple, limited comments
- Little terminology
- References may not be relevant
- Shows little awareness of methods
        """,
        "assessment_objectives": [
            "AO2: Analyse language, form and structure",
            "AO1: Identify and interpret information"
        ]
    },
    "creative_writing": {
        "levels": True,
        "max_marks": 40,
        "guidelines": """
Content & Organization (24 marks):
Level 6 (20-24): Compelling, convincing
Level 5 (16-19): Consistent, engaging
Level 4 (11-15): Clear ideas, structured
Level 3 (7-10): Some development, attempts structure
Level 2 (4-6): Simple content, basic structure
Level 1 (1-3): Limited content/structure

Technical Accuracy (16 marks):
Level 4 (13-16): Consistent control, sophisticated
Level 3 (9-12): Generally accurate, varied
Level 2 (5-8): Some control, basic range
Level 1 (1-4): Limited control/accuracy
        """,
        "assessment_objectives": [
            "AO5: Communicate clearly, effectively, imaginatively",
            "AO6: Vocabulary, sentence structure, spelling, punctuation"
        ]
    }
}

# Geography Mark Scheme Templates  
GEOGRAPHY_TEMPLATES = {
    "case_study": {
        "mark_types": ["K", "A", "E"],
        "guidelines": """
K marks: Knowledge of case study
A marks: Application to question
E marks: Evaluation/judgement

Example 9-mark case study:
- 3 marks: Specific knowledge (names, data, facts)
- 3 marks: Application to the question
- 3 marks: Evaluation/weighing up/conclusion
        """,
        "indicative_content": [
            "Specific place names and locations",
            "Relevant data/statistics",
            "Clear explanation of processes",
            "Link to geographical concepts",
            "Balanced evaluation of impacts/strategies"
        ]
    },
    "fieldwork": {
        "mark_types": ["M", "A", "E"],
        "guidelines": """
M marks: Appropriate method described
A marks: Accurate data presentation/analysis
E marks: Evaluation of methodology

Fieldwork mark scheme focuses on:
- Appropriate data collection methods
- Suitable sampling strategies
- Accurate data presentation (graphs, maps)
- Statistical analysis where appropriate
- Critical evaluation of reliability
        """,
        "common_deductions": [
            "No justification for method choice: -1 mark",
            "Inaccurate graph/no labels: lose A marks",
            "No evaluation of limitations: lose E marks"
        ]
    }
}

# History Mark Scheme Templates
HISTORY_TEMPLATES = {
    "extended_response": {
        "levels": True,
        "max_marks": 16,
        "guidelines": """
Level 4 (13-16): Complex, analytical
- Sustained, developed analysis
- Fully focused on the question
- Uses detailed, accurate knowledge
- Reaches a substantiated judgement

Level 3 (9-12): Developed explanation
- Developed analysis with some support
- Mostly focused on question
- Accurate knowledge used
- Begins to reach judgement

Level 2 (5-8): Simple explanation
- Simple analysis with limited support
- Some focus on question
- General knowledge used
- Simple statements about significance/causation

Level 1 (1-4): Basic description
- Basic description with little analysis
- May not focus on question
- Limited knowledge
- No clear judgement
        """,
        "assessment_objectives": [
            "AO1: Knowledge and understanding",
            "AO2: Explanation and analysis"
        ]
    },
    "source_evaluation": {
        "levels": True,
        "max_marks": 12,
        "guidelines": """
Level 4 (10-12): Complex evaluation of usefulness
- Analyses usefulness considering nature, origin, purpose
- Uses detailed knowledge to support evaluation
- Evaluates content AND provenance

Level 3 (7-9): Developed evaluation
- Evaluates usefulness with some support
- Uses knowledge of context
- Considers content and provenance

Level 2 (4-6): Simple evaluation
- Simple evaluation based on content
- Limited use of knowledge
- May only consider content

Level 1 (1-3): Basic comments
- Basic comments on source
- Little evaluation
- Surface-level understanding
        """,
        "assessment_objectives": [
            "AO3: Analyse, evaluate and use sources",
            "AO1: Demonstrate knowledge and understanding"
        ]
    }
}


def get_mark_scheme_template(subject: str, question_type: str) -> dict:
    """Get appropriate mark scheme template for subject and question type"""
    
    templates_map = {
        "Maths": MATHS_TEMPLATES,
        "Physics": PHYSICS_TEMPLATES,
        "Chemistry": CHEMISTRY_TEMPLATES,
        "Biology": BIOLOGY_TEMPLATES,
        "Combined Science": PHYSICS_TEMPLATES,  # Use physics as default
        "English Lang": ENGLISH_LANG_TEMPLATES,
        "English Lit": ENGLISH_LANG_TEMPLATES,
        "Geography": GEOGRAPHY_TEMPLATES,
        "History": HISTORY_TEMPLATES
    }
    
    subject_templates = templates_map.get(subject, {})
    
    # Map question types to template keys
    type_mapping = {
        "Short answer": "calculation" if subject in ["Maths", "Physics", "Chemistry"] else "describe_explain",
        "Structured calculation": "structured_calculation" if subject == "Maths" else "calculation",
        "Derivation": "proof_derivation" if subject == "Maths" else "explain_mechanism",
        "Graph/Diagram-based": "graph_interpretation",
        "Explain/describe": "describe_explain" if subject in ["Biology", "Combined Science"] else "explain_describe",
        "Extended response": "extended_response" if subject in ["English Lang", "History"] else "describe_explain",
        "Data interpretation": "data_analysis"
    }
    
    template_key = type_mapping.get(question_type, "describe_explain")
    return subject_templates.get(template_key, {})


def format_mark_scheme_guidance(template: dict) -> str:
    """Format mark scheme template into guidance text for AI"""
    if not template:
        return ""
    
    guidance = []
    
    if template.get("mark_types"):
        guidance.append(f"Mark types: {', '.join(template['mark_types'])}")
    
    if template.get("guidelines"):
        guidance.append(f"\nGuidelines:\n{template['guidelines']}")
    
    if template.get("common_deductions"):
        guidance.append("\nCommon deductions:")
        for deduction in template['common_deductions']:
            guidance.append(f"  - {deduction}")
    
    if template.get("indicative_content"):
        guidance.append("\nIndicative content:")
        for point in template['indicative_content']:
            guidance.append(f"  - {point}")
    
    if template.get("levels"):
        guidance.append("\nUSE LEVELS-BASED MARKING")
        if template.get("guidelines"):
            guidance.append(template['guidelines'])
    
    return "\n".join(guidance)
