import logging
import os
import aiosmtplib  
import ssl
from email.message import EmailMessage
from config import settings

# --- LOGGING SETUP ---
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

# --- CORE EMAIL SENDER ---
async def send_email_async(to_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    if not SENDER_EMAIL or not PASSWORD:
        logger.error("Email credentials missing. Skipping email send.")
        return False

    msg = EmailMessage()
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")

    msg["Subject"] = subject
    msg["To"] = to_email
    msg["From"] = SENDER_EMAIL

    try:
        # Automatically handle the correct security protocol based on the port
        if SMTP_PORT == 465:
            # Port 465 uses implicit SSL
            await aiosmtplib.send(
                msg,
                hostname=SMTP_SERVER,
                port=SMTP_PORT,
                username=SENDER_EMAIL,
                password=PASSWORD,
                use_tls=True
            )
        else:
            # Port 587 (or others) uses explicit TLS
            await aiosmtplib.send(
                msg,
                hostname=SMTP_SERVER,
                port=SMTP_PORT,
                username=SENDER_EMAIL,
                password=PASSWORD,
                start_tls=True
            )

        logger.info(f"Email sent successfully to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


# --- CITIZEN RECEIPT EMAIL ---
def get_receipt_email_html(citizen_name: str, complaint_id: int, category: str, location: str, estimated_time: str, tracking_link: str) -> str:
    """Returns a styled HTML string for the Citizen Complaint Receipt email."""
    
    greeting_name = citizen_name if citizen_name else "Citizen"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>We received your report!</title>
    </head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 0;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f7f6; padding: 40px 0;">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); overflow: hidden;">
                        
                        <tr>
                            <td style="background-color: #3b82f6; padding: 30px; text-align: center;">
                                <h1 style="color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 1px;">📋 Report Received</h1>
                            </td>
                        </tr>
                        
                        <tr>
                            <td style="padding: 40px 40px 20px 40px;">
                                <h2 style="color: #1f2937; margin-top: 0; font-size: 20px;">Hello {greeting_name},</h2>
                                <p style="color: #4b5563; font-size: 16px; line-height: 1.6;">
                                    Thank you for helping keep our city clean and safe! Our SmartCity AI has successfully processed your report and assigned it to the appropriate department.
                                </p>
                                
                                <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 25px; margin: 30px 0;">
                                    <h3 style="margin-top: 0; color: #1e293b; font-size: 16px; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; margin-bottom: 15px;">Report Details</h3>
                                    
                                    <table width="100%" style="color: #475569; font-size: 15px; line-height: 1.8;">
                                        <tr>
                                            <td width="40%"><strong>Ticket ID:</strong></td>
                                            <td width="60%">#{complaint_id}</td>
                                        </tr>
                                        <tr>
                                            <td><strong>Category:</strong></td>
                                            <td style="text-transform: capitalize;">{category}</td>
                                        </tr>
                                        <tr>
                                            <td valign="top"><strong>Location:</strong></td>
                                            <td>{location}</td>
                                        </tr>
                                        <tr>
                                            <td><strong>Target Resolution:</strong></td>
                                            <td style="color: #d97706; font-weight: bold;">{estimated_time}</td>
                                        </tr>
                                    </table>
                                </div>
                                
                                <div style="text-align: center; margin: 35px 0;">
                                    <a href="{tracking_link}" style="display: inline-block; background-color: #3b82f6; color: #ffffff; text-decoration: none; padding: 14px 30px; border-radius: 6px; font-weight: bold; font-size: 16px; box-shadow: 0 4px 6px rgba(59, 130, 246, 0.25);">
                                        Track Your Issue
                                    </a>
                                </div>
                                
                                <p style="color: #64748b; font-size: 14px; text-align: center; margin-top: 30px;">
                                    We will notify you the moment this issue is resolved.
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

async def send_citizen_receipt_email(to_email: str, citizen_name: str, complaint_id: int, category: str, location: str, estimated_time: str, tracking_link: str):
    """Assembles and sends the professional receipt email to the citizen."""
    subject = f"📋 We received your report! (Ticket #{complaint_id})"
    html_body = get_receipt_email_html(citizen_name, complaint_id, category, location, estimated_time, tracking_link)
    
    plain_body = (
        f"Hello {citizen_name or 'Citizen'},\n\n"
        f"We received your report for a {category} issue at {location}.\n\n"
        f"Ticket ID: #{complaint_id}\n"
        f"Estimated Resolution: {estimated_time}\n\n"
        f"Track your issue here: {tracking_link}\n\n"
        f"Thank you for keeping our city safe!"
    )
    
    await send_email_async(to_email, subject, html_body, plain_body)


# --- PROFESSIONAL INTERNAL ALERTS ---
def get_professional_alert_html(alert_type: str, complaint_id: int, category: str, location: str, description: str) -> str:
    """Returns a styled HTML string for Internal System Alerts."""
    
    is_escalation = "ESCALATION" in alert_type
    header_color = "#ef4444" if is_escalation else "#3b82f6"
    icon = "🚨" if is_escalation else "📋"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 40px 0;">
        <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); overflow: hidden;">
                        <tr>
                            <td style="background-color: {header_color}; padding: 20px; text-align: center;">
                                <h2 style="color: #ffffff; margin: 0; font-size: 20px; letter-spacing: 1px;">{icon} {alert_type}</h2>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 30px 40px;">
                                <p style="color: #4b5563; font-size: 16px; margin-top: 0;">Automated System Notification:</p>
                                
                                <div style="background-color: #f8fafc; border-left: 4px solid {header_color}; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                                    <table width="100%" style="color: #334155; font-size: 15px; line-height: 1.8;">
                                        <tr><td width="30%"><strong>Ticket ID:</strong></td><td>#{complaint_id}</td></tr>
                                        <tr><td><strong>Category:</strong></td><td style="text-transform: capitalize;">{category}</td></tr>
                                        <tr><td valign="top"><strong>Location:</strong></td><td>{location}</td></tr>
                                    </table>
                                </div>
                                
                                <h4 style="color: #1e293b; margin-bottom: 10px;">Issue Description:</h4>
                                <p style="color: #475569; font-size: 15px; background-color: #f1f5f9; padding: 15px; border-radius: 6px; margin-top: 0;">
                                    {description}
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <td style="background-color: #f9fafb; padding: 15px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="color: #9ca3af; font-size: 12px; margin: 0;">SmartCity Fix Internal System</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

async def send_professional_alert_email(to_email: str, alert_type: str, complaint_id: int, category: str, location: str, description: str):
    """Assembles and sends the professional internal alert email."""
    subject = f"[{alert_type}] Ticket #{complaint_id} - {category.upper()}"
    html_body = get_professional_alert_html(alert_type, complaint_id, category, location, description)
    plain_body = f"{alert_type}\nTicket #{complaint_id}\nCategory: {category}\nLocation: {location}\n\nDescription: {description}"
    
    await send_email_async(to_email, subject, html_body, plain_body)


# --- OTP EMAIL ---
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

async def send_otp_email(to_email: str, user_name: str, otp_code: str):
    """Assembles the plain text and HTML bodies and sends the OTP email."""
    subject = "Your SmartCity Fix Password Reset Code 🔐"
    html_body = get_otp_email_html(user_name=user_name, otp_code=otp_code)
    
    plain_body = (
        f"Hello {user_name},\n\n"
        f"We received a request to reset the password for your SmartCity Fix account. "
        f"Your 6-digit verification code is: {otp_code}\n\n"
        f"This code will expire in exactly 5 minutes.\n\n"
        f"If you did not request this, please contact your System Administrator immediately."
    )
    
    await send_email_async(to_email, subject, html_body, plain_body)


# --- CITIZEN RESOLUTION & REVIEW EMAIL ---
def get_resolution_email_html(citizen_name: str, complaint_id: int, category: str, location: str, original_image: str, resolved_image: str, feedback_link: str) -> str:
    """Returns a styled HTML string for notifying the citizen that their issue is closed."""
    
    greeting_name = citizen_name if citizen_name else "Citizen"
    header_color = "#10b981" # Emerald Green for success
    
    # Handle optional images dynamically
    original_photo_section = f"""
        <div style="flex: 1; min-width: 250px; margin: 10px;">
            <p style="color: #64748b; font-size: 14px; margin-bottom: 5px;">Original Issue:</p>
            <img src="{original_image}" alt="Original Issue" style="width: 100%; height: 200px; object-fit: cover; border-radius: 8px; border: 1px solid #e2e8f0;">
        </div>
    """ if original_image else ""

    resolved_photo_section = f"""
        <div style="flex: 1; min-width: 250px; margin: 10px;">
            <p style="color: #64748b; font-size: 14px; margin-bottom: 5px;">Resolution Proof:</p>
            <img src="{resolved_image}" alt="Resolution Proof" style="width: 100%; height: 200px; object-fit: cover; border-radius: 8px; border: 2px solid #10b981;">
        </div>
    """ if resolved_image else ""

    photo_gallery = f"""
        <div style="display: flex; flex-wrap: wrap; margin: 30px -10px;">
            {original_photo_section}
            {resolved_photo_section}
        </div>
    """ if original_photo_section or resolved_photo_section else ""
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Your Issue Has Been Resolved!</title>
    </head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 40px 0;">
        <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); overflow: hidden;">
                        <tr>
                            <td style="background-color: {header_color}; padding: 30px; text-align: center;">
                                <h1 style="color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 1px;">✅ Issue Resolved!</h1>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 40px;">
                                <h2 style="color: #1f2937; margin-top: 0; font-size: 20px;">Hello {greeting_name},</h2>
                                <p style="color: #4b5563; font-size: 16px; line-height: 1.6;">
                                    Great news! We are writing to let you know that your reported <strong>{category}</strong> issue at <strong>{location}</strong> (Ticket #{complaint_id}) has been officially resolved and closed by our city managers.
                                </p>
                                
                                {photo_gallery}
                                
                                <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 25px; margin: 30px 0; text-align: center;">
                                    <h3 style="margin-top: 0; color: #1e293b; font-size: 18px;">How did we do?</h3>
                                    <p style="color: #64748b; font-size: 15px; margin-bottom: 25px;">
                                        Your feedback helps us improve our public services. Please take 30 seconds to rate your experience.
                                    </p>
                                    <a href="{feedback_link}" style="display: inline-block; background-color: {header_color}; color: #ffffff; text-decoration: none; padding: 14px 30px; border-radius: 6px; font-weight: bold; font-size: 16px; box-shadow: 0 4px 6px rgba(16, 185, 129, 0.25);">
                                        ⭐ Rate Our Service
                                    </a>
                                </div>
                                
                                <p style="color: #64748b; font-size: 14px; text-align: center;">
                                    Thank you for being an active part of our SmartCity community!
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <td style="background-color: #f9fafb; padding: 20px; text-align: center; border-top: 1px solid #e5e7eb;">
                                <p style="color: #9ca3af; font-size: 13px; margin: 0;">&copy; 2026 SmartCity Fix Portal.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

async def send_resolution_email(to_email: str, citizen_name: str, complaint_id: int, category: str, location: str, original_image: str, resolved_image: str, feedback_link: str):
    """Assembles and sends the detailed resolution/review email."""
    subject = f"✅ Your SmartCity Report is Resolved! (Ticket #{complaint_id})"
    
    html_body = get_resolution_email_html(
        citizen_name, complaint_id, category, location, original_image, resolved_image, feedback_link
    )
    
    plain_body = f"Hello {citizen_name},\n\nYour {category} issue at {location} has been resolved! Please leave us a review here: {feedback_link}"
    
    await send_email_async(to_email, subject, html_body, plain_body)