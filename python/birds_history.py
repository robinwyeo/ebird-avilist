"""Personal eBird history: EDA, choropleth, region overlaps, country PCA."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from birds_nb import COUNTRY_KEYWORDS, ISO3_TO_NAME, family_label
from ebird_spatial import build_choropleth_country_mat, load_iso3_to_iso2


def _norm_binomial(sci: object) -> str:
    if not isinstance(sci, str) or not sci.strip():
        return ""
    main = re.split(r"\s*/\s*", sci.strip(), maxsplit=1)[0].strip()
    parts = re.split(r"\s+", main)
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0] if parts else ""


def _sci_col(df: pd.DataFrame) -> str:
    for c in ("Scientific Name", "Scientific_name", "sciName"):
        if c in df.columns:
            return c
    raise KeyError("No scientific name column found")


def _subid_col(df: pd.DataFrame) -> str | None:
    for c in ("SubID", "SUBMISSION ID", "Submission ID", "subId"):
        if c in df.columns:
            return c
    return None


def history_kpis(hist: pd.DataFrame) -> dict[str, Any]:
    """Summary numbers for notebook KPI display."""
    sci_c = _sci_col(hist)
    sid_c = _subid_col(hist)
    out: dict[str, Any] = {
        "n_rows": len(hist),
        "n_checklists": int(hist[sid_c].nunique()) if sid_c else 0,
        "n_locations": int(hist["Location ID"].nunique()) if "Location ID" in hist.columns else 0,
        "n_countries": int(hist["country_iso2"].nunique()) if "country_iso2" in hist.columns else 0,
        "n_species": int(hist[sci_c].map(_norm_binomial).replace("", pd.NA).dropna().nunique()),
    }
    if "Date" in hist.columns:
        d = pd.to_datetime(hist["Date"], errors="coerce")
        out["date_min"] = d.min()
        out["date_max"] = d.max()
    return out


def personal_country_mat(
    hist: pd.DataFrame,
    df_species: pd.DataFrame,
    iso2_to_iso3: dict[str, str],
) -> tuple[pd.DataFrame, pd.Series]:
    """Family × ISO3 counts of distinct species *you* recorded in each country.

    Returns
    -------
    mat
        Rows = Family, columns = ISO-3 alpha-3 codes present in *hist*.
    totals_iso3
        Series indexed by ISO-3: distinct species per country (all families).
    """
    sci_c = _sci_col(hist)
    fam_map = (
        df_species.dropna(subset=["Scientific_name", "Family"])
        .drop_duplicates("Scientific_name")
        .set_index("Scientific_name")["Family"]
        .to_dict()
    )
    work = hist.copy()
    work["_bio"] = work[sci_c].map(_norm_binomial)
    work = work[work["_bio"].astype(str).str.len() > 0]
    if "country_iso2" not in work.columns:
        raise KeyError("hist must have country_iso2 (use ebird_personal.add_country_column)")
    work["_iso3"] = work["country_iso2"].astype(str).str.upper().map(iso2_to_iso3)
    work = work.dropna(subset=["_iso3"])
    work["_fam"] = work["_bio"].map(lambda b: fam_map.get(b))
    work = work.dropna(subset=["_fam"])
    grp = work.groupby(["_fam", "_iso3"], as_index=False)["_bio"].nunique()
    mat = grp.pivot(index="_fam", columns="_iso3", values="_bio").fillna(0).astype(int)
    totals = mat.sum(axis=0).sort_values(ascending=False)
    return mat, totals


def invert_iso3_to_iso2(iso3_to_iso2: dict[str, str]) -> dict[str, str]:
    """First ISO-3 wins for each alpha-2 (stable for choropleth column order)."""
    out: dict[str, str] = {}
    for i3, i2 in iso3_to_iso2.items():
        i2u = str(i2).strip().upper()
        i3u = str(i3).strip().upper()
        if len(i2u) == 2 and len(i3u) == 3 and i2u not in out:
            out[i2u] = i3u
    return out


_GEO_YL_OR_RD = [
    [0.0, "rgb(255,255,204)"],
    [0.125, "rgb(255,237,160)"],
    [0.25, "rgb(254,217,118)"],
    [0.375, "rgb(254,178,76)"],
    [0.5, "rgb(253,141,60)"],
    [0.625, "rgb(252,78,42)"],
    [0.75, "rgb(227,26,28)"],
    [0.875, "rgb(189,0,38)"],
    [1.0, "rgb(128,0,38)"],
]
_geo_cs_eps = 1e-6
_GEO_COLORSCALE = (
    [[0.0, "rgb(230,230,230)"], [_geo_cs_eps, _GEO_YL_OR_RD[0][1]]] + _GEO_YL_OR_RD[1:]
)


def personal_choropleth_html(
    df_species: pd.DataFrame,
    hist: pd.DataFrame,
    family_english: dict[str, str],
    *,
    api_key: str | None,
    cache_dir: str | Path,
    all_iso3: list[str] | None = None,
    div_id: str = "geo-life-choropleth",
) -> str:
    """Return HTML string: family combobox + choropleth (same UX as AviList notebook)."""
    if api_key is None:
        api_key = os.environ.get("EBIRD_API_KEY", "").strip()
    if not api_key:
        return "<p><b>Missing EBIRD_API_KEY</b> — set it to render the personal choropleth.</p>"

    cache_dir = Path(cache_dir)
    if all_iso3 is None:
        all_iso3 = sorted(COUNTRY_KEYWORDS.keys())

    iso3_to_i2 = load_iso3_to_iso2(cache_dir, force_refresh=False)
    iso2_to_i3 = invert_iso3_to_iso2(iso3_to_i2)

    _ebird = build_choropleth_country_mat(
        df_species,
        all_iso3,
        api_key,
        cache_dir,
        force_refresh=False,
    )
    country_mat = _ebird["country_mat"]
    totals_avail = _ebird["totals_matched"].reindex(all_iso3, fill_value=0)
    totals_raw = _ebird["totals_ebird_raw"].reindex(all_iso3, fill_value=0)
    country_names = [ISO3_TO_NAME.get(iso, iso) for iso in all_iso3]

    pmat, personal_totals = personal_country_mat(hist, df_species, iso2_to_i3)
    personal_totals = personal_totals.reindex(all_iso3, fill_value=0)

    def _z_seen_family(family: str) -> np.ndarray:
        """Distinct species *you* recorded in each country for this family."""
        if family not in pmat.index:
            return np.zeros(len(all_iso3), dtype=float)
        return pmat.loc[family].reindex(all_iso3, fill_value=0).values.astype(float)

    family_avail_by_label: dict[str, list[int]] = {}
    for fam in sorted(country_mat.index):
        family_avail_by_label[_label(fam)] = (
            country_mat.loc[fam].reindex(all_iso3, fill_value=0).astype(int).tolist()
        )

    def _label(fam: str) -> str:
        return family_label(fam, family_english.get(fam, ""))

    labels_to_z: dict[str, list[int]] = {
        "All families": personal_totals.astype(int).tolist(),
    }
    for fam in sorted(country_mat.index):
        labels_to_z[_label(fam)] = _z_seen_family(fam).astype(int).tolist()

    hover_cd = []
    for iso3 in all_iso3:
        hover_cd.append(
            [
                country_names[all_iso3.index(iso3)],
                int(personal_totals.get(iso3, 0) or 0),
                int(totals_avail.get(iso3, 0) or 0),
                int(totals_raw.get(iso3, 0) or 0),
            ]
        )

    fig = go.Figure(
        go.Choropleth(
            locations=all_iso3,
            z=personal_totals.values,
            locationmode="ISO-3",
            customdata=hover_cd,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Species you recorded: %{customdata[1]}<br>"
                "Matched AviList × eBird list (all families): %{customdata[2]}<br>"
                "eBird regional list (raw codes): %{customdata[3]}<extra></extra>"
            ),
            colorscale=_GEO_COLORSCALE,
            colorbar_title="species recorded",
            marker_line_color="white",
            marker_line_width=0.3,
        )
    )
    fig.update_layout(
        title="Your species per country — all families (vs AviList × eBird regional list)",
        height=600,
        margin=dict(l=10, r=10, t=60, b=10),
        geo=dict(projection_type="natural earth", showframe=False, showcoastlines=True),
        transition=dict(duration=0),
    )
    fig_html = pio.to_html(fig, include_plotlyjs="cdn", full_html=False, div_id=div_id)
    payload_json = json.dumps(labels_to_z)
    family_avail_json = json.dumps(family_avail_by_label)

    html = f"""
<div class="geo-family-picker" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  margin-bottom: 10px; position: relative; max-width: min(520px, 96vw);">
  <label for="{div_id}-search" style="display:block; font-size: 0.82rem; font-weight: 600; color: #24292f; margin-bottom: 4px;">
    Family <span style="font-weight:400;color:#57606a;">(type to filter, ↑↓ Enter)</span>
  </label>
  <input id="{div_id}-search" type="text"
         placeholder="e.g. Parrot, Thraupidae, Accipitridae…"
         autocomplete="off" spellcheck="false"
         role="combobox" aria-autocomplete="list" aria-controls="{div_id}-suggest" aria-expanded="false"
         style="width: 100%; box-sizing: border-box; padding: 8px 10px;
         border: 1px solid #d0d7de; border-radius: 6px; font-size: 14px; outline: none;" />
  <div id="{div_id}-suggest" role="listbox" aria-label="Family suggestions"
       style="display: none; position: absolute; left: 0; right: 0; z-index: 100;
       margin-top: 4px; max-height: min(320px, 42vh); overflow-y: auto;
       background: #fff; border: 1px solid #d0d7de; border-radius: 6px;
       box-shadow: 0 12px 28px rgba(31,35,40,0.18);"></div>
</div>
{fig_html}
<script>
(function() {{
  const payload = {payload_json};
  const ALL_KEY = "All families";
  const input = document.getElementById("{div_id}-search");
  const panel = document.getElementById("{div_id}-suggest");
  const LABELS = Object.keys(payload);
  const NAMES = {json.dumps(country_names)};
  const AVAIL_ALL = {json.dumps(totals_avail.astype(int).tolist())};
  const RAW_ALL = {json.dumps(totals_raw.astype(int).tolist())};
  const FAM_AVAIL = {family_avail_json};
  let visible = [];
  let activeIdx = -1;

  function escapeHtml(s) {{
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }}

  function highlight(label, qt) {{
    if (!qt) return escapeHtml(label);
    const ll = label.toLowerCase();
    const ql = qt.toLowerCase();
    const i = ll.indexOf(ql);
    if (i < 0) return escapeHtml(label);
    return escapeHtml(label.slice(0, i))
      + '<mark style="background:#fff8c5;padding:0 1px;border-radius:2px;">'
      + escapeHtml(label.slice(i, i + qt.length)) + "</mark>"
      + escapeHtml(label.slice(i + qt.length));
  }}

  function buildVisible(q) {{
    const qt = q.trim().toLowerCase();
    if (!qt) {{
      const rest = LABELS.filter(function (l) {{ return l !== ALL_KEY; }})
        .sort(function (a, b) {{ return a.localeCompare(b); }});
      return {{ rows: [ALL_KEY].concat(rest.slice(0, 22)), more: Math.max(0, rest.length - 22) }};
    }}
    const hit = LABELS.filter(function (l) {{ return l.toLowerCase().indexOf(qt) >= 0; }});
    hit.sort(function (a, b) {{
      const ca = a.toLowerCase().indexOf(qt);
      const cb = b.toLowerCase().indexOf(qt);
      if (ca !== cb) return ca - cb;
      return a.localeCompare(b);
    }});
    return {{ rows: hit.slice(0, 80), more: Math.max(0, hit.length - 80) }};
  }}

  function apply(lbl) {{
    if (!(lbl in payload)) return;
    const z = payload[lbl];
    const famAvail = (lbl === ALL_KEY) ? null : FAM_AVAIL[lbl];
    const cd = [];
    for (let i = 0; i < NAMES.length; i++) {{
      const zv = z[i] || 0;
      const av = famAvail ? (famAvail[i] || 0) : (AVAIL_ALL[i] || 0);
      cd.push([NAMES[i], zv, av, RAW_ALL[i] || 0]);
    }}
    const ht =
      lbl === ALL_KEY
        ? "<b>%{{customdata[0]}}</b><br>Species you recorded: %{{customdata[1]}}<br>Matched AviList×eBird (all families): %{{customdata[2]}}<br>Raw eBird list: %{{customdata[3]}}<extra></extra>"
        : "<b>%{{customdata[0]}}</b><br>Recorded in this family: %{{customdata[1]}}<br>Family on country list (AviList×eBird): %{{customdata[2]}}<br>Raw eBird list: %{{customdata[3]}}<extra></extra>";
    Plotly.restyle(
      "{div_id}",
      {{ z: [z], customdata: [cd], hovertemplate: [ht] }},
      [0]
    );
    const suf = lbl === ALL_KEY ? "all families" : lbl;
    Plotly.relayout("{div_id}", {{
      "title.text": "Your species per country — " + suf,
    }});
  }}

  function selectAndApply(lbl) {{
    input.value = lbl;
    apply(lbl);
    panel.style.display = "none";
    input.setAttribute("aria-expanded", "false");
  }}

  function renderList() {{
    const q = input.value;
    const qt = q.trim();
    const built = buildVisible(q);
    visible = built.rows;
    activeIdx = -1;
    let html = "";
    for (let idx = 0; idx < visible.length; idx++) {{
      const lbl = visible[idx];
      html +=
        '<div role="option" class="geo-suggest-row" data-idx="' +
        idx +
        '" style="padding:8px 12px;cursor:pointer;font-size:13px;line-height:1.4;' +
        'border-bottom:1px solid #f0f3f6;">' +
        highlight(lbl, qt) +
        "</div>";
    }}
    if (built.more > 0) {{
      html +=
        '<div style="padding:7px 12px;font-size:12px;color:#57606a;background:#f6f8fa;' +
        'border-top:1px solid #eaeef2;">' +
        (!qt
          ? "…and " + built.more + " more families — keep typing to search"
          : "…" + built.more + " more matches — refine your search") +
        "</div>";
    }}
    if (!html) {{
      html =
        '<div style="padding:10px 12px;color:#57606a;font-size:13px;">No matching families</div>';
    }}
    panel.innerHTML = html;
    Array.prototype.forEach.call(panel.querySelectorAll(".geo-suggest-row"), function (el) {{
      el.addEventListener("mousedown", function (e) {{ e.preventDefault(); }});
      el.addEventListener("click", function () {{
        const i = parseInt(el.getAttribute("data-idx"), 10);
        const lbl = visible[i];
        if (lbl) selectAndApply(lbl);
      }});
    }});
  }}

  function showPanel() {{
    panel.style.display = "block";
    input.setAttribute("aria-expanded", "true");
    renderList();
  }}

  function hidePanel() {{
    panel.style.display = "none";
    input.setAttribute("aria-expanded", "false");
    activeIdx = -1;
  }}

  input.addEventListener("focus", function () {{ showPanel(); }});
  input.addEventListener("input", function () {{
    showPanel();
    const v = input.value.trim();
    if (v in payload) apply(v);
  }});
  input.addEventListener("change", function () {{
    const v = input.value.trim();
    if (v in payload) apply(v);
  }});
  input.addEventListener("keydown", function (e) {{
    const n = visible.length;
    if (panel.style.display === "none") {{
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {{
        e.preventDefault();
        showPanel();
        if (e.key === "ArrowDown") activeIdx = visible.length ? 0 : -1;
        else activeIdx = visible.length ? visible.length - 1 : -1;
        updateHighlight();
      }}
      return;
    }}
    if (e.key === "ArrowDown") {{
      e.preventDefault();
      if (activeIdx < 0) activeIdx = 0;
      else activeIdx = Math.min(activeIdx + 1, n - 1);
      updateHighlight();
    }} else if (e.key === "ArrowUp") {{
      e.preventDefault();
      if (activeIdx < 0) activeIdx = n - 1;
      else activeIdx = Math.max(activeIdx - 1, 0);
      updateHighlight();
    }} else if (e.key === "Enter") {{
      if (activeIdx >= 0 && visible[activeIdx]) {{
        e.preventDefault();
        selectAndApply(visible[activeIdx]);
      }}
    }} else if (e.key === "Escape") {{
      hidePanel();
    }}
  }});

  function updateHighlight() {{
    const rows = panel.querySelectorAll(".geo-suggest-row");
    for (let i = 0; i < rows.length; i++) {{
      rows[i].style.background = i === activeIdx ? "#ddf4ff" : "";
    }}
    if (activeIdx >= 0 && rows[activeIdx]) {{
      rows[activeIdx].scrollIntoView({{ block: "nearest" }});
    }}
  }}

  document.addEventListener("click", function (e) {{
    const wrap = input.closest(".geo-family-picker");
    if (wrap && !wrap.contains(e.target)) hidePanel();
  }});
}})();
</script>
"""
    return html


def summarise_history(hist: pd.DataFrame) -> dict[str, Any]:
    """Alias for :func:`history_kpis` (notebook-facing name)."""
    return history_kpis(hist)


def _species_sets_by_country(hist: pd.DataFrame, iso2s: frozenset[str]) -> dict[str, set[str]]:
    sci_c = _sci_col(hist)
    work = hist[hist["country_iso2"].astype(str).str.upper().isin(iso2s)].copy()
    out: dict[str, set[str]] = {c: set() for c in iso2s}
    for _, r in work.iterrows():
        cc = str(r["country_iso2"]).upper().strip()
        bio = _norm_binomial(r[sci_c])
        if cc in out and bio:
            out[cc].add(bio)
    return out


def _venn3_regions(a: set[str], b: set[str], c: set[str]) -> dict[str, tuple[set[str], str]]:
    """Seven Venn regions for sets A,B,C (in order). Keys: only_a, only_b, only_c, ab, ac, bc, abc."""
    ab_only = (a & b) - c
    ac_only = (a & c) - b
    bc_only = (b & c) - a
    abc = a & b & c
    only_a = a - b - c
    only_b = b - a - c
    only_c = c - a - b
    return {
        "only_a": (only_a, "only A"),
        "only_b": (only_b, "only B"),
        "only_c": (only_c, "only C"),
        "ab": (ab_only, "A ∩ B (not C)"),
        "ac": (ac_only, "A ∩ C (not B)"),
        "bc": (bc_only, "B ∩ C (not A)"),
        "abc": (abc, "A ∩ B ∩ C"),
    }


def region_overlap_figures(
    hist: pd.DataFrame,
    iso2_region: frozenset[str],
    *,
    region_title: str,
) -> tuple[go.Figure, go.Figure]:
    """3-circle style summary for top-3 countries + UpSet-style intersection bars for all."""
    sets_map = _species_sets_by_country(hist, iso2_region)
    # Top 3 by species count
    ranked = sorted(sets_map.items(), key=lambda kv: len(kv[1]), reverse=True)
    top3 = [x[0] for x in ranked[:3]]
    if len(top3) < 3:
        pad = [c for c in sorted(iso2_region) if c not in top3]
        for c in pad:
            top3.append(c)
            if len(top3) == 3:
                break
    A, B, C = top3[0], top3[1], top3[2]
    a, b, c = sets_map[A], sets_map[B], sets_map[C]
    regions = _venn3_regions(a, b, c)

    # --- Venn figure (simplified: table of regions + bar sizes) ---
    labels_v = []
    sizes_v = []
    hover_v = []
    for key, (sp_set, desc) in regions.items():
        labels_v.append(f"{desc}<br><sub>{A},{B},{C}</sub>")
        sizes_v.append(len(sp_set))
        sample = ", ".join(sorted(sp_set)[:8])
        if len(sp_set) > 8:
            sample += "…"
        hover_v.append([f"n={len(sp_set)}<br>{sample}"])

    fig_venn = go.Figure(
        data=[
            go.Bar(
                y=labels_v,
                x=sizes_v,
                orientation="h",
                marker_color="#3d7ea0",
                customdata=hover_v,
                hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>",
            )
        ]
    )
    fig_venn.update_layout(
        title=f"{region_title} — species overlap (top-3 countries by richness: {A}, {B}, {C})",
        xaxis_title="species count in region",
        height=max(360, len(labels_v) * 44 + 120),
        margin=dict(l=200, r=20, t=60, b=40),
    )

    # --- UpSet: pattern frozenset(iso2) -> species ---
    all_iso = sorted(iso2_region)
    sci_c = _sci_col(hist)
    work = hist[hist["country_iso2"].astype(str).str.upper().isin(iso2_region)].copy()
    sp_to_cc: dict[str, set[str]] = defaultdict(set)
    for _, r in work.iterrows():
        bio = _norm_binomial(r[sci_c])
        if not bio:
            continue
        cc = str(r["country_iso2"]).upper().strip()
        if cc in iso2_region:
            sp_to_cc[bio].add(cc)
    agg: dict[frozenset[str], list[str]] = defaultdict(list)
    for bio, cset in sp_to_cc.items():
        agg[frozenset(cset)].append(bio)
    rows = sorted(agg.items(), key=lambda kv: len(kv[1]), reverse=True)

    y_labels = []
    x_vals = []
    htext = []
    for pat, spp in rows:
        if not pat:
            continue
        cc_list = "+".join(sorted(pat))
        y_labels.append(f"{cc_list}  (n={len(spp)})")
        x_vals.append(len(spp))
        htext.append("<br>".join(sorted(spp)[:12]) + ("…" if len(spp) > 12 else ""))

    pairs = sorted(zip(y_labels, x_vals, htext), key=lambda t: t[1], reverse=True)
    y_ord = [p[0] for p in pairs]
    x_ord = [p[1] for p in pairs]
    h_ord = [p[2] for p in pairs]
    cd_up = [[a, b] for a, b in zip(y_ord, h_ord)]

    fig_up = go.Figure(
        go.Bar(
            y=y_ord,
            x=x_ord,
            orientation="h",
            marker_color="#d83333",
            customdata=cd_up,
            hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
        )
    )
    fig_up.update_layout(
        title=f"{region_title} — UpSet-style intersections (all {len(all_iso)} countries)",
        xaxis_title="distinct species in that exact country combination",
        height=max(420, len(y_ord) * 22 + 140),
        yaxis=dict(categoryorder="total descending"),
        margin=dict(l=280, r=20, t=60, b=40),
    )
    return fig_venn, fig_up


_ISO2_CONTINENT: dict[str, str] = {
    "BO": "South America",
    "PE": "South America",
    "CL": "South America",
    "GD": "North America",
    "MX": "North America",
    "US": "North America",
    "CA": "North America",
    "ID": "Asia",
    "KH": "Asia",
    "LA": "Asia",
    "MY": "Asia",
    "TH": "Asia",
    "VN": "Asia",
    "JP": "Asia",
    "TW": "Asia",
}


def country_pca(
    hist: pd.DataFrame,
    _df_species: pd.DataFrame,
    *,
    min_species_per_country: int = 5,
    n_components: int = 5,
) -> tuple[go.Figure, go.Figure]:
    """PCA on countries × species presence (0/1).

    *_df_species* reserved for future enrichment (e.g. trait-based features).
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    sci_c = _sci_col(hist)
    work = hist.dropna(subset=["country_iso2"]).copy()
    work["_bio"] = work[sci_c].map(_norm_binomial)
    work = work[work["_bio"].astype(str).str.len() > 0]
    work["cc"] = work["country_iso2"].astype(str).str.upper().str.strip()
    # wide: rows country, cols species
    wide = work.groupby(["cc", "_bio"]).size().unstack(fill_value=0)
    wide = (wide > 0).astype(int)
    # drop sparse countries
    n_per = wide.sum(axis=1)
    wide = wide.loc[n_per >= min_species_per_country]
    if wide.shape[0] < 2 or wide.shape[1] < 2:
        empty = go.Figure()
        empty.update_layout(title="PCA — need ≥2 countries with enough species")
        return empty, empty

    X = wide.values.astype(float)
    scaler = StandardScaler(with_mean=True, with_std=True)
    Xs = scaler.fit_transform(X)
    pca = PCA(n_components=min(n_components, Xs.shape[0], Xs.shape[1]))
    Z = pca.fit_transform(Xs)
    evr = pca.explained_variance_ratio_

    conti = [_ISO2_CONTINENT.get(cc, "Other") for cc in wide.index]

    hover_lines = []
    load = pca.components_.T  # shape (n_features, n_comp)
    species = list(wide.columns)
    for i, cc in enumerate(wide.index):
        vec = X[i]
        contrib = np.abs(load[:, 0] * vec) + np.abs(load[:, 1] * vec)
        top_idx = np.argsort(-contrib)[:5]
        top_sp = [species[j] for j in top_idx]
        hover_lines.append("<br>".join(top_sp))

    fig_sc = go.Figure()
    countries = list(wide.index)
    n_sp = wide.sum(axis=1).values.astype(float)
    sizes = 10 + n_sp / max(n_sp.max() / 25.0, 1.0)
    for cont in sorted(set(conti)):
        idx = [i for i, c in enumerate(conti) if c == cont]
        fig_sc.add_trace(
            go.Scatter(
                x=Z[idx, 0],
                y=Z[idx, 1],
                mode="markers+text",
                text=[countries[i] for i in idx],
                textposition="top center",
                name=cont,
                marker=dict(size=[sizes[i] for i in idx]),
                customdata=[[hover_lines[i]] for i in idx],
                hovertemplate=(
                    "<b>%{text}</b><br>PC1=%{x:.2f} PC2=%{y:.2f}<br>%{customdata[0]}<extra></extra>"
                ),
            )
        )
    fig_sc.update_layout(
        title="PCA of countries (rows) by species you recorded (standardised presence/absence)",
        xaxis_title=f"PC1 ({evr[0]*100:.1f}% var)",
        yaxis_title=f"PC2 ({evr[1]*100:.1f}% var)" if len(evr) > 1 else "PC2",
        height=520,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    k = min(5, len(evr))
    fig_ev = go.Figure(go.Bar(x=[f"PC{i+1}" for i in range(k)], y=evr[:k] * 100, marker_color="#457B9D"))
    fig_ev.update_layout(title="PCA scree (% variance)", yaxis_title="% variance", height=320)
    return fig_sc, fig_ev
