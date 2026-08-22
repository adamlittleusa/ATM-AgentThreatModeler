"""Agent graph."""
import os

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.prebuilt import create_react_agent
from openai import OpenAI

from tools.comms import send_customer_email, summarize_thread
from tools.crm import issue_refund, lookup_customer, update_customer_note

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

TOOLS = [lookup_customer, update_customer_note, issue_refund,
         send_customer_email, summarize_thread]


def build(conn_string: str):
    checkpointer = PostgresSaver.from_conn_string(conn_string)
    client = OpenAI(api_key=OPENAI_API_KEY)
    return create_react_agent(MODEL, TOOLS, checkpointer=checkpointer)
