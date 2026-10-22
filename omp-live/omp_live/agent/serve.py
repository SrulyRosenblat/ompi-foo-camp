from __future__ import annotations

from pathlib import Path

from ..httpkit import make_server
from .agent import Agent

HTML = Path(__file__).with_name("ui.html")


def server(agent: Agent, port: int):
    def state(q, b):
        return agent.state(q.get("session"))

    def chat(q, b):
        agent.chat(b["message"], b.get("session"))
        return {"ok": True}

    def reset(q, b):
        agent.reset(b.get("session"))
        return {"ok": True}

    return make_server(port, HTML, {
        ("GET", "/api/state"): state,
        ("POST", "/api/chat"): chat,
        ("POST", "/api/reset"): reset,
    }, name="agent")
