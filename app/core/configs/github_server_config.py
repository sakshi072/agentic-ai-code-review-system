from app.core.settings import settings
import logging

logger = logging.getLogger(__name__)

ALLOWED_TOOLS = {
    # Read - used by all specialist agents
    "get_pull_request",
    "get_pull_request_files",
    "get_pull_request_comments",
    "get_pull_request_reviews",
    "get_pull_request_status",
    "get_file_contents",
    "get_issue",
    "list_commits",
    "search_code",
    "list_issues",
    "list_pull_requests",

    # Write - supervisor agent only
    "create_pull_request_review", # covers approve / request_changes / inline comments

}

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