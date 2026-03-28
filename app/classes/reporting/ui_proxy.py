import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


UI_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
UI_PORT = int(os.getenv("DASHBOARD_PORT", "9988"))
UI_PROXY_TARGET = os.getenv("UI_PROXY_TARGET", f"http://127.0.0.1:{UI_PORT}")

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        upstream = f"{UI_PROXY_TARGET.rstrip('/')}{self.path}"
        request = urllib.request.Request(upstream, method="GET")
        for key, value in self.headers.items():
            if key.lower() == "host":
                continue
            request.add_header(key, value)

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() in HOP_BY_HOP_HEADERS:
                        continue
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except Exception:
            body = b'{"ok":false,"error":"upstream_unavailable"}'
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main():
    server = ThreadingHTTPServer((UI_HOST, UI_PORT), ProxyHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
