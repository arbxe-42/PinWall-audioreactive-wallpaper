"""Static server for checks: serves live-wallpaper/ on http://127.0.0.1:4351 (localhost only).
POST /save?name=foo.png with a PNG body writes test/foo.png (the page's own snapshot of its canvas)."""
import functools
import http.server
import os
import urllib.parse

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(root, "test")
os.makedirs(out, exist_ok=True)


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        name = os.path.basename(urllib.parse.parse_qs(u.query).get("name", ["snap.png"])[0])
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with open(os.path.join(out, name), "wb") as f:
            f.write(body)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()


http.server.ThreadingHTTPServer(("127.0.0.1", 4351), functools.partial(H, directory=root)).serve_forever()
