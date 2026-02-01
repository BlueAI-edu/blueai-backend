# BlueAI Assessment - Build Version
# This file forces cache invalidation for deployment

BUILD_VERSION = "2.0.1"
BUILD_DATE = "2026-01-10"
BUILD_ID = "syntax-fix-final"

# Changes in this build:
# - Fixed syntax error at line 1035 (removed orphaned code)
# - Added /health endpoint for deployment health checks
# - Added /root endpoint
# - Fixed join_assessment function completion
# - Added OCR import safety with graceful fallback
# - Verified AST parsing and compilation success
