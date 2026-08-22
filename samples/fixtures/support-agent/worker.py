"""Queue worker: pulls tickets and runs the agent."""
import json
import os

import requests

from graph.build import build

QUEUE_URL = "https://queue.acme.example/tickets"
WEBHOOK = os.getenv("COMPLETION_WEBHOOK")


def run_forever(conn_string: str):
    agent = build(conn_string)
    while True:
        ticket = requests.get(QUEUE_URL, timeout=30).json()
        result = agent.invoke({"messages": [("user", ticket["body"])]},
                              config={"configurable": {"thread_id": ticket["id"]}})
        requests.post(WEBHOOK, json={"ticket": ticket["id"], "result": str(result)}, timeout=10)
        with open("audit.log", "a") as fh:
            fh.write(json.dumps({"ticket": ticket["id"], "messages": str(result)}) + "\n")
