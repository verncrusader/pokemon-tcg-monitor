#!/usr/bin/env python3
"""
dashboard.py — Elite Drop Alert Dashboard
Run: python3 dashboard.py → open http://localhost:8080
Auto-refreshes every 15 seconds.
"""

import json
import ast
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from collections import defaultdict

CONFIG_FILE   = Path("config.py")
ALERT_LOG     = Path("logs/alert_history.jsonl")
TIMING_LOG    = Path("logs/competitive_timing.jsonl")
MONITOR_LOG   = Path("logs/monitor.log")
PATTERN_FILE  = Path("data/restock_patterns.json")
PRICE_FILE    = Path("data/price_history.json")
STATS_FILE    = Path("data/stats.json")

RETAILER_OPTIONS = [
    ("pokemon_center", "Pokémon Center"),
    ("target",         "Target"),
    ("walmart",        "Walmart"),
    ("costco",         "Costco"),
    ("sams_club",      "Sam's Club"),
    ("gamestop",       "GameStop"),
    ("bestbuy",        "Best Buy"),
    ("amazon",         "Amazon"),
    ("other_pokemon",  "Other Pokemon"),
    ("jp_pokemon",     "JP Pokémon"),
    ("tcg_supplies",   "TCG Supplies"),
]
RETAILER_MAP = dict(RETAILER_OPTIONS)

RETAILER_CSS = {
    "pokemon_center": "#e3350d", "target": "#cc0000", "walmart": "#0071ce",
    "costco": "#005daa", "sams_club": "#007dc6", "gamestop": "#4477ff",
    "bestbuy": "#003087", "amazon": "#ff9900", "other_pokemon": "#ffcb05",
    "jp_pokemon": "#ff4444", "tcg_supplies": "#aa66ff",
}


def load_json(path, default):
    if path and path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def load_products():
    src = CONFIG_FILE.read_text()
    m = re.search(r"^PRODUCTS\s*=\s*(\[.*?\n\])", src, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    try:
        return ast.literal_eval(m.group(1))
    except Exception:
        return []


def save_products(products):
    src = CONFIG_FILE.read_text()
    new_block = "PRODUCTS = " + json.dumps(products, indent=4)
    src_new = re.sub(
        r"^PRODUCTS\s*=\s*\[.*?\n\]",
        new_block,
        src,
        flags=re.MULTILINE | re.DOTALL
    )
    CONFIG_FILE.write_text(src_new)


def load_history(n=100):
    if not ALERT_LOG.exists():
        return []
    lines = ALERT_LOG.read_text().strip().split("\n")
    events = []
    for line in reversed(lines):
        if line.strip():
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events[:n]


def load_timing():
    if not TIMING_LOG.exists():
        return []
    lines = TIMING_LOG.read_text().strip().split("\n")
    out = []
    for line in reversed(lines):
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out[:20]


def load_log_tail(n=25):
    if not MONITOR_LOG.exists():
        return []
    return MONITOR_LOG.read_text().strip().split("\n")[-n:]


def alerts_by_retailer(history):
    counts = defaultdict(int)
    for h in history:
        counts[h.get("retailer", "unknown")] += 1
    return dict(counts)


def alerts_by_hour(history):
    """Returns list of 24 ints (alert counts per hour of day)."""
    counts = [0] * 24
    for h in history:
        try:
            dt = datetime.fromisoformat(h["ts"])
            counts[dt.hour] += 1
        except Exception:
            pass
    return counts


def render(products, history, timing, log_lines, patterns, prices):
    now_str = datetime.now().strftime("%b %d %Y %H:%M:%S")
    retailer_opts = "".join(f'<option value="{k}">{v}</option>' for k, v in RETAILER_OPTIONS)

    # Stats
    total_alerts = len(history)
    price_drops = sum(1 for h in history if h.get("is_price_drop"))
    restocks = total_alerts - price_drops
    retailers_active = len(set(p.get("retailer") for p in products))

    # Retailer bar chart data
    by_retailer = alerts_by_retailer(history)
    max_count = max(by_retailer.values(), default=1)
    retailer_bars = ""
    for r_key, r_label in RETAILER_OPTIONS:
        count = by_retailer.get(r_key, 0)
        pct = int(count / max_count * 100) if max_count > 0 else 0
        color = RETAILER_CSS.get(r_key, "#666")
        retailer_bars += f"""
        <div class="bar-row">
          <span class="bar-label">{r_label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>
          <span class="bar-count">{count}</span>
        </div>"""

    # Hourly chart (sparkline)
    by_hour = alerts_by_hour(history)
    max_h = max(by_hour) if any(by_hour) else 1
    hour_bars = ""
    for i, cnt in enumerate(by_hour):
        h = int(cnt / max_h * 60) if max_h > 0 else 0
        label = f"{i:02d}"
        hour_bars += f'<div class="spark-col" title="{label}:00 — {cnt} alerts"><div class="spark-bar" style="height:{h}px"></div><div class="spark-label">{label}</div></div>'

    # Product rows
    product_rows = ""
    for i, p in enumerate(products):
        r_key = p.get("retailer", "")
        r_label = RETAILER_MAP.get(r_key, r_key)
        color = RETAILER_CSS.get(r_key, "#666")
        pattern_count = len(patterns.get(p["name"], []))
        pattern_badge = f'<span class="pattern-badge">🔮 {pattern_count} patterns</span>' if pattern_count else ""
        # Latest price
        ph = prices.get(p["name"], [])
        price_display = ph[-1]["price_str"] if ph else "—"
        product_rows += f"""
        <tr>
          <td>
            <div class="prod-name">{p.get('name','')}</div>
            {pattern_badge}
          </td>
          <td><span class="badge" style="background:{color}22;color:{color};border:1px solid {color}44">{r_label}</span></td>
          <td class="price-cell">{price_display}</td>
          <td class="url-cell"><a href="{p.get('url','')}" target="_blank">↗ View</a></td>
          <td>
            <form method="POST" action="/delete" style="display:inline">
              <input type="hidden" name="index" value="{i}">
              <button class="btn-remove" type="submit">✕</button>
            </form>
          </td>
        </tr>"""

    # Alert history rows
    alert_rows = ""
    for h in history[:30]:
        ts = h.get("ts","")[:19].replace("T"," ")
        r_key = h.get("retailer","")
        color = RETAILER_CSS.get(r_key, "#666")
        r_label = RETAILER_MAP.get(r_key, r_key)
        drop_flag = " 💸" if h.get("is_price_drop") else ""
        pred_flag = " 🔮" if h.get("predicted") else ""
        alert_rows += f"""
        <tr>
          <td class="ts-cell">{ts}</td>
          <td><strong>{h.get('name','')}{drop_flag}{pred_flag}</strong></td>
          <td><span class="badge" style="background:{color}22;color:{color};border:1px solid {color}44">{r_label}</span></td>
          <td>{h.get('price','—')}</td>
          <td><a href="{h.get('url','')}" target="_blank">↗</a></td>
        </tr>"""
    if not alert_rows:
        alert_rows = '<tr><td colspan="5" class="empty-cell">No alerts yet — monitor is watching...</td></tr>'

    # Timing log rows
    timing_rows = ""
    for t in timing[:10]:
        our_ts = t.get("our_alert_ts","")[:19].replace("T"," ")
        discord_delta = t.get("discord_delta_s")
        discord_display = f"+{discord_delta}s" if discord_delta is not None else '<span class="muted">fill in manually</span>'
        timing_rows += f"""
        <tr>
          <td class="ts-cell">{our_ts}</td>
          <td>{t.get('product','')}</td>
          <td>{t.get('retailer','')}</td>
          <td class="edge-cell">{discord_display}</td>
        </tr>"""
    if not timing_rows:
        timing_rows = '<tr><td colspan="4" class="empty-cell">No timing data yet</td></tr>'

    # Log lines
    log_html = ""
    for line in log_lines:
        cls = "log-error" if "ERROR" in line else "log-warn" if "WARNING" in line or "⚠" in line else "log-ok" if "✅" in line else "log-alert" if "RESTOCK" in line or "💸" in line else ""
        log_html += f'<div class="log-line {cls}">{line}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Drop Alert — Master Dashboard</title>
<meta http-equiv="refresh" content="15">
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap');

  :root {{
    --bg:      #070710;
    --s1:      #0e0e1c;
    --s2:      #161628;
    --border:  #1e1e38;
    --text:    #d8d8f0;
    --muted:   #555570;
    --accent:  #e3350d;
    --gold:    #ffcb05;
    --green:   #00e676;
    --blue:    #4499ff;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ background:var(--bg); color:var(--text); font-family:'Syne',sans-serif; min-height:100vh }}

  /* ── HEADER ── */
  header {{
    padding:20px 36px;
    border-bottom:1px solid var(--border);
    display:flex; align-items:center; justify-content:space-between;
    background:linear-gradient(90deg, #0b0b18 0%, #130a10 50%, #0b0b18 100%);
  }}
  .header-left {{ display:flex; align-items:center; gap:14px }}
  .logo {{ width:36px; height:36px; position:relative }}
  .logo svg {{ width:36px; height:36px }}
  h1 {{ font-size:18px; font-weight:800; color:var(--gold); letter-spacing:-0.5px }}
  .header-sub {{ font-size:12px; color:var(--muted); font-family:'DM Mono',monospace; margin-top:2px }}
  .live-dot {{ width:8px; height:8px; background:var(--green); border-radius:50%;
               box-shadow:0 0 8px var(--green); animation:pulse 2s infinite }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}

  /* ── LAYOUT ── */
  .wrap {{ max-width:1200px; margin:0 auto; padding:28px 24px }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:14px; margin-bottom:28px }}
  .col2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:28px }}

  /* ── STAT CARDS ── */
  .stat {{ background:var(--s1); border:1px solid var(--border); border-radius:10px; padding:18px 22px }}
  .stat .lbl {{ font-size:10px; text-transform:uppercase; letter-spacing:1.5px; color:var(--muted); font-family:'DM Mono',monospace }}
  .stat .val {{ font-size:36px; font-weight:800; color:var(--gold); margin-top:4px; line-height:1 }}
  .stat .sub {{ font-size:11px; color:var(--muted); margin-top:4px }}

  /* ── SECTIONS ── */
  section {{ margin-bottom:28px }}
  .section-head {{
    font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:2px;
    color:var(--muted); margin-bottom:14px; padding-bottom:8px;
    border-bottom:1px solid var(--border); font-family:'DM Mono',monospace;
    display:flex; align-items:center; gap:8px;
  }}
  .card {{ background:var(--s1); border:1px solid var(--border); border-radius:10px; padding:20px }}

  /* ── ADD FORM ── */
  .add-form {{ display:grid; grid-template-columns:1fr 180px 1fr auto; gap:10px; align-items:end }}
  .field label {{ display:block; font-size:10px; text-transform:uppercase; letter-spacing:1px; color:var(--muted); margin-bottom:5px; font-family:'DM Mono',monospace }}
  input, select {{
    width:100%; background:var(--s2); border:1px solid var(--border); border-radius:7px;
    color:var(--text); padding:9px 13px; font-size:13px; font-family:'Syne',sans-serif; outline:none;
    transition:border-color .2s;
  }}
  input:focus, select:focus {{ border-color:var(--gold) }}
  select option {{ background:var(--s2) }}
  .btn-add {{ padding:9px 20px; background:var(--accent); color:white; border:none; border-radius:7px;
              font-size:13px; font-weight:700; cursor:pointer; font-family:'Syne',sans-serif; white-space:nowrap;
              transition:opacity .15s }}
  .btn-add:hover {{ opacity:.85 }}
  .btn-remove {{ background:transparent; border:1px solid #333; color:#666; padding:4px 10px;
                  border-radius:5px; cursor:pointer; font-size:11px; font-family:'Syne',sans-serif }}
  .btn-remove:hover {{ border-color:#ff4444; color:#ff4444 }}

  /* ── TABLES ── */
  table {{ width:100%; border-collapse:collapse }}
  th {{ font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:1px; color:var(--muted);
        padding:0 12px 10px; text-align:left; font-family:'DM Mono',monospace }}
  td {{ padding:11px 12px; border-bottom:1px solid var(--border); font-size:13px; vertical-align:middle }}
  tr:last-child td {{ border-bottom:none }}
  tr:hover td {{ background:var(--s2) }}
  .ts-cell {{ font-family:'DM Mono',monospace; font-size:11px; color:var(--muted) }}
  .url-cell a, td a {{ color:var(--blue); text-decoration:none }}
  td a:hover {{ text-decoration:underline }}
  .prod-name {{ font-weight:600 }}
  .price-cell {{ font-family:'DM Mono',monospace; color:var(--gold) }}
  .empty-cell {{ text-align:center; padding:28px; color:var(--muted); font-style:italic }}
  .edge-cell {{ font-family:'DM Mono',monospace; color:var(--green) }}
  .muted {{ color:var(--muted) }}

  .badge {{ padding:3px 10px; border-radius:20px; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.5px }}
  .pattern-badge {{ font-size:10px; color:#aa66ff; margin-top:3px; display:block }}

  /* ── CHARTS ── */
  .bar-row {{ display:flex; align-items:center; gap:10px; margin-bottom:8px }}
  .bar-label {{ font-size:11px; color:var(--muted); width:130px; flex-shrink:0; font-family:'DM Mono',monospace }}
  .bar-track {{ flex:1; height:6px; background:var(--s2); border-radius:3px; overflow:hidden }}
  .bar-fill {{ height:100%; border-radius:3px; transition:width .5s }}
  .bar-count {{ font-size:11px; color:var(--text); width:24px; text-align:right; font-family:'DM Mono',monospace }}

  .spark {{ display:flex; align-items:flex-end; gap:3px; height:70px; padding-top:10px }}
  .spark-col {{ display:flex; flex-direction:column; align-items:center; flex:1 }}
  .spark-bar {{ width:100%; background:var(--gold); border-radius:2px 2px 0 0; min-height:2px; opacity:.7 }}
  .spark-label {{ font-size:8px; color:var(--muted); margin-top:3px; font-family:'DM Mono',monospace }}

  /* ── LOG ── */
  .log-box {{ background:var(--s2); border:1px solid var(--border); border-radius:8px; padding:14px;
              max-height:280px; overflow-y:auto; font-family:'DM Mono',monospace; font-size:11px }}
  .log-line {{ padding:2px 0; color:#777; border-bottom:1px solid #111; word-break:break-all }}
  .log-line:last-child {{ border:none }}
  .log-ok {{ color:#00e676 }}
  .log-alert {{ color:var(--gold); font-weight:500 }}
  .log-warn {{ color:#ff9900 }}
  .log-error {{ color:#ff4444 }}

  @media(max-width:900px) {{
    .cols {{ grid-template-columns:1fr 1fr }}
    .col2 {{ grid-template-columns:1fr }}
    .add-form {{ grid-template-columns:1fr }}
    header {{ padding:16px 20px }}
  }}
</style>
</head>
<body>

<header>
  <div class="header-left">
    <svg class="logo" viewBox="0 0 36 36">
      <circle cx="18" cy="18" r="17" fill="#e3350d" stroke="#fff" stroke-width="2"/>
      <rect x="1" y="16" width="34" height="4" fill="white"/>
      <circle cx="18" cy="18" r="6" fill="white" stroke="#333" stroke-width="2"/>
      <circle cx="18" cy="18" r="3" fill="#333"/>
    </svg>
    <div>
      <h1>DROP ALERT MASTER</h1>
      <div class="header-sub">{now_str} &nbsp;·&nbsp; auto-refresh 15s</div>
    </div>
  </div>
  <div class="live-dot" title="Live"></div>
</header>

<div class="wrap">

  <!-- Stats -->
  <div class="cols">
    <div class="stat">
      <div class="lbl">Watching</div>
      <div class="val">{len(products)}</div>
      <div class="sub">{retailers_active} retailers</div>
    </div>
    <div class="stat">
      <div class="lbl">Restocks Found</div>
      <div class="val" style="color:var(--green)">{restocks}</div>
      <div class="sub">all time</div>
    </div>
    <div class="stat">
      <div class="lbl">Price Drops</div>
      <div class="val" style="color:#ff9900">{price_drops}</div>
      <div class="sub">alerts fired</div>
    </div>
    <div class="stat">
      <div class="lbl">Total Alerts</div>
      <div class="val">{total_alerts}</div>
      <div class="sub">logged events</div>
    </div>
  </div>

  <!-- Add product -->
  <section>
    <div class="section-head">＋ Add Product</div>
    <div class="card">
      <form method="POST" action="/add">
        <div class="add-form">
          <div class="field">
            <label>Product Name</label>
            <input type="text" name="name" placeholder="e.g. Prismatic Evolutions ETB" required>
          </div>
          <div class="field">
            <label>Retailer</label>
            <select name="retailer">{retailer_opts}</select>
          </div>
          <div class="field">
            <label>Product URL</label>
            <input type="url" name="url" placeholder="https://..." required>
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <button class="btn-add" type="submit">Add →</button>
          </div>
        </div>
      </form>
    </div>
  </section>

  <!-- Products table -->
  <section>
    <div class="section-head">🎯 Watching ({len(products)} products)</div>
    <div class="card" style="padding:0;overflow:hidden">
      <table>
        <thead><tr><th>Product</th><th>Retailer</th><th>Last Price</th><th>URL</th><th></th></tr></thead>
        <tbody>{"".join([product_rows]) or '<tr><td colspan="5" class="empty-cell">Add products above to start monitoring</td></tr>'}</tbody>
      </table>
    </div>
  </section>

  <!-- Charts -->
  <div class="col2">
    <section>
      <div class="section-head">📊 Alerts by Retailer</div>
      <div class="card">{retailer_bars or '<div style="color:var(--muted);font-size:13px">No data yet</div>'}</div>
    </section>
    <section>
      <div class="section-head">⏰ Restock Hours (all time)</div>
      <div class="card">
        <div class="spark">{hour_bars}</div>
        <div style="font-size:10px;color:var(--muted);margin-top:6px;font-family:DM Mono,monospace">Hour of day (UTC) — use this to predict hot windows</div>
      </div>
    </section>
  </div>

  <!-- Alert history -->
  <section>
    <div class="section-head">🔔 Alert History</div>
    <div class="card" style="padding:0;overflow:hidden">
      <table>
        <thead><tr><th>Time</th><th>Product</th><th>Retailer</th><th>Price</th><th>Link</th></tr></thead>
        <tbody>{alert_rows}</tbody>
      </table>
    </div>
  </section>

  <!-- Competitive timing -->
  <section>
    <div class="section-head">⚡ Competitive Timing Log — Your Edge vs Discord/Twitter</div>
    <div class="card" style="padding:0;overflow:hidden">
      <table>
        <thead><tr><th>Our Alert Time</th><th>Product</th><th>Retailer</th><th>Discord Delta</th></tr></thead>
        <tbody>{timing_rows}</tbody>
      </table>
      <div style="padding:12px 16px;font-size:11px;color:var(--muted);font-family:'DM Mono',monospace;border-top:1px solid var(--border)">
        After a drop, check when Discord posted it and enter the delta in logs/competitive_timing.jsonl (discord_delta_s field)
      </div>
    </div>
  </section>

  <!-- Live log -->
  <section>
    <div class="section-head">📟 Live Monitor Log</div>
    <div class="log-box">{log_html or '<div class="log-line">No log yet — start monitor.py first</div>'}</div>
  </section>

</div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send_html(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        products  = load_products()
        history   = load_history()
        timing    = load_timing()
        log_lines = load_log_tail()
        patterns  = load_json(PATTERN_FILE, {})
        prices    = load_json(PRICE_FILE, {})
        self.send_html(render(products, history, timing, log_lines, patterns, prices))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = parse_qs(body)
        path = urlparse(self.path).path
        products = load_products()

        if path == "/add":
            name     = params.get("name", [""])[0].strip()
            retailer = params.get("retailer", [""])[0].strip()
            url      = params.get("url", [""])[0].strip()
            if name and retailer and url:
                products.append({"name": name, "retailer": retailer, "url": url})
                save_products(products)

        elif path == "/delete":
            idx = int(params.get("index", [-1])[0])
            if 0 <= idx < len(products):
                products.pop(idx)
                save_products(products)

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


if __name__ == "__main__":
    port = 8080
    print(f"\n🚀 Drop Alert Master Dashboard")
    print(f"   → http://localhost:{port}")
    print(f"   Ctrl+C to stop\n")
    HTTPServer(("localhost", port), Handler).serve_forever()
