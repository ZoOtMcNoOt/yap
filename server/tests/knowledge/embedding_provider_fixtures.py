"""Deterministic HTTP embedding protocol fixture; never a model qualification."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading


@contextmanager
def embedding_server():
    requests = []
    settings = {
        "transform": lambda value: value,
        "status": 200,
        "release": None,
        "entered": threading.Event(),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            settings["entered"].set()
            if settings["release"] is not None:
                settings["release"].wait(3)
            response = {
                "object": "list",
                "model": body["model"],
                "data": [
                    {
                        "index": index,
                        "object": "embedding",
                        "embedding": [0.25 + index / 100] * 768,
                    }
                    for index, _text in enumerate(body["input"])
                ],
            }
            encoded = json.dumps(settings["transform"](response)).encode()
            self.send_response(settings["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, settings
    finally:
        if settings["release"] is not None:
            settings["release"].set()
        server.shutdown()
        server.server_close()
        thread.join(2)
