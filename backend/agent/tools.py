"""Phase 7: sandboxed C++ execution tool for the CP coach agent.

`compile_and_test_cpp` lets the agent actually *run* a user's C++
implementation against a hand-written test case instead of eyeballing it
for correctness. Execution never happens on this process or host: the
source is POSTed to a local Piston instance (`piston_api_url` in
`core/config.py`), which compiles and runs it inside isolate and returns
compile/run stdout, stderr, wall/cpu time, and peak memory. This module
only ever makes an outbound HTTP call; it never `exec`s, `subprocess`s,
or otherwise runs untrusted code on the FastAPI host.

Self-hosted Piston (not emkc.org / RapidAPI Judge0): the public Piston
API does not issue keys for this project, and Judge0 1.13.1 cannot
create isolate boxes on WSL2's cgroup v2. Local Piston is the sandbox
this tool is wired to.

Deliberately kept in `agent/` rather than `services/tools/`: this tool is a
gateway to an external code-execution sandbox (a materially different
trust/failure boundary than the read-only Codeforces/RAG lookups in
`services/tools/`), so it's wired into the graph in `agent/graph.py`
directly rather than folded into that package's `ALL_TOOLS`.
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any, Literal

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from core.config import settings
from services.tools.codeforces_client import codeforces_get

logger = logging.getLogger(__name__)

PRACTICE_CONTEST_DEFAULT_COUNT = 3
PRACTICE_CONTEST_MAX_COUNT = 5

CppExecutionVerdict = Literal["success", "ce", "wa", "tle", "re", "error"]
CppExecutionPayload = tuple[str, dict[str, Any]]

# Must exceed Piston's compile+run wall budgets plus HTTP overhead so a
# legitimate TLE is reported as a Piston stage status, not an httpx timeout
# that looks like the sandbox is down.
REQUEST_TIMEOUT_SECONDS = 30.0
# Piston rejects values above the server maxima (defaults: compile 10s, run 3s).
COMPILE_TIMEOUT_MS = 10_000
RUN_TIMEOUT_MS = 3_000

# Phase 9: hard-cap LLM-facing tool output *before* it is written into
# graph state. `trim_messages(..., allow_partial=False)` drops a ToolMessage
# that exceeds the context budget, which would wipe the whole window.
# ~10k chars is ~2.5k tokens, leaving room for the rest of the turn.
LLM_TOOL_OUTPUT_MAX_CHARS = 10_000
TRUNCATION_WARNING = "...[TRUNCATED: Output too long]"

PISTON_STAGE_STATUS_LABELS: dict[str, str] = {
    "RE": "Runtime Error",
    "SG": "Killed by signal",
    "TO": "Time Limit Exceeded",
    "OL": "Stdout length exceeded",
    "EL": "Stderr length exceeded",
    "XX": "Internal Error",
}


class PracticeContestInput(BaseModel):
    tags: list[str] = Field(
        default_factory=list,
        description="Codeforces problem tags to filter by (e.g. ['dp', 'trees']). Leave empty to ignore tags.",
    )
    count: int = Field(
        default=PRACTICE_CONTEST_DEFAULT_COUNT,
        ge=1,
        le=PRACTICE_CONTEST_MAX_COUNT,
        description="Number of problems to return (1-5, default 3).",
    )
    min_rating: int | None = Field(
        default=None,
        description="Minimum problem rating, inclusive. Omit to allow any lower rating.",
    )
    max_rating: int | None = Field(
        default=None,
        description="Maximum problem rating, inclusive. Omit to allow any higher rating.",
    )


class CppExecutionInput(BaseModel):
    """Strict input schema — both fields are mandatory, no defaults. A tool
    call missing either is a malformed call from the LLM (e.g. it tried to
    run code with no test input), not something to silently paper over.
    """

    source_code: str = Field(
        ...,
        description="Complete, compilable C++ source code to submit for execution (the full file, not a snippet).",
    )
    standard_input: str = Field(
        ...,
        description="Exact bytes to feed the program on stdin for this test case. Pass an empty string if the "
        "program reads no input.",
    )


def _truncate(text: str, limit: int = LLM_TOOL_OUTPUT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(TRUNCATION_WARNING) - 1)
    return text[:keep].rstrip() + "\n" + TRUNCATION_WARNING


def _stage(payload: dict[str, Any], name: str) -> dict[str, Any]:
    stage = payload.get(name)
    return stage if isinstance(stage, dict) else {}


def _ms_to_seconds(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value) / 1000.0:.3f}"
    except (TypeError, ValueError):
        return None


def _bytes_to_kb(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(int(round(float(value) / 1024.0)))
    except (TypeError, ValueError):
        return None


def _combined_output(stage: dict[str, Any]) -> str:
    stderr = (stage.get("stderr") or "").rstrip("\n")
    stdout = (stage.get("stdout") or "").rstrip("\n")
    if stderr:
        return stderr
    return stdout


def _status_label(payload: dict[str, Any]) -> str:
    compile_stage = _stage(payload, "compile")
    run_stage = _stage(payload, "run")

    compile_status = compile_stage.get("status")
    if compile_stage.get("code") not in (None, 0):
        return "Compilation Error"
    if compile_status:
        return f"Compilation {PISTON_STAGE_STATUS_LABELS.get(compile_status, compile_status)}"

    run_status = run_stage.get("status")
    if run_status:
        label = PISTON_STAGE_STATUS_LABELS.get(run_status, run_status)
        signal = run_stage.get("signal")
        return f"{label} ({signal})" if signal else label
    if run_stage.get("code") in (None, 0):
        return "Accepted"
    return f"Runtime Error (exit {run_stage.get('code')})"


def _verdict_from_status(status: str, compiled_ok: bool) -> CppExecutionVerdict:
    normalized = status.lower()
    if not compiled_ok or "compilation" in normalized:
        return "ce"
    if "time limit" in normalized:
        return "tle"
    if status == "Accepted":
        return "success"
    if "wrong answer" in normalized:
        return "wa"
    if "runtime" in normalized or normalized.startswith("killed"):
        return "re"
    return "error"


def build_cpp_execution_result(
    payload: dict[str, Any] | None = None,
    *,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Structured Judge0/Piston execution payload for the frontend UI."""
    if error_message is not None:
        return {
            "status": error_message,
            "stdout": None,
            "stderr": None,
            "compile_output": None,
            "time": None,
            "memory": None,
            "verdict": "error",
        }

    compile_stage = _stage(payload or {}, "compile")
    run_stage = _stage(payload or {}, "run")
    status = _status_label(payload or {})
    compiled_ok = compile_stage.get("code") in (None, 0) and not compile_stage.get("status")

    metrics_stage = run_stage if compiled_ok else compile_stage
    time_seconds_raw = metrics_stage.get("wall_time")
    memory_bytes_raw = metrics_stage.get("memory")

    time_value: float | None = None
    if time_seconds_raw is not None:
        try:
            time_value = round(float(time_seconds_raw) / 1000.0, 3)
        except (TypeError, ValueError):
            time_value = None

    memory_kb: int | None = None
    if memory_bytes_raw is not None:
        try:
            memory_kb = int(round(float(memory_bytes_raw) / 1024.0))
        except (TypeError, ValueError):
            memory_kb = None

    compile_output = _combined_output(compile_stage) or None
    stdout = (run_stage.get("stdout") or "").rstrip("\n") if compiled_ok else None
    stderr = (run_stage.get("stderr") or "").rstrip("\n") if compiled_ok else None

    return {
        "status": status,
        "stdout": stdout or None,
        "stderr": stderr or None,
        "compile_output": compile_output,
        "time": time_value,
        "memory": memory_kb,
        "verdict": _verdict_from_status(status, compiled_ok),
    }


def _format_result(payload: dict[str, Any]) -> str:
    """Renders the Piston execute response into the plain-text summary
    handed back to the LLM as the tool result.
    """
    compile_stage = _stage(payload, "compile")
    run_stage = _stage(payload, "run")
    language = payload.get("language") or "c++"
    version = payload.get("version") or "unknown"
    status = _status_label(payload)
    compiled_ok = compile_stage.get("code") in (None, 0) and not compile_stage.get("status")

    metrics_stage = run_stage if compiled_ok else compile_stage
    time_seconds = _ms_to_seconds(metrics_stage.get("wall_time"))
    cpu_seconds = _ms_to_seconds(metrics_stage.get("cpu_time"))
    memory_kb = _bytes_to_kb(metrics_stage.get("memory"))
    compile_output = _combined_output(compile_stage)
    stdout = (run_stage.get("stdout") or "").rstrip("\n") if compiled_ok else ""
    stderr = (run_stage.get("stderr") or "").rstrip("\n") if compiled_ok else ""

    lines = [
        f"Status: {status}",
        f"Runtime: {language} {version}",
        f"Time: {time_seconds}s wall" if time_seconds is not None else "Time: unavailable",
    ]
    if cpu_seconds is not None:
        lines.append(f"CPU time: {cpu_seconds}s")
    lines.append(f"Memory: {memory_kb} KB" if memory_kb is not None else "Memory: unavailable")
    if not compiled_ok:
        lines.append("Note: time/memory above are for the compile stage; the program did not run.")

    if compile_output:
        lines.append(f"Compile output:\n{_truncate(compile_output)}")

    if compiled_ok:
        lines.append(f"Stdout:\n{_truncate(stdout)}" if stdout else "Stdout: (empty)")
        if stderr:
            lines.append(f"Stderr:\n{_truncate(stderr)}")

    return _truncate("\n".join(lines))


def _error_payload(message: str) -> CppExecutionPayload:
    return message, build_cpp_execution_result(error_message=message)


def _problem_rating_in_range(
    rating: Any,
    *,
    min_rating: int | None,
    max_rating: int | None,
) -> bool:
    if rating is None:
        return min_rating is None and max_rating is None
    try:
        value = int(rating)
    except (TypeError, ValueError):
        return False
    if min_rating is not None and value < min_rating:
        return False
    if max_rating is not None and value > max_rating:
        return False
    return True


def _format_practice_contest_result(problems: list[dict[str, Any]]) -> str:
    return json.dumps({"problems": problems}, indent=2)


@tool(args_schema=PracticeContestInput)
async def generate_practice_contest(
    tags: list[str],
    count: int = PRACTICE_CONTEST_DEFAULT_COUNT,
    min_rating: int | None = None,
    max_rating: int | None = None,
) -> str:
    """Builds a pseudo-contest by sampling random Codeforces problemset problems
    matching the requested tags and rating band, returning each problem's name,
    rating, tags, and a direct problem URL.

    Use when the user asks for a practice contest, custom problem set, or wants
    to drill specific algorithm topics (e.g. "give me 3 dp problems around 1400").
    """
    if min_rating is not None and max_rating is not None and min_rating > max_rating:
        return (
            "Invalid rating range: min_rating must be less than or equal to max_rating. "
            "Ask the user to adjust the bounds."
        )

    params: dict[str, str] = {}
    normalized_tags = [tag.strip().lower() for tag in tags if tag.strip()]
    if normalized_tags:
        params["tags"] = ";".join(normalized_tags)

    response = await codeforces_get(
        "problemset.problems",
        params,
        context="fetching the problemset for a practice contest",
    )
    if not response.ok:
        return response.error or "Unknown Codeforces API error."

    result = response.result
    if not isinstance(result, dict):
        return "Codeforces API returned an unexpected problemset payload."

    raw_problems = result.get("problems")
    if not isinstance(raw_problems, list):
        return "Codeforces API returned an unexpected problemset payload."

    filtered: list[dict[str, Any]] = []
    for problem in raw_problems:
        if not isinstance(problem, dict):
            continue
        contest_id = problem.get("contestId")
        index = problem.get("index")
        if contest_id is None or index is None:
            continue
        if not _problem_rating_in_range(
            problem.get("rating"),
            min_rating=min_rating,
            max_rating=max_rating,
        ):
            continue
        filtered.append(problem)

    if not filtered:
        criteria: list[str] = []
        if normalized_tags:
            criteria.append(f"tags={', '.join(normalized_tags)}")
        if min_rating is not None:
            criteria.append(f"min_rating={min_rating}")
        if max_rating is not None:
            criteria.append(f"max_rating={max_rating}")
        summary = ", ".join(criteria) if criteria else "the given filters"
        return (
            f"No Codeforces problems matched {summary}. "
            "Ask the user to broaden the tag or rating filters."
        )

    sample_size = min(count, len(filtered))
    selected = random.sample(filtered, sample_size)

    formatted = []
    for problem in selected:
        contest_id = problem["contestId"]
        index = problem["index"]
        formatted.append(
            {
                "name": problem.get("name") or f"Problem {index}",
                "rating": problem.get("rating"),
                "tags": problem.get("tags") or [],
                "url": f"https://codeforces.com/problemset/problem/{contest_id}/{index}",
            }
        )

    return _format_practice_contest_result(formatted)


@tool(args_schema=CppExecutionInput, response_format="content_and_artifact")
async def compile_and_test_cpp(source_code: str, standard_input: str) -> CppExecutionPayload:
    """Compiles and runs C++ source code against a single stdin test case in
    an isolated Piston sandbox (GCC, C++17), returning the execution status,
    stdout, stderr, compile output, wall time (seconds), CPU time (seconds),
    and peak memory (KB).

    Use this proactively — before telling the user their code is correct —
    to actually verify non-trivial C++ implementations, especially advanced
    data structures such as segment trees, suffix arrays, centroid
    decomposition, and palindromic trees. Write the test cases yourself
    (typical inputs, boundary cases like N=0/N=1, and adversarial/worst-case
    inputs meant to stress complexity or edge-case handling) rather than
    waiting for the user to supply them, unless the problem statement gives
    exact sample input/output to reproduce verbatim.
    """
    if not settings.piston_api_url:
        return _error_payload(
            "C++ execution is unavailable: PISTON_API_URL is not configured on the server."
        )

    body = {
        "language": "c++",
        "version": "*",
        "files": [{"name": "main", "content": source_code}],
        "stdin": standard_input,
        "compile_timeout": COMPILE_TIMEOUT_MS,
        "run_timeout": RUN_TIMEOUT_MS,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.piston_api_url, json=body)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        return _error_payload(
            "Piston execution request timed out — the sandbox may be overloaded or the "
            "submission ran too long. Try again, or check the code for an infinite loop."
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code >= 500:
            message = (
                f"Piston API returned a server error ({status_code}) — the sandbox is temporarily unavailable."
            )
        else:
            message = f"Piston API rejected the request ({status_code}): {exc.response.text[:300]}"
        return _error_payload(message)
    except httpx.HTTPError as exc:
        return _error_payload(f"Piston API request failed: {exc}")
    except ValueError:
        return _error_payload("Piston API returned an unparseable (non-JSON) response.")

    try:
        return _format_result(payload), build_cpp_execution_result(payload)
    except Exception as exc:  # defensive: never let a malformed Piston payload crash the request
        logger.exception("compile_and_test_cpp: failed to parse Piston response")
        return _error_payload(f"Piston execution completed but the response could not be parsed: {exc}")
