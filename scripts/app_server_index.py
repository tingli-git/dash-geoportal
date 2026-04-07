#!/usr/bin/env python3
"""Run a simple HTTP server that always exposes a friendly index for the Date Palm app server."""

from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Iterable

BASE_DIR = Path("/datawaha/esom/DatePalmCounting/Geoportal/Datepalm/app_server").resolve()


def _format_listing(paths: Iterable[Path]) -> str:
    entries = []
    for path in sorted(paths, key=lambda p: p.name.lower()):
        rel = path.relative_to(BASE_DIR)
        if path.is_dir():
            label = f"<strong>{rel}/</strong>"
        else:
            label = rel.name
        href = f"/{rel.as_posix()}"
        entries.append(f"<li><a href=\"{href}\">{label}</a></li>")
    return "\n".join(entries)


class AppServerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def list_directory(self, path):
        entries = Path(path).iterdir()
        html = f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <title>Date Palm App Server</title>
    <style>
      body {{font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem;}}
      h1 {{color: #0f4c81;}}
      ul {{line-height: 1.7; list-style: none; padding: 0;}}
      li {{margin-bottom: 0.5rem;}}
      a {{padding: 0.3rem 0.6rem; border-radius: 5px; text-decoration: none; border: 1px solid #cfd8da; color: #0f4c81;}}
      a:hover {{background: #0f4c81; color: #fff;}}
    </style>
  </head>
  <body>
    <h1>Date Palm App Server</h1>
    <p>The server is serving <code>{BASE_DIR}</code>.</p>
    <ul>
      {_format_listing(entries)}
    </ul>
  </body>
</html>"""
        encoded = html.encode("utf-8", "surrogateescape")
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    addr = ("0.0.0.0", 8766)
    print(f"Serving {BASE_DIR} on http://{addr[0]}:{addr[1]}")
    server = HTTPServer(addr, AppServerHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
