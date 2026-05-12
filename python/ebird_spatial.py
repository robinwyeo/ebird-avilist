"""eBird regional species lists for geography choropleth (country × AviList family).

Uses Cornell eBird API 2.0:
  - ``GET /ref/taxonomy/ebird?fmt=json`` (no key required) — species codes → scientific names
  - ``GET /product/spplist/{region}`` (requires ``X-eBirdApiToken``) — one region code per country

Caches responses under *cache_dir* (default ``.cache_ebird``).

Counts intersect eBird regional checklists with AviList ``Range_countries`` when that field
parses to at least one ISO-3166 alpha-3 code, so escapees and other list-only records do not
inflate countries AviList does not associate with that species. Taxonomy rows with eBird
``category != "species"`` (e.g. hybrids) are excluded from code→binomial mapping.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

ISO3166_URL = (
    "https://raw.githubusercontent.com/lukes/ISO-3166-countries-with-regional-codes/"
    "master/all/all.json"
)
EBIRD_TAXONOMY_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird?fmt=json"
EBIRD_SPPLIST_URL = "https://api.ebird.org/v2/product/spplist/{region}"

_DEFAULT_SLEEP_S = 0.12
_TAXONOMY_MAX_AGE_DAYS = 30
_ISO_JSON = "iso3166_all.json"
_TAXONOMY_JSON = "ebird_taxonomy.json"
_SPPLIST_PREFIX = "spplist_"


def _cache_paths(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)


def _file_age_days(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 86400.0


def _http_get_json(url: str, *, timeout: int = 120) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ebird_spatial/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_iso3_to_iso2(cache_dir: Path, *, force_refresh: bool = False) -> dict[str, str]:
    """Map ISO-3166 alpha-3 → alpha-2 using a cached copy of the lukes ISO-3166 JSON."""
    _cache_paths(cache_dir)
    path = cache_dir / _ISO_JSON
    if not force_refresh and path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        rows = _http_get_json(ISO3166_URL, timeout=120)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    out: dict[str, str] = {}
    for row in rows:
        a2 = row.get("alpha-2")
        a3 = row.get("alpha-3")
        if isinstance(a2, str) and isinstance(a3, str) and len(a2) == 2 and len(a3) == 3:
            out[a3.upper()] = a2.upper()
    return out


def load_ebird_taxonomy(
    cache_dir: Path,
    *,
    force_refresh: bool = False,
    max_age_days: float = _TAXONOMY_MAX_AGE_DAYS,
) -> dict[str, dict[str, Any]]:
    """speciesCode → {sciName, comName, category, ...} for all eBird taxonomy rows."""
    _cache_paths(cache_dir)
    path = cache_dir / _TAXONOMY_JSON
    if (
        not force_refresh
        and path.exists()
        and _file_age_days(path) <= max_age_days
    ):
        return json.loads(path.read_text(encoding="utf-8"))

    rows = _http_get_json(EBIRD_TAXONOMY_URL, timeout=180)
    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row.get("speciesCode")
        if isinstance(code, str) and code:
            by_code[code] = row
    path.write_text(json.dumps(by_code, ensure_ascii=False), encoding="utf-8")
    return by_code


def _norm_binomial(sci: str) -> str:
    if not isinstance(sci, str) or not sci.strip():
        return ""
    main = re.split(r"\s*/\s*", sci.strip(), maxsplit=1)[0].strip()
    parts = re.split(r"\s+", main)
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return parts[0] if parts else ""


def _normalize_spplist_codes(codes: list[Any]) -> tuple[list[str], bool]:
    """Return species codes; repair legacy caches where a JSON array was stored as one string element."""
    if not codes:
        return [], False
    if len(codes) == 1 and isinstance(codes[0], str):
        s = codes[0].strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(parsed, list):
                    out = [
                        str(x).strip()
                        for x in parsed
                        if isinstance(x, (str, int)) and str(x).strip()
                    ]
                    if out:
                        return out, True
    out = [str(c).strip() for c in codes if isinstance(c, str) and c.strip()]
    return out, False


def _parse_spplist_body(text: str) -> list[str]:
    """eBird returns newline-separated species codes or a JSON array (trim, skip blanks)."""
    if not text or not text.strip():
        return []
    text_stripped = text.strip()
    if text_stripped.startswith("["):
        try:
            parsed = json.loads(text_stripped)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, list):
                out = [
                    str(x).strip()
                    for x in parsed
                    if isinstance(x, (str, int)) and str(x).strip()
                ]
                if out:
                    return out
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def fetch_spplist_for_region(
    region: str,
    api_key: str,
    *,
    timeout: int = 90,
) -> list[str]:
    """Fetch species codes for an eBird region (e.g. ``BR``, ``CO``)."""
    url = EBIRD_SPPLIST_URL.format(region=region)
    headers = {"X-eBirdApiToken": api_key}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _parse_spplist_body(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


def load_or_fetch_spplist(
    iso3: str,
    iso2: str,
    cache_dir: Path,
    api_key: str,
    *,
    force_refresh: bool = False,
) -> list[str]:
    path = cache_dir / f"{_SPPLIST_PREFIX}{iso3}.json"
    if not force_refresh and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = list(data.get("codes", []))
        codes, repaired = _normalize_spplist_codes(raw)
        if repaired:
            path.write_text(
                json.dumps({"iso3": iso3, "iso2": iso2, "codes": codes}, ensure_ascii=False),
                encoding="utf-8",
            )
        return codes
    codes = fetch_spplist_for_region(iso2, api_key)
    path.write_text(
        json.dumps({"iso3": iso3, "iso2": iso2, "codes": codes}, ensure_ascii=False),
        encoding="utf-8",
    )
    return codes


def build_choropleth_country_mat(
    df_species: pd.DataFrame,
    iso3_codes: list[str],
    api_key: str | None,
    cache_dir: str | Path,
    *,
    force_refresh: bool = False,
    sleep_s: float = _DEFAULT_SLEEP_S,
) -> dict[str, Any]:
    """Build ``country_mat`` (Family × ISO3) and auxiliary totals from eBird regional lists.

    Parameters
    ----------
    df_species
        AviList species rows; must include ``Scientific_name`` and ``Family``.
    iso3_codes
        ISO-3166 alpha-3 codes in choropleth column order (e.g. from ``birds_nb.COUNTRY_KEYWORDS``).
    api_key
        eBird API token. If missing, reads ``os.environ["EBIRD_API_KEY"]``.

    Returns
    -------
    dict with keys:
        ``country_mat``, ``all_iso``, ``totals_matched``, ``totals_ebird_raw``,
        ``customdata_rows`` (list of [name, raw_n] per ISO3 for Plotly),
        ``iso3_to_iso2``, ``iso3_missing_iso2``, ``iso3_fetch_failed``,
        ``n_codes_unmatched_taxonomy``, ``n_codes_unmatched_avilist``,
        ``n_pairs_range_filtered`` (eBird hits dropped because ``ISO3`` was not
        in AviList ``Range_countries`` when that list was non-empty).
    """
    if api_key is None:
        api_key = os.environ.get("EBIRD_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "eBird API key required: set environment variable EBIRD_API_KEY "
            "(see https://ebird.org/api/keygen )"
        )

    cache_dir = Path(cache_dir)
    _cache_paths(cache_dir)

    iso3_to_iso2 = load_iso3_to_iso2(cache_dir, force_refresh=force_refresh)
    taxonomy = load_ebird_taxonomy(cache_dir, force_refresh=force_refresh)

    # speciesCode → canonical binomial (first two epithets). Use eBird rows with
    # category ``species`` only so slash forms, hybrids, and other non-species
    # nodes do not map to a single binomial incorrectly.
    code_to_binomial: dict[str, str] = {}
    for code, row in taxonomy.items():
        if row.get("category") != "species":
            continue
        sci = row.get("sciName")
        if isinstance(sci, str):
            nb = _norm_binomial(sci)
            if nb:
                code_to_binomial[code] = nb

    sp_rows = (
        df_species[df_species["Taxon_rank"] == "species"]
        .dropna(subset=["Scientific_name", "Family"])
        .copy()
    )
    sp_rows["_binomial"] = sp_rows["Scientific_name"].map(_norm_binomial)
    binomial_to_family = (
        sp_rows.drop_duplicates("_binomial").set_index("_binomial")["Family"].to_dict()
    )

    # When AviList parsed at least one ISO-3 from ``Range``, require that a
    # country appears there before counting the species there. This drops
    # regional-list escapees/provisionals (e.g. hornbills on the U.S. eBird list)
    # while leaving species with unparsed ``Range`` unchanged (still eBird-only).
    binomial_allowed_iso3: dict[str, set[str]] = {}
    if "Range_countries" in sp_rows.columns:
        for bio, rc in zip(sp_rows["_binomial"], sp_rows["Range_countries"]):
            if not bio or not isinstance(rc, list) or not rc:
                continue
            iso_set = {str(x).strip().upper() for x in rc if x and str(x).strip()}
            if not iso_set:
                continue
            binomial_allowed_iso3.setdefault(bio, set()).update(iso_set)

    iso3_missing_iso2: list[str] = []
    iso3_fetch_failed: list[str] = []
    per_iso3_raw: dict[str, int] = {}
    pairs: list[tuple[str, str]] = []  # (Family, ISO3)
    unmatched_tax = 0
    unmatched_avilist = 0
    n_range_filtered = 0

    for iso3 in iso3_codes:
        iso3u = iso3.upper()
        iso2 = iso3_to_iso2.get(iso3u)
        if not iso2:
            iso3_missing_iso2.append(iso3u)
            per_iso3_raw[iso3u] = 0
            continue
        try:
            codes = load_or_fetch_spplist(
                iso3u, iso2, cache_dir, api_key,
                force_refresh=force_refresh,
            )
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            iso3_fetch_failed.append(iso3u)
            per_iso3_raw[iso3u] = 0
            time.sleep(sleep_s)
            continue

        per_iso3_raw[iso3u] = len(codes)
        seen_binomial_country: set[str] = set()
        for code in codes:
            bio = code_to_binomial.get(code)
            if not bio:
                unmatched_tax += 1
                continue
            fam = binomial_to_family.get(bio)
            if fam is None or fam is pd.NA:
                unmatched_avilist += 1
                continue
            allowed = binomial_allowed_iso3.get(bio)
            if allowed and iso3u not in allowed:
                n_range_filtered += 1
                continue
            if bio in seen_binomial_country:
                continue
            seen_binomial_country.add(bio)
            pairs.append((str(fam), iso3u))
        time.sleep(sleep_s)

    if pairs:
        long_df = pd.DataFrame(pairs, columns=["Family", "ISO3"])
        country_mat = long_df.groupby(["Family", "ISO3"]).size().unstack(fill_value=0)
    else:
        country_mat = pd.DataFrame(0, index=[], columns=[], dtype=int)

    all_iso = sorted(iso3_codes)
    for iso in all_iso:
        if iso not in country_mat.columns:
            country_mat[iso] = 0
    country_mat = country_mat.reindex(columns=all_iso, fill_value=0)

    totals_matched = country_mat.sum(axis=0).reindex(all_iso, fill_value=0)
    totals_raw = pd.Series(
        {k: per_iso3_raw.get(k, 0) for k in all_iso}, dtype="int64"
    ).reindex(all_iso, fill_value=0)

    return {
        "country_mat": country_mat,
        "all_iso": all_iso,
        "totals_matched": totals_matched,
        "totals_ebird_raw": totals_raw,
        "iso3_to_iso2": iso3_to_iso2,
        "iso3_missing_iso2": iso3_missing_iso2,
        "iso3_fetch_failed": iso3_fetch_failed,
        "n_codes_unmatched_taxonomy": unmatched_tax,
        "n_codes_unmatched_avilist": unmatched_avilist,
        "n_pairs_range_filtered": n_range_filtered,
    }
