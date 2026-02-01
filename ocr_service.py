"""
OCR Service for BlueAI Assessment
Handles Azure Computer Vision Read API integration with fallback
"""

import os
import time
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from PIL import Image
import io

# Azure Computer Vision imports
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    logging.warning("Azure Computer Vision SDK not available")

logger = logging.getLogger(__name__)

# Configuration
AZURE_VISION_ENDPOINT = os.getenv("AZURE_VISION_ENDPOINT", "")
AZURE_VISION_KEY = os.getenv("AZURE_VISION_KEY", "")
AZURE_CONFIGURED = bool(AZURE_VISION_ENDPOINT and AZURE_VISION_KEY and AZURE_AVAILABLE)

class OCRResult:
    """Represents OCR result for a single page"""
    def __init__(self, page_number: int, text: str, confidence: float, flags: List[str] = None):
        self.page_number = page_number
        self.text = text
        self.confidence = confidence
        self.flags = flags or []
        
    def to_dict(self):
        return {
            "page_number": self.page_number,
            "text": self.text,
            "confidence": self.confidence,
            "flags": self.flags
        }

class OCRService:
    """Service for OCR processing using Azure Computer Vision"""
    
    def __init__(self):
        self.azure_client = None
        if AZURE_CONFIGURED:
            try:
                self.azure_client = DocumentAnalysisClient(
                    endpoint=AZURE_VISION_ENDPOINT,
                    credential=AzureKeyCredential(AZURE_VISION_KEY)
                )
                logger.info("Azure Computer Vision client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Azure client: {str(e)}")
                self.azure_client = None
    
    def is_configured(self) -> bool:
        """Check if Azure OCR is properly configured"""
        return self.azure_client is not None
    
    async def process_image(self, image_path: Path, page_number: int = 1) -> OCRResult:
        """
        Process a single image file with OCR
        Returns OCRResult with extracted text and confidence
        """
        try:
            if not self.azure_client:
                # Fallback: return stub result
                logger.warning(f"Azure OCR not configured. Using fallback for {image_path}")
                return OCRResult(
                    page_number=page_number,
                    text="[OCR not configured - Please enter text manually]",
                    confidence=0.0,
                    flags=["ocr_unavailable", "manual_entry_required"]
                )
            
            # Read image file
            with open(image_path, "rb") as image_file:
                image_data = image_file.read()
            
            # Call Azure Read API
            poller = self.azure_client.begin_analyze_document(
                "prebuilt-read",
                document=image_data
            )
            
            result = poller.result()
            
            # Extract text and confidence
            text_lines = []
            confidences = []
            
            for page in result.pages:
                if page.page_number == page_number or len(result.pages) == 1:
                    for line in page.lines:
                        text_lines.append(line.content)
                        # Azure doesn't always provide confidence, use 0.95 as default
                        confidences.append(getattr(line, 'confidence', 0.95))
            
            extracted_text = "\n".join(text_lines)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            # Detect quality issues
            flags = []
            if avg_confidence < 0.7:
                flags.append("low_confidence")
            if len(extracted_text.strip()) < 10:
                flags.append("empty_or_short_text")
            if not extracted_text.strip():
                flags.append("no_text_detected")
            
            logger.info(f"OCR completed for {image_path}: {len(extracted_text)} chars, confidence {avg_confidence:.2f}")
            
            return OCRResult(
                page_number=page_number,
                text=extracted_text,
                confidence=avg_confidence,
                flags=flags
            )
            
        except Exception as e:
            logger.error(f"OCR processing failed for {image_path}: {str(e)}")
            return OCRResult(
                page_number=page_number,
                text=f"[OCR Error: {str(e)}]",
                confidence=0.0,
                flags=["ocr_error", "manual_entry_required"]
            )
    
    async def process_pdf(self, pdf_path: Path) -> List[OCRResult]:
        """
        Process a PDF file - convert to images and OCR each page
        Returns list of OCRResult objects, one per page
        """
        try:
            # Convert PDF to images
            from pdf2image import convert_from_path
            
            images = convert_from_path(pdf_path, dpi=300)
            logger.info(f"Converted PDF to {len(images)} images")
            
            results = []
            for idx, image in enumerate(images):
                page_num = idx + 1
                
                # Save temporary image
                temp_image_path = pdf_path.parent / f"temp_page_{page_num}.jpg"
                image.save(temp_image_path, "JPEG", quality=95)
                
                # Process with OCR
                ocr_result = await self.process_image(temp_image_path, page_num)
                results.append(ocr_result)
                
                # Clean up temp file
                temp_image_path.unlink()
            
            return results
            
        except Exception as e:
            logger.error(f"PDF processing failed for {pdf_path}: {str(e)}")
            # Return error result
            return [OCRResult(
                page_number=1,
                text=f"[PDF Processing Error: {str(e)}]",
                confidence=0.0,
                flags=["pdf_error", "manual_entry_required"]
            )]
    
    async def process_multiple_images(self, image_paths: List[Path]) -> List[OCRResult]:
        """
        Process multiple image files in sequence
        Returns list of OCRResult objects, one per image
        """
        results = []
        for idx, image_path in enumerate(image_paths):
            page_num = idx + 1
            ocr_result = await self.process_image(image_path, page_num)
            results.append(ocr_result)
        
        return results
    
    def get_combined_text(self, ocr_results: List[OCRResult]) -> str:
        """Combine text from multiple OCR results"""
        return "\n\n".join([
            f"--- Page {result.page_number} ---\n{result.text}"
            for result in ocr_results
        ])
    
    def validate_image(self, image_path: Path) -> Dict[str, Any]:
        """
        Validate image quality and format
        Returns dict with is_valid flag and issues list
        """
        issues = []
        
        try:
            with Image.open(image_path) as img:
                # Check format
                if img.format not in ['JPEG', 'PNG', 'TIFF', 'BMP']:
                    issues.append(f"Unsupported format: {img.format}")
                
                # Check size
                width, height = img.size
                if width < 100 or height < 100:
                    issues.append(f"Image too small: {width}x{height}")
                
                # Check file size
                file_size = image_path.stat().st_size / (1024 * 1024)  # MB
                if file_size > 50:
                    issues.append(f"File too large: {file_size:.1f}MB")
                
        except Exception as e:
            issues.append(f"Cannot open image: {str(e)}")
        
        return {
            "is_valid": len(issues) == 0,
            "issues": issues
        }

# Global OCR service instance
ocr_service = OCRService()
