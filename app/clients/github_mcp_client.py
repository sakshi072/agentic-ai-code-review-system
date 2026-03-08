import logging
import asyncio
from app.core.configs.settings import settings
from langchain_mcp_adapters.client import MultiServerMCPClient
from app.core.configs.github_server_config import build_server_config
from app.utils.pr_helper import filter_tools
from contextlib import AsyncExitStack
from langchain_mcp_adapters.tools import load_mcp_tools
from typing import Any

logger = logging.getLogger(__name__)

class GithubMCPSession:
    """
    Long lived MCP persistent session for FastAPI
    Lifecycle:
        await session.start()    <- call in FastAPI lifespan startup
        session.tools            <- passed into LangGraph agents
        await session.stop()     <- call in FastAPI lifespan shutdown
    """
    def __init__(self):
        self._stack: AsyncExitStack | None = None
        self._tools: list = []
    
    async def start(self):
        """Start the MCP session. Called once at app startup."""
        logger.info("Starting Github MCP session")
        client = MultiServerMCPClient(build_server_config())
        self._stack = AsyncExitStack()
        session = await self._stack.enter_async_context(client.session("github"))

        all_tools    = await load_mcp_tools(session)
        self._tools  = filter_tools(all_tools)

        logger.info("Github MCP session started")
    
    async def stop(self):
        """Cleanly shits down the MCP subprocess"""
        if self._stack:
            old_stack = self._stack
            self._stack = None
            self._tools = []
            logger.info("Github MCP session stopped")
            try:
                await old_stack.aclose()
            except Exception as e:
                logger.warning(f"Error during close: {e}")
            logger.info("MCP Client closed")

    @property
    def tools(self) -> list:
        """Langchain-compatible tools - pass directly into LangGraph agents."""
        if not self._tools:
            self.start()
        return self._tools

    def get_tool(self, name: str):
        """
        Fetch a single tool by name.
        Useful for targeted invocations in tests and validation scripts.
        """
        tool = next((t for t in self.tools if t.name == name), None)
        if not tool:
            raise KeyError(
                f"Tool '{name}' not found. "
                f"Available: {[t.name for t in self.tools]}"
            )
        return tool
    
    async def invoke_tool(self, tool_name:str, **kwargs) -> Any:
        """
        Invoke a single MCP tool by nam.
        """
        tool = self.get_tool(tool_name)
        logger.info(f"Invoking: {tool_name}({kwargs})")
        return await tool.ainvoke(kwargs)

# ---------------------------------------------------------------------------
# Singleton — imported across the app
# ---------------------------------------------------------------------------

github_mcp_session = GithubMCPSession()