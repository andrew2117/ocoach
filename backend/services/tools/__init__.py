"""External tool integrations for the LangGraph CP coach agent (Phase 3).

Each tool module exposes a single `@tool`-decorated async callable that the
agent graph in `services/agent.py` binds to the LLM. `ALL_TOOLS` is the list
handed to both `bind_tools()` and the `ToolNode`.
"""

from services.tools.codeforces_tool import get_user_stats
from services.tools.contest_tool import get_upcoming_contests
from services.tools.rag_tool import search_cp_knowledge

ALL_TOOLS = [search_cp_knowledge, get_user_stats, get_upcoming_contests]

__all__ = ["ALL_TOOLS", "get_user_stats", "get_upcoming_contests", "search_cp_knowledge"]
