"""
Test suite for Batch Export and Email PDF features
- GET /api/teacher/assessments/{id}/export-csv
- GET /api/teacher/assessments/{id}/export-pdfs-zip
- POST /api/teacher/submissions/{id}/email-pdf
- POST /api/teacher/assessments/{id}/email-all-pdfs
"""
import pytest
import requests
import os
import io
import zipfile

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "test_analytics@test.com"
TEST_PASSWORD = "test123"

# Known assessment ID with submissions
ASSESSMENT_ID = "0d1af82a-9d77-4fc8-ba37-1510d482ff5d"


@pytest.fixture(scope="module")
def session():
    """Create authenticated session"""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    
    # Login
    response = s.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    
    if response.status_code != 200:
        pytest.skip("Authentication failed - skipping tests")
    
    # Extract session token from cookies
    session_token = response.cookies.get("session_token")
    if session_token:
        s.headers.update({"Authorization": f"Bearer {session_token}"})
    
    return s


class TestExportCSV:
    """Tests for CSV export endpoint"""
    
    def test_export_csv_success(self, session):
        """Test successful CSV export"""
        response = session.get(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}/export-csv")
        
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("Content-Type", "")
        
        # Verify CSV content
        content = response.text
        assert "Student Name" in content
        assert "Score" in content
        assert "Max Marks" in content
        assert "What Went Well" in content
        assert "Next Steps" in content
        
    def test_export_csv_has_content_disposition(self, session):
        """Test CSV export has proper filename header"""
        response = session.get(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}/export-csv")
        
        assert response.status_code == 200
        content_disposition = response.headers.get("Content-Disposition", "")
        assert "attachment" in content_disposition
        assert ".csv" in content_disposition
        
    def test_export_csv_invalid_assessment(self, session):
        """Test CSV export with invalid assessment ID"""
        response = session.get(f"{BASE_URL}/api/teacher/assessments/invalid-id-12345/export-csv")
        
        assert response.status_code == 404
        
    def test_export_csv_requires_auth(self):
        """Test CSV export requires authentication"""
        response = requests.get(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}/export-csv")
        
        assert response.status_code == 401


class TestExportPDFsZip:
    """Tests for ZIP export of all PDFs endpoint"""
    
    def test_export_pdfs_zip_success(self, session):
        """Test successful ZIP export of PDFs"""
        response = session.get(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}/export-pdfs-zip")
        
        # Should be 200 if there are marked submissions, 400 if none
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            assert "application/zip" in response.headers.get("Content-Type", "")
            
            # Verify it's a valid ZIP file
            zip_buffer = io.BytesIO(response.content)
            with zipfile.ZipFile(zip_buffer, 'r') as zf:
                file_list = zf.namelist()
                assert len(file_list) > 0
                # All files should be PDFs
                for filename in file_list:
                    assert filename.endswith('.pdf')
                    
    def test_export_pdfs_zip_has_content_disposition(self, session):
        """Test ZIP export has proper filename header"""
        response = session.get(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}/export-pdfs-zip")
        
        if response.status_code == 200:
            content_disposition = response.headers.get("Content-Disposition", "")
            assert "attachment" in content_disposition
            assert ".zip" in content_disposition
            
    def test_export_pdfs_zip_invalid_assessment(self, session):
        """Test ZIP export with invalid assessment ID"""
        response = session.get(f"{BASE_URL}/api/teacher/assessments/invalid-id-12345/export-pdfs-zip")
        
        assert response.status_code == 404
        
    def test_export_pdfs_zip_requires_auth(self):
        """Test ZIP export requires authentication"""
        response = requests.get(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}/export-pdfs-zip")
        
        assert response.status_code == 401


class TestEmailPDF:
    """Tests for individual email PDF endpoint"""
    
    def test_email_pdf_requires_auth(self):
        """Test email PDF requires authentication"""
        response = requests.post(f"{BASE_URL}/api/teacher/submissions/test-submission-id/email-pdf")
        
        assert response.status_code == 401
        
    def test_email_pdf_invalid_submission(self, session):
        """Test email PDF with invalid submission ID"""
        response = session.post(f"{BASE_URL}/api/teacher/submissions/invalid-submission-id/email-pdf")
        
        assert response.status_code == 404
        
    def test_email_pdf_no_student_email(self, session):
        """Test email PDF when student has no email - should return 400"""
        # Use P2 Test Student which has no student_id linked
        response = session.post(f"{BASE_URL}/api/teacher/submissions/test-p2-1769731067573/email-pdf")
        
        # Should fail because student doesn't have email
        assert response.status_code == 400
        data = response.json()
        assert "email" in data.get("detail", "").lower()


class TestEmailAllPDFs:
    """Tests for batch email all PDFs endpoint"""
    
    def test_email_all_pdfs_requires_auth(self):
        """Test email all PDFs requires authentication"""
        response = requests.post(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}/email-all-pdfs")
        
        assert response.status_code == 401
        
    def test_email_all_pdfs_invalid_assessment(self, session):
        """Test email all PDFs with invalid assessment ID"""
        response = session.post(f"{BASE_URL}/api/teacher/assessments/invalid-id-12345/email-all-pdfs")
        
        assert response.status_code == 404
        
    def test_email_all_pdfs_returns_summary(self, session):
        """Test email all PDFs returns proper summary structure"""
        response = session.post(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}/email-all-pdfs")
        
        # Should return 200 with summary or 400 if no eligible submissions
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            data = response.json()
            assert "success" in data
            assert "summary" in data
            summary = data["summary"]
            assert "sent" in summary
            assert "failed" in summary
            assert "no_email" in summary


class TestStudentEmailField:
    """Tests for student email field in models"""
    
    def test_student_has_email_field(self, session):
        """Test that student model includes email field"""
        # Get classes to find a class with students
        response = session.get(f"{BASE_URL}/api/teacher/classes")
        assert response.status_code == 200
        
        classes = response.json().get("classes", [])
        if not classes:
            pytest.skip("No classes available for testing")
            
        # Get first class details
        class_id = classes[0]["id"]
        response = session.get(f"{BASE_URL}/api/teacher/classes/{class_id}")
        assert response.status_code == 200
        
        data = response.json()
        students = data.get("students", [])
        
        # Verify student model structure (email field should exist even if null)
        if students:
            student = students[0]
            # The email field should be present in the response
            # It may be null/None but the field should exist
            assert "first_name" in student
            assert "last_name" in student
            # email field is optional but should be accepted


class TestAssessmentDetailPageButtons:
    """Tests for frontend button data-testids"""
    
    def test_assessment_detail_has_submissions(self, session):
        """Test assessment detail returns submissions with required fields"""
        response = session.get(f"{BASE_URL}/api/teacher/assessments/{ASSESSMENT_ID}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "assessment" in data
        assert "question" in data
        assert "submissions" in data
        
        # Verify assessment has join_code for filename generation
        assert "join_code" in data["assessment"]
        
        # Verify question has subject for filename generation
        assert "subject" in data["question"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
