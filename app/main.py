"""DropScore — FastAPI web app.

Routes:
  GET /              Dashboard — stats, top performers
  GET /generate      Form: input base addresses + retailer → generate
  POST /generate     Generate jigged addresses
  GET /import        Form: paste post-drop results
  POST /import       Update scores
  GET /library       Full library: filter, sort, search
  GET /export        Download variants as CSV
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, Depends, Query, Form, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func as sa_func
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import Variant
from engine import jig_from_base, parse_address_string
from formats import RETAILER_PROFILES

app = FastAPI(title="DropScore")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Template engine
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def on_startup():
    init_db()


# ── Helpers ────────────────────────────────────────────────────────────────

def _bayesian_score(successes: int, attempts: int) -> float:
    return round((successes + 1) / (attempts + 2), 3)


def _variant_to_csv_dict(v: Variant) -> dict:
    return {
        "full_name": "",
        "address_1": v.line1,
        "address_2": v.line2,
        "city": v.city,
        "state": v.state,
        "zip": f"{v.zip5}-{v.zip4}" if v.zip4 else v.zip5,
        "score": v.score,
        "attempts": v.attempts,
        "successes": v.successes,
        "status": v.status,
        "last_drop": v.last_drop.isoformat() if v.last_drop else "",
        "retailer": v.retailer,
    }


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    total_variants = db.query(Variant).count()
    total_attempts = db.query(Variant).with_entities(Variant.attempts).count()
    sum_attempts = db.query(Variant.attempts).filter(Variant.attempts > 0).count()
    total_successes = sum(
        r[0] for r in db.query(Variant.successes).filter(Variant.successes > 0).all()
    )

    # Top 10 performers (active, score > 0, at least 1 attempt)
    top_performers = (
        db.query(Variant)
        .filter(Variant.status == "active", Variant.attempts >= 1)
        .order_by(desc(Variant.score))
        .limit(10)
        .all()
    )

    # Untested count
    untested = db.query(Variant).filter(Variant.attempts == 0).count()

    # By retailer
    retailer_counts = {}
    for r in db.query(Variant.retailer, sa_func.count(Variant.id)).group_by(Variant.retailer).all():
        if r[0]:
            retailer_counts[r[0]] = r[1]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_variants": total_variants,
        "sum_attempts": sum_attempts,
        "total_successes": total_successes,
        "untested": untested,
        "top_performers": top_performers,
        "retailer_counts": retailer_counts,
    })


@app.get("/generate", response_class=HTMLResponse)
def generate_form(request: Request):
    return templates.TemplateResponse("generate.html", {
        "request": request,
        "retailers": list(RETAILER_PROFILES.keys()),
        "result": None,
    })


@app.post("/generate", response_class=HTMLResponse)
def generate_submit(
    request: Request,
    addresses: str = Form(...),
    retailer: str = Form(""),
    max_per_address: int = Form(30),
    db: Session = Depends(get_db),
):
    profile = RETAILER_PROFILES.get(retailer)
    prefix_random_chars = bool(profile and profile.prefix_random_chars)
    now = datetime.now(timezone.utc)

    raw_lines = [l.strip() for l in addresses.split("\n") if l.strip()]
    if not raw_lines:
        return templates.TemplateResponse("generate.html", {
            "request": request,
            "retailers": list(RETAILER_PROFILES.keys()),
            "error": "No addresses provided.",
            "result": None,
        })

    generated = 0
    skipped = 0
    errors = []

    for raw in raw_lines:
        csv_rows = jig_from_base(
            raw,
            max_per_address=max_per_address,
            profile=profile,
            prefix_random_chars=prefix_random_chars,
        )
        if not csv_rows:
            errors.append(f"Could not parse: {raw}")
            continue

        for row in csv_rows:
            full_addr = row["normalized_address"] or f"{row['address_1']}, {row['city']}, {row['state']} {row['zip']}"
            # Check for duplicate
            existing = db.query(Variant).filter(Variant.full_address == full_addr).first()
            if existing:
                skipped += 1
                continue

            v = Variant(
                base_raw=raw,
                line1=row["address_1"],
                line2=row["address_2"],
                city=row["city"],
                state=row["state"],
                zip5=row["zip"].split("-")[0] if row["zip"] else "",
                zip4=row["zip"].split("-")[1] if "-" in row["zip"] else "",
                full_address=full_addr,
                retailer=retailer,
                format_type="",
                score=0.5,
                status="active",
                created_at=now,
                updated_at=now,
            )
            db.add(v)
            generated += 1

    db.commit()

    return templates.TemplateResponse("generate.html", {
        "request": request,
        "retailers": list(RETAILER_PROFILES.keys()),
        "result": {
            "generated": generated,
            "skipped": skipped,
            "total_input": len(raw_lines),
            "errors": errors,
        },
    })


@app.get("/import", response_class=HTMLResponse)
def import_form(request: Request):
    return templates.TemplateResponse("import_results.html", {
        "request": request,
        "result": None,
    })


@app.post("/import", response_class=HTMLResponse)
def import_submit(
    request: Request,
    successes: str = Form(""),
    failures: str = Form(""),
    drop_label: str = Form(""),
    db: Session = Depends(get_db),
):
    """Import post-drop results. Matches by full address string."""
    now = datetime.now(timezone.utc)
    updated_successes = 0
    updated_failures = 0
    not_found = []

    for line in successes.strip().split("\n"):
        addr = line.strip()
        if not addr:
            continue
        # Try to find by full_address or address_1
        v = db.query(Variant).filter(Variant.full_address == addr).first()
        if v:
            v.successes = (v.successes or 0) + 1
            v.attempts = (v.attempts or 0) + 1
            v.score = _bayesian_score(v.successes, v.attempts)
            v.last_drop = now
            v.status = "active"
            updated_successes += 1
        else:
            not_found.append(addr)

    for line in failures.strip().split("\n"):
        addr = line.strip()
        if not addr:
            continue
        v = db.query(Variant).filter(Variant.full_address == addr).first()
        if v:
            v.attempts = (v.attempts or 0) + 1
            v.score = _bayesian_score(v.successes, v.attempts)
            v.last_drop = now
            if v.attempts >= 3 and v.score < 0.2:
                v.status = "flagged"
            updated_failures += 1
        else:
            pass  # silent — failures are often "everything else"

    db.commit()

    return templates.TemplateResponse("import_results.html", {
        "request": request,
        "result": {
            "successes_updated": updated_successes,
            "failures_updated": updated_failures,
            "not_found": not_found[:10],  # show first 10
            "total_not_found": len(not_found),
        },
    })


@app.get("/library", response_class=HTMLResponse)
def library_view(
    request: Request,
    retailer: str = Query(""),
    status: str = Query(""),
    min_score: float = Query(0.0),
    sort: str = Query("score"),
    order: str = Query("desc"),
    q: str = Query(""),  # text search
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Variant)

    if retailer:
        query = query.filter(Variant.retailer == retailer)
    if status:
        query = query.filter(Variant.status == status)
    if min_score > 0:
        query = query.filter(Variant.score >= min_score)
    if q:
        like = f"%{q}%"
        query = query.filter(
            Variant.full_address.like(like) |
            Variant.line1.like(like) |
            Variant.city.like(like)
        )

    total = query.count()
    sort_col = getattr(Variant, sort, Variant.score)
    if order == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    offset = (page - 1) * per_page
    variants = query.offset(offset).limit(per_page).all()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse("library.html", {
        "request": request,
        "variants": variants,
        "retailer": retailer,
        "status_filter": status,
        "min_score": min_score,
        "sort": sort,
        "order": order,
        "q": q,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "all_retailers": list(RETAILER_PROFILES.keys()),
    })


@app.get("/export")
def export_csv(
    retailer: str = Query(""),
    status: str = Query("active"),
    min_score: float = Query(0.0),
    limit: int = Query(0),
    db: Session = Depends(get_db),
):
    """Download variants as CSV (for feeding into botting tools)."""
    query = db.query(Variant).filter(Variant.status == "active")

    if retailer:
        query = query.filter(Variant.retailer == retailer)
    if min_score > 0:
        query = query.filter(Variant.score >= min_score)

    query = query.order_by(desc(Variant.score), desc(Variant.attempts))

    if limit > 0:
        query = query.limit(limit)

    variants = query.all()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "full_name", "address_1", "address_2", "city", "state", "zip",
        "score", "attempts", "successes", "status", "last_drop", "retailer",
    ])
    writer.writeheader()
    for v in variants:
        writer.writerow(_variant_to_csv_dict(v))

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dropscore_export.csv"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}