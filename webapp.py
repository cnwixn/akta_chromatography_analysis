#!/usr/bin/env python3
"""Local web UI for the AKTA IMAC / SEC chromatogram scripts.

The plotting itself stays in `imac_analysis.py` and `sec_analysis.py`. This file
only collects the parameters, feeds them into those modules and serves the
resulting figures to the browser.

Usage
-----
    python webapp.py            # open http://127.0.0.1:8765
    python webapp.py --open     # ... and open the browser automatically
    python webapp.py --port 9000 --no-open
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import shutil
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
WORK_ROOT = HERE / "temp"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import imac_analysis  # noqa: E402
import sec_analysis  # noqa: E402

MODULES = {"imac": imac_analysis, "sec": sec_analysis}

LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
MAX_JOBS = 20
IGNORED_NAMES = {"log.md"}


def _number(value, label: str):
    """Empty / None means 'automatic' (None); anything else must parse."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number, got {value!r}") from None


def _pair(low_value, high_value, label: str, require_both: bool = False):
    """One missing bound stays automatic; the analysis scripts fill it in."""
    low = _number(low_value, f"{label} lower bound")
    high = _number(high_value, f"{label} upper bound")
    if low is None and high is None:
        return None
    if require_both and (low is None or high is None):
        raise ValueError(f"{label}: give both bounds or leave both empty.")
    if low is not None and high is not None and not low < high:
        raise ValueError(f"{label}: lower bound must be smaller than upper bound.")
    return (low, high)


def _job_dir() -> Path:
    """Each run gets its own folder inside the app folder, not the system temp."""
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    while True:
        candidate = WORK_ROOT / f"run-{uuid.uuid4().hex[:10]}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue


def _safe_name(name: str) -> str:
    cleaned = Path(str(name)).name.strip() or "chromatogram.csv"
    for bad in '<>:"/\\|?*':
        cleaned = cleaned.replace(bad, "_")
    return cleaned


def _stage_csv(payload: dict) -> tuple[Path, Path]:
    """Copy the input CSV into a private work directory."""
    work = _job_dir()
    csv_b64 = payload.get("csv_b64")
    csv_path = (payload.get("csv_path") or "").strip()

    if csv_b64:
        name = _safe_name(payload.get("csv_name") or "chromatogram.csv")
        if not name.lower().endswith(".csv"):
            name += ".csv"
        target = work / name
        try:
            target.write_bytes(base64.b64decode(csv_b64, validate=True))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Uploaded file could not be decoded: {exc}") from None
    elif csv_path:
        source = Path(csv_path).expanduser()
        if not source.is_file():
            raise ValueError(f"CSV path not found: {source}")
        target = work / _safe_name(source.name)
        shutil.copy2(source, target)
    else:
        raise ValueError("Choose a CSV file or give a path to one.")

    if target.stat().st_size == 0:
        raise ValueError("The CSV file is empty.")
    return work, target


def _run(payload: dict) -> dict:
    technique = str(payload.get("technique") or "imac").lower()
    if technique not in MODULES:
        raise ValueError("technique must be 'imac' or 'sec'.")
    module = MODULES[technique]

    x_limits = _pair(payload.get("x_min"), payload.get("x_max"), "Volume range")
    uv_limits = _pair(payload.get("uv_min"), payload.get("uv_max"), "UV range")
    elution = _pair(payload.get("elution_min"), payload.get("elution_max"), "Elution window", require_both=True)
    if elution is not None and technique != "imac":
        elution = None  # only IMAC scales UV from the elution window

    fraction_y = _number(payload.get("fraction_label_y"), "Fraction label offset")
    dpi = _number(payload.get("dpi"), "DPI")
    width = _number(payload.get("width"), "Figure width")
    height = _number(payload.get("height"), "Figure height")

    if dpi is None:
        dpi = 300.0
    dpi = int(round(dpi))
    if not 50 <= dpi <= 1200:
        raise ValueError("DPI must be between 50 and 1200.")
    if width is None:
        width = 12.0
    if height is None:
        height = 10.0
    if not (3.0 <= width <= 40.0 and 3.0 <= height <= 40.0):
        raise ValueError("Figure size must be between 3 and 40 inches.")

    if elution is not None and x_limits is not None:
        low = x_limits[0] if x_limits[0] is not None else float("-inf")
        high = x_limits[1] if x_limits[1] is not None else float("inf")
        if elution[0] < low or elution[1] > high:
            raise ValueError("The elution window must lie inside the volume range.")

    work, csv_file = _stage_csv(payload)
    job_id = uuid.uuid4().hex[:12]

    stdout = io.StringIO()
    error = None
    with LOCK:
        module.X_LIMITS = x_limits
        module.UV_Y_LIMITS = uv_limits
        module.FRACTION_LABEL_Y = -0.065 if fraction_y is None else fraction_y
        module.FIGURE_DPI = dpi
        module.FIGURE_SIZE = (width, height)
        if hasattr(module, "ELUTION_WINDOW"):
            module.ELUTION_WINDOW = elution
        try:
            with contextlib.redirect_stdout(stdout):
                module.main(str(work))
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

    log_text = ""
    log_file = work / "log.md"
    if log_file.is_file():
        log_text = log_file.read_text(encoding="utf-8", errors="replace")
    elif stdout.getvalue():
        log_text = stdout.getvalue()

    files = []
    for item in sorted(work.iterdir()):
        if not item.is_file() or item.name in IGNORED_NAMES or item == csv_file:
            continue
        suffix = item.suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png"}:
            kind = "image"
        elif suffix in {".html", ".htm"}:
            kind = "report"
        else:
            kind = "other"
        files.append({"name": item.name, "kind": kind, "size": item.stat().st_size})

    if error:
        shutil.rmtree(work, ignore_errors=True)
        return {"ok": False, "error": error, "log": log_text}

    outdir = (payload.get("outdir") or "").strip()
    saved_to = None
    if outdir:
        destination = Path(outdir).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        for item in work.iterdir():
            if item.is_file() and item != csv_file:
                shutil.copy2(item, destination / item.name)
        saved_to = str(destination)

    JOBS[job_id] = {"dir": work, "files": {f["name"] for f in files}, "technique": technique}
    while len(JOBS) > MAX_JOBS:
        old_id = next(iter(JOBS))
        shutil.rmtree(JOBS.pop(old_id)["dir"], ignore_errors=True)

    for entry in files:
        entry["url"] = f"/api/artifact?job={job_id}&name={quote(entry['name'])}"

    return {
        "ok": True,
        "job": job_id,
        "technique": technique,
        "csv": csv_file.name,
        "files": files,
        "log": log_text,
        "saved_to": saved_to,
        "settings": {
            "x_limits": x_limits,
            "uv_limits": uv_limits,
            "elution_window": elution,
            "fraction_label_y": module.FRACTION_LABEL_Y,
            "dpi": dpi,
            "figure_size": [width, height],
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AKTAWeb/1.0"

    def log_message(self, fmt, *args):  # keep the console readable
        pass

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload: dict):
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path

        if route in ("/", "/index.html"):
            index = STATIC / "index.html"
            if not index.is_file():
                self._json(500, {"ok": False, "error": "static/index.html is missing."})
                return
            self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            return

        if route.startswith("/static/"):
            target = (STATIC / route[len("/static/"):]).resolve()
            if STATIC not in target.parents or not target.is_file():
                self._json(404, {"ok": False, "error": "not found"})
                return
            ctype = "text/plain; charset=utf-8"
            if target.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif target.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)
            return

        if route == "/api/artifact":
            query = parse_qs(parsed.query)
            job_id = (query.get("job") or [""])[0]
            name = (query.get("name") or [""])[0]
            job = JOBS.get(job_id)
            if not job or name not in job["files"]:
                self._json(404, {"ok": False, "error": "artifact not found"})
                return
            target = job["dir"] / name
            if not target.is_file():
                self._json(404, {"ok": False, "error": "artifact missing on disk"})
                return
            suffix = target.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                ctype = "image/jpeg"
            elif suffix == ".png":
                ctype = "image/png"
            elif suffix in {".html", ".htm"}:
                ctype = "text/html; charset=utf-8"
            else:
                ctype = "text/plain; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)
            return

        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/api/render":
            self._json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._json(400, {"ok": False, "error": "empty request"})
            return
        if length > 128 * 1024 * 1024:
            self._json(413, {"ok": False, "error": "request too large"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"ok": False, "error": f"bad JSON: {exc}"})
            return

        try:
            result = _run(payload)
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._json(200 if result.get("ok") else 422, result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local web UI for the AKTA IMAC/SEC plotting scripts.")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port to listen on (default: 8765)")
    parser.add_argument("--open", action="store_true", help="open the browser once the server is up")
    parser.add_argument("--no-open", action="store_true", help="never open the browser")
    parser.add_argument("--csv", help="preload this CSV in the page and build its figures on load")
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    if args.csv:
        url += "?csv=" + quote(str(Path(args.csv).expanduser().resolve()))
    print(f"AKTA chromatography web UI running at {url}")
    print("Press Ctrl+C to stop.")
    if args.open and not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
