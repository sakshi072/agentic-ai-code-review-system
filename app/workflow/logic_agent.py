"""
app/workflow/logic_agent.py
 
Logic agent node — reviews PR diff for logical correctness.
 
Uses langgraph.prebuilt.create_react_agent (the current production API as of
langgraph 0.3+). This returns a compiled LangGraph graph directly — no
AgentExecutor wrapper, no hidden prompts, no deprecated abstractions.
 
The agent starts with the diff, fetches file context on demand via two
focused tools, then produces structured findings.
"""
 
import logging
import asyncio
from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
 
from app.core.prompts.logic_agent_prompt import LOGIC_AGENT_SYSTEM_PROMPT
from app.models.agent_finding_model import ResponseSchema
from app.models.workflow_state import AgentFinding
from app.tools.gihub_files import fetch_import_file, fetch_reviewed_file
from app.utils.agent_helper import build_agent_prompt, build_llm, find_line_in_diff
 
logger = logging.getLogger(__name__)
_AGENT_TIMEOUT_SECONDS=300
 
# Tools the logic agent is allowed to call.
# Both are top-level async @tool functions — no closures, no hidden state.
LOGIC_AGENT_TOOLS = [fetch_reviewed_file, fetch_import_file]

async def logic_agent_node(payload: dict) -> dict:
    """
    LangGraph node — logical code review on one diff chunk.
 
    Receives (via Send payload):
        owner, repo, pr_number, head_sha  — PR identity
        chunk                              — {files, diff_context, file_patches}
 
    Returns:
        logic_findings   — list[AgentFinding] (accumulated via add reducer)
        agents_completed — 1
    """
    owner     = payload["owner"]
    repo      = payload["repo"]
    pr_number = payload["pr_number"]
    head_sha  = payload["head_sha"]
 
    chunk        = payload["chunk"]
    to_analyze   = chunk["files"]
    diff_context = chunk["diff_context"]
    file_patches = chunk["file_patches"]
 
    logger.info(
        f"Logic agent starting — {owner}/{repo}/#{pr_number} "
        f"({len(to_analyze)} file(s) in chunk)"
    )
 
    if not diff_context.strip():
        logger.info("Logic agent — empty diff, skipping")
        return {"logic_findings": [], "agents_completed": 1}
 
    # ------------------------------------------------------------------
    # Build the agent
    # ------------------------------------------------------------------
    llm = build_llm()
 
    agent = create_agent(
        model=llm,
        tools=LOGIC_AGENT_TOOLS,
        system_prompt=LOGIC_AGENT_SYSTEM_PROMPT,  # system message injected into every turn
        response_format=ResponseSchema
    )
 
    # ------------------------------------------------------------------
    # Build the user prompt
    # ------------------------------------------------------------------
    user_prompt = build_agent_prompt(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        diff_context=diff_context,
        focus="logical correctness",
    )
 
    user_prompt += (
        f"\n\n## Tool arguments\n"
        f"owner={owner!r}  repo={repo!r}  head_sha={head_sha!r}\n\n"
        "Derive file paths from import lines in the diff:\n"
        "  'from app.utils.agent_helper import X' → 'app/utils/agent_helper.py'\n\n"
        "fetch_import_file budget: 4 calls max. Count. Stop at 4. Depth-1 only."
    )
 
    # ------------------------------------------------------------------
    # Run the agent
    # ------------------------------------------------------------------
    try:
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(content=user_prompt)]},
                config={"recursion_limit": 4},
            ),
            timeout=_AGENT_TIMEOUT_SECONDS,
        )
        response: ResponseSchema = result.get("structured_response")
        if response is None:
            logger.warning("Logic agent — no structured_response, returning empty")
            return {"logic_findings": [], "agents_completed": 1}
 
        logger.info(f"Logic agent — {len(response.findings)} finding(s)")
        for f in response.findings:
            logger.info(f"  [{f.severity}] {f.title} | file={f.file} | snippet={f.code_snippet[:60]!r}")
 
    except asyncio.TimeoutError:
        logger.warning(f"Logic agent — timed out after {_AGENT_TIMEOUT_SECONDS}s")
        return {"logic_findings": [], "agents_completed": 1}
    except Exception as exc:
        logger.error(f"Logic agent — failed: {exc}", exc_info=True)
        return {"logic_findings": [], "agents_completed": 1}
 
    # ------------------------------------------------------------------
    # Map pydantic → AgentFinding TypedDict
    # ------------------------------------------------------------------
    findings: list[AgentFinding] = [
        AgentFinding(
            severity        = f.severity.value,
            file            = f.file,
            line            = find_line_in_diff(
                                  file_patches.get(f.file, ""),
                                  f.code_snippet,
                              ),
            title           = f.title,
            description     = f.description.replace("\\\\n", "\n"),
            fix_explanation = f.fix_explanation.replace("\\\\n", "\n"),
            fix_code        = f.fix_code,
        )
        for f in response.findings
    ]
 
    logger.info(f"Logic agent complete — {len(findings)} finding(s)")
    for f in findings:
        logger.info(f"Logic agent finding: {f}")
    return {"logic_findings": findings, "agents_completed": 1}
