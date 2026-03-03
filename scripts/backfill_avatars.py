#!/usr/bin/env python3
"""
Backfill missing avatar_hash values in map_pins by querying the Discord API.

Usage:
    python scripts/backfill_avatars.py --dry-run
    python scripts/backfill_avatars.py --run
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "tausendsassa")
DB_USER     = os.getenv("DB_USER", "tausendsassa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
BOT_TOKEN   = os.getenv("DISCORD_TOKEN", "")

DISCORD_API = "https://discord.com/api/v10"


async def fetch_user(client: httpx.AsyncClient, user_id: int) -> dict | None:
    resp = await client.get(
        f"{DISCORD_API}/users/{user_id}",
        headers={"Authorization": f"Bot {BOT_TOKEN}"},
    )
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 429:
        retry = float(resp.headers.get("Retry-After", 1))
        print(f"  Rate limited — waiting {retry}s")
        await asyncio.sleep(retry)
        return await fetch_user(client, user_id)
    print(f"  Discord API error {resp.status_code} for user {user_id}")
    return None


async def main(dry_run: bool):
    if not BOT_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in .env")
        sys.exit(1)

    pool = await asyncpg.create_pool(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT user_id FROM map_pins WHERE avatar_hash IS NULL"
        )

    user_ids = [r["user_id"] for r in rows]
    print(f"Found {len(user_ids)} users with missing avatar_hash")

    if dry_run:
        print("Dry run — no changes written.")
        await pool.close()
        return

    updated = 0
    skipped = 0

    async with httpx.AsyncClient(timeout=10) as client:
        for user_id in user_ids:
            user = await fetch_user(client, user_id)
            if not user:
                skipped += 1
                continue

            avatar = user.get("avatar")
            if not avatar:
                print(f"  {user_id} ({user.get('username')}) — no avatar, skipping")
                skipped += 1
                continue

            async with pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE map_pins SET avatar_hash = $1 WHERE user_id = $2 AND avatar_hash IS NULL",
                    avatar, user_id,
                )

            count = int(result.split()[-1])
            print(f"  {user_id} ({user.get('username')}) — avatar={avatar} → {count} pin(s) updated")
            updated += count

            # Be polite to the API
            await asyncio.sleep(0.3)

    print(f"\nDone: {updated} pins updated, {skipped} users skipped (no avatar or API error)")
    await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
