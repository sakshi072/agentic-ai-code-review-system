import subprocess
import tempfile
import os
import json
import logging
from typing import List
from app.utils.agent_helper import fetch_full_file
from app.models.workflow_state import AgentFinding
import re 

logger = logging.getLogger(__name__)

PYTHON_LINTER_SEVERITY = {
    "F401": ("low",    "Unused import"),
    "F811": ("medium", "Redefined unused name"),
    "F841": ("low",    "Local variable assigned but never used"),
    "E302": ("low",    "Expected 2 blank lines"),
    "E303": ("low",    "Too many blank lines"),
}

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
            "--output-format", "concise",
            "--select", "F401,F811,F841,E302,E303",
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

def _enrich_linter_output(raw_output: str, filename: str, tmp_path: str) -> str:
    """
    Replace the temp file path with the real filename in ruff output.
    Produces one line per finding: filename:line: [CODE] message
    
    ruff --output-format concise produces:
      /tmp/tmpXXX.py:10:5: F401 `os` imported but unused
    We replace the temp path and strip the column number for brevity.
    """
    enriched = []
    for line in raw_output.splitlines():
        # Replace temp path with real filename
        line = line.replace(tmp_path, filename)
        # Match: filename:line:col: CODE message  → filename:line: [CODE] message
        m = re.match(r"^(.+?):(\d+):\d+:\s+(\S+)\s+(.+)$", line)
        if m:
            enriched.append(f"{m.group(1)}:{m.group(2)}: [{m.group(3)}] {m.group(4)}")
        elif line.strip():
            enriched.append(line)
    return "\n".join(enriched)

def filter_linter_to_diff(
    linter_output: dict[str, str],
    file_patches: dict[str, str],
) -> dict[str, str]:
    """
    Filter linter findings to only lines that were actually added in the diff.
    Uses the +[line N] annotations injected by format_files_for_llm.
    """
    filtered = {}
    for filename, output in linter_output.items():
        patch = file_patches.get(filename, "")
 
        # Extract line numbers from our diff annotations: +[line N]
        changed_lines = set(re.findall(r"\+\[line (\d+)\]", patch))
        # Fallback to hunk headers if annotations aren't present
        if not changed_lines:
            changed_lines = set(re.findall(r"\+(\d+)", patch))
 
        kept = []
        for issue_line in output.splitlines():
            m = re.search(r":(\d+):", issue_line)
            if m and m.group(1) in changed_lines:
                kept.append(issue_line)
 
        if kept:
            filtered[filename] = "\n".join(kept)

    findings = []
    for filename, output in filtered.items():
        patch = file_patches.get(filename, "")
        for line in output.splitlines():
            # Format: filename:line: [CODE] message
            m = re.match(r".+:(\d+):\s+\[(\w+)\]\s+(.+)", line)
            if not m:
                continue
            line_num, code, message = m.group(1), m.group(2), m.group(3)
            if code not in PYTHON_LINTER_SEVERITY:
                continue
            severity, title = PYTHON_LINTER_SEVERITY[code]
            findings.append(AgentFinding(
                severity=severity,
                file=filename,
                line=int(line_num),
                title=title,
                description=message,
                fix_explanation=f"Fix {code} violation on line {line_num}",
                fix_code="",
            ))
 
    return findings

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
            logger.info(f"Running {linter.name} on {filename}")
            stdout, stderr, _ = linter._run_cmd(cmd)
            output = stdout or stderr
            if output.strip():
                # Pass tmp_path so the enricher can replace it with the real filename
                enriched = _enrich_linter_output(output.strip(), filename, tmp_path)
                if enriched.strip():
                    results[filename] = enriched
                    logger.info(f"{linter.name} output for {filename}:\n{enriched}")
        finally:
            os.unlink(tmp_path)
    return results