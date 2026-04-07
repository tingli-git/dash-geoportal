#!/usr/bin/env python3
from __future__ import annotations

"""
Utility server for the pre-generated vector tiles.
The default `python -m http.server` does not expose Access-Control-Allow-Origin
so browsers running the dashboard on a different port trigger CORS errors.
Use this script instead to serve tiles with permissive CORS.

Example:
    ./scripts/start_tile_server.py --directory /datawaha/.../datepalms_tiles --port 8766
"""

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import argparse


class CORSRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve vector tiles with CORS headers")
    parser.add_argument(
        "--directory",
        "-d",
        type=Path,
        default=Path("datepalms_tiles"),
        help="Document root for the tiles folder",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host/interface to bind to",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8766,
        help="TCP port to listen on",
    )
    args = parser.parse_args()

    if not args.directory.is_dir():
        raise SystemExit(f"Tiles directory not found: {args.directory}")

    from functools import partial

    handler_class = partial(CORSRequestHandler, directory=str(args.directory.resolve()))
    httpd = ThreadingHTTPServer((args.host, args.port), handler_class)
    try:
        print(f"Serving {args.directory.resolve()} on http://{args.host}:{args.port}")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down tile server")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
