import hmac
import html
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOG = logging.getLogger(__name__)


def start_auth_server(client) -> None:
    port = int(os.getenv("PORT", "0") or 0)
    if not port:
        return
    setup_key = os.getenv("SCHWAB_AUTH_SETUP_KEY", "")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path != "/schwab-auth":
                self.send_error(404)
                return
            status = (
                "A token is stored. Use this form only when Schwab authorization needs to be replaced."
                if os.path.exists(client.token_file)
                else "Schwab authorization is required."
            )
            auth_url = html.escape(client.authorization_url(), quote=True)
            self.page(
                200,
                f'<h1>Schwab authorization</h1><p>{status}</p>'
                f'<p><a href="{auth_url}" target="_blank">1. Sign in to Schwab</a></p>'
                '<p>2. Paste the complete redirected URL below.</p>'
                '<form method="post"><input type="password" name="setup_key" placeholder="Setup key" required><br>'
                '<textarea name="callback_url" rows="5" cols="80" required></textarea><br>'
                '<button type="submit">Authorize</button></form>',
            )

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            form = parse_qs(self.rfile.read(length).decode()) if 0 < length <= 20_000 else {}
            if not setup_key or not hmac.compare_digest(form.get("setup_key", [""])[0], setup_key):
                self.page(403, "Setup key is incorrect.")
                return
            try:
                client.exchange_callback_url(form.get("callback_url", [""])[0])
                self.page(200, "Schwab authorization succeeded. Remove the setup key from Railway.")
            except Exception as exc:
                LOG.warning("Schwab authorization failed: %s", exc)
                self.page(400, f"Authorization failed: {html.escape(str(exc))}")

        def page(self, status: int, body: str):
            content = f'<!doctype html><meta charset="utf-8"><body>{body}</body>'.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            LOG.info("auth page: " + format, *args)

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

