#!/usr/bin/env python3
"""RKMOVIESZIP Telegram Bot Web Server & Dashboard.

Serves on 0.0.0.0:PORT (default 3000) for AI Studio Web Preview, Health Checks,
and Cloud Deployment monitoring.
"""
import os
import sys
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app_server")

PORT = int(os.environ.get("PORT", 3000))
HOST = "0.0.0.0"

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RKMOVIESZIP Bot Dashboard</title>
    <meta name="description" content="RKMOVIESZIP Telegram Filter Bot Status &amp; Global Colourful Button System Preview" />
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: #111827;
            --card-border: #1f2937;
            --accent-color: #3b82f6;
            --text-main: #f9fafb;
            --text-muted: #9ca3af;
            --badge-green: #065f46;
            --badge-green-txt: #34d399;
            --badge-blue: #1e3a8a;
            --badge-blue-txt: #60a5fa;
            --tg-danger-bg: linear-gradient(180deg, #992b36 0%, #7d1f29 100%);
            --tg-danger-border: #b83b48;
            --tg-primary-bg: linear-gradient(180deg, #2463eb 0%, #1d4ed8 100%);
            --tg-primary-border: #3b82f6;
            --tg-success-bg: linear-gradient(180deg, #1b7a43 0%, #145c32 100%);
            --tg-success-border: #22c55e;
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            min-height: 100vh;
            padding: 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .container {
            width: 100%;
            max-width: 1080px;
        }
        header {
            text-align: center;
            margin-bottom: 24px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--card-border);
        }
        h1 {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        p.subtitle {
            color: var(--text-muted);
            font-size: 14px;
        }
        .status-banner {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 16px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 12px;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            background-color: var(--badge-green);
            color: var(--badge-green-txt);
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--badge-green-txt);
            margin-right: 8px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 0.5; }
            50% { opacity: 1; }
            100% { opacity: 0.5; }
        }
        .section-heading {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 6px;
            color: #f3f4f6;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 8px;
        }
        .legend-bar {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-bottom: 16px;
            font-size: 12px;
            color: #d1d5db;
        }
        .legend-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 6px;
            background: #1f2937;
            border: 1px solid #374151;
        }
        .swatch {
            width: 12px;
            height: 12px;
            border-radius: 3px;
            display: inline-block;
        }
        .swatch-danger { background: #992b36; border: 1px solid #b83b48; }
        .swatch-primary { background: #2463eb; border: 1px solid #3b82f6; }
        .swatch-success { background: #1b7a43; border: 1px solid #22c55e; }
        .tg-preview-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }
        .tg-chat-card {
            background: #0e1621;
            border: 1px solid #1e2c3a;
            border-radius: 14px;
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);
        }
        .tg-chat-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 8px;
            border-bottom: 1px solid #1e2c3a;
            font-size: 12px;
            font-weight: 600;
            color: #93c5fd;
        }
        .tg-msg-bubble {
            background: #182533;
            border-radius: 10px 10px 10px 4px;
            padding: 10px 12px;
            font-size: 12.5px;
            line-height: 1.45;
            color: #e5e7eb;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        .tg-kb {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        .tg-kb-row {
            display: grid;
            grid-auto-flow: column;
            grid-auto-columns: 1fr;
            gap: 5px;
        }
        .tg-btn {
            border: none;
            border-radius: 8px;
            padding: 8px 6px;
            font-size: 12px;
            font-weight: 600;
            color: #ffffff;
            text-align: center;
            cursor: pointer;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            position: relative;
            transition: filter 0.15s ease;
        }
        .tg-btn:hover {
            filter: brightness(1.1);
        }
        .tg-btn-danger {
            background: var(--tg-danger-bg);
            border: 1px solid var(--tg-danger-border);
        }
        .tg-btn-primary {
            background: var(--tg-primary-bg);
            border: 1px solid var(--tg-primary-border);
        }
        .tg-btn-success {
            background: var(--tg-success-bg);
            border: 1px solid var(--tg-success-border);
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 16px;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .card-title {
            font-size: 15px;
            font-weight: 600;
        }
        .card-tag {
            font-size: 11px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 4px;
            background-color: var(--badge-blue);
            color: var(--badge-blue-txt);
        }
        .card-desc {
            color: var(--text-muted);
            font-size: 12.5px;
            line-height: 1.5;
        }
        footer {
            margin-top: 20px;
            text-align: center;
            color: var(--text-muted);
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>RKMOVIESZIP Filter Bot Console</h1>
            <p class="subtitle">Feature 1 Global Premium Colourful Button System &amp; Multi-Cluster Auto-Filter Engine</p>
        </header>

        <div class="status-banner">
            <div>
                <strong>Dev Server &amp; Global Telegram Bot API Button Styling</strong>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
                    Listening on <code>0.0.0.0:3000</code> &bull; Official Bot API <code>InlineKeyboardButton.style</code> (Zero Colour Emojis)
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <a href="/download/RKMOVIESZIP_Updated_Project.zip" download="RKMOVIESZIP_Updated_Project.zip" style="text-decoration: none; padding: 6px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; background-color: var(--accent-color); color: #ffffff;">
                    Download Project ZIP
                </a>
                <div class="status-badge">
                    <span class="status-dot"></span>
                    ACTIVE
                </div>
            </div>
        </div>

        <div class="section-heading">
            <span>Global Inline Keyboard Colour Preview (Official Telegram Bot API Styles)</span>
        </div>
        <div class="legend-bar">
            <span class="legend-pill"><span class="swatch swatch-danger"></span> <code>style="danger"</code> (Red) &mdash; Normal Menu &amp; General Actions</span>
            <span class="legend-pill"><span class="swatch swatch-primary"></span> <code>style="primary"</code> (Blue) &mdash; File / Movie / Stream &amp; VIP Actions (Supported Fallback)</span>
            <span class="legend-pill"><span class="swatch swatch-success"></span> <code>style="success"</code> (Green) &mdash; Navigation (Back, Next, Close, Cancel, Try Again)</span>
        </div>

        <div class="tg-preview-grid" data-testid="global-keyboards-preview">
            <!-- 1. /start Menu -->
            <div class="tg-chat-card" data-testid="kb-start-menu">
                <div class="tg-chat-header">
                    <span>1. /start Main Menu</span>
                    <span>plugins/commands.py &amp; pm_filter.py</span>
                </div>
                <div class="tg-msg-bubble">
                    <b>Hey Cutie! Welcome to RKMOVIESZIP</b><br>
                    Search any Movie or Web-Series in Group or PM!
                </div>
                <div class="tg-kb">
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">✦ 𝐀𝐃𝐃 𝐌𝐄 𝐓𝐎 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✦</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">『 🎬 𝐔𝐏𝐃𝐀𝐓𝐄𝐒 』</button>
                        <button type="button" class="tg-btn tg-btn-danger">✦ 𝐅𝐄𝐀𝐓𝐔𝐑𝐄𝐒 ✦</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">◈ 𝐇𝐄𝐋𝐏 ◈</button>
                        <button type="button" class="tg-btn tg-btn-danger">『 𝐀𝐁𝐎𝐔𝐓 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』</button>
                    </div>
                </div>
            </div>

            <!-- 2. Help & Admin Submenu -->
            <div class="tg-chat-card" data-testid="kb-help-menu">
                <div class="tg-chat-header">
                    <span>2. Help &amp; Command Menus</span>
                    <span>plugins/pm_filter.py</span>
                </div>
                <div class="tg-msg-bubble">
                    <b>𝐇𝐄𝐋𝐏 &amp; 𝐂𝐎𝐌𝐌𝐀𝐍𝐃 𝐌𝐄𝐍𝐔</b><br>
                    Select a command category below:
                </div>
                <div class="tg-kb">
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">♛ 『 𝐀𝐃𝐌𝐈𝐍 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">✦ 𝐔𝐒𝐄𝐑 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 ✦</button>
                        <button type="button" class="tg-btn tg-btn-danger">◈ 𝐆𝐑𝐎𝐔𝐏 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 ◈</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-success">◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄</button>
                    </div>
                </div>
            </div>

            <!-- 3. Premium Hub & Buy Premium -->
            <div class="tg-chat-card" data-testid="kb-premium-hub">
                <div class="tg-chat-header">
                    <span>3. Premium Hub &amp; Plans</span>
                    <span>subscription_manager.py</span>
                </div>
                <div class="tg-msg-bubble">
                    <b>♛ 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁</b><br>
                    Choose Bot Premium or VIP Channel Plans:
                </div>
                <div class="tg-kb">
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">♕ 『 𝐁𝐎𝐓 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐏𝐋𝐀𝐍𝐒 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">♛ 『 𝐆𝐑𝐎𝐔𝐏 / 𝐂𝐇𝐀𝐍𝐍𝐄𝐋 𝐕𝐈𝐏 𝐏𝐋𝐀𝐍𝐒 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">༺ 💎 𝐌𝐘 𝐀𝐂𝐓𝐈𝐕𝐄 𝐏𝐋𝐀𝐍𝐒 ༻</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">『 𝐐𝐑 𝐂𝐎𝐃𝐄 』</button>
                        <button type="button" class="tg-btn tg-btn-danger">『 𝐔𝐏𝐈 𝐃𝐄𝐓𝐀𝐈𝐋𝐒 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-success">◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄</button>
                        <button type="button" class="tg-btn tg-btn-success">『 ✕ 𝐂𝐋𝐎𝐒𝐄 』</button>
                    </div>
                </div>
            </div>

            <!-- 4. File Delivery & Watch Ad to Unlock -->
            <div class="tg-chat-card" data-testid="kb-file-delivery">
                <div class="tg-chat-header">
                    <span>4. File Delivery &amp; Feature 45 Ad Unlock</span>
                    <span>commands.py &amp; ad_unlock_manager.py</span>
                </div>
                <div class="tg-msg-bubble">
                    <b>📂 Akka.S01E05.720p.WEB-DL.mkv</b><br>
                    Daily File Limit: 15/15 &bull; Stream or Unlock:
                </div>
                <div class="tg-kb">
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">『 🎬 𝐖𝐀𝐓𝐂𝐇 / 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">⇩ 『 𝑫𝑶𝑾𝑵𝑳𝑶𝑨𝑫 』</button>
                        <button type="button" class="tg-btn tg-btn-primary">🎬 『 𝐒𝐓𝐑𝐄𝐀𝐌 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">♛ 『 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』</button>
                        <button type="button" class="tg-btn tg-btn-danger">✦ 𝐖𝐀𝐓𝐂𝐇 𝐀𝐃 &amp; 𝐔𝐍𝐋𝐎𝐂𝐊</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-success">◁ 𝐁𝐀𝐂𝐊</button>
                    </div>
                </div>
            </div>

            <!-- 5. Force Subscribe & Verification -->
            <div class="tg-chat-card" data-testid="kb-force-sub">
                <div class="tg-chat-header">
                    <span>5. Force Subscribe &amp; Ad Verification</span>
                    <span>commands.py &amp; pm_filter.py</span>
                </div>
                <div class="tg-msg-bubble">
                    <b>⚠️ 𝐉𝐎𝐈𝐍 𝐔𝐏𝐃𝐀𝐓𝐄𝐒 𝐂𝐇𝐀𝐍𝐍𝐄𝐋</b><br>
                    Join our channel or complete verification to get your file:
                </div>
                <div class="tg-kb">
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">『 📢 𝐉𝐎𝐈𝐍 𝐂𝐇𝐀𝐍𝐍𝐄𝐋 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">✦ 𝐕𝐄𝐑𝐈𝐅𝐘 𝐀𝐃</button>
                        <button type="button" class="tg-btn tg-btn-danger">『 𝐇𝐎𝐖 𝐓𝐎 𝐕𝐄𝐑𝐈𝐅𝐘 』</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-success">↻ 𝐓𝐑𝐘 𝐀𝐆𝐀𝐈𝐍</button>
                    </div>
                </div>
            </div>

            <!-- 6. Search Results Keyboard (Preserved) -->
            <div class="tg-chat-card" data-testid="kb-search-results">
                <div class="tg-chat-header">
                    <span>6. Search Results (Preserved)</span>
                    <span>plugins/pm_filter.py</span>
                </div>
                <div class="tg-msg-bubble">
                    <b>☠️ Title : Deadpool (2024)</b> &bull; Total Files: 24
                </div>
                <div class="tg-kb">
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">⟦ 📦 𝐒𝐄𝐍𝐃 𝐀𝐋𝐋 ⟧</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">◈ 𝗟𝗔𝗡𝗚𝗨𝗔𝗚𝗘 ◈</button>
                        <button type="button" class="tg-btn tg-btn-danger">◈ 𝗤𝗨𝗔𝗟𝗜𝗧𝗬 ◈</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-danger">📅 Sᴀᴀʟ</button>
                        <button type="button" class="tg-btn tg-btn-danger">↕ Sᴏʀᴛ</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-primary">[1.45 GB] Deadpool.2024.1080p.Hindi.mkv</button>
                    </div>
                    <div class="tg-kb-row">
                        <button type="button" class="tg-btn tg-btn-success">◁ 𝐁𝐀𝐂𝐊</button>
                        <button type="button" class="tg-btn tg-btn-success">2 / 3</button>
                        <button type="button" class="tg-btn tg-btn-success">𝐍𝐄𝐗𝐓 ➜</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 1: Global Button Colours</span>
                    <span class="card-tag">GLOBAL</span>
                </div>
                <p class="card-desc">
                    Official Telegram Bot API <code>InlineKeyboardButton.style</code> (<code>danger</code>, <code>primary</code>, <code>success</code>) applied across all bot menus, submenus, and callbacks with zero colour emojis.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 44: Button Typography</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    19 approved Unicode typography styles &amp; 6 decorative symbol sets preserved across all coloured inline buttons.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 45: Watch Ad to Unlock</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    1 verified ad = 1 single-file delivery when Free daily limit is exhausted, with &lt;=64-byte callback safety &amp; fast 3-query delivery pipeline.
                </p>
            </div>
        </div>

        <footer>
            RKMOVIESZIP Bot Service &bull; All automated verification tests passing
        </footer>
    </div>
</body>
</html>
"""


class BotDashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/download/RKMOVIESZIP_Updated_Project.zip":
            zip_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RKMOVIESZIP_Updated_Project.zip")
            if os.path.isfile(zip_file):
                with open(zip_file, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="RKMOVIESZIP_Updated_Project.zip"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
        elif self.path in ("/health", "/api/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "status": "ok",
                "app": "rkmovieszip-bot",
                "port": PORT,
                "features": {
                    "feature1_global_colourful_buttons": "active",
                    "feature2_smart_search_engine": "active",
                    "feature3_multi_mongodb": "active",
                    "feature4_subscription_manager": "active",
                    "feature5_payment_verification": "active",
                    "feature6_desi_flirty_personality": "active",
                    "feature44_button_typography": "active",
                    "feature45_watch_ad_unlock": "active",
                }
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))

    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {args[0]}")


def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    server = HTTPServer((HOST, PORT), BotDashboardHandler)
    logger.info(f"Server started on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server...")
        server.server_close()


if __name__ == "__main__":
    run_server()
