import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# Try to strip quotes if dotenv didn't
if SMTP_PASSWORD and SMTP_PASSWORD.startswith('"') and SMTP_PASSWORD.endswith('"'):
    SMTP_PASSWORD = SMTP_PASSWORD[1:-1]

print(f"Server: {SMTP_SERVER}:{SMTP_PORT}")
print(f"User: {SMTP_USER}")
print(f"Pass: {SMTP_PASSWORD}")

try:
    msg = EmailMessage()
    msg.set_content("Test email")
    msg['Subject'] = 'Test'
    msg['From'] = SMTP_USER
    msg['To'] = SMTP_USER

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASSWORD)
    server.send_message(msg)
    server.quit()
    print("Email sent successfully!")
except Exception as e:
    print(f"Failed to send email: {e}")
