#!/usr/bin/env python3
"""Start a temporary Cloudflare Quick Tunnel, then launch Talkin1's bot.py."""
from __future__ import annotations

import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
URL_PATTERN = re.compile(r"https://[A-Za-z0-9.-]+\.trycloudflare\.com")


def get_media_port() -> int:
    value = os.environ.get("PORT") or os.environ.get("ASSET_HTTP_PORT")
    if not value:
        try:
            from dotenv import dotenv_values

            env_file = dotenv_values(ROOT / ".env")
            value = env_file.get("PORT") or env_file.get("ASSET_HTTP_PORT")
        except Exception:
            value = None
    port = int(value or "8080")
    if not 1 <= port <= 65535:
        raise ValueError(f"PORT/ASSET_HTTP_PORT is outside 1..65535: {port}")
    return port


def cloudflared_path() -> Path:
    override = os.environ.get("CLOUDFLARED_BIN")
    target = Path(override).expanduser() if override else Path.home() / ".local" / "bin" / "cloudflared"
    if target.is_file() and os.access(target, os.X_OK):
        return target

    machine = platform.machine().lower()
    release = {
        "x86_64": "cloudflared-linux-amd64",
        "amd64": "cloudflared-linux-amd64",
        "aarch64": "cloudflared-linux-arm64",
        "arm64": "cloudflared-linux-arm64",
        "armv7l": "cloudflared-linux-arm",
        "armv7": "cloudflared-linux-arm",
        "i386": "cloudflared-linux-386",
        "i486": "cloudflared-linux-386",
        "i586": "cloudflared-linux-386",
        "i686": "cloudflared-linux-386",
    }.get(machine)
    if not release:
        raise RuntimeError(f"Unsupported CPU architecture for cloudflared: {machine}")

    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{release}"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + f".download-{os.getpid()}")
    print("[QUICK-TUNNEL] Downloading the official cloudflared binary...", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Talkin1-QuickTunnel"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temp.open("wb") as output:
            shutil.copyfileobj(response, output)
        temp.chmod(0o755)
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()
    return target


def stop_process(process: Optional[subprocess.Popen], name: str) -> None:
    if process is None or process.poll() is not None:
        return
    print(f"[QUICK-TUNNEL] Stopping {name}...", flush=True)
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    if not (ROOT / "bot.py").is_file():
        print("[QUICK-TUNNEL] bot.py must be beside run_with_quick_tunnel.py.", file=sys.stderr, flush=True)
        return 1

    tunnel: Optional[subprocess.Popen] = None
    bot: Optional[subprocess.Popen] = None
    try:
        port = get_media_port()
        binary = cloudflared_path()
        print(f"[QUICK-TUNNEL] Connecting the temporary tunnel to local port {port}...", flush=True)
        tunnel = subprocess.Popen(
            [str(binary), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        tunnel_url: queue.Queue[str] = queue.Queue(maxsize=1)

        def forward_tunnel_logs() -> None:
            assert tunnel is not None and tunnel.stdout is not None
            for line in tunnel.stdout:
                line = line.rstrip()
                if line:
                    print(f"[cloudflared] {line}", flush=True)
                match = URL_PATTERN.search(line)
                if match and tunnel_url.empty():
                    try:
                        tunnel_url.put_nowait(match.group(0))
                    except queue.Full:
                        pass

        log_thread = threading.Thread(target=forward_tunnel_logs, name="cloudflared-log", daemon=True)
        log_thread.start()

        deadline = time.monotonic() + 60
        public_url = None
        while time.monotonic() < deadline:
            if tunnel.poll() is not None:
                raise RuntimeError(f"cloudflared exited with code {tunnel.returncode} before creating a URL")
            try:
                public_url = tunnel_url.get(timeout=1)
                break
            except queue.Empty:
                continue
        if not public_url:
            raise TimeoutError("No trycloudflare.com URL appeared in cloudflared's first 60 seconds of output")

        env = os.environ.copy()
        env["PUBLIC_MEDIA_URL"] = public_url
        print(f"[QUICK-TUNNEL] Public media URL: {public_url}", flush=True)
        print("[QUICK-TUNNEL] Starting bot.py with this URL in PUBLIC_MEDIA_URL.", flush=True)
        bot = subprocess.Popen([sys.executable, "-u", str(ROOT / "bot.py")], cwd=ROOT, env=env)

        while bot.poll() is None:
            if tunnel.poll() is not None:
                raise RuntimeError("cloudflared stopped; media links are no longer reachable")
            time.sleep(2)
        return int(bot.returncode or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"[QUICK-TUNNEL] ERROR: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        stop_process(bot, "bot.py")
        stop_process(tunnel, "cloudflared")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(143))
    raise SystemExit(main())
