from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class PRUser(BaseModel):
    login:str
    id:int
    avatar_url: Optional[str] = None
    html_url: Optional[str] = None

class PRRepository(BaseModel):
    id:int
    name:str
    full_name:str
    owner:PRUser
    html_url:str
    default_branch:str
    language:Optional[str] = None

class PRLabel(BaseModel):
    id:int
    name:str
    color:str
    description: Optional[str] = None

class PRData(BaseModel):
    """
    Structured representation of a GitHub Pull Request
    extracted from the webhook payload.
    """
    # Identity
    number:int
    id:int
    title:str
    state:str

    # People
    author:str
    author_id:int

    # Content
    body: Optional[str] = None
    base_branch:str
    head_branch:str
    head_sha:str

    # Stats - avialable in webhook payload
    commits:int
    additions:int
    deletions:int
    changed_files:int

    # Metadata
    draft:bool
    labels: list[str] = []
    assignees: list[str] = []
    requested_reviewers: Optional[List[str]] = None

    # URLs
    html_url:str
    diff_url:str
    patch_url:str

    # Timestamps
    created_at:str
    updated_at:str

    # Repo context
    repo_name:str
    repo_full_name:str
    repo_owner:str
    repo_default_branch:str
    repo_language:Optional[str] = None

    @classmethod
    def from_webhook_payload(cls, payload:dict) -> "PRData":
        """
        Parse raw GitHub webhook payload into a structured PRData object.
        Handles missing/optional fields gracefully.
        """
        pr = payload["pull_request"]
        repo = payload["repository"]

        return cls(
            # Identity
            number = pr["number"],
            id = pr["id"],
            title=pr["title"],
            state=pr["state"],

            # People
            author=pr["user"]["login"],
            author_id=pr["user"]["id"],

            # Content
            body=pr.get("body"),
            base_branch=pr["base"]["ref"],
            head_branch=pr["head"]["ref"],
            head_sha=pr["head"]["sha"],

            # Stats
            commits=pr.get("commits", 0),
            additions=pr.get("additions", 0),
            deletions=pr.get("deletions", 0),
            changed_files=pr.get("changed_files", 0),

            # Metadata
            draft = pr.get("draft", False),
            labels=[lbl["name"] for lbl in pr.get("labels", [])],
            assignees=[a["login"] for a in pr.get("assignees", [])],
            requested_reviewers=[
                r["login"] for r in pr.get("requested_reviewers", [])
            ],

            # URLs
            html_url=pr["html_url"],
            diff_url=pr["diff_url"],
            patch_url=pr["patch_url"],

            # Timestamps
            created_at=pr["created_at"],
            updated_at=pr["updated_at"],

            # Repo context
            repo_name=repo["name"],
            repo_full_name=repo["full_name"],
            repo_owner=repo["owner"]["login"],
            repo_default_branch=repo.get("default_branch", "main"),
            repo_language=repo.get("language"),
        )
    
    def log_summary(self) -> dict:
        """
        Returns a clean dict for structured logging —
        avoids dumping the full object into logs.
        """
        return {
            "pr_number": self.number,
            "title": self.title,
            "author": self.author,
            "repo": self.repo_full_name,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "head_sha": self.head_sha[:8],
            "draft": self.draft,
            "commits": self.commits,
            "additions": self.additions,
            "deletions": self.deletions,
            "changed_files": self.changed_files,
            "labels": self.labels,
            "requested_reviewers": self.requested_reviewers,
            "pr_url": self.html_url,
        }