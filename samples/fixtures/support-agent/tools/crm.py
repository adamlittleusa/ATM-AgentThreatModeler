"""Customer record tools."""
import os

import psycopg
import requests
from langchain_core.tools import tool

SERVICE_TOKEN = os.environ["SERVICE_TOKEN"]
DB_URL = os.getenv("DATABASE_URL")
CRM_BASE = "https://crm.internal.acme.example/v2"


@tool
def lookup_customer(customer_id: str) -> dict:
    """Read a customer record by id."""
    resp = requests.get(f"{CRM_BASE}/customers/{customer_id}",
                        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}, timeout=10)
    return resp.json()


@tool
def update_customer_note(customer_id: str, note: str) -> dict:
    """Append a note to a customer record."""
    resp = requests.post(f"{CRM_BASE}/customers/{customer_id}/notes",
                         json={"body": note},
                         headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}, timeout=10)
    return resp.json()


@tool
def issue_refund(order_id: str, amount_cents: int) -> dict:
    """Issue a refund against an order."""
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO refunds (order_id, amount_cents, status) VALUES (%s, %s, 'pending')",
                (order_id, amount_cents),
            )
        conn.commit()
    return {"order_id": order_id, "amount_cents": amount_cents}
