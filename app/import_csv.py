#!/usr/bin/env python3
"""Import existing jig_library.csv into the SQLite database.

Usage:
    cd /Users/hotdog/dropscore
    python3 app/import_csv.py [--csv jig_library.csv]

Creates a Variant row for each CSV row. Skips exact duplicates (by full_address).
"""

import csv
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Add parent dir to path so engine imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import init_db, SessionLocal
from app.models import Variant


def main():
    parser = argparse.ArgumentParser(description="Import jig_library.csv into SQLite")
    parser.add_argument("--csv", default="jig_library.csv", help="Path to CSV file")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}")
        return 1

    # Ensure DB/tables exist
    print("📦 Initializing database...")
    init_db()

    # Read CSV
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"📖 Read {len(rows)} rows from {csv_path}")

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    created = 0
    skipped = 0

    try:
        for row in rows:
            # Build full_address for dedup
            a1 = row.get("address_1", "") or ""
            a2 = row.get("address_2", "") or ""
            city = row.get("city", "") or ""
            state = row.get("state", "") or ""
            zip_raw = row.get("zip", "") or ""

            full = f"{a1}, {city}, {state} {zip_raw}" if a2 else f"{a1}, {city}, {state} {zip_raw}"
            if a2:
                full = f"{a1} {a2}, {city}, {state} {zip_raw}"

            # Check for duplicate (committed rows only)
            existing = db.query(Variant).filter(Variant.full_address == full).first()
            if existing:
                skipped += 1
                continue

            zip5 = zip_raw.split("-")[0] if "-" in zip_raw else zip_raw
            zip4 = zip_raw.split("-")[1] if "-" in zip_raw else ""

            # Score — if attempts exist in CSV, calculate
            attempts = int(row.get("attempts", 0) or 0)
            successes = int(row.get("successes", 0) or 0)
            score = round((successes + 1) / (attempts + 2), 3) if attempts > 0 else 0.5

            v = Variant(
                base_raw=row.get("full_name", "") or "",
                line1=a1,
                line2=a2,
                city=city,
                state=state,
                zip5=zip5,
                zip4=zip4,
                full_address=full,
                retailer=row.get("retailer", ""),
                format_type=row.get("format_type", ""),
                attempts=attempts,
                successes=successes,
                score=score,
                status="active",
                created_at=now,
                updated_at=now,
            )
            db.add(v)
            created += 1

        db.commit()
        print(f"✅ Imported {created} new variants ({skipped} duplicates skipped)")
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        return 1
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())