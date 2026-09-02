"""Serve web/ locally with the headers Netlify will actually send.

`python3 -m http.server` sends no Content-Security-Policy, so the site looks
fine locally and then loses every colour in production — which is exactly what
happened: the CSP in netlify.toml has no 'unsafe-inline', and the UI was
colouring chips with style attributes. Reading the headers out of netlify.toml
rather than restating them here means the two cannot drift.

    python3 scripts/serve_web.py [port]
"""

from __future__ import annotations

import re
import sys
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
NETLIFY_TOML = ROOT / "netlify.toml"

# Header lines inside a [headers.values] block: `Name = "value"`.
HEADER_RE = re.compile(r'^\s*([A-Za-z][A-Za-z0-9-]*)\s*=\s*"(.*)"\s*$')


def headers_for_all_paths() -> dict[str, str]:
    """Pull the `for = "/*"` header block out of netlify.toml."""
    if not NETLIFY_TOML.exists():
        return {}
    out: dict[str, str] = {}
    in_block = False
    for line in NETLIFY_TOML.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("[["):
            in_block = False
        if stripped.startswith('for =') or stripped.startswith("for="):
            in_block = stripped.split("=", 1)[1].strip().strip('"') == "/*"
            continue
        if in_block and stripped.startswith("["):
            continue
        if in_block:
            m = HEADER_RE.match(line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


class Handler(SimpleHTTPRequestHandler):
    extra_headers: dict[str, str] = {}

    def end_headers(self):
        for name, value in self.extra_headers.items():
            self.send_header(name, value)
        super().end_headers()

    def log_message(self, fmt, *args):
        if "404" in (fmt % args):
            super().log_message(fmt, *args)


def main() -> int:
    if not (WEB / "data" / "index.json").exists():
        print("web/data is missing — run: python3 scripts/10_export_web.py", file=sys.stderr)
        return 1
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8610
    Handler.extra_headers = headers_for_all_paths()
    if "Content-Security-Policy" not in Handler.extra_headers:
        print("WARNING: no Content-Security-Policy found in netlify.toml — "
              "production will not match this.", file=sys.stderr)
    for name in Handler.extra_headers:
        print(f"  sending {name}")
    print(f"\nserving {WEB.relative_to(ROOT)} on http://localhost:{port}")
    HTTPServer(("", port), partial(Handler, directory=str(WEB))).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
