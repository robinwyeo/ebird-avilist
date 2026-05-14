"""Phylocanvas metadata helpers: family-tree completion ring + species seen/unseen."""
from __future__ import annotations

from typing import Any

from phylo import order_tip_color_map


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
    df_species: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Clone *meta* for Phylocanvas family tips: order hue ring + grayscale inner fill.

    Each tip's ``color`` is the order ring (hex), drawn as the leaf shape border
    when ``showShapeBorders`` is on in the Phylocanvas embed. ``inner_fill`` is
    ``[r,r,r,255]`` with *r* from 255 (0% species seen) down to 0 (100% seen).

    Pass *df_species* (full AviList species table) so ring colours match
    ``build_family_tree`` / ``avilist_birds_explore`` exactly; omit it to keep
    each tip's existing ``color`` field (also hex from cached meta).
    """
    ord_palette: dict[str, str] | None = None
    if df_species is not None:
        ord_palette = order_tip_color_map(df_species)

    out: dict[str, dict[str, Any]] = {}
    for fam, row in meta.items():
        m = dict(row)
        pct = float(pct_by_family.get(fam, 0.0) or 0.0)
        pct = max(0.0, min(100.0, pct))
        base = str(m.get("color", "#aaaaaa"))
        order = str(m.get("order", "") or "").strip()
        if ord_palette and order:
            base = ord_palette.get(order, base)
        # Hex only — Phylocanvas strokeColour matches the avilist family tree;
        # rgba() strings can fail to parse when paired with inner_fill arrays.
        m["color"] = base
        g = int(round(255.0 * (1.0 - pct / 100.0)))
        g = max(0, min(255, g))
        m["inner_fill"] = [g, g, g, 255]
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
