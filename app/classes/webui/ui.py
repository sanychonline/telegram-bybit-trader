import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import (
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DASHBOARD_REFRESH_SEC,
)
from classes.reporting.dashboard_data import DashboardDataService
from classes.reporting.storage import APP_SETTINGS_SCHEMA, APP_SECRETS_SCHEMA
from classes.webui.renderers.trader_dashboard import render_trader_dashboard_html


class DashboardService:
    def __init__(self, bybit, storage, logger):
        self.logger = logger
        self.storage = storage
        self.host = DASHBOARD_HOST
        self.port = DASHBOARD_PORT
        self.data = DashboardDataService(bybit, storage)
        self._server = None
        self._thread = None

    def _html(self):
        refresh_sec = max(2, int(self.storage.get_app_setting("dashboard_refresh_sec", DASHBOARD_REFRESH_SEC)))
        refresh_ms = refresh_sec * 1000
        return render_trader_dashboard_html(refresh_ms)

    def _mask_secret(self, value):
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= 6:
            return "*" * len(text)
        return f"{text[:3]}***{text[-2:]}"

    def _settings_payload(self):
        values = self.storage.get_app_settings()
        secrets_meta = self.storage.get_app_secrets_meta()
        settings = {
            key: values.get(key, {}).get("value", schema["default"])
            for key, schema in APP_SETTINGS_SCHEMA.items()
        }
        return {
            "settings": settings,
            "schema": {
                key: {"type": schema["type"]}
                for key, schema in APP_SETTINGS_SCHEMA.items()
            },
            "secrets": {
                key: {
                    "configured": bool(meta.get("configured")),
                    "masked": "Saved" if meta.get("configured") else "",
                    "source": meta.get("source") or "missing",
                }
                for key, meta in secrets_meta.items()
            },
            "secret_schema": {
                key: {"type": schema["type"]}
                for key, schema in APP_SECRETS_SCHEMA.items()
            },
        }

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

                if path_only == "/api/settings":
                    payload = json.dumps(service._settings_payload()).encode("utf-8")
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

            def do_POST(self):
                path_only = self.path.split("?", 1)[0]
                if path_only != "/api/settings":
                    self.send_response(404)
                    self.end_headers()
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0") or 0)
                except Exception:
                    length = 0

                try:
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except Exception:
                    self.send_response(400)
                    self.end_headers()
                    return

                try:
                    updates = service.storage.update_app_settings(payload.get("settings") or {})
                    updated_secrets = service.storage.update_app_secrets(payload.get("secrets") or {})
                    response = json.dumps({
                        "ok": True,
                        "updated": updates,
                        "updated_secrets": list(updated_secrets.keys()),
                        "settings": service._settings_payload()["settings"],
                    }).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                except Exception as exc:
                    response = json.dumps({
                        "ok": False,
                        "error": str(exc),
                    }).encode("utf-8")
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)

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
