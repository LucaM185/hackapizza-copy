"""Agent factory — builds all 6 agents with role-restricted tool subsets.

All agents use the same model (gpt-oss-20b).
"""
from __future__ import annotations

import logging

from datapizza.agents import Agent
from datapizza.clients.openai_like import OpenAILikeClient
from datapizza.tools.mcp_client import MCPClient
from datapizza.tools.web_fetch import WebFetchTool

from src.config import (
    REGOLO_API_KEY,
    REGOLO_BASE_URL,
    MCP_URL,
    HEADERS,
)

logger = logging.getLogger(__name__)

# ── Model config ─────────────────────────────────────────────
FAST_MODEL = "gpt-oss-120b"

# ── Tool name sets per agent ─────────────────────────────────
SPEAKING_TOOLS = {"send_message", "save_menu", "update_restaurant_is_open"}
BIDDING_TOOLS  = {"closed_bid"}
MARKET_TOOLS   = {"create_market_entry", "execute_transaction", "delete_market_entry"}
PREPARE_TOOLS  = {"prepare_dish"}
SERVE_TOOLS    = {"serve_dish"}
OPENER_TOOLS   = {"update_restaurant_is_open"}



# ── Helpers ──────────────────────────────────────────────────
def _build_client(model: str) -> OpenAILikeClient:
    """Create an OpenAI-compatible LLM client for a specific model."""
    return OpenAILikeClient(
        api_key=REGOLO_API_KEY,
        model=model,
        base_url=REGOLO_BASE_URL,
    )


def _load_mcp_tools() -> list:
    """Fetch all MCP tools from the game server."""
    logger.info("Fetching MCP tools from %s …", MCP_URL)
    mcp = MCPClient(url=MCP_URL, headers=HEADERS)
    tools = mcp.list_tools()
    logger.info("Loaded %d MCP tools: %s", len(tools), [t.name for t in tools])
    return tools


def _filter_tools(all_tools: list, allowed_names: set) -> list:
    """Return only the tools whose name is in *allowed_names*."""
    filtered = [t for t in all_tools if t.name in allowed_names]
    logger.debug("Filtered tools: %s", [t.name for t in filtered])
    return filtered


"""Build and return all 6 agents with role-restricted tool access."""
all_tools = _load_mcp_tools()

client = _build_client(FAST_MODEL)

opener = Agent(
    name="Opener",
    client=client,
    system_prompt="Esegui 'update_restaurant_is_open(is_open=true)'",
    tools=_filter_tools(all_tools, OPENER_TOOLS),
    max_steps=2,
    planning_interval=0,
)

bidder = Agent(
    name="Bidder",
    client=client,
    system_prompt="Esegui 'closed_bid'",
    tools=_filter_tools(all_tools, BIDDING_TOOLS),
    max_steps=2,
    planning_interval=0,
)

menu = Agent(
    name="Menu",
    client=client,
    system_prompt="Esegui 'save_menu', come prezzi stai attorno ai 300-500 per piatto",
    tools=_filter_tools(all_tools, SPEAKING_TOOLS),
    max_steps=2,
    planning_interval=0,
)

prepara = Agent(
    name="Prepara",
    client=client,
    system_prompt="Esegui 'prepare_dish' con il nome esatto del piatto che ti viene dato. Non modificare il nome.",
    tools=_filter_tools(all_tools, PREPARE_TOOLS),
    max_steps=2,
    planning_interval=0,
)

servi = Agent(
    name="Servi",
    client=client,
    system_prompt="Esegui 'serve_dish' con il nome esatto del piatto e il client_id che ti vengono dati. Non modificare i parametri. Non chiamare altri tool.",
    tools=_filter_tools(all_tools, SERVE_TOOLS),
    max_steps=2,
    planning_interval=0,
)

notizie = Agent(
    name="web_researcher",
    client=_build_client(FAST_MODEL),
    system_prompt=(
        "You are a research assistant. Use the web_fetch tool to fetch web pages "
        "and extract information from them. When given a URL, fetch it first, "
        "then analyze the content."
    ),
    tools=[WebFetchTool(timeout=15.0)],
    max_steps=3,
    planning_interval=0,
)

strategia = Agent(
    name="Strategia",
    client=client,
    system_prompt=(
        "Sei un analista strategico per un ristorante in un gioco. "
        "Ti viene dato il testo di notizie/eventi del gioco. "
        "Rispondi con UNA SOLA PAROLA che indica la strategia migliore:\n"
        "- 'prestigio' se i clienti premiano piatti prestigiosi o di lusso\n"
        "- 'velocità' se i clienti premiano piatti veloci o c'e' fretta\n"
        "- 'prezzo' se i clienti badano al prezzo o le risorse sono scarse\n"
        "Rispondi SOLO con una di queste tre parole, niente altro."
    ),
    tools=[],
    max_steps=1,
    planning_interval=0,
)