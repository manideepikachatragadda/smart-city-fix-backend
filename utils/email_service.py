import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from config import settings

logger = logging.getLogger('email_service')
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

SMTP_SERVER = settings.SMTP_SERVER
SMTP_PORT = settings.SMTP_PORT
SENDER_EMAIL = settings.SENDER_EMAIL
PASSWORD = settings.SENDER_PASSWORD

def send_email_sync(to_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    if not SENDER_EMAIL or not PASSWORD:
        logger.error("Email credentials missing. Skipping email send.")
        return False

    msg = EmailMessage()
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")

    msg["Subject"] = subject
    msg["To"] = to_email
    msg["From"] = SENDER_EMAIL

    context = ssl.create_default_context()

    try:
        # Automatically handle the correct security protocol based on the port
        if SMTP_PORT == 465:
            # Port 465 uses implicit SSL
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
                server.login(SENDER_EMAIL, PASSWORD)
                server.send_message(msg)
        else:
            # Port 587 (or others) uses explicit TLS
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.ehlo()
                server.starttls(context=context) # Upgrade to secure connection
                server.ehlo()
                server.login(SENDER_EMAIL, PASSWORD)
                server.send_message(msg)

        logger.info(f"Email sent successfully to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False

def send_alert_email(to_email: str, alert_type: str, complaint_id: int, category: str, location: str, description: str):
    subject = f"[{alert_type}] Complaint #{complaint_id} - {category}"
    plain_body = (
        f"Alert Type: {alert_type}\nComplaint ID: {complaint_id}\nCategory: {category}\n"
        f"Location: {location}\nDescription: {description}\n\nPlease review immediately."
    )
    color = "#d9534f" if alert_type == "ESCALATION (SLA BREACH)" else "#f0ad4e"
    html_body = f"""
    <html><body style="font-family: Arial, sans-serif;">
      <div style="border: 1px solid #ddd; padding: 20px; border-radius: 8px;">
        <h2 style="color: {color};">{alert_type} ALERT</h2>
        <p><strong>Complaint ID:</strong> #{complaint_id}</p>
        <p><strong>Category:</strong> {category}</p>
        <p><strong>Location:</strong> {location}</p>
        <div style="background-color: #f9f9f9; padding: 15px; margin: 15px 0; border-left: 4px solid {color};">
          <p><strong>Description:</strong> {description}</p>
        </div>
      </div>
    </body></html>
    """
    send_email_sync(to_email, subject, html_body, plain_body)

def get_otp_email_html(user_name: str, otp_code: str) -> str:
    """Returns a styled HTML string for the Password Reset OTP email."""
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Password Reset OTP</title>
    </head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 0;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f7f6; padding: 40px 0;">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); overflow: hidden;">
                        
                        <tr>
                            <td style="background-color: #3b82f6; padding: 30px; text-align: center;">
                                <h1 style="color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 1px;">⚡ SmartCity Fix</h1>
                            </td>
                        </tr>
                        
                        <tr>
                            <td style="padding: 40px 40px 20px 40px;">
                                <h2 style="color: #1f2937; margin-top: 0; font-size: 20px;">Password Reset Request</h2>
                                <p style="color: #4b5563; font-size: 16px; line-height: 1.6;">
                                    Hello {user_name},<br><br>
                                    We received a request to reset the password for your SmartCity Fix account. Enter the following 6-digit verification code to proceed:
                                </p>
                                
                                <div style="text-align: center; margin: 35px 0;">
                                    <span style="display: inline-block; background-color: #f3f4f6; border: 2px dashed #9ca3af; border-radius: 8px; padding: 15px 30px; font-size: 32px; font-weight: bold; color: #1d4ed8; letter-spacing: 8px;">
                                        {otp_code}
                                    </span>
                                </div>
                                
                                <p style="color: #ef4444; font-size: 14px; text-align: center; font-weight: bold;">
                                    ⏳ This code will expire in exactly 5 minutes.
                                </p>
                                
                                <p style="color: #4b5563; font-size: 15px; line-height: 1.6; margin-top: 30px;">
                                    If you did not request this password reset, please ignore this email or contact your System Administrator immediately.
                                </p>
                            </td>
                        </tr>
                        
                        <tr>
                            <td style="background-color: #f9fafb; padding: 20px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="color: #9ca3af; font-size: 13px; margin: 0;">
                                    &copy; 2026 SmartCity Fix Portal. All rights reserved.<br>
                                    This is an automated message, please do not reply.
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

def send_otp_email(to_email: str, user_name: str, otp_code: str):
    """Assembles the plain text and HTML bodies and sends the OTP email."""
    subject = "Your SmartCity Fix Password Reset Code 🔐"
    
    # 1. Generate the beautiful HTML body
    html_body = get_otp_email_html(user_name=user_name, otp_code=otp_code)
    
    # 2. Create a clean plain-text fallback
    plain_body = (
        f"Hello {user_name},\n\n"
        f"We received a request to reset the password for your SmartCity Fix account. "
        f"Your 6-digit verification code is: {otp_code}\n\n"
        f"This code will expire in exactly 5 minutes.\n\n"
        f"If you did not request this, please contact your System Administrator immediately."
    )
    
    # 3. Dispatch via your existing sync function
    send_email_sync(to_email, subject, html_body, plain_body)