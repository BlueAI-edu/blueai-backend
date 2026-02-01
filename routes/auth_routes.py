from fastapi import APIRouter, HTTPException, Request, Response, Depends
from datetime import datetime, timezone, timedelta
import httpx
import uuid
import secrets
import logging
from models.user_models import User, UserRegister, UserLogin, PasswordReset, PasswordResetConfirm, UpdateProfile
from services.auth_service import hash_password, verify_password, send_reset_email, verify_azure_token
from utils.database import db
from utils.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/session")
async def create_session(request: Request, response: Response):
    body = await request.json()
    session_id = body.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": session_id}
        )
        
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session_id")
        
        data = resp.json()
    
    # Check if user exists
    existing_user = await db.users.find_one({"email": data["email"]}, {"_id": 0})
    
    if existing_user:
        user_id = existing_user["user_id"]
        # Update user info
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "name": data["name"],
                "picture": data.get("picture")
            }}
        )
    else:
        # Create new user with teacher role by default
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": data["email"],
            "name": data["name"],
            "role": "teacher",
            "picture": data.get("picture"),
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    
    # Create session
    session_token = data["session_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Set httpOnly cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7*24*60*60
    )
    
    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])
    
    return User(**user_doc)

@router.get("/me", response_model=User)
async def get_me(user: User = Depends(get_current_user)):
    return user

@router.post("/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    response.delete_cookie("session_token", path="/")
    return {"message": "Logged out"}

@router.post("/register", response_model=User)
async def register(user_data: UserRegister, response: Response):
    # Check if user already exists
    existing_user = await db.users.find_one({"email": user_data.email}, {"_id": 0})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create new user
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    hashed_password = hash_password(user_data.password)
    
    user_doc = {
        "user_id": user_id,
        "email": user_data.email,
        "name": user_data.name,
        "role": "teacher",
        "password_hash": hashed_password,
        "display_name": user_data.name,
        "school_name": user_data.school_name,
        "department": user_data.department,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.users.insert_one(user_doc)
    
    # Create session
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Set httpOnly cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7*24*60*60
    )
    
    # Return user (without password_hash)
    user_doc.pop('password_hash', None)
    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])
    
    return User(**user_doc)

@router.post("/login", response_model=User)
async def login(login_data: UserLogin, response: Response):
    # Find user by email
    user_doc = await db.users.find_one({"email": login_data.email}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Check if user has password_hash (email/password user)
    if not user_doc.get('password_hash'):
        raise HTTPException(status_code=401, detail="Please use Google sign-in for this account")
    
    # Verify password
    if not verify_password(login_data.password, user_doc['password_hash']):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Create session
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    await db.user_sessions.insert_one({
        "user_id": user_doc["user_id"],
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Set httpOnly cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7*24*60*60
    )
    
    # Return user (without password_hash)
    user_doc.pop('password_hash', None)
    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])
    
    return User(**user_doc)

@router.post("/forgot-password")
async def forgot_password(reset_data: PasswordReset):
    # Find user by email
    user_doc = await db.users.find_one({"email": reset_data.email}, {"_id": 0})
    if not user_doc:
        # Don't reveal if email exists or not for security
        return {"message": "If the email exists, a reset link has been sent"}
    
    # Check if user has password_hash (email/password user)
    if not user_doc.get('password_hash'):
        return {"message": "If the email exists, a reset link has been sent"}
    
    # Generate reset token
    from services.auth_service import generate_reset_token
    reset_token = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    
    # Store reset token
    await db.password_resets.insert_one({
        "user_id": user_doc["user_id"],
        "token": reset_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "used": False
    })
    
    # Send email
    try:
        await send_reset_email(user_doc["email"], reset_token, user_doc["name"])
    except Exception as e:
        logging.error(f"Failed to send reset email: {str(e)}")
        # Don't fail the request, just log the error
    
    return {"message": "If the email exists, a reset link has been sent"}

@router.post("/reset-password")
async def reset_password(reset_data: PasswordResetConfirm):
    # Find valid reset token
    reset_doc = await db.password_resets.find_one({
        "token": reset_data.token,
        "used": False
    }, {"_id": 0})
    
    if not reset_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Check if token is expired
    expires_at = datetime.fromisoformat(reset_doc["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset token has expired")
    
    # Update user password
    new_password_hash = hash_password(reset_data.new_password)
    await db.users.update_one(
        {"user_id": reset_doc["user_id"]},
        {"$set": {"password_hash": new_password_hash}}
    )
    
    # Mark token as used
    await db.password_resets.update_one(
        {"token": reset_data.token},
        {"$set": {"used": True}}
    )
    
    # Invalidate all existing sessions for this user
    await db.user_sessions.delete_many({"user_id": reset_doc["user_id"]})
    
    return {"message": "Password reset successfully"}

@router.post("/microsoft", response_model=User)
async def microsoft_auth(request: Request, response: Response):
    """Authenticate with Microsoft OAuth - accepts Azure AD access token"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="No token provided")
        
        token = auth_header.split(" ")[1]
        
        # Verify the Azure AD token
        payload = verify_azure_token(token)
        
        # Extract user information
        email = payload.get("email") or payload.get("upn") or payload.get("preferred_username")
        name = payload.get("name", "Unknown User")
        tenant_id = payload.get("tid")
        
        if not email:
            raise HTTPException(status_code=400, detail="Email not found in token")
        
        # Check if user exists
        existing_user = await db.users.find_one({"email": email}, {"_id": 0})
        
        if existing_user:
            # Update last login and auth provider info
            await db.users.update_one(
                {"email": email},
                {
                    "$set": {
                        "last_login": datetime.now(timezone.utc),
                        "auth_provider": "microsoft",
                        "tenant_id": tenant_id
                    }
                }
            )
            
            # Create session
            session_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            await db.user_sessions.insert_one({
                "user_id": existing_user["user_id"],
                "session_token": session_token,
                "expires_at": expires_at.isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            })
            
            # Set httpOnly cookie
            response.set_cookie(
                key="session_token",
                value=session_token,
                httponly=True,
                secure=True,
                samesite="none",
                path="/",
                max_age=30*24*60*60
            )
            
            # Parse created_at if it's a string
            if isinstance(existing_user.get('created_at'), str):
                existing_user['created_at'] = datetime.fromisoformat(existing_user['created_at'])
            
            logging.info(f"Microsoft user logged in: {email}")
            
            return User(**existing_user)
        else:
            # Create new user
            user_id = str(uuid.uuid4())
            new_user = {
                "user_id": user_id,
                "email": email,
                "name": name,
                "role": "teacher",
                "auth_provider": "microsoft",
                "tenant_id": tenant_id,
                "display_name": name,
                "created_at": datetime.now(timezone.utc),
                "last_login": datetime.now(timezone.utc)
            }
            
            await db.users.insert_one(new_user)
            
            # Create session
            session_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            await db.user_sessions.insert_one({
                "user_id": user_id,
                "session_token": session_token,
                "expires_at": expires_at.isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            })
            
            # Set httpOnly cookie
            response.set_cookie(
                key="session_token",
                value=session_token,
                httponly=True,
                secure=True,
                samesite="none",
                path="/",
                max_age=30*24*60*60
            )
            
            logging.info(f"Created new Microsoft user: {email}")
            
            return User(**new_user)
    
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Microsoft authentication error: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication failed")

@router.put("/profile", response_model=User)
async def update_profile(profile_data: UpdateProfile, user: User = Depends(get_current_user)):
    # Build update data
    update_data = {}
    if profile_data.name is not None:
        update_data["name"] = profile_data.name
    if profile_data.display_name is not None:
        update_data["display_name"] = profile_data.display_name
    if profile_data.school_name is not None:
        update_data["school_name"] = profile_data.school_name
    if profile_data.department is not None:
        update_data["department"] = profile_data.department
    
    if update_data:
        await db.users.update_one(
            {"user_id": user.user_id},
            {"$set": update_data}
        )
    
    # Return updated user
    updated_user = await db.users.find_one({"user_id": user.user_id}, {"_id": 0})
    updated_user.pop('password_hash', None)
    if isinstance(updated_user['created_at'], str):
        updated_user['created_at'] = datetime.fromisoformat(updated_user['created_at'])
    
    return User(**updated_user)
