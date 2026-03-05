"""
Local test script — simulates a GitHub PR webhook payload
Run: python tests/test_webhook_local.py

Useful during development before connecting real GitHub webhooks.
"""
import json
import requests

WEBHOOK_URL = "http://localhost:8000/review/webhook"

# Simulated GitHub PR webhook payload (mirrors real GitHub structure)
SAMPLE_PAYLOAD = {
    "action": "opened",
    "pull_request": {
        "number": 42,
        "id": 987654321,
        "title": "feat: add multi-agent orchestration layer",
        "state": "open",
        "draft": False,
        "body": "## Summary\nAdds LangGraph supervisor pattern with 4 specialist agents.\n\n## Changes\n- Security agent\n- Performance agent\n- Style agent\n- Test coverage agent",
        "html_url": "https://github.com/myorg/pr-review-system/pull/42",
        "diff_url": "https://github.com/myorg/pr-review-system/pull/42.diff",
        "patch_url": "https://github.com/myorg/pr-review-system/pull/42.patch",
        "user": {
            "login": "dev-alice",
            "id": 1001,
            "avatar_url": "https://avatars.githubusercontent.com/u/1001",
            "html_url": "https://github.com/dev-alice",
        },
        "base": {
            "ref": "main",
            "sha": "abc123def456abc123def456abc123def456abc1",
        },
        "head": {
            "ref": "feat/multi-agent-orchestration",
            "sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        },
        "commits": 5,
        "additions": 342,
        "deletions": 18,
        "changed_files": 8,
        "labels": [
            {"name": "enhancement"},
            {"name": "ai-feature"}
        ],
        "assignees": [],
        "requested_reviewers": [
            {"login": "senior-bob"},
            {"login": "tech-lead-carol"},
        ],
        "created_at": "2025-03-04T10:00:00Z",
        "updated_at": "2025-03-04T10:05:00Z",
    },
    "repository": {
        "id": 111222333,
        "name": "pr-review-system",
        "full_name": "myorg/pr-review-system",
        "html_url": "https://github.com/myorg/pr-review-system",
        "default_branch": "main",
        "language": "Python",
        "owner": {
            "login": "myorg",
            "id": 9001,
        },
    },
}


def test_webhook():
    print("🚀 Sending simulated GitHub PR webhook...")
    print(f"   URL     : {WEBHOOK_URL}")
    print(f"   PR      : #{SAMPLE_PAYLOAD['pull_request']['number']}")
    print(f"   Action  : {SAMPLE_PAYLOAD['action']}")
    print()

    response = requests.post(
        WEBHOOK_URL,
        json=SAMPLE_PAYLOAD,
        headers={
            "Content-Type": "application/json",
            "x-github-event": "pull_request",
            # No signature — dev mode (GITHUB_WEBHOOK_SECRET not set)
        },
    )

    print(f"✅ Response Status : {response.status_code}")
    print(f"✅ Response Body   : {json.dumps(response.json(), indent=2)}")


if __name__ == "__main__":
    test_webhook()