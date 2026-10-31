"""Human-readable rendering of normalised entity values (mirror of frontend/src/utils/format.js)."""

from typing import Any


def fmt_amount(nv: dict[str, Any]) -> str:
    amt = float(nv["amount"])
    text = f"{amt / 1e6:,.2f}m".replace(".00m", "m") if amt >= 1e6 else f"{amt:,.0f}"
    return f"{nv.get('currency') or ''} {text}".strip()


def fmt_normalized(nv: dict[str, Any] | None) -> str | None:
    if not nv:
        return None
    if nv.get("amount") is not None:
        return fmt_amount(nv)
    if nv.get("date"):
        return nv["date"]
    if nv.get("tenor"):
        t = nv["tenor"]
        return f"{t.get('value')} {t.get('unit')}{'' if t.get('value') == 1 else 's'}"
    if nv.get("type") == "fixed":
        return f"{nv.get('rate_pct')}% fixed"
    if nv.get("type") == "floating":
        spread = f" + {nv['spread_bps']} bps" if nv.get("spread_bps") is not None else ""
        tenor = f"{nv['benchmark_tenor']} " if nv.get("benchmark_tenor") else ""
        return f"{tenor}{nv.get('benchmark')}{spread}"
    if nv.get("type") == "spread":
        return f"{nv.get('spread_bps')} bps"
    if nv.get("jurisdiction"):
        return nv["jurisdiction"]
    if nv.get("name"):
        return f"{nv['name']}" + (f" ({nv['role'].replace('_', ' ')})" if nv.get("role") else "")
    if nv.get("currency") and len(nv) == 1:
        return nv["currency"]
    if nv.get("frequency"):
        return f"{nv['frequency'].replace('-', ' ')} ({nv.get('per_year')}/yr)"
    if nv.get("convention"):
        return nv["convention"]
    if nv.get("type"):
        return str(nv["type"]).replace("_", " ")
    if nv.get("text"):
        return nv["text"]
    return str(nv)
