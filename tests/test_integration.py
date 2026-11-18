"""Starts the real MCP server and Local Guide agent as processes and talks to them over HTTP.

No LLM calls: checks the wiring (MCP over streamable HTTP, A2A agent card, health routes).
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/trip_buddy"))
from agent import result_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(script: str, port: int, extra_env: dict | None = None) -> subprocess.Popen:
    env = {**os.environ, "PORT": str(port), "HOST": "127.0.0.1", "DESTINATIONS_TABLE": "",
           "PYTHONPATH": str(ROOT / "shared"), **(extra_env or {})}
    proc = subprocess.Popen([sys.executable, script], cwd=Path(script).parent, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.3)
    proc.kill()
    raise RuntimeError(f"{script} did not start:\n{proc.stdout.read().decode(errors='replace')}")


@pytest.fixture(scope="module")
def mcp_port():
    port = free_port()
    proc = start(str(ROOT / "services/mcp_server/server.py"), port)
    yield port
    proc.kill()


@pytest.fixture(scope="module")
def guide_port():
    port = free_port()
    # LLM_PROVIDER=openai with a dummy key: the model is only built on first question, never here.
    proc = start(str(ROOT / "services/guide_agent/agent.py"), port,
                 {"GUIDE_PUBLIC_URL": f"http://127.0.0.1:{port}", "LLM_PROVIDER": "openai",
                  "OPENAI_API_KEY": "test-not-used"})
    yield port
    proc.kill()


def test_mcp_tools_resources_and_cost(mcp_port):
    async def go():
        async with streamable_http_client(f"http://127.0.0.1:{mcp_port}/mcp") as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert names == {"db_lookup", "list_destinations", "compute_trip_cost"}
                places = json.loads((await s.read_resource("trips://destinations")).contents[0].text)
                assert len(places) == 10
                goa = json.loads(result_text(await s.call_tool("db_lookup", {"place": "goa"})))
                cost = json.loads(result_text(await s.call_tool("compute_trip_cost", {
                    "travel_cost_per_person": goa["travel_cost_per_person"],
                    "room_price_per_night": goa["room_price_per_night"],
                    "daily_spend_per_person": goa["daily_spend_per_person"],
                    "people": 4, "nights": 3, "budget_per_person": 12000})))
                assert cost["total_per_person"] == 11800
                bad = await s.call_tool("compute_trip_cost", {
                    "travel_cost_per_person": 1, "room_price_per_night": 1,
                    "daily_spend_per_person": 1, "people": 99, "nights": 1})
                assert bad.isError   # pydantic bounds enforced by the server, not trusted to the LLM
    asyncio.run(go())


def test_guide_agent_card(guide_port):
    card = httpx.get(f"http://127.0.0.1:{guide_port}/.well-known/agent-card.json").json()
    assert card["name"] == "Local Guide Agent"
    assert card["skills"][0]["id"] == "local_tips"


class ScriptedLLM:
    """Stands in for Bedrock/OpenAI: replays tool calls, then writes a final answer from the tool results."""

    def __init__(self):
        self.turn = 0

    def bind_tools(self, tools):
        self.tool_names = {t["function"]["name"] for t in tools}
        return self

    async def ainvoke(self, messages):
        from langchain_core.messages import AIMessage
        self.turn += 1
        if self.turn == 1:
            return AIMessage(content="", tool_calls=[{"id": "1", "name": "db_lookup", "args": {"place": "Goa"}}])
        if self.turn == 2:
            goa = json.loads(messages[-1].content)
            return AIMessage(content="", tool_calls=[
                {"id": "2", "name": "compute_trip_cost", "args": {
                    "travel_cost_per_person": goa["travel_cost_per_person"],
                    "room_price_per_night": goa["room_price_per_night"],
                    "daily_spend_per_person": goa["daily_spend_per_person"],
                    "people": 4, "nights": 3, "budget_per_person": 12000}},
                {"id": "3", "name": "ask_local_guide", "args": {"place": "Goa", "month": "December"}},
                {"id": "4", "name": "delete_everything", "args": {}}])
        cost = json.loads(messages[-3].content)
        return AIMessage(content=f"Total per person: {cost['total_per_person']}. Guide said: {messages[-2].content}")


def test_react_loop_over_mcp_and_a2a(mcp_port, monkeypatch):
    from test_unit import KeywordEmbeddings

    import agent
    from rag import TravelNotebook

    monkeypatch.setattr(agent, "MCP_URL", f"http://127.0.0.1:{mcp_port}/mcp")
    monkeypatch.setattr(agent, "GUIDE_URL", f"http://127.0.0.1:{free_port()}")   # nothing listening
    monkeypatch.setattr(agent, "get_chat_model", lambda: ScriptedLLM())

    result = asyncio.run(agent.run_agent(TravelNotebook(KeywordEmbeddings()), "Goa for 4 friends?", []))
    assert "11800" in result.reply
    assert "offline" in result.reply                               # graceful A2A failure
    assert [(s["tool"], s["via"]) for s in result.steps] == [
        ("db_lookup", "mcp"), ("compute_trip_cost", "mcp"),
        ("ask_local_guide", "a2a"), ("delete_everything", "blocked")]   # unknown tool refused
    assert len(result.rag_hits) == 3
