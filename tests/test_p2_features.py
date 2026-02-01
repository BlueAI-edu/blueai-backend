"""
Test P2 Features: Teacher Feedback Moderation, Regenerate PDF, Teacher Profile
- PUT /api/teacher/submissions/{id}/moderate-feedback
- POST /api/teacher/submissions/{id}/regenerate-pdf
- PUT /api/auth/profile
- GET /api/teacher/profile (stats via questions, assessments, classes endpoints)
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from previous iteration
TEST_EMAIL = "test_analytics@test.com"
TEST_PASSWORD = "test123"


class TestP2Features:
    """Test P2 Features: Feedback Moderation, Regenerate PDF, Profile"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup session and authenticate"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get session
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code != 200:
            pytest.skip(f"Authentication failed: {login_response.status_code}")
        
        # Store session cookie
        self.user = login_response.json()
        yield
    
    # ==================== Profile Tests ====================
    
    def test_get_profile_via_auth_me(self):
        """GET /api/auth/me - Get current user profile"""
        response = self.session.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        
        data = response.json()
        assert "user_id" in data
        assert "email" in data
        assert data["email"] == TEST_EMAIL
        print(f"✓ Profile loaded: {data['name']}")
    
    def test_update_profile_name(self):
        """PUT /api/auth/profile - Update name"""
        update_data = {
            "name": "Test Teacher Updated"
        }
        response = self.session.put(f"{BASE_URL}/api/auth/profile", json=update_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "Test Teacher Updated"
        print("✓ Profile name updated successfully")
        
        # Revert back
        self.session.put(f"{BASE_URL}/api/auth/profile", json={"name": "Test Analytics Teacher"})
    
    def test_update_profile_display_name(self):
        """PUT /api/auth/profile - Update display_name"""
        update_data = {
            "display_name": "Mr. Test"
        }
        response = self.session.put(f"{BASE_URL}/api/auth/profile", json=update_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["display_name"] == "Mr. Test"
        print("✓ Display name updated successfully")
    
    def test_update_profile_school_name(self):
        """PUT /api/auth/profile - Update school_name"""
        update_data = {
            "school_name": "Test Academy"
        }
        response = self.session.put(f"{BASE_URL}/api/auth/profile", json=update_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["school_name"] == "Test Academy"
        print("✓ School name updated successfully")
    
    def test_update_profile_department(self):
        """PUT /api/auth/profile - Update department"""
        update_data = {
            "department": "Science Department"
        }
        response = self.session.put(f"{BASE_URL}/api/auth/profile", json=update_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["department"] == "Science Department"
        print("✓ Department updated successfully")
    
    def test_update_profile_all_fields(self):
        """PUT /api/auth/profile - Update all fields at once"""
        update_data = {
            "name": "Full Update Teacher",
            "display_name": "Dr. Full",
            "school_name": "Complete Academy",
            "department": "All Subjects"
        }
        response = self.session.put(f"{BASE_URL}/api/auth/profile", json=update_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "Full Update Teacher"
        assert data["display_name"] == "Dr. Full"
        assert data["school_name"] == "Complete Academy"
        assert data["department"] == "All Subjects"
        print("✓ All profile fields updated successfully")
        
        # Revert
        self.session.put(f"{BASE_URL}/api/auth/profile", json={
            "name": "Test Analytics Teacher",
            "display_name": "Mr. Test",
            "school_name": "Test Academy",
            "department": "Science"
        })
    
    # ==================== Profile Stats Tests ====================
    
    def test_profile_stats_questions(self):
        """GET /api/teacher/questions - Get questions for stats"""
        response = self.session.get(f"{BASE_URL}/api/teacher/questions")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Questions count: {len(data)}")
    
    def test_profile_stats_assessments(self):
        """GET /api/teacher/assessments - Get assessments for stats"""
        response = self.session.get(f"{BASE_URL}/api/teacher/assessments")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Assessments count: {len(data)}")
    
    def test_profile_stats_classes(self):
        """GET /api/teacher/classes - Get classes for stats"""
        response = self.session.get(f"{BASE_URL}/api/teacher/classes")
        assert response.status_code == 200
        
        data = response.json()
        assert "classes" in data
        print(f"✓ Classes count: {len(data['classes'])}")
    
    # ==================== Feedback Moderation Tests ====================
    
    def test_moderate_feedback_requires_auth(self):
        """PUT /api/teacher/submissions/{id}/moderate-feedback - Requires auth"""
        # Use a new session without auth
        unauth_session = requests.Session()
        response = unauth_session.put(
            f"{BASE_URL}/api/teacher/submissions/fake-id/moderate-feedback",
            json={"score": 5}
        )
        assert response.status_code == 401
        print("✓ Moderate feedback requires authentication")
    
    def test_moderate_feedback_not_found(self):
        """PUT /api/teacher/submissions/{id}/moderate-feedback - 404 for non-existent"""
        response = self.session.put(
            f"{BASE_URL}/api/teacher/submissions/non-existent-id/moderate-feedback",
            json={"score": 5}
        )
        assert response.status_code == 404
        print("✓ Returns 404 for non-existent submission")
    
    # ==================== Regenerate PDF Tests ====================
    
    def test_regenerate_pdf_requires_auth(self):
        """POST /api/teacher/submissions/{id}/regenerate-pdf - Requires auth"""
        unauth_session = requests.Session()
        response = unauth_session.post(
            f"{BASE_URL}/api/teacher/submissions/fake-id/regenerate-pdf"
        )
        assert response.status_code == 401
        print("✓ Regenerate PDF requires authentication")
    
    def test_regenerate_pdf_not_found(self):
        """POST /api/teacher/submissions/{id}/regenerate-pdf - 404 for non-existent"""
        response = self.session.post(
            f"{BASE_URL}/api/teacher/submissions/non-existent-id/regenerate-pdf"
        )
        assert response.status_code == 404
        print("✓ Returns 404 for non-existent submission")


class TestFeedbackModerationFlow:
    """Test full feedback moderation flow with real submission"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup session and authenticate"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code != 200:
            pytest.skip("Authentication failed")
        
        self.user = login_response.json()
        yield
    
    def test_find_marked_submission_and_moderate(self):
        """Find a marked submission and test moderation flow"""
        # Get assessments
        assessments_response = self.session.get(f"{BASE_URL}/api/teacher/assessments")
        if assessments_response.status_code != 200:
            pytest.skip("Could not get assessments")
        
        assessments = assessments_response.json()
        
        # Find an assessment with marked submissions
        marked_submission = None
        for assessment in assessments:
            detail_response = self.session.get(f"{BASE_URL}/api/teacher/assessments/{assessment['id']}")
            if detail_response.status_code == 200:
                detail = detail_response.json()
                submissions = detail.get('submissions', [])
                for sub in submissions:
                    if sub.get('status') == 'marked':
                        marked_submission = sub
                        break
            if marked_submission:
                break
        
        if not marked_submission:
            pytest.skip("No marked submissions found to test moderation")
        
        submission_id = marked_submission['attempt_id']
        print(f"Found marked submission: {submission_id}")
        
        # Test moderation - update score
        original_score = marked_submission.get('score', 0)
        new_score = original_score + 1 if original_score < 10 else original_score - 1
        
        moderation_response = self.session.put(
            f"{BASE_URL}/api/teacher/submissions/{submission_id}/moderate-feedback",
            json={"score": new_score}
        )
        assert moderation_response.status_code == 200
        data = moderation_response.json()
        assert data["success"] == True
        print(f"✓ Score moderated from {original_score} to {new_score}")
        
        # Test moderation - update www
        moderation_response = self.session.put(
            f"{BASE_URL}/api/teacher/submissions/{submission_id}/moderate-feedback",
            json={"www": "Teacher moderated: Great work on this answer!"}
        )
        assert moderation_response.status_code == 200
        print("✓ WWW moderated successfully")
        
        # Test moderation - update next_steps
        moderation_response = self.session.put(
            f"{BASE_URL}/api/teacher/submissions/{submission_id}/moderate-feedback",
            json={"next_steps": "Teacher moderated: Focus on improving clarity."}
        )
        assert moderation_response.status_code == 200
        print("✓ Next steps moderated successfully")
        
        # Test moderation - update overall_feedback
        moderation_response = self.session.put(
            f"{BASE_URL}/api/teacher/submissions/{submission_id}/moderate-feedback",
            json={"overall_feedback": "Teacher moderated: Overall good effort!"}
        )
        assert moderation_response.status_code == 200
        print("✓ Overall feedback moderated successfully")
        
        # Verify moderation was saved
        submission_response = self.session.get(f"{BASE_URL}/api/teacher/submissions/{submission_id}")
        if submission_response.status_code == 200:
            submission_data = submission_response.json()
            sub = submission_data.get('submission', {})
            assert sub.get('moderated_at') is not None
            print("✓ Moderation timestamp saved")
    
    def test_regenerate_pdf_after_moderation(self):
        """Test regenerating PDF after moderation"""
        # Get assessments
        assessments_response = self.session.get(f"{BASE_URL}/api/teacher/assessments")
        if assessments_response.status_code != 200:
            pytest.skip("Could not get assessments")
        
        assessments = assessments_response.json()
        
        # Find a marked submission
        marked_submission = None
        for assessment in assessments:
            detail_response = self.session.get(f"{BASE_URL}/api/teacher/assessments/{assessment['id']}")
            if detail_response.status_code == 200:
                detail = detail_response.json()
                submissions = detail.get('submissions', [])
                for sub in submissions:
                    if sub.get('status') == 'marked':
                        marked_submission = sub
                        break
            if marked_submission:
                break
        
        if not marked_submission:
            pytest.skip("No marked submissions found to test PDF regeneration")
        
        submission_id = marked_submission['attempt_id']
        
        # Regenerate PDF
        regenerate_response = self.session.post(
            f"{BASE_URL}/api/teacher/submissions/{submission_id}/regenerate-pdf"
        )
        assert regenerate_response.status_code == 200
        data = regenerate_response.json()
        assert data["success"] == True
        assert "pdf_url" in data
        print(f"✓ PDF regenerated: {data['pdf_url']}")


class TestProfilePageNavigation:
    """Test profile page navigation link in header"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code != 200:
            pytest.skip("Authentication failed")
        
        yield
    
    def test_dashboard_endpoint_works(self):
        """GET /api/teacher/dashboard - Dashboard loads for profile nav"""
        response = self.session.get(f"{BASE_URL}/api/teacher/dashboard")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_assessments" in data
        assert "total_submissions" in data
        print("✓ Dashboard endpoint works for navigation")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
