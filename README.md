# 🎴 Drop Alert — Elite Edition v4.0
### The fastest local Pokémon TCG restock monitor you can run

Polls 260+ products across **Target · Walmart · Pokémon Center · Best Buy · GameStop · Sam's Club · Costco** and fires instant Discord + SMS + macOS alerts the moment a product comes back in stock — before anyone else sees it.

---

## ✨ Elite Features

| Feature | Detail |
|---|---|
| **Tier System** | T1 = 5s · T2 = 10s · T3 = 30s adaptive polling |
| **Launch BLITZ** | 3s polling on set release day (±1 day) |
| **Launch Window** | 5s polling in ±7-day release window |
| **Surge Mode** | T1 restock triggers 5-min speed boost across all T1+T2 |
| **Velocity Alerts** | "SELLING FAST" when qty drops >50% in 2 minutes |
| **Multi-Channel Discord** | Separate webhooks: main / in-store / price-drops / heartbeat |
| **Smart Pings** | @everyone T1 · @here T2 · silent T3 |
| **PC Queue Detect** | Catches Pokémon Center waiting room before it opens |
| **In-Store Tracking** | Live shelf qty at your local Target, Walmart & Best Buy |
| **Stale Detection** | Auto-slows products dark for 90+ days |
| **Release Countdown** | Terminal + heartbeat show days to next set drop |
| **Referer Chains** | Retailer-specific headers to reduce bot detection |
| **Pre-release Stubs** | Future sets tracked from day one, URLs swap on launch |

---

## 📦 Sets Tracked (260+ products)

### 🔴 Tier 1 — Ultra Fast (5s polling)
- Prismatic Evolutions ETB & Super Premium
- Ascended Heroes / Perfect Order / Chaos Rising PC ETBs
- Mega Charizard X ex UPC · Team Rocket's Moltres ex UPC
- Pokemon 151 Mew ex UPC
- Surging Sparks Super Premium Collection
- Paldean Fates Shiny Charizard ex Premium Collection
- Enhanced Booster Boxes · Pokemon Day 2026

### 🟡 Tier 2 — Fast (10s polling)
Surging Sparks · Stellar Crown · Shrouded Fable · Twilight Masquerade · Temporal Forces · Paldean Fates · Paradox Rift · Obsidian Flames · Pokemon 151 · Destined Rivals · Journey Together · Black Bolt · White Flare · Phantasmal Flames · Ascended Heroes · Perfect Order

### 🟢 Tier 3 — Standard (30s polling)
Booster Bundles · Costco Packs · Surprise Boxes

### 📅 Pre-Release (stub monitoring)
- **Chaos Rising** — May 22, 2026
- **Storm Emerald** — Sep 5, 2026

---

## 🚀 Setup

### Requirements
```
Python 3.10+
pip install aiohttp
```

Optional (for SMS alerts):
```
pip install twilio
```

### Configuration
Edit `config.py`:

1. **Discord webhook** — paste your webhook URL in `discord_webhook_url`
2. **SMS** — fill in Twilio `account_sid`, `auth_token`, `from`, and `to`
3. **Local stores** — update `local_stores` with your nearest store IDs
4. **Multi-channel Discord** — optionally fill `discord_webhooks` for organized channels

### Run
```bash
cd files
python monitor.py
```

---

## 📁 Files

| File | Purpose |
|---|---|
| `monitor.py` | Main async monitoring engine |
| `config.py` | All products, URLs, webhooks, store IDs |
| `dashboard.py` | Local web dashboard for status viewing |
| `discover.py` | Auto-discovers new product listings |
| `setup.sh` | Install dependencies |

---

## 🏪 Local Store IDs (configure for your city)

Update these in `config.py → local_stores` for your area:

| Retailer | Store IDs |
|---|---|
| Target | Update with your nearest store IDs |
| Walmart | Update with your nearest store IDs |
| Best Buy | Update with your nearest store IDs |

---

## ⚠️ Rules

- **MSRP only** — no resellers, no Amazon marketplace
- **Walmart** — shipped & sold by Walmart only (no third-party sellers)
- This tool is for personal use only — be respectful of retailer ToS

---

## 📅 Upcoming Releases

| Date | Set |
|---|---|
| May 22, 2026 | Chaos Rising (Mega Greninja ex) |
| Sep 5, 2026 | Storm Emerald |

Monitor auto-activates **BLITZ mode** (3s polling) on release day.
