"""Personal eBird exports: country partitioning, optional checklist JSON from the API.

Bulk history: My eBird → Download my data → save under ``data/personal_ebird/raw/``.

API (optional): ``GET https://api.ebird.org/v2/product/checklist/view/{subId}`` with
``X-eBirdApiToken`` — same key as ``ebird_spatial`` (``EBIRD_API_KEY``).
"""
from __future__ import annotations

import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from ebird_spatial import (
    _DEFAULT_SLEEP_S,
    load_iso3_to_iso2,
    load_or_fetch_spplist,
)

CHECKLIST_VIEW_URL = "https://api.ebird.org/v2/product/checklist/view/{subId}"

_SUBNATIONAL_CANDIDATES = (
    "S/P",
    "State/Province",
    "State / Province",
    "STATE/PROVINCE",
    "SUBNATIONAL1 CODE",
    "Subnational1 Code",
    "subnational1Code",
    "SUBNATIONAL1_CODE",
)

_COUNTRY_CANDIDATES = (
    "COUNTRY",
    "Country",
    "COUNTRY CODE",
    "Country Code",
    "countryCode",
)


def _strip_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _sniff_sep(path: Path) -> str:
    with path.open("rb") as f:
        sample = f.read(65536)
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        text = sample.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text, delimiters=",\t;")
        return dialect.delimiter
    except csv.Error:
        return "\t" if text.count("\t") > text.count(",") else ","


def load_my_ebird_export(path: Path, *, sep: str | None = None) -> pd.DataFrame:
    """Load a My eBird export or life-list-style CSV (comma or tab)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    use_sep = sep if sep is not None else _sniff_sep(path)
    df = pd.read_csv(path, sep=use_sep, dtype=str, encoding="utf-8", on_bad_lines="warn")
    if df.shape[1] == 1 and use_sep == ",":
        alt = pd.read_csv(path, sep="\t", dtype=str, encoding="utf-8", on_bad_lines="warn")
        if alt.shape[1] > 1:
            df = alt
    return _strip_columns(df)


def find_subnational_column(df: pd.DataFrame) -> str:
    cols = {c: c for c in df.columns}
    for cand in _SUBNATIONAL_CANDIDATES:
        if cand in cols:
            return cand
    lower_map = {c.lower().replace(" ", ""): c for c in df.columns}
    for cand in _SUBNATIONAL_CANDIDATES:
        key = cand.lower().replace(" ", "").replace("/", "")
        if key in lower_map:
            return lower_map[key]
    raise KeyError(
        "No subnational / state column found. Expected one of "
        f"{_SUBNATIONAL_CANDIDATES}. Columns: {list(df.columns)}"
    )


def find_country_column(df: pd.DataFrame) -> str | None:
    for cand in _COUNTRY_CANDIDATES:
        if cand in df.columns:
            return cand
    lower_map = {c.lower().replace(" ", ""): c for c in df.columns}
    for cand in _COUNTRY_CANDIDATES:
        key = cand.lower().replace(" ", "")
        if key in lower_map:
            return lower_map[key]
    return None


def country_series_from_dataframe(df: pd.DataFrame) -> pd.Series:
    """ISO-3166 alpha-2 country codes (eBird-style: CA, US, MX, …)."""
    df = _strip_columns(df)
    cc_col = find_country_column(df)
    if cc_col is not None:
        s = df[cc_col].astype(str).str.strip().str.upper()
        s = s.str.replace(r"[^A-Z]", "", regex=True)
        s = s.where(s.str.len() == 2, other=pd.NA)
        if s.notna().sum() >= max(1, len(df) // 4):
            return s

    sp = find_subnational_column(df)
    parts = df[sp].astype(str).str.strip().str.split("-", n=1, expand=False)
    return parts.str[0].str.upper().str.strip()


def add_country_column(df: pd.DataFrame, *, col_name: str = "country_iso2") -> pd.DataFrame:
    out = _strip_columns(df)
    out[col_name] = country_series_from_dataframe(out)
    return out


def partition_by_country(
    df: pd.DataFrame,
    out_root: str | Path,
    *,
    country_col: str | None = None,
    stem: str = "observations",
    country_col_out: str = "country_iso2",
) -> dict[str, Path]:
    """Write one CSV per country under ``out_root/{CC}/{stem}.csv``."""
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    work = _strip_columns(df)
    if country_col is None:
        work = add_country_column(work, col_name=country_col_out)
        cc_key = country_col_out
    else:
        if country_col not in work.columns:
            raise KeyError(
                f"country_col {country_col!r} not in columns: {list(work.columns)}"
            )
        raw = work[country_col].astype(str).str.strip()
        work = work.copy()
        work[country_col_out] = raw.str.split("-").str[0].str.upper().str[:2]
        cc_key = country_col_out

    written: dict[str, Path] = {}
    for cc, grp in work.groupby(work[cc_key], dropna=True):
        if not isinstance(cc, str) or len(cc) != 2:
            continue
        d = out_root / cc.upper()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{stem}.csv"
        grp.drop(columns=[cc_key], errors="ignore").to_csv(path, index=False)
        written[cc.upper()] = path
    return written


def checklist_summary_rows(df: pd.DataFrame, *, sub_id_col: str | None = None) -> pd.DataFrame:
    """One row per checklist (dedupe by submission id)."""
    work = _strip_columns(df)
    sid_col = sub_id_col
    if sid_col is None:
        for cand in ("SubID", "SUBMISSION ID", "Submission ID", "subId"):
            if cand in work.columns:
                sid_col = cand
                break
    if sid_col is None or sid_col not in work.columns:
        raise KeyError(
            "No submission / SubID column. Expected SubID or Submission ID. "
            f"Columns: {list(work.columns)}"
        )
    work = add_country_column(work)
    return work.drop_duplicates(subset=[sid_col]).reset_index(drop=True)


def fetch_checklist_view_json(
    sub_id: str,
    api_key: str,
    cache_dir: str | Path,
    *,
    force_refresh: bool = False,
    timeout: int = 90,
) -> dict[str, Any]:
    """GET checklist/view JSON; cache raw JSON under *cache_dir* / checklists /."""
    cache_dir = Path(cache_dir)
    safe = str(sub_id).strip().replace("/", "_")
    path = cache_dir / "checklists" / f"{safe}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not force_refresh and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if not isinstance(data, dict):
            raise TypeError(f"Unexpected checklist JSON type: {type(data)}")
        return data

    url = CHECKLIST_VIEW_URL.format(subId=urllib.parse.quote(str(sub_id).strip()))
    req = urllib.request.Request(url, headers={"X-eBirdApiToken": api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            err = json.loads(e.read().decode("utf-8", errors="replace"))
            raise FileNotFoundError(f"Checklist not found: {sub_id!r} — {err}") from e
        raise
    data: Any = json.loads(raw)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        raise TypeError(f"Unexpected checklist JSON type: {type(data)}")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def checklist_observations_table(
    checklist_json: dict[str, Any],
    taxonomy: dict[str, dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Flatten ``obs`` array from checklist JSON into a DataFrame with sciName when taxonomy given."""
    obs = checklist_json.get("obs") or []
    if not isinstance(obs, list):
        return pd.DataFrame()
    rows = [x for x in obs if isinstance(x, dict)]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if taxonomy is None:
        return df
    sci = []
    for code in df.get("speciesCode", pd.Series(dtype=str)).fillna(""):
        row = taxonomy.get(str(code).strip())
        sci.append(row.get("sciName") if isinstance(row, dict) else None)
    df = df.copy()
    df["sciName"] = sci
    return df


def _iso2_to_iso3(cache_dir: Path) -> dict[str, str]:
    i3_i2 = load_iso3_to_iso2(cache_dir, force_refresh=False)
    out: dict[str, str] = {}
    for i3, i2 in i3_i2.items():
        if not isinstance(i2, str) or len(i2) != 2:
            continue
        i2u = i2.upper()
        if i2u not in out:
            out[i2u] = i3.upper()
    return out


def reference_spplists_for_iso2(
    iso2_codes: Iterable[str],
    cache_dir: str | Path,
    api_key: str | None = None,
    *,
    force_refresh: bool = False,
    sleep_s: float = _DEFAULT_SLEEP_S,
) -> dict[str, list[str]]:
    """Species codes per country via ``product/spplist`` (same as choropleth)."""
    if api_key is None:
        api_key = os.environ.get("EBIRD_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set EBIRD_API_KEY (https://ebird.org/api/keygen )")

    cache_dir = Path(cache_dir)
    i2_to_i3 = _iso2_to_iso3(cache_dir)
    out: dict[str, list[str]] = {}
    for raw in iso2_codes:
        iso2 = str(raw).strip().upper()
        if len(iso2) != 2:
            continue
        iso3 = i2_to_i3.get(iso2)
        if not iso3:
            continue
        codes = load_or_fetch_spplist(
            iso3, iso2, cache_dir, api_key, force_refresh=force_refresh
        )
        out[iso2] = codes
        time.sleep(sleep_s)
    return out
