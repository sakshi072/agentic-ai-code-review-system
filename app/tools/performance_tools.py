import ast
import textwrap
from langchain_core.tools import tool
from typing import Any
from app.core.configs.settings import settings
import httpx

@tool
def _build_ast_report(source:str) -> dict[str, Any]:
    """
    Single O(n) pass over the AST. Collects per-function max loop nesting
    depth and call graph without re-walking subtrees.
    """
    functions:list[dict[str, Any]] = []
    file_max_depth = 0
    func_stack: list[dict[str, Any]] = []
    loop_depth = 0

    class _Visitor(ast.NodeVisitor):

        def _enter_function(self, node):
            frame = {"name": node.name, "line": node.lineno, "calls": set(), "max_loop_depth": 0}
            func_stack.append(frame)
            self.generic_visit(node)
            completed = func_stack.pop()
            completed["calls"] = sorted(completed["calls"])
            functions.append(completed)
        
        visit_FunctionDef = visit_AsyncFunctionDef = _enter_function

        def _enter_loop(self, node):
            nonlocal loop_depth, file_max_depth
            loop_depth += 1
            file_max_depth = max(file_max_depth, loop_depth)
            if func_stack:
                func_stack[-1]["max_loop_depth"] = max(
                    func_stack[-1]["max_loop_depth"], loop_depth
                )
            self.generic_visit(node)
            loop_depth -= 1
        
        visit_For = visit_While = _enter_loop
        visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _enter_loop
    
        def visit_Call(self, node):
            if func_stack:
                func = node.func
                if isinstance(func, ast.Name):
                    func_stack[-1]["calls"].add(func.id)
                elif isinstance(func, ast.Attribute):
                    func_stack[-1]["calls"].add(func.attr)
            self.generic_visit(node)
        
    _Visitor().visit(ast.parse(source))
    return {"file_max_loop_nesting": file_max_depth, "functions": functions}

@tool
def ast_analyze(code:str) -> str:
    """
    Parse complete Python source and return per-function loop nesting depth
    and call graph.

    Args:
        code: Complete Python source of a file. Must be valid, parseable Python.
    
    Returns:
        {file_max_loop_nesting, functions: [{name, line, max_loop_depth, calls}]}
        or a SyntaxError message if the source cannot be parsed.
    """
    try:
        report = _build_ast_report(textwrap.dedent(code))
    except SyntaxError as e:
        return f"SyntaxError - could not parse: {e}"
    return str(report)

_GITHUB_HEADERS = {
    "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
    "Accept": "application/vnd.github.text-match+json",
}

@tool
async def search_callers(owner:str, repo:str, function_name:str) -> str:
    """
    Find files in te repo that call this function.
    Use ONLY after confirming a performance issue - not speculatively.

    Args:
        owner: Repository owner, e.g. "acme-corp"
        repo: Repository name, e.g. "backend-api"
        function_name: Exact function name, e.g. "process_chunk"
    
    Returns:
        File paths and surrounding code fragments, or an error/empty message.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.github.com/search/code",
            params={"q": f"{function_name} repo:{owner}/{repo} language:python"},
            headers=_GITHUB_HEADERS,
        )
    
    if resp.status_code in (403, 429):
        if resp.status_code == 403:
            return (
                f"[RATE LIMITED] GitHub code search rate limit hit \u00e2\u0080\u0094 "
                f"cannot determine caller frequency for '{function_name}'. "
                "Treat the issue severity based on the diff alone."
            )
        return "GitHub code search rate limit exceeded"
    
    resp.raise_for_status()

    items = resp.json().get("items", [])[:10]

    results = []
    for item in items:
        for match in item.get("text_matches", []):
            results.append(f"{item['path']}:\n{match['fragment']}")
    
    return "\n---\n".join(results) if results else "No callers found"