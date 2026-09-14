"""Core jigging engine — shared between CLI and web app.

Validates nothing externally; generates format permutations from parsed
address components. No Smarty/USPS dependency.
"""

from __future__ import annotations

import csv
import itertools
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from formats import (
    STREET_SUFFIXES,
    DIRECTIONALS,
    STATE_NAMES,
    SECONDARY_LABELS,
    _LABEL_RE,
    RetailerProfile,
    RETAILER_PROFILES,
)

# ── Address Components ─────────────────────────────────────────────────────
@dataclass
class AddressComponents:
    """USPS-validated address components from Smarty response."""
    line1: str
    line2: str
    city: str
    state: str
    zip5: str
    zip4: str = ""
    dpbc: str = ""
    dpv_code: str = ""
    cmra: str = "N"

    def full_address(self) -> str:
        addr = f"{self.line1}, {self.city}, {self.state} {self.zip5}"
        if self.zip4:
            addr = f"{self.line1}, {self.city}, {self.state} {self.zip5}-{self.zip4}"
        return addr

    def as_csv_row(self, base_address: str = "") -> dict:
        return {
            "full_name": "",
            "address_1": self.line1,
            "address_2": self.line2,
            "city": self.city,
            "state": self.state,
            "zip": f"{self.zip5}-{self.zip4}" if self.zip4 else self.zip5,
            "dpbc": self.dpbc,
            "dpv_code": self.dpv_code,
            "normalized_address": self.full_address(),
            "base_address": base_address,
        }


# ── Street Token Helpers ───────────────────────────────────────────────────
def _tokenize_street(street: str) -> list[str]:
    """Split a street name into tokens, preserving multi-unit components."""
    parts = []
    for token in street.split():
        # Keep leading chars like "x" or "xx" attached to the number
        if token[:-1].lower() in ("x", "xx") and token[-1].isdigit():
            parts.append(token)
        else:
            parts.append(token)
    return parts


def _reconstruct_line1(tokens: list[str]) -> str:
    """Join tokens back into a clean line1 string."""
    return " ".join(t for t in tokens if t)


# ── Parsing ────────────────────────────────────────────────────────────────
def parse_address_string(raw: str) -> Optional[AddressComponents]:
    """Parse an address string into components without calling any API.

    Handles formats like:
      "111 4th Place Apt 3B, Brooklyn, NY 11231"
      "267 Douglass St, Suite 1, Brooklyn, NY 11217"
      "265 Douglass St, Ground Floor, Brooklyn, NY 11217"
    """
    raw = raw.strip()
    if not raw:
        return None

    # Try to split on commas
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    if len(parts) < 2:
        # Single-line format: "111 4th Place Apt 3B Brooklyn NY 11231"
        # Just treat the whole thing as line1, no city/state/zip parsing
        return AddressComponents(line1=raw, line2="", city="", state="", zip5="")

    # Last part should contain state + zip
    state_zip = parts[-1].strip()
    state = ""
    zip5 = ""
    state_zip_match = re.match(r"([A-Za-z]{2})\s+(\d{5})(?:-(\d{4}))?$", state_zip)
    if state_zip_match:
        state = state_zip_match.group(1).upper()
        zip5 = state_zip_match.group(2)
        zip4 = state_zip_match.group(3) or ""
    else:
        zip4 = ""

    # Second-to-last is city
    city = parts[-2].strip() if len(parts) >= 2 else ""

    # Everything before city is the street address
    street_part = ", ".join(parts[:-2]) if len(parts) > 2 else parts[0]

    # Try to separate line1 from line2 in street_part
    label_m = re.search(
        rf"\s+({_LABEL_RE})\s+(.+)$", street_part, re.IGNORECASE
    )
    line2 = ""
    if label_m:
        # Secondary unit: strip it from line1 and set line2
        line1 = re.sub(
            rf"\s+({_LABEL_RE})\s+{re.escape(label_m.group(2))}$",
            "",
            street_part,
            flags=re.IGNORECASE,
        )
        line2 = f"{label_m.group(1).title()} {label_m.group(2)}"
    else:
        line1 = street_part

    return AddressComponents(
        line1=line1,
        line2=line2,
        city=city,
        state=state,
        zip5=zip5,
        zip4=zip4,
        dpv_code="Y",  # assumed valid — no API call
    )


# ── Address Mutation ───────────────────────────────────────────────────────

def _case_variants(value: str) -> list[str]:
    """Return title-case, UPPER, and lower variants."""
    return [value, value.upper(), value.lower()]


def generate_format_permutations(
    base: AddressComponents,
    profile: Optional[RetailerProfile] = None,
) -> list[AddressComponents]:
    """Generate permutations of an address by varying suffix, directional,
    case, state, and ZIP format.

    Returns a flat list of unique AddressComponents.
    """
    tokens = _tokenize_street(base.line1)
    results: list[AddressComponents] = []

    # Identify suffix, predir, postdir tokens
    suffix_idx = -1
    predir_idx = -1
    postdir_idx = -1

    suffix_norm = ""
    for i, t in enumerate(tokens):
        lower = t.rstrip(".").lower()
        if lower in STREET_SUFFIXES:
            if suffix_idx == -1:
                suffix_idx = i
                suffix_norm = lower
        elif lower in DIRECTIONALS:
            if predir_idx == -1 and suffix_idx == -1:
                predir_idx = i
            elif suffix_idx != -1:
                postdir_idx = i

    # Collect alternative forms for each token position
    suffix_alternatives: list[list[str]] = [[] for _ in tokens]
    if suffix_idx != -1:
        suffix_alternatives[suffix_idx] = (
            [s.lower() for s in STREET_SUFFIXES[suffix_norm]]
        )
    if predir_idx != -1:
        predir_lower = tokens[predir_idx].rstrip(".").lower()
        suffix_alternatives[predir_idx] = (
            DIRECTIONALS.get(predir_lower, [tokens[predir_idx]])
        )
    if postdir_idx != -1:
        postdir_lower = tokens[postdir_idx].rstrip(".").lower()
        suffix_alternatives[postdir_idx] = (
            DIRECTIONALS.get(postdir_lower, [tokens[postdir_idx]])
        )

    # State name variants
    state_abbr = base.state.upper().strip()
    state_variants: list[str] = [state_abbr]
    if state_abbr in STATE_NAMES:
        full_name = STATE_NAMES[state_abbr]
        state_variants.append(full_name)

    city_variants: list[str] = [base.city]
    zip_variants: list[str] = [base.zip5]
    if base.zip4:
        zip_variants.append(f"{base.zip5}-{base.zip4}")

    # Collect token position indices that have alternatives
    var_indices = [
        i for i, alts in enumerate(suffix_alternatives) if len(alts) > 1
    ]
    var_lists = [suffix_alternatives[i] for i in var_indices]

    # Build combinations: token_variants × city_variants × state_variants × zip_variants
    base_token_variants = [tuple(tokens)]
    if var_indices:
        var_product = list(itertools.product(*var_lists))
        for combo in var_product:
            vt = list(tokens)
            for idx, val in zip(var_indices, combo):
                vt[idx] = val
            base_token_variants.append(tuple(vt))

    seen = set()
    for token_tuple in base_token_variants:
        line1_candidates: list[str] = [token_tuple[i] for i in range(len(tokens))]
        line1_base = _reconstruct_line1(line1_candidates)

        for city in city_variants:
            for state in state_variants:
                for z5 in zip_variants:
                    addr = AddressComponents(
                        line1=line1_base,
                        line2=base.line2,
                        city=city,
                        state=state,
                        zip5=z5,
                        zip4=base.zip4 if "zip+" not in z5 else base.zip4,
                    )
                    key = (addr.line1, addr.line2, addr.city, addr.state, addr.zip5)
                    if key not in seen:
                        seen.add(key)
                        results.append(addr)

    # Case permutations (title/UPPER/lower on line1, city, and state)
    case_funcs = [
        ("title", lambda s: s.title()),
        ("upper", lambda s: s.upper()),
        ("lower", lambda s: s.lower()),
    ]
    case_results: list[AddressComponents] = []
    case_seen = set()
    for addr in results:
        for case_name, case_fn in case_funcs:
            line1_cased = case_fn(addr.line1)
            city_cased = case_fn(addr.city)
            state_cased = case_fn(addr.state) if case_name in ("upper", "lower") else addr.state
            cased = AddressComponents(
                line1=line1_cased,
                line2=addr.line2,
                city=city_cased,
                state=state_cased,
                zip5=addr.zip5,
                zip4=addr.zip4,
                dpv_code=addr.dpv_code,
            )
            key = (cased.line1, cased.line2, cased.city, cased.state, cased.zip5)
            if key not in case_seen:
                case_seen.add(key)
                case_results.append(cased)

    # Merge: original + case variants, deduped
    final_seen = set()
    merged: list[AddressComponents] = []
    for addr in results + case_results:
        key = (addr.line1, addr.line2, addr.city, addr.state, addr.zip5)
        if key not in final_seen:
            final_seen.add(key)
            merged.append(addr)

    # Prefix-random variants for Target
    if profile and profile.prefix_random_chars:
        prefixes = ["x", "xx", "a", "b", "z"]
        tokens_v2 = _tokenize_street(base.line1)
        # tokens_v2 may have 1-3 elements; pad to always have at least 3 for indexing
        while len(tokens_v2) < 3:
            tokens_v2.append("")
        for prefix in prefixes:
            for case_name, case_fn in case_funcs:
                prefixed_line1 = f"{prefix} {case_fn(tokens_v2[0])}"
                rest_parts = []
                if tokens_v2[1]:
                    rest_parts.append(case_fn(tokens_v2[1]))
                if tokens_v2[2]:
                    rest_parts.append(case_fn(tokens_v2[2]))
                if rest_parts:
                    prefixed_line1 += " " + " ".join(rest_parts)
                city_cased = case_fn(base.city)
                state_cased = base.state
                z5 = base.zip5
                key = (prefixed_line1, base.line2, city_cased, state_cased, z5)
                if key not in final_seen:
                    final_seen.add(key)
                    merged.append(AddressComponents(
                        line1=prefixed_line1, line2=base.line2,
                        city=city_cased, state=state_cased,
                        zip5=z5, zip4=base.zip4, dpv_code=base.dpv_code,
                    ))

    return merged


def generate_pkc_line2_variants(base: AddressComponents) -> list[AddressComponents]:
    """PKC mode: generate line2-only variants from existing line2.

    Varies the secondary designator label (Apt → # → Unit → etc.)
    while keeping the unit number. Line1 is left untouched.
    """
    if not base.line2:
        return []

    # Parse existing line2 for label + number
    m = re.match(rf"^({_LABEL_RE})\s+(.+)$", base.line2, re.IGNORECASE)
    if not m:
        return []

    unit_number = m.group(2).strip()
    results: list[AddressComponents] = []

    # Only clean PKC designators
    pkc_labels = ["Apt", "#", "Unit", "Suite", "Fl", "Ste", "Rm", "Lot", "Bldg"]

    for label in pkc_labels:
        new_line2 = f"{label} {unit_number}"
        jig = AddressComponents(
            line1=base.line1,
            line2=new_line2,
            city=base.city,
            state=base.state,
            zip5=base.zip5,
            zip4=base.zip4,
            dpv_code=base.dpv_code,
        )
        results.append(jig)

    return results


# ── Output ─────────────────────────────────────────────────────────────────
CSV_FIELDS = [
    "full_name", "address_1", "address_2", "city", "state",
    "zip", "dpbc", "dpv_code", "normalized_address", "base_address",
]


def write_csv(path: str, rows: list[dict], append: bool = False) -> int:
    """Write CSV. Returns number of rows written."""
    mode = "a" if append else "w"
    write_header = not (append and Path(path).exists())

    with open(path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


# ── Jig Generation (no validation) ─────────────────────────────────────────
def jig_from_base(
    base_address: str,
    max_per_address: int = 0,
    profile: Optional[RetailerProfile] = None,
    prefix_random_chars: bool = False,
) -> list[dict]:
    """Jig one base address into format variants (no external validation).

    Returns list of CSV-style dicts.
    """
    base_parse = parse_address_string(base_address)
    if not base_parse:
        return []

    address = base_parse
    all_jigs: list[AddressComponents] = []

    # PKC mode: line2-only variants
    if profile and not profile.line1_touch:
        pkc_variants = generate_pkc_line2_variants(address)
        all_jigs.extend(pkc_variants)
        if not pkc_variants:
            # Fall through to standard path if no line2 to vary
            pass

    # Standard path (non-PKC, or PKC fallback)
    if not profile or profile.line1_touch or not all_jigs:
        format_variants = generate_format_permutations(address, profile=profile)
        all_jigs.extend(format_variants)

    # Target prefix random chars
    if prefix_random_chars:
        prefix_variants = _generate_prefix_variants(address)
        all_jigs.extend(prefix_variants)

    # Deduplicate
    seen = set()
    unique_jigs = []
    for jig in all_jigs:
        key = (jig.line1, jig.line2, jig.city, jig.state, jig.zip5)
        if key not in seen:
            seen.add(key)
            unique_jigs.append(jig)

    # Apply max
    if max_per_address > 0:
        unique_jigs = unique_jigs[:max_per_address]

    return [jig.as_csv_row(base_address=base_address) for jig in unique_jigs]


def _generate_prefix_variants(base: AddressComponents) -> list[AddressComponents]:
    """Target-specific: add random-character prefixes to line1.

    Generates variants like 'x 123 Main St', 'xx 123 Main St', 'j 123 Main St'
    """
    results: list[AddressComponents] = []
    prefixes = ["x", "xx", "j", "k", "z"]
    for p in prefixes:
        jig = AddressComponents(
            line1=f"{p} {base.line1}",
            line2=base.line2,
            city=base.city,
            state=base.state,
            zip5=base.zip5,
            zip4=base.zip4,
        )
        results.append(jig)
    return results