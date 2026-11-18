"""Local Guide agent: a separate A2A service that Trip Buddy asks about things to do, food and weather.

Runs as its own ECS service, reachable inside the VPC at http://guide.<namespace>.local:9999
    Agent card:  GET  /.well-known/agent-card.json
    Messages:    POST /            (A2A JSON-RPC)
    Health:      GET  /health
"""

from __future__ import annotations

import os

import uvicorn
from a2a.helpers import get_message_text, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Role
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from tripbuddy_shared.llm import get_chat_model, model_name
from tripbuddy_shared.logs import get_logger, log_event

log = get_logger("guide_agent")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9999"))
# The URL other agents should use, as published in the agent card (Cloud Map DNS name on AWS).
PUBLIC_URL = os.getenv("GUIDE_PUBLIC_URL", f"http://127.0.0.1:{PORT}")

agent_card = AgentCard(
    name="Local Guide Agent",
    description="Knows what to do, what to eat and what weather to expect at popular trips from Bengaluru.",
    version="1.0.0",
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=False),
    supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=PUBLIC_URL, protocol_version="1.0")],
    skills=[AgentSkill(
        id="local_tips",
        name="Local tips",
        description="Things to do, local food and weather warnings for an Indian destination in a given month.",
        tags=["travel", "local guide"],
        examples=["What should we do in Hampi in December?"],
    )],
)

LOCAL_NOTES = {
    "goa": "Do: Fort Aguada at sunset, Fontainhas walk in Panaji, Dudhsagar falls. Eat: fish thali, bebinca (veg: mushroom xacuti).",
    "gokarna": "Do: Om Beach, the cliff trek from Kudle to Half Moon Beach, Mahabaleshwar temple. Eat: Udupi thali, neer dosa.",
    "pondicherry": "Do: White Town walk, Auroville, Paradise Beach. Eat: French bakery croissants, Creole curry.",
    "coorg": "Do: Abbey Falls, a coffee plantation tour, Raja's Seat at sunset. Eat: akki roti, bamboo shoot curry.",
    "ooty": "Do: toy train to Coonoor, Botanical Garden, Doddabetta Peak. Eat: homemade chocolates, varkey biscuits.",
    "manali": "Do: Solang Valley, Old Manali cafes, Hadimba Temple. Eat: siddu, rajma chawal.",
    "hampi": "Do: Virupaksha Temple, sunrise at Matanga Hill, coracle ride on the Tungabhadra. Eat: thali meals, banana pancakes.",
    "jaipur": "Do: Amber Fort, Hawa Mahal, Nahargarh at sunset. Eat: dal baati churma, pyaaz kachori.",
    "rishikesh": "Do: river rafting (Oct-Jun), Ganga aarti at Triveni Ghat, Laxman Jhula. Eat: Chotiwala thali, cafe pancakes.",
    "dandeli": "Do: white-water rafting on the Kali (Oct-May), Syntheri Rocks, jungle safari. Eat: Malnad meals, kokum juice.",
}


def find_notes(question: str) -> str:
    q = question.lower()
    return next((notes for place, notes in LOCAL_NOTES.items() if place in q), "No notes for this place.")


async def guide_brain(question: str) -> str:
    notes = find_notes(question)
    reply = await get_chat_model().ainvoke([
        ("system", "You are a friendly local guide for Indian destinations. Using the notes, give 3 things to do, "
                   "1 local food to try, and 1 weather warning for the month asked. Under 80 words.\n"
                   f"Notes: {notes}"),
        ("human", question),
    ])
    return reply.text


class GuideExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        question = get_message_text(context.message)
        log_event(log, "a2a_request", question=question[:200])
        answer = await guide_brain(question)
        await event_queue.enqueue_event(new_text_message(answer, role=Role.ROLE_AGENT))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel is not supported.")


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "model": model_name()})


handler = DefaultRequestHandler(agent_executor=GuideExecutor(), task_store=InMemoryTaskStore(), agent_card=agent_card)
app = Starlette(routes=[Route("/health", health)]
                + create_agent_card_routes(agent_card)
                + create_jsonrpc_routes(handler, "/"))

if __name__ == "__main__":
    log_event(log, "starting", port=PORT, public_url=PUBLIC_URL, model=model_name())
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
