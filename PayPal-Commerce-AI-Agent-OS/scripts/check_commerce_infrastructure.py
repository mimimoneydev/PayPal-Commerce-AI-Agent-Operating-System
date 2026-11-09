#!/usr/bin/env python3
"""Read-only connection checks. Does not create carts, orders, payments or schemas."""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv


async def check_woocommerce():
    from shopping_agent.woocommerce import WooCommerceBackend

    backend = WooCommerceBackend(
        os.environ["WOOCOMMERCE_URL"],
        os.environ["WOOCOMMERCE_BRIDGE_SECRET"],
        os.environ.get("COMMERCE_MERCHANT_ID", "validation"),
    )
    try:
        products = await backend.search_products(None, "", limit=1)
        if products:
            assert await backend.get_product_details(None, products[0].product_id)
        print("PASS WooCommerce: signed catalog and product reads")
    finally:
        await backend.aclose()


async def check_postgres():
    import psycopg

    async with await psycopg.AsyncConnection.connect(
        os.environ["COMMERCE_PAYMENT_DATABASE_URL"],
        connect_timeout=10,
        options="-c default_transaction_read_only=on",
    ) as connection:
        cursor = await connection.execute("SELECT current_setting('server_version_num')::integer")
        assert (await cursor.fetchone())[0] >= 140000
    print("PASS PostgreSQL: read-only connection and server version >= 14")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=["woocommerce", "postgres"])
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    load_dotenv(args.env_file, override=False)
    try:
        await {"woocommerce": check_woocommerce, "postgres": check_postgres}[args.target]()
    except Exception as error:
        print(
            f"FAIL {args.target}: {type(error).__name__}; check local configuration and connectivity"
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    asyncio.run(main())
