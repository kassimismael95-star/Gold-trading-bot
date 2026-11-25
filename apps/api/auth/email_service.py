"""Configurable SMTP email delivery. Never logs OTP or reset tokens."""
import os, smtplib
from email.message import EmailMessage
from flask import current_app

def send_email(to, subject, text_body):
    sender = current_app.extensions.get("email_sender")
    if callable(sender):
        return sender(to=to, subject=subject, text_body=text_body)
    host = os.getenv("SMTP_HOST", "")
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("EMAIL_FROM", username)
    if not host or not from_addr:
        raise RuntimeError("smtp_not_configured")
    port = int(os.getenv("SMTP_PORT", "587"))
    msg = EmailMessage()
    msg["From"] = from_addr; msg["To"] = to; msg["Subject"] = subject
    msg.set_content(text_body)
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True
