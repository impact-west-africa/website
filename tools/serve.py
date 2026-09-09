#!/usr/bin/env python3
"""Preview site/ locally, with the custom 404 page.

Each route is a directory index (site/give/index.html), so the stdlib server
resolves /give/ on its own; this only adds the branded 404.

Usage:  python3 tools/serve.py [PORT]
"""

import functools
import http.server
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site")


class Handler(http.server.SimpleHTTPRequestHandler):
    def send_error(self, code, message=None, explain=None):
        page = os.path.join(ROOT, "404.html")
        if code == 404 and os.path.exists(page):
            body = open(page, "rb").read()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)


port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
handler = functools.partial(Handler, directory=ROOT)
print("serving site/ at http://localhost:%d  (ctrl-c to stop)" % port)
http.server.ThreadingHTTPServer(("", port), handler).serve_forever()
