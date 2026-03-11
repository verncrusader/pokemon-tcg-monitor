#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║          DROP ALERT — ELITE EDITION v4.0                         ║
║   The fastest Pokemon TCG restock tracker you can run locally    ║
╚══════════════════════════════════════════════════════════════════╝

Elite Features v4:
  • TIER SYSTEM       — T1=5s · T2=10s · T3=30s adaptive polling
  • LAUNCH BLITZ      — 3s polling on set release day (±1 day)
  • LAUNCH WINDOW     — 5s polling in ±7-day release window
  • SURGE MODE        — T1 restock triggers 5-min boost across ALL T1+T2
  • VELOCITY ALERTS   — "SELLING FAST" when qty drops >50% in 2 minutes
  • MULTI-CHANNEL     — separate Discord webhooks per alert type
  • SMART PINGS       — @everyone T1 · @here T2 · silent T3
  • SMART COOLDOWN    — instant re-alert after PC queue waves
  • PC QUEUE DETECT   — catch the waiting room before it opens
  • STALE DETECTION   — auto-slow products dark for 90+ days
  • RELEASE COUNTDOWN — terminal + heartbeat show days to next drop
  • REFERER CHAINS    — retailer-specific headers to avoid bot blocks
  • COMPETITIVE LOG   — timestamp your edge vs Discord/Twitter
"""

import asyncio
import aiohttp
import json
import re
import time
import random
import subprocess
import logging
import sys
import os
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict
from config import CONFIG, PRODUCTS, PRODUCT_TIERS, RELEASE_CALENDAR

# ── Bootstrap ─────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/monitor.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
COOLDOWN           = CONFIG.get("alert_cooldown_seconds", 240)
BLITZ_INTERVAL     = 3      # release day ± 1 day
ULTRA_FAST         = 5      # Tier 1 / launch window / surge
FAST_INTERVAL      = 10     # Tier 2 / hot pattern
BASE_INTERVAL      = 30     # Tier 3 standard
SLOW_INTERVAL      = 90     # stale / never-restocked
PRICE_DROP_PCT     = 0.05   # alert if price drops >5%
HEARTBEAT_MINS     = 60     # Discord ping every N minutes
SURGE_DURATION     = 300    # surge lasts 5 minutes
LAUNCH_WINDOW_DAYS = 7      # ±7 days around release = launch window
BLITZ_WINDOW_DAYS  = 1      # ±1 day = blitz window
STALE_DAYS         = 90     # no restock in 90 days = stale
VELOCITY_WINDOW    = 120    # seconds to measure qty drop velocity
PATTERN_FILE       = Path("data/restock_patterns.json")
PRICE_FILE         = Path("data/price_history.json")
TIMING_LOG         = Path("logs/competitive_timing.jsonl")
ALERT_HISTORY      = Path("logs/alert_history.jsonl")
STATS_FILE         = Path("data/stats.json")

# ── Anti-bot: Rotating browser fingerprints ───────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.8,es;q=0.6",
    "en-GB,en;q=0.9,en-US;q=0.8",
    "en-US,en;q=0.9,fr;q=0.7",
    "en-US,en;q=1.0",
]

RETAILER_REFERERS = {
    "pokemon_center": "https://www.pokemoncenter.com/category/trading-cards",
    "target":         "https://www.target.com/s?searchTerm=pokemon+tcg",
    "walmart":        "https://www.walmart.com/search?q=pokemon+trading+card+game",
    "bestbuy":        "https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+tcg",
    "gamestop":       "https://www.gamestop.com/toys-games/trading-cards/products/category/pokemon/",
    "sams_club":      "https://www.samsclub.com/s/pokemon",
    "costco":         "https://www.costco.com/CatalogSearch?keyword=pokemon+cards",
}


def random_headers(retailer: str = "") -> dict:
    h = {
        "User-Agent":                random.choice(USER_AGENTS),
        "Accept-Language":           random.choice(ACCEPT_LANGUAGES),
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding":           "gzip, deflate, br",
        "DNT":                       "1",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control":             "no-cache",
        "Pragma":                    "no-cache",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "same-origin",
        "Sec-Fetch-User":            "?1",
    }
    if retailer in RETAILER_REFERERS:
        h["Referer"] = RETAILER_REFERERS[retailer]
    return h


def api_headers(retailer: str = "") -> dict:
    h = {
        "User-Agent":       random.choice(USER_AGENTS),
        "Accept":           "application/json, text/plain, */*",
        "Accept-Language":  random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding":  "gzip, deflate, br",
        "Connection":       "keep-alive",
        "Cache-Control":    "no-cache",
        "Sec-Fetch-Dest":   "empty",
        "Sec-Fetch-Mode":   "cors",
        "Sec-Fetch-Site":   "same-origin",
    }
    if retailer in RETAILER_REFERERS:
        h["Referer"] = RETAILER_REFERERS[retailer]
    return h


# ── State ─────────────────────────────────────────────────────────────────────
stock_state:      dict[str, bool]  = {}
price_state:      dict[str, float] = {}
alert_cooldowns:  dict[str, float] = {}
error_counts:     dict[str, int]   = {}
check_intervals:  dict[str, float] = {}
last_checked:     dict[str, float] = {}
qty_history:      dict[str, list]  = defaultdict(list)   # name → [(ts, qty)]
restock_times:    dict[str, float] = {}                  # name → ts when last restocked
oos_times:        dict[str, float] = {}                  # name → ts when last went OOS
cycle_stats:      dict[str, dict]  = defaultdict(lambda: {"checks": 0, "errors": 0, "avg_ms": 0})
session_start                      = time.time()
total_alerts                       = 0

# Surge mode state
surge_active     = False
surge_expires_at = 0.0
surge_trigger    = ""


# ── Pattern DB ────────────────────────────────────────────────────────────────
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2))


restock_patterns = load_json(PATTERN_FILE, {})
price_history    = load_json(PRICE_FILE, {})
stats_db         = load_json(STATS_FILE, {})


def record_restock(name: str, ts: float):
    restock_patterns.setdefault(name, [])
    restock_patterns[name].append(datetime.fromtimestamp(ts).isoformat())
    restock_patterns[name] = restock_patterns[name][-200:]
    save_json(PATTERN_FILE, restock_patterns)


def predict_hot_window(name: str) -> bool:
    """True if current time matches a historical restock window (±30 min, same DoW)."""
    events = restock_patterns.get(name, [])
    if len(events) < 3:
        return False
    now = datetime.now()
    current_min = now.hour * 60 + now.minute
    hits = 0
    for iso in events:
        try:
            dt = datetime.fromisoformat(iso)
            if dt.weekday() == now.weekday():
                if abs((dt.hour * 60 + dt.minute) - current_min) <= 30:
                    hits += 1
        except Exception:
            pass
    return hits >= 2


# ── Tier System ───────────────────────────────────────────────────────────────
def get_product_tier(name: str) -> int:
    """Return tier 1 / 2 / 3 by matching name substrings against PRODUCT_TIERS."""
    nl = name.lower()
    for tier_num in sorted(PRODUCT_TIERS.keys()):
        for pattern in PRODUCT_TIERS[tier_num]:
            if pattern.lower() in nl:
                return tier_num
    return 3


def tier_badge(tier: int) -> str:
    return {1: "🏆 T1", 2: "⭐ T2", 3: "📦 T3"}.get(tier, "📦 T3")


# ── Release Calendar ──────────────────────────────────────────────────────────
def _release_date_for(name: str) -> date | None:
    nl = name.lower()
    for date_str, names in RELEASE_CALENDAR.items():
        if isinstance(names, str):
            names = [names]
        if any(n.lower() in nl for n in names):
            try:
                return date.fromisoformat(date_str)
            except Exception:
                pass
    return None


def is_in_blitz_window(name: str) -> bool:
    """True on release day ±1 day."""
    rd = _release_date_for(name)
    if rd is None:
        return False
    return abs((date.today() - rd).days) <= BLITZ_WINDOW_DAYS


def is_in_launch_window(name: str) -> bool:
    """True within ±LAUNCH_WINDOW_DAYS of release."""
    rd = _release_date_for(name)
    if rd is None:
        return False
    delta = (date.today() - rd).days
    return -LAUNCH_WINDOW_DAYS <= delta <= LAUNCH_WINDOW_DAYS


def release_countdown_lines() -> list[str]:
    """Return human-readable countdown strings for the terminal / heartbeat."""
    today = date.today()
    lines = []
    for date_str, names in sorted(RELEASE_CALENDAR.items()):
        if isinstance(names, str):
            names = [names]
        try:
            rel = date.fromisoformat(date_str)
            delta = (rel - today).days
            for n in names:
                if delta == 0:
                    lines.append(f"  🔥 {n}: RELEASE DAY — BLITZ ACTIVE")
                elif 0 < delta <= 14:
                    lines.append(f"  ⏰ {n}: {delta}d to launch")
                elif -7 <= delta < 0:
                    lines.append(f"  ✅ {n}: launched {abs(delta)}d ago")
        except Exception:
            pass
    return lines


# ── Surge Mode ────────────────────────────────────────────────────────────────
def activate_surge(trigger_name: str):
    global surge_active, surge_expires_at, surge_trigger
    surge_active     = True
    surge_expires_at = time.time() + SURGE_DURATION
    surge_trigger    = trigger_name
    log.info(f"⚡ SURGE MODE — triggered by: {trigger_name}")
    log.info(f"   All T1+T2 products → {ULTRA_FAST}s for {SURGE_DURATION // 60} min")


def check_surge_expiry():
    global surge_active
    if surge_active and time.time() > surge_expires_at:
        surge_active = False
        log.info("⚡ Surge mode expired — returning to normal intervals")


# ── Adaptive Interval ─────────────────────────────────────────────────────────
def adaptive_interval(name: str) -> float:
    """
    Tier-aware polling interval selection:
      BLITZ (3s):      release day ±1 day
      ULTRA_FAST (5s): Tier 1 · launch window (±7d) · surge active for T1+T2
      FAST (10s):      Tier 2 · hot window predicted
      BASE (30s):      Tier 3 standard
      SLOW (90s):      stale product (>90 days without restock)
    """
    check_surge_expiry()
    tier = get_product_tier(name)

    # Release day = absolute fastest
    if is_in_blitz_window(name):
        return BLITZ_INTERVAL

    # Launch window = ultra fast regardless of tier
    if is_in_launch_window(name):
        return ULTRA_FAST

    # Surge: apply to Tier 1 & 2
    if surge_active and tier <= 2:
        return ULTRA_FAST

    # Tier 1 always fast
    if tier == 1:
        base = ULTRA_FAST
    elif tier == 2:
        base = FAST_INTERVAL
    else:
        base = BASE_INTERVAL

    # Hot window prediction tightens Tier 2 & 3 to at most FAST
    if predict_hot_window(name):
        return min(base, FAST_INTERVAL)

    # Stale check: Tier 3 products dark for STALE_DAYS → SLOW
    if tier == 3:
        events = restock_patterns.get(name, [])
        if events:
            try:
                last_dt = datetime.fromisoformat(events[-1])
                if (datetime.now() - last_dt).days > STALE_DAYS:
                    return SLOW_INTERVAL
            except Exception:
                pass
        elif not events:
            return SLOW_INTERVAL   # never restocked → poll slowly

    return base


# ═══════════════════════════════════════════════════════════════════════════════
# RETAILER CHECKERS — returns (in_stock: bool, price: str, detail: str)
# ═══════════════════════════════════════════════════════════════════════════════

async def check_pokemon_center(session, url) -> tuple[bool, str, str]:
    slug = url.rstrip("/").split("/")[-1]
    # For search-page stubs (upcoming products), try title API
    if "searchTerm" in url or "search" in url:
        return False, "—", "Pre-release stub (not yet listed)"
    api = f"https://www.pokemoncenter.com/api/products/{slug}"
    try:
        async with session.get(api, headers=api_headers("pokemon_center"),
                               timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status == 200:
                data = await r.json()
                inv    = data.get("inventory", {})
                status = inv.get("status", "").upper()
                qty    = inv.get("quantity", "?")
                price_raw = data.get("price", {}).get("sale", 0)
                price     = f"${price_raw:.2f}" if price_raw else "—"
                # Queue / waiting room detection
                if status in ("QUEUE", "WAITING_ROOM", "HOLD", "QUEUED"):
                    log.info(f"🎟️  PC QUEUE OPEN: {url}")
                    return True, price, f"⚠️ PC QUEUE OPEN — join now! ({status})"
                in_stock = status == "IN_STOCK"
                detail   = f"qty={qty}" if in_stock else status
                return in_stock, price, detail
    except Exception as e:
        return False, "—", f"Error: {e}"
    return False, "—", "No response"


async def check_target(session, url) -> tuple[bool, str, str]:
    if "searchTerm" in url or "/s?" in url:
        return False, "—", "Pre-release stub (not yet listed)"
    parts = url.split("-/A-")
    if len(parts) < 2:
        return False, "—", "Bad URL"
    tcin = parts[-1].split("?")[0].strip()
    # Local zip as primary, fallback to other cities
    zips = [("27601", "NC", "35.78", "-78.64"),
            ("10001", "NY", "40.71", "-74.00"),
            ("60601", "IL", "41.88", "-87.63")]
    zip_data = random.choice(zips)
    api = (
        f"https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1"
        f"?key=9f36aeafbe60771e321a7cc95a78140772ab3e96"
        f"&tcin={tcin}&store_id=3991&zip={zip_data[0]}&state={zip_data[1]}"
        f"&latitude={zip_data[2]}&longitude={zip_data[3]}"
    )
    async with session.get(api, headers=api_headers("target"),
                           timeout=aiohttp.ClientTimeout(total=12)) as r:
        if r.status == 200:
            data  = await r.json()
            prod  = data.get("data", {}).get("product", {})
            avail = prod.get("fulfillment", {}).get("shipping_options", {}).get("availability_status", "")
            price = prod.get("price", {}).get("formatted_current_price", "—")
            return avail.upper() == "IN_STOCK", price, avail
    return False, "—", f"HTTP {r.status}"


async def check_walmart(session, url) -> tuple[bool, str, str]:
    if "search?q=" in url:
        return False, "—", "Pre-release stub (not yet listed)"
    await asyncio.sleep(random.uniform(0.5, 2.0))
    async with session.get(url, headers=random_headers("walmart"),
                           timeout=aiohttp.ClientTimeout(total=18)) as r:
        if r.status == 200:
            text     = await r.text()
            m_status = re.search(r'"availabilityStatus":"([^"]+)"', text)
            m_price  = re.search(r'"priceString":"([^"]+)"', text)
            m_qty    = re.search(r'"availableQuantity":(\d+)', text)
            if m_status:
                status   = m_status.group(1).upper()
                price    = m_price.group(1) if m_price else "—"
                qty      = m_qty.group(1)   if m_qty   else "?"
                in_stock = status == "IN_STOCK"
                return in_stock, price, f"qty={qty}" if in_stock else status
        elif r.status == 429:
            return False, "—", "Rate limited"
    return False, "—", f"HTTP {r.status}"


async def check_costco(session, url) -> tuple[bool, str, str]:
    async with session.get(url, headers=random_headers("costco"),
                           timeout=aiohttp.ClientTimeout(total=18)) as r:
        if r.status == 200:
            text = await r.text()
            tl   = text.lower()
            if '"availability":"outofstock"' in tl or 'class="oos-overlay"' in tl:
                return False, "—", "Out of Stock"
            if "add-to-cart" in tl and "out-of-stock" not in tl:
                p = re.search(r'\$[\d,]+\.?\d*', text)
                return True, p.group(0) if p else "—", "In Stock"
    return False, "—", f"HTTP {r.status}"


async def check_sams_club(session, url) -> tuple[bool, str, str]:
    m = re.search(r'/prod(\d+)', url)
    if m:
        item_id = m.group(1)
        api = f"https://www.samsclub.com/api/node/vivaldi/v2/pdp/product?clubId=6333&productId={item_id}"
        async with session.get(api, headers=api_headers(),
                               timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status == 200:
                data = await r.json()
                try:
                    inv      = data["payload"]["inventoryStatus"]
                    in_stock = inv.upper() not in ("OUT_OF_STOCK", "OOS", "UNAVAILABLE")
                    price_raw = data["payload"].get("offerId", {}).get("finalPrice", "")
                    return in_stock, f"${price_raw}" if price_raw else "—", inv
                except (KeyError, TypeError):
                    pass
    async with session.get(url, headers=random_headers(),
                           timeout=aiohttp.ClientTimeout(total=18)) as r:
        if r.status == 200:
            text     = await r.text()
            in_stock = '"OOS"' not in text and "add-to-cart" in text.lower()
            return in_stock, "—", "In Stock" if in_stock else "OOS"
    return False, "—", f"HTTP {r.status}"


async def check_gamestop(session, url) -> tuple[bool, str, str]:
    if "#q=" in url and "&t=product" in url:
        return False, "—", "Pre-release stub (not yet listed)"
    async with session.get(url, headers=random_headers("gamestop"),
                           timeout=aiohttp.ClientTimeout(total=18)) as r:
        if r.status == 200:
            text = await r.text()
            if 'data-button-state="add-to-cart"' in text or '"addToCart"' in text:
                p = re.search(r'"price":\s*"?\$?([\d.]+)"?', text)
                return True, f"${p.group(1)}" if p else "—", "Add to Cart"
            skip_pre = CONFIG.get("skip_preorder", True)
            if not skip_pre and "pre-order" in text.lower():
                return True, "—", "Pre-Order"
            return False, "—", "Sold Out"
    return False, "—", f"HTTP {r.status}"


async def check_bestbuy(session, url) -> tuple[bool, str, str]:
    if "searchpage.jsp" in url:
        return False, "—", "Pre-release stub (not yet listed)"
    m = re.search(r'/(\d{6,8})\.p', url)
    if not m:
        return False, "—", "Bad URL"
    sku = m.group(1)
    api = (
        f"https://www.bestbuy.com/api/tcfb/model.json"
        f"?paths=%5B%5B%22shop%22%2C%22buttonstate%22%2C%22v5%22%2C%22item%22%2C%22skus%22%2C{sku}%5D%5D"
        f"&method=post"
    )
    async with session.get(api, headers=api_headers("bestbuy"),
                           timeout=aiohttp.ClientTimeout(total=12)) as r:
        if r.status == 200:
            data = await r.json()
            try:
                btn = (data["jsonGraph"]["shop"]["buttonstate"]["v5"]
                           ["item"]["skus"][sku]["conditions"]["NONE"]
                           ["destinationZipCode"][""]["buttonState"]["value"])
                skip_pre = CONFIG.get("skip_preorder", True)
                in_stock = btn.upper() == "ADD_TO_CART" or (not skip_pre and btn.upper() == "PRE_ORDER")
                return in_stock, "—", btn
            except (KeyError, TypeError):
                pass
    return False, "—", f"HTTP {r.status}"


async def check_amazon(session, url) -> tuple[bool, str, str]:
    await asyncio.sleep(random.uniform(1.0, 3.0))
    async with session.get(url, headers=random_headers(),
                           timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status == 200:
            text = await r.text()
            if 'id="add-to-cart-button"' in text or '"inStock":true' in text:
                p = re.search(r'id="priceblock_ourprice"[^>]*>\s*\$?([\d.,]+)', text)
                if not p:
                    p = re.search(r'"price":\s*"?\$?([\d.]+)"?', text)
                return True, f"${p.group(1)}" if p else "—", "Add to Cart"
            if "Currently unavailable" in text:
                return False, "—", "Unavailable"
            if "captcha" in text.lower():
                return False, "—", "CAPTCHA — slow down"
    return False, "—", f"HTTP {r.status}"


async def check_generic_pokemon(session, url) -> tuple[bool, str, str]:
    async with session.get(url, headers=random_headers(),
                           timeout=aiohttp.ClientTimeout(total=18)) as r:
        if r.status == 200:
            text = await r.text()
            tl   = text.lower()
            sold_out = any(s in tl for s in ["sold out", "out of stock", "unavailable", "notify me when available"])
            in_stock = any(s in tl for s in ["add to cart", "add-to-cart", "buy now", "in stock"])
            if in_stock and not sold_out:
                p = re.search(r'\$[\d,]+\.?\d*', text)
                return True, p.group(0) if p else "—", "In Stock"
            return False, "—", "Out of Stock"
    return False, "—", f"HTTP {r.status}"


async def check_jp_pokemon(session, url) -> tuple[bool, str, str]:
    headers = {**api_headers(), "Accept-Language": "ja,en;q=0.9"}
    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status == 200:
            text = await r.text()
            tl   = text.lower()
            if "pokemon.co.jp" in url:
                in_stock = 'class="soldOut"' not in text and "buyButton" in text
                return in_stock, "—", "In Stock" if in_stock else "Sold Out"
            sold_out    = any(s in tl for s in ["sold out", "在庫なし", "品切れ", "売り切れ"])
            in_stock_sig = any(s in tl for s in ["add to cart", "カートに入れる", "購入する"])
            if in_stock_sig and not sold_out:
                p = re.search(r'[¥￥][\d,]+', text)
                return True, p.group(0) if p else "—", "In Stock (JP)"
            return False, "—", "Out of Stock"
    return False, "—", f"HTTP {r.status}"


async def check_tcg_supplies(session, url) -> tuple[bool, str, str]:
    async with session.get(url, headers=random_headers(),
                           timeout=aiohttp.ClientTimeout(total=18)) as r:
        if r.status == 200:
            text = await r.text()
            tl   = text.lower()
            sold_out = any(s in tl for s in ["sold out", "out of stock", "unavailable"])
            in_stock = any(s in tl for s in ["add to cart", "add-to-cart", "in stock", "buy now"])
            if in_stock and not sold_out:
                p = re.search(r'\$[\d,]+\.?\d*', text)
                return True, p.group(0) if p else "—", "In Stock"
            return False, "—", "Out of Stock"
    return False, "—", f"HTTP {r.status}"


# ── In-Store Checkers (your local area) ─────────────────────────────────────

async def check_target_instore(session, url) -> tuple[bool, str, str]:
    if "searchTerm" in url or "/s?" in url:
        return False, "—", "Pre-release stub"
    parts = url.split("-/A-")
    if len(parts) < 2:
        return False, "—", "Bad URL"
    tcin      = parts[-1].split("?")[0].strip()
    store_ids = CONFIG.get("local_stores", {}).get("target", ["1826", "1080"])
    for store_id in store_ids[:4]:
        api = (
            f"https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1"
            f"?key=9f36aeafbe60771e321a7cc95a78140772ab3e96"
            f"&tcin={tcin}&store_id={store_id}&zip=27601&state=NC"
            f"&latitude=35.78&longitude=-78.64"
        )
        try:
            async with session.get(api, headers=api_headers("target"),
                                   timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status == 200:
                    data       = await r.json()
                    prod       = data.get("data", {}).get("product", {})
                    store_opts = prod.get("fulfillment", {}).get("store_options", [])
                    price      = prod.get("price", {}).get("formatted_current_price", "—")
                    for opt in store_opts:
                        try:
                            qty = int(opt.get("available_to_pick_up_qty", 0) or 0)
                        except (TypeError, ValueError):
                            qty = 0
                        if qty > 0:
                            loc = opt.get("location_name", f"Target #{store_id}")
                            return True, price, f"IN STORE: {loc} (qty={qty})"
        except Exception:
            pass
    return False, "—", "Not in store"


async def check_walmart_instore(session, url) -> tuple[bool, str, str]:
    if "search?q=" in url:
        return False, "—", "Pre-release stub"
    m = re.search(r'/ip/[^/]+/(\d+)', url)
    if not m:
        return False, "—", "Bad URL"
    item_id   = m.group(1)
    store_ids = CONFIG.get("local_stores", {}).get("walmart", ["1751", "2058", "1372"])
    for store_id in store_ids[:4]:
        api = (f"https://www.walmart.com/store/ajax/api/products/availability"
               f"?storeId={store_id}&itemIds={item_id}")
        try:
            async with session.get(api, headers=api_headers(),
                                   timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status == 200:
                    data      = await r.json()
                    items     = data.get("items", {})
                    item_data = items.get(item_id, items.get(str(item_id), {}))
                    if item_data.get("availabilityStatus", "").upper() == "IN_STOCK":
                        return True, "—", f"IN STORE: Walmart #{store_id}"
        except Exception:
            pass
    # Fallback: page HTML
    try:
        await asyncio.sleep(random.uniform(0.5, 1.5))
        async with session.get(url, headers=random_headers("walmart"),
                               timeout=aiohttp.ClientTimeout(total=18)) as r:
            if r.status == 200:
                text    = await r.text()
                m_store = re.search(r'"inStoreAvailability"\s*:\s*"([^"]+)"', text)
                if m_store and m_store.group(1).upper() == "IN_STOCK":
                    return True, "—", "IN STORE: Walmart (local)"
    except Exception:
        pass
    return False, "—", "Not in store"


async def check_bestbuy_instore(session, url) -> tuple[bool, str, str]:
    if "searchpage.jsp" in url:
        return False, "—", "Pre-release stub"
    m = re.search(r'/(\d{6,8})\.p', url)
    if not m:
        return False, "—", "Bad URL"
    sku       = m.group(1)
    store_ids = CONFIG.get("local_stores", {}).get("bestbuy", ["299", "821"])
    sid_str   = ",".join(str(s) for s in store_ids)
    api = (f"https://www.bestbuy.com/fulfillment/order/api/storeAvailability"
           f"?skuIds={sku}&storeIds={sid_str}")
    try:
        async with session.get(api, headers=api_headers("bestbuy"),
                               timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status == 200:
                data = await r.json()
                for sku_data in data.get("skuAvailabilityList", []):
                    for store in sku_data.get("stores", []):
                        status = store.get("pickupStatus", "").upper()
                        if status in ("AVAILABLE", "IN_STORE_ONLY", "PICKUP_ONLY"):
                            sn = store.get("storeName", f"Best Buy #{store.get('storeId', '')}")
                            return True, "—", f"PICKUP: {sn}"
    except Exception:
        pass
    # Fallback: button state
    api2 = (
        f"https://www.bestbuy.com/api/tcfb/model.json"
        f"?paths=%5B%5B%22shop%22%2C%22buttonstate%22%2C%22v5%22%2C%22item%22%2C%22skus%22%2C{sku}%5D%5D"
        f"&method=post"
    )
    try:
        async with session.get(api2, headers=api_headers("bestbuy"),
                               timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status == 200:
                data = await r.json()
                btn  = (data["jsonGraph"]["shop"]["buttonstate"]["v5"]
                            ["item"]["skus"][sku]["conditions"]["NONE"]
                            ["destinationZipCode"][""]["buttonState"]["value"])
                if btn.upper() == "ADD_TO_CART":
                    return True, "—", "Pickup available (check store)"
    except (KeyError, TypeError, Exception):
        pass
    return False, "—", "Not available for pickup"


# ── Checker Registry ──────────────────────────────────────────────────────────
CHECKERS = {
    "pokemon_center":  check_pokemon_center,
    "target":          check_target,
    "target_instore":  check_target_instore,
    "walmart":         check_walmart,
    "walmart_instore": check_walmart_instore,
    "costco":          check_costco,
    "sams_club":       check_sams_club,
    "gamestop":        check_gamestop,
    "bestbuy":         check_bestbuy,
    "bestbuy_instore": check_bestbuy_instore,
    "amazon":          check_amazon,
    "other_pokemon":   check_generic_pokemon,
    "jp_pokemon":      check_jp_pokemon,
    "tcg_supplies":    check_tcg_supplies,
}

RETAILER_LABELS = {
    "pokemon_center":  "Pokémon Center",
    "target":          "Target",
    "target_instore":  "🏪 Target In-Store",
    "walmart":         "Walmart",
    "walmart_instore": "🏪 Walmart In-Store",
    "costco":          "Costco",
    "sams_club":       "Sam's Club",
    "gamestop":        "GameStop",
    "bestbuy":         "Best Buy",
    "bestbuy_instore": "🏪 Best Buy Pickup",
    "amazon":          "Amazon",
    "other_pokemon":   "Pokemon Retailer",
    "jp_pokemon":      "JP Pokémon",
    "tcg_supplies":    "TCG Supplies",
}

RETAILER_COLORS = {
    "pokemon_center":  0xE3350D,
    "target":          0xCC0000,
    "target_instore":  0xFF6B6B,
    "walmart":         0x0071CE,
    "walmart_instore": 0x4DA8FF,
    "costco":          0x005DAA,
    "sams_club":       0x007DC6,
    "gamestop":        0x002C5F,
    "bestbuy":         0x003087,
    "bestbuy_instore": 0x0056C8,
    "amazon":          0xFF9900,
    "other_pokemon":   0xFFCB05,
    "jp_pokemon":      0xFF0000,
    "tcg_supplies":    0x6B46C1,
}


# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def notify_macos(name: str, detail: str, is_price_drop: bool = False):
    emoji = "💸" if is_price_drop else "🚨"
    title = f"{emoji} {'PRICE DROP' if is_price_drop else 'IN STOCK'}: {name}"
    try:
        script = f'display notification "{detail}" with title "{title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    except Exception as e:
        log.error(f"macOS notify: {e}")


def _resolve_webhook(alert_type_key: str) -> str:
    """Pick the right webhook URL — channel-specific if configured, else primary."""
    primary    = CONFIG.get("discord_webhook_url", "")
    webhooks   = CONFIG.get("discord_webhooks", {})
    specific   = webhooks.get(alert_type_key, "")
    hook       = specific if specific else primary
    if not hook or "YOUR_WEBHOOK" in hook:
        return ""
    return hook


async def notify_discord(session, product: dict, price: str, detail: str,
                          is_price_drop: bool = False, predicted: bool = False,
                          velocity_alert: bool = False):
    tier     = get_product_tier(product["name"])
    blitz    = is_in_blitz_window(product["name"])
    launch   = is_in_launch_window(product["name"])
    retailer = product["retailer"]

    # Route to right channel
    if is_price_drop:
        hook_key = "price_drops"
    elif "_instore" in retailer:
        hook_key = "in_store"
    else:
        hook_key = "main"

    webhook = _resolve_webhook(hook_key)
    if not webhook:
        return

    # Build alert title
    if velocity_alert:
        alert_type = "⚡ SELLING FAST"
    elif is_price_drop:
        alert_type = "💸 PRICE DROP"
    elif blitz:
        alert_type = "🔥🔥 LAUNCH DAY DROP"
    elif surge_active:
        alert_type = "⚡ SURGE DROP 🚨"
    else:
        alert_type = "🚨 IN STOCK"
    if predicted:
        alert_type += " 🔮"

    # Build tier / status badge
    if blitz:
        badge = "🚀 LAUNCH DAY"
    elif launch:
        badge = "⏰ LAUNCH WINDOW"
    elif surge_active and not is_price_drop:
        badge = "⚡ SURGE"
    else:
        badge = tier_badge(tier)

    fields = [
        {"name": "🏪 Retailer", "value": RETAILER_LABELS.get(retailer, retailer), "inline": True},
        {"name": "💰 Price",    "value": price or "—",                             "inline": True},
        {"name": badge,          "value": detail or "—",                            "inline": True},
        {"name": "🔗 Buy Now",  "value": f"[→ Go to product]({product['url']})",   "inline": False},
    ]

    if surge_active and not velocity_alert and not is_price_drop:
        fields.append({
            "name":   "⚡ Surge Tip",
            "value":  f"Triggered by: {surge_trigger} — check ALL retailers now!",
            "inline": False
        })

    # Escalate embed colour on special modes
    color = RETAILER_COLORS.get(retailer, 0x00FF00)
    if blitz:
        color = 0xFF4500   # vivid orange-red
    elif surge_active and not is_price_drop:
        color = 0xFFAA00   # gold

    embed = {
        "title":  f"{alert_type}: {product['name']}",
        "url":    product["url"],
        "color":  color,
        "fields": fields,
        "footer": {"text": f"Drop Alert Elite v4 • {datetime.now().strftime('%b %d %Y %H:%M:%S')}"},
    }
    payload = {"embeds": [embed]}

    # Ping strategy: @everyone T1/launch-day · @here T2 · silent T3
    if tier == 1 or blitz:
        payload["content"] = "@everyone 🚨 TIER 1 DROP — MOVE NOW"
    elif tier == 2:
        payload["content"] = "@here"
    if velocity_alert:
        payload["content"] = "@here ⚡ Selling fast — check qty before it's gone"

    try:
        async with session.post(webhook, json=payload,
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status not in (200, 204):
                log.warning(f"Discord {r.status}: {await r.text()}")
    except Exception as e:
        log.error(f"Discord: {e}")


async def notify_sms(product: dict, price: str, is_price_drop: bool = False):
    cfg = CONFIG.get("twilio", {})
    if not cfg.get("account_sid"):
        return
    tier  = get_product_tier(product["name"])
    if tier > 2 and not is_price_drop:
        return   # SMS only for T1/T2 to avoid spam
    import base64
    creds = base64.b64encode(f"{cfg['account_sid']}:{cfg['auth_token']}".encode()).decode()
    label = "💸 PRICE DROP" if is_price_drop else f"🚨 T{tier} IN STOCK"
    body  = f"{label}: {product['name']}\n{price}\n{product['url']}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{cfg['account_sid']}/Messages.json",
                data={"From": cfg["from"], "To": cfg["to"], "Body": body},
                headers={"Authorization": f"Basic {creds}"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 201:
                    log.warning(f"Twilio {r.status}: {await r.text()}")
    except Exception as e:
        log.error(f"SMS: {e}")


async def fire_all_alerts(session, product: dict, price: str, detail: str,
                           is_price_drop: bool = False, predicted: bool = False,
                           velocity_alert: bool = False):
    global total_alerts
    total_alerts += 1
    notifs = CONFIG.get("notifications", ["macos"])
    label  = RETAILER_LABELS.get(product["retailer"], product["retailer"])
    msg    = f"{price} — {label} {detail}"

    if "macos" in notifs:
        notify_macos(product["name"], msg, is_price_drop)
    if "discord" in notifs:
        await notify_discord(session, product, price, detail,
                             is_price_drop, predicted, velocity_alert)
    if "sms" in notifs:
        await notify_sms(product, price, is_price_drop)

    alert_ts = datetime.now().isoformat()
    with open(ALERT_HISTORY, "a") as f:
        f.write(json.dumps({
            "ts":            alert_ts,
            "ts_unix":       time.time(),
            "name":          product["name"],
            "retailer":      product["retailer"],
            "tier":          get_product_tier(product["name"]),
            "price":         price,
            "detail":        detail,
            "is_price_drop": is_price_drop,
            "predicted":     predicted,
            "velocity":      velocity_alert,
            "blitz":         is_in_blitz_window(product["name"]),
            "url":           product["url"],
        }) + "\n")

    with open(TIMING_LOG, "a") as f:
        f.write(json.dumps({
            "our_alert_ts":   alert_ts,
            "our_alert_unix": time.time(),
            "product":        product["name"],
            "retailer":       product["retailer"],
            "tier":           get_product_tier(product["name"]),
            "discord_delta_s": None,   # fill in manually after Discord check
            "twitter_delta_s": None,
            "note":           "",
        }) + "\n")


async def send_heartbeat(session):
    webhook = _resolve_webhook("heartbeat")
    if not webhook:
        return
    uptime     = str(timedelta(seconds=int(time.time() - session_start)))
    checked    = sum(s["checks"] for s in cycle_stats.values())
    in_stk     = sum(1 for v in stock_state.values() if v)
    t1_cnt     = sum(1 for p in PRODUCTS if get_product_tier(p["name"]) == 1 and "_instore" not in p["retailer"])
    t2_cnt     = sum(1 for p in PRODUCTS if get_product_tier(p["name"]) == 2 and "_instore" not in p["retailer"])
    countdown  = "\n".join(release_countdown_lines()) or "None in next 14 days"
    embed = {
        "title": "💚 Drop Alert Elite v4 — Heartbeat",
        "color": 0xFFAA00 if surge_active else 0x00CC66,
        "fields": [
            {"name": "⏱️ Uptime",         "value": uptime,                     "inline": True},
            {"name": "👁️ Watching",       "value": f"{len(PRODUCTS)} products", "inline": True},
            {"name": "✅ In Stock Now",   "value": str(in_stk),                "inline": True},
            {"name": "🔔 Alerts Fired",   "value": str(total_alerts),          "inline": True},
            {"name": "🏆 T1 Online",      "value": str(t1_cnt),                "inline": True},
            {"name": "⭐ T2 Online",      "value": str(t2_cnt),                "inline": True},
            {"name": "⚡ Surge Mode",     "value": f"ACTIVE — {surge_trigger}" if surge_active else "Standby", "inline": True},
            {"name": "🔍 Total Checks",   "value": str(checked),               "inline": True},
            {"name": "📅 Upcoming Drops", "value": countdown,                  "inline": False},
        ],
        "footer": {"text": f"Drop Alert Elite v4 • Next heartbeat in {HEARTBEAT_MINS} min"},
    }
    try:
        async with session.post(webhook, json={"embeds": [embed]},
                                timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status in (200, 204):
                log.info("💚 Heartbeat sent")
    except Exception as e:
        log.error(f"Heartbeat failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

def parse_price(price_str: str) -> float | None:
    m = re.search(r'[\d,]+\.?\d*', price_str.replace(",", ""))
    if m:
        try:
            return float(m.group(0).replace(",", ""))
        except ValueError:
            pass
    return None


def check_price_drop(name: str, new_price_str: str) -> tuple[bool, str]:
    new_price = parse_price(new_price_str)
    if new_price is None or new_price <= 0:
        return False, ""
    history = price_history.get(name, [])
    if history:
        last_price = history[-1]["price"]
        if last_price > 0:
            drop_pct = (last_price - new_price) / last_price
            if drop_pct >= PRICE_DROP_PCT:
                return True, f"${last_price:.2f} → {new_price_str} (↓{drop_pct*100:.1f}%)"
    price_history.setdefault(name, [])
    price_history[name].append({
        "ts": datetime.now().isoformat(), "price": new_price, "price_str": new_price_str
    })
    price_history[name] = price_history[name][-100:]
    save_json(PRICE_FILE, price_history)
    return False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# VELOCITY (QTY) TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

def track_qty_velocity(name: str, detail: str) -> bool:
    """
    Parse qty from detail string and check sell-through velocity.
    Returns True (= "SELLING FAST") if qty dropped >50% in VELOCITY_WINDOW secs.
    """
    m = re.search(r'qty=(\d+)', detail)
    if not m:
        return False
    qty = int(m.group(1))
    now = time.time()
    hist = qty_history[name]
    hist.append((now, qty))
    qty_history[name] = [(ts, q) for ts, q in hist if now - ts <= VELOCITY_WINDOW * 2]
    window = [(ts, q) for ts, q in qty_history[name] if now - ts <= VELOCITY_WINDOW]
    if len(window) < 2:
        return False
    oldest_qty = window[0][1]
    if oldest_qty <= 0:
        return False
    drop_pct = (oldest_qty - qty) / oldest_qty
    if drop_pct >= 0.5 and (oldest_qty - qty) >= 2:
        log.info(f"⚡ VELOCITY: {name} qty {oldest_qty}→{qty} ({drop_pct*100:.0f}% in {VELOCITY_WINDOW}s)")
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# CORE CHECK LOOP
# ═══════════════════════════════════════════════════════════════════════════════

async def check_product(session, product: dict):
    name    = product["name"]
    checker = CHECKERS.get(product["retailer"])
    if not checker:
        return

    # Adaptive interval gate
    interval = adaptive_interval(name)
    check_intervals[name] = interval
    if time.time() - last_checked.get(name, 0) < interval:
        return
    last_checked[name] = time.time()

    t0 = time.time()
    try:
        in_stock, price, detail = await checker(session, product["url"])
        elapsed_ms = (time.time() - t0) * 1000
        error_counts[name] = 0
        s = cycle_stats[name]
        s["checks"] += 1
        s["avg_ms"] = (s["avg_ms"] * (s["checks"] - 1) + elapsed_ms) / s["checks"]
    except Exception as e:
        n = error_counts.get(name, 0) + 1
        error_counts[name] = n
        cycle_stats[name]["errors"] += 1
        if n <= 3 or n % 20 == 0:
            log.warning(f"⚠️  {name}: error #{n} — {e}")
        return

    was_in_stock = stock_state.get(name, False)
    tier         = get_product_tier(name)
    predicted    = predict_hot_window(name)
    blitz        = is_in_blitz_window(name)

    # ── RESTOCK ALERT ────────────────────────────────────────────────────────
    if in_stock and not was_in_stock:
        since_last = time.time() - alert_cooldowns.get(name, 0)
        if since_last > COOLDOWN:
            tag = " 🔥 LAUNCH DAY" if blitz else (f" 🏆 T{tier}" if tier <= 2 else "")
            log.info(f"✅ RESTOCK{tag}: {name} | {price} | {detail}")
            alert_cooldowns[name] = time.time()
            restock_times[name]   = time.time()
            record_restock(name, time.time())
            # Tier 1 restock → activate surge
            if tier == 1 and not surge_active:
                activate_surge(name)
            await fire_all_alerts(session, product, price, detail, predicted=predicted)
        else:
            log.debug(f"  Cooldown: {name} ({int(COOLDOWN - since_last)}s left)")

    # ── WENT OOS ─────────────────────────────────────────────────────────────
    elif not in_stock and was_in_stock:
        log.info(f"❌ OOS: {name}")
        oos_times[name] = time.time()

    # ── VELOCITY ALERT (still in stock, but qty dropping fast) ───────────────
    elif in_stock and was_in_stock and "qty=" in detail:
        if track_qty_velocity(name, detail):
            vel_key    = f"velocity:{name}"
            since_vel  = time.time() - alert_cooldowns.get(vel_key, 0)
            if since_vel > COOLDOWN:
                alert_cooldowns[vel_key] = time.time()
                await fire_all_alerts(session, product, price, detail, velocity_alert=True)

    # ── PRICE DROP (any state) ────────────────────────────────────────────────
    if price not in ("—", ""):
        is_drop, drop_desc = check_price_drop(name, price)
        if is_drop:
            log.info(f"💸 PRICE DROP: {name} — {drop_desc}")
            await fire_all_alerts(session, product, price, drop_desc, is_price_drop=True)
    else:
        itag = f"⚡{interval}s" if interval <= ULTRA_FAST else f"{interval}s"
        log.debug(f"  {'✅' if in_stock else '⭕'} [{tier_badge(tier)}] {name} [{itag}] {detail}")

    stock_state[name] = in_stock


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

async def validate_config(session):
    log.info("🔧 Validating notification channels...")
    webhook = _resolve_webhook("main")
    if webhook:
        t1 = sum(1 for p in PRODUCTS if get_product_tier(p["name"]) == 1 and "_instore" not in p["retailer"])
        t2 = sum(1 for p in PRODUCTS if get_product_tier(p["name"]) == 2 and "_instore" not in p["retailer"])
        t3 = sum(1 for p in PRODUCTS if get_product_tier(p["name"]) == 3 and "_instore" not in p["retailer"])
        online  = sum(1 for p in PRODUCTS if "_instore" not in p["retailer"])
        instore = sum(1 for p in PRODUCTS if "_instore" in p["retailer"])
        blitz_sets = [n for p in PRODUCTS if is_in_blitz_window(p["name"])
                      for n in [p["name"]] if "_instore" not in p["retailer"]]
        mode_str = f"🔥 BLITZ ({', '.join(set(blitz_sets[:2]))})" if blitz_sets else "⏰ Standard"

        payload = {"embeds": [{"title": "🚀 Drop Alert Elite v4 — Online", "color": 0x00FF88,
           "description": (
               f"Monitor started.\n\n"
               f"**Products:** {len(PRODUCTS)} ({online} online · {instore} in-store)\n"
               f"**Polling:** 🏆 T1={t1} @ 5s · ⭐ T2={t2} @ 10s · 📦 T3={t3} @ 30s\n"
               f"**Local stores:** "
               f"{len(CONFIG.get('local_stores',{}).get('target',[]))} Target · "
               f"{len(CONFIG.get('local_stores',{}).get('walmart',[]))} Walmart · "
               f"{len(CONFIG.get('local_stores',{}).get('bestbuy',[]))} Best Buy\n"
               f"**Mode:** {mode_str}\n\n"
               f"{''.join(release_countdown_lines()) or 'No releases in next 14 days'}"
           )}]}
        try:
            async with session.post(webhook, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status in (200, 204):
                    log.info("  ✅ Discord webhook — OK")
                else:
                    log.error(f"  ❌ Discord returned {r.status}")
        except Exception as e:
            log.error(f"  ❌ Discord: {e}")
    else:
        log.info("  ⚠️  Discord not configured")

    cfg = CONFIG.get("twilio", {})
    log.info("  ✅ Twilio configured" if cfg.get("account_sid") else "  ⚠️  SMS not configured")
    log.info("  ✅ All channels checked")


def print_banner():
    uptime_s   = int(time.time() - session_start)
    in_stk     = sum(1 for v in stock_state.values() if v)
    watching   = len(PRODUCTS)
    ivals      = set(check_intervals.values())
    idisplay   = f"{min(ivals)}–{max(ivals)}s" if len(ivals) > 1 else f"{BASE_INTERVAL}s"
    t1         = sum(1 for p in PRODUCTS if get_product_tier(p["name"]) == 1 and "_instore" not in p["retailer"])
    t2         = sum(1 for p in PRODUCTS if get_product_tier(p["name"]) == 2 and "_instore" not in p["retailer"])
    surge_line = f"\n  ⚡ SURGE ACTIVE — {int(surge_expires_at - time.time())}s left  triggered by: {surge_trigger}" if surge_active else ""

    print(f"""
╔════════════════════════════════════════════════════════════════╗
║  🏆 DROP ALERT ELITE v4 — LIVE                                 ║
║  Products: {watching:<4} (T1:{t1:<3} T2:{t2:<3})   In Stock: {in_stk:<4}            ║
║  Intervals: {idisplay:<12}  Alerts: {total_alerts:<6}  Uptime: {str(timedelta(seconds=uptime_s)):<10}║{surge_line}
╚════════════════════════════════════════════════════════════════╝""")
    for line in release_countdown_lines():
        print(line)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def run():
    log.info("╔═══════════════════════════════════════════════════════════╗")
    log.info("║  DROP ALERT ELITE v4                                      ║")
    log.info(f"║  {len(PRODUCTS)} products · {len(set(p['retailer'] for p in PRODUCTS))} retailer types · tier-aware polling      ║")
    log.info("╚═══════════════════════════════════════════════════════════╝")

    # Release calendar summary
    log.info("📅 Release Calendar:")
    today = date.today()
    for date_str, names in sorted(RELEASE_CALENDAR.items()):
        if isinstance(names, str):
            names = [names]
        try:
            rel   = date.fromisoformat(date_str)
            delta = (rel - today).days
            for n in names:
                if delta < 0:
                    log.info(f"  ✅ {n}: released {abs(delta)}d ago")
                elif delta == 0:
                    log.info(f"  🔥 {n}: RELEASE DAY — BLITZ MODE ACTIVE")
                else:
                    log.info(f"  ⏰ {n}: {delta} days until launch")
        except Exception:
            pass

    # Tier summary
    t1_names = [p["name"] for p in PRODUCTS if get_product_tier(p["name"]) == 1 and "_instore" not in p["retailer"]]
    log.info(f"🏆 Tier 1 ({len(t1_names)} online, 5s): {', '.join(t1_names[:6])}{'...' if len(t1_names) > 6 else ''}")

    connector = aiohttp.TCPConnector(limit=25, ssl=False, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        await validate_config(session)

        last_heartbeat = time.time()
        last_banner    = time.time()

        while True:
            await asyncio.gather(
                *[check_product(session, p) for p in PRODUCTS],
                return_exceptions=True
            )

            if time.time() - last_heartbeat > HEARTBEAT_MINS * 60:
                await send_heartbeat(session)
                last_heartbeat = time.time()

            if time.time() - last_banner > 300:
                print_banner()
                last_banner = time.time()

            # Sleep at BLITZ_INTERVAL so release-day products can poll at 3s
            await asyncio.sleep(BLITZ_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("\n👋 Monitor stopped.")
        print_banner()
