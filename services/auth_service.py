import os
import time
import uuid
import socket
from typing import Optional, Dict, Any, Tuple
from passlib.context import CryptContext
import jwt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from validate_email_address import validate_email

# Try to import dnspython resolver; if not available, continue with best-effort SMTP connect
try:
    import dns.resolver
except Exception:
    dns = None

import logging
import asyncio

logger = logging.getLogger(__name__)

try:
    import dns.resolver as _dns_resolver
    _HAS_DNS = True
except Exception:
    _dns_resolver = None
    _HAS_DNS = False

JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("JWT_SECRET_KEY", "dev-secret"))
JWT_ALGO = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MIN = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


class AuthService:
    def __init__(self, database_service=None):
        self.db = database_service
        self.pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self._store: Dict[str, Dict[str, Any]] = {}  # in-memory fallback keyed by email
        # In-memory revoked token set (JWT identifiers or raw tokens)
        # Note: for production you should persist this to a DB with expiry to avoid memory growth.
        self._revoked_tokens: set = set()
        # Cache for deliverability checks: email -> (ok: bool, timestamp: float, ttl: int, reason: Optional[str])
        self._deliverability_cache: Dict[str, Tuple[bool, float, int, Optional[str]]] = {}

    def hash_password(self, password: str) -> str:
        return self.pwd.hash(password)

    def verify_password(self, plain: str, hashed: str) -> bool:
        try:
            return self.pwd.verify(plain, hashed)
        except Exception:
            return False

    def validate_email(self, email: str) -> Dict[str, Any]:
        if not email or not email.strip():
            return {"is_valid": False, "normalized_email": None, "error": "Email is required"}
        email = email.strip().lower()
        
        # Basic format check: must contain @ and domain with proper TLD
        if "@" not in email:
            return {"is_valid": False, "normalized_email": None, "error": "Invalid email address"}
        
        local, _, domain = email.partition("@")
        
        # Check local part (before @)
        if not local or len(local) < 1:
            return {"is_valid": False, "normalized_email": None, "error": "Invalid email address"}
        
        # Check domain part (after @)
        if not domain or "." not in domain:
            return {"is_valid": False, "normalized_email": None, "error": "Invalid email address"}
        
        # Check for valid TLD (top-level domain)
        domain_parts = domain.split(".")
        if len(domain_parts) < 2 or not domain_parts[-1] or len(domain_parts[-1]) < 2:
            return {"is_valid": False, "normalized_email": None, "error": "Invalid email address"}
        
        # Check for empty parts (consecutive dots)
        if any(not part for part in domain_parts):
            return {"is_valid": False, "normalized_email": None, "error": "Invalid email address"}
        
        try:
            # Use validate_email for additional validation
            is_valid = validate_email(email)
            if not is_valid:
                return {"is_valid": False, "normalized_email": None, "error": "Invalid email address"}
            normalized = email
        except Exception as e:
            # Handle any validation errors
            return {"is_valid": False, "normalized_email": None, "error": "Invalid email address"}

        # Reject obvious dummy domains/localparts
        disposable_indicators = ["example.com", "test.com", "mailinator.com", "tempmail.com", "disposable.com", "fake.com"]
        full_email_lower = normalized.lower()
        
        # Check for common email typos and suggest corrections
        common_typos = {
            "gamil.com": "gmail.com",
            "gmial.com": "gmail.com",
            "gmai.com": "gmail.com",
            "gmailc.om": "gmail.com",
            "gmaul.com": "gmail.com",
            "gnail.com": "gmail.com",
            "yaho.com": "yahoo.com",
            "yahooo.com": "yahoo.com",
            "yhoo.com": "yahoo.com",
            "hotmial.com": "hotmail.com",
            "hotmai.com": "hotmail.com",
            "outloo.com": "outlook.com",
            "outlok.com": "outlook.com",
        }
        
        # Check if the domain has a common typo
        for typo, correct in common_typos.items():
            if domain == typo or domain.endswith(f".{typo}"):
                return {
                    "is_valid": False, 
                    "normalized_email": None, 
                    "error": f"Did you mean {local}@{correct}? Please check your email address."
                }
        
        # Check if domain ends with any disposable indicator
        for indicator in disposable_indicators:
            if domain.endswith(indicator) or domain == indicator:
                return {"is_valid": False, "normalized_email": None, "error": "Please use a real email address"}
        
        # Check if local part contains test/fake keywords
        test_keywords = ["test", "fake", "dummy", "noreply"]
        if any(keyword == local or local.startswith(f"{keyword}.") or local.startswith(f"{keyword}_") for keyword in test_keywords):
            return {"is_valid": False, "normalized_email": None, "error": "Please use a real email address"}

        return {"is_valid": True, "normalized_email": normalized, "error": None}

    def _cached_deliverability(self, email: str) -> Optional[Tuple[bool, str]]:
        """Return cached result if not expired: (ok, reason) or None."""
        rec = self._deliverability_cache.get(email)
        if not rec:
            return None
        ok, ts, ttl, reason = rec
        if time.time() - ts <= ttl:
            return (ok, reason or "cached")
        # expired
        try:
            del self._deliverability_cache[email]
        except Exception:
            pass
        return None

    def _set_deliverability_cache(self, email: str, ok: bool, ttl: int = 3600, reason: Optional[str] = None):
        self._deliverability_cache[email] = (ok, time.time(), ttl, reason)

    def check_email_deliverability(self, email: str, timeout: int = 6) -> Dict[str, Any]:
        """Best-effort deliverability check.

        Steps:
        - Check cache
        - Lookup MX records (if dnspython available)
        - Try to connect to SMTP host(s) and issue RCPT TO for the target address

        Returns: {"ok": bool, "reason": str}
        Note: This is a best-effort check — some mail servers accept any RCPT or block RCPT checks.
        """
        email = (email or "").strip().lower()
        if not email:
            return {"ok": False, "reason": "empty email"}

        cached = self._cached_deliverability(email)
        if cached is not None:
            ok, reason = cached
            return {"ok": ok, "reason": f"cached: {reason}"}

        # extract domain
        if "@" not in email:
            self._set_deliverability_cache(email, False, ttl=3600, reason="invalid format")
            return {"ok": False, "reason": "invalid email format"}

        _, domain = email.rsplit("@", 1)
        mx_hosts = []

        # 1) Try to get MX records using dnspython
        if dns is not None:
            try:
                answers = dns.resolver.resolve(domain, 'MX')
                for r in answers:
                    # r.exchange is a Name object
                    mx_hosts.append(str(r.exchange).rstrip('.'))
            except Exception:
                mx_hosts = []

        # 2) Fallback: use domain itself
        if not mx_hosts:
            mx_hosts = [domain]

        last_err = None
        for host in mx_hosts:
            try:
                # Attempt SMTP conversation
                with smtplib.SMTP(host, 25, timeout=timeout) as smtp:
                    smtp.ehlo_or_helo_if_needed()
                    # Some servers require TLS; try STARTTLS if available but don't insist
                    try:
                        code, message = smtp.mail('noreply@' + socket.gethostname())
                        # rcpt
                        code_rcpt, msg_rcpt = smtp.rcpt(email)
                        # 250 and 251 typically mean accepted
                        if code_rcpt and int(code_rcpt) in (250, 251):
                            self._set_deliverability_cache(email, True, ttl=86400, reason=f'mx:{host}')
                            return {"ok": True, "reason": f"accepted by {host}"}
                        else:
                            last_err = f"rcpt rejected {code_rcpt} {msg_rcpt} on {host}"
                            continue
                    except smtplib.SMTPRecipientsRefused as rref:
                        last_err = f"recipients refused: {rref}"
                        continue
                    except Exception as e:
                        last_err = str(e)
                        continue
            except Exception as e:
                last_err = str(e)
                continue

        # If we reach here, no host accepted RCPT
        reason = last_err or 'no mx/connection'
        # cache negative result for shorter TTL
        self._set_deliverability_cache(email, False, ttl=1800, reason=reason)
        return {"ok": False, "reason": reason}

    def check_email_reachable(self, email: str, timeout: int = 6) -> Dict[str, Any]:
        """Best-effort SMTP deliverability check.

        This attempts to connect to the domain's MX servers (if dnspython available) or
        falls back to the domain itself. It issues MAIL FROM and RCPT TO to see if the
        remote server accepts the recipient. Many providers disable RCPT checks or use
        catch-all addresses; treat those as reachable. This is a best-effort check and
        may produce false negatives for protected mail servers.
        """
        try:
            local_sender = os.getenv('SMTP_FROM', f'validator@{socket.gethostname()}')
            domain = email.split('@', 1)[1]
        except Exception:
            return {"is_reachable": False, "error": "Invalid email format"}

        hosts = []
        # Try MX lookup when possible
        if _HAS_DNS and _dns_resolver:
            try:
                answers = _dns_resolver.resolve(domain, 'MX')
                mx = sorted([(r.preference, str(r.exchange).rstrip('.')) for r in answers], key=lambda x: x[0])
                hosts = [h for _, h in mx]
            except Exception:
                hosts = []

        # Fallback hosts
        if not hosts:
            hosts = [f'mail.{domain}', domain]

        last_err = None
        for host in hosts[:3]:
            try:
                with smtplib.SMTP(host, timeout=timeout) as smtp:
                    smtp.ehlo_or_helo_if_needed()
                    # Some servers require TLS for RCPT checks; try STARTTLS if available
                    try:
                        if smtp.has_extn('starttls'):
                            smtp.starttls()
                            smtp.ehlo()
                    except Exception:
                        pass

                    # Use a harmless MAIL FROM (some servers expect a valid domain)
                    code, resp = smtp.mail(local_sender)
                    if code >= 400:
                        last_err = f"MAIL FROM rejected: {code} {resp}"
                        continue
                    code, resp = smtp.rcpt(email)
                    # 250/251 typically mean accepted
                    if 200 <= code < 300 or code == 250 or code == 251:
                        return {"is_reachable": True, "error": None}
                    else:
                        last_err = f"RCPT TO rejected ({host}): {code} {resp}"
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, socket.timeout, OSError) as e:
                last_err = f"SMTP connection failed to {host}: {e}"
                continue
            except Exception as e:
                last_err = f"SMTP check error for {host}: {e}"
                continue

        # If none succeeded, return failure with last error (or generic message)
        return {"is_reachable": False, "error": last_err or "Email deliverability could not be verified"}

    def create_access_token(self, data: Dict[str, Any], expires_minutes: Optional[int] = None) -> str:
        to_encode = data.copy()
        expire = int(time.time()) + (expires_minutes or ACCESS_TOKEN_EXPIRE_MIN) * 60
        to_encode.update({"exp": expire, "type": "access"})
        encoded = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)
        return encoded

    def create_refresh_token(self, data: Dict[str, Any]) -> str:
        to_encode = data.copy()
        expire = int(time.time()) + 60 * 60 * 24 * 30
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:

            # Quick check for revoked tokens (in-memory exact-token match)
            if token in getattr(self, '_revoked_tokens', set()):
                return None

            # If a DB is available, consult persistent revoked tokens
            try:
                if self.db and getattr(self.db, 'is_connected', lambda: False)():
                    # Use DB method if available
                    is_revoked = False
                    try:
                        # db.is_token_revoked is async; schedule a sync-to-async check
                        import asyncio
                        is_revoked = asyncio.get_event_loop().run_until_complete(self.db.is_token_revoked(token))
                    except Exception:
                        # Fallback: try calling is_token_revoked via asyncio.to_thread if event loop already running
                        try:
                            is_revoked = asyncio.get_event_loop().run_until_complete(self.db.is_token_revoked(token))
                        except Exception:
                            is_revoked = False
                    if is_revoked:
                        return None
            except Exception:
                # ignore DB errors and continue to normal verification
                pass

            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
            # Optionally check jti or token identifier if you store those instead
            jti = payload.get('jti')
            if jti and getattr(self, '_revoked_tokens', None) is not None:
                # If revoked tokens store jti strings, check membership
                if jti in self._revoked_tokens:
                    return None
            return payload
        except Exception:
            return None

    def revoke_token(self, token: str) -> bool:
        """Revoke a token so further verification fails. Returns True if stored revoked."""
        try:
            if not token:
                return False
            # Add to in-memory revocation set
            self._revoked_tokens.add(token)
            # Persist to DB if available (best-effort)
            try:
                if self.db and getattr(self.db, 'is_connected', lambda: False)():
                    # Try to persist revoked token asynchronously without blocking.
                    try:
                        # Determine token expiry from JWT if present so DB TTL can remove it later
                        try:
                            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO], options={"verify_exp": False})
                            exp = payload.get('exp')
                        except Exception:
                            exp = None

                        add_fn = getattr(self.db, 'add_revoked_token', None)
                        if callable(add_fn):
                            import asyncio
                            # Schedule background task to persist the revoked token
                            try:
                                asyncio.create_task(add_fn(token, exp))
                            except RuntimeError:
                                # If no running loop, run in a new thread
                                try:
                                    loop = asyncio.new_event_loop()
                                    loop.run_until_complete(add_fn(token, exp))
                                    loop.close()
                                except Exception:
                                    pass
                    except Exception:
                        # ignore DB persistence errors
                        pass
            except Exception:
                pass
            return True
        except Exception:
            return False

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        # Try DB first if connected, otherwise fall back to in-memory store
        try:
            if self.db and getattr(self.db, 'is_connected', lambda: False)():
                user = await self.db.get_user_by_email(email)
                if user:
                    return user
                # If DB connected but user not found, fall back to in-memory (helpful for tests)
                logger.debug(f"AuthService: user not found in DB for {email}, checking in-memory store")
            return self._store.get(email)
        except Exception as e:
            logger.warning(f"AuthService: error fetching user by email from DB: {e}. Falling back to in-memory store")
            return self._store.get(email)

    def _check_email_deliverability_blocking(self, email: str, timeout: int = 5) -> tuple:
        """Blocking checks for basic deliverability: MX lookup via dnspython if available,
        otherwise fall back to A/AAAA DNS resolution. Returns (is_reachable, error_message).
        This function is intentionally conservative and avoids SMTP probes to reduce false positives
        and avoid long-timeouts.
        """
        domain = None
        try:
            domain = email.split('@', 1)[1].lower()
        except Exception:
            return False, "Invalid email format"

        # Try dnspython MX lookup if available
        try:
            import dns.resolver  # type: ignore
            answers = dns.resolver.resolve(domain, 'MX', lifetime=timeout)
            if answers:
                return True, None
        except Exception:
            # fall through to A/AAAA lookup
            pass

        # Fallback: check A/AAAA records via socket (fast)
        try:
            # Limit DNS resolution time by running in thread with socket timeout not available here
            socket.getaddrinfo(domain, None)
            return True, None
        except Exception as e:
            return False, str(e)

    async def check_email_deliverability(self, email: str, user_id: Optional[str] = None) -> bool:
        """Async wrapper that runs the blocking deliverability check in a thread and updates
        the database or in-memory store with the result. Cached results are used when possible.
        """
        if not email:
            return False

        # Use cached result when available
        cached = self._deliverability_cache.get(email)
        if cached is not None:
            # Update db/store with cached result if user_id provided
            try:
                if user_id and self.db and getattr(self.db, 'is_connected', lambda: False)():
                    await self.db.db.users.update_one({'email': email}, {'$set': {'email_reachable': bool(cached)}})
                elif email in self._store:
                    self._store[email]['email_reachable'] = bool(cached)
            except Exception:
                pass
            return bool(cached)

        # Run the blocking checker in a thread
        try:
            reachable, err = await asyncio.to_thread(self._check_email_deliverability_blocking, email)
            # cache the result
            self._deliverability_cache[email] = bool(reachable)

            # Persist the reachability to DB or in-memory store
            try:
                if user_id and self.db and getattr(self.db, 'is_connected', lambda: False)():
                    await self.db.db.users.update_one({'email': email}, {'$set': {'email_reachable': bool(reachable)}})
                elif email in self._store:
                    self._store[email]['email_reachable'] = bool(reachable)
            except Exception:
                pass

            return bool(reachable)
        except Exception:
            return False

    async def create_user(self, email: str, first_name: str, last_name: str, password: str) -> Dict[str, Any]:
        # Validate email format first
        validation_result = self.validate_email(email)
        if not validation_result["is_valid"]:
            raise ValueError(validation_result["error"] or "Invalid email address")
        
        # Use the normalized email from validation
        email = validation_result["normalized_email"]
        
        # Check if email already exists
        existing = await self.get_user_by_email(email)
        if existing:
            raise ValueError("Email already exists")

        user = {
            "id": str(uuid.uuid4()),
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "password_hash": self.hash_password(password),
            "is_active": True,
            "email_verified": False,
            "created_at": int(time.time())
        }
        if self.db and getattr(self.db, 'is_connected', lambda: False)():
            try:
                ok = await self.db.create_user(user)
                if not ok:
                    # Log and fall back to in-memory store instead of failing registration
                    logger.warning(f"DB create_user returned False for {email} - falling back to in-memory store")
                    self._store[email] = user
            except Exception as e:
                # On unexpected DB errors, log and fallback to in-memory store
                logger.warning(f"Exception while persisting user to DB for {email}: {e} - falling back to in-memory store")
                self._store[email] = user
        else:
            self._store[email] = user
        
    

        # Sender and receiver info
        # sender_email = "umeshgayakwad100@gmail.com"
        # receiver_email = email
        # smtp_password = "afmtnmkjjqzlqbub"  # Use App Password, not your Gmail password
        sender_email = "talkeasyofficial100@gmail.com"
        receiver_email = email
        smtp_password = "bnlrgxnrdmpxnidk"  # Use App Password, not your Gmail password

        # Create the email with HTML content
        msg = MIMEMultipart("alternative")
        msg["From"] = f"TalkEasy <{sender_email}>"
        msg["To"] = receiver_email
        msg["Subject"] = "🎉 Welcome to TalkEasy - Your Voice Assistant is Ready!"

        # Plain text version (fallback)
        text_body = f"""
Hello {first_name} {last_name}!

Welcome to TalkEasy - Your AI-Powered Voice Assistant

Your account has been successfully created and is ready to use!

What you can do with TalkEasy:
✓ Real-time voice conversations with AI
✓ Stream audio responses instantly
✓ Get help with tasks using natural voice commands
✓ Seamless multi-turn conversations

Get started now at: https://talkeasy.app

Need help? Reply to this email or visit our support center.

Best regards,
The TalkEasy Team

---
This is an automated message. Please do not reply directly to this email.
        """

        # Beautiful HTML version
        html_body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to TalkEasy</title>
</head>
<body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh;">
    <table role="presentation" style="width: 100%; border-collapse: collapse; background: transparent;">
        <tr>
            <td style="padding: 40px 20px;">
                <!-- Main Container -->
                <table role="presentation" style="max-width: 600px; margin: 0 auto; background: rgba(255, 255, 255, 0.98); border-radius: 20px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.3); overflow: hidden;">
                    
                    <!-- Header with Gradient -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px 30px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 36px; font-weight: bold; text-shadow: 2px 2px 4px rgba(0,0,0,0.2);">
                                🎙️ TalkEasy
                            </h1>
                            <p style="margin: 10px 0 0 0; color: rgba(255, 255, 255, 0.95); font-size: 16px; letter-spacing: 1px;">
                                Your AI-Powered Voice Assistant
                            </p>
                        </td>
                    </tr>

                    <!-- Welcome Message -->
                    <tr>
                        <td style="padding: 40px 30px; background: #ffffff;">
                            <div style="text-align: center; margin-bottom: 30px;">
                                <div style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 15px 30px; border-radius: 50px; box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);">
                                    <span style="color: #ffffff; font-size: 18px; font-weight: bold;">🎉 Account Created Successfully!</span>
                                </div>
                            </div>
                            
                            <h2 style="color: #2d3748; font-size: 24px; margin: 0 0 20px 0; text-align: center;">
                                Hello, {first_name} {last_name}!
                            </h2>
                            
                            <p style="color: #4a5568; font-size: 16px; line-height: 1.8; margin: 0 0 25px 0; text-align: center;">
                                Welcome to <strong style="color: #667eea;">TalkEasy</strong>! Your account is now active and ready to revolutionize how you interact with AI through voice.
                            </p>

                            <!-- Features Section -->
                            <div style="background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%); border-radius: 15px; padding: 25px; margin: 30px 0; border-left: 4px solid #667eea;">
                                <h3 style="color: #2d3748; font-size: 18px; margin: 0 0 20px 0; display: flex; align-items: center;">
                                    <span style="margin-right: 10px;">✨</span> What You Can Do:
                                </h3>
                                
                                <table role="presentation" style="width: 100%;">
                                    <tr>
                                        <td style="padding: 10px 0;">
                                            <div style="display: flex; align-items: start;">
                                                <span style="color: #667eea; font-size: 20px; margin-right: 15px;">🎤</span>
                                                <div>
                                                    <strong style="color: #2d3748; font-size: 15px;">Real-Time Voice Conversations</strong>
                                                    <p style="color: #718096; font-size: 14px; margin: 5px 0 0 0; line-height: 1.6;">
                                                        Engage in natural, flowing conversations with our advanced AI
                                                    </p>
                                                </div>
                                            </div>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0;">
                                            <div style="display: flex; align-items: start;">
                                                <span style="color: #667eea; font-size: 20px; margin-right: 15px;">⚡</span>
                                                <div>
                                                    <strong style="color: #2d3748; font-size: 15px;">Instant Audio Streaming</strong>
                                                    <p style="color: #718096; font-size: 14px; margin: 5px 0 0 0; line-height: 1.6;">
                                                        Get lightning-fast responses streamed directly to you
                                                    </p>
                                                </div>
                                            </div>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0;">
                                            <div style="display: flex; align-items: start;">
                                                <span style="color: #667eea; font-size: 20px; margin-right: 15px;">🤖</span>
                                                <div>
                                                    <strong style="color: #2d3748; font-size: 15px;">Smart Task Assistance</strong>
                                                    <p style="color: #718096; font-size: 14px; margin: 5px 0 0 0; line-height: 1.6;">
                                                        Use natural voice commands to get things done effortlessly
                                                    </p>
                                                </div>
                                            </div>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0;">
                                            <div style="display: flex; align-items: start;">
                                                <span style="color: #667eea; font-size: 20px; margin-right: 15px;">💬</span>
                                                <div>
                                                    <strong style="color: #2d3748; font-size: 15px;">Context-Aware Conversations</strong>
                                                    <p style="color: #718096; font-size: 14px; margin: 5px 0 0 0; line-height: 1.6;">
                                                        Enjoy seamless multi-turn conversations that remember context
                                                    </p>
                                                </div>
                                            </div>
                                        </td>
                                    </tr>
                                </table>
                            </div>

                            <!-- Call to Action Button -->
                            <div style="text-align: center; margin: 35px 0 25px 0;">
                                <a href="https://talkeasy.app" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #ffffff; text-decoration: none; padding: 16px 40px; border-radius: 50px; font-size: 16px; font-weight: bold; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4); transition: transform 0.3s ease; text-transform: uppercase; letter-spacing: 1px;">
                                    🚀 Start Using TalkEasy
                                </a>
                            </div>

                            <!-- Quick Stats -->
                            <div style="background: #f7fafc; border-radius: 12px; padding: 20px; margin: 25px 0; text-align: center;">
                                <p style="color: #4a5568; font-size: 14px; margin: 0; line-height: 1.8;">
                                    <strong style="color: #667eea;">Pro Tip:</strong> Enable your microphone for the best experience. TalkEasy works best with Chrome, Firefox, or Edge browsers.
                                </p>
                            </div>
                        </td>
                    </tr>

                    <!-- Support Section -->
                    <tr>
                        <td style="background: #f7fafc; padding: 30px; text-align: center; border-top: 1px solid #e2e8f0;">
                            <h3 style="color: #2d3748; font-size: 16px; margin: 0 0 15px 0;">
                                Need Help Getting Started?
                            </h3>
                            <p style="color: #718096; font-size: 14px; margin: 0 0 20px 0; line-height: 1.6;">
                                Our support team is here to help you make the most of TalkEasy
                            </p>
                            <div style="margin-top: 15px;">
                                <a href="mailto:support@talkeasy.app" style="color: #667eea; text-decoration: none; font-size: 14px; font-weight: 600; margin: 0 15px;">
                                    📧 Email Support
                                </a>
                                <span style="color: #cbd5e0;">|</span>
                                <a href="https://talkeasy.app/docs" style="color: #667eea; text-decoration: none; font-size: 14px; font-weight: 600; margin: 0 15px;">
                                    📚 Documentation
                                </a>
                                <span style="color: #cbd5e0;">|</span>
                                <a href="https://talkeasy.app/faq" style="color: #667eea; text-decoration: none; font-size: 14px; font-weight: 600; margin: 0 15px;">
                                    ❓ FAQ
                                </a>
            </div>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 25px 30px; text-align: center;">
                            <p style="margin: 0 0 10px 0; color: rgba(255, 255, 255, 0.95); font-size: 14px; line-height: 1.6;">
                                <strong>TalkEasy</strong> - Empowering Communication Through Voice AI
                            </p>
                            <p style="margin: 0 0 15px 0; color: rgba(255, 255, 255, 0.8); font-size: 12px; line-height: 1.5;">
                                © 2025 TalkEasy. All rights reserved.
                            </p>
                            <div style="margin-top: 15px;">
                                <a href="https://twitter.com/talkeasy" style="text-decoration: none; color: #ffffff; margin: 0 8px; font-size: 20px;">🐦</a>
                                <a href="https://facebook.com/talkeasy" style="text-decoration: none; color: #ffffff; margin: 0 8px; font-size: 20px;">📘</a>
                                <a href="https://linkedin.com/company/talkeasy" style="text-decoration: none; color: #ffffff; margin: 0 8px; font-size: 20px;">💼</a>
                                <a href="https://instagram.com/talkeasy" style="text-decoration: none; color: #ffffff; margin: 0 8px; font-size: 20px;">📸</a>
                            </div>
                            <p style="margin: 15px 0 0 0; color: rgba(255, 255, 255, 0.7); font-size: 11px;">
                                You're receiving this because you created a TalkEasy account.<br>
                                <a href="https://talkeasy.app/unsubscribe" style="color: rgba(255, 255, 255, 0.9); text-decoration: underline;">Unsubscribe</a> | 
                                <a href="https://talkeasy.app/privacy" style="color: rgba(255, 255, 255, 0.9); text-decoration: underline;">Privacy Policy</a>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        # Attach both plain text and HTML versions
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # Connect to Gmail SMTP server and send email
        server = None
        try:
            server = smtplib.SMTP("smtp.gmail.com", 587)  # 587 = TLS
            server.starttls()  # Secure connection
            server.login(sender_email, smtp_password)
            server.send_message(msg)
            logger.info(f"✅ Welcome email sent successfully to {receiver_email}")
        except Exception as e:
            logger.error(f"❌ Error sending welcome email: {e}")
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass

        return user

    async def authenticate_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        user = await self.get_user_by_email(email)
        if not user:
            logger.info(f"authenticate_user: no user record found for email={email}")
            return None

        stored = user.get('password_hash') or user.get('password')
        if not stored:
            logger.info(f"authenticate_user: user found but no password hash stored for email={email}")
            return None

        try:
            if self.verify_password(password, stored):
                logger.info(f"authenticate_user: successful login for email={email}")
                return user
            else:
                logger.info(f"authenticate_user: password mismatch for email={email}")
                return None
        except Exception as e:
            logger.error(f"authenticate_user: error verifying password for email={email}: {e}")
            return None


# global instance placeholder; main.initialize_services will replace if needed
auth_service = AuthService()