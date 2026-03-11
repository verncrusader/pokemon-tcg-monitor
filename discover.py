#!/usr/bin/env python3
"""
discover.py — Auto-discover product URLs from retailers by search term.

Usage:
    python3 discover.py "prismatic evolutions"
    python3 discover.py "paldean fates etb" --retailers pokemon_center target walmart
    python3 discover.py "charizard ex" --add   # auto-adds results to config.py
"""

import asyncio
import aiohttp
import re
import sys
import json
import argparse
from urllib.parse import quote_plus
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def search_pokemon_center(session, query: str) -> list[dict]:
    results = []
    api = f"https://www.pokemoncenter.com/api/products?q={quote_plus(query)}&limit=10"
    try:
        async with session.get(api, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                data = await r.json()
                for item in data.get("products", [])[:5]:
                    slug = item.get("slug", "")
                    pid  = item.get("productId", "")
                    name = item.get("name", "")
                    if slug and pid:
                        url = f"https://www.pokemoncenter.com/en-us/product/{slug}/{pid}"
                        results.append({"name": name, "url": url, "retailer": "pokemon_center"})
    except Exception as e:
        print(f"  Pokemon Center search error: {e}")
    return results


async def search_target(session, query: str) -> list[dict]:
    results = []
    api = (
        f"https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2"
        f"?key=9f36aeafbe60771e321a7cc95a78140772ab3e96"
        f"&channel=WEB&count=10&default_purchasability_filter=true"
        f"&keyword={quote_plus(query)}&page=%2Fsearch&platform=desktop"
        f"&pricing_store_id=3991&scheduled_delivery_store_id=3991"
        f"&store_ids=3991&useragent={quote_plus(USER_AGENT)}&visitor_id=test"
        f"&zip=10001"
    )
    try:
        async with session.get(api, headers={**HEADERS, "Accept": "application/json"},
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                data = await r.json()
                items = data.get("data", {}).get("search", {}).get("products", [])
                for item in items[:5]:
                    tcin = item.get("tcin", "")
                    name = item.get("item", {}).get("product_description", {}).get("title", "")
                    url_path = item.get("item", {}).get("enrichment", {}).get("buy_url", "")
                    if tcin and name:
                        url = url_path if url_path else f"https://www.target.com/p/-/-/A-{tcin}"
                        results.append({"name": name, "url": url, "retailer": "target"})
    except Exception as e:
        print(f"  Target search error: {e}")
    return results


async def search_walmart(session, query: str) -> list[dict]:
    results = []
    url = f"https://www.walmart.com/search?q={quote_plus(query)}"
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=18)) as r:
            if r.status == 200:
                text = await r.text()
                # Extract items from embedded JSON
                pattern = r'"usItemId":"(\d+)","name":"([^"]+)","canonicalUrl":"([^"]+)"'
                matches = re.findall(pattern, text)
                for item_id, name, path in matches[:5]:
                    full_url = f"https://www.walmart.com{path}" if path.startswith("/") else path
                    results.append({"name": name, "url": full_url, "retailer": "walmart"})
    except Exception as e:
        print(f"  Walmart search error: {e}")
    return results


async def search_bestbuy(session, query: str) -> list[dict]:
    results = []
    api = (
        f"https://www.bestbuy.com/api/2.0/json/search"
        f"?q={quote_plus(query)}&type=product&categoryId=pcmcat203400050006&pageSize=5"
    )
    try:
        async with session.get(api, headers={**HEADERS, "Accept": "application/json"},
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                data = await r.json()
                for item in data.get("products", [])[:5]:
                    sku  = item.get("sku", "")
                    name = item.get("name", "")
                    url  = item.get("url", "")
                    if sku and name:
                        results.append({"name": name, "url": f"https://www.bestbuy.com{url}", "retailer": "bestbuy"})
    except Exception as e:
        print(f"  Best Buy search error: {e}")
    return results


SEARCH_FUNCTIONS = {
    "pokemon_center": search_pokemon_center,
    "target":         search_target,
    "walmart":        search_walmart,
    "bestbuy":        search_bestbuy,
}


def add_to_config(products: list[dict]):
    """Append discovered products to config.py."""
    config_path = Path("config.py")
    if not config_path.exists():
        print("❌ config.py not found. Run from your drop-alert directory.")
        return

    src = config_path.read_text()
    # Find the end of PRODUCTS list
    insert_before = "\n]\n"
    new_entries = ""
    for p in products:
        new_entries += f"""
    {{
        "name": "{p['name']}",
        "retailer": "{p['retailer']}",
        "url": "{p['url']}",
    }},"""

    updated = src.replace(insert_before, new_entries + insert_before, 1)
    config_path.write_text(updated)
    print(f"✅ Added {len(products)} products to config.py")


async def discover(query: str, retailers: list[str], auto_add: bool):
    print(f"\n🔍 Searching for: '{query}'")
    print(f"   Retailers: {', '.join(retailers)}\n")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [SEARCH_FUNCTIONS[r](session, query) for r in retailers if r in SEARCH_FUNCTIONS]
        all_results = []
        for coro in asyncio.as_completed(tasks):
            results = await coro
            all_results.extend(results)

    if not all_results:
        print("❌ No results found. Try a different search term.")
        return

    print(f"Found {len(all_results)} products:\n")
    for i, p in enumerate(all_results, 1):
        print(f"  [{i}] {p['name']}")
        print(f"      Retailer: {p['retailer']}")
        print(f"      URL: {p['url']}\n")

    if auto_add:
        add_to_config(all_results)
    else:
        print("\nTo add these to your monitor, run with --add flag:")
        print(f"  python3 discover.py \"{query}\" --add")
        print("\nOr copy the URLs manually into config.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-discover product URLs for Drop Alert")
    parser.add_argument("query", help="Search term e.g. 'prismatic evolutions etb'")
    parser.add_argument("--retailers", nargs="+",
                        default=["pokemon_center", "target", "walmart", "bestbuy"],
                        help="Which retailers to search")
    parser.add_argument("--add", action="store_true",
                        help="Automatically add results to config.py")
    args = parser.parse_args()

    asyncio.run(discover(args.query, args.retailers, args.add))
