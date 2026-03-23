import subprocess
import tempfile
import os
import json
import logging
from typing import List
from app.utils.agent_helper import fetch_full_file

logger = logging.getLogger(__name__)

# Base class with shared helpers

class BaseLinter:
    name = ""
    extensions = set = set()

    def _write_to_temp(self, content:str, suffix:str) -> str:
        """Write content to a temp file, return path."""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        )
        tmp.write(content)
        tmp.flush()
        tmp.close()
        return tmp.name
    
    def _run_cmd(self, cmd:List[str]) -> tuple[str, str, int]:
        """Run a subprocess, return (stdout, stderr, returncode)."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            return result.stdout, result.stderr, result.returncode
        except FileNotFoundError:
            return "", f"{cmd[0]} not found", -1
        except subprocess.TimeoutExpired:
            return "", f"{cmd[0]} timed out", -1
    
    def is_available(self) -> bool:
        _,_,code = self._run_cmd([self.name, "--version"])
        return code != -1

class RuffLinter(BaseLinter):
    name = "ruff"
    extensions = {".py", ".pyw"}

    def build_cmd(self, tmp_path:str) -> list[str]:
        return [
            "ruff", "check", tmp_path, 
            "--no-cache",
            "--select", "F401,F811,F841,E501,E302,E303,W291,W293",
            "--ignore-noqa",
        ]
    

# Registry - maps extensions to linters
LINTER_REGISTRY: list[BaseLinter] = [
    RuffLinter()
]

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".lock", ".woff",
    ".woff2", ".ttf", ".eot", ".mp4", ".mp3",
}

def _resolve_linter(filename:str) -> BaseLinter | None:
    """Pick the right linter based on file extension or filename"""
    ext = os.path.splitext(filename)[-1].lower()
    basename = os.path.basename(filename).lower()

    for linter in LINTER_REGISTRY:
        if ext in linter.extensions:
            return linter

def _extract_added_lines(patch:str) -> str:
    """Extract only added lines from a unified diff patch."""
    lines = []
    for line in patch.splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            lines.append(line[1:])  # strip leading +
    return "\n".join(lines)

# Public API
async def run_linters(files:list, owner:str, repo:str, head_sha:str) -> dict[str, str]:
    """
    Run appropriate linter for each changed file.
    Returns dict of filenam -> raw linter output string.
    """
    results: dict[str,str] = {}

    for f in files:
        filename = f.get("filename", "")
        patch = f.get("patch", "")
        status = f.get("status", "modified")

        ext = os.path.splitext(filename)[-1].lower()
        if status == "removed" or ext in BINARY_EXTENSIONS:
            logger.info(f"Linter skipping {filename} — {status or 'binary'}")
            continue
        
        if not patch:
            logger.info(f"Linter skipping {filename} — no patch")
            continue

        linter = _resolve_linter(filename)
        if not linter:
            logger.info(f"No linter available for {filename}")
            continue
            
        if not linter.is_available():
            logger.warning(f"{linter.name} not installed — skipping {filename}")
            continue

        try:
            full_content = await fetch_full_file(owner, repo, filename, ref=head_sha)
            logger.info(f"Fetched full file {filename} — {len(full_content)} chars, {full_content.count(chr(10))} lines")
            logger.info(f"First 10 lines:\n" + "\n".join(full_content.splitlines()[:12]))
        except Exception as e:
            logger.warning(f"Could not fetch full file {filename}: {e}")
            continue

        if not full_content.strip():
            logger.info(f"Linter skipping {filename} — no added lines")
            continue

        tmp_path = linter._write_to_temp(full_content, ext)

        try:
            cmd = linter.build_cmd(tmp_path)
            logger.info(f"Running {linter.name} on {filename} — cmd: {cmd}")
            stdout,stderr,_ = linter._run_cmd(cmd) 
            output = stdout or stderr
            if output.strip():
                results[filename] = output.strip()
                logger.info(f"{linter.name} output for {filename}:\n{output.strip()}")
        finally:
            os.unlink(tmp_path)
    return results