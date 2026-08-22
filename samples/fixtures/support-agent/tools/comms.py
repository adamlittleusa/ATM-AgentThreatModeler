"""Outbound customer communication."""
import os

from langchain_core.tools import tool
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

SENDGRID_KEY = os.getenv("SENDGRID_API_KEY")


@tool
def send_customer_email(to_address: str, subject: str, body: str) -> str:
    """Send an email to a customer."""
    message = Mail(from_email="support@acme.example", to_emails=to_address,
                   subject=subject, html_content=body)
    client = SendGridAPIClient(SENDGRID_KEY)
    response = client.send(message)
    return f"sent:{response.status_code}"


@tool
def summarize_thread(thread_text: str) -> str:
    """Summarize a support thread."""
    return thread_text[:500]
