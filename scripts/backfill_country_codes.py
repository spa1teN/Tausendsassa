#!/usr/bin/env python3
"""
Backfill missing country_code values in map_pins via point-in-polygon lookup
against the Natural Earth countries shapefile already bundled for map
rendering (cogs/map_data/ne_10m_admin_0_countries.shp). Every pin has
latitude/longitude (NOT NULL columns), so this needs no new dependency and
no reverse-geocoding API calls — only pins missing country_code are touched.

Usage:
    python scripts/backfill_country_codes.py --dry-run
    python scripts/backfill_country_codes.py --apply
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import geopandas as gpd
from dotenv import load_dotenv
from shapely.geometry import Point

load_dotenv(Path(__file__).parent.parent / ".env")

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "tausendsassa")
DB_USER     = os.getenv("DB_USER", "tausendsassa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

SHAPEFILE = Path(__file__).parent.parent / "cogs" / "map_data" / "ne_10m_admin_0_countries.shp"


ISO_COLUMN = "ISO_A2_EH"  # ISO_A2 is "-99" for France/Norway/etc. (Natural Earth's
                            # long-standing disputed-territory quirk); ISO_A2_EH
                            # ("Errata & Hoc") is the de-facto-sovereignty fixed variant


def load_countries() -> "gpd.GeoDataFrame":
    if not SHAPEFILE.exists():
        print(f"ERROR: shapefile not found at {SHAPEFILE}")
        sys.exit(1)
    world = gpd.read_file(SHAPEFILE)
    if ISO_COLUMN not in world.columns:
        print(f"ERROR: shapefile has no {ISO_COLUMN} column")
        sys.exit(1)
    return world


def lookup_country_code(world: "gpd.GeoDataFrame", lat: float, lon: float) -> str | None:
    point = Point(lon, lat)
    matches = world[world.geometry.contains(point)]
    if matches.empty:
        # Fall back to nearest polygon for points just off a coastline
        # (imprecise geocoded coordinates landing in the sea).
        distances = world.geometry.distance(point)
        nearest_idx = distances.idxmin()
        if distances.loc[nearest_idx] > 0.5:  # ~55km at the equator — too far to guess
            return None
        matches = world.loc[[nearest_idx]]

    iso = matches.iloc[0][ISO_COLUMN]
    if not iso or iso in ("-99", ""):
        return None
    return iso.lower()


async def main(apply: bool):
    world = load_countries()
    print(f"Loaded {len(world)} country polygons from {SHAPEFILE.name}")

    pool = await asyncpg.create_pool(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, latitude, longitude FROM map_pins WHERE country_code IS NULL"
        )

    print(f"Found {len(rows)} pins with missing country_code")

    resolved = 0
    unresolved = 0
    updates = []
    for row in rows:
        code = lookup_country_code(world, row["latitude"], row["longitude"])
        if code:
            resolved += 1
            updates.append((code, row["id"]))
        else:
            unresolved += 1
            print(f"  pin {row['id']} at ({row['latitude']}, {row['longitude']}) — no match, leaving NULL")

    print(f"\nResolved: {resolved}, unresolved: {unresolved}")

    if not apply:
        print("Dry run — no changes written. Re-run with --apply to write.")
        await pool.close()
        return

    async with pool.acquire() as conn:
        await conn.executemany(
            "UPDATE map_pins SET country_code = $1 WHERE id = $2",
            updates,
        )

    print(f"Applied: {len(updates)} pins updated.")
    await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
