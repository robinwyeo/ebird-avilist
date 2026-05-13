"""phylo.py — Phylogenetic tree helpers for the AviList notebook.

Fetches bird family- and order-level evolutionary trees from OpenTree of Life
(which incorporates Stiller et al. 2024 and other genomic studies), builds
rich tip metadata from AviList, and renders Phylocanvas.gl HTML widgets.

Workflow
--------
  from phylo import (build_order_tree, build_family_tree,
                     build_family_subtrees, load_family_subtrees_inline,
                     display_phylocanvas, phylocanvas_html)
  from birds_nb import data_dir

  PHYLO_DIR = data_dir() / "phylogeny"
  ord_nwk, ord_meta = build_order_tree(df_species, PHYLO_DIR)
  fam_nwk, fam_meta = build_family_tree(df_species, PHYLO_DIR)
  # One-time build of per-family species subtrees (slow, cached after first run):
  build_family_subtrees(df_species, PHYLO_DIR)
  subtrees = load_family_subtrees_inline(PHYLO_DIR)
  # Notebook (inline data — all subtrees bundled in the srcdoc):
  display_phylocanvas(fam_nwk, fam_meta, "avilist-fam-tree", height=760,
                      drilldown=True, subtrees_inline=subtrees)
  # Static Jekyll page (same iframe+srcdoc pattern as the notebook; per-family
  # JSON fetched on click from the site):
  html = phylocanvas_html(fam_nwk, fam_meta, "avilist-fam-tree", height=760,
                          drilldown=True,
                          subtrees_url_base="/assets/data-science/avilist/phylogeny/subtrees/")
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TNRS_URL     = "https://api.opentreeoflife.org/v3/tnrs/match_names"
_INDUCED_URL  = "https://api.opentreeoflife.org/v3/tree_of_life/induced_subtree"
# Pin major v1 — avoids surprise breakage from a future 2.x on unpkg @latest
_PHYLOCANVAS_CDN = (
    "https://unpkg.com/@phylocanvas/phylocanvas.gl@1/dist/bundle.min.js"
)

# 50-color palette designed to be distinct on dark backgrounds.
# Cycles when there are more taxa than colors (unlikely for orders).
_PALETTE: list[str] = [
    "#E63946", "#F4A261", "#2A9D8F", "#457B9D", "#6A4C93",
    "#F72585", "#4CC9F0", "#06D6A0", "#FB8500", "#3A86FF",
    "#FF006E", "#8338EC", "#FFBE0B", "#38B000", "#D00000",
    "#023E8A", "#9B2226", "#AE2012", "#CA6702", "#EE9B00",
    "#94D2BD", "#0A9396", "#005F73", "#D62828", "#F77F00",
    "#FCBF49", "#84A98C", "#52B788", "#2D6A4F", "#40916C",
    "#74C69D", "#74B3CE", "#508CA4", "#5C5C8A", "#6B4226",
    "#A7754D", "#CE796B", "#C18C5D", "#43AA8B", "#577590",
    "#E9C46A", "#264653", "#2B9348", "#80B918", "#FF9F1C",
    "#FFBF69", "#CBF3F0", "#9BF5D1", "#EF8C8C", "#C77DFF",
]

_TREE_TYPE_MAP: dict[str, str] = {
    "circular":     "Circular",
    "radial":       "Radial",
    "rectangular":  "Rectangular",
    "hierarchical": "Hierarchical",
}

# Interactive viewer: light canvas so default branch colour (~#222222) is visible.
# Phylocanvas.gl expects RGBA arrays for these props (see package docs).
_TREE_VIEW_BG_CSS = "#ffffff"
_TREE_STROKE_RGBA = [42, 42, 42, 255]   # branch lines
_TREE_FONT_RGBA = [26, 26, 26, 255]    # leaf labels
_TREE_BRANCH_WIDTH = 1.75


def _format_family_tooltip(
    order_lat: str,
    order_eng: str,
    family_lat: str,
    family_eng: str,
    n_genera: int,
    n_species: int,
) -> str:
    """Multi-line hover text: Latin (English) for order & family, then genus/species counts."""
    ord_part = f"{order_lat} ({order_eng})" if order_eng else order_lat
    fam_part = f"{family_lat} ({family_eng})" if family_eng else family_lat
    return (
        f"Order: {ord_part}\n"
        f"Family: {fam_part}\n"
        f"Genera: {n_genera:,}\n"
        f"Species: {n_species:,}"
    )


def _family_meta_has_hover(meta: dict[str, dict]) -> bool:
    """True if cached family meta includes per-tip tooltip strings."""
    for v in meta.values():
        if isinstance(v, dict) and v.get("tooltip"):
            return True
    return False


def _family_meta_from_avilist(df_species, families: list[str]) -> dict[str, dict]:
    """Build Phylocanvas tip metadata (colours, counts, hover tooltips) from AviList."""
    import pandas as pd

    fam_to_ord = (
        df_species.dropna(subset=["Family", "Order"])
        .drop_duplicates("Family")
        .set_index("Family")["Order"]
        .to_dict()
    )
    fam_to_eng = (
        df_species.dropna(subset=["Family"])
        .drop_duplicates("Family")
        .set_index("Family")["Family_English_name"]
        .map(lambda x: str(x).strip() if pd.notna(x) else "")
        .to_dict()
    )
    try:
        from birds_nb import ORDER_ENGLISH
    except ImportError:
        ORDER_ENGLISH = {}

    fam_gen_count = df_species.groupby("Family")["Genus"].nunique().to_dict()
    fam_sp_count = df_species.groupby("Family").size().to_dict()
    all_orders = list(dict.fromkeys(df_species["Order"].dropna()))
    ord_palette = _palette_for_groups(all_orders)

    meta: dict[str, dict] = {}
    for fam in families:
        order = fam_to_ord.get(fam, "")
        n = int(fam_sp_count.get(fam, 0))
        n_gen = int(fam_gen_count.get(fam, 0))
        color = ord_palette.get(order, "#aaaaaa")
        fam_eng = fam_to_eng.get(fam, "") or ""
        ord_eng = ORDER_ENGLISH.get(order, "") if order else ""
        tip = _format_family_tooltip(order, ord_eng, fam, fam_eng, n_gen, n)
        meta[fam] = {
            "order":           order,
            "color":           color,
            "n_species":       n,
            "n_genera":        n_gen,
            "order_english":   ord_eng,
            "family_english":  fam_eng,
            "tooltip":         tip,
            "label":           fam,
        }
    return meta


# ---------------------------------------------------------------------------
# Internal: per-species metadata helpers (for family drill-down subtrees)
# ---------------------------------------------------------------------------

def _format_species_tooltip(
    genus: str,
    family_lat: str,
    family_eng: str,
    english_name: str,
    iucn: str,
    authority: str,
) -> str:
    """Hover text for a single species leaf in a family drill-down subtree."""
    fam_part = f"{family_lat} ({family_eng})" if family_eng else family_lat
    lines = [f"Genus: {genus}", f"Family: {fam_part}"]
    if english_name:
        lines.append(f"English: {english_name}")
    if iucn:
        lines.append(f"IUCN: {iucn}")
    if authority:
        lines.append(f"Authority: {authority}")
    return "\n".join(lines)


def _get_cell(row, *cols: str) -> str:
    """Safely return the first non-empty string value from a pandas Series."""
    import pandas as pd
    for c in cols:
        try:
            v = row[c]
            if not pd.isna(v):
                s = str(v).strip()
                if s:
                    return s
        except (KeyError, TypeError):
            pass
    return ""


def _species_meta_for_family(
    df_species,
    family: str,
    family_eng: str,
    genus_palette: dict[str, str],
) -> dict[str, dict]:
    """Build per-species Phylocanvas tip metadata for one family."""
    fam_rows = df_species[df_species["Family"] == family]
    meta: dict[str, dict] = {}
    for _, row in fam_rows.iterrows():
        sci = _get_cell(row, "Scientific_name")
        if not sci:
            continue
        genus     = _get_cell(row, "Genus") or sci.split()[0]
        eng       = _get_cell(
            row,
            "English_name_AviList",
            "English_name_Clements_v2024",
            "English_name_BirdLife_v9",
        )
        iucn      = _get_cell(row, "IUCN_category", "IUCN_Red_List_category")
        authority = _get_cell(row, "Authority", "Describer")
        color     = genus_palette.get(genus, "#aaaaaa")
        # English-first label reads clearly on the species cladogram; Newick tips
        # use underscores — buildStyles() in JS also maps space↔underscore.
        label     = f"{eng} ({sci})" if eng else sci
        tooltip   = _format_species_tooltip(genus, family, family_eng, eng, iucn, authority)
        meta[sci] = {"color": color, "genus": genus, "label": label, "tooltip": tooltip}
    return meta


def _comb_newick(leaf_names: list[str]) -> str:
    """Flat polytomy Newick — fallback when OpenTree resolution fails."""
    if not leaf_names:
        return "();"
    safe = [re.sub(r"[(),;:\s]+", "_", n).strip("_") for n in leaf_names]
    return "(" + ",".join(safe) + ");"


# ---------------------------------------------------------------------------
# Internal: OpenTree API helpers
# ---------------------------------------------------------------------------

def _ot_post(url: str, payload: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    """POST JSON to an OpenTree endpoint, returning the parsed response."""
    data = json.dumps(payload).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except (urllib.error.URLError, OSError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"OpenTree request failed after {retries} attempts: {exc}") from exc
            wait = 2 ** attempt
            print(f"  [retry {attempt+1}/{retries}] sleeping {wait}s …", file=sys.stderr)
            time.sleep(wait)
    return {}


def _tnrs_match(names: list[str]) -> dict[str, tuple[int, str]]:
    """Match taxon names to OTT IDs via TNRS.

    Returns ``{input_name: (ott_id, matched_name)}`` where *matched_name* is
    the canonical OTT name (may differ from *input_name* in spelling/synonymy).
    """
    if not names:
        return {}
    d = _ot_post(_TNRS_URL, {
        "names": names,
        "do_approximate_matching": True,
        "include_suppressed": False,
    })
    result: dict[str, tuple[int, str]] = {}
    for inp_name, res in zip(names, d.get("results", [])):
        matches = res.get("matches", [])
        if not matches:
            continue
        # Prefer exact matches; fall back to first approximate match
        best = next((m for m in matches if not m.get("is_approximate_match")), matches[0])
        taxon = best["taxon"]
        result[inp_name] = (taxon["ott_id"], taxon["name"])
    return result


def _induced_subtree(ott_ids: list[int]) -> tuple[str, dict[str, str]]:
    """Return (newick_str, broken_dict) from OpenTree induced_subtree endpoint."""
    d = _ot_post(_INDUCED_URL, {"ott_ids": ott_ids, "label_format": "name"})
    return d.get("newick", ""), d.get("broken", {})


# ---------------------------------------------------------------------------
# Internal: Newick cleaning
# ---------------------------------------------------------------------------

# Matches leaf names in Newick: a word of [A-Za-z0-9_.-] followed by , ) ; :
_LEAF_PAT = re.compile(r"([A-Za-z][A-Za-z0-9_.\-]+)([:,);])")


def _rename_leaves(newick: str, rename_map: dict[str, str]) -> str:
    """Substitute leaf names in a Newick string using rename_map."""
    def _repl(m: re.Match) -> str:
        return rename_map.get(m.group(1), m.group(1)) + m.group(2)
    return _LEAF_PAT.sub(_repl, newick)


def _strip_internal_labels(newick: str) -> str:
    """Remove all internal node labels from a Newick string.

    Internal node labels appear after a closing paren: ``)[label]``.
    Stripping them is safe for Phylocanvas.gl because all style/label
    information is supplied via the ``styles`` meta dict, not embedded labels.
    It also avoids duplicate-label issues when renamed leaves match pre-existing
    OpenTree internal clade names (e.g. "Accipitriformes").
    """
    # Match ) followed by a label token (may be quoted) up to , ) ; :
    # Quoted labels (may contain any char except '): '...'
    # Unquoted labels: alphanumeric + _ . - only (NO parens or commas)
    return re.sub(r"\)(?:'[^']*'|[A-Za-z0-9_.'\- ]+)(?=[,);:])", ")", newick)


def _suppress_unifurcations(newick: str) -> str:
    """Iteratively collapse ``(X)`` → ``X`` for single-child internal nodes.

    Operates on a newick that has already had internal labels stripped, so
    there is no ambiguity between leaf tokens and internal node tokens.
    """
    # After stripping internal labels, every )(X) group is )(leaf) or )(clade).
    # A unifurcation is (X) where X has no nested parens.
    pat = re.compile(r"\(([^(),;]+)\)")
    prev = None
    while prev != newick:
        prev = newick
        newick = pat.sub(r"\1", newick)
    return newick


# ---------------------------------------------------------------------------
# Internal: AviList helpers
# ---------------------------------------------------------------------------

def _pick_representative_species(df_species, level: str) -> dict[str, str]:
    """Return {level_value: first_scientific_name} in AviList row order."""
    seen: dict[str, str] = {}
    for row in df_species[["Scientific_name", level]].dropna().itertuples(index=False):
        lv = getattr(row, level)
        if lv not in seen:
            seen[lv] = str(row.Scientific_name)
    return seen


def _palette_for_groups(groups: list[str]) -> dict[str, str]:
    return {g: _PALETTE[i % len(_PALETTE)] for i, g in enumerate(groups)}


# ---------------------------------------------------------------------------
# Public: tree builders
# ---------------------------------------------------------------------------

def build_order_tree(
    df_species,
    cache_dir: Path | str,
    force_refresh: bool = False,
) -> tuple[str, dict[str, dict]]:
    """Fetch / return an order-level bird phylogeny from OpenTree.

    Returns
    -------
    newick : str
        Newick string with order names as leaf labels.
    meta : dict[str, dict]
        Mapping ``{order_name: {color, n_species, english, label}}``.

    Results are cached in *cache_dir* as ``order_tree.nwk`` and
    ``order_meta.json`` and reused on subsequent calls.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    nwk_path  = cache_dir / "order_tree.nwk"
    meta_path = cache_dir / "order_meta.json"

    if not force_refresh and nwk_path.exists() and meta_path.exists():
        print(f"[phylo] Using cached order tree ({nwk_path.name})")
        return nwk_path.read_text(encoding="utf-8"), json.loads(meta_path.read_text(encoding="utf-8"))

    rep = _pick_representative_species(df_species, "Order")
    orders = list(rep.keys())
    print(f"[phylo] Matching {len(orders)} representative species for orders …")
    ott_map = _tnrs_match(list(rep.values()))

    order_to_ott: dict[str, int] = {}
    sp_to_order: dict[str, str] = {sp: o for o, sp in rep.items()}
    for sp, (ott_id, _matched) in ott_map.items():
        order = sp_to_order.get(sp)
        if order:
            order_to_ott[order] = ott_id

    print(f"[phylo] Fetching induced subtree for {len(order_to_ott)} orders …")
    newick, broken = _induced_subtree(list(order_to_ott.values()))
    print(f"[phylo] Broken (non-monophyletic in OTL): {len(broken)}")

    # Strip internal node labels first to avoid conflicts with renamed leaves
    # (OpenTree labels clades with order names that would clash after rename).
    newick = _strip_internal_labels(newick)

    # Use the OTT-matched name (not the AviList name) so the rename matches
    # the leaf labels OpenTree uses in its Newick output.
    rename_map: dict[str, str] = {}
    for sp, (ott_id, matched_name) in ott_map.items():
        order = sp_to_order.get(sp)
        if order and order in order_to_ott:
            rename_map[matched_name.replace(" ", "_")] = order

    newick = _rename_leaves(newick, rename_map)
    newick = _suppress_unifurcations(newick)

    ord_palette = _palette_for_groups(orders)
    ord_sp_count = df_species.groupby("Order").size().to_dict()
    try:
        from birds_nb import ORDER_ENGLISH
    except ImportError:
        ORDER_ENGLISH: dict[str, str] = {}

    meta: dict[str, dict] = {}
    for o in orders:
        n   = int(ord_sp_count.get(o, 0))
        eng = ORDER_ENGLISH.get(o, "")
        meta[o] = {
            "color":     ord_palette[o],
            "n_species": n,
            "english":   eng,
            "label":     f"{o} — {eng} ({n:,} sp)" if eng else f"{o} ({n:,} sp)",
        }

    nwk_path.write_text(newick, encoding="utf-8")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[phylo] Cached → {nwk_path}")
    return newick, meta


def build_family_tree(
    df_species,
    cache_dir: Path | str,
    force_refresh: bool = False,
) -> tuple[str, dict[str, dict]]:
    """Fetch / return a family-level bird phylogeny from OpenTree.

    Returns
    -------
    newick : str
        Newick string with family names as leaf labels.
    meta : dict[str, dict]
        Mapping ``{family_name: {order, color, n_species, n_genera, …}}``.
        Each entry includes ``tooltip`` (multi-line hover text), ``label``
        (short Latin family name), ``order_english``, ``family_english``.

    Results are cached in *cache_dir* as ``family_tree.nwk`` and
    ``family_meta.json`` and reused on subsequent calls.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    nwk_path  = cache_dir / "family_tree.nwk"
    meta_path = cache_dir / "family_meta.json"

    if not force_refresh and nwk_path.exists() and meta_path.exists():
        meta_cached = json.loads(meta_path.read_text(encoding="utf-8"))
        if _family_meta_has_hover(meta_cached):
            print(f"[phylo] Using cached family tree ({nwk_path.name})")
            return nwk_path.read_text(encoding="utf-8"), meta_cached
        print("[phylo] Cached family meta missing hover fields — refreshing from AviList …")
        newick_cached = nwk_path.read_text(encoding="utf-8")
        rep = _pick_representative_species(df_species, "Family")
        families = list(rep.keys())
        meta = _family_meta_from_avilist(df_species, families)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[phylo] Updated metadata → {meta_path.name}")
        return newick_cached, meta

    rep = _pick_representative_species(df_species, "Family")
    families = list(rep.keys())

    species_list = list(rep.values())
    ott_map: dict[str, int] = {}
    batch_size = 100
    print(f"[phylo] Matching {len(species_list)} representative species for families …")
    for i in range(0, len(species_list), batch_size):
        batch = species_list[i : i + batch_size]
        ott_map.update(_tnrs_match(batch))
        print(f"  … matched {min(i + batch_size, len(species_list))}/{len(species_list)}", end="\r")
    print()

    sp_to_family: dict[str, str] = {sp: fam for fam, sp in rep.items()}
    family_to_ott: dict[str, int] = {}
    for sp, (ott_id, _matched) in ott_map.items():
        fam = sp_to_family.get(sp)
        if fam:
            family_to_ott[fam] = ott_id

    print(f"[phylo] Fetching induced subtree for {len(family_to_ott)} families …")
    newick, broken = _induced_subtree(list(family_to_ott.values()))
    print(f"[phylo] Broken (non-monophyletic in OTL): {len(broken)}")

    # Strip internal node labels before rename to avoid clade-name conflicts
    newick = _strip_internal_labels(newick)

    # Use OTT matched names for the rename map (avoids spelling mismatches)
    rename_map: dict[str, str] = {}
    for sp, (ott_id, matched_name) in ott_map.items():
        fam = sp_to_family.get(sp)
        if fam and fam in family_to_ott:
            rename_map[matched_name.replace(" ", "_")] = fam

    newick = _rename_leaves(newick, rename_map)
    newick = _suppress_unifurcations(newick)

    meta = _family_meta_from_avilist(df_species, families)

    nwk_path.write_text(newick, encoding="utf-8")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[phylo] Cached → {nwk_path}")
    return newick, meta


def build_family_subtrees(
    df_species,
    cache_dir: Path | str,
    force_refresh: bool = False,
) -> None:
    """Fetch / build per-family species-level phylogenies from OpenTree.

    For each of the ~252 bird families in *df_species*, matches all species to
    OTT IDs via TNRS (batched at 200), fetches the induced subtree from
    OpenTree, cleans the Newick, and writes a compact JSON payload to::

        <cache_dir>/subtrees/<Family>.json

    A summary index is written to ``<cache_dir>/subtrees_index.json``.

    This is a one-time slow operation (~5–15 min for all ~11 k species).
    Results are cached and reused on subsequent calls unless *force_refresh*.

    Per-family JSON schema::

        {
          "newick":     "<Newick string with species as leaves>",
          "meta":       {"Genus species": {"color": "#hex", "label": "...",
                                           "genus": "...", "tooltip": "..."}},
          "n_species":  <int>,
          "n_genera":   <int>,
          "n_resolved": <int>    # species matched by TNRS / used in topology
        }
    """
    import pandas as pd

    cache_dir = Path(cache_dir)
    sub_dir   = cache_dir / "subtrees"
    idx_path  = cache_dir / "subtrees_index.json"

    # Skip entirely if fully cached
    if not force_refresh and idx_path.exists():
        try:
            existing = json.loads(idx_path.read_text(encoding="utf-8"))
            if all((sub_dir / v["file"]).exists() for v in existing.values()):
                print(f"[phylo] Using cached family subtrees ({len(existing)} families in {sub_dir.name}/)")
                return
        except Exception:
            pass

    sub_dir.mkdir(parents=True, exist_ok=True)

    # All AviList species rows (need Scientific_name)
    sp_rows = df_species.dropna(subset=["Scientific_name"])

    # Map family → species list (preserving AviList order)
    fam_to_species: dict[str, list[str]] = {}
    for _, row in sp_rows[["Scientific_name", "Family"]].dropna().iterrows():
        fam_to_species.setdefault(str(row["Family"]), []).append(str(row["Scientific_name"]))

    all_species = list({sp for sps in fam_to_species.values() for sp in sps})
    print(f"[phylo] Matching {len(all_species):,} species via TNRS (batches of 200) …")

    ott_map: dict[str, tuple[int, str]] = {}
    batch_size = 200
    for i in range(0, len(all_species), batch_size):
        batch = all_species[i : i + batch_size]
        ott_map.update(_tnrs_match(batch))
        done = min(i + batch_size, len(all_species))
        print(f"  … {done:,}/{len(all_species):,}", end="\r")
    print()
    print(f"[phylo] TNRS resolved {len(ott_map):,}/{len(all_species):,} species")

    sp_to_ott:     dict[str, int] = {sp: oid for sp, (oid, _)  in ott_map.items()}
    sp_to_matched: dict[str, str] = {sp: mn  for sp, (_, mn)   in ott_map.items()}

    # Family English names
    fam_eng_map: dict[str, str] = {}
    if "Family_English_name" in sp_rows.columns:
        fam_eng_map = (
            sp_rows.drop_duplicates("Family")
            .set_index("Family")["Family_English_name"]
            .map(lambda x: str(x).strip() if pd.notna(x) else "")
            .to_dict()
        )

    # Build a fast species → genus lookup
    sp_to_genus: dict[str, str] = {}
    if "Genus" in sp_rows.columns:
        sp_to_genus = (
            sp_rows.dropna(subset=["Genus"])
            .drop_duplicates("Scientific_name")
            .set_index("Scientific_name")["Genus"]
            .to_dict()
        )

    index: dict[str, dict] = {}
    families = sorted(fam_to_species.keys())

    for fi, family in enumerate(families):
        safe_name  = re.sub(r"[^\w]", "_", family)
        cache_path = sub_dir / f"{safe_name}.json"

        if not force_refresh and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                index[family] = {
                    "file":       f"{safe_name}.json",
                    "n_species":  cached.get("n_species",  0),
                    "n_resolved": cached.get("n_resolved", 0),
                    "n_genera":   cached.get("n_genera",   0),
                }
                continue
            except Exception:
                pass

        species_in_fam  = fam_to_species[family]
        ott_ids_for_fam = [sp_to_ott[sp] for sp in species_in_fam if sp in sp_to_ott]
        n_resolved      = len(ott_ids_for_fam)

        # Assign one palette colour per genus (stable order)
        genera_in_fam = list(dict.fromkeys(
            sp_to_genus.get(sp, sp.split()[0] if " " in sp else sp)
            for sp in species_in_fam
        ))
        genus_palette = {g: _PALETTE[i % len(_PALETTE)] for i, g in enumerate(genera_in_fam)}
        family_eng    = fam_eng_map.get(family, "")
        species_meta  = _species_meta_for_family(df_species, family, family_eng, genus_palette)
        n_genera      = len(genus_palette)

        # Try OpenTree species-level topology (need ≥3 resolved OTT IDs)
        nwk = ""
        if n_resolved >= 3:
            try:
                raw_nwk, _ = _induced_subtree(ott_ids_for_fam)
                if raw_nwk:
                    nwk = _strip_internal_labels(raw_nwk)
                    rename_map: dict[str, str] = {}
                    for sp in species_in_fam:
                        if sp in sp_to_matched:
                            ott_name = sp_to_matched[sp].replace(" ", "_")
                            rename_map[ott_name] = sp.replace(" ", "_")
                    nwk = _rename_leaves(nwk, rename_map)
                    nwk = _suppress_unifurcations(nwk)
            except Exception as exc:
                print(f"\n[phylo] {family}: OpenTree error ({exc}), using comb", file=sys.stderr)

        if not nwk:
            nwk = _comb_newick(species_in_fam)

        payload = {
            "newick":     nwk,
            "meta":       species_meta,
            "n_species":  len(species_in_fam),
            "n_genera":   n_genera,
            "n_resolved": n_resolved,
        }
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        index[family] = {
            "file":       f"{safe_name}.json",
            "n_species":  len(species_in_fam),
            "n_resolved": n_resolved,
            "n_genera":   n_genera,
        }

        if (fi + 1) % 25 == 0 or fi + 1 == len(families):
            print(f"[phylo] {fi + 1}/{len(families)} families done")

    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[phylo] Family subtrees cached → {sub_dir}/")


def load_family_subtrees_inline(cache_dir: Path | str) -> dict[str, dict]:
    """Load all cached per-family subtrees into one in-memory dict.

    Used in notebook *inline* mode where the full subtrees dict is serialised
    directly into the ``<script>`` block inside the iframe srcdoc so no
    network requests are needed at click time.

    Run :func:`build_family_subtrees` once before calling this.
    """
    cache_dir = Path(cache_dir)
    idx_path  = cache_dir / "subtrees_index.json"
    if not idx_path.exists():
        raise FileNotFoundError(
            f"Subtrees index not found at {idx_path}. "
            "Run build_family_subtrees() first."
        )
    index   = json.loads(idx_path.read_text(encoding="utf-8"))
    sub_dir = cache_dir / "subtrees"
    result: dict[str, dict] = {}
    for family, info in index.items():
        fpath = sub_dir / info["file"]
        if fpath.exists():
            result[family] = json.loads(fpath.read_text(encoding="utf-8"))
    print(f"[phylo] Loaded {len(result)} family subtrees for inline mode")
    return result


# ---------------------------------------------------------------------------
# Public: Phylocanvas.gl HTML renderer
# ---------------------------------------------------------------------------

def _build_legend(meta: dict[str, dict]) -> str:
    """Build a compact order-colour legend as an HTML string."""
    order_colors: dict[str, str] = {}
    for m in meta.values():
        order = m.get("order") or ""
        color = m.get("color", "#aaaaaa")
        if not order:
            # For the order tree itself, use the top-level entry
            order = m.get("label", "").split(" ")[0]
            color = m.get("color", "#aaaaaa")
        if order and order not in order_colors:
            order_colors[order] = color

    if not order_colors:
        return ""

    items = "".join(
        f'<span style="display:inline-flex;align-items:center;margin:3px 10px 3px 0;">'
        f'<span style="width:10px;height:10px;border-radius:50%;background:{c};'
        f'flex-shrink:0;margin-right:5px;"></span>'
        f'<span style="font-size:10px;color:#24292f;">{o}</span></span>'
        for o, c in sorted(order_colors.items())
    )
    return (
        f'<details style="background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;'
        f'padding:8px 14px;margin-bottom:6px;">'
        f'<summary style="font-size:12px;font-weight:600;color:#24292f;cursor:pointer;">'
        f'Legend — bird orders (click to expand)</summary>'
        f'<div style="padding-top:8px;line-height:1.9;">{items}</div>'
        f'</details>'
    )


def _phylocanvas_canvas_div(container_id: str, height: int, *, drilldown: bool = False) -> str:
    """Tree mount <div>: plain inner target, or (drilldown) wrapper + inner + path overlay canvas."""
    if not drilldown:
        return (
            f'<div id="{container_id}" '
            f'style="width:100%;height:{height}px;'
            f'background:{_TREE_VIEW_BG_CSS};overflow:hidden;"></div>'
        )
    inner = f"{container_id}-pc"
    return (
        f'<div id="{container_id}" style="position:relative;width:100%;height:{height}px;">'
        f'<div id="{inner}" style="width:100%;height:100%;'
        f'background:{_TREE_VIEW_BG_CSS};overflow:hidden;"></div>'
        f'<canvas id="{container_id}-path-overlay" width="8" height="8" '
        "style=\"position:absolute;left:0;top:0;width:100%;height:100%;"
        'pointer-events:none;z-index:3;"></canvas>'
        "</div>"
    )


def _family_search_rows(meta: dict[str, dict]) -> list[dict[str, str]]:
    """Rows for the family search picker: display label (Latin + optional English) → Newick tip key."""
    rows: list[dict[str, str]] = []
    for tip in sorted(meta.keys(), key=lambda s: s.lower()):
        m = meta.get(tip) or {}
        eng = ""
        raw = m.get("family_english")
        if isinstance(raw, str):
            eng = raw.strip()
        disp = f"{tip} ({eng})" if eng else tip
        rows.append({"display": disp, "tip": tip})
    return rows


def _phylocanvas_family_search_div(container_id: str) -> str:
    """Combobox-style family search (same interaction pattern as the eBird choropleth picker)."""
    sid = f"{container_id}-fam-search"
    lid = f"{container_id}-fam-suggest"
    aid = f"{container_id}-fam-search-all"
    uid = f"{container_id}-fam-search-undo"
    btn = (
        "display:inline-flex;align-items:center;justify-content:center;"
        "padding:8px 11px;font-size:12px;font-weight:600;line-height:1.2;"
        "cursor:pointer;border:1px solid #d0d7de;border-radius:6px;"
        "background:#f6f8fa;color:#24292f;white-space:nowrap;"
        "font-family:inherit;box-sizing:border-box;"
    )
    return (
        '<div id="' + container_id + '-fam-search-wrap" class="phylo-family-picker" '
        'style="font-family:system-ui,Segoe UI,sans-serif;margin:0 0 8px 0;'
        "position:relative;max-width:min(560px,96vw);\">"
        f'<label for="{sid}" style="display:block;font-size:0.82rem;font-weight:600;'
        'color:#24292f;margin-bottom:4px;">'
        "Family <span style=\"font-weight:400;color:#57606a;\">"
        "(type to filter, ↑↓ Enter — "
        '<span style="white-space:nowrap;">All families</span> / '
        '<span style="white-space:nowrap;">Undo</span> buttons, '
        '<span style="white-space:nowrap;">⌘/Ctrl+Z</span> undo)</span></label>'
        '<div style="display:flex;gap:8px;align-items:center;width:100%;">'
        '<div style="flex:1;min-width:0;position:relative;">'
        f'<input id="{sid}" type="text" placeholder="e.g. Paridae, Thraupidae, Parrot…" '
        'autocomplete="off" spellcheck="false" '
        f'role="combobox" aria-autocomplete="list" aria-controls="{lid}" aria-expanded="false" '
        "style=\"width:100%;box-sizing:border-box;padding:8px 10px;"
        "border:1px solid #d0d7de;border-radius:6px;font-size:14px;outline:none;\" />"
        f'<div id="{lid}" role="listbox" aria-label="Family suggestions" '
        "style=\"display:none;position:absolute;left:0;right:0;z-index:100;"
        "margin-top:4px;max-height:min(320px,42vh);overflow-y:auto;"
        "background:#fff;border:1px solid #d0d7de;border-radius:6px;"
        'box-shadow:0 12px 28px rgba(31,35,40,0.18);"></div>'
        "</div>"
        f'<div style="display:flex;flex-direction:column;gap:5px;flex-shrink:0;">'
        f'<button type="button" id="{aid}" aria-label="Show all families, clear highlight" '
        f'style="{btn}">All families</button>'
        f'<button type="button" id="{uid}" aria-label="Undo last family selection" '
        f'style="{btn}background:#fff;">Undo</button>'
        "</div>"
        "</div>"
        "</div>"
    )


def _phylocanvas_bar_div(container_id: str, n_families: int) -> str:
    """Thin header bar shown above the canvas in drilldown mode."""
    title_id = f"{container_id}-dd-title"
    back_id  = f"{container_id}-dd-back"
    return (
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:6px 10px;background:#f6f8fa;border:1px solid #d0d7de;'
        f'border-bottom:none;border-radius:6px 6px 0 0;gap:10px;box-sizing:border-box;">'
        f'<span id="{title_id}" '
        f'style="font:13px/1.4 system-ui,Segoe UI,sans-serif;color:#24292f;'
        f'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        f'All bird families ({n_families}) \u2014 click a family to see its species'
        f'</span>'
        f'<button id="{back_id}" hidden '
        f'style="flex-shrink:0;padding:3px 10px;font-size:12px;cursor:pointer;'
        f'border:1px solid #d0d7de;border-radius:5px;background:#fff;color:#24292f;">'
        f'\u2190 Back to family tree'
        f'</button>'
        f'</div>'
    )


def _phylocanvas_js_source(
    container_id: str,
    newick: str,
    meta: dict[str, dict],
    height: int,
    tree_type: str,
    *,
    family_hover: bool = False,
    drilldown: bool = False,
    subtrees_inline: dict[str, dict] | None = None,
    subtrees_url_base: str | None = None,
    species_tree_type: str = "rectangular",
    external_nwk_url: str | None = None,
    external_meta_url: str | None = None,
) -> str:
    """JavaScript IIFE: load Phylocanvas.gl (CDN) and draw into *container_id*.

    When *drilldown* is True, clicking a family leaf replaces the tree with a
    species-level cladogram for that family.  Data is loaded either from the
    bundled *subtrees_inline* dict (notebook) or via ``fetch()`` from
    *subtrees_url_base* (static page).

    When *external_nwk_url* and *external_meta_url* are both supplied, the
    Newick and meta JSON are **not** inlined as JS literals; instead the IIFE
    fetches them at runtime via ``Promise.all([fetch(...), fetch(...)])``.
    This keeps the generated script small enough for Jekyll to build quickly.
    """
    tt_js    = _TREE_TYPE_MAP.get(tree_type, "Circular")
    sp_tt_js = _TREE_TYPE_MAP.get(species_tree_type, "Rectangular")
    meta_j   = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    nwk_j    = json.dumps(newick, ensure_ascii=False)
    cdn_j    = json.dumps(_PHYLOCANVAS_CDN)
    cid_j    = json.dumps(container_id)
    stroke_j = json.dumps(_TREE_STROKE_RGBA)
    font_j   = json.dumps(_TREE_FONT_RGBA)
    hover_js = "true" if family_hover else "false"
    dd_js    = "true" if drilldown else "false"

    n_fam = len(meta)

    if drilldown and subtrees_inline is not None:
        dd_mode_j     = '"inline"'
        dd_subtrees_j = json.dumps(subtrees_inline, ensure_ascii=False, separators=(",", ":"))
        dd_url_j      = "null"
    elif drilldown and subtrees_url_base:
        dd_mode_j     = '"fetch"'
        dd_subtrees_j = "null"
        dd_url_j      = json.dumps(subtrees_url_base)
    else:
        dd_mode_j     = '"none"'
        dd_subtrees_j = "null"
        dd_url_j      = "null"

    # Initial title shown in the drilldown bar when the family tree is active.
    dd_title_j = json.dumps(
        f"All bird families ({n_fam}) \u2014 click a family to see its species"
    ) if drilldown else '""'

    fs_rows = _family_search_rows(meta) if drilldown else []
    fs_j = json.dumps(fs_rows, ensure_ascii=False, separators=(",", ":"))

    js = f"""(function () {{
  var CONTAINER_ID = {cid_j};
  var NEWICK       = {nwk_j};
  var META         = {meta_j};
  var HEIGHT       = {height};
  var CDN          = {cdn_j};
  var STROKE       = {stroke_j};
  var FONT         = {font_j};
  var LINE_W       = {_TREE_BRANCH_WIDTH};
  var FAMILY_HOVER = {hover_js};
  var DRILLDOWN    = {dd_js};
  var DD_MODE      = {dd_mode_j};
  var DD_URL_BASE  = {dd_url_j};
  var DD_SUBTREES  = {dd_subtrees_j};
  var DD_FAM_TITLE = {dd_title_j};
  var DD_SP_TYPE   = window.phylocanvas ? window.phylocanvas.TreeTypes["{sp_tt_js}"] : "{sp_tt_js}";
  var FAMILY_SEARCH_ROWS = {fs_j};

  // Shared mutable state — updated whenever the active tree changes.
  var _currentTree  = null;
  var _inFamilyMode = true;
  var _activeMeta   = META;
  var _container    = null;
  var _outerWrap    = null;
  var DEF_HI_COL    = [60, 115, 131, 255];
  var DEF_HALO_W    = 4;
  var DEF_HALO_R    = 12;
  var _pathTimer    = null;
  var _pathNodes    = [];
  var _familyPayload = null;
  /** Tip key last highlighted on the family tree ("" = none); used for search undo. */
  var _lastAppliedFamilyTip = "";
  var _famNavHistory = [];

  function buildStyles(meta) {{
    var s = {{}};
    Object.keys(meta).forEach(function (tip) {{
      var m = meta[tip];
      var style = {{
        fillColour:   m.color || "#aaaaaa",
        strokeColour: m.color || "#aaaaaa",
        shape: "circle",
        size:  5,
        label: (m.label !== undefined && m.label !== null && m.label !== "") ? m.label : tip,
      }};
      s[tip] = style;
      // Newick leaves use underscores; AviList meta keys use spaces in binomials.
      var us = tip.replace(/ /g, "_");
      if (us !== tip) s[us] = style;
    }});
    return s;
  }}

  function _metaRowForLeaf(key) {{
    if (!key) return null;
    if (_activeMeta[key]) return _activeMeta[key];
    var spaced = key.replace(/_/g, " ");
    if (spaced !== key && _activeMeta[spaced]) return _activeMeta[spaced];
    return null;
  }}

  // ── Shared tooltip (one DOM element reused for both tree modes) ─────────────
  var _tipEl = null;
  function _ensureTip() {{
    if (_tipEl) return _tipEl;
    _tipEl = document.createElement("div");
    _tipEl.setAttribute("data-phylo-tip", "1");
    _tipEl.style.cssText = [
      "position:fixed","z-index:99999","pointer-events:none","display:none",
      "max-width:min(380px,94vw)","padding:9px 11px",
      "font:12px/1.5 system-ui,Segoe UI,sans-serif","color:#24292f",
      "background:#fff","border:1px solid #d0d7de","border-radius:7px",
      "box-shadow:0 6px 18px rgba(31,35,40,.18)","white-space:pre-wrap",
      "word-break:break-word"
    ].join(";");
    document.body.appendChild(_tipEl);
    return _tipEl;
  }}
  function _hideTip() {{
    if (_tipEl) {{ _tipEl.style.display = "none"; _tipEl.textContent = ""; }}
  }}
  function _showTip(txt, ev) {{
    var tip = _ensureTip();
    tip.textContent = txt;
    tip.style.display = "block";
    var pad = 12, w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(6, Math.min(ev.clientX + pad, window.innerWidth  - w - 6)) + "px";
    tip.style.top  = Math.max(6, Math.min(ev.clientY + pad, window.innerHeight - h - 6)) + "px";
  }}

  // ── Hover handler — bound once, always uses _currentTree / _activeMeta ──────
  var _hoverBound = false;
  function _onHoverMove(ev) {{
    var canvas = _container && _container.querySelector("canvas");
    if (!canvas || !_currentTree || !_currentTree.deck) {{ _hideTip(); return; }}
    var r = canvas.getBoundingClientRect();
    var x = ev.clientX - r.left, y = ev.clientY - r.top;
    if (x < 0 || y < 0 || x > r.width || y > r.height) {{ _hideTip(); return; }}
    var node = null;
    try {{
      var picked = _currentTree.deck.pickObject({{ x: x, y: y }});
      if (picked && typeof _currentTree.pickNodeFromLayer === "function")
        node = _currentTree.pickNodeFromLayer(picked);
    }} catch (e) {{ _hideTip(); return; }}
    if (!node || !node.isLeaf) {{ _hideTip(); return; }}
    var key = node.label || node.id;
    var row = _metaRowForLeaf(key);
    if (!row || !row.tooltip) {{ _hideTip(); return; }}
    _showTip(row.tooltip, ev);
  }}
  function _bindHover(container) {{
    if (_hoverBound) return;
    _hoverBound = true;
    _ensureTip();
    container.addEventListener("pointerleave", _hideTip);
    container.addEventListener("pointermove",  _onHoverMove);
  }}

  // ── Resize handler — bound once, always uses _currentTree ──────────────────
  var _resizeBound = false;
  function _onResize() {{
    if (!_currentTree) return;
    var el = _sizeTargetEl();
    if (!el) return;
    _currentTree.setProps({{ size: {{ width: containerWidth(el), height: HEIGHT }} }});
    if (DRILLDOWN) {{
      _resizePathOverlay();
      _drawPathOverlay();
    }}
  }}
  function _bindResize(container) {{
    if (_resizeBound) return;
    _resizeBound = true;
    window.addEventListener("resize", _onResize);
    if (typeof ResizeObserver !== "undefined") {{
      new ResizeObserver(_onResize).observe(container);
    }}
  }}

  // ── Drilldown click detection (bound once) ──────────────────────────────────
  var _ddBound    = false;
  var _ddPtrStart = null;
  function _bindDrilldown(container) {{
    if (_ddBound) return;
    _ddBound = true;
    container.addEventListener("pointerdown", function (ev) {{
      _ddPtrStart = {{ x: ev.clientX, y: ev.clientY }};
      _hideTip();
    }});
    container.addEventListener("pointerup", function (ev) {{
      if (!DRILLDOWN || !_inFamilyMode || !_ddPtrStart) {{ _ddPtrStart = null; return; }}
      var dx = ev.clientX - _ddPtrStart.x;
      var dy = ev.clientY - _ddPtrStart.y;
      _ddPtrStart = null;
      if (dx * dx + dy * dy > 64) return;   // > 8 px drag — pan gesture, not click
      if (!_currentTree || !_currentTree.deck) return;
      var canvas = container.querySelector("canvas");
      if (!canvas) return;
      var r  = canvas.getBoundingClientRect();
      var cx = ev.clientX - r.left, cy = ev.clientY - r.top;
      var node = null;
      try {{
        var picked = _currentTree.deck.pickObject({{ x: cx, y: cy }});
        if (picked && typeof _currentTree.pickNodeFromLayer === "function")
          node = _currentTree.pickNodeFromLayer(picked);
      }} catch (e) {{ return; }}
      if (!node || !node.isLeaf) return;
      var family = node.label || node.id;
      if (!family) return;
      _enterFamily(family);
    }});
  }}

  // ── Family search + root→tip path overlay (drilldown / family tree only) ───
  var _famSearchBound = false;
  function _sizeTargetEl() {{
    return (DRILLDOWN && _outerWrap) ? _outerWrap : _container;
  }}
  function _pathOverlay() {{
    return document.getElementById(CONTAINER_ID + "-path-overlay");
  }}
  function _stopPathTimer() {{
    if (_pathTimer) {{ clearInterval(_pathTimer); _pathTimer = null; }}
  }}
  function _clearPathOverlay() {{
    var c = _pathOverlay();
    if (!c) return;
    var ctx = c.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, c.width, c.height);
  }}
  function _resizePathOverlay() {{
    var c = _pathOverlay();
    if (!c || !_outerWrap) return;
    var r = _outerWrap.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    var w = Math.max(1, Math.floor(r.width * dpr));
    var h = Math.max(1, Math.floor(r.height * dpr));
    if (c.width !== w || c.height !== h) {{
      c.width = w;
      c.height = h;
    }}
    c.style.width = "100%";
    c.style.height = "100%";
  }}
  function _projectPhylo(tree, node) {{
    if (!tree || typeof tree.projectPoint !== "function" || !node) return null;
    try {{
      var p = tree.projectPoint([node.x, node.y]);
      return (p && p.length >= 2) ? [p[0], p[1]] : null;
    }} catch (e) {{ return null; }}
  }}
  function _projectPhyloXY(tree, x, y) {{
    if (!tree || typeof tree.projectPoint !== "function") return null;
    try {{
      var p = tree.projectPoint([x, y]);
      return (p && p.length >= 2) ? [p[0], p[1]] : null;
    }} catch (e2) {{ return null; }}
  }}
  function _shortAngleDelta(a0, a1) {{
    var d = a1 - a0;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    return d;
  }}
  function _dedupePts2D(pts, eps) {{
    eps = eps || 0.45;
    var out = [];
    for (var i = 0; i < pts.length; i++) {{
      var q = pts[i];
      if (!q) continue;
      if (!out.length) {{ out.push(q); continue; }}
      var p = out[out.length - 1];
      if (Math.hypot(q[0] - p[0], q[1] - p[1]) > eps) out.push(q);
    }}
    return out;
  }}
  /** Phylocanvas TreeTypes values are short strings (e.g. Circular → "cr"). */
  function _treeTypeIs(name) {{
    var TT = window.phylocanvas && window.phylocanvas.TreeTypes;
    var tt = null;
    try {{
      if (_currentTree && _currentTree.props && _currentTree.props.type != null)
        tt = _currentTree.props.type;
      else if (_currentTree && _currentTree.getTreeType)
        tt = _currentTree.getTreeType();
    }} catch (e0) {{}}
    if (tt == null) return false;
    if (TT) {{
      if (name === "Circular"   && tt === TT.Circular) return true;
      if (name === "Rectangular" && tt === TT.Rectangular) return true;
      if (name === "Hierarchical" && tt === TT.Hierarchical) return true;
      if (name === "Radial"     && tt === TT.Radial) return true;
      if (name === "Diagonal"   && tt === TT.Diagonal) return true;
    }}
    var codes = {{ Circular: "cr", Rectangular: "rc", Hierarchical: "hr", Radial: "rd", Diagonal: "dg" }};
    return tt === codes[name];
  }}
  function _nodeAngleRad(n, rx, ry) {{
    if (!n) return null;
    if (n.angle != null && isFinite(n.angle)) return n.angle;
    if (rx == null || ry == null) return null;
    return Math.atan2(n.y - ry, n.x - rx);
  }}
  /** Inner end of child radial on circular trees: (cx,cy) or layout from parent ring + child angle. */
  function _circInnerJunction(n, p, rx, ry) {{
    var ix = n.cx, iy = n.cy;
    if (ix != null && iy != null && isFinite(ix) && isFinite(iy)) {{
      if (Math.hypot(ix - rx, iy - ry) > 1e-4) return [ix, iy];
    }}
    var na = _nodeAngleRad(n, rx, ry);
    if (!p || na == null) return null;
    var pr = Math.hypot(p.x - rx, p.y - ry);
    if (pr < 1e-4) return [rx, ry];
    return [rx + pr * Math.cos(na), ry + pr * Math.sin(na)];
  }}
  /** Build world-space polyline that follows Phylocanvas branch geometry (not chord shortcuts). */
  function _worldPathAlongBranches(chain) {{
    if (!chain || chain.length < 2)
      return chain && chain.length ? [[chain[0].x, chain[0].y]] : [];
    var g = null;
    try {{
      if (_currentTree && _currentTree.getGraphAfterLayout)
        g = _currentTree.getGraphAfterLayout();
    }} catch (e1) {{ g = null; }}
    var root = g && g.root;
    var rx = root ? root.x : 0, ry = root ? root.y : 0;

    if (_treeTypeIs("Rectangular")) {{
      var pr = [];
      for (var ir = 1; ir < chain.length; ir++) {{
        var pa = chain[ir - 1], ch = chain[ir];
        if (!pr.length) pr.push([pa.x, pa.y]);
        pr.push([pa.x, ch.y]);
        pr.push([ch.x, ch.y]);
      }}
      return _dedupePts2D(pr, 0.35);
    }}

    if (_treeTypeIs("Hierarchical")) {{
      var ph = [];
      for (var ih = 1; ih < chain.length; ih++) {{
        var pap = chain[ih - 1], chh = chain[ih];
        if (!ph.length) ph.push([pap.x, pap.y]);
        ph.push([chh.x, pap.y]);
        ph.push([chh.x, chh.y]);
      }}
      return _dedupePts2D(ph, 0.35);
    }}

    if (_treeTypeIs("Circular") && root) {{
      var leaf = chain[chain.length - 1];
      var acc = [];
      var n = leaf;
      while (n.parent) {{
        var p = n.parent;
        acc.push([n.x, n.y]);
        var ij = _circInnerJunction(n, p, rx, ry);
        if (!ij) {{ n = p; continue; }}
        var ix = ij[0], iy = ij[1];
        var innerR = Math.hypot(ix - rx, iy - ry);
        if (innerR > 1e-4) {{
          acc.push([ix, iy]);
          var prx = p.x - rx, pry = p.y - ry;
          var a0 = Math.atan2(iy - ry, ix - rx);
          var pa = _nodeAngleRad(p, rx, ry);
          var a1 = (Math.abs(prx) + Math.abs(pry) < 1e-4)
            ? a0
            : (pa != null ? pa : Math.atan2(pry, prx));
          var d = _shortAngleDelta(a0, a1);
          if (Math.abs(d) > 2e-3) {{
            var segs = Math.max(10, Math.min(96, Math.ceil(Math.abs(d) / (Math.PI / 32))));
            for (var s = 1; s <= segs; s++) {{
              var t = s / segs;
              var a = a0 + d * t;
              acc.push([rx + innerR * Math.cos(a), ry + innerR * Math.sin(a)]);
            }}
          }}
        }}
        n = p;
      }}
      acc.reverse();
      return _dedupePts2D(acc, 0.12);
    }}

    if (_treeTypeIs("Radial") || _treeTypeIs("Diagonal")) {{
      var pr2 = [];
      for (var ir2 = 0; ir2 < chain.length; ir2++) {{
        var nd = chain[ir2];
        pr2.push([nd.x, nd.y]);
      }}
      return _dedupePts2D(pr2, 0.2);
    }}

    return _dedupePts2D(
      chain.map(function (n) {{ return [n.x, n.y]; }}),
      0.2
    );
  }}
  function _drawPathOverlay() {{
    var c = _pathOverlay();
    if (!c || !_currentTree || !_pathNodes.length) return;
    var ctx = c.getContext("2d");
    if (!ctx) return;
    var dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, c.width / dpr, c.height / dpr);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#000";
    ctx.lineWidth = 4;
    var wPts = _worldPathAlongBranches(_pathNodes);
    ctx.beginPath();
    var first = true;
    for (var i = 0; i < wPts.length; i++) {{
      var ppt = _projectPhyloXY(_currentTree, wPts[i][0], wPts[i][1]);
      if (!ppt) continue;
      if (first) {{ ctx.moveTo(ppt[0], ppt[1]); first = false; }}
      else ctx.lineTo(ppt[0], ppt[1]);
    }}
    if (!first) ctx.stroke();
  }}
  function _startPathTimer() {{
    _stopPathTimer();
    if (!DRILLDOWN || !_pathNodes.length) return;
    _pathTimer = setInterval(function () {{ _drawPathOverlay(); }}, 120);
  }}
  function _clearFamilyPathHighlight() {{
    _stopPathTimer();
    _pathNodes = [];
    _clearPathOverlay();
    if (_currentTree && typeof _currentTree.setProps === "function") {{
      try {{
        _currentTree.setProps({{
          selectedIds: [],
          highlightColour: DEF_HI_COL,
          haloWidth: DEF_HALO_W,
          haloRadius: DEF_HALO_R,
        }});
      }} catch (e) {{}}
    }}
  }}
  function _findLeafNodeForTip(tip) {{
    if (!_currentTree || !tip) return null;
    // Phylocanvas.gl does not ship getLeafLabels / getLeafIds on the public bundle;
    // resolve tips via getGraphAfterLayout().leaves (same graph the renderer uses).
    var g = null;
    try {{
      if (typeof _currentTree.getGraphAfterLayout === "function")
        g = _currentTree.getGraphAfterLayout();
    }} catch (e1) {{ g = null; }}
    if (!g || !g.leaves) return null;
    var want = String(tip).trim();
    var wantLo = want.toLowerCase();
    var wantUs = want.replace(/ /g, "_");
    var wantUsLo = wantUs.toLowerCase();
    for (var i = 0; i < g.leaves.length; i++) {{
      var L = g.leaves[i];
      if (!L) continue;
      var lab = L.label != null ? String(L.label) : "";
      var labUs = lab.replace(/ /g, "_");
      if (lab === want || labUs === wantUs) return L;
      if (lab.toLowerCase() === wantLo || labUs.toLowerCase() === wantUsLo) return L;
    }}
    return null;
  }}
  function _chainRootToLeaf(leaf) {{
    var ch = [];
    for (var n = leaf; n; n = n.parent) ch.push(n);
    ch.reverse();
    return ch;
  }}
  function _applyFamilyTip(tip) {{
    if (!DRILLDOWN || !_inFamilyMode) return;
    _clearFamilyPathHighlight();
    if (!tip) {{
      _lastAppliedFamilyTip = "";
      return;
    }}
    if (!_currentTree) {{
      _lastAppliedFamilyTip = "";
      return;
    }}
    var leaf = _findLeafNodeForTip(tip);
    if (!leaf) {{
      _lastAppliedFamilyTip = "";
      return;
    }}
    _pathNodes = _chainRootToLeaf(leaf);
    _resizePathOverlay();
    _drawPathOverlay();
    _startPathTimer();
    try {{
      _currentTree.setProps({{
        selectedIds: [leaf.id],
        highlightColour: [0, 0, 0, 255],
        haloWidth: 6,
        haloRadius: 16,
      }});
    }} catch (e) {{}}
    _lastAppliedFamilyTip = String(tip).trim();
  }}
  function _bindFamilySearch() {{
    if (!DRILLDOWN || _famSearchBound) return;
    _famSearchBound = true;
    var ALL_KEY = "All families";
    var input = document.getElementById(CONTAINER_ID + "-fam-search");
    var panel = document.getElementById(CONTAINER_ID + "-fam-suggest");
    if (!input || !panel) return;
    var btnAll = document.getElementById(CONTAINER_ID + "-fam-search-all");
    var btnUndo = document.getElementById(CONTAINER_ID + "-fam-search-undo");

    var payload = {{}};
    payload[ALL_KEY] = "";
    for (var i = 0; i < FAMILY_SEARCH_ROWS.length; i++) {{
      var row = FAMILY_SEARCH_ROWS[i];
      if (row && row.display) payload[row.display] = row.tip || "";
    }}
    var LABELS = Object.keys(payload);

    function escapeHtml(s) {{
      var d = document.createElement("div");
      d.textContent = s;
      return d.innerHTML;
    }}
    function highlight(label, qt) {{
      if (!qt) return escapeHtml(label);
      var ll = label.toLowerCase();
      var ql = qt.toLowerCase();
      var ii = ll.indexOf(ql);
      if (ii < 0) return escapeHtml(label);
      return escapeHtml(label.slice(0, ii))
        + '<mark style="background:#fff8c5;padding:0 1px;border-radius:2px;">'
        + escapeHtml(label.slice(ii, ii + qt.length)) + "</mark>"
        + escapeHtml(label.slice(ii + qt.length));
    }}
    function buildVisible(q) {{
      var qt = q.trim().toLowerCase();
      if (!qt) {{
        var rest = LABELS.filter(function (l) {{ return l !== ALL_KEY; }})
          .sort(function (a, b) {{ return a.localeCompare(b); }});
        return {{ rows: [ALL_KEY].concat(rest.slice(0, 22)), more: Math.max(0, rest.length - 22) }};
      }}
      var hit = LABELS.filter(function (l) {{ return l.toLowerCase().indexOf(qt) >= 0; }});
      hit.sort(function (a, b) {{
        var ca = a.toLowerCase().indexOf(qt);
        var cb = b.toLowerCase().indexOf(qt);
        if (ca !== cb) return ca - cb;
        return a.localeCompare(b);
      }});
      return {{ rows: hit.slice(0, 80), more: Math.max(0, hit.length - 80) }};
    }}
    var FAM_HIST_MAX = 24;
    function rememberNavState() {{
      _famNavHistory.push({{ v: input.value, tip: _lastAppliedFamilyTip }});
      if (_famNavHistory.length > FAM_HIST_MAX) _famNavHistory.shift();
    }}
    function syncUndoButton() {{
      if (btnUndo) btnUndo.disabled = !_famNavHistory.length;
    }}
    function undoFamilySearchSelection() {{
      if (!_famNavHistory.length) return;
      var prev = _famNavHistory.pop();
      input.value = prev.v != null ? prev.v : "";
      _applyFamilyTip(prev.tip || "");
      closePanel();
      syncUndoButton();
    }}
    function applyByLabel(lbl) {{
      if (!(lbl in payload)) return;
      var tip = payload[lbl];
      _applyFamilyTip(tip);
    }}
    function selectAndApply(lbl) {{
      if (!(lbl in payload)) return;
      var newTip = payload[lbl] != null ? String(payload[lbl]).trim() : "";
      if (input.value === lbl && _lastAppliedFamilyTip === newTip) {{
        panel.style.display = "none";
        input.setAttribute("aria-expanded", "false");
        return;
      }}
      rememberNavState();
      input.value = lbl;
      applyByLabel(lbl);
      panel.style.display = "none";
      input.setAttribute("aria-expanded", "false");
      syncUndoButton();
    }}
    var visible = [];
    var activeIdx = -1;
    function renderList() {{
      var q = input.value;
      var qt = q.trim();
      var built = buildVisible(q);
      visible = built.rows;
      activeIdx = -1;
      var html = "";
      for (var idx = 0; idx < visible.length; idx++) {{
        var lbl = visible[idx];
        html +=
          '<div role="option" tabindex="-1" class="phylo-suggest-row" data-idx="' + idx + '" '
          + 'style="padding:8px 10px;cursor:pointer;font-size:13px;color:#24292f;'
          + 'border-bottom:1px solid #f0f3f6;">' + highlight(lbl, qt) + "</div>";
      }}
      if (built.more > 0) {{
        html += '<div style="padding:7px 10px;font-size:11px;color:#57606a;border-top:1px solid #eaeef2;">'
          + (qt ? ("\u2026" + built.more + " more matches \u2014 refine your search")
                 : ("\u2026and " + built.more + " more families \u2014 keep typing to search"))
          + "</div>";
      }}
      panel.innerHTML = html;
      Array.prototype.forEach.call(panel.querySelectorAll(".phylo-suggest-row"), function (el) {{
        el.addEventListener("mousedown", function (ev) {{
          ev.preventDefault();
          var i = parseInt(el.getAttribute("data-idx"), 10);
          if (i >= 0 && visible[i]) selectAndApply(visible[i]);
        }});
      }});
    }}
    function openPanel() {{
      renderList();
      panel.style.display = "block";
      input.setAttribute("aria-expanded", "true");
    }}
    function closePanel() {{
      panel.style.display = "none";
      input.setAttribute("aria-expanded", "false");
    }}

    input.addEventListener("focus", function () {{ openPanel(); }});
    input.addEventListener("input", function () {{ openPanel(); }});
    input.addEventListener("keydown", function (ev) {{
      if ((ev.ctrlKey || ev.metaKey) && String(ev.key).toLowerCase() === "z" && !ev.shiftKey) {{
        if (_famNavHistory.length > 0) {{
          ev.preventDefault();
          undoFamilySearchSelection();
        }}
        return;
      }}
      if (ev.key === "Backspace" && input.value === "" && !ev.repeat) {{
        if (_famNavHistory.length > 0) {{
          ev.preventDefault();
          undoFamilySearchSelection();
        }}
        return;
      }}
      if (panel.style.display !== "none" && (ev.key === "ArrowDown" || ev.key === "ArrowUp")) {{
        ev.preventDefault();
        if (!visible.length) return;
        if (activeIdx < 0) activeIdx = 0;
        else if (ev.key === "ArrowDown") activeIdx = (activeIdx + 1) % visible.length;
        else activeIdx = (activeIdx - 1 + visible.length) % visible.length;
        var rows = panel.querySelectorAll(".phylo-suggest-row");
        for (var r = 0; r < rows.length; r++) {{
          rows[r].style.background = (r === activeIdx) ? "#f6f8ff" : "#fff";
        }}
      }} else if (ev.key === "Enter") {{
        if (panel.style.display !== "none" && activeIdx >= 0 && visible[activeIdx]) {{
          ev.preventDefault();
          selectAndApply(visible[activeIdx]);
        }} else {{
          var q = input.value.trim();
          var built = buildVisible(q);
          if (built.rows.length === 1) {{
            ev.preventDefault();
            selectAndApply(built.rows[0]);
          }} else if (q && built.rows.length > 0) {{
            // Non-empty query: apply best-ranked suggestion (same order as the list).
            ev.preventDefault();
            selectAndApply(built.rows[0]);
          }}
        }}
      }} else if (ev.key === "Escape") {{
        closePanel();
      }}
    }});
    document.addEventListener("click", function (ev) {{
      var wrap = input.closest(".phylo-family-picker");
      if (wrap && !wrap.contains(ev.target)) closePanel();
    }});
    if (btnAll) {{
      btnAll.addEventListener("click", function () {{ selectAndApply(ALL_KEY); }});
    }}
    if (btnUndo) {{
      btnUndo.addEventListener("click", function () {{ undoFamilySearchSelection(); }});
    }}
    syncUndoButton();
    _familyPayload = payload;
  }}

  function containerWidth(el) {{
    var w = el.clientWidth || el.offsetWidth || 0;
    if (w < 32) w = el.getBoundingClientRect().width || 0;
    return Math.max(w, 560);
  }}

  // Wait until the container has a non-zero width before constructing the
  // PhylocanvasGL instance — otherwise the WebGL canvas renders 0×H and
  // shows up as a black rectangle.
  function whenSized(el, cb, tries) {{
    tries = tries || 0;
    var w = el.clientWidth || el.offsetWidth || 0;
    if (w >= 32) {{ cb(w); return; }}
    if (tries > 60) {{ cb(containerWidth(el)); return; }}
    requestAnimationFrame(function () {{ whenSized(el, cb, tries + 1); }});
  }}

  // ── Core tree factory ───────────────────────────────────────────────────────
  function _makeTree(newick, meta, treeType, showLeafLabels) {{
    return new window.phylocanvas.PhylocanvasGL(_container, {{
      size:               {{ width: containerWidth(_sizeTargetEl()), height: HEIGHT }},
      source:             newick,
      type:               window.phylocanvas.TreeTypes[treeType],
      strokeColour:       STROKE,
      fontColour:         FONT,
      lineWidth:          LINE_W,
      showLabels:         true,
      showLeafLabels:     showLeafLabels,
      alignLabels:        true,
      showInternalLabels: false,
      showBranchLengths:  false,
      interactive:        true,
      styles:             buildStyles(meta),
    }});
  }}

  // ── Drilldown: enter a family's species tree ────────────────────────────────
  function _enterFamily(family) {{
    _clearFamilyPathHighlight();
    _famNavHistory.length = 0;
    var ubDrill = document.getElementById(CONTAINER_ID + "-fam-search-undo");
    if (ubDrill) ubDrill.disabled = true;
    var fw0 = document.getElementById(CONTAINER_ID + "-fam-search-wrap");
    if (fw0) fw0.style.display = "none";
    function _go(payload) {{
      if (!payload || !payload.newick) return;
      try {{ _currentTree.destroy(); }} catch (e) {{}}
      _activeMeta  = payload.meta || {{}};
      _currentTree = _makeTree(payload.newick, _activeMeta, DD_SP_TYPE, true);
      _inFamilyMode = false;
      var titleEl = document.getElementById(CONTAINER_ID + "-dd-title");
      if (titleEl) {{
        var nSp = payload.n_species || 0, nGe = payload.n_genera || 0;
        titleEl.textContent = family + "\u2009\u2014\u2009" + nSp + " species\u2002|\u2002" + nGe + " genera";
      }}
      var backEl = document.getElementById(CONTAINER_ID + "-dd-back");
      if (backEl) backEl.hidden = false;
      _hideTip();
      _resizePathOverlay();
    }}
    if (DD_MODE === "inline") {{
      _go(DD_SUBTREES ? (DD_SUBTREES[family] || null) : null);
    }} else if (DD_MODE === "fetch" && DD_URL_BASE) {{
      fetch(DD_URL_BASE + encodeURIComponent(family) + ".json")
        .then(function (r) {{ return r.ok ? r.json() : null; }})
        .then(_go)
        .catch(function () {{}});
    }}
  }}

  // ── Drilldown: return to the family tree ────────────────────────────────────
  function _enterFamilyTree() {{
    try {{ _currentTree.destroy(); }} catch (e) {{}}
    _activeMeta  = META;
    _currentTree = _makeTree(NEWICK, META, "{tt_js}", !FAMILY_HOVER);
    _inFamilyMode = true;
    var titleEl = document.getElementById(CONTAINER_ID + "-dd-title");
    if (titleEl) titleEl.textContent = DD_FAM_TITLE;
    var backEl = document.getElementById(CONTAINER_ID + "-dd-back");
    if (backEl) backEl.hidden = true;
    _hideTip();
    var fw1 = document.getElementById(CONTAINER_ID + "-fam-search-wrap");
    if (fw1) fw1.style.display = "block";
    _clearFamilyPathHighlight();
    _resizePathOverlay();
    var inp = document.getElementById(CONTAINER_ID + "-fam-search");
    if (inp && inp.value.trim() && _familyPayload) {{
      var v = inp.value.trim();
      if (Object.prototype.hasOwnProperty.call(_familyPayload, v))
        _applyFamilyTip(_familyPayload[v]);
    }}
  }}

  // ── Initial render ──────────────────────────────────────────────────────────
  function renderTree() {{
    try {{
      if (DRILLDOWN) {{
        _outerWrap = document.getElementById(CONTAINER_ID);
        _container = document.getElementById(CONTAINER_ID + "-pc");
        if (!_outerWrap || !_container) {{
          console.error("[phylo] Missing drilldown tree mount:", CONTAINER_ID);
          return;
        }}
      }} else {{
        _outerWrap = null;
        _container = document.getElementById(CONTAINER_ID);
        if (!_container) {{
          console.error("[phylo] Missing container:", CONTAINER_ID);
          return;
        }}
      }}
      if (!window.phylocanvas || !window.phylocanvas.PhylocanvasGL) {{
        console.error("[phylo] Phylocanvas.gl not loaded");
        return;
      }}
      // Re-resolve DD_SP_TYPE now that phylocanvas is loaded
      DD_SP_TYPE = window.phylocanvas.TreeTypes["{sp_tt_js}"] || "{sp_tt_js}";
      whenSized(_sizeTargetEl(), function () {{
        _activeMeta  = META;
        _currentTree = _makeTree(NEWICK, META, "{tt_js}", !FAMILY_HOVER);
        _inFamilyMode = true;
        _bindResize(_sizeTargetEl());
        if (FAMILY_HOVER || DRILLDOWN) _bindHover(_container);
        if (DRILLDOWN) {{
          _bindDrilldown(_container);
          var backEl = document.getElementById(CONTAINER_ID + "-dd-back");
          if (backEl) {{
            backEl.addEventListener("click", function () {{ _enterFamilyTree(); }});
          }}
          _bindFamilySearch();
          _resizePathOverlay();
        }}
      }});
    }} catch (err) {{
      console.error("[phylo] Phylocanvas render error:", err);
    }}
  }}

  function loadAndRender() {{
    if (window.phylocanvas && window.phylocanvas.PhylocanvasGL) {{
      setTimeout(renderTree, 0);
      return;
    }}
    var tag = document.querySelector('script[data-phylocanvas-loader="true"]');
    if (!tag) {{
      tag = document.createElement("script");
      tag.src = CDN;
      tag.async = true;
      tag.setAttribute("data-phylocanvas-loader", "true");
      (document.head || document.documentElement).appendChild(tag);
      tag.addEventListener("load", function () {{ setTimeout(renderTree, 0); }}, {{ once: true }});
      tag.addEventListener("error", function () {{
        console.error("[phylo] Failed to load Phylocanvas.gl from", CDN);
      }});
      return;
    }}
    var n = 0;
    var poll = setInterval(function () {{
      if (window.phylocanvas && window.phylocanvas.PhylocanvasGL) {{
        clearInterval(poll);
        renderTree();
      }} else if (++n > 200) {{
        clearInterval(poll);
        console.error("[phylo] Timeout waiting for Phylocanvas.gl");
      }}
    }}, 50);
  }}

  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", loadAndRender, {{ once: true }});
  }} else {{
    setTimeout(loadAndRender, 0);
  }}
}})();"""

    # External-data mode: strip the inline NEWICK/META literals and replace
    # the synchronous bootstrap with a Promise.all(fetch(...)) bootstrap so
    # that the Jekyll page receives a compact <script> block.
    if external_nwk_url is not None and external_meta_url is not None:
        nwk_url_j  = json.dumps(external_nwk_url)
        meta_url_j = json.dumps(external_meta_url)

        # Remove the large inline literals — replace with uninitialized vars.
        js = js.replace(f"var NEWICK       = {nwk_j};\n", "var NEWICK;\n", 1)
        js = js.replace(f"var META         = {meta_j};\n", "var META;\n", 1)

        # Swap out the synchronous readyState bootstrap for a fetch bootstrap.
        old_boot = (
            '  if (document.readyState === "loading") {\n'
            '    document.addEventListener("DOMContentLoaded", loadAndRender, { once: true });\n'
            '  } else {\n'
            '    setTimeout(loadAndRender, 0);\n'
            '  }\n'
            '})();'
        )
        new_boot = (
            "  Promise.all([\n"
            f"    fetch({nwk_url_j}).then(function(r){{return r.text();}}),\n"
            f"    fetch({meta_url_j}).then(function(r){{return r.json();}})\n"
            "  ]).then(function(res){\n"
            "    NEWICK = res[0];\n"
            "    META   = res[1];\n"
            '    if (document.readyState === "loading") {\n'
            '      document.addEventListener("DOMContentLoaded", loadAndRender, { once: true });\n'
            "    } else {\n"
            "      setTimeout(loadAndRender, 0);\n"
            "    }\n"
            "  }).catch(function(err){\n"
            '    console.error("[phylo] Failed to load tree data:", err);\n'
            "  });\n"
            "})();"
        )
        js = js.replace(old_boot, new_boot, 1)

    return js


def _build_iframe_srcdoc(
    newick: str,
    meta: dict[str, dict],
    container_id: str,
    height: int,
    tree_type: str,
    *,
    family_hover: bool = False,
    drilldown: bool = False,
    subtrees_inline: dict[str, dict] | None = None,
    subtrees_url_base: str | None = None,
    species_tree_type: str = "rectangular",
    external_nwk_url: str | None = None,
    external_meta_url: str | None = None,
) -> str:
    """Self-contained HTML document containing canvas + Phylocanvas.gl + render JS."""
    bar    = _phylocanvas_bar_div(container_id, len(meta)) if drilldown else ""
    search = _phylocanvas_family_search_div(container_id) if drilldown else ""
    canvas = _phylocanvas_canvas_div(container_id, height, drilldown=drilldown)
    js     = _phylocanvas_js_source(
        container_id, newick, meta, height, tree_type,
        family_hover=family_hover,
        drilldown=drilldown,
        subtrees_inline=subtrees_inline,
        subtrees_url_base=subtrees_url_base,
        species_tree_type=species_tree_type,
        external_nwk_url=external_nwk_url,
        external_meta_url=external_meta_url,
    )
    # Drilldown bar needs natural height above the fixed-height canvas; only
    # the canvas itself clips to overflow:hidden.
    body_style = (
        f"html,body{{margin:0;padding:0;background:{_TREE_VIEW_BG_CSS};"
        "font-family:sans-serif;overflow:hidden;}"
        if not drilldown else
        f"html,body{{margin:0;padding:0;background:{_TREE_VIEW_BG_CSS};"
        "font-family:sans-serif;}}"
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<style>{body_style}</style>'
        '</head><body>'
        f'{bar}{search}{canvas}'
        f'<script src="{_PHYLOCANVAS_CDN}"></script>'
        f'<script>{js}</script>'
        '</body></html>'
    )


def display_phylocanvas(
    newick: str,
    meta: dict[str, dict],
    container_id: str,
    height: int = 700,
    tree_type: str = "circular",
    *,
    family_hover: bool = False,
    drilldown: bool = False,
    subtrees_inline: dict[str, dict] | None = None,
    subtrees_url_base: str | None = None,
    species_tree_type: str = "rectangular",
) -> None:
    """Show an interactive Phylocanvas.gl tree in a Jupyter notebook.

    Renders the canvas inside a single sandboxed ``<iframe srcdoc=…>`` so that
    the container DOM, the Phylocanvas.gl bundle and the render script all
    share **one** document context. This avoids the cross-output-iframe
    isolation that breaks the alternative ``display(HTML) + display(Javascript)``
    pattern in VS Code's notebook renderer (where each output gets its own
    sandbox iframe — the JS would then be unable to find the container by id,
    leaving an empty black box).

    The colour legend is rendered outside the iframe so it picks up the
    notebook's normal styling and stays accessible to ``<details>`` toggles.

    Parameters
    ----------
    family_hover
        For family-level trees built with :func:`build_family_tree`, pass
        ``True`` so a **DOM tooltip** follows the pointer over each coloured leaf,
        showing order/family (Latin + English), genus count, and species count.
    drilldown
        When ``True``, clicking a family leaf replaces the tree in-place with a
        species-level cladogram for that family. A *Back* button returns to the
        family tree. Requires either *subtrees_inline* or *subtrees_url_base*.
    subtrees_inline
        Full subtrees dict returned by :func:`load_family_subtrees_inline`.
        Used in the notebook where ``fetch()`` cannot reach local files.
    subtrees_url_base
        Base URL for per-family JSON files (e.g.
        ``"/assets/data-science/avilist/phylogeny/subtrees/"``).
        Used by the static Jekyll page via ``fetch()``.
    species_tree_type
        Phylocanvas tree type for the species-level cladogram.
        Defaults to ``"rectangular"`` (better for tall species lists).
    """
    from html import escape as _esc

    from IPython.display import HTML, display

    # Drilldown bar + family search add vertical space above the canvas iframe.
    iframe_height = height + (225 if drilldown else 0)

    legend = _build_legend(meta)
    srcdoc = _esc(
        _build_iframe_srcdoc(
            newick, meta, container_id, height, tree_type,
            family_hover=family_hover,
            drilldown=drilldown,
            subtrees_inline=subtrees_inline,
            subtrees_url_base=subtrees_url_base,
            species_tree_type=species_tree_type,
            external_nwk_url=None,
            external_meta_url=None,
        ),
        quote=True,
    )
    iframe = (
        f'<iframe srcdoc="{srcdoc}" sandbox="allow-scripts" scrolling="no" '
        f'style="width:100%;min-width:560px;height:{iframe_height}px;border:none;'
        f'border-radius:8px;border:1px solid #d0d7de;background:{_TREE_VIEW_BG_CSS};'
        f'display:block;"></iframe>'
    )
    display(HTML(f'<div style="font-family:sans-serif;">{legend}{iframe}</div>'))


def phylocanvas_html(
    newick: str,
    meta: dict[str, dict],
    container_id: str,
    height: int = 700,
    tree_type: str = "circular",
    *,
    family_hover: bool = False,
    drilldown: bool = False,
    subtrees_inline: dict[str, dict] | None = None,
    subtrees_url_base: str | None = None,
    species_tree_type: str = "rectangular",
    external_nwk_url: str | None = None,
    external_meta_url: str | None = None,
) -> str:
    """Return legend + sandboxed ``<iframe srcdoc=…>`` for Phylocanvas.gl (static sites).

    Uses the **same** iframe + ``srcdoc`` pattern as :func:`display_phylocanvas`
    so the tree, bar, search UI, CDN bundle, and boot script share one document.
    That avoids Jekyll / theme pipelines that drop or reorder inline ``<script>``
    tags in the post body (which would leave an empty white canvas area).

    When the embed must ``fetch()`` same-site assets (drilldown JSON and/or
    *external_nwk_url* / *external_meta_url*), the iframe is sandboxed with
    ``allow-scripts allow-same-origin`` so those requests stay first-party.

    Parameters
    ----------
    newick : str
        Newick tree string with leaf names matching *meta* keys.
    meta : dict
        Per-tip metadata produced by ``build_order_tree`` / ``build_family_tree``.
    container_id : str
        HTML element id for the tree container (must be unique on the page).
    height : int
        Canvas height in pixels.
    tree_type : str
        One of "circular", "radial", "rectangular", "hierarchical".
    drilldown : bool
        When ``True``, clicking a family leaf replaces the tree with a
        species-level cladogram. Requires *subtrees_url_base* for fetch mode.
    subtrees_url_base : str, optional
        Base URL for per-family JSON files served from the static site.
    species_tree_type : str
        Phylocanvas tree type for the species-level cladogram ("rectangular").
    external_nwk_url : str, optional
        If provided together with *external_meta_url*, the Newick string is
        **not** inlined; the browser fetches it from this URL at render time.
        Keeps the Jekyll markdown small (the Newick can be several MB).
    external_meta_url : str, optional
        URL for the meta JSON file; used together with *external_nwk_url*.
    """
    from html import escape as _esc

    legend = _build_legend(meta)
    iframe_height = height + (225 if drilldown else 0)
    needs_same_origin = bool(
        (external_nwk_url and external_meta_url)
        or (drilldown and subtrees_url_base)
    )
    sandbox = (
        "allow-scripts allow-same-origin"
        if needs_same_origin else
        "allow-scripts"
    )
    srcdoc = _esc(
        _build_iframe_srcdoc(
            newick, meta, container_id, height, tree_type,
            family_hover=family_hover,
            drilldown=drilldown,
            subtrees_inline=subtrees_inline,
            subtrees_url_base=subtrees_url_base,
            species_tree_type=species_tree_type,
            external_nwk_url=external_nwk_url,
            external_meta_url=external_meta_url,
        ),
        quote=True,
    )
    iframe = (
        "<!-- phylocanvas-static-embed -->\n"
        f'<iframe srcdoc="{srcdoc}" sandbox="{sandbox}" scrolling="no" '
        f'style="width:100%;min-width:560px;height:{iframe_height}px;border:none;'
        f'border-radius:8px;border:1px solid #d0d7de;background:{_TREE_VIEW_BG_CSS};'
        f'display:block;"></iframe>'
    )
    return f'<div style="font-family:sans-serif;">{legend}{iframe}</div>\n'


def save_static_png(
    newick: str,
    meta: dict[str, dict],
    out_path: Path | str,
    figsize: tuple[float, float] = (14, 14),
    title: str = "",
) -> None:
    """Render a static PNG fallback tree using dendropy + matplotlib.

    The PNG is saved to *out_path* and can be used as a ``<noscript>`` image
    or for archival/preview purposes.
    """
    import dendropy
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Parse tree with dendropy (robust to minor newick quirks)
    tree = dendropy.Tree.get(
        data=newick, schema="newick",
        preserve_underscores=True,
        suppress_internal_node_taxa=False,
    )

    # Assign hex colours to terminal taxa from meta
    def _get_color(name: str) -> str:
        m = meta.get(name, {})
        return m.get("color", "#888888")

    # Build a simple rectangular dendrogram using matplotlib
    leaves = [n for n in tree.leaf_node_iter()]
    n_leaves = len(leaves)

    fig, ax = plt.subplots(figsize=figsize, facecolor="#0d1117")
    ax.set_facecolor("#0d1117")

    # Assign y positions to leaves (top to bottom)
    leaf_y: dict[int, float] = {id(n): n_leaves - 1 - i for i, n in enumerate(leaves)}

    # Compute x positions by distance from root (use node depth as proxy)
    max_depth = max(n.level() for n in tree.nodes())

    def node_x(node) -> float:
        return node.level() / max(max_depth, 1)

    def node_y(node) -> float:
        if node.is_leaf():
            return leaf_y[id(node)]
        ch = list(node.child_nodes())
        return (node_y(ch[0]) + node_y(ch[-1])) / 2 if ch else 0.0

    # Draw branches
    for node in tree.preorder_node_iter():
        nx, ny = node_x(node), node_y(node)
        color = _get_color(node.taxon.label if node.taxon else "")
        if not color or color == "#888888":
            # inherit color from first leaf child
            try:
                first_leaf = next(node.leaf_iter())
                color = _get_color(first_leaf.taxon.label if first_leaf.taxon else "")
            except StopIteration:
                color = "#888888"
        for child in node.child_nodes():
            cx, cy = node_x(child), node_y(child)
            # Elbow: horizontal then vertical
            ax.plot([nx, cx], [ny, ny], color=color, lw=0.6, alpha=0.85)
            ax.plot([cx, cx], [ny, cy], color=color, lw=0.6, alpha=0.85)
        if node.is_leaf() and node.taxon:
            label = node.taxon.label.replace("_", " ")
            ax.text(node_x(node) + 0.005, node_y(node), label,
                    va="center", ha="left", fontsize=max(3.5, 7 - n_leaves / 60),
                    color=color)

    ax.set_xlim(-0.02, 1.35)
    ax.set_ylim(-1, n_leaves)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    if title:
        ax.set_title(title, color="#e0e0e0", fontsize=11, pad=8)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    print(f"[phylo] Saved static PNG → {out_path}")
