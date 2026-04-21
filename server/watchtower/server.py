"""WatchTower MCP server.

Exposes WatchTower's unified event store to MCP-compatible clients
(Claude Desktop, Cursor, VS Code, etc.) via the Model Context Protocol.

Run locally over stdio::

    python -m watchtower.server

Claude Desktop launches this file automatically once configured.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import Config, configure_logging, load_config
from .db import ping
from .tools import (
    search_events,
    what_changed,
    suspect_rank,
    query_metrics,
    search_logs,
    correlate_signals,
    list_applicable_runbooks,
    execute_runbook_checks,
    propose_remedy,
    request_approval,
    execute_approved_remedy,
    generate_postmortem,
)

log = logging.getLogger("watchtower.server")


# Registry: tool name -> (schema dict, runner function)
TOOL_REGISTRY = {
    search_events.TOOL_NAME: (search_events.TOOL_SCHEMA, search_events.run),
    what_changed.TOOL_NAME:  (what_changed.TOOL_SCHEMA,  what_changed.run),
    suspect_rank.TOOL_NAME:  (suspect_rank.TOOL_SCHEMA,  suspect_rank.run),
    query_metrics.TOOL_NAME: (query_metrics.TOOL_SCHEMA, query_metrics.run),
    search_logs.TOOL_NAME:   (search_logs.TOOL_SCHEMA,   search_logs.run),
    correlate_signals.TOOL_NAME: (correlate_signals.TOOL_SCHEMA, correlate_signals.run),
    list_applicable_runbooks.TOOL_NAME: (list_applicable_runbooks.TOOL_SCHEMA, list_applicable_runbooks.run),
    execute_runbook_checks.TOOL_NAME:   (execute_runbook_checks.TOOL_SCHEMA,   execute_runbook_checks.run),
    propose_remedy.TOOL_NAME:           (propose_remedy.TOOL_SCHEMA,           propose_remedy.run),
    request_approval.TOOL_NAME:         (request_approval.TOOL_SCHEMA,         request_approval.run),
    execute_approved_remedy.TOOL_NAME:  (execute_approved_remedy.TOOL_SCHEMA,  execute_approved_remedy.run),
    generate_postmortem.TOOL_NAME:      (generate_postmortem.TOOL_SCHEMA,      generate_postmortem.run),
}


def build_server(cfg: Config) -> Server:
    """Construct the MCP server with tool handlers bound to this config."""
    server: Server = Server("watchtower")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**schema) for schema, _run in TOOL_REGISTRY.values()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        entry = TOOL_REGISTRY.get(name)
        if not entry:
            raise ValueError(f"Unknown tool: {name}")
        _schema, runner = entry
        result = runner(cfg, arguments or {})
        return [TextContent(type="text", text=result)]

    return server


async def run() -> None:
    cfg = load_config()
    configure_logging(cfg.log_level)

    if not ping(cfg):
        log.error("Cannot reach database. Is the Postgres container running?")
        raise SystemExit(1)

    log.info(
        "WatchTower MCP server starting (db=%s:%s/%s, tools=%s)",
        cfg.db_host, cfg.db_port, cfg.db_name,
        ", ".join(TOOL_REGISTRY.keys()),
    )
    server = build_server(cfg)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())