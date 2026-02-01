"""
Test suite for Performance Heatmap Feature
Tests the GET /api/teacher/classes/{class_id}/analytics/heatmap endpoint
and related analytics functionality
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_SESSION_TOKEN = None
TEST_CLASS_ID = "65009c22-3b81-4bd8-8f16-6429d8fbf0a9"


@pytest.fixture(scope="module")
def auth_session():
    """Create authenticated session for tests"""
    import subprocess
    result = subprocess.run([
        'mongosh', '--quiet', '--eval', '''
        use('test_database');
        var user = db.users.findOne({email: 'test_analytics@test.com'});
        if (user) {
            var token = 'pytest_heatmap_' + Date.now();
            db.user_sessions.deleteMany({user_id: user.user_id});
            db.user_sessions.insertOne({
                user_id: user.user_id,
                session_token: token,
                expires_at: new Date(Date.now() + 7*24*60*60*1000),
                created_at: new Date()
            });
            print(token);
        }
        '''
    ], capture_output=True, text=True)
    token = result.stdout.strip().split('\n')[-1]
    
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    })
    return session


class TestHeatmapEndpoint:
    """Tests for GET /api/teacher/classes/{class_id}/analytics/heatmap"""
    
    def test_heatmap_returns_200(self, auth_session):
        """Heatmap endpoint returns 200 for valid class"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/heatmap")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ Heatmap endpoint returns 200")
    
    def test_heatmap_returns_class_info(self, auth_session):
        """Heatmap response includes class information"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/heatmap")
        data = response.json()
        
        assert "class" in data, "Response missing 'class' field"
        assert data["class"]["id"] == TEST_CLASS_ID
        assert "class_name" in data["class"]
        print(f"✓ Class info returned: {data['class']['class_name']}")
    
    def test_heatmap_returns_assessments_list(self, auth_session):
        """Heatmap response includes assessments list with headers"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/heatmap")
        data = response.json()
        
        assert "assessments" in data, "Response missing 'assessments' field"
        assert isinstance(data["assessments"], list)
        
        if len(data["assessments"]) > 0:
            assessment = data["assessments"][0]
            assert "assessment_id" in assessment
            assert "subject" in assessment
            assert "join_code" in assessment
            print(f"✓ Assessments list returned with {len(data['assessments'])} items")
        else:
            print("✓ Assessments list returned (empty)")
    
    def test_heatmap_returns_matrix(self, auth_session):
        """Heatmap response includes student-assessment matrix"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/heatmap")
        data = response.json()
        
        assert "matrix" in data, "Response missing 'matrix' field"
        assert isinstance(data["matrix"], list)
        
        if len(data["matrix"]) > 0:
            row = data["matrix"][0]
            assert "student_id" in row
            assert "student_name" in row
            assert "scores" in row
            assert "average" in row
            assert "submission_count" in row
            print(f"✓ Matrix returned with {len(data['matrix'])} students")
        else:
            print("✓ Matrix returned (empty)")
    
    def test_heatmap_matrix_scores_structure(self, auth_session):
        """Each matrix row has properly structured scores"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/heatmap")
        data = response.json()
        
        for row in data["matrix"]:
            assert isinstance(row["scores"], list), f"Scores should be list for {row['student_name']}"
            for score in row["scores"]:
                assert "assessment_id" in score
                assert "status" in score
                # Score can be null for no_submission
                if score["status"] == "marked":
                    assert "score" in score
                    assert "percentage" in score
                    assert score["percentage"] is not None
        print("✓ Matrix scores structure is valid")
    
    def test_heatmap_returns_stats(self, auth_session):
        """Heatmap response includes stats summary"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/heatmap")
        data = response.json()
        
        assert "stats" in data, "Response missing 'stats' field"
        assert "total_students" in data["stats"]
        assert "total_assessments" in data["stats"]
        assert "students_with_submissions" in data["stats"]
        print(f"✓ Stats returned: {data['stats']['total_students']} students, {data['stats']['total_assessments']} assessments")
    
    def test_heatmap_404_for_invalid_class(self, auth_session):
        """Heatmap returns 404 for non-existent class"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/invalid-class-id/analytics/heatmap")
        assert response.status_code == 404
        print("✓ Returns 404 for invalid class ID")
    
    def test_heatmap_401_without_auth(self):
        """Heatmap requires authentication"""
        response = requests.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/heatmap")
        assert response.status_code == 401
        print("✓ Returns 401 without authentication")


class TestAnalyticsEndpoint:
    """Tests for GET /api/teacher/classes/{class_id}/analytics (Overview)"""
    
    def test_analytics_returns_200(self, auth_session):
        """Analytics endpoint returns 200 for valid class"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics")
        assert response.status_code == 200
        print("✓ Analytics endpoint returns 200")
    
    def test_analytics_returns_summary(self, auth_session):
        """Analytics response includes summary stats"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics")
        data = response.json()
        
        assert "summary" in data
        summary = data["summary"]
        assert "total_students" in summary
        assert "class_average" in summary
        assert "students_needing_support" in summary
        assert "improving_count" in summary
        assert "declining_count" in summary
        print(f"✓ Summary returned: class_average={summary['class_average']}")
    
    def test_analytics_returns_students_breakdown(self, auth_session):
        """Analytics response includes students breakdown"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics")
        data = response.json()
        
        assert "students" in data
        students = data["students"]
        assert "all" in students
        assert "needing_support" in students
        assert "improving" in students
        assert "declining" in students
        print(f"✓ Students breakdown returned: {len(students['all'])} total")


class TestExportEndpoints:
    """Tests for CSV and PDF export endpoints"""
    
    def test_csv_export_returns_200(self, auth_session):
        """CSV export returns 200 with valid content-type"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/export-csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        print("✓ CSV export returns 200 with correct content-type")
    
    def test_pdf_export_returns_200(self, auth_session):
        """PDF export returns 200 with valid content-type"""
        response = auth_session.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/export-pdf")
        assert response.status_code == 200
        assert "application/pdf" in response.headers.get("content-type", "")
        print("✓ PDF export returns 200 with correct content-type")
    
    def test_csv_export_401_without_auth(self):
        """CSV export requires authentication"""
        response = requests.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/export-csv")
        assert response.status_code == 401
        print("✓ CSV export returns 401 without auth")
    
    def test_pdf_export_401_without_auth(self):
        """PDF export requires authentication"""
        response = requests.get(f"{BASE_URL}/api/teacher/classes/{TEST_CLASS_ID}/analytics/export-pdf")
        assert response.status_code == 401
        print("✓ PDF export returns 401 without auth")


class TestStudentEmailField:
    """Tests for student email field in add student endpoint"""
    
    def test_create_student_with_email(self, auth_session):
        """Can create student with email field"""
        import uuid
        student_data = {
            "class_id": TEST_CLASS_ID,
            "first_name": f"Test_{uuid.uuid4().hex[:6]}",
            "last_name": "EmailStudent",
            "email": "test.student@school.edu"
        }
        
        response = auth_session.post(f"{BASE_URL}/api/teacher/students", json=student_data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") == True
        assert "student" in data
        
        # Verify email was saved
        student = data["student"]
        assert student.get("email") == "test.student@school.edu"
        print(f"✓ Student created with email: {student.get('email')}")
        
        # Cleanup - archive the test student
        if student.get("id"):
            auth_session.delete(f"{BASE_URL}/api/teacher/students/{student['id']}")


class TestBatchExportFeatures:
    """Tests for batch export features (from previous implementation)"""
    
    def test_batch_export_endpoint_exists(self, auth_session):
        """Batch export endpoint exists and requires auth"""
        # Test that the endpoint exists (may return 400 without proper data)
        response = auth_session.post(f"{BASE_URL}/api/teacher/submissions/batch-export", json={})
        # Should not be 404 (endpoint exists) and not 401 (authenticated)
        assert response.status_code != 404, "Batch export endpoint not found"
        assert response.status_code != 401, "Authentication failed"
        print(f"✓ Batch export endpoint exists (status: {response.status_code})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
