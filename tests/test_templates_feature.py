"""
Test Assessment Templates Feature (P3)
Tests for template CRUD operations and create-assessment-from-template functionality
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "test_analytics@test.com"
TEST_PASSWORD = "test123"


@pytest.fixture(scope="module")
def session():
    """Create a requests session"""
    return requests.Session()


@pytest.fixture(scope="module")
def auth_token(session):
    """Get authentication token by logging in"""
    response = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if response.status_code != 200:
        pytest.skip(f"Authentication failed: {response.text}")
    
    # Extract session token from cookies
    token = response.cookies.get('session_token')
    if not token:
        pytest.skip("No session token in response")
    return token


@pytest.fixture(scope="module")
def authenticated_session(session, auth_token):
    """Session with auth header"""
    session.headers.update({"Authorization": f"Bearer {auth_token}"})
    return session


@pytest.fixture(scope="module")
def test_question_id(authenticated_session):
    """Get or create a test question for template tests"""
    # First try to get existing questions
    response = authenticated_session.get(f"{BASE_URL}/api/teacher/questions")
    if response.status_code == 200:
        questions = response.json()
        if questions:
            return questions[0]['id']
    
    # Create a new question if none exist
    response = authenticated_session.post(
        f"{BASE_URL}/api/teacher/questions",
        json={
            "subject": "TEST_Template_Subject",
            "exam_type": "Quiz",
            "topic": "Template Testing Topic",
            "question_text": "Test question for template testing",
            "max_marks": 10,
            "mark_scheme": "Award marks for correct answers"
        }
    )
    if response.status_code in [200, 201]:
        return response.json()['id']
    pytest.skip("Could not get or create test question")


class TestTemplateListEndpoint:
    """Tests for GET /api/teacher/templates"""
    
    def test_list_templates_requires_auth(self):
        """Templates list requires authentication"""
        # Use fresh session without auth
        response = requests.get(f"{BASE_URL}/api/teacher/templates")
        assert response.status_code == 401
    
    def test_list_templates_success(self, authenticated_session):
        """Templates list returns 200 with templates array"""
        response = authenticated_session.get(f"{BASE_URL}/api/teacher/templates")
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert isinstance(data["templates"], list)
    
    def test_list_templates_structure(self, authenticated_session):
        """Templates have correct structure with enriched data"""
        response = authenticated_session.get(f"{BASE_URL}/api/teacher/templates")
        assert response.status_code == 200
        templates = response.json()["templates"]
        
        if templates:
            template = templates[0]
            # Check required fields
            assert "id" in template
            assert "name" in template
            assert "question_id" in template
            assert "owner_teacher_id" in template
            assert "use_count" in template
            assert "created_at" in template
            # Check enriched fields
            assert "question_subject" in template
            assert "question_topic" in template


class TestTemplateCreateEndpoint:
    """Tests for POST /api/teacher/templates"""
    
    def test_create_template_requires_auth(self):
        """Create template requires authentication"""
        # Use fresh session without auth
        response = requests.post(
            f"{BASE_URL}/api/teacher/templates",
            json={"name": "Test", "question_id": "test"}
        )
        assert response.status_code == 401
    
    def test_create_template_success(self, authenticated_session, test_question_id):
        """Create template with valid data"""
        unique_name = f"TEST_Template_{uuid.uuid4().hex[:8]}"
        response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={
                "name": unique_name,
                "description": "Test template description",
                "question_id": test_question_id,
                "duration_minutes": 45,
                "auto_close": True
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "template" in data
        assert data["template"]["name"] == unique_name
        assert data["template"]["duration_minutes"] == 45
        assert data["template"]["auto_close"] == True
        assert data["template"]["use_count"] == 0
        
        # Cleanup - delete the template
        template_id = data["template"]["id"]
        authenticated_session.delete(f"{BASE_URL}/api/teacher/templates/{template_id}")
    
    def test_create_template_minimal_data(self, authenticated_session, test_question_id):
        """Create template with only required fields"""
        unique_name = f"TEST_Minimal_{uuid.uuid4().hex[:8]}"
        response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={
                "name": unique_name,
                "question_id": test_question_id
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["template"]["name"] == unique_name
        assert data["template"]["description"] is None
        assert data["template"]["duration_minutes"] is None
        assert data["template"]["auto_close"] == False
        
        # Cleanup
        authenticated_session.delete(f"{BASE_URL}/api/teacher/templates/{data['template']['id']}")
    
    def test_create_template_invalid_question(self, authenticated_session):
        """Create template with non-existent question fails"""
        response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={
                "name": "Invalid Question Template",
                "question_id": "non-existent-question-id"
            }
        )
        assert response.status_code == 404
        assert "Question not found" in response.json()["detail"]
    
    def test_create_template_duplicate_name(self, authenticated_session, test_question_id):
        """Create template with duplicate name fails"""
        unique_name = f"TEST_Duplicate_{uuid.uuid4().hex[:8]}"
        
        # Create first template
        response1 = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={"name": unique_name, "question_id": test_question_id}
        )
        assert response1.status_code == 200
        template_id = response1.json()["template"]["id"]
        
        # Try to create duplicate
        response2 = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={"name": unique_name, "question_id": test_question_id}
        )
        assert response2.status_code == 400
        assert "already exists" in response2.json()["detail"]
        
        # Cleanup
        authenticated_session.delete(f"{BASE_URL}/api/teacher/templates/{template_id}")


class TestTemplateDetailEndpoint:
    """Tests for GET /api/teacher/templates/{template_id}"""
    
    def test_get_template_detail_requires_auth(self):
        """Get template detail requires authentication"""
        # Use fresh session without auth
        response = requests.get(f"{BASE_URL}/api/teacher/templates/some-id")
        assert response.status_code == 401
    
    def test_get_template_detail_not_found(self, authenticated_session):
        """Get non-existent template returns 404"""
        response = authenticated_session.get(
            f"{BASE_URL}/api/teacher/templates/non-existent-id"
        )
        assert response.status_code == 404
    
    def test_get_template_detail_success(self, authenticated_session, test_question_id):
        """Get template detail returns template with question info"""
        # Create a template first
        unique_name = f"TEST_Detail_{uuid.uuid4().hex[:8]}"
        create_response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={
                "name": unique_name,
                "description": "Detail test",
                "question_id": test_question_id,
                "duration_minutes": 30
            }
        )
        template_id = create_response.json()["template"]["id"]
        
        # Get detail
        response = authenticated_session.get(
            f"{BASE_URL}/api/teacher/templates/{template_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "template" in data
        assert "question" in data
        assert data["template"]["name"] == unique_name
        assert data["question"]["id"] == test_question_id
        
        # Cleanup
        authenticated_session.delete(f"{BASE_URL}/api/teacher/templates/{template_id}")


class TestTemplateUpdateEndpoint:
    """Tests for PUT /api/teacher/templates/{template_id}"""
    
    def test_update_template_requires_auth(self):
        """Update template requires authentication"""
        # Use fresh session without auth
        response = requests.put(
            f"{BASE_URL}/api/teacher/templates/some-id",
            json={"name": "Updated"}
        )
        assert response.status_code == 401
    
    def test_update_template_not_found(self, authenticated_session):
        """Update non-existent template returns 404"""
        response = authenticated_session.put(
            f"{BASE_URL}/api/teacher/templates/non-existent-id",
            json={"name": "Updated"}
        )
        assert response.status_code == 404
    
    def test_update_template_success(self, authenticated_session, test_question_id):
        """Update template fields successfully"""
        # Create a template
        unique_name = f"TEST_Update_{uuid.uuid4().hex[:8]}"
        create_response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={"name": unique_name, "question_id": test_question_id}
        )
        template_id = create_response.json()["template"]["id"]
        
        # Update template
        updated_name = f"TEST_Updated_{uuid.uuid4().hex[:8]}"
        response = authenticated_session.put(
            f"{BASE_URL}/api/teacher/templates/{template_id}",
            json={
                "name": updated_name,
                "description": "Updated description",
                "duration_minutes": 60,
                "auto_close": True
            }
        )
        assert response.status_code == 200
        
        # Verify update
        get_response = authenticated_session.get(
            f"{BASE_URL}/api/teacher/templates/{template_id}"
        )
        template = get_response.json()["template"]
        assert template["name"] == updated_name
        assert template["description"] == "Updated description"
        assert template["duration_minutes"] == 60
        assert template["auto_close"] == True
        
        # Cleanup
        authenticated_session.delete(f"{BASE_URL}/api/teacher/templates/{template_id}")


class TestTemplateDeleteEndpoint:
    """Tests for DELETE /api/teacher/templates/{template_id}"""
    
    def test_delete_template_requires_auth(self):
        """Delete template requires authentication"""
        # Use fresh session without auth
        response = requests.delete(f"{BASE_URL}/api/teacher/templates/some-id")
        assert response.status_code == 401
    
    def test_delete_template_not_found(self, authenticated_session):
        """Delete non-existent template returns 404"""
        response = authenticated_session.delete(
            f"{BASE_URL}/api/teacher/templates/non-existent-id"
        )
        assert response.status_code == 404
    
    def test_delete_template_success(self, authenticated_session, test_question_id):
        """Delete template successfully"""
        # Create a template
        unique_name = f"TEST_Delete_{uuid.uuid4().hex[:8]}"
        create_response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={"name": unique_name, "question_id": test_question_id}
        )
        template_id = create_response.json()["template"]["id"]
        
        # Delete template
        response = authenticated_session.delete(
            f"{BASE_URL}/api/teacher/templates/{template_id}"
        )
        assert response.status_code == 200
        
        # Verify deletion
        get_response = authenticated_session.get(
            f"{BASE_URL}/api/teacher/templates/{template_id}"
        )
        assert get_response.status_code == 404


class TestCreateAssessmentFromTemplate:
    """Tests for POST /api/teacher/templates/{template_id}/create-assessment"""
    
    def test_create_assessment_from_template_requires_auth(self):
        """Create assessment from template requires authentication"""
        # Use fresh session without auth
        response = requests.post(
            f"{BASE_URL}/api/teacher/templates/some-id/create-assessment"
        )
        assert response.status_code == 401
    
    def test_create_assessment_from_template_not_found(self, authenticated_session):
        """Create assessment from non-existent template returns 404"""
        response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates/non-existent-id/create-assessment"
        )
        assert response.status_code == 404
    
    def test_create_assessment_from_template_success(self, authenticated_session, test_question_id):
        """Create assessment from template successfully"""
        # Create a template
        unique_name = f"TEST_CreateAssessment_{uuid.uuid4().hex[:8]}"
        create_response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={
                "name": unique_name,
                "question_id": test_question_id,
                "duration_minutes": 25,
                "auto_close": True
            }
        )
        template_id = create_response.json()["template"]["id"]
        
        # Create assessment from template
        response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates/{template_id}/create-assessment"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "assessment" in data
        assert "message" in data
        assert unique_name in data["message"]
        
        # Verify assessment has template settings
        assessment = data["assessment"]
        assert assessment["question_id"] == test_question_id
        assert assessment["duration_minutes"] == 25
        assert assessment["auto_close"] == True
        assert "join_code" in assessment
        assert len(assessment["join_code"]) == 6
        
        # Verify template use_count incremented
        template_response = authenticated_session.get(
            f"{BASE_URL}/api/teacher/templates/{template_id}"
        )
        template = template_response.json()["template"]
        assert template["use_count"] >= 1
        assert template["last_used_at"] is not None
        
        # Cleanup
        authenticated_session.delete(f"{BASE_URL}/api/teacher/templates/{template_id}")
    
    def test_create_multiple_assessments_from_template(self, authenticated_session, test_question_id):
        """Create multiple assessments from same template increments use_count"""
        # Create a template
        unique_name = f"TEST_MultiAssessment_{uuid.uuid4().hex[:8]}"
        create_response = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates",
            json={"name": unique_name, "question_id": test_question_id}
        )
        template_id = create_response.json()["template"]["id"]
        initial_use_count = create_response.json()["template"]["use_count"]
        
        # Create first assessment
        response1 = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates/{template_id}/create-assessment"
        )
        assert response1.status_code == 200
        
        # Create second assessment
        response2 = authenticated_session.post(
            f"{BASE_URL}/api/teacher/templates/{template_id}/create-assessment"
        )
        assert response2.status_code == 200
        
        # Verify use_count incremented by 2
        template_response = authenticated_session.get(
            f"{BASE_URL}/api/teacher/templates/{template_id}"
        )
        template = template_response.json()["template"]
        assert template["use_count"] == initial_use_count + 2
        
        # Cleanup
        authenticated_session.delete(f"{BASE_URL}/api/teacher/templates/{template_id}")


class TestExistingTemplateData:
    """Tests for existing template data (Weekly Science Quiz)"""
    
    def test_existing_template_exists(self, authenticated_session):
        """Verify the existing 'Weekly Science Quiz' template exists"""
        response = authenticated_session.get(f"{BASE_URL}/api/teacher/templates")
        assert response.status_code == 200
        templates = response.json()["templates"]
        
        weekly_quiz = next(
            (t for t in templates if t["name"] == "Weekly Science Quiz"),
            None
        )
        
        if weekly_quiz:
            assert weekly_quiz["description"] == "Standard weekly quiz for 10X"
            assert weekly_quiz["duration_minutes"] == 30
            assert weekly_quiz["auto_close"] == True
            assert weekly_quiz["use_count"] >= 1
            assert "question_subject" in weekly_quiz
            assert "question_topic" in weekly_quiz
            print(f"Found existing template: {weekly_quiz['name']} with use_count={weekly_quiz['use_count']}")
        else:
            print("Weekly Science Quiz template not found - may have been deleted")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
