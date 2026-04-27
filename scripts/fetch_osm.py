#!/usr/bin/env python3
"""Fetch OSM data via Overpass and write a slimmed JSON dataset for the cdmx-3d viewer.

Usage:
    python3 scripts/fetch_osm.py <lat> <lon> <radius_m> <slug> \
        [--name "Display Name"] [--secondary "Subtitle"]

Output: data/<slug>.json (schema documented in CLAUDE.md).
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "cdmx-3d/1.0 (github.com/anthropics; OSM neighborhood viewer)"

KEPT_TAGS = {
    "building", "building:levels", "building:material", "height",
    "highway", "name", "leisure", "landuse", "natural", "amenity",
}


def build_query(lat: float, lon: float, radius_m: int) -> str:
    a = f"around:{radius_m},{lat},{lon}"
    return f"""[out:json][timeout:30];
(
  way["building"]({a});
  way["highway"]({a});
  way["leisure"~"^(park|garden|playground|pitch|common)$"]({a});
  way["landuse"~"^(grass|recreation_ground|forest|cemetery)$"]({a});
  way["natural"="water"]({a});
  way["amenity"="parking"]({a});
);
out body;
>;
out skel qt;
"""


def fetch_overpass(query: str) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"Overpass HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"Overpass network error: {e.reason}")


def slim(raw: dict, lat: float, lon: float, radius: int,
         name: str, secondary: str) -> tuple[dict, dict]:
    """Filter Overpass output to the runtime schema. Returns (json_payload, counts)."""
    elements = []
    used_nodes: set[int] = set()
    counts = {"buildings": 0, "roads": 0, "parks": 0, "parking": 0, "water": 0}

    for el in raw.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        kept = {k: v for k, v in tags.items() if k in KEPT_TAGS}
        if not kept:
            continue

        if "building" in kept:
            counts["buildings"] += 1
        elif "highway" in kept:
            counts["roads"] += 1
        elif "leisure" in kept or "landuse" in kept:
            counts["parks"] += 1
        elif kept.get("natural") == "water":
            counts["water"] += 1
        elif kept.get("amenity") == "parking":
            counts["parking"] += 1

        nodes = el.get("nodes") or []
        elements.append({"t": "w", "i": el["id"], "n": nodes, "tags": kept})
        used_nodes.update(nodes)

    for el in raw.get("elements", []):
        if el.get("type") != "node" or el["id"] not in used_nodes:
            continue
        elements.append({
            "t": "n",
            "i": el["id"],
            "lat": round(el["lat"], 7),
            "lon": round(el["lon"], 7),
        })

    payload = {
        "c": [lat, lon],
        "r": radius,
        "name": name,
        "secondary": secondary,
        "e": elements,
    }
    return payload, counts


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch OSM data for cdmx-3d.")
    p.add_argument("lat", type=float)
    p.add_argument("lon", type=float)
    p.add_argument("radius_m", type=int)
    p.add_argument("slug")
    p.add_argument("--name", default=None, help="Display name (defaults to slug)")
    p.add_argument("--secondary", default="", help="Subtitle line")
    args = p.parse_args()

    name = args.name or args.slug
    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.slug}.json"

    print(f"→ Querying Overpass for {args.lat}, {args.lon} r={args.radius_m}m…", file=sys.stderr)
    raw = fetch_overpass(build_query(args.lat, args.lon, args.radius_m))
    payload, counts = slim(raw, args.lat, args.lon, args.radius_m, name, args.secondary)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = out_path.stat().st_size / 1024
    print(
        f"✓ Wrote {out_path.relative_to(out_dir.parent)} "
        f"({size_kb:.1f} KB, {len(payload['e'])} elements)",
        file=sys.stderr,
    )
    print(
        f"  buildings={counts['buildings']} roads={counts['roads']} "
        f"parks={counts['parks']} water={counts['water']} parking={counts['parking']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
