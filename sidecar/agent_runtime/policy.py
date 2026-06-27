from typing import Any, Literal

PolicyAction = Literal["allow", "ask", "deny"]


class PermissionPolicy:
    def __init__(self, rules: dict[str, PolicyAction] | None = None) -> None:
        self._rules = rules or {}

    def decide(
        self,
        tool_name: str,
        risk: str,
        permission_mode: str,
        arguments: dict[str, Any] | None = None,
    ) -> PolicyAction:
        explicit = self._rules.get(tool_name)
        if explicit:
            return explicit
        if (
            risk == "destructive"
            and permission_mode != "autonomous"
            and not bool((arguments or {}).get("confirmed", False))
        ):
            return "ask"
        return "allow"
