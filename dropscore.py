#!/usr/bin/env python3
"""DropScore CLI — address lifecycle for botting ops.

Generates address format variants from base addresses, optionally validates
base addresses via Smarty, and maintains a living library CSV with scoring.

Usage:
    python3 dropscore.py --csv jig_library.csv  # generate from base_addresses.txt
    python3 dropscore.py --import-feedback results.csv  # update scores
    python3 dropscore.py --best --retailer target  # export top performers
"""

import argparse
import csv
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from engine import (
    AddressComponents,
    RETAILER_PROFILES,
    parse_address_string,
    generate_format_permutations,
    generate_pkc_line2_variants,
    generate_secondary_candidates,
    jig_from_base,
    write_csv,
    CSV_FIELDS,
)

BASE_DIR = Path(__file__).parent
DEFAULT_BASE_FILE = BASE_DIR / "base_addresses.txt"
DEFAULT_LIBRARY = BASE_DIR / "jig_library.csv"

# ── Optional Smarty Validation ─────────────────────────────────────────────

def smarty_validate(address: AddressComponents) -> AddressComponents:
    """Validate a single address via Smarty. Returns AddressComponents with DPBC/cmra populated."""
    try:
        from smarty_client import SmartyClient
    except ImportError:
        print("  ✗ smarty_client.py not found — skipping Smarty validation", file=sys.stderr)
        return address

    client = SmartyClient()
    result = client.validate_one(address)
    if result:
        # Return a copy with Smarty data merged
        return AddressComponents(
            line1=(result.line1 or address.line1),
            line2=(result.line2 or address.line2),
            city=(result.city or address.city),
            state=(result.state or address.state),
            zip5=(result.zip5 or address.zip5),
            zip4=(result.zip4 or address.zip4),
            dpbc=result.dpbc or "",
            dpv_code=result.dpv_code or "",
            cmra=result.cmra or "",
        )
    return address


def resolve_smarty_street(raw: str) -> AddressComponents | None:
    """Resolve a raw address string through Smarty, get normalized components."""
    try:
        from smarty_client import SmartyClient
    except ImportError:
        return None
    client = SmartyClient()
    return client.validate_one_raw(raw)


# ── Scoring ─────────────────────────────────────────────────────────────────

def bayesian_score(successes: int, attempts: int, prior: float = 0.5, prior_n: int = 2) -> float:
    return (successes + prior * prior_n) / (attempts + prior_n)


def import_feedback(library_path: str, success_lines: list[str], fail_lines: list[str]):
    """Update scores in the CSV library from post-drop feedback."""
    if not os.path.exists(library_path):
        print(f"Error: library not found: {library_path}", file=sys.stderr)
        return

    with open(library_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    success_set = {s.strip().lower() for s in success_lines if s.strip()}
    fail_set = {f.strip().lower() for f in fail_lines if f.strip()}

    updated = 0
    for row in rows:
        addr = f"{row['address_1']}, {row['city']}, {row['state']} {row['zip']}".strip().lower()
        if addr in success_set:
            row['attempts'] = str(int(row.get('attempts', 0)) + 1)
            row['successes'] = str(int(row.get('successes', 0)) + 1)
            updated += 1
        elif addr in fail_set:
            row['attempts'] = str(int(row.get('attempts', 0)) + 1)
            row['successes'] = str(int(row.get('successes', 0)) + 1)
            # failures = attempts - successes
            updated += 1

    # Recalculate scores
    for row in rows:
        att = int(row.get('attempts', 0))
        suc = int(row.get('successes', 0))
        row['score'] = f"{bayesian_score(suc, att):.4f}"

    with open(library_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ {updated} addresses updated in {library_path}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    if load_dotenv:
        load_dotenv()

    parser = argparse.ArgumentParser(description="DropScore — address lifecycle tool")
    parser.add_argument("--base-file", default=str(DEFAULT_BASE_FILE), help="File with base addresses (one per line)")
    parser.add_argument("--csv", default=str(DEFAULT_LIBRARY), help="Library CSV path")
    parser.add_argument("--retailer", choices=list(RETAILER_PROFILES.keys()) + [""], default="",
                        help="Retailer for format rules")
    parser.add_argument("--max", type=int, default=0, help="Max variants per address (0 = all)")
    parser.add_argument("--import-feedback", nargs='*', default=None,
                        help="Lines of addresses that worked and didn't. Use: --import-feedback addr1 addr2 -- addr3 addr4")
    parser.add_argument("--best", action="store_true", help="Export best-performing addresses")
    parser.add_argument("--limit", type=int, default=50, help="Max results for --best")
    parser.add_argument("--validate", action="store_true", help="Validate base addresses via Smarty (requires credentials)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written without modifying files")
    args = parser.parse_args()

    if args.import_feedback is not None:
        # Split on '--' — before = successes, after = failures
        successes = []
        failures = []
        current = successes
        for item in args.import_feedback:
            if item == '--':
                current = failures
            else:
                current.append(item)
        import_feedback(args.csv, successes, failures)
        return

    if args.best:
        if not os.path.exists(args.csv):
            print(f"Error: {args.csv} not found", file=sys.stderr)
            return
        with open(args.csv) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Sort by score descending, then by attempts descending
        rows.sort(key=lambda r: (
            float(r.get('score', 0.5)),
            int(r.get('attempts', 0))
        ), reverse=True)
        if args.retailer:
            rows = [r for r in rows if r.get('retailer', '') == args.retailer]
        best = rows[:args.limit]
        out_path = BASE_DIR / f"best_{args.retailer or 'all'}.csv"
        with open(out_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=reader.fieldnames)
            w.writeheader()
            w.writerows(best)
        print(f"✓ Exported {len(best)} best addresses to {out_path}")
        return

    # Generate mode
    base_file = Path(args.base_file)
    if not base_file.exists():
        print(f"Error: base file not found: {base_file}", file=sys.stderr)
        return

    with open(base_file) as f:
        base_lines = [l.strip() for l in f if l.strip()]

    if not base_lines:
        print("No addresses found in base file.", file=sys.stderr)
        return

    profile = RETAILER_PROFILES.get(args.retailer)
    prefix_random_chars = bool(profile and profile.prefix_random_chars)
    all_rows: list[dict] = []
    errors: list[str] = []

    for raw in base_lines:
        rows = jig_from_base(
            raw,
            max_per_address=args.max,
            profile=profile,
            prefix_random_chars=prefix_random_chars,
        )
        if not rows:
            errors.append(raw)
        else:
            all_rows.extend(rows)

    if not all_rows:
        print("No valid addresses generated.")
        for e in errors:
            print(f"  Could not parse: {e}")
        return

    if args.validate:
        print("Validating via Smarty (one call per unique base address)...")
        seen = set()
        for row in all_rows:
            base = row["base_address"]
            if base not in seen:
                seen.add(base)
                parsed = parse_address_string(base)
                if parsed:
                    validated = smarty_validate(parsed)
                    # Update dpv_code in all rows with this base
                    for r in all_rows:
                        if r["base_address"] == base:
                            r["dpv_code"] = validated.dpv_code
                            r["dpbc"] = validated.dpbc
                print(f"  {base} — DPV: {row.get('dpv_code', 'N/A')}")

    # Write CSV
    written = write_csv(args.csv, all_rows, append=os.path.exists(args.csv))
    print(f"✓ {written} variants written to {args.csv}")
    if errors:
        print(f"! {len(errors)} addresses could not be parsed:")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()