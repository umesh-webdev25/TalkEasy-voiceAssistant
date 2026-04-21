import smtplib
import os
from email.message import EmailMessage
from typing import Optional
import logging

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_ADDRESS = os.getenv("SMTP_FROM", SMTP_USER)


class EmailService:
    def __init__(self):
        self.host = SMTP_HOST
        self.port = SMTP_PORT
        self.user = SMTP_USER
        self.password = SMTP_PASS

    def is_configured(self) -> bool:
        return all([self.host, self.port, self.user, self.password])

    def send_email(self, to: str, subject: str, body: str) -> bool:
        if not self.is_configured():
            logger.warning("Email service not configured. Missing SMTP credentials.")
            return False
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = FROM_ADDRESS
        msg['To'] = to
        msg.set_content(body)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(self.user, self.password)
                smtp.send_message(msg)
            logger.info(f"Email sent successfully to {to}")
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ SMTP Authentication Failed: {e}")
            logger.error("💡 For Gmail: Use App Password, not regular password!")
            logger.error("   1. Enable 2FA: https://myaccount.google.com/security")
            logger.error("   2. Generate App Password: https://myaccount.google.com/apppasswords")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"❌ SMTP Error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error sending email: {e}")
            return False
