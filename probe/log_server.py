"""Tiny log server for the probe wallpaper: keeps the latest report per screen in probe/reports/.

Run: listener/.venv/Scripts/python.exe probe/log_server.py
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "reports")
os.makedirs(OUT, exist_ok=True)


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            d = json.loads(body)
            key = f"{d['screen']['w']}x{d['screen']['h']}"
            with open(os.path.join(OUT, f"report_{key}.json"), "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1)
        except Exception as e:  # keep serving whatever arrives
            print("bad report", e)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("probe log server on 127.0.0.1:4361")
    ThreadingHTTPServer(("127.0.0.1", 4361), H).serve_forever()
