import base64
import json
import os
import random
import ssl
import socket
import struct
import hashlib
import threading
import time
import uuid
import subprocess
import shutil
import re
import queue
import mimetypes
from urllib.parse import urlparse, unquote
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from collections import defaultdict
from pathlib import Path

try:
    from fontTools.ttLib import TTFont
except Exception:
    TTFont = None

import requests
try:
    from supabase import create_client
except Exception:
    create_client = None
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# Media / music / gifts ported from the supplied Giant bot + Talkin APK.
# The actual Talkin transport remains the authoritative transport.
# ============================================================
try:
    import yt_dlp
except Exception:
    yt_dlp = None
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    Image = ImageDraw = ImageFont = None
    PIL_AVAILABLE = False
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:
    arabic_reshaper = None
    get_display = None

MUSIC_MAX_SECONDS = int(os.getenv("MUSIC_MAX_SECONDS", "900"))
MUSIC_COOLDOWN = float(os.getenv("MUSIC_COOLDOWN", "15"))
# Optional YouTube Netscape cookies supplied as a Railway secret variable.
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "").strip()
YOUTUBE_COOKIE_FILE = None
if YOUTUBE_COOKIES:
    try:
        cookie_text = YOUTUBE_COOKIES.replace("\\n", "\n").replace("\\t", "\t")
        if not cookie_text.startswith("# Netscape HTTP Cookie File"):
            cookie_text = "# Netscape HTTP Cookie File\n" + cookie_text
        YOUTUBE_COOKIE_FILE = "/tmp/youtube_cookies.txt"
        Path(YOUTUBE_COOKIE_FILE).write_text(cookie_text, encoding="utf-8")
    except Exception:
        YOUTUBE_COOKIE_FILE = None

# Gift images copied verbatim from the supplied Giant Chat bot assets/.
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
GIFT_IMAGE_FILES = {
    str(i): [ASSETS_DIR / f"gift_{i:02d}_1.png", ASSETS_DIR / f"gift_{i:02d}_2.png", ASSETS_DIR / f"gift_{i:02d}_3.png"]
    for i in range(1, 15)
}
# Railway exposes this service through RAILWAY_PUBLIC_DOMAIN after a public domain is generated.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
GIFT_PUBLIC_BASE_URL = os.getenv("GIFT_PUBLIC_BASE_URL", "").strip().rstrip("/")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()

def _public_base_url():
    domain = RAILWAY_PUBLIC_DOMAIN
    if domain:
        if not domain.startswith(("http://", "https://")):
            domain = "https://" + domain
        return domain.rstrip("/")
    return (PUBLIC_BASE_URL or GIFT_PUBLIC_BASE_URL).rstrip("/")

MEDIA_PUBLIC_BASE_URL = _public_base_url()
ASSET_HTTP_PORT = int(os.getenv("PORT", "8080"))
ASSET_HTTP_ENABLED = os.getenv("ASSET_HTTP_ENABLED", "1") == "1"

GIFT_CATALOG = {
    "1": ("🌹", "وردة"), "2": ("❤️", "قلب"), "3": ("😘", "قبلة"),
    "4": ("🧸", "دب"), "5": ("🎂", "كعكة"), "6": ("🎆", "ألعاب نارية"),
    "7": ("⚡", "برق"), "8": ("👑", "تاج"), "9": ("👸", "أميرة"),
    "10": ("🏎️", "سيارة"), "11": ("✈️", "طائرة"), "12": ("🐉", "تنين"),
    "13": ("🚀", "سفينة فضاء"), "14": ("🏰", "قصر"),
}

# ============================================================
# Talkin/ChatP protocol ported from the supplied Android APK.
# The realtime protocol is protobuf over binary WebSocket frames.
# Authentication is protobuf over POST /api?auth_new.
# ============================================================

BOT_ID = os.getenv("BOT_ID", "").strip()
BOT_PWD = os.getenv("BOT_PWD", "")
BOT_MASTER = os.getenv("BOT_MASTER", "").strip()
INVITE_SENDER_NAME = os.getenv("INVITE_SENDER_NAME", "السفير").strip() or "السفير"
GROUP_TO_JOIN = os.getenv("GROUP_TO_JOIN", "").strip()

# Persistent Giant-style bot data. The owner/master has unlimited points.
DATA_DIR = Path(__file__).resolve().parent
MASTERS_FILE = DATA_DIR / "masters.json"
VIP_FILE = DATA_DIR / "vip_users.json"
VERIFIED_FILE = DATA_DIR / "verified_users.json"
POINTS_FILE = DATA_DIR / "points.json"
MESSAGES_FILE = DATA_DIR / "messages.json"
PUBLISHED_FILE = DATA_DIR / "published_posts.json"
MONITORED_USERS_FILE = DATA_DIR / "monitored_users.json"
MONITOR_DEBUG = os.getenv("MONITOR_DEBUG", "1") == "1"

# Giant Chat gift costs/labels; images remain the local Giant assets.
GIFT_COSTS = {"1":10,"2":20,"3":30,"4":50,"5":80,"6":150,"7":200,"8":500,"9":800,"10":1000,"11":1500,"12":3000,"13":5000,"14":8000}


API_BASE_URL = os.getenv("API_BASE_URL", "https://chatp.net/api?").rstrip("?") + "?"
HOST = os.getenv("HOST_HEADER", "chatp.net").strip()
WS_HOSTS = [x.strip() for x in os.getenv("WS_HOSTS", "chatp.net").split(",") if x.strip()]
DEFAULT_PORT = os.getenv("SOCKET_PORT", "5335").strip()
WS_PATHS = [x.strip() if x.strip().startswith("/") else "/" + x.strip()
            for x in os.getenv("WS_PATHS", "/server").split(",") if x.strip()]
# RawWebSocket uses this timeout as the heartbeat interval. The receive loop
# sends a WebSocket ping whenever the interval expires without traffic.
WS_HEARTBEAT_SECONDS = max(5, int(os.getenv("WS_HEARTBEAT_SECONDS", "20")))
if not WS_PATHS:
    WS_PATHS = ["/server"]
REFERRER_URL = os.getenv("REFERRER_URL", "")
SDK = os.getenv("SDK", "35")
LANGUAGE = os.getenv("LANGUAGE", "").strip()
if not LANGUAGE:
    try:
        from jnius import autoclass
        Locale = autoclass("java.util.Locale")
        LANGUAGE = str(Locale.getDefault().getLanguage())
    except Exception:
        LANGUAGE = "en"
def android_prop(name, fallback=""):
    # Pydroid may not put Android toolbox binaries on PATH, so try the
    # absolute locations used by Android as well.
    for cmd in (("/system/bin/getprop", name), ("getprop", name)):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2).decode("utf-8", "ignore").strip()
            if out:
                return out
        except Exception:
            pass
    return fallback


def android_secure_id():
    # First try Android's real Java API (the APK obtains its ID from
    # Settings.Secure.ANDROID_ID). This avoids inventing a UUID.
    try:
        from jnius import autoclass
        Build = autoclass("android.os.Build")
        ActivityThread = autoclass("android.app.ActivityThread")
        SettingsSecure = autoclass("android.provider.Settings$Secure")
        app = ActivityThread.currentApplication()
        if app is not None:
            value = SettingsSecure.getString(app.getContentResolver(), SettingsSecure.ANDROID_ID)
            if value:
                return str(value).replace("@", "_")
    except Exception:
        pass

    for cmd in (("/system/bin/settings", "get", "secure", "android_id"),
                ("settings", "get", "secure", "android_id")):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2).decode("utf-8", "ignore").strip()
            if out and out.lower() not in ("null", "unknown"):
                return out.replace("@", "_")
        except Exception:
            pass
    return ""


def android_build_info():
    manufacturer = android_prop("ro.product.manufacturer", "")
    model = android_prop("ro.product.model", "")
    sdk = android_prop("ro.build.version.sdk", "")
    try:
        from jnius import autoclass
        Build = autoclass("android.os.Build")
        manufacturer = manufacturer or str(Build.MANUFACTURER)
        model = model or str(Build.MODEL)
        sdk = sdk or str(Build.VERSION.SDK_INT)
    except Exception:
        pass
    return manufacturer.strip(), model.strip(), sdk.strip()


# Railway has no Android runtime and this bot does not need the phone's
# Android ID or Android system properties for publishing.  Talkin's wire
# protocol still requires device_id/device_model fields, so keep a stable
# synthetic profile in the exact APK fingerprint format without probing Android.
DEVICE_ID = "chatbuz-railway"
_MANUFACTURER = "samsung"
_MODEL = "SM-G998B"
SDK = os.getenv("SDK", "35").strip() or "35"
DEVICE_MODEL = os.getenv("DEVICE_MODEL", "").strip() or (
    "444$" + _MANUFACTURER + "-" + _MODEL + "$" + SDK
)

API_VER = "2"
CLIENT_VER = "1"
AUTH_VER = "444"
AUTH_METHOD = "1"

# Keep these enabled for easy troubleshooting.
DEBUG = os.getenv("DEBUG", "1") == "1"
RAW_DIAGNOSTIC = os.getenv("RAW_DIAGNOSTIC", "0") == "1"
ACK_ROOM_EVENTS = os.getenv("ACK_ROOM_EVENTS", "1") == "1"
AUTO_HELP = os.getenv("AUTO_HELP", "1") == "1"
BANNED_WORDS = {w.strip().lower() for w in os.getenv("BANNED_WORDS", "").split(",") if w.strip()}
AUTO_BAN_WORDS = os.getenv("AUTO_BAN_WORDS", "0") == "1"

# ------------------------- protobuf wire helpers -------------------------

def _varint(n: int) -> bytes:
    n = int(n)
    if n < 0:
        n &= (1 << 64) - 1
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _field_string(num: int, value: str, force: bool = False) -> bytes:
    if value is None:
        value = ""
    raw = str(value).encode("utf-8")
    # APK protobuf classes use presence bits, so forced empty fields are
    # useful for AuthRequest where setters are called even for empty captcha.
    if not raw and not force:
        return b""
    return _varint((num << 3) | 2) + _varint(len(raw)) + raw


def _field_int32(num: int, value: int, force: bool = False) -> bytes:
    value = int(value)
    if value == 0 and not force:
        return b""
    return _varint(num << 3) + _varint(value)


def encode_auth_request(username: str, password: str, captcha_code: str = "", captcha_url: str = "") -> bytes:
    # AuthRequest fields from net.chatp.data.AuthRequest.smali:
    # 1 type, 2 username, 3 password, 4 captchaCode, 5 captchaUrl,
    # 6 sid, 7 sdk, 8 os, 9 ver, 10 clientVer, 11 deviceId,
    # 12 deviceModel, 13 language, 14 method.
    parts = [
        _field_string(1, "login", True),
        _field_string(2, username, True),
        _field_string(3, password, True),
        _field_string(4, captcha_code, True),
        _field_string(5, captcha_url, True),
        _field_string(6, str(uuid.uuid4()), True),
        _field_string(7, SDK, True),
        _field_string(8, "android@" + REFERRER_URL, True),
        _field_string(9, AUTH_VER, True),
        _field_string(10, "2", True),
        _field_string(11, DEVICE_ID, True),
        _field_string(12, DEVICE_MODEL, True),
        _field_string(13, LANGUAGE, True),
        _field_string(14, AUTH_METHOD, True),
    ]
    return b"".join(parts)


def encode_query(action: str, *, type_: str = None, length: str = None,
                 to: str = None, body: str = None, room: str = None,
                 url: str = None, uid: str = None, password: str = None,
                 state: str = None, value: str = None, value1: str = None,
                 int_value: int = None, long_value: int = None,
                 use_bin: int = None, captcha_code: str = None,
                 captcha_url: str = None, id_: str = None,
                 product_id: str = None, order_id: str = None,
                 purchase_time: str = None, purchase_state: str = None,
                 payload: str = None, token: str = None,
                 force_int_value: bool = False) -> bytes:
    # Query fields from net.chatp.data.Query.smali.
    vals = {
        1: action, 2: type_, 3: length, 4: to, 5: body, 6: room,
        7: url, 8: uid, 9: password, 10: state, 11: value, 12: value1,
        16: captcha_code, 17: captcha_url, 18: id_, 19: product_id,
        20: order_id, 21: purchase_time, 22: purchase_state,
        23: payload, 24: token,
    }
    out = bytearray()
    out += _field_string(1, action, True)
    for num in range(2, 25):
        if num in (13, 14, 15):
            continue
        if num in vals and vals[num] is not None:
            out += _field_string(num, vals[num], True)
    if int_value is not None:
        out += _field_int32(13, int_value, force_int_value)
    if long_value is not None:
        out += _varint(14 << 3) + _varint(int(long_value))
    if use_bin is not None:
        out += _field_int32(15, use_bin, True)
    return bytes(out)


def read_varint(data: bytes, pos: int):
    value = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, pos
        shift += 7
        if shift > 70:
            raise ValueError("invalid protobuf varint")
    raise ValueError("truncated protobuf varint")


def decode_message(data: bytes):
    """Generic protobuf decoder; enough for the APK schemas and nested events."""
    fields = defaultdict(list)
    pos = 0
    while pos < len(data):
        key, pos = read_varint(data, pos)
        num, wire = key >> 3, key & 7
        if num == 0:
            break
        if wire == 0:
            value, pos = read_varint(data, pos)
            fields[num].append(value)
        elif wire == 1:
            if pos + 8 > len(data): raise ValueError("truncated fixed64")
            fields[num].append(data[pos:pos+8]); pos += 8
        elif wire == 2:
            length, pos = read_varint(data, pos)
            if pos + length > len(data): raise ValueError("truncated bytes")
            fields[num].append(data[pos:pos+length]); pos += length
        elif wire == 5:
            if pos + 4 > len(data): raise ValueError("truncated fixed32")
            fields[num].append(data[pos:pos+4]); pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
    return fields


def as_text(v):
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return str(v)


def first_text(fields, num, default=""):
    vals = fields.get(num)
    return as_text(vals[0]) if vals else default


def first_int(fields, num, default=0):
    vals = fields.get(num)
    if not vals: return default
    return int(vals[0]) if isinstance(vals[0], int) else default


def decode_auth_result(data: bytes):
    f = decode_message(data)
    # AuthResult: 1 result, 2 userId, 3 photoUrl, 4 photoVersion,
    # 5 id, 6 message, 7 server, 8 method, 9 enablePing, 10 enableRoomAck.
    return {
        "result": first_text(f, 1),
        "user_id": first_text(f, 2),
        "photo_url": first_text(f, 3),
        "photo_version": first_text(f, 4),
        "id": first_text(f, 5),
        "message": first_text(f, 6),
        "server": first_text(f, 7),
        "method": first_text(f, 8),
        "enable_ping": bool(first_int(f, 9)),
        "enable_room_ack": bool(first_int(f, 10)),
    }


def decode_result_message(data: bytes):
    f = decode_message(data)
    result = {
        "handler_id": first_int(f, 1),
        "type": first_text(f, 2),
        "page": first_int(f, 3),
        "uid": first_text(f, 4),
        "value": first_text(f, 5),
        "int_value": first_int(f, 6),
    }
    # ResultMessage nested protobuf fields:
    # 8 StreamEvent, 9 ChatMessage, 10 RoomEvent, 11 users,
    # 12 rooms, 13 CallInfo, 14 RoomAdmin, 15 LoginInfo, 16 sessions.
    if 8 in f:
        result["stream_event"] = decode_generic(f[8][0])
    if 9 in f:
        result["chat_message"] = decode_generic(f[9][0])
    if 10 in f:
        result["room_event"] = decode_generic(f[10][0])
    if 11 in f:
        result["users"] = [decode_generic(x) for x in f[11]]
    if 12 in f:
        result["rooms"] = [decode_generic(x) for x in f[12]]
    if 13 in f:
        result["call_info"] = decode_generic(f[13][0])
    if 14 in f:
        # Keep RoomAdmin field 10 as raw protobuf bytes so occupants_list can
        # decode each UserItem exactly instead of losing the nested structure.
        ra_fields = decode_message(f[14][0])
        ra = decode_generic(f[14][0])
        if 10 in ra_fields:
            ra[10] = list(ra_fields[10])
        result["room_admin"] = ra
    if 15 in f:
        result["login_info"] = decode_generic(f[15][0])
    if 16 in f:
        result["sessions"] = [decode_generic(x) for x in f[16]]
    return result


def decode_generic(data: bytes):
    f = decode_message(data)
    out = {}
    for num, vals in f.items():
        converted = []
        for v in vals:
            if isinstance(v, int):
                converted.append(v)
            elif isinstance(v, bytes):
                try:
                    s = v.decode("utf-8")
                    # Nested protobuf objects are also bytes. Prefer text for
                    # fields that look like UTF-8; otherwise expose raw hex.
                    if any(c == "\x00" for c in s):
                        converted.append(v.hex())
                    else:
                        converted.append(s)
                except UnicodeDecodeError:
                    converted.append(v.hex())
        out[num] = converted[0] if len(converted) == 1 else converted
    return out


# ------------------------- raw WebSocket transport ------------------------
class RawWebSocket:
    """RFC6455 client closely mirroring the supplied Android Y9/v handshake."""
    MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, url, headers, timeout=20, debug=False):
        from urllib.parse import urlsplit
        u = urlsplit(url)
        self.scheme = u.scheme
        self.host = u.hostname
        self.port = u.port or (443 if u.scheme == "wss" else 80)
        self.path = u.path or "/"
        if u.query:
            self.path += "?" + u.query
        self.headers = list(headers or [])
        self.timeout = timeout
        self.debug = debug
        self.sock = None
        self._recvbuf = bytearray()
        self.peer_ip = None
        self.permessage_deflate = False

    def _connect_android_like(self):
        # Android's Y9/s resolves all addresses before creating the socket.
        # We do the same and keep the TLS hostname as chatp.net for SNI/cert check.
        infos = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        seen = set()
        last = None
        for family, socktype, proto, _canon, sockaddr in infos:
            ip = sockaddr[0]
            if (family, ip, self.port) in seen:
                continue
            seen.add((family, ip, self.port))
            raw = socket.socket(family, socktype, proto)
            raw.settimeout(self.timeout)
            try:
                raw.connect(sockaddr)
                self.peer_ip = ip
                return raw
            except Exception as e:
                last = e
                try: raw.close()
                except Exception: pass
        raise ConnectionError(f"TCP connect failed to {self.host}:{self.port}: {last}")

    def connect(self):
        raw = self._connect_android_like()

        # Android Client obtains the platform default SSLSocketFactory.
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        self.sock.settimeout(self.timeout)

        # Y9/v: SecureRandom -> 16 bytes -> Base64.
        key = base64.b64encode(os.urandom(16)).decode("ascii")

        # Y9/v builds this base order. Newer TalkinChat builds may use a
        # conventional WebSocket stack, so optional compatibility headers are
        # selected by the caller rather than being hard-coded.
        lines = [
            f"GET {self.path} HTTP/1.1",
            f"Host: {self.host}:{self.port}",
            "Connection: Upgrade",
            "Upgrade: websocket",
            "Sec-WebSocket-Version: 13",
            f"Sec-WebSocket-Key: {key}",
        ]
        lines.extend(self.headers)
        request = "\r\n".join(lines) + "\r\n\r\n"

        if self.debug:
            # Header values contain credentials encoded by the APK protocol.
            # Redact username/password header values in diagnostics.
            shown=[]
            for line in lines:
                low=line.lower()
                if low.startswith("username:") or low.startswith("password:"):
                    shown.append(line.split(":",1)[0] + ": <redacted>")
                else:
                    shown.append(line)
            print("[RAW-WS] peer_ip=", self.peer_ip, flush=True)
            print("[RAW-WS] TLS=", self.sock.version(), "cipher=", self.sock.cipher(), flush=True)
            print("[RAW-WS] handshake:\n" + "\\r\\n\n".join(shown) + "\\r\\n\\r\\n", flush=True)

        self.sock.sendall(request.encode("utf-8"))

        # Read the complete HTTP response header so a 404 can be diagnosed.
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("server closed during WebSocket handshake")
            buf += chunk
            if len(buf) > 65536:
                raise ConnectionError("oversized WebSocket handshake")

        head, self._prefetch = buf.split(b"\r\n\r\n", 1)
        text = head.decode("iso-8859-1", "replace")
        response_lines = text.split("\r\n")
        status = response_lines[0] if response_lines else ""

        if self.debug:
            print("[RAW-WS] response:", flush=True)
            print(text, flush=True)

        if not (" 101 " in status or status.endswith(" 101")):
            # Include headers/body prefix but never echo credential-bearing request headers.
            body_preview = self._prefetch[:512].decode("utf-8", "replace") if self._prefetch else ""
            detail = status
            if body_preview:
                detail += " | body=" + repr(body_preview)
            raise ConnectionError("WebSocket handshake rejected: " + detail)

        h = {}
        for line in response_lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                h[k.strip().lower()] = v.strip()
        ext = h.get("sec-websocket-extensions", "")
        self.permessage_deflate = "permessage-deflate" in ext.lower()
        if self.debug and ext:
            print("[RAW-WS] negotiated extensions:", ext, flush=True)
        expected = base64.b64encode(hashlib.sha1((key + self.MAGIC).encode("ascii")).digest()).decode("ascii")
        if h.get("sec-websocket-accept") != expected:
            raise ConnectionError("invalid Sec-WebSocket-Accept")
        self._recvbuf = bytearray(self._prefetch)

    def _recv_exact(self, n):
        while len(self._recvbuf) < n:
            chunk = self.sock.recv(max(4096, n-len(self._recvbuf)))
            if not chunk:
                raise ConnectionError("socket closed")
            self._recvbuf.extend(chunk)
        out = bytes(self._recvbuf[:n]); del self._recvbuf[:n]
        return out

    def send_binary(self, payload):
        payload = bytes(payload)
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            hdr = bytes([0x82, 0x80 | n])
        elif n <= 0xffff:
            hdr = bytes([0x82, 0x80 | 126]) + struct.pack('!H', n)
        else:
            hdr = bytes([0x82, 0x80 | 127]) + struct.pack('!Q', n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(hdr + mask + masked)

    def send_control(self, opcode, payload=b''):
        payload = bytes(payload); mask = os.urandom(4)
        if len(payload) > 125: raise ValueError('control frame too large')
        hdr = bytes([0x80 | opcode, 0x80 | len(payload)])
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(hdr + mask + masked)

    def recv(self):
        b1, b2 = self._recv_exact(2)
        rsv1 = bool(b1 & 0x40)
        opcode = b1 & 0x0f; masked = bool(b2 & 0x80); n = b2 & 0x7f
        if n == 126: n = struct.unpack('!H', self._recv_exact(2))[0]
        elif n == 127: n = struct.unpack('!Q', self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b''
        data = self._recv_exact(n)
        if masked: data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if rsv1 and self.permessage_deflate and opcode in (0x1, 0x2, 0x0):
            import zlib
            try:
                data = zlib.decompress(data + b"\\x00\\x00\\xff\\xff", -zlib.MAX_WBITS)
            except zlib.error:
                pass
        if opcode == 0x8:
            code = None; reason = ''
            if len(data) >= 2:
                try:
                    code = struct.unpack('!H', data[:2])[0]
                    reason = data[2:].decode('utf-8', 'replace')
                except Exception:
                    pass
            return ('close', {'code': code, 'reason': reason, 'raw': data})
        if opcode == 0x9:
            self.send_control(0xA, data); return ('ping', data)
        if opcode == 0xA: return ('pong', data)
        if opcode == 0x1: return ('text', data.decode('utf-8', 'replace'))
        if opcode == 0x2: return ('binary', data)
        return ('other', data)

    def close(self):
        try:
            if self.sock: self.send_control(0x8, b'')
        except Exception: pass
        try:
            if self.sock: self.sock.close()
        except Exception: pass
        self.sock = None

# ------------------------------ Database ----------------------------------

class DatabaseBridge:
    """Read the same room_members/profiles data used by the web app.

    The supplied app source explicitly reads room_members(user_id, rank,
    joined_at, is_present) and then resolves those IDs through profiles.
    """
    def __init__(self, log):
        self.log = log
        self.client = None
        self.url = os.getenv("SUPABASE_URL", "").strip()
        self.key = os.getenv("SUPABASE_KEY", "").strip()
        self.email = os.getenv("SUPABASE_EMAIL", "").strip()
        self.password = os.getenv("SUPABASE_PASSWORD", "")
        self.last_error = ""
        self.last_room_id = ""
        self.last_member_count = 0
        self.last_profile_count = 0
        cfg_path = Path(os.getenv("DB_CONFIG_PATH", str(Path(__file__).resolve().parent / "config.json")))
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                # Support both the current flat config and the older config
                # format used by the working Talkin bot.
                sbcfg = cfg.get("supabase") if isinstance(cfg.get("supabase"), dict) else {}
                self.url = self.url or str(cfg.get("supabase_url", sbcfg.get("url", ""))).strip()
                self.key = self.key or str(cfg.get("supabase_key", sbcfg.get("key", ""))).strip()
                self.email = self.email or str(cfg.get("supabase_email", cfg.get("email", sbcfg.get("email", "")))).strip()
                self.password = self.password or str(cfg.get("supabase_password", cfg.get("password", sbcfg.get("password", ""))))
            except Exception as e:
                self.log("[DB] config read failed:", repr(e))
        if not create_client:
            self.log("[DB] Supabase library غير مثبتة/غير قابلة للاستيراد")
        elif not self.url or not self.key:
            self.log("[DB] Supabase client غير متاح: SUPABASE_URL/SUPABASE_KEY مفقودان")
        else:
            try:
                if self.key.startswith("sb_publishable_"):
                    self.client = create_client(self.url, "a.b.c")
                    self.client.supabase_key = self.key
                    self.client.options.headers["apiKey"] = self.key
                    self.client.options.headers.pop("Authorization", None)
                else:
                    self.client = create_client(self.url, self.key)
                self.log("[DB] Supabase client ready")
            except Exception as e:
                self.log("[DB] client init failed:", repr(e))

    def sign_in(self):
        if not self.client or not self.password:
            return False
        try:
            # The Talkin app logs in to the realtime service by username, while
            # the Supabase Auth account is email-based. Resolve that email through
            # the same backend RPC used by the original bot when necessary.
            if not self.email:
                username = str(BOT_ID or os.getenv("USERNAME", "")).strip()
                if username:
                    try:
                        rr = self.client.rpc("lookup_auth_email", {"_username": username}).execute()
                        val = getattr(rr, "data", None)
                        if isinstance(val, str) and "@" in val:
                            self.email = val.strip()
                        elif isinstance(val, dict):
                            self.email = str(val.get("email") or val.get("auth_email") or "").strip()
                    except Exception as e:
                        self.log("[DB] lookup_auth_email failed:", repr(e))
            if not self.email:
                self.log("[DB] Supabase auth email not resolved")
                return False
            res = self.client.auth.sign_in_with_password({"email": self.email, "password": self.password})
            user = getattr(res, "user", None)
            self.log("[DB] Supabase auth:", "OK" if user else "FAILED")
            if user:
                self.log("[DB] authenticated Supabase user ready for moderation/status")
            return bool(user)
        except Exception as e:
            self.log("[DB] Supabase auth failed:", repr(e))
            return False

    def room_id(self, room_name):
        if not self.client: return None
        name = str(room_name or "").strip()
        try:
            r = self.client.table("rooms").select("id,name").eq("name", name).limit(1).execute()
            rows = getattr(r, "data", None) or []
            if rows:
                rid = str(rows[0].get("id"))
                self.last_room_id = rid
                return rid
        except Exception as e:
            self.last_error = str(e)
            self.log("[DB] room lookup failed:", repr(e))
        return None

    def moderation_rpc(self, room_name, target_username, operation):
        """Use the real Talkin moderation RPC after authenticating Supabase.

        Kick is kept on the proven Talkin websocket packet first. Ban/unban use
        the backend RPCs exposed by the Talkin application.
        """
        room = str(room_name or "").strip()
        username = str(target_username or "").strip().lstrip("@")
        op = str(operation or "").lower().strip()
        if not room or not username:
            return False, "الغرفة أو اسم المستخدم فارغ"
        if not self.client:
            return False, "Supabase client غير متاح — تأكد أن config.json يحتوي supabase_url و supabase_key"
        try:
            rid = self.room_id(room)
            if not rid:
                return False, f"لم يتم العثور على room_id للغرفة: {room}"
            q = self.client.table("profiles").select("id,username").eq("username", username).limit(1).execute()
            rows = getattr(q, "data", None) or []
            if not rows:
                q = self.client.table("profiles").select("id,username").ilike("username", username).limit(1).execute()
                rows = getattr(q, "data", None) or []
            if not rows:
                return False, f"لم يتم العثور على user_id للحساب: {username}"
            uid = str(rows[0].get("id") or "").strip()
            if not uid:
                return False, f"user_id فارغ للحساب: {username}"

            rpc_name = {"ban":"ban_room_member", "unban":"unban_room_member"}.get(op)
            if op == "kick":
                # This is the same proven transport used by the older working bot:
                # room_admin -> kick.
                return self._native_moderation_packet(room, username, "kick"), "تم إرسال أمر الطرد عبر Talkin"
            if not rpc_name:
                return False, f"عملية غير معروفة: {op}"

            # Try the common parameter names, stopping only when the backend
            # confirms the operation.
            candidates = [
                {"_room": rid, "_user": uid},
                {"_room_id": rid, "_user_id": uid},
                {"room_id": rid, "user_id": uid},
                {"room_id": rid, "target_user_id": uid},
                {"_room": rid, "_user_id": uid},
            ]
            errors = []
            for params in candidates:
                try:
                    res = self.client.rpc(rpc_name, params).execute()
                    self.log(f"[ADMIN] {rpc_name} OK params={list(params)} data={getattr(res,'data',None)!r}")
                    return True, f"RPC {rpc_name} نجح"
                except Exception as e:
                    errors.append(str(e))
                    low = str(e).lower()
                    # Keep trying only for signature/argument mismatches.
                    if not any(x in low for x in ("argument", "parameter", "function", "does not exist", "could not find", "pgrst202")):
                        break
            return False, f"{rpc_name} فشل: {' | '.join(errors[-3:])}"
        except Exception as e:
            self.last_error = str(e)
            self.log("[ADMIN] moderation failed:", repr(e))
            return False, str(e)

    def _native_moderation_packet(self, room, username, operation):
        if operation == "kick":
            self.send_query(encode_query("room_admin", type_="kick", room=room, to=username, value="none"))
            return True
        if operation == "ban":
            self.send_query(encode_query("room_admin", type_="ban_ip", room=room, to=username, value="outcast"))
            return True
        return False

    def room_users(self, room_name):
        if not self.client: return []
        rid = self.room_id(room_name)
        if not rid: return []
        try:
            r = self.client.table("room_members").select("user_id, rank, joined_at, is_present").eq("room_id", rid).execute()
            members = getattr(r, "data", None) or []
            self.last_member_count = len(members)
            ids = []
            for row in members:
                uid = row.get("user_id")
                if uid and str(uid) not in ids: ids.append(str(uid))
            if not ids: return []
            out=[]
            for i in range(0, len(ids), 100):
                batch=ids[i:i+100]
                pr=self.client.table("profiles").select("id, username").in_("id", batch).execute()
                for row in (getattr(pr,"data",None) or []):
                    u=str(row.get("username") or "").strip()
                    if u: out.append({"username":u,"user_id":str(row.get("id") or "")})
            seen=set(); final=[]
            for u in out:
                k=u["username"].casefold()
                if k not in seen: seen.add(k); final.append(u)
            self.last_profile_count = len(final)
            self.log(f"[DB] room_members={len(members)} profiles={len(final)} room_id={rid}")
            return final
        except Exception as e:
            self.last_error = str(e)
            self.log("[DB] room_members query failed:", repr(e))
            return []

# ----------------------- Giant-style local data -----------------------
def _load_local_json(path, default):
    try:
        if Path(path).is_file():
            return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _save_local_json(path, data):
    tmp=Path(str(path)+".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def _norm_user(name):
    return str(name or "").strip().lstrip("@").casefold()

def _master_list():
    data=_load_local_json(MASTERS_FILE, [])
    return data if isinstance(data,list) else []

def _is_master_name(name):
    n=_norm_user(name)
    return bool(n and (n == _norm_user(BOT_MASTER) or n in {_norm_user(x) for x in _master_list()}))

def _verified_data():
    data=_load_local_json(VERIFIED_FILE,{})
    return data if isinstance(data,dict) else {}

def _vip_data():
    data=_load_local_json(VIP_FILE,{})
    return data if isinstance(data,dict) else {}

def _points_data():
    data=_load_local_json(POINTS_FILE,{})
    return data if isinstance(data,dict) else {}

def _add_points(username, amount):
    amount=int(amount)
    data=_points_data(); key=_norm_user(username)
    item=data.get(key,{"username":str(username).strip().lstrip("@"),"points":0})
    item["username"]=str(username).strip().lstrip("@")
    item["points"]=int(item.get("points",0) or 0)+amount
    data[key]=item; _save_local_json(POINTS_FILE,data)
    return item["points"]

def _get_points(username):
    if _is_master_name(username): return None
    item=_points_data().get(_norm_user(username),{})
    return int(item.get("points",0) or 0)

def _message_template(section,key,default,**kwargs):
    data=_load_local_json(MESSAGES_FILE,{})
    value=((data.get(section) or {}).get(key)) if isinstance(data,dict) else None
    text=value if isinstance(value,str) else default
    try: return text.format(**kwargs)
    except Exception: return text

def _command_menu():
    return (
        "📚 قوائم أوامر البوت\n"
        "━━━━━━━━━━━━\n"
        "help1 — الإدارة\n"
        "help2 — الموسيقى والتفاعلات\n"
        "help3 — الألعاب\n"
        "help4 — الهدايا والنشر\n"
        "help5 — النقاط\n"
        "help6 — الغرف\n"
        "help7 — الماستر والفلتر\n"
        "━━━━━━━━━━━━\n"
        "اكتب اسم القائمة مثل: help1"
    )


def _default_help_pages():
    return {
        1: '📋 أوامر الإدارة\n━━━━━━━━━━━━\nk@اسم — طرد\nb@اسم — حظر\nub@اسم — فك الحظر\na@اسم — تعيين مشرف\no@اسم — تعيين مالك',
        2: '🎵 الموسيقى\n━━━━━━━━━━━━\n.sa اسم الأغنية — تشغيل',
        3: '🎮 الألعاب\n━━━━━━━━━━━━\nالعاب — عرض الألعاب\nحظ — جائزة عشوائية\nنرد — رمي النرد\nتخمين — تخمين رقم\nحجر — حجر ورق مقص\nورق — حجر ورق مقص\nمقص — حجر ورق مقص\nسؤال — مسابقة',
        4: '🎁 الهدايا والنشر\n━━━━━━━━━━━━\nsa@رقم@اسم — إرسال هدية\nانشر — نشر صورة\nانشر@وصف — نشر صورة بوصف\nsay نص — إرسال نص',
        5: '💰 النقاط\n━━━━━━━━━━━━\nنقاطي — عرض النقاط\nتوب — المتصدرين\nsb@اسم@عدد — تعديل النقاط',
        6: '🚪 الغرف\n━━━━━━━━━━━━\nدخول اسم_الغرفة — دخول غرفة\nخروج — خروج من الغرف\nخروج اسم_الغرفة — خروج من غرفة\ninv — دعوة المستخدمين\ninv اسم_الغرفة — دعوة من غرفة\ninvmsg نص — تغيير رسالة الدعوة\nsay نص — إرسال نص',
        7: '👑 الماستر والفلتر\n━━━━━━━━━━━━\nmas@اسم — إضافة ماستر\numas@اسم — إزالة ماستر\nالمسترات — عرض الماسترز\ns@اسم — توثيق\nuns@اسم — إزالة التوثيق\nVip@اسم — توثيق VIP\nunVip@اسم — إلغاء VIP\nmf@on / mf@off — تشغيل أو إيقاف الفلتر\n+mf@كلمة — إضافة كلمة ممنوعة\n-mf@كلمة — إزالة كلمة ممنوعة\nl@mf — عرض الكلمات\nclear@mf — حذف الكلمات',
    }

def _help_pages_from_messages():
    defaults=_default_help_pages()
    data=_load_local_json(MESSAGES_FILE,{})
    raw=data.get("help_pages") if isinstance(data,dict) else None
    if isinstance(raw,list) and raw:
        pages={}
        for i,v in enumerate(raw,1):
            if isinstance(v,str) and v.strip():
                pages[i]=v.replace("\\n","\n")
        if pages: return pages
    return defaults

def _command_help(page=1):
    try: page=int(page)
    except Exception: page=1
    pages=_help_pages_from_messages()
    page=max(1,min(len(pages),page))
    return pages.get(page,_default_help_pages()[1])

# ------------------------------ Bot --------------------------------------

def _shape_name(text):
    # Keep the exact logical username. Do not reverse or normalize decorative Arabic.
    return str(text or "")

_GIFT_FONT_CACHE = {}
_FONT_COVERAGE_CACHE = {}

def _font_coverage(path):
    key=str(path)
    if key in _FONT_COVERAGE_CACHE:
        return _FONT_COVERAGE_CACHE[key]
    coverage=set()
    if TTFont is not None:
        try:
            font=TTFont(key, lazy=True)
            for table in font["cmap"].tables:
                coverage.update(table.cmap.keys())
            font.close()
        except Exception:
            coverage=set()
    _FONT_COVERAGE_CACHE[key]=coverage
    return coverage

def _load_font(path, size):
    key=(str(path),int(size))
    if key not in _GIFT_FONT_CACHE:
        f=ImageFont.truetype(str(path),int(size))
        try:
            f._source_path=str(path)
            f._coverage=_font_coverage(path)
        except Exception:
            pass
        _GIFT_FONT_CACHE[key]=f
    return _GIFT_FONT_CACHE[key]

def _gift_font(text,size):
    # Primary font for Arabic names. Decorative Unicode is handled by the
    # coverage-aware fallback chain below; the input username is never changed.
    path=BASE_DIR/"assets"/"NotoSansArabic-SemiBold.ttf"
    if not path.is_file(): path=BASE_DIR/"assets"/"NotoSansArabic-Regular.ttf"
    if not path.is_file(): path=BASE_DIR/"assets"/"Amiri-Bold.ttf"
    return _load_font(path,size)

def _fallback_fonts(size):
    # Broad Unicode fallback chain. This is important for decorated Talkin
    # usernames containing Arabic Presentation Forms, Egyptian hieroglyphs,
    # symbols, music symbols and Mathematical Alphanumeric characters.
    paths=[
        BASE_DIR/"assets"/"NotoSansArabic-Regular.ttf",
        BASE_DIR/"assets"/"NotoSansArabic-SemiBold.ttf",
        BASE_DIR/"assets"/"Amiri-Bold.ttf",
        BASE_DIR/"assets"/"NotoSans-Regular.ttf",
        BASE_DIR/"assets"/"NotoSansMath-Regular.ttf",
        BASE_DIR/"assets"/"NotoSansSymbols-Regular.ttf",
        BASE_DIR/"assets"/"NotoSansSymbols2-Regular.ttf",
        BASE_DIR/"assets"/"NotoSansEgyptianHieroglyphs-Regular.ttf",
        BASE_DIR/"assets"/"NotoMusic-Regular.ttf",
        BASE_DIR/"assets"/"DejaVuSans.ttf",
    ]
    return [_load_font(p,size) for p in paths if p.is_file()]

def _font_has_glyph(font, ch):
    # Do not trust FreeType's getmask() alone: missing glyphs can still return
    # a .notdef box. Use the actual font cmap when available.
    try:
        coverage=getattr(font,"_coverage",None)
        if coverage:
            return ord(ch) in coverage
        return font.getlength(ch) > 0 and font.getmask(ch).getbbox() is not None
    except Exception:
        return False

def _text_clusters(text):
    # Keep combining marks attached to the character they decorate so a
    # decorative username is not visually broken when fallback fonts are used.
    import unicodedata
    clusters=[]
    for ch in _shape_name(text):
        if clusters and (unicodedata.combining(ch) or unicodedata.category(ch) in ("Cf",)):
            clusters[-1]+=ch
        else:
            clusters.append(ch)
    return clusters

def _cluster_font(cluster, base, fallbacks):
    # Prefer a font containing every code point in the cluster.
    for f in [base]+fallbacks:
        if all(_font_has_glyph(f,ch) for ch in cluster):
            return f
    # If a combining mark has no complete-font match, use the first font that
    # can draw the base character. Unsupported characters are left unchanged
    # in the source string and only fall back visually when unavoidable.
    base_ch=cluster[0] if cluster else ""
    return next((f for f in [base]+fallbacks if _font_has_glyph(f,base_ch)), base)

def _build_text_runs(raw_text,size):
    text=_shape_name(raw_text)
    base=_gift_font(text,size); fallbacks=_fallback_fonts(size)
    runs=[]; cur_font=None; cur=[]
    for cluster in _text_clusters(text):
        chosen=_cluster_font(cluster,base,fallbacks)
        if cur_font is None or chosen is cur_font:
            cur.append(cluster)
        else:
            runs.append((cur_font,"".join(cur))); cur=[cluster]
        cur_font=chosen
    if cur: runs.append((cur_font,"".join(cur)))
    return runs

def _measure_runs(runs):
    total=0
    for font,run in runs:
        try: total += font.getlength(run)
        except Exception: total += sum(font.getlength(ch) for ch in run)
    return total

def _draw_exact_text(draw, xy, raw_text, size, fill, stroke_width=2, stroke_fill=(0,0,0,220)):
    """Render the EXACT username string with Unicode-aware font fallback.

    No transliteration, normalization or replacement of the sender/receiver
    name is performed. If one font cannot render a decorative character, the
    same character is drawn from another bundled Unicode font.
    """
    runs=_build_text_runs(raw_text,size)
    x,y=xy
    for font,run in runs:
        draw.text((x,y),run,font=font,fill=fill,stroke_width=stroke_width,stroke_fill=stroke_fill)
        try: x += draw.textlength(run,font=font)
        except Exception: x += _measure_runs([(font,run)])
    return x

def _fit_text_size(raw_text, initial_size, max_width):
    size=int(initial_size)
    while size>12:
        if _measure_runs(_build_text_runs(raw_text,size)) <= max_width:
            return size
        size-=2
    return max(12,size)

def _draw_centered(draw,center,raw_text,size,fill,max_width):
    size=_fit_text_size(raw_text,size,max_width)
    runs=_build_text_runs(raw_text,size)
    width=_measure_runs(runs)
    # Pillow draws the runs in their logical sequence; for Talkin decorated
    # names we preserve the exact Unicode sequence received from the server.
    x=center[0]-width/2
    bbox=_gift_font(raw_text,size).getbbox("Hg")
    y=center[1]-(bbox[3]-bbox[1])/2-bbox[1]
    _draw_exact_text(draw,(x,y),raw_text,size,fill,stroke_width=3,stroke_fill=(0,0,0,220))

def _fit_crop(im,size):
    im=im.convert("RGB"); tw,th=size; scale=max(tw/im.width,th/im.height); nw,nh=max(tw,int(im.width*scale)),max(th,int(im.height*scale)); im=im.resize((nw,nh),Image.LANCZOS); left=max(0,(nw-tw)//2); top=max(0,(nh-th)//2); return im.crop((left,top,left+tw,top+th))

def _draw_centered(draw,center,raw_text,size,fill,max_width):
    size=int(size)
    # Measure using the actual mixed-font renderer; shrink until it fits.
    while size>14:
        tmp=_gift_font(raw_text,size)
        # approximate mixed width from runs
        x=0
        for ch in _shape_name(raw_text):
            f=tmp if _font_has_glyph(tmp,ch) else next((f for f in _fallback_fonts(size) if _font_has_glyph(f,ch)),tmp)
            x += f.getlength(ch)
        if x<=max_width: break
        size-=2
    # Draw from centered x. For Arabic the exact visual shaping is retained by Noto Arabic runs.
    tmp=_gift_font(raw_text,size)
    width=sum((tmp if _font_has_glyph(tmp,ch) else next((f for f in _fallback_fonts(size) if _font_has_glyph(f,ch)),tmp)).getlength(ch) for ch in _shape_name(raw_text))
    bbox=tmp.getbbox("Hg")
    x=center[0]-width/2
    y=center[1]-(bbox[3]-bbox[1])/2-bbox[1]
    _draw_exact_text(draw,(x,y),raw_text,size,fill,stroke_width=3,stroke_fill=(0,0,0,220))

def render_gift_card(gift_id,sender_name,receiver_name):
    if not PIL_AVAILABLE: raise RuntimeError("Pillow غير مثبت")
    files=[p for p in GIFT_IMAGE_FILES.get(str(gift_id),[]) if p.is_file()]
    if not files: raise FileNotFoundError("صور الهدية غير موجودة داخل assets")
    template_path=BASE_DIR/"assets"/"gift_template_elegant.png"
    template=Image.open(template_path).convert("RGBA") if template_path.is_file() else Image.new("RGBA",(1239,1270),(0,0,0,0))
    image=_fit_crop(Image.open(random.choice(files)),template.size).convert("RGBA"); image.alpha_composite(template); d=ImageDraw.Draw(image); w,h=template.size
    gold=(244,196,92,255); panel=(10,14,28,245); header=(int(w*.27),65,int(w*.73),205)
    d.rounded_rectangle(header,radius=48,fill=panel,outline=gold,width=4)
    gift_name=GIFT_CATALOG.get(str(gift_id),("🎁","هدية"))[1]
    _draw_centered(d,((header[0]+header[2])/2,135),"هدية "+gift_name,42,(255,222,155,255),header[2]-header[0]-50)
    box_w=int(w*.64); box_h=int(h*.105); box_x=(w-box_w)//2; top_y=int(h*.705); bottom_y=int(h*.815)
    for y in (top_y,bottom_y): d.rounded_rectangle((box_x,y,box_x+box_w,y+box_h),radius=28,fill=panel,outline=gold,width=4)
    _draw_centered(d,(w/2,top_y+28),"من",27,(255,224,165,255),box_w-20); _draw_centered(d,(w/2,bottom_y+28),"إلى",27,(255,224,165,255),box_w-20)
    colors=[(255,130,165,255),(100,220,255,255),(255,211,85,255),(180,135,255,255),(100,235,170,255),(255,150,95,255)]; c1,c2=random.sample(colors,2)
    _draw_centered(d,(w/2,top_y+box_h*.68),sender_name,39,c1,box_w-42); _draw_centered(d,(w/2,bottom_y+box_h*.68),receiver_name,39,c2,box_w-42)
    out=BASE_DIR/"generated_gifts"/f"gift_{gift_id}_{uuid.uuid4().hex}.png"; out.parent.mkdir(parents=True,exist_ok=True); image.save(out,"PNG",optimize=True); return out

class _MediaHandler(SimpleHTTPRequestHandler):
    def _resolve_target(self):
        path=unquote(urlparse(self.path).path)
        if path.startswith("/assets/"):
            rel=path[len("/assets/"):].lstrip("/"); root=ASSETS_DIR.resolve(); target=(ASSETS_DIR/rel).resolve()
        elif path.startswith("/gifts/"):
            rel=path[len("/gifts/"):].lstrip("/"); root=(BASE_DIR/"generated_gifts").resolve(); target=(BASE_DIR/"generated_gifts"/rel).resolve()
        elif path.startswith("/media/"):
            rel=path[len("/media/"):].lstrip("/"); root=(BASE_DIR/"generated_music").resolve(); target=(BASE_DIR/"generated_music"/rel).resolve()
        else:
            return None
        if root not in target.parents or not target.is_file(): return None
        return target

    def _ctype(self,target):
        ctype,_=mimetypes.guess_type(str(target))
        return ctype or {
            ".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp",".gif":"image/gif",
            ".mp3":"audio/mpeg",".m4a":"audio/mp4",".webm":"audio/webm",".ogg":"audio/ogg"
        }.get(target.suffix.lower(),"application/octet-stream")

    def _serve(self,head_only=False):
        target=self._resolve_target()
        if not target:
            self.send_error(404); return
        try:
            total=target.stat().st_size; start=0; end=total-1; status=200
            rh=self.headers.get("Range")
            if rh and rh.startswith("bytes="):
                spec=rh.split("=",1)[1].split(",",1)[0].strip(); a,_,b=spec.partition("-")
                if a: start=int(a); end=int(b) if b else total-1
                elif b:
                    length=int(b); start=max(0,total-length)
                if start>=total or end<start:
                    self.send_response(416); self.send_header("Content-Range",f"bytes */{total}"); self.end_headers(); return
                end=min(end,total-1); status=206
            length=end-start+1
            self.send_response(status)
            self.send_header("Content-Type",self._ctype(target))
            self.send_header("Accept-Ranges","bytes")
            self.send_header("Content-Length",str(length))
            if status==206: self.send_header("Content-Range",f"bytes {start}-{end}/{total}")
            self.send_header("Cache-Control","public,max-age=86400")
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers()
            if head_only: return
            with target.open("rb") as fh:
                fh.seek(start); remaining=length
                while remaining:
                    chunk=fh.read(min(1024*1024,remaining))
                    if not chunk: break
                    self.wfile.write(chunk); remaining-=len(chunk)
        except Exception:
            try: self.send_error(404)
            except Exception: pass

    def do_HEAD(self): self._serve(True)
    def do_GET(self): self._serve(False)
    def log_message(self,fmt,*args):
        if DEBUG: print("[MEDIA] "+(fmt%args),flush=True)


def start_asset_server():
    if not ASSET_HTTP_ENABLED: return None
    try:
        (BASE_DIR/"generated_gifts").mkdir(parents=True,exist_ok=True); (BASE_DIR/"generated_music").mkdir(parents=True,exist_ok=True)
        server=ThreadingHTTPServer(("0.0.0.0",ASSET_HTTP_PORT),_MediaHandler)
        threading.Thread(target=server.serve_forever,name="media-http",daemon=True).start()
        print(f"[MEDIA] HTTP server listening on :{ASSET_HTTP_PORT}",flush=True)
        return server
    except Exception as e:
        print("[MEDIA] HTTP server failed:",repr(e),flush=True); return None

class TalkinBot:
    def __init__(self):
        self.ws = None
        self.stop_event = threading.Event()
        self.http = requests.Session()
        self.port = DEFAULT_PORT
        self.room = GROUP_TO_JOIN
        self.auth = None
        self.last_error = None
        self.banned_words = set()
        self.last_messages = defaultdict(list)
        # Live room membership cache: username -> role.  This is updated by
        # occupants_list and by user_joined/user_left room events.
        self.room_users = defaultdict(dict)
        self.last_joined_room = None
        self.invite_pending = False
        self.invite_room = ""
        self.invite_sent = set()
        self.invite_thread = None
        self.invite_lock = threading.Lock()
        self.invite_message_template = "{sender} يدعوك للغرفة {room}"
        self.known_rooms = set()
        # Rooms discovered from a fresh server room-list request.
        self.available_rooms = set()
        self._rooms_list_lock = threading.Lock()
        self._rooms_list_event = threading.Event()
        self._join_lock = threading.Lock()
        self._last_join_sent = {}
        self._rejoin_attempts = defaultdict(int)
        self._last_reconnect = 0.0
        self._pending_reconnect_reason = ""
        self._had_connection = False
        self.banned_words = set(BANNED_WORDS)
        self.text_limit = max(80, int(os.getenv("TALKIN_TEXT_LIMIT", "180")))
        self.db = DatabaseBridge(self.log)
        self.db.sign_in()
        self.music_last = defaultdict(float)
        self.music_current = {}
        self.music_lock = threading.Lock()
        # Reaction/publish state used by music and image publishing.
        self.reaction_targets = {}
        self.publish_pending = {}
        # Persistent account monitoring. Master can add usernames with: راقب@username
        self.monitored_users = {}
        self.monitor_seen_events = {}
        self._monitor_lock = threading.Lock()
        self._load_monitored_users()
        # Talkin profile/status shown under the bot name.
        self.bot_status_text = "🎵✨ بوت ميوزك تالكين شات ✨🎵"
        self._status_lock = threading.Lock()
        self._status_restore_timer = None
        # Mini-games: free-to-play, no points are deducted.
        self.game_lock = threading.Lock()
        self.game_cooldown = defaultdict(float)
        self.guess_games = {}
        self.help_pages = {}
        # Auto replies and per-user custom welcome messages.
        self.auto_replies_enabled = True
        self.auto_replies = {}
        self.custom_welcome_enabled = True
        self.custom_welcomes = {}
        self._load_social_features()
        self.invite_message_template = _message_template("invite", "default", "{sender} يدعوك للغرفة {room}")

    def _load_monitored_users(self):
        try:
            data = _load_local_json(MONITORED_USERS_FILE, {})
            raw = data.get("users", data) if isinstance(data, dict) else data
            if isinstance(raw, list):
                self.monitored_users = {_norm_user(x): str(x).strip().lstrip("@") for x in raw if _norm_user(x)}
            elif isinstance(raw, dict):
                self.monitored_users = {_norm_user(k): str(v or k).strip().lstrip("@") for k, v in raw.items() if _norm_user(k)}
            else:
                self.monitored_users = {}
        except Exception:
            self.monitored_users = {}

    def _save_monitored_users(self):
        with self._monitor_lock:
            data = {"users": dict(sorted(self.monitored_users.items()))}
        _save_local_json(MONITORED_USERS_FILE, data)

    def _monitor_add(self, username):
        username = str(username or "").strip().lstrip("@")
        key = _norm_user(username)
        if not key:
            return False
        with self._monitor_lock:
            existed = key in self.monitored_users
            self.monitored_users[key] = username
        self._save_monitored_users()
        return not existed

    def _monitor_remove(self, username):
        key = _norm_user(username)
        if not key:
            return False
        with self._monitor_lock:
            existed = key in self.monitored_users
            self.monitored_users.pop(key, None)
        if existed:
            self._save_monitored_users()
        return existed

    def _monitor_report(self, event, event_type, username, room, event_id="", frm="", to="", role="", body=""):
        """Report all meaningful activity for a watched user across all rooms."""
        key = _norm_user(username)
        with self._monitor_lock:
            if key not in self.monitored_users:
                return False
            display_name = self.monitored_users.get(key, username)

        et = str(event_type or "").casefold().strip()
        bt = str(body or "").casefold().strip()

        # The visible system messages in the app can be ordinary RoomEvents
        # whose type is only `user_left`/`user_joined`.  The actual action is
        # then written in the Arabic body, for example:
        #   "تم حظره من قبل X"
        #   "اصبح مشرف من قبل X"
        #   "اصبح عضو من قبل X"
        # So inspect BOTH event type and system body.
        ban_words = ("ban", "banned", "outcast", "blocked", "حظر", "محظور", "حظره", "حظرت", "تم حظره")
        kick_words = ("kick", "kicked", "removed", "remove_user", "user_kicked", "user_removed", "طرد", "مطرود", "طرده", "تم طرده")
        owner_words = ("owner", "owner_changed", "اونر", "ونر", "مالك", "المالك")
        role_words = ("role", "promote", "demote", "admin", "moderator", "مشرف", "ادمن", "رتبة", "اصبح مشرف", "اصبح ادمن", "اصبح اونر", "اصبح مالك")

        # IMPORTANT: `text` events are also used for ordinary chat messages.
        # Never treat a random message/command containing the watched username
        # as a moderation event.  Only accept known system-event phrases.
        system_text = any(phrase in bt for phrase in (
            "أصبح عضو من قبل", "اصبح عضو من قبل",
            "تم حظره من قبل", "تم حظره",
            "تم طرده من قبل", "تم طرده",
            "أصبح مشرف من قبل", "اصبح مشرف من قبل",
            "أصبح ادمن من قبل", "اصبح ادمن من قبل",
            "أصبح مالك من قبل", "اصبح مالك من قبل",
            "أصبح اونر من قبل", "اصبح اونر من قبل",
            "تم تعيين" + " " + "@",
        ))

        # Ignore bot-generated command confirmations.  They are ordinary text
        # events and were the source of the false alerts shown by the user.
        bot_sender = _norm_user(frm) == _norm_user(BOT_ID)
        bot_generated = any(phrase in bt for phrase in (
            "تمت إضافة", "تمت اضافه", "إلى المراقبة", "الى المراقبة",
            "ستصلك رسالة خاصة",
            "تم تعيين" + " " + "@",
        ))

        if any(x in bt for x in ban_words) or any(x in et for x in ban_words):
            # For text events, require a recognizable system phrase; otherwise
            # words like "حظر" in a normal chat message would be a false alert.
            if et == "text" and not system_text:
                return False
            operation = "حظر"
        elif any(x in bt for x in kick_words) or any(x in et for x in kick_words):
            if et == "text" and not system_text:
                return False
            operation = "طرد"
        elif any(x in bt for x in owner_words):
            if et == "text" and not system_text:
                return False
            operation = "تغيير الونر/المالك"
        elif any(x in bt for x in role_words) or any(x in et for x in role_words):
            if et == "text" and not system_text:
                return False
            operation = "تغيير صلاحية/رتبة"
        elif et in ("user_joined", "you_joined", "user_rejoined", "joined"):
            operation = "دخول / أصبح عضو"
        elif et in ("user_left", "left", "user_exit", "user_exited"):
            operation = "خروج"
        else:
            # Unknown ordinary text/command: do not report it.
            return False

        if et == "text" and (bot_sender or bot_generated):
            return False

        dedupe = "|".join((str(event_id or ""), et, operation, key, str(room or ""), str(frm or ""), str(to or ""), str(role or "")))
        now = time.time()
        with self._monitor_lock:
            if dedupe in self.monitor_seen_events:
                return False
            self.monitor_seen_events[dedupe] = now
            if len(self.monitor_seen_events) > 1000:
                cutoff = now - 3600
                self.monitor_seen_events = {k:v for k,v in self.monitor_seen_events.items() if v >= cutoff}

        # Prefer the RoomEvent id. If the protocol does not provide it, keep
        # the other server identifiers visible instead of inventing a code.
        code_candidates = [
            ("event_id", event_id),
            ("uid", event.get("_result_uid", "") if isinstance(event, dict) else ""),
            ("handler_id", event.get("_handler_id", "") if isinstance(event, dict) else ""),
            ("value", event.get("_result_value", "") if isinstance(event, dict) else ""),
        ]
        code_text = "غير موجود في الحدث"
        for label, value in code_candidates:
            if str(value or "").strip():
                code_text = str(value).strip()
                if label != "event_id":
                    code_text = f"{label}={code_text}"
                break
        lines = [
            "🚨 تنبيه مراقبة حساب",
            f"👤 الحساب: @{display_name}",
            f"⚠️ العملية: {operation}",
            f"🏠 الغرفة: {room or 'غير معروفة'}",
            f"🧩 نوع الحدث: {event_type or 'غير معروف'}",
            f"🔢 كود/معرّف الحدث: {code_text}",
        ]
        if role:
            lines.append(f"👑 الرتبة: {role}")
        if frm:
            lines.append(f"👮 المنفّذ/المرسل: @{frm}")
        if to:
            lines.append(f"🎯 الهدف: @{to}")
        if event.get(5) not in (None, ""):
            lines.append(f"📌 القيمة: {event.get(5)}")
        if body:
            lines.append(f"📝 نص الحدث: {body}")
        return self.send_private_text(BOT_MASTER, "\n".join(lines))

    def _load_social_features(self):
        self.auto_replies_file = BASE_DIR / "auto_replies.json"
        self.custom_welcomes_file = BASE_DIR / "custom_welcomes.json"
        try:
            data = _load_local_json(self.auto_replies_file, {})
            self.auto_replies_enabled = bool(data.get("enabled", True))
            raw = data.get("replies", {})
            self.auto_replies = raw if isinstance(raw, dict) else {}
        except Exception:
            self.auto_replies_enabled, self.auto_replies = True, {}
        try:
            data = _load_local_json(self.custom_welcomes_file, {})
            self.custom_welcome_enabled = bool(data.get("enabled", True))
            raw = data.get("welcomes", {})
            self.custom_welcomes = raw if isinstance(raw, dict) else {}
        except Exception:
            self.custom_welcome_enabled, self.custom_welcomes = True, {}

    def _save_social_features(self):
        _save_local_json(self.auto_replies_file, {"enabled": self.auto_replies_enabled, "replies": self.auto_replies})
        _save_local_json(self.custom_welcomes_file, {"enabled": self.custom_welcome_enabled, "welcomes": self.custom_welcomes})

    def log(self, *args):
        if DEBUG:
            print(*args, flush=True)

    def report_master_error(self, context: str, error, room: str = ""):
        """Send the real diagnostic privately without exceeding Talkin's limit."""
        detail = " ".join(str(error or "خطأ غير معروف").split())
        location = f" | الغرفة: {room}" if room else ""
        message = f"❌ خطأ {context}{location}\nالتفاصيل: {detail}"
        self.log(f"[{context}]", repr(error))
        # Music/gift failures must remain visible in Railway Logs even when
        # DEBUG=0; the master also receives the complete diagnostic privately.
        print(f"[{context}] {detail}", flush=True)
        if BOT_MASTER and _norm_user(BOT_MASTER) != _norm_user(BOT_ID):
            try:
                self.send_private_text(BOT_MASTER, message)
            except Exception as notify_error:
                self.log("[MASTER-ERROR] failed:", repr(notify_error))

    def authenticate(self):
        body = encode_auth_request(BOT_ID, BOT_PWD)
        url = API_BASE_URL + "auth_new"
        self.log("[AUTH] POST", url)
        r = self.http.post(
            url,
            data=body,
            headers={"Content-Type": "application/octet-stream", "User-Agent": "Talkinchat/1.0 (Android 12; net.chatp)"},
            timeout=15,
        )
        r.raise_for_status()
        self.auth = decode_auth_result(r.content)
        self.log("[AUTH] result=", self.auth["result"], "user_id=", self.auth["user_id"], "server=", self.auth["server"])
        if self.auth["message"]:
            self.log("[AUTH] message=", self.auth["message"])
        self.auth_server = self.auth["server"] if self.auth["server"].isdigit() else ""
        # The APK stores AuthResult.id as the shared-preference captcha_id,
        # and M9/c.c() uses that value in the default `b` handshake header.
        # Using the hard-coded default `0` causes the server to accept the
        # HTTP/WebSocket upgrade but then close with `require_login`.
        if self.auth.get("id"):
            self.captcha_id = self.auth["id"]
        else:
            self.captcha_id = os.getenv("CAPTCHA_ID", "0")
        self.photo_version = self.auth.get("photo_version") or os.getenv("PHOTO_VERSION", "0")
        self.roster_version = os.getenv("ROSTER_VERSION", "0")
        self.log("[AUTH] session id/captcha_id received; using it for WS b header")
        self.port = DEFAULT_PORT
        if self.auth["result"].lower() not in ("ok", "success", "true", "1"):
            raise RuntimeError("Authentication rejected: " + (self.auth["message"] or self.auth["result"]))
        return self.auth

    @staticmethod
    def b64(value: str) -> str:
        # Android Base64.encode(bytes, Base64.NO_WRAP) == standard Base64 without line breaks.
        return base64.b64encode((value or "").encode("utf-8")).decode("ascii")

    def app_ws_headers(self):
        """Use the default TalkinChat 5.8.3 Client branch: a single `b` header.

        Client.smali checks SharedPreferences `default/m` with default `n`.
        On the normal/default path it calls M9/c.c(), which builds `b` from:
        captcha_id @ android_id @ device_model @ android@language@photo_version@roster_version
        and Base64.NO_WRAP encodes the whole string.
        """
        user_id = str((self.auth or {}).get("user_id") or os.getenv("USER_ID", "0"))
        captcha_id = getattr(self, "captcha_id", os.getenv("CAPTCHA_ID", "0"))
        photo_version = getattr(self, "photo_version", os.getenv("PHOTO_VERSION", "0"))
        roster_version = getattr(self, "roster_version", os.getenv("ROSTER_VERSION", "0"))

        raw = (
            captcha_id + "@" +
            DEVICE_ID + "@" +
            DEVICE_MODEL + "@android@" +
            LANGUAGE + "@" +
            photo_version + "@" +
            roster_version
        )
        encoded = self.b64(raw)
        if DEBUG:
            self.log("[WS] b(decoded)=", raw)
            self.log("[WS] b(base64)=", encoded)
            self.log("[WS] b(user_id)=", user_id)
        return ["b: " + encoded]

    def websocket_url(self, path=None):
        # Authentication is separate via auth_new. Keep the path configurable
        # because the service has returned 404 for the old /server endpoint
        # when its realtime gateway is moved.
        return "wss://%s:%s%s" % (
            getattr(self, "ws_host", HOST), self.port,
            path if path is not None else getattr(self, "ws_path", WS_PATHS[0]),
        )

    def send_query(self, payload: bytes):
        if not self.ws:
            raise RuntimeError("WebSocket is not connected")
        self.ws.send_binary(payload)

    def _extract_room_name(self, item):
        """Best-effort extraction of a Talkin room name from a decoded room item."""
        if isinstance(item, str):
            v=item.strip()
            return v if v else ""
        if not isinstance(item, dict):
            return ""
        # Known/likely room-name fields in the protocol, ordered by preference.
        for key in ("name", "room", "title", "room_name", "roomName", "group_name", 2, 1, 3, 4):
            v=item.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Some builds nest the room object in one field.
        for v in item.values():
            if isinstance(v, dict):
                got=self._extract_room_name(v)
                if got: return got
        return ""

    def _remember_room_list(self, rooms):
        found=[]
        for item in (rooms or []):
            name=self._extract_room_name(item)
            if name and name != BOT_MASTER:
                found.append(name)
        if found:
            with self._rooms_list_lock:
                self.available_rooms.update(found)
            self._rooms_list_event.set()
            self.log("[ROOM-LIST] discovered", len(found), "rooms")
        return found

    def discover_all_rooms(self, wait_seconds=3.0):
        """Ask the server for a fresh room list and return discovered room names."""
        self._rooms_list_event.clear()
        with self._rooms_list_lock:
            self.available_rooms.clear()
        try:
            self.send_query(encode_query("load_list_new"))
            self.log("[ROOM-LIST] fresh load_list_new requested")
        except Exception as e:
            self.log("[ROOM-LIST] request failed:", repr(e))
            return []
        self._rooms_list_event.wait(max(0.5, float(wait_seconds)))
        with self._rooms_list_lock:
            return sorted(self.available_rooms)

    def join_all_rooms(self):
        """Join every room returned by the fresh server room-list request."""
        rooms=self.discover_all_rooms()
        joined=0
        for room in rooms:
            try:
                if self.join_room(room):
                    joined += 1
            except Exception as e:
                self.log("[ROOM] join-all failed", room, repr(e))
        return rooms, joined

    def join_room(self, room: str, force: bool = False):
        """Join a room without spamming room_join.

        TalkinChat treats room_join as a membership change on a WebSocket.
        Re-sending it repeatedly can produce the visible leave/join loop.
        Therefore the bot sends it once per room unless explicitly forced.
        """
        room = str(room or "").strip()
        if not room:
            return False
        now = time.time()
        with self._join_lock:
            last = self._last_join_sent.get(room, 0.0)
            if not force and now - last < float(os.getenv("JOIN_DEBOUNCE_SECONDS", "20")):
                self.log("[ROOM] join suppressed (debounce):", room)
                return False
            self._last_join_sent[room] = now
        self.log("[ROOM] joining", room)
        self.send_query(encode_query("room_join", room=room, int_value=0, force_int_value=True))
        self.known_rooms.add(room)
        return True

    def leave_room(self, room: str):
        """Leave exactly one Talkin room using the APK's room_leave packet."""
        room = str(room or "").strip()
        if not room:
            return False
        self.send_query(encode_query("room_leave", room=room))
        with self._join_lock:
            self.known_rooms.discard(room)
            self._last_join_sent.pop(room, None)
        self.room_users.pop(room, None)
        self.log("[ROOM] left", room)
        return True

    def leave_all_rooms(self):
        """Leave every currently tracked room; no room is automatically rejoined."""
        rooms = [r for r in self.known_rooms if str(r).strip()]
        for room in rooms:
            try:
                self.leave_room(room)
            except Exception as e:
                self.log("[ROOM] leave failed", room, repr(e))
        return rooms

    def _split_talkin_text(self, text: str, limit: int = None):
        """Compatibility helper: command menus use their own <=300 splitter."""
        text = str(text or "")
        return [text] if text else [""]

    def _send_text_packets(self, packet_type: str, text: str, **kwargs):
        # All normal results stay in ONE message: games, music, publishing,
        # points, admin results, etc. Only command-menu pages are split.
        payload = dict(kwargs)
        payload["type_"] = "text"
        payload["body"] = str(text or "")
        self.send_query(encode_query(packet_type, **payload))
        return True

    def _send_help_chunks(self, packet_type: str, text: str, limit: int = 300, **kwargs):
        """Send a command list in ordered chunks, each <= 300 chars."""
        text = str(text or "")
        if not text:
            return True
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        chunks=[]; current=""
        for line in lines:
            candidate = line if not current else current + "\n" + line
            if len(candidate) <= limit:
                current=candidate
            else:
                if current:
                    chunks.append(current)
                # A single command should normally fit; hard-split only if needed.
                while len(line) > limit:
                    cut=line.rfind(" ",0,limit+1)
                    if cut < max(20,limit//2): cut=limit
                    chunks.append(line[:cut].rstrip())
                    line=line[cut:].lstrip()
                current=line
        if current: chunks.append(current)
        for chunk in chunks:
            payload=dict(kwargs); payload["type_"]="text"; payload["body"]=chunk
            self.send_query(encode_query(packet_type, **payload))
        return True

    def set_bot_status(self, text: str, restore_seconds: int = 0):
        """Set the bot profile status/bio and also try the Talkin status packet.

        The supplied Talkin/Giant web app exposes a profile ``bio`` field.  To
        make the visible profile text actually persist, we update the bot's
        profile through Supabase when possible.  We also send the native status
        query for Talkin builds that expose a separate status field.
        """
        text = str(text or self.bot_status_text).strip() or self.bot_status_text
        ok = False
        try:
            # Persist the visible profile text.  The bot's authenticated DB
            # identity is resolved from its username.
            if getattr(self, "db", None) and getattr(self.db, "client", None):
                try:
                    # Prefer the authenticated Talkin user id returned by auth.
                    uid = str((getattr(self, "auth", None) or {}).get("user_id") or "").strip()
                    rows = []
                    if uid:
                        q = self.db.client.table("profiles").select("id,username").eq("id", uid).limit(1).execute()
                        rows = getattr(q, "data", None) or []
                    # Fallback for configurations where BOT_ID is the username.
                    if not rows and BOT_ID:
                        q = self.db.client.table("profiles").select("id,username").ilike("username", BOT_ID).limit(1).execute()
                        rows = getattr(q, "data", None) or []
                        if not rows:
                            q = self.db.client.table("profiles").select("id,username").eq("username", BOT_ID).limit(1).execute()
                            rows = getattr(q, "data", None) or []
                    if rows and rows[0].get("id"):
                        uid = str(rows[0]["id"])
                        self.db.client.table("profiles").update({"bio": text}).eq("id", uid).execute()
                        self.log("[STATUS] profile bio updated")
                        ok = True
                except Exception as e:
                    self.log("[STATUS] profile update failed:", repr(e))

            # Also try the Talkin native profile/status action for clients that
            # support it. Failure here must not break the bot.
            try:
                with self._status_lock:
                    self.send_query(encode_query(
                        os.getenv("TALKIN_STATUS_ACTION", "set_status"),
                        type_="text", body=text, value=text
                    ))
                self.log("[STATUS] native status sent: " + text)
                ok = True
            except Exception as e:
                self.log("[STATUS] native status failed:", repr(e))

            if restore_seconds > 0:
                with self._status_lock:
                    if self._status_restore_timer:
                        try: self._status_restore_timer.cancel()
                        except Exception: pass
                    self._status_restore_timer = threading.Timer(
                        restore_seconds, self.set_bot_status,
                        args=(self.bot_status_text, 0)
                    )
                    self._status_restore_timer.daemon = True
                    self._status_restore_timer.start()
            return ok
        except Exception as e:
            self.log("[STATUS] failed:", repr(e))
            return False

    def _set_default_bot_status(self):
        self.set_bot_status(self.bot_status_text, 0)

    def send_command_reply(self, room: str, sender: str, text: str, is_private: bool = False):
        """Route command replies to the same context that received the command.

        Private command -> private reply. Room command -> room reply.
        Error/warning replies are always sent privately to avoid exposing
        diagnostics in public rooms.
        """
        room = str(room or "").strip()
        sender = str(sender or "").strip()
        text = str(text or "")
        is_error = text.lstrip().startswith(("❌", "⚠️", "🚫")) or "فشل" in text[:80]
        if sender and (is_private or is_error):
            return self.send_private_text(sender, text)
        if room:
            return self.send_room_text(room, text)
        if sender:
            return self.send_private_text(sender, text)
        return False

    def send_room_text(self, room: str, text: str):
        return self._send_text_packets("room_message", text, room=room)

    def send_room_lines(self, room: str, lines):
        for line in lines:
            if line is not None:
                self.send_room_text(room, str(line))
        return True

    def send_admin(self, room: str, target: str, operation: str):
        # Real Talkin moderation is performed through the backend RPCs discovered
        # in the supplied app source, not by a local ban list or a guessed packet.
        if operation in ("kick", "ban", "unban"):
            return self.db.moderation_rpc(room, target, operation)
        # Role changes remain on the native room_admin transport until their exact
        # backend RPC argument signature is confirmed.
        role_map = {
            "outcast": "outcast",
            "admin": "admin",
            "member": "member",
            "owner": "owner",
            "none": "none",
        }
        if operation in role_map:
            return self.send_query(encode_query("room_admin", type_="change_role", room=room, to=target, value=role_map[operation]))
        raise ValueError("Unknown admin operation: " + operation)

    def ack(self, uid: str):
        if uid:
            self.send_query(encode_query("ack_msg", uid=uid))

    def send_private_text(self, username: str, text: str):
        """Send the complete private text in safe sequential chunks.

        The private chat may display long reports, but one oversized protobuf
        can make Talkin close the entire WebSocket with code 1009. Chunking
        preserves every character while keeping each packet below the safe
        room/server limit.
        """
        username = str(username or "").strip()
        if not username or username == BOT_ID:
            return False
        return self._send_text_packets("chat_message", text, to=username)

    def send_private_media(self, username: str, media_url: str, media_type: str, duration: int = 0):
        """Send audio/image back to the private-chat sender."""
        return self.send_query(encode_query(
            "chat_message", type_=media_type, to=username, url=media_url,
            length=str(max(0, int(duration or 0))) if media_type == "audio" else None
        ))

    def reply_text(self, room: str, text: str, private_to: str = ""):
        return self.send_private_text(private_to, text) if private_to else self.send_room_text(room, text)

    def request_occupants(self, room: str = ""):
        """Load users from ALL rooms currently joined by the bot.

        The room argument is only the command-context room: it is used in the
        invitation text. The source roster is collected from every room in
        self.known_rooms, so joining another room never replaces old rooms.
        """
        with self.invite_lock:
            if self.invite_pending:
                self.send_private_text(BOT_MASTER, "⏳ ما زلت أجمع معلومات الغرف، انتظر حتى تكتمل العملية.")
                return
            self.invite_pending = True
            self.invite_room = str(room or self.room or "").strip()
            self.invite_sent.clear()

        command_room = self.invite_room
        active_rooms = []
        for r in list(self.known_rooms):
            r = str(r).strip()
            if r and r not in active_rooms:
                active_rooms.append(r)
        self.log("[INV] loading users from ALL active rooms:", active_rooms)
        try:
            self.send_private_text(
                BOT_MASTER,
                f"⏳ جاري جمع جميع المستخدمين من {len(active_rooms)} غرفة...\n"
                f"📌 نص الدعوة سيكون باسم الغرفة التي نُفّذ فيها inv: {command_room}"
            )
        except Exception as e:
            self.log("[INV] private progress message failed:", repr(e))

        # Collect the persistent roster for every room. This includes members
        # who are currently offline, not just the live occupants.
        all_users = []
        seen = set()
        room_counts = {}
        for source_room in active_rooms:
            db_users = self.db.room_users(source_room)
            room_counts[source_room] = len(db_users)
            for u in db_users or []:
                username = str(u.get("username") or "").strip() if isinstance(u, dict) else ""
                if not username or username == BOT_ID:
                    continue
                key = username.casefold()
                if key in seen:
                    continue
                seen.add(key)
                all_users.append(username)

        if all_users:
            self.log(f"[INV] ALL rooms loaded: rooms={len(active_rooms)} unique_users={len(all_users)} counts={room_counts}")
            self.process_occupants_for_invite({
                "db_users": [{"username": u} for u in all_users],
                "source_rooms": active_rooms,
            })
            return

        # If DB is unavailable, request occupants_list from every active room.
        # Results are accumulated by room until all responses arrive.
        self._inv_expected_rooms = set(active_rooms)
        self._inv_live_users = []
        self._inv_live_seen = set()
        self._inv_command_room = command_room
        if not active_rooms:
            with self.invite_lock:
                self.invite_pending = False
            self.send_private_text(BOT_MASTER, "⚠️ لا توجد غرف نشطة حالياً. استخدم: دخول اسم_الغرفة")
            return
        for source_room in active_rooms:
            try:
                self.send_query(encode_query(
                    "room_admin", type_="occupants_list", room=source_room,
                    to=BOT_ID, value="none"
                ))
            except Exception as e:
                self.log("[INV] occupants request failed", source_room, repr(e))
                self._inv_expected_rooms.discard(source_room)
        if not self._inv_expected_rooms:
            with self.invite_lock:
                self.invite_pending = False

    def send_native_system_invite(self, username: str, room: str):
        """Send the platform's native room invitation through its Supabase RPC.

        The supplied web/admin source calls room_invite_username with:
            {"_room": <room UUID>, "_username": <username>}
        This is different from chat_message: it creates the same invitation flow
        used by the official system, subject to the bot's authenticated account
        having permission to invite in that room.
        """
        if not self.db.client:
            return False, "Supabase client غير متاح"
        rid = self.db.room_id(room)
        if not rid:
            return False, "لم أجد room_id للغرفة في قاعدة البيانات"
        try:
            res = self.db.client.rpc("room_invite_username", {"_room": rid, "_username": str(username).strip()}).execute()
            err = getattr(res, "error", None)
            data = getattr(res, "data", None)
            if err:
                detail = str(getattr(err, "message", err))
                self.log("[INV] RPC error:", username, detail)
                return False, detail
            self.log("[INV] RPC OK:", username, "data=", repr(data)[:300])
            return True, "ok"
        except Exception as e:
            detail = repr(e)
            self.log("[INV] RPC exception:", username, detail)
            return False, detail

    def send_private_invite(self, username: str, room: str):
        """Send a NORMAL private chat invitation, not a system/RPC invitation.

        The room name is always the exact room in which the `inv` command was
        executed (or the room explicitly supplied to a master private `inv`
        command). This keeps the invitation text tied to the command room.
        """
        username = str(username or "").strip()
        room = str(room or "").strip()
        if not username or username == BOT_ID or not room:
            return False
        with self.invite_lock:
            if username in self.invite_sent:
                return False

        # IMPORTANT: normal TalkinChat private message, deliberately NOT
        # room_invite_username / native system invitation.
        text = self.invite_message_template
        try:
            text = text.format(sender=INVITE_SENDER_NAME, room=room, username=username)
        except Exception:
            text = f"{INVITE_SENDER_NAME} يدعوك للغرفة {room}"
        self.send_query(encode_query("chat_message", type_="text", to=username, body=text))

        with self.invite_lock:
            self.invite_sent.add(username)
        self.log("[INV] normal private invite sent:", username, "room=", room)
        return True

    def _users_from_room_admin(self, room_admin):
        """Extract UserItem records from RoomAdmin field 10.

        UserItem fields in the APK: 1=username, 2=user_id, 3=photo,
        4=status, 5=online, 6=role.  The old decoder converted nested
        protobuf bytes to strings, so V12 keeps the bytes and decodes them
        here before any invitation or role grouping is done.
        """
        if not isinstance(room_admin, dict):
            return []
        raw = room_admin.get(10) or []
        if not isinstance(raw, list):
            raw = [raw]
        users = []
        for item in raw:
            try:
                if isinstance(item, bytes):
                    uf = decode_message(item)
                elif isinstance(item, dict):
                    uf = item
                else:
                    continue
                username = first_text(uf, 1).strip()
                role = first_text(uf, 6).strip().lower()
                user_id = first_text(uf, 2).strip()
                online = first_text(uf, 5).strip()
                if username and username != BOT_ID:
                    users.append({"username": username, "role": role or "none",
                                  "user_id": user_id, "online": online})
            except Exception as e:
                self.log("[INV] UserItem decode failed:", repr(e))
        # De-duplicate by username while preserving server order.
        out = []
        seen = set()
        for u in users:
            k = u["username"].casefold()
            if k not in seen:
                seen.add(k)
                out.append(u)
        return out

    def _usernames_from_room_admin(self, room_admin):
        return [u["username"] for u in self._users_from_room_admin(room_admin)]

    def _finish_invites(self, room, usernames):
        """Send invitations in a worker so the main receive loop stays alive."""
        count = 0
        try:
            for username in usernames:
                try:
                    if self.send_private_invite(username, room):
                        count += 1
                    # Small pacing gap, but never blocks the WebSocket reader.
                    time.sleep(0.08)
                except Exception as e:
                    self.log("[INV] failed for", username, repr(e))

            self.log(f"[INV] occupants loaded: {len(usernames)}, invitations sent: {count}")
            try:
                if count == 0:
                    self.send_private_text(BOT_MASTER,
                        f"⚠️ لم تُرسل أي دعوة نظام. DB client={'نعم' if self.db.client else 'لا'} | "
                        f"Supabase room_id={self.db.last_room_id or 'غير موجود'} | "
                        f"room_members={self.db.last_member_count} | profiles={self.db.last_profile_count} | "
                        f"آخر خطأ={self.db.last_error or 'راجع سجل Pydroid'}")
            except Exception:
                pass
            try:
                self.send_private_text(
                    BOT_MASTER,
                    f"✅ تم جمع معلومات الغرفة. عدد المستخدمين: {len(usernames)}\n"
                    f"📨 تم إرسال الدعوة العادية على الخاص إلى: {count} مستخدم."
                )
            except Exception as e:
                self.log("[INV] final private result failed:", repr(e))
        finally:
            with self.invite_lock:
                self.invite_pending = False

    def process_occupants_for_invite(self, result):
        if not self.invite_pending:
            return
        room = self.invite_room or self.room

        # Fallback live responses are tagged by the room they came from.
        # Accumulate all room responses before sending the final invitation batch.
        source_room = str(result.get("_occupants_room") or "").strip()
        if source_room and hasattr(self, "_inv_expected_rooms"):
            for u in self._users_from_room_admin(result.get("room_admin") or {}):
                username = str(u.get("username") or "").strip()
                if username and username != BOT_ID and username.casefold() not in getattr(self, "_inv_live_seen", set()):
                    self._inv_live_seen.add(username.casefold())
                    self._inv_live_users.append(username)
            self._inv_expected_rooms.discard(source_room)
            if self._inv_expected_rooms:
                return
            result = {"db_users": [{"username": u} for u in self._inv_live_users]}

        users_info = []
        for user in (result.get("db_users") or []):
            if isinstance(user, dict):
                username = str(user.get("username") or "").strip()
                if username and username != BOT_ID:
                    users_info.append({"username": username, "role": "none", "user_id": str(user.get("user_id") or "")})

        # Some server builds return ResultMessage.users directly.
        for user in (result.get("users") or []):
            if not isinstance(user, dict):
                continue
            username = str(user.get(1, "") or "").strip()
            role = str(user.get(6, "") or "none").strip().lower()
            if username and username != BOT_ID:
                users_info.append({"username": username, "role": role or "none"})

        # Actual occupants_list response: RoomAdmin field 10 contains the
        # repeated UserItem protobuf messages.
        if not users_info and result.get("room_admin"):
            users_info = self._users_from_room_admin(result["room_admin"])

        # Cache the complete room list, including role categories.
        if users_info:
            self.room_users[room] = {u["username"]: u.get("role", "none") for u in users_info}

        if not users_info:
            self.log("[INV] occupants response received but no usernames decoded")
            try:
                self.send_private_text(BOT_MASTER, "⚠️ وصلت بيانات إعدادات الغرفة لكن لم أستطع استخراج أسماء المستخدمين.")
            except Exception:
                pass
            with self.invite_lock:
                self.invite_pending = False
            return

        # Categorize exactly as the room settings list does.
        owners = [u["username"] for u in users_info if u.get("role") == "owner"]
        admins = [u["username"] for u in users_info if u.get("role") == "admin"]
        members = [u["username"] for u in users_info if u.get("role") not in ("owner", "admin")]
        self.log(f"[INV] room={room} total={len(users_info)} owners={len(owners)} admins={len(admins)} members={len(members)}")

        # Master gets the progress/result privately; no public room spam.
        try:
            self.send_private_text(
                BOT_MASTER,
                f"📋 تم تحميل إعدادات الغرفة. الكل: {len(users_info)} | المالكين: {len(owners)} | المشرفين: {len(admins)} | الأعضاء: {len(members)}"
            )
        except Exception as e:
            self.log("[INV] role summary failed:", repr(e))

        self.invite_thread = threading.Thread(
            target=self._finish_invites,
            args=(room, [u["username"] for u in users_info]),
            name="talkin-invites",
            daemon=True,
        )
        self.invite_thread.start()


    def send_room_media(self, room: str, media_url: str, media_type: str, duration: int = 0):
        """Send room media using Query's normal room/url fields.

        Text messages already prove that Query field ``room`` (field 6) is
        the room identifier. Media uses the same field; ``length`` (field 3)
        carries the optional audio duration. Putting the room in ``password``
        made Talkin accept the packet but discard the image/audio payload.
        """
        if media_type == "audio":
            return self.send_query(encode_query(
                "room_message", type_="audio",
                length=str(max(0, int(duration or 0))), room=room, url=media_url
            ))
        return self.send_query(encode_query(
            "room_message", type_=media_type, room=room, url=media_url
        ))

    def _music_download(self,query):
        """Search/download public audio and return an MP3 ready for TalkinChat.

        Primary source: SoundCloud (public audio, independent of YouTube).
        Fallback: YouTube through yt-dlp with optional YOUTUBE_COOKIES.
        Public YouTube/Spotify URLs are first resolved to a title so the
        SoundCloud route can still be used when YouTube extraction is blocked.
        """
        if yt_dlp is None:
            raise RuntimeError("yt-dlp غير مثبت")

        outdir=BASE_DIR/"generated_music"
        outdir.mkdir(parents=True,exist_ok=True)
        stamp=uuid.uuid4().hex
        out_mp3=outdir/(stamp+".mp3")
        errors=[]

        def resolve_public_title(value):
            """Get public page title without downloading media."""
            try:
                u=str(value or "").strip()
                if not re.match(r"^https?://",u,re.I):
                    return ""
                if "youtube.com" in u.lower() or "youtu.be" in u.lower():
                    r=requests.get("https://www.youtube.com/oembed",params={"url":u,"format":"json"},
                                   headers={"User-Agent":"Mozilla/5.0"},timeout=15)
                    if r.ok:
                        data=r.json()
                        return str(data.get("title") or "").strip()
                if "open.spotify.com" in u.lower():
                    r=requests.get(u,headers={"User-Agent":"Mozilla/5.0"},timeout=15)
                    if r.ok:
                        m=re.search(r'<meta[^>]+property=[\"\']og:title[\"\'][^>]+content=[\"\']([^\"\']+)',r.text,re.I)
                        if not m:
                            m=re.search(r'<meta[^>]+content=[\"\']([^\"\']+)[\"\'][^>]+property=[\"\']og:title[\"\']',r.text,re.I)
                        if m:
                            title=re.sub(r'\s*\|\s*Spotify\s*$','',m.group(1),flags=re.I).strip()
                            return title
            except Exception as exc:
                errors.append(f"Public metadata: {type(exc).__name__}: {exc}")
            return ""

        def normalize_to_mp3(source, duration=0):
            if duration and int(duration) > MUSIC_MAX_SECONDS:
                raise RuntimeError(f"الأغنية أطول من {MUSIC_MAX_SECONDS} ثانية")
            source=Path(source)
            if source.suffix.lower()==".mp3":
                return source
            ffmpeg_bin=shutil.which("ffmpeg")
            if not ffmpeg_bin:
                raise RuntimeError("FFmpeg غير موجود داخل Railway")
            proc=subprocess.run([
                ffmpeg_bin,"-y","-hide_banner","-loglevel","error",
                "-i",str(source),"-vn","-ac","2","-ar","44100",
                "-codec:a","libmp3lame","-b:a","192k",str(out_mp3)
            ],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=180)
            if proc.returncode!=0 or not out_mp3.is_file() or out_mp3.stat().st_size<=4096:
                detail=" | ".join((proc.stderr or "").strip().splitlines()[-4:])
                raise RuntimeError("فشل تحويل الصوت إلى MP3: "+detail[:500])
            try: source.unlink()
            except Exception: pass
            return out_mp3

        def download_with_ydl(target,label,cookies=False):
            tmpdir=outdir/f".{stamp}_{label}"
            tmpdir.mkdir(parents=True,exist_ok=True)
            template=str(tmpdir/"source.%(ext)s")
            opts={
                "quiet":True,"no_warnings":True,"noplaylist":True,
                "format":"bestaudio/best","outtmpl":template,
                "socket_timeout":45,"retries":5,"fragment_retries":5,
                "extractor_retries":3,"file_access_retries":3,
                "cachedir":False,"overwrites":True,
                "concurrent_fragment_downloads":1,
                "http_headers":{"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"},
                "check_formats":False,
                "js_runtimes":{"node":{}},
                "remote_components":{"ejs":"github"},
            }
            if cookies and YOUTUBE_COOKIE_FILE:
                opts["cookiefile"]=YOUTUBE_COOKIE_FILE
            if label.startswith("youtube_"):
                client=label.split("_",1)[1]
                if client != "native_default":
                    opts["extractor_args"]={"youtube":{"player_client":[client]}}
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info=ydl.extract_info(target,download=True)
                    if info and info.get("entries"):
                        info=next((x for x in info["entries"] if x),None)
                    if not info:
                        raise RuntimeError("لم يتم العثور على الأغنية")
                candidates=[x for x in tmpdir.iterdir() if x.is_file() and x.suffix.lower() not in (".part",".ytdl",".temp") and x.stat().st_size>4096]
                if not candidates:
                    raise RuntimeError("تم العثور على الأغنية لكن لم يكتمل الملف الصوتي")
                source=max(candidates,key=lambda x:x.stat().st_mtime)
                duration=int(info.get("duration") or 0)
                mp3=normalize_to_mp3(source,duration)
                return {
                    "id":str(info.get("id") or ""),
                    "title":str(info.get("title") or query),
                    "uploader":str(info.get("uploader") or info.get("channel") or ""),
                    "duration":duration,
                },mp3
            except Exception as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")
                shutil.rmtree(tmpdir,ignore_errors=True)
                return None

        # Resolve URL to a searchable title when possible. This lets a
        # blocked YouTube/Spotify URL still use SoundCloud as the source.
        search_query=str(query or "").strip()
        if re.match(r"^https?://",search_query,re.I):
            title=resolve_public_title(search_query)
            if title:
                search_query=title

        # -------- SoundCloud primary source --------
        sc_targets=[]
        if re.match(r"^https?://",query,re.I) and "soundcloud.com" in query.lower():
            sc_targets=[query]
        elif search_query:
            sc_targets=["scsearch1:"+search_query]

        for target in sc_targets:
            result=download_with_ydl(target,"soundcloud",cookies=False)
            if result:
                info,mp3=result
                for child in outdir.glob(f".{stamp}_*"):
                    if child.is_dir(): shutil.rmtree(child,ignore_errors=True)
                return info,mp3

        # -------- YouTube fallback --------
        youtube_target=query if re.match(r"^https?://",query,re.I) else "ytsearch1:"+query
        for client in ("web_embedded","default","native_default"):
            result=download_with_ydl(youtube_target,f"youtube_{client}",cookies=True)
            if result:
                info,mp3=result
                for child in outdir.glob(f".{stamp}_*"):
                    if child.is_dir(): shutil.rmtree(child,ignore_errors=True)
                return info,mp3

        detail=" | ".join(errors[-10:])
        raise RuntimeError("تعذر تنزيل ملف صوت من SoundCloud أو YouTube."+(f" تفاصيل: {detail[:1200]}" if detail else ""))

    def handle_music_command(self,room,text,requester,private_to=""):
        raw=text.strip()
        if not raw.lower().startswith(".sa "): return False
        query=raw[4:].strip()
        if not query: self.reply_text(room,"❌ اكتب: .sa اسم الأغنية",private_to); return True
        now=time.time(); last=self.music_last.get(requester,0)
        if now-last<MUSIC_COOLDOWN: self.reply_text(room,f"⏳ انتظر {int(MUSIC_COOLDOWN-(now-last))+1} ثانية.",private_to); return True
        self.music_last[requester]=now
        def worker():
            try:
                public_base = _public_base_url()
                if not public_base: raise RuntimeError("لا يوجد رابط عام للصوت؛ أنشئ Railway Public Domain أو ضع PUBLIC_BASE_URL")
                info,path=self._music_download(query)
                title=str(info.get("title") or query)
                artist=str(info.get("uploader") or info.get("channel") or "YouTube")
                duration=int(info.get("duration") or 0)
                url=public_base+"/media/"+path.name
                # Music posts use the user's messages.json template.  The
                # reaction code is intentionally limited to 4 characters.
                code=uuid.uuid4().hex[:4]
                caption=_message_template(
                    "music", "broadcast",
                    "🎵 {title}\n🎤 {requester_name}\n🎶 {title}\n📡 المصدر: {source_label}\n🏠 الغرفة الأصلية: {room}\n━━━━━━━━━━━━━\n👍 lk@{code}\n❤️ lv@{code}\n👎 dl@{code}\n💬 cm@{code} msg\n🚨 report@{code} msg",
                    requester_name=requester, title=title, artist=artist,
                    source_label=artist or "Music", room=room, code=code,
                    url=url, duration=duration
                )
                # Music is broadcast to every room currently joined by the bot.
                # The requester also receives the same post privately.
                self.reaction_targets[code] = {"publisher": requester, "kind": "music", "title": title, "description": title, "created_at": time.time()}
                target_rooms=list(self.known_rooms) or ([room] if room else [])
                for target_room in target_rooms:
                    self.send_room_text(target_room,caption)
                    self.send_room_media(target_room,url,"audio",duration)
                self.send_private_text(requester,caption)
                self.send_private_media(requester,url,"audio",duration)
            except Exception as e:
                self.report_master_error("تشغيل الأغنية", e, room)
                self.reply_text(room, "❌ تعذر تشغيل الأغنية. تم إرسال الخطأ الحقيقي للماستر.", private_to)
        threading.Thread(target=worker,name="music-request",daemon=True).start(); self.reply_text(room,"⏳ جاري البحث عن الأغنية وتحضير الصوت...",private_to); return True

    def send_gift_native(self, room: str, gift_id: str, target_username: str):
        """Legacy/native packet kept for diagnostics only. Gift command now sends the real asset image."""
        kwargs = {"room": room}
        kwargs[GIFT_TARGET_FIELD] = target_username
        kwargs[GIFT_ID_FIELD] = gift_id
        return self.send_query(encode_query("gifts", type_=GIFT_PROTOCOL, **kwargs))

    def gift_help(self, room):
        lines = ["🎁 الهدايا المتاحة:"]
        for k, (emoji, name) in GIFT_CATALOG.items():
            lines.append(f"{k} {emoji} {name}")
        lines.append("📌 الإرسال: sa@رقم_الهدية@اسم_المستخدم")
        self.send_room_text(room, "\n".join(lines))

    def _verify_public_media_url(self, url: str, media_kind: str = "image"):
        try:
            r=requests.get(url,headers={"Range":"bytes=0-4095","User-Agent":"TalkinBot/22"},timeout=15,stream=True)
            ctype=(r.headers.get("Content-Type") or "").lower()
            if r.status_code not in (200,206):
                raise RuntimeError(f"الرابط العام أعاد HTTP {r.status_code}")
            if media_kind=="image" and not ctype.startswith("image/"):
                raise RuntimeError(f"نوع الصورة غير صحيح: {ctype or 'unknown'}")
            if media_kind=="audio" and not (ctype.startswith("audio/") or "octet-stream" in ctype):
                raise RuntimeError(f"نوع الصوت غير صحيح: {ctype or 'unknown'}")
            return True
        except Exception as exc:
            self.log("[MEDIA] public URL check failed:",repr(exc))
            raise RuntimeError(f"الرابط العام للوسائط غير قابل للوصول: {exc}") from exc

    def handle_gift_command(self, room: str, text: str, sender_name: str = "", private_to: str = ""):
        raw=text.strip(); m=re.match(r"^sa@([^@]+)@(.+)$",raw,re.I)
        if not m: return False
        gift_id=m.group(1).strip(); target=m.group(2).strip().lstrip("@"); item=GIFT_CATALOG.get(gift_id)
        if not item or not target:
            self.reply_text(room,"❌ الصيغة: sa@رقم_الهدية@اسم_المستخدم",private_to); return True
        try:
            sender_name = str(sender_name or BOT_ID).strip()
            # Giant Chat point costs; owner/masters have unlimited points.
            cost=int(GIFT_COSTS.get(str(gift_id),0)); charged=False
            if not _is_master_name(sender_name):
                balance=_get_points(sender_name)
                if balance < cost:
                    self.reply_text(room,f"❌ رصيدك غير كافٍ. الهدية تحتاج {cost} نقطة، ورصيدك {balance}.",private_to); return True
                _add_points(sender_name,-cost); charged=True
            # Render and send the real gift card image, then send the gift text.
            # The image is hosted by the bot media server under /gifts/.
            public_base = _public_base_url()
            if not public_base:
                if charged:
                    _add_points(sender_name, cost)
                raise RuntimeError("لا يوجد رابط عام لصور الهدايا؛ أنشئ Railway Public Domain أو ضع PUBLIC_BASE_URL")
            gift_path = render_gift_card(gift_id, sender_name, target)
            gift_url = public_base + "/gifts/" + gift_path.name
            self._verify_public_media_url(gift_url, "image")
            if not gift_path.is_file() or gift_path.stat().st_size < 64:
                raise RuntimeError(f"ملف صورة الهدية غير صالح: {gift_path}")
            gift_text = f"🎁 {item[0]} {item[1]} | 📤 {sender_name} ➜ 📥 {target} | 💰 {cost} نقطة"
            # Publish every gift to ALL rooms where the bot is currently present.
            # The originating room is included automatically; the private requester
            # still receives a private copy when ``private_to`` is supplied.
            target_rooms = sorted({str(r).strip() for r in self.known_rooms if str(r).strip()})
            if not target_rooms and room:
                target_rooms = [room]
            for target_room in target_rooms:
                self.send_room_media(target_room, gift_url, "image")
                self.send_room_text(target_room, gift_text)
            if private_to:
                self.send_private_media(private_to, gift_url, "image")
                self.send_private_text(private_to, gift_text)
            # Show the gift as the bot profile status briefly, then restore the
            # normal profile status.
            self.set_bot_status(
                f"🎁💫 {item[1]} | من {sender_name} ➜ {target} 💫🎁",
                restore_seconds=30,
            )
        except Exception as e:
            self.report_master_error("إرسال صورة الهدية", e, room)
            self.reply_text(room, "❌ تعذر إرسال صورة الهدية. تم إرسال الخطأ الحقيقي للماستر.", private_to)
        return True

    # ----------------------------- Mini Games -----------------------------
    def _game_award(self, username, amount):
        if not username or _is_master_name(username):
            return _get_points(username)
        return _add_points(username, int(amount))

    def _game_ready(self, username, room, cooldown=3.0):
        key=(str(room or "").casefold(), _norm_user(username))
        now=time.time()
        with self.game_lock:
            last=self.game_cooldown.get(key,0.0)
            if now-last < cooldown:
                return False, int(cooldown-(now-last))+1
            self.game_cooldown[key]=now
        return True,0

    def game_help(self, room):
        # Game results/help are one message; only command menus are chunked.
        self.send_room_text(room, "🎮 ألعاب البوت المجانية:\n━━━━━━━━━━━━\n🍀 حظ — جائزة عشوائية مجانية.\n🎯 تخمين — ابدأ ثم اكتب رقماً من 1 إلى 10.\n🎲 نرد — ارْمِ النرد واربح نقاطاً حسب النتيجة.\n✂️ حجر ورق مقص — اكتب: حجر أو ورق أو مقص.\n🧠 سؤال — سؤال معلومات عامة بجائزة 15 نقطة.\n📌 لا توجد أي تكلفة أو خصم نقاط عند اللعب.")

    def handle_game_command(self, room, text, sender_name):
        raw=str(text or "").strip()
        if not raw or not sender_name: return False
        low=raw.casefold(); key=(str(room or "").casefold(), _norm_user(sender_name))
        if low in ("العاب","ألعاب","لعب","games","game"):
            self.game_help(room); return True

        if re.fullmatch(r"\d{1,2}", raw):
            with self.game_lock: game=self.guess_games.get(key)
            if not game: return False
            guess=int(raw); game["attempts"]+=1; target=game["number"]
            if not 1<=guess<=10:
                self.send_room_text(room,f"🎯 @{sender_name} اختر رقماً من 1 إلى 10."); return True
            if guess==target:
                reward=max(10,30-(game["attempts"]-1)*5)
                with self.game_lock: self.guess_games.pop(key,None)
                balance=self._game_award(sender_name,reward); suffix="♾️" if balance is None else str(balance)
                self.send_room_text(room,f"🎯 مبروك @{sender_name}! الرقم هو {target} ✅\n🏆 ربحت {reward} نقطة.\n💰 الرصيد: {suffix}"); return True
            if game["attempts"]>=3:
                with self.game_lock: self.guess_games.pop(key,None)
                self.send_room_text(room,f"🎯 انتهت المحاولات يا @{sender_name}. الرقم الصحيح كان {target}. 😄"); return True
            hint="⬆️ الرقم أكبر" if guess<target else "⬇️ الرقم أصغر"
            self.send_room_text(room,f"🎯 @{sender_name}: {hint} — بقيت {3-game['attempts']} محاولات."); return True

        if low in ("حظ","الحظ","luck"):
            ok,wait=self._game_ready(sender_name,room,4.0)
            if not ok: self.send_room_text(room,f"⏳ @{sender_name} انتظر {wait} ثوانٍ."); return True
            label,reward=random.choice((("🍀 حظ ممتاز!",30),("✨ حظ جميل!",20),("🌟 حظ متوسط!",10),("😅 حظك اليوم عادي!",5)))
            balance=self._game_award(sender_name,reward); suffix="♾️" if balance is None else str(balance)
            self.send_room_text(room, f"{label}\n👤 @{sender_name}\n🎁 الجائزة: {reward} نقطة\n💰 الرصيد: {suffix}"); return True

        if low in ("نرد","ارم النرد","ارمي النرد","dice"):
            ok,wait=self._game_ready(sender_name,room,3.0)
            if not ok: self.send_room_text(room,f"⏳ @{sender_name} انتظر {wait} ثوانٍ."); return True
            roll=random.randint(1,6); reward={1:2,2:3,3:5,4:7,5:10,6:20}[roll]
            balance=self._game_award(sender_name,reward); suffix="♾️" if balance is None else str(balance)
            self.send_room_text(room,f"🎲 @{sender_name} رمى النرد: {roll}\n🎁 ربحت {reward} نقطة!\n💰 الرصيد: {suffix}"); return True

        if low in ("حجر","ورق","مقص"):
            ok,wait=self._game_ready(sender_name,room,3.0)
            if not ok: self.send_room_text(room,f"⏳ @{sender_name} انتظر {wait} ثوانٍ."); return True
            bot_choice=random.choice(("حجر","ورق","مقص"))
            if low==bot_choice: result,reward="🤝 تعادل!",5
            elif (low,bot_choice) in (("حجر","مقص"),("ورق","حجر"),("مقص","ورق")): result,reward="🏆 فزت!",12
            else: result,reward="😄 خسرت الجولة، جرّب مرة أخرى.",2
            balance=self._game_award(sender_name,reward); suffix="♾️" if balance is None else str(balance)
            self.send_room_text(room,f"✂️ @{sender_name}: {low}\n🤖 البوت: {bot_choice}\n{result}\n🎁 +{reward} نقطة\n💰 الرصيد: {suffix}"); return True

        if low in ("تخمين","ابدأ تخمين","تخمين 1-10","guess"):
            ok,wait=self._game_ready(sender_name,room,3.0)
            if not ok: self.send_room_text(room,f"⏳ @{sender_name} انتظر {wait} ثوانٍ."); return True
            with self.game_lock: self.guess_games[key]={"number":random.randint(1,10),"attempts":0,"started":time.time()}
            self.send_room_text(room,f"🎯 @{sender_name} بدأت لعبة التخمين!\n🔢 اختر رقماً من 1 إلى 10.\n🎲 لديك 3 محاولات — اكتب الرقم فقط."); return True

        if low in ("سؤال","سوال","quiz","مسابقة"):
            ok,wait=self._game_ready(sender_name,room,5.0)
            if not ok: self.send_room_text(room,f"⏳ @{sender_name} انتظر {wait} ثوانٍ."); return True
            q,a=random.choice((("ما هو أكبر كوكب في المجموعة الشمسية؟","المشتري"),("كم عدد أيام الأسبوع؟","7"),("ما عاصمة اليمن؟","صنعاء"),("ما لون الموز غالباً عند النضج؟","أصفر")))
            with self.game_lock: self.guess_games[(str(room or "").casefold(),"__quiz__")]={"answer":a,"expires":time.time()+30}
            self.send_room_text(room,f"🧠 سؤال سريع!\n❓ {q}\n💬 أول شخص يكتب الإجابة الصحيحة يربح 15 نقطة."); return True

        with self.game_lock: quiz=self.guess_games.get((str(room or "").casefold(),"__quiz__"))
        if quiz and time.time()<=quiz.get("expires",0) and low==str(quiz.get("answer","")).casefold():
            with self.game_lock: self.guess_games.pop((str(room or "").casefold(),"__quiz__"),None)
            balance=self._game_award(sender_name,15); suffix="♾️" if balance is None else str(balance)
            self.send_room_text(room,f"🧠 إجابة صحيحة يا @{sender_name}! 🎉\n🏆 +15 نقطة\n💰 الرصيد: {suffix}"); return True
        return False

    def _send_help(self, room=None, private_to=None, page=1):
        text=_command_help(page)
        if private_to:
            self._send_help_chunks("chat_message", text, to=private_to)
        elif room:
            self._send_help_chunks("room_message", text, room=room)

    def _handle_management_command(self, room, body, sender, is_private=False):
        """Giant-style persistent management commands. Returns True if consumed."""
        text=str(body or "").strip()
        low=text.casefold()
        def _reply(msg):
            return self.send_command_reply(room, sender, msg, is_private=is_private)
        # `اوامر` shows the organized menu only.
        if low in ("اوامر","الاوامر","help","مساعدة"):
            target = sender if is_private else None
            if target:
                self.send_private_text(target, _command_menu())
            else:
                self.send_room_text(room, _command_menu())
            return True
        m_help = re.fullmatch(r"help([1-7])", low)
        if m_help:
            page=int(m_help.group(1))
            self.help_pages[(str(room), _norm_user(sender))]=page
            self._send_help(room=room, private_to=sender if is_private else None, page=page)
            return True
        if low in ("ns","n","التالي","القائمة التالية","next"):
            key=(str(room), _norm_user(sender))
            page=int(self.help_pages.get(key,1) or 1)+1
            if page>7: page=1
            self.help_pages[key]=page
            self._send_help(room=room, private_to=sender if is_private else None, page=page)
            return True
        if low in ("نقاطي","points"):
            pts=_get_points(sender)
            _reply("♾️ نقاطك: لا محدود" if pts is None else f"💰 نقاطك: {pts}")
            return True
        if low in ("توب","top"):
            data=_points_data(); rows=[]
            for v in data.values():
                try: rows.append((int(v.get("points",0)),v.get("username", "")))
                except Exception: pass
            rows.sort(reverse=True)
            msg="🏆 المتصدرين:\n"+"\n".join(f"{i}. @{u} — {p}" for i,(p,u) in enumerate(rows[:10],1)) if rows else "🏆 لا توجد نقاط بعد."
            if is_private: _reply(msg)
            else: self.send_room_text(room,msg)
            return True
        if low in ("المسترات", "masters"):
            masters=_master_list()
            names=[BOT_MASTER] + [x for x in masters if _norm_user(x)!=_norm_user(BOT_MASTER)]
            msg="👑 الماسترز:\n"+"\n".join(f"{i}. @{u}" for i,u in enumerate(names,1)) if names and any(names) else "👑 لا يوجد ماستر مسجل."
            if is_private: _reply(msg)
            else: self.send_room_text(room,msg)
            return True
        if not _is_master_name(sender):
            return False
        # Persistent monitored accounts. These commands are master-only.
        m_monitor = re.match(r"^(?:راقب|راقبة|monitor)@\s*(@?[A-Za-z0-9_.-]+)$", text, re.I)
        if m_monitor:
            target=m_monitor.group(1).lstrip("@").strip()
            added=self._monitor_add(target)
            _reply(f"{'✅ تمت إضافة' if added else 'ℹ️ الحساب مراقَب بالفعل'} @{target} إلى المراقبة.\n📌 ستصلك رسالة خاصة عند ورود أي حدث للحساب: دخول، خروج، طرد، حظر، رتبة، مشرف، ونر، أو حدث إداري.")
            return True
        m_unmonitor = re.match(r"^(?:إلغاء مراقبة|الغاء مراقبة|unmonitor)@\s*(@?[A-Za-z0-9_.-]+)$", text, re.I)
        if m_unmonitor:
            target=m_unmonitor.group(1).lstrip("@").strip()
            removed=self._monitor_remove(target)
            _reply(f"{'✅ تم إلغاء مراقبة' if removed else 'ℹ️ الحساب غير موجود في المراقبة'} @{target}.")
            return True
        if low in ("المراقبة", "المراقبين", "المراقبون", "monitors", "monitor list"):
            with self._monitor_lock:
                names=list(self.monitored_users.values())
            msg="👁️ الحسابات تحت المراقبة:\n" + ("\n".join(f"{i}. @{u}" for i,u in enumerate(sorted(names, key=_norm_user),1)) if names else "لا توجد حسابات مراقبة حالياً.")
            _reply(msg)
            return True
        # Master commands are accepted from both private chat and rooms.
        # Room moderation acts on the room where the command was received.
        # Confirmations and diagnostics are sent privately to the master.
        # Fresh room discovery / room membership commands.
        if low in ("دخول الكل", "دخول كل الغرف", "ادخل الكل", "ادخل كل الغرف", "join all", "enter all"):
            try:
                rooms, joined = self.join_all_rooms()
                if rooms:
                    _reply(f"✅ تم البحث عن الغرف ودخول {joined} غرفة من أصل {len(rooms)} غرفة مكتشفة.")
                else:
                    _reply("⚠️ لم تصل قائمة الغرف من الخادم. حاول الأمر مرة أخرى بعد ثوانٍ.")
            except Exception as e:
                _reply(f"❌ تعذر البحث عن الغرف: {e}")
            return True
        if low in ("غرفي", "my rooms", "rooms"):
            rooms=sorted(r for r in self.known_rooms if str(r).strip())
            msg="🏠 الغرف التي يتواجد بها البوت:\n" + ("\n".join(f"{i}. {r}" for i,r in enumerate(rooms,1)) if rooms else "لا توجد غرف مسجلة حالياً.")
            _reply(msg)
            return True
        m_loc=re.match(r"^\.s\s+(.+)$", text.strip(), re.I)
        if m_loc:
            target=m_loc.group(1).strip().lstrip("@")
            found=[]
            for r, users in self.room_users.items():
                if any(_norm_user(u)==_norm_user(target) for u in users):
                    found.append(r)
            if found:
                _reply("📍 @%s موجود في:\n%s" % (target, "\n".join(f"{i}. {r}" for i,r in enumerate(sorted(set(found)),1))))
            else:
                _reply(f"❌ لم أجد @{target} في الغرف التي يتابعها البوت حالياً.")
            return True
        # Add/remove master. Only the owner from BOT_MASTER may alter master list.
        if low.startswith("mas@"):
            if _norm_user(sender) != _norm_user(BOT_MASTER):
                _reply("🚫 إضافة الماسترز متاحة لصاحب البوت فقط."); return True
            target=text[4:].strip().lstrip("@");
            if not target: _reply("❌ الصيغة: mas@اسم المستخدم"); return True
            masters=_master_list()
            if not any(_norm_user(x)==_norm_user(target) for x in masters): masters.append(target); _save_local_json(MASTERS_FILE,masters)
            _reply(f"✅ تم إضافة @{target} كماستر متحكم بالبوت."); return True
        if low.startswith("umas@") or low.startswith("umas "):
            if _norm_user(sender) != _norm_user(BOT_MASTER):
                _reply("🚫 إزالة الماسترز متاحة لصاحب البوت فقط."); return True
            target=text[5:].strip().lstrip("@"); masters=[x for x in _master_list() if _norm_user(x)!=_norm_user(target)]; _save_local_json(MASTERS_FILE,masters)
            _reply(f"✅ تم إزالة @{target} من الماسترز."); return True
        if low.startswith("sb@"):
            if not _is_master_name(sender):
                _reply("🚫 أمر النقاط للماستر فقط."); return True
            m=re.match(r"^sb@([^@]+)@(-?\d+)$",text,re.I)
            if not m: _reply("❌ الصيغة: sb@اسم المستخدم@عدد النقاط"); return True
            target,amount=m.group(1).strip(),int(m.group(2)); new=_add_points(target,amount)
            action = "تحويل" if amount >= 0 else "خصم"
            _reply(f"✅ تم {action} نقاط @{target} بمقدار {abs(amount)}. الرصيد: {new}")
            if _norm_user(target) != _norm_user(sender):
                self.send_private_text(target, f"💰 إشعار النقاط: تم {action} {abs(amount)} نقطة لحسابك بواسطة @{sender}. رصيدك الحالي: {new}")
            return True
        if low.startswith("s@"):
            target=text[2:].strip().lstrip("@");
            if not target: _reply("❌ الصيغة: s@اسم المستخدم"); return True
            data=_verified_data(); data[_norm_user(target)]={"username":target,"verified_by":sender,"created_at":int(time.time())}; _save_local_json(VERIFIED_FILE,data)
            _reply(f"✅ تم توثيق @{target} لاستخدام البوت.")
            if _norm_user(target) != _norm_user(sender):
                self.send_private_text(target, f"✅ تم توثيق حسابك لاستخدام البوت بواسطة @{sender}.")
            return True
        if low.startswith("ازالة توثيق@") or low.startswith("إزالة توثيق@") or low.startswith("uns@"): 
            prefix="uns@" if low.startswith("uns@") else text.split("@",1)[0]+"@"
            target=text[len(prefix):].strip().lstrip("@"); data=_verified_data(); data.pop(_norm_user(target),None); _save_local_json(VERIFIED_FILE,data)
            _reply(f"✅ تم إزالة توثيق @{target}."); return True
        if low.startswith("vip@"):
            target=text[4:].strip().lstrip("@");
            if not target: _reply("❌ الصيغة: Vip@اسم المستخدم"); return True
            data=_vip_data(); data[_norm_user(target)]={"username":target,"granted_by":sender,"created_at":int(time.time())}; _save_local_json(VIP_FILE,data)
            _reply(f"✅ تم توثيق VIP @{target}."); return True
        if low.startswith("unvip@") or low.startswith("un vip@"):
            target=text[text.casefold().find("vip@")+4:].strip().lstrip("@"); data=_vip_data(); data.pop(_norm_user(target),None); _save_local_json(VIP_FILE,data)
            _reply(f"✅ تم إزالة VIP @{target}."); return True
        # Room/admin commands accepted in both room and private master chat.
        m=re.match(r"^(k@|kick\s+)(@?[^\s]+)$", text, re.I)
        if m:
            target=m.group(2).lstrip("@").strip()
            if not room:
                _reply("❌ لا توجد غرفة لتنفيذ الطرد فيها."); return True
            ok, detail = self.send_admin(room,target,"kick")
            if ok:
                _reply(f"✅ تم طرد @{target} فعليًا من الغرفة {room}.")
            else:
                _reply(f"❌ فشل تنفيذ الطرد الفعلي: {detail}")
                self.send_private_text(BOT_MASTER, f"🛠️ تشخيص الطرد\nالأمر: k@{target}\nالغرفة: {room}\nالنتيجة: {detail}")
            return True
        m=re.match(r"^(b@|ban\s+)(@?[^\s]+)$", text, re.I)
        if m:
            target=m.group(2).lstrip("@").strip()
            if not room:
                _reply("❌ لا توجد غرفة لتنفيذ الحظر فيها."); return True
            ok, detail = self.send_admin(room,target,"ban")
            if ok:
                _reply(f"✅ تم حظر @{target} فعليًا من الغرفة {room}.")
            else:
                _reply(f"❌ فشل تنفيذ الحظر الفعلي: {detail}")
                self.send_private_text(BOT_MASTER, f"🛠️ تشخيص الحظر\nالأمر: b@{target}\nالغرفة: {room}\nالنتيجة: {detail}")
            return True
        m=re.match(r"^(u@|ub@|unban\s+)(@?[^\s]+)$", text, re.I)
        if m:
            target=m.group(2).lstrip("@").strip()
            if not room:
                _reply("❌ لا توجد غرفة لتنفيذ فك الحظر فيها."); return True
            ok, detail = self.send_admin(room,target,"unban")
            if ok:
                _reply(f"✅ تم فك الحظر فعليًا عن @{target} في الغرفة {room}.")
            else:
                _reply(f"❌ فشل فك الحظر الفعلي: {detail}")
                self.send_private_text(BOT_MASTER, f"🛠️ تشخيص فك الحظر\nالأمر: ub@{target}\nالغرفة: {room}\nالنتيجة: {detail}")
            return True
        m=re.match(r"^(a@|admin\s+)(@?[^\s]+)$", text, re.I)
        if m:
            target=m.group(2).lstrip("@").strip()
            if not room:
                _reply("❌ لا توجد غرفة لتعيين المشرف فيها."); return True
            self.send_admin(room,target,"admin")
            _reply(f"✅ تم تعيين @{target} مشرفًا في الغرفة {room}."); return True
        m=re.match(r"^(o@|owner\s+)(@?[^\s]+)$", text, re.I)
        if m:
            target=m.group(2).lstrip("@").strip()
            if not room:
                _reply("❌ لا توجد غرفة لتعيين المالك فيها."); return True
            self.send_admin(room,target,"owner")
            _reply(f"✅ تم تعيين @{target} مالكًا في الغرفة {room}."); return True
        if low.startswith(("دخول ","join ","ادخل ","enter ")):
            parts=text.split(None,1); target=parts[1].strip() if len(parts)==2 else ""
            if not target:
                _reply("❌ الصيغة: دخول اسم_الغرفة"); return True
            self.join_room(target)
            _reply(f"✅ دخلت الغرفة: {target} | الغرف الحالية: {len(self.known_rooms)}"); return True
        if low in ("خروج","leave","exit") or low.startswith(("خروج ","leave ","exit ")):
            parts=text.split(None,1); target=parts[1].strip() if len(parts)==2 else ""
            if target:
                ok=self.leave_room(target)
                _reply(f"{'✅ خرجت من الغرفة' if ok else '❌ تعذر الخروج'}: {target}")
            else:
                rooms=self.leave_all_rooms()
                _reply(f"✅ خرجت من جميع الغرف. العدد: {len(rooms)}")
            return True
        if low.startswith("invmsg") or low.startswith("رسالةدعوة"):
            parts=text.split(None,1); template=parts[1].strip() if len(parts)==2 else "{sender} يدعوك للغرفة {room}"
            self.invite_message_template=template
            _reply(f"✅ تم تغيير نص الدعوة إلى: {template}"); return True
        if low == "inv" or low.startswith("inv ") or low in ("دعوات","invite") or low.startswith(("دعوات ","invite ")):
            parts=text.split(None,1); target_room=parts[1].strip() if len(parts)==2 else room
            if not target_room:
                _reply("❌ استخدم: inv اسم_الغرفة"); return True
            self.request_occupants(target_room)
            _reply(f"📨 بدأت دعوات المستخدمين في: {target_room}"); return True
        if low.startswith("say ") or low.startswith("قل "):
            parts=text.split(None,1); msg=parts[1].strip() if len(parts)==2 else ""
            if room and msg: self.send_room_text(room,msg)
            else: _reply("❌ استخدم say نص داخل غرفة.")
            return True
        # Auto replies: +sr@وصف@الرد / Sr@on / Sr@off
        m_sr = re.match(r"^\+sr@([^@]+)@(.+)$", text.strip(), re.I)
        if m_sr and _is_master_name(sender):
            trigger, reply = m_sr.group(1).strip(), m_sr.group(2).strip()
            if trigger and reply:
                self.auto_replies[trigger.casefold()] = {"trigger": trigger, "reply": reply}
                self.auto_replies_enabled = True
                self._save_social_features()
                _reply(f"✅ تمت إضافة الرد التلقائي\n📌 الوصف: {trigger}\n💬 الرد: {reply}")
            return True
        if re.match(r"^sr@(?:on|off)$", text.strip(), re.I) and _is_master_name(sender):
            self.auto_replies_enabled = text.strip().lower() == "sr@on"
            self._save_social_features()
            _reply("✅ تم تشغيل الردود التلقائية." if self.auto_replies_enabled else "⛔ تم إيقاف الردود التلقائية.")
            return True
        # Custom welcome: swc+@اسم@الترحيب and on/off.
        m_sw = re.match(r"^(?:\+swc|swc\+)@([^@]+)@(.+)$", text.strip(), re.I)
        if m_sw and _is_master_name(sender):
            user, welcome = m_sw.group(1).strip().lstrip("@"), m_sw.group(2).strip()
            if user and welcome:
                self.custom_welcomes[_norm_user(user)] = {"username": user, "message": welcome}
                self.custom_welcome_enabled = True
                self._save_social_features()
                _reply(f"✅ تم حفظ الترحيب المخصص لـ @{user}.\n💬 {welcome}")
            return True
        # Delete a per-user custom welcome.
        m_del_sw = re.match(r"^(?:-swc@|del\s+swc@|حذف\s+الترحيب@|حذف\s+ترحيب@)(.+)$", text.strip(), re.I)
        if m_del_sw and _is_master_name(sender):
            user=m_del_sw.group(1).strip().lstrip("@")
            if not user:
                _reply("❌ الصيغة: -swc@اسم الشخص")
                return True
            key=_norm_user(user)
            existed=key in self.custom_welcomes
            self.custom_welcomes.pop(key, None)
            self._save_social_features()
            _reply(f"{'✅ تم حذف الترحيب المخصص لـ @'+user+'.' if existed else '⚠️ لا يوجد ترحيب مخصص محفوظ لـ @'+user+'.'}")
            return True
        if re.match(r"^swc@(?:on|off)$", text.strip(), re.I) and _is_master_name(sender):
            self.custom_welcome_enabled = text.strip().lower() == "swc@on"
            self._save_social_features()
            _reply("✅ تم تشغيل الترحيب المخصص." if self.custom_welcome_enabled else "⛔ تم إيقاف الترحيب المخصص.")
            return True
        # Publishing: master says `انشر` or `انشر@description`, then sends an image.
        # Accept both forms strictly and preserve the description exactly.
        m_publish = re.match(r"^انشر(?:@(.+))?$", text, re.I)
        if m_publish:
            desc = (m_publish.group(1) or "").strip()
            # The image may be sent later in a room or in private chat.
            # Key the pending publish by sender, not by the command room, so
            # sending the image from another room still completes the publish.
            source_room = str(room or self.room or "")
            self.publish_pending[_norm_user(sender)]={"description":desc,"source_room":source_room,"created_at":time.time()}
            publish_wait_message = _message_template(
                "publish", "waiting",
                "🖼️ تم استلام أمر النشر. أرسل الصورة الآن خلال 10 دقائق في الروم أو الخاص، وسيتم نشرها في جميع الغرف.",
                sender=sender, room=source_room, description=desc
            )
            # Reply to the publish command IN THE SAME ROOM, not by private message.
            # If the command came from private chat and no room is available,
            # do not send this waiting message privately.
            if source_room:
                self.send_room_text(source_room, publish_wait_message)
            return True
        return False

    def _handle_publish_media(self, room, sender, media_url, description="", private_to=None):
        if not media_url: return False
        # Accept the pending image from ANY room (or private chat).
        key=_norm_user(sender); pending=self.publish_pending.get(key)
        if not pending: return False
        if time.time()-pending.get("created_at",0)>600:
            pending_room = str(pending.get("source_room") or room or self.room or "")
            self.publish_pending.pop(key,None)
            if pending_room:
                if private_to:
                    self.send_private_text(private_to, "⌛ انتهت مهلة النشر، أرسل أمر انشر من جديد.")
                else:
                    self.send_room_text(pending_room, "⌛ انتهت مهلة النشر، أرسل أمر انشر من جديد.")
            return True
        desc=pending.get("description",description or "")
        source_room=str(pending.get("source_room") or room or "")
        self.publish_pending.pop(key,None)
        rooms=list(self.known_rooms) or ([self.room] if self.room else [])
        # In rooms, the successful publish message contains ONLY the reaction
        # controls. The publish status/result is sent privately to the master.
        base_code=uuid.uuid4().hex[:4]
        reaction_codes={
            "like": base_code,
            "love": uuid.uuid4().hex[:4],
            "dislike": uuid.uuid4().hex[:4],
            "comment": uuid.uuid4().hex[:4],
            "report": uuid.uuid4().hex[:4],
        }
        for kind,code in reaction_codes.items():
            self.reaction_targets[code]={"publisher": sender, "kind": kind, "description": desc or "منشور صورة", "created_at": time.time()}
        caption=_message_template(
            "publish", "broadcast",
            "🖼️ {description}\n👤 {publisher}\n━━━━━━━━━━━━━\n👍 lk@{like}\n❤️ lv@{love}\n👎 dl@{dislike}\n💬 cm@{comment} msg\n🚨 report@{report} msg",
            publisher=sender, description=desc or "منشور صورة",
            source_label=source_room, code=base_code,
            like=reaction_codes["like"], love=reaction_codes["love"], dislike=reaction_codes["dislike"],
            comment=reaction_codes["comment"], report=reaction_codes["report"], room=source_room
        )
        ok=0
        errors=[]
        for target in rooms:
            try:
                self.send_room_media(target,media_url,"image")
                self.send_room_text(target,caption)
                ok+=1
            except Exception as e:
                errors.append((target,str(e)))
                self.log("[PUBLISH] failed",target,repr(e))
        # Never announce a successful publish in the room; tell the master in PM.
        self.send_command_reply(source_room, sender, f"✅ تم نشر الصورة في {ok} غرفة." + (f"\n❌ أخطاء: {len(errors)}" if errors else ""), is_private=bool(private_to))
        if errors:
            self.send_command_reply(source_room, sender, "❌ أخطاء النشر: " + " | ".join(f"{r}: {e[:60]}" for r,e in errors), is_private=bool(private_to))
        return True

    def handle_room_event(self, result):
        event = result.get("room_event") or {}
        event_type = str(event.get(1, ""))
        frm = str(event.get(2, ""))
        to = str(event.get(3, ""))
        body = str(event.get(6, ""))
        room = str(event.get(13, self.room))
        if room and room != BOT_MASTER:
            self.known_rooms.add(room)
        event_id = str(event.get(41, ""))
        # Carry ResultMessage identifiers into the nested event for the monitor.
        if isinstance(event, dict):
            event["_result_uid"] = str(result.get("uid", "") or "")
            event["_handler_id"] = str(result.get("handler_id", "") or "")
            event["_result_value"] = str(result.get("value", "") or "")
        username = str(event.get(22, "") or "").strip()
        role = str(event.get(8, "") or "").strip().lower()
        count = str(event.get(23, "") or "").strip()
        reconnected = str(event.get(24, "") or "").strip()
        # Do not log room message contents, usernames, room names, or media events.

        # Monitor the watched account in EVERY room.  Important: Giant/Talkin
        # RoomEvent messages can describe the action in `body` while `frm`
        # contains the account that performed it.  Therefore we must check
        # username + frm + to, not just one of them.
        monitor_candidates = [x for x in (username, frm, to) if str(x or "").strip()]
        watched_candidates = []
        with self._monitor_lock:
            watched_keys = set(self.monitored_users.keys())
        for candidate in monitor_candidates:
            if _norm_user(candidate) in watched_keys:
                watched_candidates.append(candidate)

        # Some system events have no username field; the Arabic system text
        # itself can contain the actor/target name.
        if body:
            for key in watched_keys:
                if key and key.casefold() in body.casefold() and key not in {
                    _norm_user(x) for x in watched_candidates
                }:
                    watched_candidates.append(self.monitored_users.get(key, key))

        if watched_candidates:
            # Report once per watched account mentioned in this RoomEvent.
            seen = set()
            for monitored_target in watched_candidates:
                mkey = _norm_user(monitored_target)
                if mkey in seen:
                    continue
                seen.add(mkey)
                self._monitor_report(
                    event, event_type, monitored_target, room, event_id,
                    frm, to, role, body=body
                )

        # Keep the live membership state in sync.  The APK itself uses these
        # exact event names and RoomEvent fields.
        if event_type == "user_joined" and username:
            self.room_users[room][username] = role or "none"
            self.last_joined_room = room
            # Welcome the master using the exact configured BOT_MASTER account.
            if _norm_user(username) == _norm_user(BOT_MASTER):
                self.send_room_text(room, f"👑 لقد أتاكم الزعيم\n👤 {username}\n🏠 الغرفة: {room}")
            elif self.custom_welcome_enabled:
                cw = self.custom_welcomes.get(_norm_user(username))
                if isinstance(cw, dict) and cw.get("message"):
                    self.send_room_text(room, str(cw["message"]).replace("{username}", username).replace("{room}", room))
        elif event_type == "user_left" and username:
            self.room_users[room].pop(username, None)
        elif event_type in ("you_joined", "you_rejoined"):
            self.last_joined_room = room
        elif event_type in ("room_full_rejoin", "room_unauthorized_rejoin", "room_wrong_password_rejoin", "room_needs_captcha_rejoin", "room_needs_password_rejoin", "room_membership_required_rejoin"):
            # IMPORTANT: do not immediately send room_join here.  These events
            # can be emitted repeatedly by the server when a room rejects a
            # join.  The old code answered every event with another room_join,
            # creating the visible leave/join loop.  A real reconnect is left
            # to run_once(), while a rejoin is attempted at most once after a
            # long cooldown and never recursively from this event handler.
            self.log("[ROOM] server requested rejoin; delayed reconnect")

        if ACK_ROOM_EVENTS and result.get("uid"):
            try:
                self.ack(result["uid"])
            except Exception as e:
                self.log("[ACK] failed:", e)

        # A photo sent in a room arrives as RoomEvent type=image with its
        # public URL in field 7 (url). If a master previously used `انشر`,
        # publish that image even when it was sent from a different room.
        if event_type == "image":
            media_url = str(event.get(7, "") or "").strip()
            if frm and frm != BOT_ID and media_url:
                if self._handle_publish_media(room, frm, media_url):
                    return
            return

        if event_type != "text" or not body:
            return
        if frm == BOT_ID:
            return

        # Reactions/comments/reports: notify the original publisher privately.
        reaction=re.match(r"^(lk|lv|dl|cm|report)@([A-Za-z0-9]{4})(?:\s+(.*))?$", body.strip(), re.I)
        if reaction:
            action,code,extra=reaction.group(1).lower(),reaction.group(2).lower(),(reaction.group(3) or "").strip()
            info=self.reaction_targets.get(code)
            if info and time.time()-float(info.get("created_at",0)) <= 86400:
                publisher=str(info.get("publisher") or "").strip()
                labels={"lk":"👍 إعجاب","lv":"❤️ حب","dl":"👎 عدم إعجاب","cm":"💬 تعليق","report":"🚨 بلاغ"}
                source_desc = str(info.get("description") or info.get("title") or "").strip()
                notice=f"{labels.get(action,action)}\n👤 المتفاعل: {frm}\n📌 الناشر: {publisher}"
                if source_desc: notice += f"\n📝 وصف المنشور: {source_desc}"
                if extra: notice += f"\n💬 رسالة التفاعل: {extra}"
                self.send_private_text(publisher,notice)
                return

        # Music/gifts require verification; masters are always allowed.
        is_verified = _norm_user(frm) in _verified_data() or _is_master_name(frm)
        if re.match(r"^sa@[^@]+@.+$", body.strip(), re.I):
            if not is_verified:
                self.send_private_text(frm, f"🔒 @{frm} غير موثّق لاستخدام الهدايا.")
                return
            if self.handle_gift_command(room, body, frm):
                return
        if body.strip().lower().startswith(".sa "):
            if not is_verified:
                self.send_private_text(frm, f"🔒 @{frm} غير موثّق لاستخدام الأغاني.")
                return
            if self.handle_music_command(room, body, frm):
                return

        # Keep a small per-room message history for diagnostics.
        self.last_messages[room].append((frm, body, event_id))
        self.last_messages[room] = self.last_messages[room][-50:]

        # Exact-match automatic replies.
        if self.auto_replies_enabled:
            ar = self.auto_replies.get(body.strip().casefold())
            if isinstance(ar, dict) and ar.get("reply"):
                reply = str(ar["reply"]).replace("{username}", frm).replace("{room}", room)
                self.send_room_text(room, reply)
                return

        if self._handle_management_command(room, body, frm):
            return

        if self.handle_game_command(room, body, frm):
            return

        # Optional automatic word filter. It uses the same room ban operation
        # already implemented for manual `b@` commands. Enable explicitly in .env.
        if AUTO_BAN_WORDS and self.banned_words:
            low = body.casefold()
            hit = next((w for w in self.banned_words if w.casefold() in low), None)
            if hit:
                try:
                    self.send_admin(room, frm, "ban")
                    self.log("[WORD-FILTER] banned", frm, "word=", hit)
                except Exception as e:
                    self.log("[WORD-FILTER] failed:", repr(e))
                return

        if body.lower().strip() in ("!help", "مساعدة") and AUTO_HELP:
            self.send_room_text(room, "أوامر البوت: k@ اسم، b@ اسم، a@ اسم، o@ اسم، دخول اسم_الغرفة، خروج [اسم_الغرفة]، inv، invmsg نص الدعوة لدعوة مستخدمي الغرفة")

    def on_message(self, ws, message):
        try:
            if isinstance(message, str):
                self.log("[WS] unexpected text frame received")
                return
            result = decode_result_message(message)
            if result.get("rooms"):
                self._remember_room_list(result.get("rooms"))
            if "room_event" in result:
                self.handle_room_event(result)
                try:
                    ev_text = repr(result.get("room_event"))
                    with self._monitor_lock:
                        watched = list(self.monitored_users.values())
                    if MONITOR_DEBUG and any(_norm_user(u) and _norm_user(u) in ev_text.casefold() for u in watched):
                        self.log("[MONITOR DEBUG][ROOM_EVENT]", ev_text[:4000])
                        self.log("[MONITOR DEBUG][RESULT]", {k: result.get(k) for k in ("handler_id", "type", "uid", "value", "int_value")})
                except Exception as e:
                    self.log("[MONITOR DEBUG] room_event inspect failed:", repr(e))
            if result.get("users") or result.get("room_admin"):
                self.process_occupants_for_invite(result)
            if result.get("stream_event"):
                self.log("[STREAM]", result["stream_event"])
            if result.get("room_admin"):
                ra = result["room_admin"]
                self.log("[ROOM_ADMIN]", ra)
                # Last-resort monitor diagnostics: some moderation actions are
                # delivered as RoomAdmin rather than RoomEvent. Log the exact
                # decoded payload when a watched username is present.
                try:
                    ra_text = repr(ra)
                    with self._monitor_lock:
                        watched = list(self.monitored_users.values())
                    if MONITOR_DEBUG and any(_norm_user(u) and _norm_user(u) in ra_text.casefold() for u in watched):
                        self.log("[MONITOR DEBUG][ROOM_ADMIN]", ra_text[:4000])
                        self.log("[MONITOR DEBUG][RESULT]", {k: result.get(k) for k in ("handler_id", "type", "uid", "value", "int_value")})
                except Exception as e:
                    self.log("[MONITOR DEBUG] room_admin inspect failed:", repr(e))
            if result.get("chat_message"):
                # Private master commands are also accepted as ChatMessage frames.
                cm = result["chat_message"]
                try:
                    frm = str(cm.get(3, "") or "").strip()
                    body = str(cm.get(5, "") or "").strip()
                    media_url = str(cm.get(6, "") or "").strip()
                    if frm and media_url and self._handle_publish_media(self.room, frm, media_url, private_to=frm):
                        return
                    if _is_master_name(frm) and body:
                        if self._handle_management_command(self.room, body, frm, is_private=True):
                            return
                    if body.strip().lower().startswith(".sa "):
                        if self.handle_music_command(self.room, body, frm, private_to=frm):
                            return
                    if re.match(r"^sa@[^@]+@.+$", body.strip(), re.I):
                        if self.handle_gift_command(self.room, body, frm, private_to=frm):
                            return
                    # All master/private management commands are handled once above.
                    # This prevents private commands from being duplicated or answered in a room.
                except Exception as e:
                    self.log("[CHAT_MESSAGE] private command handling failed:", repr(e))
        except Exception as e:
            self.last_error = str(e)
            self.log("[WS] decode error:", repr(e))
            if DEBUG and isinstance(message, (bytes, bytearray)):
                self.log("[WS] raw:", bytes(message).hex()[:1000])

    def on_open(self, ws):
        # Room join is deliberately performed once by bootstrap_after_connect(),
        # after the server handshake/bootstrap frame. Joining here as well can
        # cause duplicate join/leave events on some server sessions.
        self.log("[WS] connected:", self.websocket_url())

    def on_error(self, ws, error):
        self.last_error = str(error)
        self.log("[WS] error:", error)

    def on_close(self, ws, code, msg):
        self.log("[WS] closed:", code, msg)

    def bootstrap_after_connect(self):
        # Restore the normal bot status after every connection/reconnect.
        self._set_default_bot_status()
        """Wait briefly for the server bootstrap, then request the room lists."""
        deadline = time.time() + float(os.getenv("BOOTSTRAP_WAIT", "6"))
        got_server_frame = False

        while time.time() < deadline:
            remaining = max(0.2, deadline - time.time())
            old_timeout = getattr(self.ws, "timeout", 20)
            try:
                self.ws.sock.settimeout(min(remaining, 1.0))
                kind, message = self.ws.recv()
            except socket.timeout:
                continue
            finally:
                try:
                    self.ws.sock.settimeout(old_timeout)
                except Exception:
                    pass

            if kind == "ping":
                continue
            if kind == "pong":
                continue
            if kind == "close":
                raise ConnectionError(f"WebSocket closed during server bootstrap: {message}")
            if kind != "binary":
                continue

            got_server_frame = True
            self.on_message(self.ws, message)

            # First valid server result is the synchronization point used
            # before room-list loading.
            try:
                # Newer TalkinChat builds expose this request name directly.
                self.send_query(encode_query("load_list_new"))
                self.log("[BOOTSTRAP] sent load_list_new")
            except Exception as e:
                self.log("[BOOTSTRAP] load_list_new failed:", repr(e))
            break

        if not got_server_frame:
            # Do not hang forever if a build/server does not send an initial
            # unsolicited frame. Still request the list exactly once.
            try:
                self.send_query(encode_query("load_list_new"))
                self.log("[BOOTSTRAP] no unsolicited frame; sent load_list_new")
            except Exception as e:
                self.log("[BOOTSTRAP] list request failed:", repr(e))

        # Give the server a short window to return list data before joining.
        list_deadline = time.time() + float(os.getenv("LIST_BOOTSTRAP_WAIT", "2"))
        while time.time() < list_deadline:
            remaining = min(0.8, max(0.1, list_deadline - time.time()))
            old_timeout = getattr(self.ws, "timeout", 20)
            try:
                self.ws.sock.settimeout(remaining)
                kind, message = self.ws.recv()
            except socket.timeout:
                continue
            finally:
                try:
                    self.ws.sock.settimeout(old_timeout)
                except Exception:
                    pass
            if kind == "binary":
                self.on_message(self.ws, message)
            elif kind == "ping":
                continue
            elif kind == "close":
                raise ConnectionError(f"WebSocket closed during room-list bootstrap: {message}")

        # Keep every room selected by the master. A reconnect restores the
        # existing room set once; room-event handlers never leave/rejoin in a
        # loop, which avoids the visible leave/join cycle.
        rooms_to_restore = {str(r).strip() for r in self.known_rooms if str(r).strip()}
        if self.room:
            rooms_to_restore.add(str(self.room).strip())
        for room in sorted(rooms_to_restore):
            self.join_room(room, force=True)

    def run_once(self):
        self.authenticate()
        # Android saves AuthResult.server into SharedPreferences and then
        # Client uses that saved server for the WebSocket. Do the same:
        # authenticated server first, configured default only as fallback.
        ports = []
        # AuthResult.server is the server selected by TalkinChat for this
        # account/session. Prefer it and only use SOCKET_PORT if auth did not
        # provide a server.
        auth_port = getattr(self, "auth_server", "")
        if auth_port:
            ports.append(auth_port)
        elif DEFAULT_PORT:
            ports.append(DEFAULT_PORT)
        if not ports:
            ports = ["5335"]

        # Exact default 5.8.3 Client.smali branch: Client reads `default/m`
        # with default `n`, then calls M9/c.c(), which supplies only `b`.
        # This is also the branch that previously reached HTTP 101 on this server.
        header_lines = self.app_ws_headers()

        last_error = None
        # Client.smali constructs only chatp.net:<server>/server. The CDN entry
        # seen in the connection monitor is not used by this Talkin Client path,
        # so do not treat it as a WebSocket fallback.
        for port in ports:
            self.port = port
            for host in WS_HOSTS:
                self.ws_host = host
                for path in WS_PATHS:
                    self.ws_path = path
                    url = self.websocket_url(path)
                    self.log("[WS] trying host/port/path:", host, port, path, url)
                    try:
                        # Y9/v Client.smali does not copy the HTTP auth Session
                        # cookies into the WebSocket handshake. Keep the WS request
                        # limited to the headers actually built by the APK.
                        self.ws = RawWebSocket(
                            url,
                            list(header_lines),
                            timeout=WS_HEARTBEAT_SECONDS,
                            debug=RAW_DIAGNOSTIC,
                        )
                        self.ws.connect()
                        self.log("[WS] CONNECTED:", url)
                        self.log("[WS] custom headers:", [x.split(":",1)[0] + ": <redacted>" if x.lower().startswith(("username:", "password:")) else x for x in header_lines])
                        self.bootstrap_after_connect()
                        if self._pending_reconnect_reason and BOT_MASTER:
                            reason = self._pending_reconnect_reason
                            self._pending_reconnect_reason = ""
                            self.send_private_text(BOT_MASTER, f"⚠️ انقطع الاتصال ثم عاد. السبب: {reason}")
                            self.send_private_text(BOT_MASTER, "✅ تم الدخول والعودة للغرفة بنجاح.")
                        elif not self._had_connection and BOT_MASTER:
                            self.send_private_text(BOT_MASTER, "✅ تم الدخول للغرفة والاتصال بنجاح.")
                        self._had_connection = True

                        while not self.stop_event.is_set():
                            try:
                                kind, message = self.ws.recv()
                            except socket.timeout:
                                # Keep the realtime WebSocket alive. The server may
                                # close an otherwise idle connection with code 1000.
                                # Sending a client ping prevents idle disconnects
                                # while preserving the normal reconnect path if the
                                # socket is genuinely dead.
                                try:
                                    if self.ws:
                                        self.ws.send_control(0x9, b"talkin")
                                        self.log("[WS] heartbeat ping sent")
                                except Exception as heartbeat_error:
                                    raise ConnectionError(
                                        f"WebSocket heartbeat failed: {heartbeat_error}"
                                    )
                                continue
                            if kind == "binary":
                                self.on_message(self.ws, message)
                            elif kind == "ping":
                                continue
                            elif kind == "pong":
                                continue
                            elif kind == "text":
                                self.log("[WS] unexpected text frame received")
                            elif kind == "close":
                                if isinstance(message, dict):
                                    code = message.get("code")
                                    reason = str(message.get("reason") or "").strip()
                                    if code == 1000:
                                        detail = "WebSocket closed normally (1000)"
                                    else:
                                        detail = f"WebSocket closed by server ({code})"
                                    if reason:
                                        detail += f": {reason}"
                                else:
                                    detail = f"WebSocket closed by server: {message}"
                                raise ConnectionError(detail)
                        return
                    except Exception as e:
                        last_error = e
                        self.log("[WS] host/path failed:", host, port, path, repr(e))
                        try:
                            if self.ws:
                                self.ws.close()
                        except Exception:
                            pass
                        self.ws = None
        raise last_error

    def start(self):
        print("=== Talkinchat Bot V22 - Talkin + YouTube Cookies + Giant Gift Cards ===", flush=True)
        self.asset_server = start_asset_server()
        if not BOT_ID or not BOT_PWD or not self.room:
            raise SystemExit("Set BOT_ID, BOT_PWD and GROUP_TO_JOIN in .env first.")
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception as e:
                self.last_error = str(e)
                if self._had_connection:
                    raw_reason = " ".join(str(e).split())
                    if "code': 1000" in raw_reason or '"code": 1000' in raw_reason:
                        raw_reason = "الخادم أغلق WebSocket إغلاقًا طبيعيًا (1000)، وسيتم إعادة الاتصال تلقائيًا"
                    self._pending_reconnect_reason = raw_reason[:1000]
                print("[BOT] error:", repr(e), flush=True)
            if not self.stop_event.is_set():
                # Short backoff: the room list is preserved and restored once
                # after the new authenticated WebSocket is established.
                reconnect_delay = float(os.getenv("RECONNECT_DELAY_SECONDS", "3"))
                print(f"[BOT] reconnecting in {reconnect_delay:g}s...", flush=True)
                time.sleep(max(1.0, reconnect_delay))


if __name__ == "__main__":
    TalkinBot().start()
