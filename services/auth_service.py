from passlib.context import CryptContext
import secrets
from datetime import datetime, timezone, timedelta
import os
import logging
import resend
from fastapi import HTTPException, Request
from utils.database import db
from models.user_models import User
import requests
import time
from jose import jwt, JWTError
from google.oauth2 import id_token
from google.auth.transport import requests as google_auth_requests

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Email configuration
resend.api_key = os.environ.get('RESEND_API_KEY')

# Azure AD configuration
AZURE_TENANT_ID = os.environ.get('AZURE_TENANT_ID')
AZURE_CLIENT_ID = os.environ.get('AZURE_BACKEND_CLIENT_ID')
AZURE_CLIENT_SECRET = os.environ.get('AZURE_CLIENT_SECRET')
JWKS_URL = "https://login.microsoftonline.com/common/discovery/v2.0/keys"

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')

# JWKS cache
jwks_cache = {"keys": None, "last_updated": 0}
JWKS_CACHE_TTL = 3600  # 1 hour

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)

async def send_reset_email(email: str, token: str, name: str):
    """Send password reset email"""
    if not resend.api_key:
        raise HTTPException(status_code=500, detail="Email service not configured")
    
    # Get frontend URL from environment (required for deployment)
    frontend_url = os.environ.get('FRONTEND_URL')
    if not frontend_url:
        raise HTTPException(status_code=500, detail="FRONTEND_URL not configured")
    reset_url = f"{frontend_url}/reset-password?token={token}"
    
    try:
        params = {
            "from": "BlueAI <noreply@blueai.app>",
            "to": [email],
            "subject": "Reset Your BlueAI Password",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #2563eb;">Reset Your Password</h2>
                <p>Hi {name},</p>
                <p>You requested to reset your password for your BlueAI account. Click the button below to set a new password:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Reset Password</a>
                </div>
                <p>If the button doesn't work, copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666;">{reset_url}</p>
                <p>This link will expire in 1 hour for security reasons.</p>
                <p>If you didn't request this password reset, please ignore this email.</p>
                <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
                <p style="color: #666; font-size: 12px;">BlueAI Assessment Platform</p>
            </div>
            """
        }
        
        response = resend.Emails.send(params)
        return response
        
    except Exception as e:
        logging.error(f"Failed to send reset email: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send email")

def get_jwks():
    """Fetch and cache JWKS from Azure AD"""
    current_time = time.time()
    if jwks_cache["keys"] is None or (current_time - jwks_cache["last_updated"]) > JWKS_CACHE_TTL:
        try:
            response = requests.get(JWKS_URL, timeout=10)
            response.raise_for_status()
            jwks_cache["keys"] = response.json()
            jwks_cache["last_updated"] = current_time
            logging.info("Successfully fetched JWKS from Azure AD")
        except Exception as e:
            logging.error(f"Failed to fetch JWKS: {str(e)}")
            if jwks_cache["keys"] is None:
                raise HTTPException(status_code=503, detail="Authentication service unavailable")
    return jwks_cache["keys"]

def verify_azure_token(token: str):
    """Verify and decode Azure AD access token"""
    try:
        # Get the token header to find the key ID
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        
        if not kid:
            raise HTTPException(status_code=401, detail="Token missing key ID")
        
        # Get JWKS and find the matching key
        jwks = get_jwks()
        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = k
                break
        
        if not key:
            raise HTTPException(status_code=401, detail="Unable to find appropriate signing key")
        
        # Convert JWK to PEM format
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import base64
        
        def base64_to_long(data: str) -> int:
            if isinstance(data, str):
                data = data.encode("ascii")
            decoded = base64.urlsafe_b64decode(data + b"==")
            return int.from_bytes(decoded, byteorder="big")
        
        n = base64_to_long(key['n'])
        e = base64_to_long(key['e'])
        public_key = rsa.RSAPublicNumbers(e, n).public_key()
        pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # Verify and decode the token
        payload = jwt.decode(
            token,
            pem,
            algorithms=["RS256"],
            audience=AZURE_CLIENT_ID,
            options={"verify_exp": True}
        )
        
        # Validate issuer format for v2.0 tokens
        iss = payload.get('iss', '')
        tid = payload.get('tid', '')
        if not tid or iss != f"https://login.microsoftonline.com/{tid}/v2.0":
            logging.error(f"Invalid token issuer: {iss}")
            raise HTTPException(status_code=401, detail="Invalid token issuer")
        
        return payload
    except JWTError as e:
        logging.error(f"Token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logging.error(f"Unexpected error during token verification: {str(e)}")
        raise HTTPException(status_code=401, detail="Token verification failed")

def verify_google_token(token: str) -> dict:
    """Verify and decode a Google OAuth ID token"""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google authentication not configured")
    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            google_auth_requests.Request(),
            GOOGLE_CLIENT_ID
        )
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise HTTPException(status_code=401, detail="Invalid token issuer")
        return idinfo
    except ValueError as e:
        logging.error(f"Google token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid Google token")
