from typing import Optional


class TaskModeSelector:
    """Resolve task routing mode using explicit request mode or lightweight heuristics."""

    SIMPLE_VERBS = ("show", "list", "get", "fetch", "search", "find", "convert", "ocr", "extract")
    COMPLEX_VERBS = ("create", "add", "assign", "bind", "update", "delete", "deploy", "start", "join")

    def resolve_mode(self, goal: str, requested_mode: Optional[str]) -> str:
        if requested_mode in {"cmdengine", "mcp"}:
            return requested_mode

        goal_lower = (goal or "").lower()
        if "mcp." in goal_lower or "tool " in goal_lower or "server " in goal_lower:
            return "mcp"

        if any(verb in goal_lower for verb in self.COMPLEX_VERBS):
            return "cmdengine"

        if any(verb in goal_lower for verb in self.SIMPLE_VERBS):
            return "mcp"

        return "cmdengine"
