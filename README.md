# DropScore

Address lifecycle tool for botting ops. Generates format variants from base
addresses, tracks which addresses work across drops, and surfaces the best
performers via Bayesian scoring.

## Web App (FastAPI)

```bash
cd /Users/hotdog/dropscore
python3 -m uvicorn app.main:app --port 9999
```

Then open http://localhost:9999.

Pages:
- **Dashboard** — library stats, top performers at a glance
- **Generate** — paste base addresses, pick retailer, get variants
- **Import Results** — paste what worked/didn't after a drop → scores update
- **Library** — full table, filter by retailer/status/score, sortable
- **Export CSV** — download best addresses for your next drop

## CLI

```bash
dropscore --csv jig_library.csv              # generate variants
dropscore --import-feedback addr1 addr2 -- addr3  # update scores
dropscore --best --retailer target --limit 50     # export top performers
dropscore --validate                          # verify via Smarty
```

## Railway Deploy

```bash
cd /Users/hotdog/dropscore
railway login
railway init
railway up
```

Set `API_TOKEN=` in Railway dashboard. DB persists via attached volume or PostgreSQL add-on.

## Scoring

Bayesian average: `(successes + 1) / (attempts + 2)` — untested addresses score 0.5,
proven performers climb toward 1.0, consistent failures drop toward 0.

## Files

```
dropscore/
├── app/
│   ├── main.py            # FastAPI routes
│   ├── models.py          # Variant model with scoring
│   ├── database.py        # SQLite + Railway volume ready
│   ├── auth.py            # API token gate
│   ├── templates/         # Dark gold Jinja2 pages
│   ├── static/style.css   # Black bg, gold accent
│   └── import_csv.py      # One-time migration from CSV
├── engine.py              # Core address generation logic
├── formats.py             # Retailer profiles + address parsing
├── dropscore.py           # CLI entry point
├── pyproject.toml / Dockerfile / railway.json  # Deploy config
└── jig_library.csv        # Existing address library (3,737 rows)
```