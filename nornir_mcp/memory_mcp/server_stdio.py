#!/usr/bin/env python3

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from backends import FileMemoryBackend
from inventory import InventoryResolver
from models import (
    GetMemoryEpisodeRequest,
    ListMemoryEpisodesRequest,
    SaveEpisodeRequest,
    SearchDeviceQuirksRequest,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("memory_mcp")

mcp = FastMCP("memory-mcp")


def _build_backend() -> FileMemoryBackend:
    backend_name = os.getenv("MEMORY_MCP_BACKEND", "file").strip().lower()
    if backend_name != "file":
        raise RuntimeError(
            "Unsupported MEMORY_MCP_BACKEND. This implementation ships a stable file backend. "
            "Keep the wrapper contract and swap the backend later if Graphiti is introduced."
        )

    store_path = Path(
        os.getenv(
            "MEMORY_MCP_STORE_PATH",
            str(Path(__file__).resolve().parent / "data" / "episodes.json"),
        )
    )
    inventory = InventoryResolver()
    logger.info("[Setup] memory-mcp using file backend at %s", store_path)
    return FileMemoryBackend(store_path=store_path, inventory=inventory)


backend = _build_backend()


@mcp.tool()
async def search_device_quirks(data: SearchDeviceQuirksRequest):
    """
    Search compact persistent operational memory before a mutating change.
    Use canonical Nornir device_name values and prefer one call per phase, not one call per device.
    """
    logger.info(
        "[Tool] search_device_quirks devices=%s phase=%s intent_class=%s operation_type=%s",
        data.device_names,
        data.phase,
        data.intent_class,
        data.operation_type,
    )
    return backend.search_device_quirks(data)


@mcp.tool()
async def save_episode(data: SaveEpisodeRequest):
    """
    Persist a validated operational lesson only after explicit user approval.
    Do not store secrets, raw configs, or long command outputs.
    """
    logger.info(
        "[Tool] save_episode target=%s operation=%s scope=%s",
        data.episode.device_target,
        data.episode.operation_executed,
        data.episode.scope,
    )
    return backend.save_episode(data)


@mcp.tool()
async def list_memory_episodes(data: ListMemoryEpisodesRequest):
    """
    List compact memory episodes for audit and troubleshooting.
    This is read-only and should be used to inspect what the memory server learned.
    """
    logger.info(
        "[Tool] list_memory_episodes device=%s phase=%s intent_class=%s operation_type=%s",
        data.device_name or data.device_names,
        data.phase,
        data.intent_class,
        data.operation_type,
    )
    return backend.list_memory_episodes(data)


@mcp.tool()
async def get_memory_episode(data: GetMemoryEpisodeRequest):
    """
    Fetch one redacted memory episode by id after search/list returned it.
    This supports progressive retrieval without bloating normal workflow context.
    """
    logger.info("[Tool] get_memory_episode episode_id=%s", data.episode_id)
    return backend.get_memory_episode(data)


if __name__ == "__main__":
    logger.info("[Setup] Starting memory-mcp server with stdio transport...")
    mcp.run(transport="stdio")
