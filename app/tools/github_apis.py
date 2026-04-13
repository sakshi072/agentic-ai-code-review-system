import logging
from app.core.configs.settings import settings
import httpx
import json
from typing import Any

logger = logging.getLogger(__name__)

# Embedded in every inline comment so they can be identified for cleanup.
# HTML comment — invisible in GitHub's rendered markdown.
BOT_COMMENT_TAG = "<!-- AI-BOT-COMMENT -->"

_REVIEW_COMMENTS_QUERY = """
query GetReviewComments($reviewId: ID!) {
  node(id: $reviewId) {
    ... on PullRequestReview {
      comments(first: 100) {
        nodes {
          databaseId
        }
      }
    }
  }
}
"""

# GitHub REST / GraphQL helpers

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

async def _graphql(query:str, variables:dict) -> dict:
    """Execute a GitHub GraphQL request and return the parsed JSON body."""
    try:    
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": variables},
                headers={
                    "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"failed to execute github graphql query: {e}")
        return {}

async def _fetch_review_comment_ids(review_node_id:str) -> list[int]:
    """
    Fetch the database IDs of all inline comments on a specific review.
    Uses a single GraphQL request
    Returns an empty list if the review no longer exists or has no comments.
    """
    try:
        data = await _graphql(
            _REVIEW_COMMENTS_QUERY,
            {"reviewId": review_node_id},
        )
        nodes = (
            data.get("data", {})
                .get("node", {})
                .get("comments", {})
                .get("nodes", [])
        )
        ids = [n["databaseId"] for n in nodes if n.get("databaseId")]
        logger.info(
            f"GraphQL — {len(ids)} comment(s) on review node {review_node_id}"
        )
        return ids
    except Exception as e:
        logger.warning(f"Failed to fetch review comments via GraphQL: {e}")
        return []

async def _delete_comment(owner:str, repo:str, comment_id:int) -> None:
    """
    Delete a single inline review comment via REST.
    204 = deleted, 404 = already gone — both treated as success.
    """
    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"https://api.github.com/repos/{owner}/{repo}"
            f"/pulls/comments/{comment_id}",
            headers=_headers(),
            timeout=10.0,
        )
    if response.status_code not in (204, 404):
        logger.warning(
            f"Unexpected status deleting comment {comment_id}: {response.status_code}"
        )

async def update_review(owner:str, repo:str, pr_number:int, review_id:int, new_review:str) -> None:
    """
    Delete a single inline review comment via REST.
    204 = deleted, 404 = already gone — both treated as success.
    """
    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"https://api.github.com/repos/{owner}/{repo}"
            f"/pulls/{pr_number}/reviews/{review_id}",
            json={"body": new_review},
            headers=_headers(),
            timeout=10.0,
        )
    if response.status_code == 200:
        logger.info(f"Updated summary for review {review_id}")
    else:
        logger.warning(
            f"Failed updating review {review_id}: {response.status_code} - {response.text}"
        )

async def cleanup_prior_review(
    owner:str,
    repo:str,
    pr_number:int,
    prior_review_id:int | None,
    prior_review_node_id: str | None,
) -> None:
    """
    Delete all inline comments from the prior bot review, then dismiss it.
    Fully non-fatal — any failure here is logged and skipped so the new
    review can always be posted.
    """
    if not prior_review_id or not prior_review_node_id:
        logger.info("No prior review IDs in state — skipping cleanup")
        return
    
    logger.info(
        f"Cleaning up prior review {prior_review_id} "
        f"(node: {prior_review_node_id})"
    )

    try:
        comment_ids = await _fetch_review_comment_ids(prior_review_node_id)
        for cid in comment_ids:
            await _delete_comment(owner, repo, cid)
        logger.info(f"Deleted {len(comment_ids)} inline comment(s)")
    except Exception as e:
        logger.warning(f"Comment deletion failed (non-fatal): {e}")

def _parse_review_ids(response: Any) -> tuple[int | None, str | None]:
    """
    Extract (database_id, node_id) from the MCP create-review response.
 
    database_id  — integer, used for REST dismiss endpoint.
    node_id      — string (e.g. 'PRR_kwDO...'), used for GraphQL comment fetch.
 
    Returns (None, None) on any parse failure.
    """
    try:
        data = response[0]["text"] if isinstance(response, list) else response["text"]
        
        if isinstance(data, dict):
            return data.get("id"), data.get("node_id")
            
        if isinstance(data, (str, bytes, bytearray)):
            parsed = json.loads(data)
            return parsed.get("id"), parsed.get("node_id")
    except Exception as e:
        logger.warning(f"Could not parse review IDs from response: {e}")
        return None, None

def _tag_inline_comments(comments: list[dict]) -> list[dict]:
    """Prepend BOT_COMMENT_TAG to every inline comment body."""
    return [
        {**c, "body": BOT_COMMENT_TAG + "\n" + c["body"]}
        for c in comments
    ]