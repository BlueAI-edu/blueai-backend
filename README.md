# BlueAI Backend

FastAPI-based backend for the BlueAI Assessment Platform.

## Overview

BlueAI is an AI-powered educational assessment platform for teachers to create assessments and students to submit answers for AI marking.

## Tech Stack

- **Framework**: FastAPI
- **Database**: MongoDB (Motor async driver)
- **AI**: OpenAI GPT-4o
- **PDF Generation**: ReportLab
- **Authentication**: JWT tokens

## Project Structure

```
.
├── server.py              # Main FastAPI application
├── requirements.txt       # Python dependencies
├── example.env           # Environment variables template
├── routes/               # API route modules
│   ├── auth_routes.py
│   ├── public_routes.py
│   ├── classes_routes.py
│   └── enhanced_assessments.py
├── services/             # Business logic
│   ├── ai_question_generator.py
│   ├── ai_multi_question_generator.py
│   ├── marking_service.py
│   ├── analytics_service.py
│   ├── pdf_service.py
│   └── ...
├── models/               # Pydantic models
├── utils/                # Utilities (database, dependencies)
├── tests/                # Test suite
└── docs/                 # Documentation
    └── PRD.md           # Product Requirements Document
```

## Setup

1. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment:
   ```bash
   cp example.env .env
   # Edit .env with your actual values
   ```

4. Run the server:
   ```bash
   uvicorn server:app --reload
   ```

## Environment Variables

Required variables (see `example.env`):
- `MONGO_URL` - MongoDB connection string
- `DB_NAME` - Database name
- `OPENAI_API_KEY` - OpenAI API key for AI marking
- `RESEND_API_KEY` - Email service API key
- `AZURE_TENANT_ID` - Azure AD tenant (for OAuth)
- `AZURE_BACKEND_CLIENT_ID` - Azure AD client ID
- `AZURE_CLIENT_SECRET` - Azure AD client secret

## API Documentation

Once running, access:
- API docs: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

## Testing

Run tests with pytest:
```bash
pytest tests/
```

## Features

- Teacher authentication and management
- Question creation with mark schemes
- Assessment management with time limits
- Student attempt tracking with auto-save
- AI-powered marking and feedback
- PDF report generation
- Class and student management
- CSV import for students
- Analytics and heatmaps

## License

Private - All rights reserved.
