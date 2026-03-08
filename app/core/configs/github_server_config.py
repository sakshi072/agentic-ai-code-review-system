from app.core.configs.settings import settings
import logging
from enum import Enum

logger = logging.getLogger(__name__)

class MCPTool(str, Enum):
    """
    GitHub MCP tool names — single source of truth.
    Use these instead of hardcoded strings in agent code.
    """
    # Read
    GET_PULL_REQUEST         = "get_pull_request"
    GET_PULL_REQUEST_FILES   = "get_pull_request_files"
    GET_PULL_REQUEST_COMMENTS = "get_pull_request_comments"
    GET_PULL_REQUEST_REVIEWS  = "get_pull_request_reviews"
    GET_PULL_REQUEST_STATUS   = "get_pull_request_status"
    GET_FILE_CONTENTS        = "get_file_contents"
    GET_ISSUE                = "get_issue"
    LIST_COMMITS             = "list_commits"
    SEARCH_CODE              = "search_code"
    LIST_ISSUES              = "list_issues"
    LIST_PULL_REQUESTS       = "list_pull_requests"
    # Write
    CREATE_PULL_REQUEST_REVIEW = "create_pull_request_review"

ALLOWED_TOOLS = {tool.value for tool in MCPTool}

def build_server_config() -> dict:
    """Build server config"""
    token = settings.GITHUB_TOKEN
    if not token:
        raise EnvironmentError("GITHUB_TOKEN is missing")
    return {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "transport": "stdio",
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token},
        }
    }