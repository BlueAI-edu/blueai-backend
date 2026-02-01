from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from datetime import datetime, timezone
from pathlib import Path
import re
import html
from utils.database import db

ROOT_DIR = Path(__file__).parent.parent

def sanitize_text(text):
    """Remove HTML tags and clean text for PDF generation"""
    if not text:
        return ""
    
    # Convert to string
    text = str(text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Replace smart quotes and special chars
    replacements = {
        '\u2018': "'", '\u2019': "'",  # Smart single quotes
        '\u201c': '"', '\u201d': '"',  # Smart double quotes
        '\u2013': '-', '\u2014': '--', # En/em dashes
        '\u2022': '•',  # Bullet point (keep this)
        '\u2026': '...',  # Ellipsis
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text

def split_into_bullets(text):
    """Convert text into bullet points"""
    if not text or text.strip() == "":
        return ["None recorded."]
    
    text = sanitize_text(text)
    
    # Split by common delimiters
    items = []
    for delimiter in ['\n', '.', ';']:
        if delimiter in text:
            items = [item.strip() for item in text.split(delimiter) if item.strip()]
            break
    
    if not items:
        items = [text]
    
    # Clean up items
    cleaned_items = []
    for item in items:
        item = item.strip()
        # Remove existing bullets
        item = re.sub(r'^[•\-\*]\s*', '', item)
        if item and len(item) > 3:  # Skip very short fragments
            cleaned_items.append(item)
    
    return cleaned_items if cleaned_items else ["None recorded."]

async def generate_feedback_pdf(attempt_doc: dict, teacher_display: str, teacher_school: str = None) -> str:
    """Generate feedback PDF for a marked attempt. Returns the PDF filename."""
    # Fetch related data
    assessment = await db.assessments.find_one({"id": attempt_doc["assessment_id"]}, {"_id": 0})
    question = await db.questions.find_one({"id": assessment["question_id"]}, {"_id": 0})
    
    # Sanitize all data
    student_name = sanitize_text(attempt_doc['student_name'])
    subject = sanitize_text(question['subject'])
    topic = sanitize_text(question.get('topic', ''))
    max_marks = int(question['max_marks'])
    
    # Sanitize score field (may contain HTML tags like <b>10</b>)
    score_raw = sanitize_text(str(attempt_doc.get('score', 0)))
    try:
        score = int(score_raw)
    except ValueError:
        # Extract first number if conversion fails
        numbers = re.findall(r'\d+', score_raw)
        score = int(numbers[0]) if numbers else 0
    
    answer_text = sanitize_text(attempt_doc['answer_text'])
    
    # Process feedback sections
    www_items = split_into_bullets(attempt_doc.get('www', ''))
    ebi_items = split_into_bullets(attempt_doc.get('next_steps', ''))
    overall_feedback = sanitize_text(attempt_doc.get('overall_feedback', ''))
    if not overall_feedback:
        overall_feedback = f"Good effort, {student_name}. Keep working on the areas highlighted above."
    
    # Create PDF filename
    safe_student_name = student_name.replace(" ", "_").replace("/", "_")
    safe_subject = subject.replace(" ", "_").replace("/", "_")
    pdf_filename = f"{safe_student_name}_{safe_subject}_Feedback_{attempt_doc['id'][:8]}.pdf"
    pdf_path = Path(ROOT_DIR) / "generated_pdfs" / pdf_filename
    
    # Generate PDF with A4 size and 25mm margins
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=25*mm,
        rightMargin=25*mm,
        topMargin=25*mm,
        bottomMargin=25*mm
    )
    
    # Define styles
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        textColor=colors.HexColor('#2563eb'),
        spaceAfter=6,
        alignment=TA_LEFT
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=20,
        alignment=TA_LEFT
    )
    
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=8,
        spaceBefore=14,
        alignment=TA_LEFT
    )
    
    normal_style = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        spaceAfter=6,
        alignment=TA_LEFT,
        leading=14
    )
    
    bold_style = ParagraphStyle(
        'Bold',
        parent=normal_style,
        fontName='Helvetica-Bold'
    )
    
    bullet_style = ParagraphStyle(
        'Bullet',
        parent=normal_style,
        leftIndent=15,
        bulletIndent=5,
        spaceAfter=4
    )
    
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_LEFT,
        spaceBefore=20,
        leading=10
    )
    
    footer_timestamp_style = ParagraphStyle(
        'FooterTimestamp',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        textColor=colors.HexColor('#999999'),
        alignment=TA_LEFT,
        spaceAfter=0,
        leading=9
    )
    
    story = []
    
    # Header
    story.append(Paragraph("BlueAI Assessment", title_style))
    story.append(Paragraph(
        f"Feedback Report – Generated on {datetime.now(timezone.utc).strftime('%d %B %Y')}",
        subtitle_style
    ))
    
    # Student Information
    story.append(Paragraph("Student Information", heading_style))
    
    info_data = [
        ['Student Name:', student_name],
        ['Assessment:', subject],
        ['Question:', topic if topic else 'N/A'],
        ['Maximum Marks:', str(max_marks)],
        ['Marks Awarded:', f"{score}/{max_marks}"]
    ]
    
    info_table = Table(info_data, colWidths=[45*mm, 115*mm])
    info_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -2), 'Helvetica'),
        ('FONTNAME', (1, -1), (1, -1), 'Helvetica-Bold'),  # Make marks awarded bold
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(info_table)
    
    # Student Response
    story.append(Paragraph("Student Response", heading_style))
    if answer_text:
        story.append(Paragraph(answer_text, normal_style))
    else:
        story.append(Paragraph("No response provided.", normal_style))
    
    # Feedback
    story.append(Paragraph("Feedback", heading_style))
    
    # What Went Well
    story.append(Paragraph("<b>What Went Well:</b>", bold_style))
    for item in www_items:
        story.append(Paragraph(f"• {item}", bullet_style))
    story.append(Spacer(1, 8))
    
    # Next Steps
    story.append(Paragraph("<b>Next Steps:</b>", bold_style))
    for item in ebi_items:
        story.append(Paragraph(f"• {item}", bullet_style))
    story.append(Spacer(1, 8))
    
    # Overall Feedback
    story.append(Paragraph("<b>Overall Feedback:</b>", bold_style))
    story.append(Paragraph(overall_feedback, normal_style))
    
    # Personalized Footer
    story.append(Spacer(1, 15))
    
    # Create footer text
    if teacher_school:
        footer_text = f"Prepared for {teacher_display} • {teacher_school}"
    else:
        footer_text = f"Prepared for {teacher_display}"
    
    story.append(Paragraph(footer_text, footer_style))
    
    # Timestamp line
    timestamp = datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M')
    story.append(Paragraph(f"Generated on {timestamp}", footer_timestamp_style))
    
    # Build PDF
    doc.build(story)
    
    return pdf_filename
