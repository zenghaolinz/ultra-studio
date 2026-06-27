from typing import Literal

PolicyAction = Literal["allow", "ask", "deny"]


class PermissionPolicy:
    def __init__(self, rules: dict[str, PolicyAction] | None = None) -> None:
        self._rules = rules or {}

    def decide(self, tool_name: str, risk: str, permission_mode: str) -> PolicyAction:
        explicit = self._rules.get(tool_name)
        if explicit:
            return explicit
        if risk == "destructive" and permission_mode != "autonomous":
            return "ask"
        return "allow"
