# BlueAI Assessment - Product Requirements Document

## Original Problem Statement
The user wants to stabilize and enhance an MVP web application called "BlueAI Assessment" - an AI-powered educational assessment platform for teachers to create assessments and students to submit answers for AI marking.

## Core Features

### 1. Authentication
- **Email/Password Auth**: Working - Registration, login, password reset
- **Google OAuth**: NOT WORKING - Persistent issue with CORS/redirect configuration
- **Microsoft OAuth**: REMOVED from UI at user request

### 2. Teacher Features
- Create and manage questions with mark schemes
- Create assessments with optional time limits (can be linked to classes)
- Start/close assessments with unique join codes
- View all student submissions
- Download PDF feedback reports
- **Release Feedback Control** - Teachers can control when students see their feedback
- **Bulk Release Feedback** - Release feedback for all marked submissions at once

### 3. Student Features
- Join assessments via join code
- **Class-linked assessments**: Students select name from dropdown (Phase 4)
- **Fullscreen Enforcement** - Students must be in fullscreen mode during assessment
- Answer questions with timed submissions
- **Auto-save** - Answers saved every 15 seconds
- **Anti-cheat** - Copy/paste/right-click disabled, focus-loss logged, fullscreen exit logged
- View feedback after teacher releases it
- Download feedback PDF

### 4. AI Features
- **AI Marking**: Using GPT-4o via emergentintegrations library
- Automatic scoring, WWW (What Went Well), Next Steps, Overall Feedback
- **OCR**: Azure Computer Vision (CURRENTLY BROKEN - 401 credential error)

### 5. Classes & Students Module (NEW - Phases 1-4 COMPLETE)
- **Phase 1**: Create/edit classes, manually add students ✅
- **Phase 2**: CSV import with preview, deduplication, auto-class creation ✅
- **Phase 3**: Class Analytics - score trends, support indicators, topics to reteach, CSV/PDF export ✅
- **Phase 4**: Assessment-Class linking, student dropdown in join flow ✅

## Tech Stack
- **Frontend**: React, React Router, Tailwind CSS, Axios, Recharts, Papaparse
- **Backend**: FastAPI, Motor (MongoDB async), Pydantic
- **Database**: MongoDB
- **AI**: OpenAI GPT-4o via Emergent LLM Key
- **PDF**: ReportLab

## API Endpoints

### Auth
- `POST /api/auth/register` - Email registration
- `POST /api/auth/login` - Email login
- `POST /api/auth/logout` - Logout
- `GET /api/auth/me` - Get current user
- `GET /api/health` - Health check

### Teacher
- `GET/POST /api/teacher/questions` - CRUD questions
- `GET/POST /api/teacher/assessments` - CRUD assessments (now with class_id support)
- `POST /api/teacher/assessments/{id}/start` - Start assessment
- `POST /api/teacher/assessments/{id}/close` - Close assessment
- `GET /api/teacher/submissions/{id}` - Get submission details
- `GET /api/teacher/submissions/{id}/download-pdf` - Download feedback PDF
- `POST /api/teacher/submissions/{id}/release-feedback` - Release feedback to student
- `POST /api/teacher/assessments/{id}/release-all-feedback` - Bulk release all feedback
- `GET /api/teacher/assessments/{id}/security-report` - Get security report

### Classes & Students (NEW)
- `GET/POST /api/teacher/classes` - List/create classes
- `GET/PUT/DELETE /api/teacher/classes/{class_id}` - Class CRUD
- `GET /api/teacher/classes/{class_id}/analytics` - Class analytics (Phase 3)
- `GET /api/teacher/classes/{class_id}/analytics/export-csv` - CSV export
- `GET /api/teacher/classes/{class_id}/analytics/export-pdf` - PDF export
- `GET/POST /api/teacher/students` - List/create students
- `GET/PUT/DELETE /api/teacher/students/{student_id}` - Student CRUD
- `GET /api/teacher/students/csv-template` - Download CSV template
- `POST /api/teacher/students/csv-preview` - Preview CSV import
- `POST /api/teacher/students/csv-import` - Execute CSV import
- `GET /api/teacher/classes/{class_id}/students-dropdown` - Get students for dropdown

### Student/Public
- `POST /api/public/join` - Join assessment (now with student_id support)
- `GET /api/public/attempt/{id}` - Get attempt details
- `POST /api/public/attempt/{id}/autosave` - Auto-save answer
- `POST /api/public/attempt/{id}/submit` - Submit answer
- `POST /api/public/attempt/{id}/log-security-event` - Log security events
- `GET /api/public/assessment/{join_code}/class-roster` - Get student roster (Phase 4)

## Database Schema

### users
```json
{
  "user_id": "string",
  "email": "string",
  "name": "string",
  "role": "teacher|admin",
  "password_hash": "string (optional)",
  "auth_provider": "email|google|microsoft",
  "school_name": "string (optional)",
  "created_at": "datetime"
}
```

### classes (NEW)
```json
{
  "id": "string",
  "teacher_owner_id": "string",
  "class_name": "string",
  "subject": "string (optional)",
  "year_group": "string (optional)",
  "created_at": "datetime"
}
```

### students (NEW)
```json
{
  "id": "string",
  "teacher_owner_id": "string",
  "class_id": "string",
  "first_name": "string",
  "last_name": "string",
  "preferred_name": "string (optional)",
  "student_code": "string (optional)",
  "sen_flag": "boolean",
  "pupil_premium_flag": "boolean",
  "eal_flag": "boolean",
  "archived": "boolean",
  "created_at": "datetime"
}
```

### assessments
```json
{
  "id": "string",
  "owner_teacher_id": "string",
  "question_id": "string",
  "class_id": "string (optional, Phase 4)",
  "join_code": "string",
  "status": "draft|started|closed",
  "duration_minutes": "int (optional)",
  "created_at": "datetime"
}
```

### attempts
```json
{
  "attempt_id": "string",
  "assessment_id": "string",
  "owner_teacher_id": "string",
  "student_name": "string",
  "student_id": "string (optional, Phase 4)",
  "class_id": "string (optional, Phase 4)",
  "answer_text": "string",
  "status": "in_progress|submitted|marked|error",
  "score": "int",
  "www": "string",
  "next_steps": "string",
  "overall_feedback": "string",
  "feedback_released": "bool (default: false)"
}
```

## Code Architecture (Refactored)
```
/app/
├── backend/
│   ├── .env
│   ├── server.py               # Main FastAPI app (~2750 lines, reduced from 3500)
│   ├── routes/
│   │   ├── auth_routes.py      # Authentication routes
│   │   ├── public_routes.py    # Public student routes
│   │   └── classes_routes.py   # Classes & Students routes (NEW - 920+ lines)
│   ├── models/
│   │   ├── user_models.py
│   │   ├── assessment_models.py
│   │   └── classes_models.py   # NEW - Classes & Students models
│   ├── services/
│   │   ├── analytics_service.py
│   │   ├── marking_service.py
│   │   └── pdf_service.py
│   └── utils/
│       ├── database.py
│       └── dependencies.py
├── frontend/
│   └── src/
│       ├── App.js              # Main React app (~1500 lines)
│       └── components/
│           ├── TeacherPages.js     # With class selector for assessments
│           ├── ClassesPage.js      # Classes management + Analytics tab
│           ├── CSVImportPage.js    # CSV student import
│           └── AnalyticsPage.js    # General analytics
└── memory/
    └── PRD.md
```

## Known Issues
1. **Google OAuth**: Not working - CORS/redirect issues (BLOCKED)
2. **OCR**: Not working - 401 credential error (needs valid Azure credentials)

## Completed Work (This Session)
- ✅ Backend refactoring: Extracted classes/students routes into modular file
- ✅ Phase 3: Class Analytics with score trends, support indicators, topics to reteach
- ✅ Phase 3: CSV and PDF export for class analytics
- ✅ Phase 4: Assessment-class linking (class_id field in assessments)
- ✅ Phase 4: Student dropdown in join flow when assessment is class-linked
- ✅ P2: Teacher feedback moderation (edit AI-generated feedback before release)
- ✅ P2: Regenerate PDF button (useful after editing feedback)
- ✅ P2: Teacher Profile Page with stats and profile editing
- ✅ Batch export: CSV export for all assessment submissions
- ✅ Batch export: ZIP download for all PDFs
- ✅ Email PDF reports: Single student and bulk email to all students with email addresses
- ✅ Student email field: Added to student model and forms
- ✅ Performance Heatmap: Students x Assessments color-coded matrix view
- ✅ Bug fix: Analytics now uses percentage instead of raw scores
- ✅ Assessment Templates (P3): Save and reuse assessment configurations
- ✅ Testing: All backend and frontend tests passed

## Future Tasks
- Google OAuth fix (BLOCKED - complex CORS/redirect issue)
- OCR marking (BLOCKED - 401 credential error)
