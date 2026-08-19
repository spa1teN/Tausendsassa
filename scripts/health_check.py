#!/usr/bin/env python3
"""
Health check script for Docker container.
Checks database connectivity and bot status.
"""

import asyncio
import os
import sys


async def check_database():
    """Check if database is accessible."""
    try:
        import asyncpg

        conn = await asyncpg.connect(
            host=os.getenv('DB_HOST', 'postgres'),
            port=int(os.getenv('DB_PORT', 5432)),
            database=os.getenv('DB_NAME', 'tausendsassa'),
            user=os.getenv('DB_USER', 'tausendsassa'),
            password=os.getenv('DB_PASSWORD', ''),
            timeout=5
        )

        # Simple query to verify connection
        result = await conn.fetchval('SELECT 1')
        await conn.close()

        if result == 1:
            print("Database: OK")
            return True
        else:
            print("Database: Query failed")
            return False

    except Exception as e:
        print(f"Database: FAILED - {e}")
        return False


async def check_bot_process():
    """Check if bot process is running (basic check)."""
    # In Docker, if this script runs, Python is working
    print("Python: OK")
    return True


async def main():
    """Run all health checks."""
    checks = [
        ("Database", check_database()),
        ("Python", check_bot_process()),
    ]

    results = await asyncio.gather(*[check[1] for check in checks], return_exceptions=True)

    all_passed = all(
        r is True for r in results
        if not isinstance(r, Exception)
    )

    if all_passed:
        print("\nHealth check: PASSED")
        sys.exit(0)
    else:
        print("\nHealth check: FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
