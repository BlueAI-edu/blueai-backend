"""
Test Suite for BlueAI Classes & Students Module - Phase 3 (Analytics) and Phase 4 (Join Code Student Linking)

Tests:
- Class Analytics endpoint - GET /api/teacher/classes/{class_id}/analytics
- Class Analytics CSV export - GET /api/teacher/classes/{class_id}/analytics/export-csv
- Class Analytics PDF export - GET /api/teacher/classes/{class_id}/analytics/export-pdf
- Assessment creation with class linking - POST /api/teacher/assessments with class_id
- Student join flow with class roster - GET /api/public/assessment/{join_code}/class-roster
- Student join with student_id selection - POST /api/public/join with student_id
"""

import pytest
import requests
import os
import uuid

# Get BASE_URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    # Fallback for local testing
    BASE_URL = "https://learnsphere-146.preview.emergentagent.com"

# Test credentials
TEST_EMAIL = "test_analytics@test.com"
TEST_PASSWORD = "test123"
EXISTING_CLASS_ID = "65009c22-3b81-4bd8-8f16-6429d8fbf0a9"

# Student IDs from the existing class
STUDENT_ALICE_ID = "7a46014f-f6ab-46f2-9a8c-e650300b3217"
STUDENT_BOB_ID = "91128129-16d5-4125-8a88-91ae74759aa5"


@pytest.fixture(scope="module")
def session():
    """Create a requests session with auth"""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def auth_session(session):
    """Authenticate and return session with cookies"""
    # Login
    response = session.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    
    if response.status_code != 200:
        pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")
    
    # Session cookies are automatically stored
    return session


@pytest.fixture(scope="module")
def test_question_id(auth_session):
    """Create a test question and return its ID"""
    response = auth_session.post(f"{BASE_URL}/api/teacher/questions", json={
        "subject": "Test Science",
        "exam_type": "GCSE",
        "topic": "Phase 3/4 Test Topic",
        "question_text": "Explain the process of photosynthesis.",
        "max_marks": 10,
        "mark_scheme": "1 mark for mentioning light, 2 marks for CO2 and water, 3 marks for glucose production"
    })
    
    if response.status_code not in [200, 201]:
        pytest.skip(f"Failed to create test question: {response.text}")
    
    data = response.json()
    return data.get("id") or data.get("question", {}).get("id")


class TestClassAnalytics:
    """Phase 3: Class Analytics Tests"""
    
    def test_get_class_analytics_success(self, auth_session):
        """Test GET /api/teacher/classes/{class_id}/analytics returns proper data"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{EXISTING_CLASS_ID}/analytics")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify response structure
        assert "class" in data, "Response should contain 'class' field"
        assert "summary" in data, "Response should contain 'summary' field"
        assert "students" in data, "Response should contain 'students' field"
        assert "topics_to_reteach" in data, "Response should contain 'topics_to_reteach' field"
        assert "assessments" in data, "Response should contain 'assessments' field"
        
        # Verify summary structure
        summary = data["summary"]
        assert "total_students" in summary, "Summary should have total_students"
        assert "class_average" in summary, "Summary should have class_average"
        assert "students_needing_support" in summary, "Summary should have students_needing_support"
        assert "improving_count" in summary, "Summary should have improving_count"
        assert "declining_count" in summary, "Summary should have declining_count"
        
        # Verify students structure
        students = data["students"]
        assert "all" in students, "Students should have 'all' list"
        assert "needing_support" in students, "Students should have 'needing_support' list"
        assert "improving" in students, "Students should have 'improving' list"
        assert "declining" in students, "Students should have 'declining' list"
        
        print(f"✓ Class analytics returned: {summary['total_students']} students, avg: {summary['class_average']}%")
    
    def test_get_class_analytics_not_found(self, auth_session):
        """Test analytics for non-existent class returns 404"""
        fake_class_id = str(uuid.uuid4())
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{fake_class_id}/analytics")
        
        assert response.status_code == 404, f"Expected 404 for non-existent class, got {response.status_code}"
        print("✓ Non-existent class returns 404")
    
    def test_export_csv_success(self, auth_session):
        """Test GET /api/teacher/classes/{class_id}/analytics/export-csv"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{EXISTING_CLASS_ID}/analytics/export-csv")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Verify content type is CSV
        content_type = response.headers.get("content-type", "")
        assert "text/csv" in content_type, f"Expected text/csv content type, got {content_type}"
        
        # Verify content-disposition header for download
        content_disposition = response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition, "Should have attachment disposition"
        assert ".csv" in content_disposition, "Filename should have .csv extension"
        
        # Verify CSV content has headers
        csv_content = response.text
        assert "Student Name" in csv_content, "CSV should have Student Name header"
        assert "Average Score" in csv_content, "CSV should have Average Score header"
        
        print(f"✓ CSV export successful, size: {len(csv_content)} bytes")
    
    def test_export_pdf_success(self, auth_session):
        """Test GET /api/teacher/classes/{class_id}/analytics/export-pdf"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{EXISTING_CLASS_ID}/analytics/export-pdf")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Verify content type is PDF
        content_type = response.headers.get("content-type", "")
        assert "application/pdf" in content_type, f"Expected application/pdf content type, got {content_type}"
        
        # Verify PDF magic bytes
        pdf_content = response.content
        assert pdf_content[:4] == b'%PDF', "Response should be a valid PDF file"
        
        print(f"✓ PDF export successful, size: {len(pdf_content)} bytes")


class TestAssessmentClassLinking:
    """Phase 4: Assessment-Class Linking Tests"""
    
    def test_create_assessment_with_class_id(self, auth_session, test_question_id):
        """Test POST /api/teacher/assessments with class_id"""
        response = auth_session.post(f"{BASE_URL}/api/teacher/assessments", json={
            "question_id": test_question_id,
            "class_id": EXISTING_CLASS_ID,
            "duration_minutes": 30,
            "auto_close": False
        })
        
        assert response.status_code in [200, 201], f"Expected 200/201, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify assessment has class_id
        assessment = data.get("assessment") or data
        assert "id" in assessment, "Assessment should have id"
        assert "join_code" in assessment, "Assessment should have join_code"
        assert assessment.get("class_id") == EXISTING_CLASS_ID, f"Assessment class_id should be {EXISTING_CLASS_ID}"
        
        # Store for later tests
        pytest.assessment_id = assessment["id"]
        pytest.join_code = assessment["join_code"]
        
        print(f"✓ Assessment created with class_id, join_code: {pytest.join_code}")
        return assessment
    
    def test_start_class_linked_assessment(self, auth_session):
        """Start the class-linked assessment"""
        if not hasattr(pytest, 'assessment_id'):
            pytest.skip("No assessment created")
        
        response = auth_session.post(f"{BASE_URL}/api/teacher/assessments/{pytest.assessment_id}/start")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ Class-linked assessment started")


class TestStudentJoinWithClassRoster:
    """Phase 4: Student Join Flow with Class Roster Tests"""
    
    def test_get_class_roster_for_assessment(self, session):
        """Test GET /api/public/assessment/{join_code}/class-roster"""
        if not hasattr(pytest, 'join_code'):
            pytest.skip("No join code available")
        
        response = session.get(f"{BASE_URL}/api/public/assessment/{pytest.join_code}/class-roster")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify roster structure
        assert "has_roster" in data, "Response should have has_roster field"
        assert data["has_roster"] == True, "Should have roster for class-linked assessment"
        assert "students" in data, "Response should have students list"
        assert "class_name" in data, "Response should have class_name"
        
        # Verify students in roster
        students = data["students"]
        assert len(students) >= 2, f"Expected at least 2 students, got {len(students)}"
        
        # Verify student structure
        for student in students:
            assert "id" in student, "Student should have id"
            assert "display_name" in student, "Student should have display_name"
        
        # Check Alice and Bob are in the roster
        student_ids = [s["id"] for s in students]
        assert STUDENT_ALICE_ID in student_ids, "Alice should be in roster"
        assert STUDENT_BOB_ID in student_ids, "Bob should be in roster"
        
        print(f"✓ Class roster returned: {len(students)} students, class: {data['class_name']}")
    
    def test_get_roster_for_non_class_linked_assessment(self, auth_session, test_question_id):
        """Test roster endpoint for assessment without class_id"""
        # Create assessment without class_id
        response = auth_session.post(f"{BASE_URL}/api/teacher/assessments", json={
            "question_id": test_question_id,
            "duration_minutes": 15
        })
        
        assert response.status_code in [200, 201]
        
        data = response.json()
        assessment = data.get("assessment") or data
        join_code = assessment["join_code"]
        
        # Start the assessment
        auth_session.post(f"{BASE_URL}/api/teacher/assessments/{assessment['id']}/start")
        
        # Get roster - should return has_roster: false
        roster_response = requests.get(f"{BASE_URL}/api/public/assessment/{join_code}/class-roster")
        
        assert roster_response.status_code == 200
        roster_data = roster_response.json()
        
        assert roster_data["has_roster"] == False, "Non-class-linked assessment should have has_roster: false"
        assert roster_data["students"] == [], "Should have empty students list"
        
        print("✓ Non-class-linked assessment returns has_roster: false")
    
    def test_student_join_with_student_id(self, session):
        """Test POST /api/public/join with student_id selection"""
        if not hasattr(pytest, 'join_code'):
            pytest.skip("No join code available")
        
        response = session.post(f"{BASE_URL}/api/public/join", json={
            "join_code": pytest.join_code,
            "student_name": "Alice Smith",  # Will be overridden by student_id lookup
            "student_id": STUDENT_ALICE_ID
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify attempt was created
        assert "attempt_id" in data, "Response should have attempt_id"
        assert "assessment" in data, "Response should have assessment"
        assert "question" in data, "Response should have question"
        
        # Store attempt_id for later
        pytest.attempt_id = data["attempt_id"]
        
        print(f"✓ Student joined with student_id, attempt_id: {pytest.attempt_id}")
    
    def test_student_join_with_invalid_student_id(self, session):
        """Test join with invalid student_id returns error"""
        if not hasattr(pytest, 'join_code'):
            pytest.skip("No join code available")
        
        fake_student_id = str(uuid.uuid4())
        
        response = session.post(f"{BASE_URL}/api/public/join", json={
            "join_code": pytest.join_code,
            "student_name": "Fake Student",
            "student_id": fake_student_id
        })
        
        assert response.status_code == 400, f"Expected 400 for invalid student_id, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data, "Error response should have detail"
        
        print("✓ Invalid student_id correctly rejected")
    
    def test_get_roster_invalid_join_code(self, session):
        """Test roster endpoint with invalid join code"""
        response = session.get(f"{BASE_URL}/api/public/assessment/INVALID/class-roster")
        
        assert response.status_code == 404, f"Expected 404 for invalid join code, got {response.status_code}"
        print("✓ Invalid join code returns 404")


class TestClassManagement:
    """Additional Class Management Tests"""
    
    def test_get_classes_list(self, auth_session):
        """Test GET /api/teacher/classes returns list with stats"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "classes" in data, "Response should have classes list"
        
        # Find our test class
        test_class = None
        for cls in data["classes"]:
            if cls["id"] == EXISTING_CLASS_ID:
                test_class = cls
                break
        
        assert test_class is not None, "Test class should be in list"
        assert "student_count" in test_class, "Class should have student_count"
        assert "assessment_count" in test_class, "Class should have assessment_count"
        
        print(f"✓ Classes list returned: {len(data['classes'])} classes")
    
    def test_get_class_detail(self, auth_session):
        """Test GET /api/teacher/classes/{class_id} returns detail with students"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{EXISTING_CLASS_ID}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        assert "class" in data, "Response should have class"
        assert "students" in data, "Response should have students"
        assert "assessments" in data, "Response should have assessments"
        assert "student_count" in data, "Response should have student_count"
        
        # Verify students
        students = data["students"]
        assert len(students) >= 2, f"Expected at least 2 students, got {len(students)}"
        
        print(f"✓ Class detail returned: {data['student_count']} students, {len(data['assessments'])} assessments")
    
    def test_create_class(self, auth_session):
        """Test POST /api/teacher/classes creates new class"""
        unique_name = f"Test Class {uuid.uuid4().hex[:8]}"
        
        response = auth_session.post(f"{BASE_URL}/api/teacher/classes", json={
            "class_name": unique_name,
            "subject": "Mathematics",
            "year_group": "11"
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, "Should return success: true"
        assert "class" in data, "Should return created class"
        assert data["class"]["class_name"] == unique_name, "Class name should match"
        
        # Store for cleanup
        pytest.created_class_id = data["class"]["id"]
        
        print(f"✓ Class created: {unique_name}")
    
    def test_add_student_to_class(self, auth_session):
        """Test POST /api/teacher/students adds student to class"""
        if not hasattr(pytest, 'created_class_id'):
            pytest.skip("No class created")
        
        response = auth_session.post(f"{BASE_URL}/api/teacher/students", json={
            "class_id": pytest.created_class_id,
            "first_name": "Test",
            "last_name": f"Student_{uuid.uuid4().hex[:6]}",
            "student_code": f"TST{uuid.uuid4().hex[:4].upper()}"
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True, "Should return success: true"
        assert "student" in data, "Should return created student"
        
        print("✓ Student added to class")


class TestUnauthenticatedAccess:
    """Test that protected endpoints require authentication"""
    
    def test_analytics_requires_auth(self):
        """Test analytics endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/teacher/classes/{EXISTING_CLASS_ID}/analytics")
        
        assert response.status_code == 401, f"Expected 401 for unauthenticated request, got {response.status_code}"
        print("✓ Analytics endpoint requires authentication")
    
    def test_csv_export_requires_auth(self):
        """Test CSV export requires authentication"""
        response = requests.get(f"{BASE_URL}/api/teacher/classes/{EXISTING_CLASS_ID}/analytics/export-csv")
        
        assert response.status_code == 401, f"Expected 401 for unauthenticated request, got {response.status_code}"
        print("✓ CSV export requires authentication")
    
    def test_pdf_export_requires_auth(self):
        """Test PDF export requires authentication"""
        response = requests.get(f"{BASE_URL}/api/teacher/classes/{EXISTING_CLASS_ID}/analytics/export-pdf")
        
        assert response.status_code == 401, f"Expected 401 for unauthenticated request, got {response.status_code}"
        print("✓ PDF export requires authentication")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
