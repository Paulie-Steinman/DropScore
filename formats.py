"""Retailer-specific jigging profiles and format rules."""

import re
from dataclasses import dataclass

# ── Street Suffix Mappings ─────────────────────────────────────────────────
STREET_SUFFIXES = {
    "st": ["st", "street"],
    "ave": ["ave", "avenue"],
    "blvd": ["blvd", "boulevard"],
    "rd": ["rd", "road"],
    "dr": ["dr", "drive"],
    "ln": ["ln", "lane"],
    "pkwy": ["pkwy", "parkway"],
    "hwy": ["hwy", "highway"],
    "ct": ["ct", "court"],
    "cir": ["cir", "circle"],
    "pl": ["pl", "place"],
    "ter": ["ter", "terrace"],
    "way": ["way", "way"],
}

# ── Directional Mappings ───────────────────────────────────────────────────
DIRECTIONALS = {
    "n": ["n", "north", "n."],
    "s": ["s", "south", "s."],
    "e": ["e", "east", "e."],
    "w": ["w", "west", "w."],
    "ne": ["ne", "northeast", "n.e."],
    "nw": ["nw", "northwest", "n.w."],
    "se": ["se", "southeast", "s.e."],
    "sw": ["sw", "southwest", "sw."],
}

# ── State Names ────────────────────────────────────────────────────────────
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

# ── Secondary Designator Labels ────────────────────────────────────────────
SECONDARY_LABELS = [
    "Apt", "Apartment", "#", "Unit", "Suite", "Ste", "Unt",
    "Dept", "Department", "MS", "Mailstop", "OFC", "Office", "SPC", "Space",
]

# Build regex-safe alternation from labels
_LABEL_RE = "|".join(re.escape(l) for l in SECONDARY_LABELS)

# Full secondary format permutation list
SECONDARY_FORMATS: list[tuple[str, str]] = [
    ("Apt", "{}"), ("Apartment", "{}"), ("#", "{}"),
    ("", "Apt {}"), ("", "Apartment {}"), ("", "#{}"),
    ("Unit", "{}"), ("Suite", "{}"), ("Ste", "{}"),
    # Commercial designators
    ("Dept", "{}"), ("Department", "{}"),
    ("", "Dept {}"), ("", "Department {}"),
    ("MS", "{}"), ("Mailstop", "{}"),
    ("", "MS {}"), ("", "Mailstop {}"),
    ("OFC", "{}"), ("Office", "{}"),
    ("", "OFC {}"), ("", "Office {}"),
    ("SPC", "{}"), ("Space", "{}"),
    ("", "SPC {}"), ("", "Space {}"),
]

# ── Retailer Profiles ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class RetailerProfile:
    """Defines which jig types are allowed per retailer."""
    name: str
    # Line1 jigging toggles
    suffix_swaps: bool = True
    directional_swaps: bool = True
    case_variants: bool = True
    zip4_variant: bool = True
    # Line2 jigging
    line2_jigging: bool = True
    # Target-specific extras
    prefix_random_chars: bool = False
    # PKC constraints
    line1_touch: bool = True
    max_jigs: int = 0  # 0 = unlimited


RETAILER_PROFILES: dict[str, RetailerProfile] = {
    "walmart": RetailerProfile(name="walmart"),
    "target": RetailerProfile(
        name="target",
        prefix_random_chars=True,
    ),
    "pokemon-center": RetailerProfile(
        name="pokemon-center",
        suffix_swaps=False,
        directional_swaps=False,
        case_variants=False,
        zip4_variant=False,
        line1_touch=False,
        max_jigs=3,
    ),
}