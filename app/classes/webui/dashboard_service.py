import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from classes.config import BRAND_NAME, DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_REFRESH_SEC
from classes.reporting.dashboard_data import DashboardDataService
from classes.webui.renderers.trader_dashboard import render_trader_dashboard_html


class DashboardService:
    def __init__(self, bybit, storage, logger):
        self.logger = logger
        self.host = DASHBOARD_HOST
        self.port = DASHBOARD_PORT
        self.refresh_sec = max(2, DASHBOARD_REFRESH_SEC)
        self.data = DashboardDataService(bybit, storage)
        self._server = None
        self._thread = None

    def _html(self):
        refresh_ms = self.refresh_sec * 1000
        return render_trader_dashboard_html(BRAND_NAME, refresh_ms)

    def _make_handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                path_only = self.path.split("?", 1)[0]

                if path_only in ["/", "/index.html"]:
                    body = service._html().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if path_only.startswith("/api/stats"):
                    range_key = "all"
                    if "?" in self.path:
                        query = self.path.split("?", 1)[1]
                        for item in query.split("&"):
                            if item.startswith("range="):
                                value = item.split("=", 1)[1].strip().lower()
                                if value in ["today", "current_month", "month", "quarter", "previous_month", "half_year", "year", "previous_year", "all"]:
                                    range_key = value
                                break
                    payload = json.dumps(service.data.build_stats(range_key)).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if path_only.startswith("/api/equity"):
                    range_key = "all"
                    if "?" in self.path:
                        query = self.path.split("?", 1)[1]
                        for item in query.split("&"):
                            if item.startswith("range="):
                                value = item.split("=", 1)[1].strip().lower()
                                if value in ["today", "current_month", "month", "quarter", "previous_month", "half_year", "year", "previous_year", "all"]:
                                    range_key = value
                                break
                    payload = json.dumps(service.data.build_equity_curve(range_key)).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if path_only == "/health":
                    payload = b'{"ok":true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                self.send_response(404)
                self.end_headers()

        return Handler

    async def run(self):
        if self._thread and self._thread.is_alive():
            while True:
                await asyncio.sleep(3600)

        self._server = ThreadingHTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.logger.info(f"Dashboard started | host={self.host} port={self.port}")

        while True:
            await asyncio.sleep(3600)
