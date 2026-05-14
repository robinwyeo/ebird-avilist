"""Tint Phylocanvas metadata for life-list completion (family tree + species subtrees)."""
from __future__ import annotations

from typing import Any


def _parse_hex_color(s: str) -> tuple[int, int, int]:
    """Parse #RGB or #RRGGBB to (r,g,b). Fallback grey if invalid."""
    if not isinstance(s, str):
        return 170, 170, 170
    t = s.strip()
    if not t.startswith("#"):
        return 170, 170, 170
    h = t[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) >= 6:
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            pass
    return 170, 170, 170


def _color_with_alpha(base: str, alpha: float) -> str:
    """Return rgba(...) string (Phylocanvas accepts this reliably)."""
    a = max(0.0, min(1.0, float(alpha)))
    r, g, b = _parse_hex_color(base)
    return f"rgba({r},{g},{b},{a:.3f})"


def tint_family_meta_by_completion(
    meta: dict[str, dict[str, Any]],
    pct_by_family: dict[str, float],
    seen_by_family: dict[str, int],
    total_by_family: dict[str, int],
    *,
    alpha_min: float = 0.18,
    alpha_max: float = 1.0,
) -> dict[str, dict[str, Any]]:
    """Clone *meta* and set tip colour alpha from % species seen in that family.

    Keeps the base hue from each entry's ``color`` (order palette) and scales
    opacity from *alpha_min* (0% seen) to *alpha_max* (100% seen).
    """
    out: dict[str, dict[str, Any]] = {}
    for fam, row in meta.items():
        m = dict(row)
        pct = float(pct_by_family.get(fam, 0.0) or 0.0)
        pct = max(0.0, min(100.0, pct))
        t = pct / 100.0
        alpha = alpha_min + (alpha_max - alpha_min) * t
        base = str(m.get("color", "#aaaaaa"))
        m["color"] = _color_with_alpha(base, alpha)
        s = int(seen_by_family.get(fam, 0) or 0)
        tot = int(total_by_family.get(fam, 0) or 0)
        tip = str(m.get("tooltip", "") or "").rstrip()
        extra = f"\n% seen: {pct:.0f}% ({s}/{tot})"
        m["tooltip"] = tip + extra if tip else f"% seen: {pct:.0f}% ({s}/{tot})"
        out[fam] = m
    return out


def tint_subtrees_by_seen(
    subtrees: dict[str, dict[str, Any]],
    seen_sci_names: set[str],
    *,
    alpha_seen: float = 1.0,
    alpha_unseen: float = 0.2,
) -> dict[str, dict[str, Any]]:
    """Clone *subtrees* and dim species tips not in *seen_sci_names*."""
    seen = {str(x).strip() for x in seen_sci_names if x}
    out: dict[str, dict[str, Any]] = {}
    for fam, payload in subtrees.items():
        pl = dict(payload)
        meta_in = pl.get("meta") or {}
        meta_out: dict[str, dict[str, Any]] = {}
        for tip, mrow in meta_in.items():
            m = dict(mrow)
            sci = tip.replace("_", " ").strip()
            is_seen = sci in seen or tip in seen
            base = str(m.get("color", "#aaaaaa"))
            m["color"] = _color_with_alpha(base, alpha_seen if is_seen else alpha_unseen)
            tip_txt = str(m.get("tooltip", "") or "").rstrip()
            tag = "Seen: yes" if is_seen else "Seen: no"
            m["tooltip"] = tip_txt + ("\n" + tag if tip_txt else tag)
            meta_out[tip] = m
        pl["meta"] = meta_out
        out[fam] = pl
    return out
