from app.rules.checks import builtin  # noqa: F401  -- registers built-in checks
from app.rules.checks.registry import check, get_check, registered_checks

__all__ = ["check", "get_check", "registered_checks"]
