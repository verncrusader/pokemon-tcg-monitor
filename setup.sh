#!/bin/bash
# setup.sh — One-time setup for Drop Alert Master Edition

set -e
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  DROP ALERT MASTER — Setup           ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Python check
if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 not found. Install from https://python.org"
  exit 1
fi
echo "✅ Python: $(python3 --version)"

# Install deps
echo ""
echo "📦 Installing dependencies..."
pip3 install aiohttp --quiet --break-system-packages 2>/dev/null || pip3 install aiohttp --quiet
echo "✅ aiohttp installed"

# Folders
mkdir -p logs data
echo "✅ logs/ and data/ folders ready"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Setup complete! Here's how to run:  ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  1. Configure notifications in config.py"
echo "     → Discord webhook URL"
echo "     → Twilio SMS credentials"
echo ""
echo "  2. Add products (pick one):"
echo "     → Dashboard: python3 dashboard.py → http://localhost:8080"
echo "     → Auto-discover: python3 discover.py 'prismatic evolutions' --add"
echo "     → Edit config.py directly"
echo ""
echo "  3. Start monitoring:"
echo "     python3 monitor.py"
echo ""
echo "  Run in background (survives closing Terminal):"
echo "     nohup python3 monitor.py > logs/monitor.log 2>&1 &"
echo "     echo \$! > logs/monitor.pid"
echo ""
echo "  Stop background monitor:"
echo "     kill \$(cat logs/monitor.pid)"
echo ""
echo "  Watch live:"
echo "     tail -f logs/monitor.log"
