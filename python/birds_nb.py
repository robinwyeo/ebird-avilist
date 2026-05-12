"""Helpers for `notebooks/avilist_birds_explore.ipynb` / `notebooks/RWY_life_list_explore.ipynb`: range keywords, labels, IO."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


def repo_root() -> Path:
    """Directory containing ``requirements.txt`` (repository root)."""
    pkg_dir = Path(__file__).resolve().parent
    for cand in (pkg_dir, pkg_dir.parent, *pkg_dir.parents):
        if (cand / "requirements.txt").exists():
            return cand
    return pkg_dir.parent


def data_dir() -> Path:
    """Spreadsheets, reference tables, caches, and ``phylogeny/`` assets."""
    root = repo_root()
    d = root / "data"
    return d if d.is_dir() else root


ORDER_ENGLISH: dict[str, str] = {
    "Accipitriformes": "Hawks, eagles & relatives",
    "Aegotheliformes": "Owlet-nightjars",
    "Anseriformes": "Ducks, geese & swans",
    "Apodiformes": "Swifts & hummingbirds",
    "Apterygiformes": "Kiwis",
    "Bucerotiformes": "Hornbills & hoopoes",
    "Caprimulgiformes": "Nightjars, nighthawks & allies",
    "Cariamiformes": "Seriemas",
    "Casuariiformes": "Cassowaries & emus",
    "Cathartiformes": "New World vultures",
    "Charadriiformes": "Shorebirds, gulls & auks",
    "Ciconiiformes": "Storks, herons & ibises",
    "Coliiformes": "Mousebirds",
    "Columbiformes": "Pigeons & doves",
    "Coraciiformes": "Kingfishers, bee-eaters & rollers",
    "Cuculiformes": "Cuckoos & allies",
    "Eurypygiformes": "Sunbittern & kagu",
    "Falconiformes": "Falcons & caracaras",
    "Galbuliformes": "Jacamars & puffbirds",
    "Galliformes": "Gamebirds (pheasants, quail, turkeys…)",
    "Gaviiformes": "Loons / divers",
    "Gruiformes": "Cranes, rails & coots",
    "Leptosomiformes": "Cuckoo-roller",
    "Mesitornithiformes": "Mesites",
    "Musophagiformes": "Turacos",
    "Nyctibiiformes": "Potoos",
    "Opisthocomiformes": "Hoatzin",
    "Otidiformes": "Bustards",
    "Passeriformes": "Perching birds / songbirds",
    "Pelecaniformes": "Pelicans, herons & ibises",
    "Phaethontiformes": "Tropicbirds",
    "Phoenicopteriformes": "Flamingos",
    "Piciformes": "Woodpeckers, barbets & toucans",
    "Podargiformes": "Frogmouths",
    "Podicipediformes": "Grebes",
    "Procellariiformes": "Albatrosses, petrels & shearwaters",
    "Psittaciformes": "Parrots & cockatoos",
    "Pterocliformes": "Sandgrouse",
    "Rheiformes": "Rheas",
    "Sphenisciformes": "Penguins",
    "Steatornithiformes": "Oilbird",
    "Strigiformes": "Owls",
    "Struthioniformes": "Ostriches",
    "Suliformes": "Cormorants, boobies & frigatebirds",
    "Tinamiformes": "Tinamous",
    "Trogoniformes": "Trogons & quetzals",
}

CONTINENT_DISPLAY: dict[str, str] = {
    "Africa": "Africa", "Europe": "Europe", "Asia": "Asia",
    "North America": "North America", "South America": "South America",
    "Oceania": "Australia & Pacific islands",
    "Antarctic": "Antarctic & subantarctic islands",
}

COUNTRY_PREFIX_EN: dict[str, str] = {
    "CA": "Canada", "US": "United States", "MX": "Mexico", "GT": "Guatemala", "BZ": "Belize",
    "CR": "Costa Rica", "PA": "Panama", "CU": "Cuba", "JM": "Jamaica", "DO": "Dominican Republic",
    "HT": "Haiti", "BR": "Brazil", "AR": "Argentina", "CL": "Chile", "PE": "Peru", "CO": "Colombia",
    "EC": "Ecuador", "BO": "Bolivia", "PY": "Paraguay", "UY": "Uruguay", "VE": "Venezuela", "GY": "Guyana",
    "SR": "Suriname", "GF": "French Guiana", "GB": "United Kingdom", "IE": "Ireland", "FR": "France",
    "DE": "Germany", "ES": "Spain", "PT": "Portugal", "IT": "Italy", "NL": "Netherlands", "BE": "Belgium",
    "CH": "Switzerland", "AT": "Austria", "SE": "Sweden", "NO": "Norway", "FI": "Finland", "DK": "Denmark",
    "PL": "Poland", "CZ": "Czechia", "SK": "Slovakia", "HU": "Hungary", "RO": "Romania", "BG": "Bulgaria",
    "GR": "Greece", "TR": "Türkiye", "IL": "Israel", "ZA": "South Africa", "KE": "Kenya", "TZ": "Tanzania",
    "UG": "Uganda", "RW": "Rwanda", "NA": "Namibia", "BW": "Botswana", "ZW": "Zimbabwe", "MZ": "Mozambique",
    "AU": "Australia", "NZ": "New Zealand", "JP": "Japan", "CN": "China", "IN": "India", "TH": "Thailand",
    "MY": "Malaysia", "ID": "Indonesia", "PH": "Philippines", "VN": "Vietnam", "TW": "Taiwan", "KR": "Korea",
}

CONTINENT_KEYWORDS = {
    "Africa": [
        "Africa", "Afrotropic", "Afrotropical", "Sahel", "Sahara",
        "Madagascar", "Comoros", "Seychelles", "Mauritius", "Reunion",
        "R\u00e9union", "Socotra", "Ethiopia", "Ethiopian", "Kenya",
        "Tanzania", "Uganda", "Rwanda", "Burundi", "Somalia", "Eritrea",
        "Djibouti", "Sudan", "Chad", "Niger", "Nigeria", "Cameroon",
        "Gabon", "Congo", "Angola", "Zambia", "Zimbabwe", "Botswana",
        "Namibia", "Mozambique", "Malawi", "South Africa", "Lesotho",
        "Eswatini", "Swaziland", "Liberia", "Ghana", "Togo", "Benin",
        "Senegal", "Gambia", "Mali", "Mauritania", "Guinea", "Sierra Leone",
        "Ivory Coast", "C\u00f4te d'Ivoire", "Burkina Faso", "Morocco",
        "Algeria", "Tunisia", "Libya", "Egypt", "Western Sahara",
        "Cape Verde", "S\u00e3o Tom\u00e9", "Principe",
    ],
    "Europe": [
        "Europe", "European", "Palearctic", "Palaearctic", "Britain",
        "British Isles", "Scandinavia", "Iberia", "Iberian", "Mediterranean",
        "Balkan", "Iceland", "Ireland", "Scotland", "Wales", "France",
        "Germany", "Italy", "Spain", "Portugal", "Greece", "Norway",
        "Sweden", "Finland", "Denmark", "Netherlands", "Belgium", "Poland",
        "Ukraine", "Romania", "Bulgaria", "Hungary", "Austria", "Switzerland",
        "Czech", "Slovakia", "Croatia", "Serbia", "Estonia", "Latvia",
        "Lithuania", "Belarus", "Moldova",
    ],
    "Asia": [
        "Asia", "Asian", "Palearctic", "Palaearctic", "Siberia", "Siberian",
        "Himalaya", "Himalayas", "Tibet", "Tibetan", "Indian subcontinent",
        "India", "Sri Lanka", "Nepal", "Bhutan", "Bangladesh", "Pakistan",
        "Afghanistan", "Iran", "Iraq", "Turkey", "Turkish",
        "Syria", "Lebanon", "Israel", "Jordan", "Yemen", "Oman",
        "United Arab Emirates", "Kuwait", "Qatar", "Bahrain", "Saudi Arabia",
        "Indochina", "Southeast Asia", "Japan", "Korea", "China", "Chinese",
        "Mongolia", "Mongolian", "Kazakhstan", "Uzbekistan", "Turkmenistan",
        "Kyrgyzstan", "Tajikistan", "Philippines", "Borneo", "Sumatra",
        "Java", "Sulawesi", "Wallacea", "Wallacean", "Middle East", "Arabia",
        "Arabian", "Caucasus", "Central Asia", "Myanmar", "Burma", "Malaysia",
        "Thailand", "Vietnam", "Laos", "Cambodia", "Singapore", "Brunei",
        "Taiwan", "Russia", "Russian Far East",
    ],
    "North America": [
        "North America", "North American", "Nearctic", "Canada", "Canadian",
        "United States", "Mexico", "Mexican", "Central America", "Central American",
        "West Indies", "Caribbean", "Cuba", "Cuban", "Hispaniola",
        "Dominican Republic", "Haiti", "Jamaica", "Jamaican", "Bahamas",
        "Bahamian", "Greenland", "Alaska", "Alaskan", "Guatemala",
        "Honduras", "Nicaragua", "Costa Rica", "Panama", "Panamanian",
        "Belize", "El Salvador", "Puerto Rico", "Antilles", "Greater Antilles",
        "Lesser Antilles", "Dominica", "Barbados", "Trinidad", "Tobago",
        "Grenada", "St. Lucia", "St. Vincent", "Martinique", "Guadeloupe",
        "Cayman", "Bermuda", "Yucatan", "Yucat\u00e1n",
    ],
    "South America": [
        "South America", "South American", "Neotropic", "Neotropics",
        "Neotropical", "Amazon", "Amazonia", "Amazonian", "Andes", "Andean",
        "Patagonia", "Patagonian", "Brazil", "Brazilian", "Argentina",
        "Argentinian", "Chile", "Chilean", "Peru", "Peruvian", "Ecuador",
        "Ecuadorian", "Colombia", "Colombian", "Venezuela", "Venezuelan",
        "Guiana", "Guyana", "Suriname", "French Guiana", "Paraguay",
        "Paraguayan", "Uruguay", "Uruguayan", "Bolivia", "Bolivian",
        "Galapagos", "Gal\u00e1pagos", "Tierra del Fuego", "Falkland",
        "Atacama",
    ],
    "Oceania": [
        "Oceania", "Australasia", "Australasian", "Australia", "Australian",
        "New Zealand", "New Guinea", "Papua", "Papuan", "Solomon",
        "Solomons", "Fiji", "Fijian", "Samoa", "Samoan", "Tonga", "Tongan",
        "Tasmania", "Tasmanian", "Polynesia", "Polynesian", "Melanesia",
        "Melanesian", "Micronesia", "Micronesian", "Hawaii", "Hawaiian",
        "Vanuatu", "New Caledonia", "Niue", "Cook Islands", "Tuvalu",
        "Kiribati", "Marshall Islands", "Palau", "Nauru", "Tahiti",
        "Society Islands", "Marquesas", "Auckland Islands", "Campbell Island",
        "Lord Howe", "Norfolk Island", "Chatham",
    ],
    "Antarctic": [
        "Antarctic", "Antarctica", "South Georgia", "South Sandwich",
        "sub-Antarctic", "subantarctic", "South Orkney", "South Shetland",
        "Kerguelen", "Heard Island", "Crozet",
    ],
}

ALL_KEYWORDS = {kw: cont for cont, kws in CONTINENT_KEYWORDS.items() for kw in kws}
KEYWORD_PAT = re.compile(
    "|".join(sorted((re.escape(k) for k in ALL_KEYWORDS), key=len, reverse=True)),
    flags=re.IGNORECASE,
)


def _load_country_keywords() -> dict[str, list[str]]:
    """ISO-3166 alpha-3 → [canonical English name, …aliases]. Data: `data/birds_country_table.tsv`."""
    path = data_dir() / "birds_country_table.tsv"
    if not path.exists():
        path = Path(__file__).with_name("birds_country_table.tsv")
    if not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        iso3, rest = line.split("\t", 1)
        iso3 = iso3.strip().upper()
        names = [p.strip() for p in rest.split("|") if p.strip()]
        if iso3 and names:
            out[iso3] = names
    return out


COUNTRY_KEYWORDS: dict[str, list[str]] = _load_country_keywords()
COUNTRY_KEYWORD_TO_ISO3: dict[str, str] = {
    kw: iso3 for iso3, kws in COUNTRY_KEYWORDS.items() for kw in kws
}
ISO3_TO_NAME: dict[str, str] = {iso3: kws[0] for iso3, kws in COUNTRY_KEYWORDS.items()}
_COUNTRY_KEYS_SORTED = sorted(COUNTRY_KEYWORD_TO_ISO3, key=len, reverse=True)
# Word boundaries: short tokens like US/UK/USA must not match inside "various", "focus", "disusal", …
if _COUNTRY_KEYS_SORTED:
    _country_inner = "|".join(re.escape(k) for k in _COUNTRY_KEYS_SORTED)
    COUNTRY_PAT = re.compile(
        r"\b(?:" + _country_inner + r")\b",
        flags=re.IGNORECASE | re.UNICODE,
    )
else:
    COUNTRY_PAT = re.compile("$^")

# When `Range` names the Amazon basin but not every sovereign state, credit all lowland basin
# countries (still an approximation; BirdLife polygons would be exact).
_AMAZON_BASIN_ISO3: frozenset[str] = frozenset(
    {"BRA", "COL", "PER", "ECU", "BOL", "VEN", "GUY", "SUR", "GUF"}
)
_AMAZON_RE = re.compile(r"\bAmazon(?:ia|ian)?\b", re.IGNORECASE)

# Andean cordillera spans these countries; skip imputation for purely Chilean/Argentine Andean
# phrasing or for lowland "east/west of the Andes" summaries (no upland country list).
_N_ANDES_ISO3: frozenset[str] = frozenset({"COL", "PER", "ECU", "BOL", "VEN"})
_ANDES_RE = re.compile(r"\bAndes\b|\bAndean\b", re.IGNORECASE)
_ANDES_IMPUTE_SKIP = re.compile(
    r"east of the Andes|east of Andes|excluding the Andes|west of the Andes|west of Andes",
    re.IGNORECASE,
)
_ANDES_IMPUTE_CORE_SA = re.compile(
    r"\b(?:"
    r"Peru|Peruvian|Colombia|Colombian|Ecuador|Ecuadorian|Bolivia|Bolivian|"
    r"Venezuela|Venezuelan|Brazil|Brazilian"
    r")\b",
    re.IGNORECASE,
)
_CHILE_RE = re.compile(r"\bChile\b|\bChilean\b", re.IGNORECASE)


def continents_in(text: object) -> list[str]:
    if not isinstance(text, str):
        return []
    hits = KEYWORD_PAT.findall(text)
    conts = set()
    for h in hits:
        # map back via case-insensitive key
        for kw, cont in ALL_KEYWORDS.items():
            if kw.lower() == h.lower():
                conts.add(cont)
                break
    return sorted(conts)


def regions_in(text: object) -> list[str]:
    if not isinstance(text, str):
        return []
    hits = KEYWORD_PAT.findall(text)
    return sorted({h.title() for h in hits})


def _andes_imputation_iso3(text: str) -> frozenset[str]:
    """Extra ISO-3 codes inferred from generic Andes wording (see module constants)."""
    if not _ANDES_RE.search(text):
        return frozenset()
    if _ANDES_IMPUTE_SKIP.search(text):
        return frozenset()
    if _CHILE_RE.search(text) and not _ANDES_IMPUTE_CORE_SA.search(text):
        return frozenset()
    return _N_ANDES_ISO3


def countries_in(text: object) -> list[str]:
    """Return sorted ISO-3166 alpha-3 codes for countries / territories in `Range` text.

    Literal country/territory names are matched with word boundaries. When the prose names
    the Amazon basin or the Andes without listing every state, a small fixed set of
    sovereign states is added so the choropleth better reflects shared lowland / cordilleran
    distributions (still not a substitute for range polygons).
    """
    if not isinstance(text, str) or not COUNTRY_KEYWORD_TO_ISO3:
        return []
    iso3: set[str] = set()
    for m in COUNTRY_PAT.findall(text):
        code = COUNTRY_KEYWORD_TO_ISO3.get(m)
        if code is None:
            for kw, c in COUNTRY_KEYWORD_TO_ISO3.items():
                if kw.lower() == m.lower():
                    code = c
                    break
        if code:
            iso3.add(code)
    if _AMAZON_RE.search(text):
        iso3 |= _AMAZON_BASIN_ISO3
    iso3 |= _andes_imputation_iso3(text)
    return sorted(iso3)


def order_label(order: object) -> str:
    o = "" if pd.isna(order) else str(order)
    eng = ORDER_ENGLISH.get(o, "")
    return f"{o} ({eng})" if (o and eng) else (o or "")


def family_label(family: object, english: object) -> str:
    fam = "" if pd.isna(family) else str(family)
    eng = "" if pd.isna(english) else str(english).strip()
    return f"{fam} ({eng})" if eng else fam


def genus_label(genus: object, english_hint: object) -> str:
    g = "" if pd.isna(genus) else str(genus)
    eng = "" if pd.isna(english_hint) else str(english_hint).strip()
    return f"{g} ({eng})" if eng else g


def sp_region_label(code: object) -> str:
    if not isinstance(code, str) or "-" not in code:
        return str(code)
    prefix, sub = code.split("-", 1)
    country = COUNTRY_PREFIX_EN.get(prefix, prefix)
    return f"{code} ({country}: {sub})"


def load_avilist(xlsx: Path, cache: Path) -> pd.DataFrame:
    if cache.exists() and cache.stat().st_mtime > xlsx.stat().st_mtime:
        return pd.read_pickle(cache)
    df = pd.read_excel(xlsx, sheet_name="AviList v2025 extended")
    df.to_pickle(cache)
    return df


def add_genus_common_example(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.sort_values("Scientific_name", kind="stable")
        .groupby("Genus", dropna=False)["English_name_AviList"]
        .agg(lambda ser: next((str(v).strip() for v in ser if pd.notna(v) and str(v).strip()), ""))
        .rename("Genus_common_example")
        .reset_index()
    )
    return df.merge(g, on="Genus", how="left")


def describer_name(val: object) -> str:
    if not isinstance(val, str):
        return ""
    s = re.sub(r",?\s*(\(?\d{4}\)?)\s*$", "", val).strip().strip("()").split(";")[0].strip()
    return s


ISLAND_GROUPS = (
    "Madagascar", "New Zealand", "New Guinea", "Hawaii", "Hawaiian", "Galapagos", "Gal\u00e1pagos",
    "Philippines", "Indonesia", "Borneo", "Sumatra", "Java", "Sulawesi", "Cuba", "Hispaniola", "Jamaica",
    "Caribbean", "Seychelles", "Mauritius", "Reunion", "Comoros", "Socotra", "Fiji", "Solomon",
)


def mentioned_islands(text: object) -> list[str]:
    if not isinstance(text, str):
        return []
    return sorted({g for g in ISLAND_GROUPS if re.search(re.escape(g), text, re.IGNORECASE)})


def sunburst_panzoom_viewport(fig_html: str, gd_id: str, width: int = 900, height: int = 900) -> str:
    """Wrap a Plotly ``pio.to_html(..., div_id=gd_id)`` fragment in a viewport with wheel zoom and left-drag pan.

    Plotly's built-in ``scrollZoom`` / ``dragmode='pan'`` do not apply reliably to sunburst traces; this outer
    transform preserves wedge clicks when the pointer does not move beyond a small drag threshold.
    """
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", gd_id):
        raise ValueError("gd_id must start with a letter and use only letters, digits, hyphen, underscore")
    gid_js = json.dumps(gd_id)
    js = r"""
(function(){
  var GDID = ___GDID_JS___;
  var gd, vp, pz, scale = 1, tx = 0, ty = 0;
  function apply() {
    pz.style.transform = 'translate(' + Math.round(tx) + 'px,' + Math.round(ty) + 'px) scale(' + scale + ')';
  }
  function init() {
    gd = document.getElementById(GDID);
    vp = document.getElementById(GDID + '-vp');
    pz = document.getElementById(GDID + '-pz');
    if (!gd || !vp || !pz) return;
    if (vp.dataset.sunburstPanzoomInit) return;
    vp.dataset.sunburstPanzoomInit = '1';
    var suppress = false, drag = false, sx, sy, stx, sty, moved = false;
    function wheel(e) {
      e.preventDefault();
      var rect = vp.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      var f = (e.deltaY > 0) ? 0.92 : 1.08;
      var ns = Math.max(0.2, Math.min(5, scale * f));
      var wx = (mx - tx) / scale, wy = (my - ty) / scale;
      scale = ns;
      tx = mx - wx * scale;
      ty = my - wy * scale;
      apply();
    }
    vp.addEventListener('wheel', wheel, {passive: false, capture: true});
    vp.addEventListener('pointerdown', function(e) {
      if (e.button !== 0) return;
      suppress = false;
      drag = true;
      moved = false;
      sx = e.clientX;
      sy = e.clientY;
      stx = tx;
      sty = ty;
      vp.style.cursor = 'grabbing';
    });
    function pm(e) {
      if (!drag) return;
      var dx = e.clientX - sx, dy = e.clientY - sy;
      if ((dx * dx + dy * dy) > 36) moved = true;
      if (moved) {
        tx = stx + dx;
        ty = sty + dy;
        apply();
      }
    }
    function pu() {
      if (!drag) return;
      drag = false;
      vp.style.cursor = 'grab';
      var didPan = moved;
      moved = false;
      if (didPan) {
        suppress = true;
        setTimeout(function() { suppress = false; }, 0);
      }
    }
    window.addEventListener('pointermove', pm);
    window.addEventListener('pointerup', pu);
    window.addEventListener('pointercancel', pu);
    vp.addEventListener('click', function(e) {
      if (suppress) {
        e.stopImmediatePropagation();
        e.preventDefault();
      }
    }, true);
    vp.addEventListener('dblclick', function(e) {
      scale = 1;
      tx = 0;
      ty = 0;
      apply();
      e.preventDefault();
      e.stopPropagation();
    }, true);
  }
  function wait() {
    var el = document.getElementById(GDID);
    if (el && el._fullLayout) {
      init();
      return;
    }
    setTimeout(wait, 50);
  }
  wait();
})();
""".replace(
        "___GDID_JS___", gid_js
    )
    return (
        f'<div id="{gd_id}-vp" style="width:{width}px;height:{height}px;overflow:hidden;'
        f'position:relative;cursor:grab">'
        f'<div id="{gd_id}-pz" style="width:100%;height:100%;transform-origin:0 0">'
        f"{fig_html}</div><script>{js}</script></div>"
    )
