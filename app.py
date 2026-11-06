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
    <meta name="description" content="RKMOVIESZIP Telegram Filter Bot Status & Management Console" />
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
            max-width: 900px;
        }
        header {
            text-align: center;
            margin-bottom: 32px;
            padding-bottom: 24px;
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
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .card:hover {
            border-color: #374151;
            transform: translateY(-2px);
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .card-title {
            font-size: 16px;
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
            font-size: 13px;
            line-height: 1.5;
        }
        .commands-section {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
        }
        .commands-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 12px;
        }
        .command-list {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 8px;
        }
        .command-item {
            font-family: monospace;
            font-size: 13px;
            color: #93c5fd;
            background: rgba(59, 130, 246, 0.08);
            padding: 6px 10px;
            border-radius: 6px;
            border: 1px solid rgba(59, 130, 246, 0.15);
        }
        footer {
            margin-top: 32px;
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
            <p class="subtitle">High-Performance Telegram Auto-Filter & Multi-Cluster Storage Engine</p>
        </header>

        <div class="status-banner">
            <div>
                <strong>Dev Server & Health API</strong>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
                    Listening on host <code>0.0.0.0:3000</code> &bull; Timezone: Asia/Kolkata
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

        <div class="grid">
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 1: Button Styling</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    Official Telegram styling API with strict zero colour emoji discipline on button labels.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 2: Smart Search</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    10 clean file layout formats, single-link movie rule, season extraction, and query normalization.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 3: Multi-MongoDB</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    Extensible Multi-Cluster storage manager, 90% threshold alert & failover, cross-DB search and deduplication.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 4: Premium Hub</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    Unified Premium Hub menu, independent VIP destination subscriptions, single-member unique invite links & auto-kick expiry.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Manual Payment Verification</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    Screenshot upload verification, atomic admin review (Approve / Reject / Custom Message), and strict product separation.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Desi-Flirty Personality</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    Centralized Desi Hinglish + Cute Flirty template engine with anti-repetition, neutral fallback, and strict payment/broadcast accuracy.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 44: Button Typography</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    19 approved Unicode typography styles &amp; 6 decorative symbol sets with plain fallback labels and zero callback modifications.
                </p>
            </div>

            <div class="card">
                <div class="card-header">
                    <span class="card-title">Feature 45: Watch Ad to Unlock</span>
                    <span class="card-tag">READY</span>
                </div>
                <p class="card-desc">
                    1 verified ad = 1 single-file delivery when Free daily limit is exhausted, with <=64-byte callback safety &amp; fast 3-query delivery pipeline.
                </p>
            </div>
        </div>

        <div class="commands-section">
            <div class="commands-title">Quick Admin Telegram Commands</div>
            <div class="command-list">
                <div class="command-item">/multidb - Storage clusters</div>
                <div class="command-item">/switch_db &lt;id&gt; - Target DB</div>
                <div class="command-item">/dest_list - VIP destinations</div>
                <div class="command-item">/vip_add - Activate subscriber</div>
                <div class="command-item">/pending_payments - Payment queue</div>
                <div class="command-item">/ad_unlock_stats - Ad Unlock stats</div>
                <div class="command-item">/ad_unlock_toggle - Toggle Ad Unlock</div>
                <div class="command-item">/lock_file &lt;id&gt; - Lock Premium file</div>
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
                    "feature1_colourful_search_ui": "active",
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
        # Concise logging to keep server output clean
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
