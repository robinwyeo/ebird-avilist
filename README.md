# BIRDS — AviList exploration

Jupyter notebooks that explore the global avian checklist **AviList v2025 (11 Jun, extended)**. `notebooks/avilist_birds_explore.ipynb` covers history, taxonomy, evolution, geography, and conservation. `notebooks/RWY_life_list_explore.ipynb` cross-references a personal eBird world life list for completion charts and regional breakdowns.

## Layout

- `data/` — AviList spreadsheet, personal life list CSV, `birds_country_table.tsv`, OpenTree cache under `data/phylogeny/`, and notebook caches (`.cache_avilist.pkl.gz`, `.cache_ebird/`, gitignored).
- `python/` — `birds_nb.py`, `phylo.py`, `ebird_spatial.py` (imported by the notebooks via a short `sys.path` bootstrap).
- `notebooks/` — `avilist_birds_explore.ipynb`, `RWY_life_list_explore.ipynb`.

For one-off Python from the shell (without the notebook bootstrap), use `PYTHONPATH=python` or `cd python` and adjust imports accordingly.

## Data

- `data/AviList-v2025-11Jun-extended.xlsx` — AviList v2025 extended, ~33.7k rows covering every taxonomic rank (order, family, genus, species, subspecies) with authority, range, IUCN status, Cornell/BirdLife/Avibase cross-references, type locality, etc.
- `data/RWY_ebird_world_life_list.csv` — personal eBird world life list (~1.3k species) with location, state/province, and observation date.

## Setup

**eBird API key (choropleth):** the Geography world map downloads per-country species lists from the [eBird API](https://ebird.org/api/keygen). Create a free key, then export `EBIRD_API_KEY` in the shell before starting Jupyter, or configure the same variable for your IDE / kernel. Lists are cached under `data/.cache_ebird/` (gitignored).

Use a local virtualenv (example name `birds_python`):

```bash
cd /path/to/ebird-avilist
python3 -m venv birds_python
source birds_python/bin/activate   # Windows: birds_python\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
python -m ipykernel install --user --name=birds_python --display-name "Python (birds_python)"
```

## Run

The first notebook cell discovers the repo root (looks for `requirements.txt` and `python/birds_nb.py`) and sets `DATA_DIR` to `data/`, so the kernel working directory can be the repo root, `notebooks/`, or another folder under the tree.

```bash
cd /path/to/ebird-avilist
source birds_python/bin/activate
jupyter notebook notebooks/avilist_birds_explore.ipynb
# optional companion:
# jupyter notebook notebooks/RWY_life_list_explore.ipynb
```

Select the **Python (birds_python)** kernel from the Kernel menu, then Run All.

## Publish on robinwyeo.github.io

The website repo contains `scripts/nbconvert_avilist_postprocess.py`, which reads **this** clone and writes `_data_science/ebird-avilist.md` plus assets under `assets/data-science/avilist/` and `images/data-science/avilist/`. If that script hard-codes the notebook filename, point it at `notebooks/avilist_birds_explore.ipynb` after this layout change.

1. Clone [robinwyeo.github.io](https://github.com/robinwyeo/robinwyeo.github.io) and this repo as **siblings** (same parent folder), e.g. `Github/robinwyeo.github.io` and `Github/ebird-avilist`.
2. From the website repo:

   ```bash
   cd /path/to/robinwyeo.github.io
   python scripts/nbconvert_avilist_postprocess.py
   ```

   If `ebird-avilist` is not next to the site repo, set the root explicitly:

   ```bash
   EBIRD_AVILIST_ROOT=/path/to/ebird-avilist python scripts/nbconvert_avilist_postprocess.py
   ```

3. Add YAML front matter to `_data_science/ebird-avilist.md` if nbconvert did not emit it (title, date, `permalink`, tags) so the page appears on `/data-science/` like your other articles.
4. Commit the generated `.md`, images, and `assets/` updates in **robinwyeo.github.io** only; keep notebooks and source data in **ebird-avilist**.

## Stages

This is stage 1: `notebooks/avilist_birds_explore.ipynb` for AviList themes and `notebooks/RWY_life_list_explore.ipynb` for the personal life list crosswalk. Stage 2 ideas include time-calibrated phylogeny from BirdTree/Jetz, BirdLife range polygons, AVONET trait data, and eBird frequency.
