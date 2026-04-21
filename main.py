from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, UploadFile, File, Path, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import uuid
import uvicorn
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from typing import Dict, Optional

from models.schemas import (
    VoiceChatResponse, 
    ChatHistoryResponse, 
    BackendStatusResponse,
    APIKeyConfig,
    ErrorType,
    WebSearchResponse,
    WebSearchResult
)
# auth schemas removed — authentication functionality has been stripped
from services.stt_service import STTService
from services.llm_service import LLMService
from services.tts_service import TTSService
from services.database_service import DatabaseService
from services.assemblyai_streaming_service import AssemblyAIStreamingService
from services.murf_websocket_service import MurfWebSocketService
# new services
from services.custom_web_search_service import custom_web_search_service as web_search_service
from services.skills_manager import skills_manager
from services.auth_service import auth_service
from services.email_service import EmailService
# pymongo.errors import removed (used only by auth code which is stripped)
from utils.logging_config import setup_logging, get_logger
from utils.constants import get_fallback_message
from authlib.integrations.starlette_client import OAuth

# Load environment variables
load_dotenv()
setup_logging()
logger = get_logger(__name__)
# Reduce noise from passlib bcrypt backend warnings when bcrypt package layout differs
import logging as _logging
_logging.getLogger('passlib.handlers.bcrypt').setLevel(_logging.ERROR)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting Voice Agent application...")
    config = initialize_services()
    if database_service:
        try:
            db_connected = await database_service.connect()
            if db_connected:
                logger.info("✅ Database service connected successfully")
            else:
                logger.warning("⚠️ Database service running in fallback mode")
        except Exception as e:
            logger.error(f"❌ Database service initialization error: {e}")
    else:
        logger.error("❌ Database service not initialized")

    logger.info("✅ Application startup completed")

    yield

    # Shutdown
    logger.info("🛑 Shutting down Voice Agent application...")

    if database_service:
        await database_service.close()

    # Clean up session locks
    global session_locks
    session_locks.clear()

    logger.info("✅ Application shutdown completed")

# Initialize FastAPI app
app = FastAPI(
    title="30 Days of Voice Agents - AI Voice Assistant",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
stt_service: Optional[STTService] = None
llm_service: Optional[LLMService] = None
tts_service: Optional[TTSService] = None
database_service: Optional[DatabaseService] = None
assemblyai_streaming_service: Optional[AssemblyAIStreamingService] = None
murf_websocket_service: Optional[MurfWebSocketService] = None
email_service: Optional[EmailService] = None


def initialize_services(config: APIKeyConfig = None) -> APIKeyConfig:
    """Initialize all services with API keys from the provided config or environment variables.

    This is a minimal, safe initializer used at startup and when updating configuration.
    It will attempt to construct each service and fallback to None on error, logging failures.
    """
    global stt_service, llm_service, tts_service, database_service, assemblyai_streaming_service, murf_websocket_service

    # Build config from environment if not provided
    if config is None:
        config = APIKeyConfig(
            personas=["default", "pirate", "developer", "cowboy", "robot"],
            selected_persona=os.getenv("AGENT_PERSONA", "default"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            assemblyai_api_key=os.getenv("ASSEMBLYAI_API_KEY"),
            murf_api_key=os.getenv("MURF_API_KEY"),
            murf_voice_id=os.getenv("MURF_VOICE_ID", "en-US-amara"),
            mongodb_url=os.getenv("MONGODB_URL")
        )

    # Initialize each service defensively
    try:
        if config.assemblyai_api_key:
            try:
                stt_service = STTService(config.assemblyai_api_key)
            except Exception as e:
                logger.error(f"Failed to initialize STTService: {e}")
                stt_service = None

            try:
                assemblyai_streaming_service = AssemblyAIStreamingService(config.assemblyai_api_key)
            except Exception as e:
                logger.error(f"Failed to initialize AssemblyAIStreamingService: {e}")
                assemblyai_streaming_service = None
        else:
            stt_service = None
            assemblyai_streaming_service = None

        if config.gemini_api_key:
            try:
                llm_service = LLMService(config.gemini_api_key, persona=config.selected_persona)
            except Exception as e:
                logger.error(f"Failed to initialize LLMService: {e}")
                llm_service = None
        else:
            llm_service = None

        if config.murf_api_key:
            try:
                tts_service = TTSService(config.murf_api_key, voice_id=config.murf_voice_id)
            except Exception as e:
                logger.error(f"Failed to initialize TTSService: {e}")
                tts_service = None
            try:
                murf_websocket_service = MurfWebSocketService(config.murf_api_key, voice_id=config.murf_voice_id)
            except Exception as e:
                logger.error(f"Failed to initialize MurfWebSocketService: {e}")
                murf_websocket_service = None
        else:
            tts_service = None
            murf_websocket_service = None

        try:
            database_service = DatabaseService(config.mongodb_url)
        except Exception as e:
            logger.error(f"Failed to initialize DatabaseService: {e}")
            database_service = None

        # Initialize email service
        try:
            email_service = EmailService()
        except Exception as e:
            logger.error(f"Failed to initialize EmailService: {e}")
            email_service = None

        # Wire auth service to database if available
        try:
            auth_service.db = database_service
        except Exception:
            pass

        # If persona provided, set it on the LLM service
        if llm_service and config.selected_persona:
            try:
                llm_service.set_persona(config.selected_persona)
            except Exception:
                pass

        return config

    except Exception as e:
        logger.error(f"Unexpected error while initializing services: {e}")
        # Ensure globals are at least defined
        stt_service = stt_service if 'stt_service' in globals() else None
        llm_service = llm_service if 'llm_service' in globals() else None
        tts_service = tts_service if 'tts_service' in globals() else None
        database_service = database_service if 'database_service' in globals() else None
        assemblyai_streaming_service = assemblyai_streaming_service if 'assemblyai_streaming_service' in globals() else None
        murf_websocket_service = murf_websocket_service if 'murf_websocket_service' in globals() else None
        return config


# Initialize OAuth (Authlib) with Google configuration
oauth: Optional[OAuth] = None
def initialize_oauth(app: FastAPI):
    global oauth
    oauth = OAuth()
    google_client_id = os.getenv('GOOGLE_CLIENT_ID')
    google_client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.getenv('OAUTH_REDIRECT_URI', 'http://127.0.0.1:8000/auth/callback/google')

    if google_client_id and google_client_secret:
        oauth.register(
            name='google',
            client_id=google_client_id,
            client_secret=google_client_secret,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'},
        )
    else:
        oauth = None


# Initialize OAuth at module import time (will use env vars)
try:
    initialize_oauth(app)
except Exception:
    oauth = None


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main application page."""
    try:
        # Prefer session_id from query params if provided (frontend may pass it); otherwise generate one
        session_id = request.query_params.get('session_id') or str(uuid.uuid4())
        # timestamp used for cache-busting static assets (app.js?v={{ timestamp }})
        timestamp = int(datetime.now().timestamp())
        return templates.TemplateResponse("index.html", {"request": request, "session_id": session_id, "timestamp": timestamp})
    except Exception as e:
        logger.error(f"Error rendering index.html: {e}")
        raise HTTPException(status_code=500, detail="Failed to render index")


@app.get("/agent/chat/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history_endpoint(session_id: str = Path(..., description="Session ID")):
    """Get chat history for a session"""
    try:
        if not database_service:
            return ChatHistoryResponse(
                success=False,
                session_id=session_id,
                messages=[],
                message_count=0,
                error="Database service not available"
            )
            
        chat_history = await database_service.get_chat_history(session_id)
        return ChatHistoryResponse(
            success=True,
            session_id=session_id,
            messages=chat_history,
            message_count=len(chat_history)
        )
    except Exception as e:
        logger.error(f"Error getting chat history for session {session_id}: {str(e)}")
        return ChatHistoryResponse(
            success=False,
            session_id=session_id,
            messages=[],
            message_count=0,
            error=str(e)
        )


from fastapi import Request as FastAPIRequest


@app.get("/agent/chat/all")
async def get_all_chat_histories_endpoint(request: FastAPIRequest):
    """Get all chat histories across sessions (used by frontend conversation history viewer).

    If an Authorization: Bearer <token> header is provided, the endpoint will verify the token
    and return only sessions attributed to that user (by user_id). Otherwise returns all sessions.
    """
    try:
        if not database_service:
            return {"success": False, "chat_histories": [], "error": "Database service not available"}

        histories = await database_service.get_all_chat_histories()

        # read optional Authorization header
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        user_id = None
        if auth and isinstance(auth, str) and auth.lower().startswith("bearer "):
            token = auth.split(None, 1)[1]
            payload = auth_service.verify_token(token)
            if payload and payload.get("user_id"):
                user_id = payload.get("user_id")

        if user_id:
            filtered = []
            for s in histories:
                sid_user = None
                # support both MongoDB document shape and the in-memory shapes we use as fallback
                if isinstance(s, dict):
                    sid_user = s.get("user_id")
                    # some older records might store metadata under different keys
                    if not sid_user:
                        sid_user = s.get("session_owner") or s.get("owner")
                    # if in-memory structure uses nested dict
                    if not sid_user and isinstance(s.get("messages"), dict):
                        sid_user = s.get("messages").get("user_id")

                if sid_user == user_id:
                    filtered.append(s)

            histories = filtered

        # Ensure returned data is JSON serializable (datetime -> isoformat)
        def normalize_session(sess):
            try:
                sess_copy = dict(sess)
            except Exception:
                return sess

            msgs = sess_copy.get("messages") or []
            norm_msgs = []
            for m in msgs:
                try:
                    m_copy = dict(m)
                except Exception:
                    m_copy = m
                ts = m_copy.get("timestamp")
                try:
                    if hasattr(ts, "isoformat"):
                        m_copy["timestamp"] = ts.isoformat()
                except Exception:
                    pass
                norm_msgs.append(m_copy)
            sess_copy["messages"] = norm_msgs

            lu = sess_copy.get("last_updated")
            try:
                if hasattr(lu, "isoformat"):
                    sess_copy["last_updated"] = lu.isoformat()
            except Exception:
                pass

            return sess_copy

        normalized = [normalize_session(s) for s in histories]
        return {"success": True, "chat_histories": normalized}
    except Exception as e:
        logger.error(f"Error getting all chat histories: {str(e)}")
        return {"success": False, "chat_histories": [], "error": str(e)}

@app.delete("/agent/chat/{session_id}/history")
async def clear_session_history(session_id: str = Path(..., description="Session ID")):
    """Clear chat history for a specific session"""
    try:
        if not database_service:
            return {"success": False, "message": "Database service not available"}
            
        success = await database_service.clear_session_history(session_id)
        if success:
            logger.info(f"Chat history cleared for session: {session_id}")
            return {"success": True, "message": f"Chat history cleared for session {session_id}"}
        else:
            return {"success": False, "message": f"Failed to clear chat history for session {session_id}"}
    except Exception as e:
        logger.error(f"Error clearing session history for {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/config")
async def update_configuration(config: APIKeyConfig):
    """Update API key configuration"""
    try:
        # Reinitialize services with the new configuration
        initialize_services(config)
        
        return {
            "success": True,
            "message": "Configuration updated successfully",
            "services_initialized": {
                "stt": stt_service is not None,
                "llm": llm_service is not None,
                "tts": tts_service is not None,
                "database": database_service is not None,
                "assemblyai_streaming": assemblyai_streaming_service is not None,
                "murf_websocket": murf_websocket_service is not None
            }
        }
    except Exception as e:
        logger.error(f"Error updating configuration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update configuration: {str(e)}")


@app.post("/auth/signup")
async def signup(request: Request):
    """Register a new user and send welcome email"""
    body = await request.json()
    email = body.get("email", "").strip().lower()
    first_name = body.get("first_name", "")
    last_name = body.get("last_name", "")
    password = body.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    # Validate email and normalize
    validation = auth_service.validate_email(email)
    if not validation.get("is_valid"):
        raise HTTPException(status_code=400, detail=validation.get("error") or "Invalid email")
    normalized_email = validation.get("normalized_email")

    # Optionally require deliverability check (best-effort) before creating the user
    require_deliv = os.getenv('REQUIRE_EMAIL_DELIVERABILITY', 'false').lower() in ('1', 'true', 'yes')
    if require_deliv:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, auth_service.check_email_deliverability, normalized_email)
            if not result.get('ok'):
                # If deliverability explicitly fails, reject registration
                raise HTTPException(status_code=400, detail=f"Email deliverability check failed: {result.get('reason')}")
        except HTTPException:
            raise
        except Exception as e:
            # If the check cannot complete (DNS/network errors), log and allow registration
            logger.warning(f"Email deliverability pre-check failed (continuing): {e}")

    try:
        user = await auth_service.create_user(normalized_email, first_name, last_name, password)
    except ValueError as ve:
        raise HTTPException(status_code=409, detail=str(ve))
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")

    # Send welcome email in background if email service configured
    try:
        if email_service and email_service.is_configured():
            subject = "Welcome to TalkEasy"
            body_text = f"Hi {first_name or ''},\n\nThanks for signing up for TalkEasy. Your account has been created.\n\nRegards,\nTalkEasy Team"
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, email_service.send_email, normalized_email, subject, body_text)
        else:
            logger.info("EmailService not configured - skipping welcome email")
    except Exception as e:
        logger.warning(f"Failed to send welcome email: {e}")

    # Schedule a non-blocking deliverability check for the email (does not block signup)
    try:
        async def _deliverability_check_runner(email_to_check, user_obj):
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, auth_service.check_email_deliverability, email_to_check)
                ok = result.get('ok')
                reason = result.get('reason')
                if not ok:
                    logger.warning(f"Email deliverability check failed for {email_to_check}: {reason}")
                    # Optionally persist this metadata to DB if available
                    try:
                        if database_service and database_service.is_connected():
                            await database_service.db.users.update_one({'email': email_to_check}, {'$set': {'email_deliverable': False, 'email_deliverable_reason': reason}})
                    except Exception:
                        pass
                else:
                    # Mark deliverable
                    try:
                        if database_service and database_service.is_connected():
                            await database_service.db.users.update_one({'email': email_to_check}, {'$set': {'email_deliverable': True}})
                    except Exception:
                        pass
            except Exception as ex:
                logger.warning(f"Deliverability check failed: {ex}")

        # Fire-and-forget the deliverability check
        asyncio.create_task(_deliverability_check_runner(normalized_email, user))
    except Exception as e:
        logger.warning(f"Failed to schedule deliverability check: {e}")

    return {"success": True, "message": "User created successfully", "user_id": user.get("id")}


@app.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    # Validate and normalize email before authenticating
    validation = auth_service.validate_email(email)
    if not validation.get("is_valid"):
        raise HTTPException(status_code=400, detail=validation.get("error") or "Invalid email")
    email = validation.get("normalized_email")

    # Debug: log whether user exists to aid troubleshooting (no password information logged)
    try:
        found_user = await auth_service.get_user_by_email(email)
        if found_user:
            logger.info(f"Login attempt for existing user: {email}")
        else:
            logger.info(f"Login attempt for unknown user: {email}")
    except Exception as e:
        logger.warning(f"Error checking user existence for login debugging: {e}")

    user = await auth_service.authenticate_user(email, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = auth_service.create_access_token({"sub": user.get("email"), "user_id": user.get("id")})
    refresh_token = auth_service.create_refresh_token({"sub": user.get("email"), "user_id": user.get("id")})

    return {
        "success": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {"id": user.get("id"), "email": user.get("email"), "first_name": user.get("first_name"), "last_name": user.get("last_name")}
    }


@app.get('/auth/login', response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse('auth/login.html', {"request": request})


@app.get('/auth/register', response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse('auth/register.html', {"request": request})


@app.post('/auth/logout')
async def logout(request: Request):
    """Logout endpoint. Accepts Authorization header or JSON body with token."""
    try:
        token = None
        auth_header = request.headers.get('authorization')
        # Log incoming headers for debugging (do not log in production)
        try:
            logger.info(f"Logout request received. headers={dict(request.headers)}")
        except Exception:
            logger.info("Logout request received (failed to stringify headers)")

        # Safely read JSON body once (if present) for debugging/use
        body = {}
        try:
            if request.headers.get('content-type', '').startswith('application/json'):
                body = await request.json()
        except Exception as e:
            logger.info(f"Failed to parse logout request JSON body: {e}")

        try:
            logger.info(f"Logout request json body: {body}")
        except Exception:
            pass

        if auth_header and auth_header.lower().startswith('bearer '):
            token = auth_header.split(None, 1)[1]
        else:
            token = body.get('token')

        payload = None
        if token:
            # Verify token first to capture payload/expiry for persistence
            try:
                payload = auth_service.verify_token(token)
            except Exception:
                payload = None

            # Revoke the token so it cannot be used again (in-memory quick path)
            try:
                revoked = auth_service.revoke_token(token)
                logger.info(f"Token revoke attempted: {revoked}")
            except Exception as e:
                logger.warning(f"Token revoke error: {e}")

            # Persist revoked token to database immediately if DB is available
            try:
                if database_service and database_service.is_connected():
                    # Determine expiry timestamp from payload if available
                    exp_ts = None
                    try:
                        exp_ts = int(payload.get('exp')) if payload and payload.get('exp') else None
                    except Exception:
                        exp_ts = None

                    try:
                        # Use the DatabaseService helper to persist revoked token
                        await database_service.add_revoked_token(token, exp_ts)
                        logger.info('Persisted revoked token to DB')
                    except Exception as db_e:
                        logger.warning(f'Failed to persist revoked token to DB: {db_e}')
            except Exception:
                pass

        # Optionally update last login/logout metadata in DB
        try:
            if payload and database_service and payload.get('user_id'):
                await database_service.update_user_last_login(payload.get('user_id'))
        except Exception:
            pass

        return {"success": True, "message": "Logged out"}
    except Exception as e:
        logger.error(f"Logout error: {e}")
        return {"success": False, "message": "Logout failed"}


@app.get('/auth/login/google')
async def auth_login_google(request: Request):
    """Start Google OAuth flow by redirecting to Google's authorization endpoint."""
    if not oauth:
        raise HTTPException(status_code=503, detail="OAuth not configured")
    redirect_uri = os.getenv('OAUTH_REDIRECT_URI', 'http://127.0.0.1:8000/auth/callback/google')
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get('/auth/callback/google', response_class=HTMLResponse)
async def auth_callback_google(request: Request):
    """Handle Google OAuth callback, create user if needed, return tokens via a small redirect page."""
    if not oauth:
        raise HTTPException(status_code=503, detail="OAuth not configured")

    try:
        token = await oauth.google.authorize_access_token(request)
        userinfo = await oauth.google.parse_id_token(request, token)
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        raise HTTPException(status_code=400, detail="OAuth failed")

    email = (userinfo.get('email') or '').lower()
    first = userinfo.get('given_name') or ''
    last = userinfo.get('family_name') or ''

    if not email:
        raise HTTPException(status_code=400, detail="Email not provided by Google")

    # Validate and normalize the email received from Google
    validation = auth_service.validate_email(email)
    if not validation.get("is_valid"):
        logger.warning(f"Google OAuth returned invalid email: {email}")
        raise HTTPException(status_code=400, detail=validation.get("error") or "Invalid email from OAuth provider")
    email = validation.get("normalized_email")

    # Find or create user
    existing = await auth_service.get_user_by_email(email)
    if not existing:
        try:
            user = await auth_service.create_user(email, first, last, os.urandom(16).hex())
            # mark email verified
            if database_service and database_service.is_connected():
                try:
                    await database_service.db.users.update_one({'email': email}, {'$set': {'email_verified': True}})
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to create OAuth user: {e}")
            raise HTTPException(status_code=500, detail="Failed to create user")
        user_obj = user
    else:
        user_obj = existing

    access_token = auth_service.create_access_token({"sub": email, "user_id": user_obj.get('id')})
    refresh_token = auth_service.create_refresh_token({"sub": email, "user_id": user_obj.get('id')})

    # Return a tiny HTML that stores tokens into localStorage and redirects to '/'
    # Safely embed tokens into JS using JSON encoding to avoid f-string brace issues
    access_js = json.dumps(access_token)
    refresh_js = json.dumps(refresh_token)
    user_js = json.dumps({
        "id": user_obj.get('id'),
        "email": user_obj.get('email'),
        "first_name": user_obj.get('first_name'),
        "last_name": user_obj.get('last_name')
    })
    html = (
        "<!doctype html>"
        "<html>"
        "  <head><meta charset=\"utf-8\"><title>Login successful</title></head>"
        "  <body>"
        "    <script>"
        f"      try {{ localStorage.setItem('access_token', {access_js}); localStorage.setItem('refresh_token', {refresh_js}); localStorage.setItem('user', {user_js}); }} catch(e){{}};"
        "      window.location.href = '/';"
        "    </script>"
        "  </body>"
        "</html>"
    )
    return HTMLResponse(html)


@app.post("/auth/migrate-session")
async def migrate_session(request: Request):
    # Authentication endpoints removed
    raise HTTPException(status_code=404, detail="Not Found")


@app.post("/api/persona/switch")
async def switch_persona(request: Request):
    """Switch the AI persona"""
    try:
        # Parse the JSON body
        body = await request.json()
        persona = body.get("persona")
        
        if not persona:
            raise HTTPException(status_code=400, detail="Persona not provided")
        
        if llm_service:
            llm_service.set_persona(persona)
            return {
                "success": True,
                "message": f"Persona switched to {persona}",
                "persona": persona
            }
        else:
            raise HTTPException(status_code=500, detail="LLM service not initialized")
    except Exception as e:
        logger.error(f"Error switching persona: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to switch persona: {str(e)}")


@app.post("/api/web-search", response_model=WebSearchResponse)
async def search_web_endpoint(request: Request):
    """Search the web using Tavily API"""
    try:
        body = await request.json()
        query = body.get("query", "")
        
        if not query.strip():
            return WebSearchResponse(
                success=False,
                query=query,
                results=[],
                error_message="Search query cannot be empty"
            )
        
        if not web_search_service or not web_search_service.is_configured():
            return WebSearchResponse(
                success=False,
                query=query,
                results=[],
                error_message="Web search service is not available. Please check Tavily API key."
            )
        
        # Perform web search
        search_results = await web_search_service.search_web(query, max_results=3)
        
        # Convert to response format
        web_results = [
            WebSearchResult(
                title=result["title"],
                snippet=result["snippet"],
                url=result["url"]
            )
            for result in search_results
        ]
        
        return WebSearchResponse(
            success=True,
            query=query,
            results=web_results
        )
        
    except Exception as e:
        logger.error(f"Web search error: {str(e)}")
        return WebSearchResponse(
            success=False,
            query=body.get("query", "") if 'body' in locals() else "",
            results=[],
            error_message=str(e)
        )


@app.post("/agent/chat/{session_id}", response_model=VoiceChatResponse)
async def chat_with_agent(
    request: Request,
    session_id: str = Path(..., description="Session ID"),
    audio: UploadFile = File(..., description="Audio file for voice input")
):
    """Chat with the voice agent using audio input"""
    transcribed_text = ""
    response_text = ""
    audio_url = None
    temp_audio_path = None
    
    try:
        # Validate services availability
        config = initialize_services()
        if not config.are_keys_valid:
            missing_keys = config.validate_keys()
            error_message = get_fallback_message(ErrorType.API_KEYS_MISSING)
            fallback_audio = await tts_service.generate_fallback_audio(error_message) if tts_service else None
            return VoiceChatResponse(
                success=False,
                message=error_message,
                transcription="",
                llm_response=error_message,
                audio_url=fallback_audio,
                session_id=session_id,
                error_type=ErrorType.API_KEYS_MISSING
            )
        
        # Determine user_id from Authorization header if present
        user_id = None
        auth_header = None
        try:
            auth_header = request.headers.get('authorization') or request.headers.get('Authorization')
        except Exception:
            auth_header = None
        if auth_header and isinstance(auth_header, str) and auth_header.lower().startswith('bearer '):
            token = auth_header.split(None, 1)[1]
            payload = auth_service.verify_token(token)
            if payload and payload.get('user_id'):
                user_id = payload.get('user_id')

        # Process audio file
        audio_content = await audio.read()
        temp_audio_path = f"temp_audio_{session_id}_{uuid.uuid4().hex}.wav"
        
        with open(temp_audio_path, "wb") as temp_file:
            temp_file.write(audio_content)
        
        # Transcribe audio
        transcribed_text = await stt_service.transcribe_audio(temp_audio_path)
        
        # Generate LLM response with chat history
        if not database_service:
            chat_history = []
            user_save_success = False
            assistant_save_success = False
        else:
            chat_history = await database_service.get_chat_history(session_id)
            
            # Save user message to chat history
            user_save_success = await database_service.add_message_to_history(session_id, "user", transcribed_text, user_id=user_id)
        
        response_text = await llm_service.generate_response(transcribed_text, chat_history)
        
        if database_service:
            # Save assistant response to chat history (include user_id if available)
            assistant_save_success = await database_service.add_message_to_history(session_id, "assistant", response_text, user_id=user_id)
        
        # Generate TTS audio
        audio_url = await tts_service.generate_audio(response_text, session_id)
        
        return VoiceChatResponse(
            success=True,
            message="Voice chat processed successfully",
            transcription=transcribed_text,
            llm_response=response_text,
            audio_url=audio_url,
            session_id=session_id
        )
        
    except Exception as e:
        logger.error(f"Error in chat_with_agent for session {session_id}: {str(e)}")
        
        # Generate appropriate error response based on the stage where error occurred
        if not transcribed_text:
            error_type = ErrorType.STT_ERROR
            error_message = get_fallback_message(ErrorType.STT_ERROR)
        elif not response_text:
            error_type = ErrorType.LLM_ERROR
            error_message = get_fallback_message(ErrorType.LLM_ERROR)
        elif not audio_url:
            error_type = ErrorType.TTS_ERROR
            error_message = get_fallback_message(ErrorType.TTS_ERROR)
        else:
            error_type = ErrorType.GENERAL_ERROR
            error_message = get_fallback_message(ErrorType.GENERAL_ERROR)
        
        fallback_audio = await tts_service.generate_fallback_audio(error_message) if tts_service else None
        
        return VoiceChatResponse(
            success=False,
            message=error_message,
            transcription=transcribed_text,
            llm_response=response_text or error_message,
            audio_url=fallback_audio,
            session_id=session_id,
            error_type=error_type
        )
    
    finally:
        # Clean up temporary file
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_audio_path}: {str(e)}")
        

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    def is_connected(self, websocket: WebSocket) -> bool:
        """Check if a WebSocket is still in active connections"""
        return websocket in self.active_connections

    async def send_personal_message(self, message: str, websocket: WebSocket):
        if self.is_connected(websocket):
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.error(f"Error sending personal message: {e}")
                self.disconnect(websocket)
        else:
            logger.debug("Attempted to send message to disconnected WebSocket")

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to WebSocket: {e}")
                self.disconnect(connection)


manager = ConnectionManager()

# Global locks to prevent concurrent LLM streaming for the same session
session_locks: Dict[str, asyncio.Lock] = {}

# Global function to handle LLM streaming (moved outside WebSocket handler to prevent duplicates)
async def handle_llm_streaming(user_message: str, session_id: str, websocket: WebSocket, web_search_enabled: bool = False, websocket_user_id: Optional[str] = None, language: str = 'auto'):
    """Handle LLM streaming response and send to Murf WebSocket for TTS"""
    
    # Prevent concurrent streaming for the same session
    if session_id not in session_locks:
        session_locks[session_id] = asyncio.Lock()
    
    async with session_locks[session_id]:
        # Initialize variables at function scope
        accumulated_response = ""
        audio_chunk_count = 0
        total_audio_size = 0
        
        try:
            # Get chat history
            try:
                if not database_service:
                    chat_history = []
                else:
                    chat_history = await database_service.get_chat_history(session_id)
                    # Save user message to chat history only if websocket_user_id is available
                    if websocket_user_id:
                        try:
                            save_success = await database_service.add_message_to_history(session_id, "user", user_message, user_id=websocket_user_id)
                        except Exception:
                            save_success = await database_service.add_message_to_history(session_id, "user", user_message)
                    else:
                        save_success = False
            except Exception as e:
                logger.error(f"Chat history error: {str(e)}")
                chat_history = []
            
            # Send LLM streaming start notification
            start_message = {
                "type": "llm_streaming_start",
                "message": "LLM is generating response...",
                "user_message": user_message,
                "web_search_enabled": web_search_enabled,
                "timestamp": datetime.now().isoformat()
            }
            await manager.send_personal_message(json.dumps(start_message), websocket)
            
            # Connect to Murf WebSocket
            try:
                await murf_websocket_service.connect()
                
                    # Create async generator for LLM streaming
                async def llm_text_stream():
                    nonlocal accumulated_response
                    
                    # Perform web search if enabled
                    web_search_results = ""
                    if web_search_enabled and web_search_service and web_search_service.is_configured():
                        try:
                            logger.info(f"🔍 Performing web search for: {user_message}")
                            search_results = await web_search_service.search_web(user_message, max_results=3)
                            web_search_results = web_search_service.format_search_results(search_results, user_message)
                            logger.info(f"✅ Web search completed with {len(search_results)} results")
                            
                            # If web search is enabled, yield the formatted search results directly as a single chunk
                            yield web_search_results
                            # Do not return here; continue to generate LLM streaming response with web search results as context
                            
                        except Exception as search_error:
                            logger.error(f"Web search failed: {search_error}")
                            web_search_results = f"Web search unavailable: {str(search_error)}"
                            yield web_search_results
                            return
                    
                    # Normal LLM streaming for non-web-search queries
                    llm_stream = llm_service.generate_streaming_response(user_message, chat_history, web_search_results if web_search_enabled else None, language=language)
                    async for chunk in llm_stream:
                        if chunk:
                            accumulated_response += chunk
                            chunk_message = {
                                "type": "llm_streaming_chunk",
                                "chunk": chunk,
                                "accumulated_length": len(accumulated_response),
                                "timestamp": datetime.now().isoformat()
                            }
                            await manager.send_personal_message(json.dumps(chunk_message), websocket)
                            yield chunk
                    
                    if not accumulated_response.strip():
                        logger.error(f"❌ Empty accumulated response for: '{user_message}'")
                        raise Exception("Empty response from LLM stream")
                
                # Send LLM stream to Murf and receive base64 audio
                tts_start_message = {
                    "type": "tts_streaming_start", 
                    "message": "Starting TTS streaming with Murf WebSocket...",
                    "timestamp": datetime.now().isoformat()
                }
                await manager.send_personal_message(json.dumps(tts_start_message), websocket)
                
                # Stream LLM text to Murf and get base64 audio back
                async for audio_response in murf_websocket_service.stream_text_to_audio(llm_text_stream()):
                    if audio_response["type"] == "audio_chunk":
                        audio_chunk_count += 1
                        total_audio_size += audio_response["chunk_size"]
                        
                        # Send audio data to client
                        audio_message = {
                            "type": "tts_audio_chunk",
                            "audio_base64": audio_response["audio_base64"],
                            "chunk_number": audio_response["chunk_number"],
                            "chunk_size": audio_response["chunk_size"],
                            "total_size": audio_response["total_size"],
                            "is_final": audio_response["is_final"],
                            "timestamp": audio_response["timestamp"]
                        }
                        await manager.send_personal_message(json.dumps(audio_message), websocket)
                        
                        # Check if this is the final chunk
                        if audio_response["is_final"]:
                            break
                    
                    elif audio_response["type"] == "status":
                        # Send status updates to client
                        status_message = {
                            "type": "tts_status",
                            "data": audio_response["data"],
                            "timestamp": audio_response["timestamp"]
                        }
                        await manager.send_personal_message(json.dumps(status_message), websocket)
                
            except Exception as e:
                logger.error(f"Error with Murf WebSocket streaming: {str(e)}")
                error_message = {
                    "type": "tts_streaming_error",
                    "message": f"Error with Murf WebSocket: {str(e)}",
                    "timestamp": datetime.now().isoformat()
                }
                await manager.send_personal_message(json.dumps(error_message), websocket)
            
            finally:
                # Disconnect from Murf WebSocket
                try:
                    await murf_websocket_service.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting from Murf WebSocket: {str(e)}")
            
            # Save to chat history for authenticated websocket users only
            try:
                if database_service and accumulated_response and websocket_user_id:
                    try:
                        save_success = await database_service.add_message_to_history(session_id, "assistant", accumulated_response, user_id=websocket_user_id)
                    except Exception:
                        save_success = await database_service.add_message_to_history(session_id, "assistant", accumulated_response)
            except Exception as e:
                logger.error(f"Failed to save assistant response to history: {str(e)}")
            
            # Send completion notification
            complete_message = {
                "type": "llm_streaming_complete",
                "message": "LLM response and TTS streaming completed",
                "complete_response": accumulated_response,
                "total_length": len(accumulated_response),
                "audio_chunks_received": audio_chunk_count,
                "total_audio_size": total_audio_size,
                "session_id": session_id,  # Include session_id in response
                "web_search_enabled": web_search_enabled,
                "timestamp": datetime.now().isoformat()
            }
            await manager.send_personal_message(json.dumps(complete_message), websocket)
            
        except Exception as e:
            logger.error(f"Error in LLM streaming: {str(e)}")
            error_message = {
                "type": "llm_streaming_error",
                "message": f"Error generating LLM response: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
            await manager.send_personal_message(json.dumps(error_message), websocket)
        
        finally:
            # Clean up session lock if no longer needed
            if session_id in session_locks:
                del session_locks[session_id]


@app.websocket("/ws/audio-stream")
async def audio_stream_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    
    # Try to get session_id from query parameters first
    query_params = dict(websocket.query_params)
    session_id = query_params.get('session_id')
    # try to extract token from query params (frontend may send token=...)
    token = query_params.get('token')
    websocket_user_id = None
    if token and isinstance(token, str):
        # token param may be either the raw JWT or the string 'Bearer <token>'
        try:
            t = token.split(None, 1)[1] if token.lower().startswith('bearer ') else token
            payload = auth_service.verify_token(t)
            if payload and payload.get('user_id'):
                websocket_user_id = payload.get('user_id')
        except Exception:
            websocket_user_id = None
    web_search_enabled = query_params.get('web_search', 'false').lower() == 'true'
    # language preference for responses: 'en', 'hi', 'both', or 'auto'
    lang_param = query_params.get('lang', 'auto').lower()
    
    if not session_id:
        session_id = str(uuid.uuid4())
    
    audio_filename = f"streamed_audio_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    audio_filepath = os.path.join("streamed_audio", audio_filename)
    os.makedirs("streamed_audio", exist_ok=True)
    is_websocket_active = True
    last_processed_transcript = ""  # Track last processed transcript to prevent duplicates
    last_processing_time = 0  # Track when we last processed a transcript
    
    async def transcription_callback(transcript_data):
        nonlocal last_processed_transcript, last_processing_time
        try:
            if is_websocket_active and manager.is_connected(websocket):
                # Only show final transcriptions and trigger LLM streaming
                if transcript_data.get("type") == "final_transcript":
                    await manager.send_personal_message(json.dumps(transcript_data), websocket)
                    final_text = transcript_data.get('text', '').strip()
                    
                    # Normalize text for comparison
                    normalized_current = final_text.lower().strip('.,!?;: ')
                    normalized_last = last_processed_transcript.lower().strip('.,!?;: ')
                    
                    # Add cooldown period (minimum 2 seconds between processing)
                    current_time = datetime.now().timestamp()
                    time_since_last = current_time - last_processing_time
                    
                    # Prevent duplicate processing
                    if (final_text and 
                        normalized_current != normalized_last and 
                        len(normalized_current) > 0 and 
                        time_since_last >= 2.0 and
                        llm_service):
                        
                        last_processed_transcript = final_text
                        last_processing_time = current_time

                        # Pass web_search_enabled, websocket_user_id and lang_param to LLM streaming
                        await handle_llm_streaming(final_text, session_id, websocket, web_search_enabled, websocket_user_id, language=lang_param)
                        
        except Exception as e:
            logger.error(f"Error sending transcription: {e}")

    # Initialize streaming readiness flag
    assemblyai_ready = False
    
    try:
        if assemblyai_streaming_service:
            assemblyai_streaming_service.set_transcription_callback(transcription_callback)
            async def safe_websocket_callback(msg):
                nonlocal assemblyai_ready
                if is_websocket_active and manager.is_connected(websocket):
                    # Check if AssemblyAI is now ready
                    if msg.get("type") == "transcription_ready":
                        assemblyai_ready = True
                        logger.info(f"✅ AssemblyAI streaming service is ready for session {session_id}")
                    elif msg.get("type") == "transcription_error":
                        assemblyai_ready = False
                        logger.error(f"❌ AssemblyAI streaming error: {msg.get('message')}")
                    return await manager.send_personal_message(json.dumps(msg), websocket)
                return None
            
            # Start the streaming service and wait for it to be ready
            stream_started = await assemblyai_streaming_service.start_streaming_transcription(
                websocket_callback=safe_websocket_callback
            )
            
            if not stream_started:
                logger.warning("Failed to start AssemblyAI streaming service")
            
        welcome_message = {
            "type": "audio_stream_ready",
            "message": "Audio streaming endpoint ready with AssemblyAI transcription. Send binary audio data.",
            "session_id": session_id,
            "audio_filename": audio_filename,
            "transcription_enabled": assemblyai_streaming_service is not None,
            "transcription_ready": assemblyai_ready,
            "web_search_enabled": web_search_enabled,
            "timestamp": datetime.now().isoformat()
        }
        await manager.send_personal_message(json.dumps(welcome_message), websocket)
        
        with open(audio_filepath, "wb") as audio_file:
            chunk_count = 0
            total_bytes = 0
            
            while True:
                try:
                    message = await websocket.receive()
                    
                    if "text" in message:
                        text_data = message["text"]
                        
                        # Try to parse as JSON first (for session_id message)
                        try:
                            command_data = json.loads(text_data)
                            if isinstance(command_data, dict):
                                if command_data.get("type") == "session_id":
                                    # Update session_id if provided from frontend
                                    new_session_id = command_data.get("session_id")
                                    if new_session_id and new_session_id != session_id:
                                        logger.info(f"Updating session_id from {session_id} to {new_session_id}")
                                        session_id = new_session_id
                                        # Update audio filename with new session ID
                                        audio_filename = f"streamed_audio_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
                                        audio_filepath = os.path.join("streamed_audio", audio_filename)
                                elif command_data.get("type") == "web_search_toggle":
                                    # Update web search setting
                                    web_search_enabled = command_data.get("enabled", False)
                                    logger.info(f"Web search {'enabled' if web_search_enabled else 'disabled'}")
                                continue
                        except json.JSONDecodeError:
                            # Not JSON, treat as regular command
                            pass
                        
                        command = text_data
                        
                        if command == "start_streaming":
                            response = {
                                "type": "command_response",
                                "message": "Ready to receive audio chunks with real-time transcription",
                                "status": "streaming_ready"
                            }
                            await manager.send_personal_message(json.dumps(response), websocket)
                            
                        elif command == "stop_streaming":
                            response = {
                                "type": "command_response",
                                "message": "Stopping audio stream",
                                "status": "streaming_stopped"
                            }
                            await manager.send_personal_message(json.dumps(response), websocket)
                            
                            if assemblyai_streaming_service:
                                async def safe_stop_callback(msg):
                                    if manager.is_connected(websocket):
                                        return await manager.send_personal_message(json.dumps(msg), websocket)
                                    return None
                            break
                    
                    elif "bytes" in message:
                        audio_chunk = message["bytes"]
                        chunk_count += 1
                        total_bytes += len(audio_chunk)
                        
                        # Write to file
                        audio_file.write(audio_chunk)
                        
                        # Send to AssemblyAI for transcription only if service is ready
                        if (assemblyai_streaming_service and 
                            is_websocket_active and 
                            assemblyai_ready and 
                            assemblyai_streaming_service.is_ready_for_audio()):
                            await assemblyai_streaming_service.send_audio_chunk(audio_chunk)
                        
                        # Send chunk confirmation to client (less frequently to reduce noise)
                        if chunk_count % 50 == 0:  # Send every 50th chunk to reduce spam
                            chunk_response = {
                                "type": "audio_chunk_received",
                                "chunk_number": chunk_count,
                                "total_bytes": total_bytes,
                                "transcription_active": assemblyai_ready and assemblyai_streaming_service.is_active() if assemblyai_streaming_service else False,
                                "timestamp": datetime.now().isoformat()
                            }
                            await manager.send_personal_message(json.dumps(chunk_response), websocket)
                
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error processing audio chunk: {e}")
                    break
        
        final_response = {
            "type": "audio_stream_complete",
            "message": f"Audio stream completed. Total chunks: {chunk_count}, Total bytes: {total_bytes}",
            "session_id": session_id,
            "audio_filename": audio_filename,
            "total_chunks": chunk_count,
            "total_bytes": total_bytes,
            "timestamp": datetime.now().isoformat()
        }
        await manager.send_personal_message(json.dumps(final_response), websocket)
        
    except WebSocketDisconnect:
        is_websocket_active = False
        manager.disconnect(websocket)
    except Exception as e:
        is_websocket_active = False
        logger.error(f"Audio streaming WebSocket error: {e}")
        manager.disconnect(websocket)
    finally:
        is_websocket_active = False
        if assemblyai_streaming_service:
            await assemblyai_streaming_service.stop_streaming_transcription()


# /auth/test endpoint removed


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)