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
import re
import queue
import mimetypes
from urllib.parse import urlparse, unquote
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from collections import defaultdict
from pathlib import Path

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

# Giant Chat gift costs/labels; images remain the local Giant assets.
GIFT_COSTS = {"1":10,"2":20,"3":30,"4":50,"5":80,"6":150,"7":200,"8":500,"9":800,"10":1000,"11":1500,"12":3000,"13":5000,"14":8000}


API_BASE_URL = os.getenv("API_BASE_URL", "https://chatp.net/api?").rstrip("?") + "?"
HOST = os.getenv("HOST_HEADER", "chatp.net").strip()
WS_HOSTS = [x.strip() for x in os.getenv("WS_HOSTS", "chatp.net").split(",") if x.strip()]
DEFAULT_PORT = os.getenv("SOCKET_PORT", "5335").strip()
WS_PATHS = [x.strip() if x.strip().startswith("/") else "/" + x.strip()
            for x in os.getenv("WS_PATHS", "/server").split(",") if x.strip()]
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
                self.url = self.url or str(cfg.get("supabase_url", "")).strip()
                self.key = self.key or str(cfg.get("supabase_key", "")).strip()
                self.email = self.email or str(cfg.get("supabase_email", cfg.get("email", ""))).strip()
                self.password = self.password or str(cfg.get("supabase_password", cfg.get("password", "")))
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
        if not self.client or not self.email or not self.password:
            return False
        try:
            res = self.client.auth.sign_in_with_password({"email": self.email, "password": self.password})
            user = getattr(res, "user", None)
            self.log("[DB] Supabase auth:", "OK" if user else "FAILED")
            if user:
                self.log("[DB] authenticated Supabase user ready for native invites")
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

def _command_help(page=1):
    pages = [
        "📋 أوامر البوت (1/4)\n1. .sa اسم/رابط الأغنية\n2. sa@رقم_الهدية@اسم\n3. نقاطي\n4. توب\n5. دخول اسم_الغرفة\n6. خروج [الغرفة]\n7. inv\n8. invmsg نص الدعوة\n9. انشر\n10. انشر@الرسالة\n➡️ أرسل ns للقائمة التالية",
        "📋 أوامر البوت (2/4)\n1. انشر ثم أرسل الصورة\n2. انشر@الرسالة ثم أرسل الصورة\n3. .sa اسم الأغنية\n4. sa@رقم_الهدية@اسم\n5. نقاطي\n6. توب\n7. دخول اسم_الغرفة\n8. خروج\n9. inv\n10. say النص\n➡️ أرسل ns للقائمة التالية",
        "👑 أوامر الماستر (3/4)\n1. sb@اسم@عدد\n2. mas@اسم\n3. umas@اسم\n4. s@اسم\n5. ازالة توثيق@اسم\n6. Vip@اسم\n7. unVip@اسم\n8. المسترات\n9. دخول اسم_الغرفة\n10. خروج [الغرفة]\n➡️ أرسل ns للقائمة التالية",
        "👑 أوامر الماستر (4/4)\n1. inv\n2. inv اسم_الغرفة\n3. invmsg نص الدعوة\n4. say النص\n5. k@ اسم للطرد\n6. b@ اسم للحظر\n7. u@ اسم لإلغاء الحظر\n8. a@ اسم مشرف\n9. o@ اسم مالك\n10. اوامر\n✅ انتهت القوائم. أرسل اوامر للبدء من جديد"
    ]
    try: page=int(page)
    except Exception: page=1
    page=max(1,min(len(pages),page))
    return pages[page-1]

# ------------------------------ Bot --------------------------------------

def _shape_name(text):
    text=str(text or "")
    if arabic_reshaper and get_display and any("\u0600"<=c<="\u06ff" for c in text):
        try: return get_display(arabic_reshaper.reshape(text))
        except Exception: pass
    return text

def _gift_font(text,size):
    arabic=any("\u0600"<=c<="\u06ff" for c in str(text))
    path=BASE_DIR/"assets"/("NotoSansArabic-SemiBold.ttf" if arabic else "DejaVuSans.ttf")
    if not path.is_file(): path=BASE_DIR/"assets"/"DejaVuSans.ttf"
    return ImageFont.truetype(str(path),size)

def _fit_crop(im,size):
    im=im.convert("RGB"); tw,th=size; scale=max(tw/im.width,th/im.height); nw,nh=max(tw,int(im.width*scale)),max(th,int(im.height*scale)); im=im.resize((nw,nh),Image.LANCZOS); left=max(0,(nw-tw)//2); top=max(0,(nh-th)//2); return im.crop((left,top,left+tw,top+th))

def _draw_centered(draw,center,raw_text,size,fill,max_width):
    shaped=_shape_name(raw_text); size=int(size); font=_gift_font(raw_text,size)
    while size>16:
        box=draw.textbbox((0,0),shaped,font=font,stroke_width=2)
        if box[2]-box[0]<=max_width: break
        size-=2; font=_gift_font(raw_text,size)
    box=draw.textbbox((0,0),shaped,font=font,stroke_width=3); x=center[0]-(box[2]-box[0])/2-box[0]; y=center[1]-(box[3]-box[1])/2-box[1]
    draw.text((x,y),shaped,font=font,fill=fill,stroke_width=3,stroke_fill=(0,0,0,220))

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
        self._join_lock = threading.Lock()
        self._last_join_sent = {}
        self._rejoin_attempts = defaultdict(int)
        self._last_reconnect = 0.0
        self.banned_words = set(BANNED_WORDS)
        self.db = DatabaseBridge(self.log)
        self.db.sign_in()
        self.music_last = defaultdict(float)
        self.music_current = {}
        self.music_lock = threading.Lock()
        self.publish_pending = {}
        self.help_pages = {}
        self.invite_message_template = _message_template("invite", "default", "{sender} يدعوك للغرفة {room}")

    def log(self, *args):
        if DEBUG:
            print(*args, flush=True)

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

    def _split_talkin_text(self, text: str, limit: int = 180):
        """Talkin Chat rejects/tears down oversized text frames; keep every
        outgoing text safely below the server's 200-character limit.
        Prefer line boundaries, then hard-split long lines."""
        text = str(text or "")
        if not text:
            return [""]
        chunks = []
        for block in text.split("\n"):
            block = block.strip()
            if not block:
                continue
            while len(block) > limit:
                cut = block.rfind(" ", 0, limit + 1)
                if cut < max(20, limit // 2):
                    cut = limit
                chunks.append(block[:cut].rstrip())
                block = block[cut:].lstrip()
            if block:
                chunks.append(block)
        return chunks or [""]

    def send_room_text(self, room: str, text: str):
        for chunk in self._split_talkin_text(text):
            self.send_query(encode_query("room_message", type_="text", room=room, body=chunk))
        return True

    def send_admin(self, room: str, target: str, operation: str):
        # Exact command forms observed in the APK.
        if operation == "kick":
            return self.send_query(encode_query("room_admin", type_="kick", room=room, to=target, value="none"))
        if operation == "ban":
            return self.send_query(encode_query("room_admin", type_="ban_ip", room=room, to=target, value="outcast"))
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
        """Send TalkinChat private text safely under the 200-char limit."""
        username = str(username or "").strip()
        if not username or username == BOT_ID:
            return False
        for chunk in self._split_talkin_text(text):
            self.send_query(encode_query("chat_message", type_="text", to=username, body=chunk))
        return True

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
        """Exact media shape observed in TalkinChat Android RoomActivity.

        image: action=room_message, type=image, password=<room>, url=<url>
        audio: action=room_message, type=audio, password=<room>, url=<url>,
               room=<duration seconds>
        """
        if media_type == "audio":
            return self.send_query(encode_query(
                "room_message", type_="audio", password=room,
                url=media_url, room=str(max(0, int(duration or 0)))
            ))
        return self.send_query(encode_query(
            "room_message", type_=media_type, password=room, url=media_url
        ))

    def _music_download(self,query):
        """Download audio with several YouTube clients, then Piped as fallback."""
        if yt_dlp is None:
            raise RuntimeError("yt-dlp غير مثبت")

        outdir=BASE_DIR/"generated_music"
        outdir.mkdir(parents=True,exist_ok=True)
        stamp=uuid.uuid4().hex
        out_mp3=outdir/(stamp+".mp3")
        errors=[]

        target_query=query if re.match(r"^https?://",query,re.I) else "ytsearch1:"+query

        def try_client(client, use_cookies=False):
            tmpdir=outdir/f".{stamp}_{client}_{'cookies' if use_cookies else 'nocookies'}"
            tmpdir.mkdir(parents=True,exist_ok=True)
            template=str(tmpdir/"source.%(ext)s")
            opts={
                "quiet":True,
                "no_warnings":True,
                "noplaylist":True,
                "format":"bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "outtmpl":template,
                "socket_timeout":45,
                "retries":5,
                "fragment_retries":5,
                "extractor_retries":3,
                "file_access_retries":3,
                "cachedir":False,
                "overwrites":True,
                "concurrent_fragment_downloads":1,
                "http_headers":{"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
                "extractor_args":{"youtube":{"player_client":[client]}},
            }
            if use_cookies and YOUTUBE_COOKIE_FILE:
                opts["cookiefile"]=YOUTUBE_COOKIE_FILE
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info=ydl.extract_info(target_query,download=True)
                    if info and info.get("entries"):
                        info=next((x for x in info["entries"] if x),None)
                    if not info:
                        raise RuntimeError("لم يتم العثور على الأغنية")
                candidates=[x for x in tmpdir.iterdir() if x.is_file() and x.suffix.lower() not in (".part",".ytdl",".temp") and x.stat().st_size>4096]
                if not candidates:
                    raise RuntimeError(f"يوتيوب أعاد البيانات عبر {client} لكن ملف الصوت لم يكتمل")
                source=max(candidates,key=lambda x:x.stat().st_mtime)
                duration=int(info.get("duration") or 0)
                if duration>MUSIC_MAX_SECONDS:
                    raise RuntimeError(f"الأغنية أطول من {MUSIC_MAX_SECONDS} ثانية")
                return info,source
            except Exception as exc:
                errors.append(f"yt-dlp/{client}: {type(exc).__name__}: {exc}")
                return None

        info=source=None
        attempts=[("android_vr",False),("web_embedded",False),("tv",False),("default",False)]
        if YOUTUBE_COOKIE_FILE:
            attempts.append(("default",True))
        for client,use_cookies in attempts:
            result=try_client(client,use_cookies)
            if result:
                info,source=result
                break

        # Piped fallback. This is used only when YouTube metadata works but
        # direct media download is blocked or incomplete.
        if not source:
            try:
                meta=None
                opts={"quiet":True,"no_warnings":True,"noplaylist":True,
                      "skip_download":True,
                      "extractor_args":{"youtube":{"player_client":["web_embedded"]}}}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    if re.match(r"^https?://",query,re.I):
                        meta=ydl.extract_info(query,download=False)
                    else:
                        meta=ydl.extract_info("ytsearch1:"+query,download=False)
                        if meta and meta.get("entries"):
                            meta=next((x for x in meta["entries"] if x),None)
                video_id=str((meta or {}).get("id") or "").strip()
                if video_id:
                    apis=[]
                    for x in os.getenv("PIPED_APIS","").split(","):
                        x=x.strip().rstrip("/")
                        if x: apis.append(x)
                    try:
                        r=requests.get("https://piped.video/api/v1/instances",headers={"User-Agent":"Mozilla/5.0"},timeout=15)
                        if r.ok:
                            for item in (r.json() or []):
                                api=str(item.get("api_url") or "").strip().rstrip("/")
                                if api.startswith("http"): apis.append(api)
                    except Exception as exc:
                        errors.append(f"Piped instances: {type(exc).__name__}: {exc}")
                    apis=list(dict.fromkeys(apis))[:12]
                    for api in apis:
                        try:
                            sr=requests.get(f"{api}/streams/{video_id}",headers={"User-Agent":"Mozilla/5.0"},timeout=25)
                            if not sr.ok:
                                errors.append(f"Piped {api}: HTTP {sr.status_code}"); continue
                            data=sr.json()
                            streams=sorted(data.get("audioStreams") or [],key=lambda s:float(s.get("bitrate") or 0),reverse=True)
                            for stream in streams:
                                u=str(stream.get("url") or "").strip()
                                if not u: continue
                                ext=".m4a" if "mp4" in str(stream.get("mimeType","")).lower() else ".webm"
                                candidate=outdir/f"{stamp}{ext}"
                                try:
                                    with requests.get(u,headers={"User-Agent":"Mozilla/5.0"},timeout=120,stream=True) as ar:
                                        if not ar.ok: continue
                                        with candidate.open("wb") as fh:
                                            for chunk in ar.iter_content(1024*256):
                                                if chunk: fh.write(chunk)
                                    if candidate.is_file() and candidate.stat().st_size>4096:
                                        source=candidate
                                        info={"id":video_id,
                                              "title":str(data.get("title") or (meta or {}).get("title") or query),
                                              "uploader":str((meta or {}).get("uploader") or data.get("uploader") or "YouTube"),
                                              "duration":int((meta or {}).get("duration") or data.get("duration") or 0)}
                                        break
                                except Exception as exc:
                                    errors.append(f"Piped stream: {type(exc).__name__}: {exc}")
                                try: candidate.unlink()
                                except Exception: pass
                            if source: break
                        except Exception as exc:
                            errors.append(f"Piped {api}: {type(exc).__name__}: {exc}")
            except Exception as exc:
                errors.append(f"Piped fallback: {type(exc).__name__}: {exc}")

        if not source or not source.is_file() or source.stat().st_size<=4096:
            detail=" | ".join(errors[-8:])
            raise RuntimeError("تم العثور على الأغنية لكن لم يتم تنزيل ملف الصوت."+(f" تفاصيل: {detail[:900]}" if detail else ""))

        duration=int((info or {}).get("duration") or 0)
        if duration>MUSIC_MAX_SECONDS:
            try: source.unlink()
            except Exception: pass
            raise RuntimeError(f"الأغنية أطول من {MUSIC_MAX_SECONDS} ثانية")

        if source.suffix.lower()==".mp3":
            mp3=source
        else:
            ffmpeg_bin=shutil.which("ffmpeg")
            if not ffmpeg_bin:
                raise RuntimeError("FFmpeg غير موجود داخل Railway")
            proc=subprocess.run([ffmpeg_bin,"-y","-hide_banner","-loglevel","error",
                                 "-i",str(source),"-vn","-ac","2","-ar","44100",
                                 "-codec:a","libmp3lame","-b:a","192k",str(out_mp3)],
                                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=180)
            if proc.returncode!=0 or not out_mp3.is_file() or out_mp3.stat().st_size<=4096:
                detail=" | ".join((proc.stderr or "").strip().splitlines()[-4:])
                raise RuntimeError("فشل تحويل الصوت إلى MP3: "+detail[:500])
            mp3=out_mp3
            try: source.unlink()
            except Exception: pass

        for child in outdir.glob(f".{stamp}_*"):
            if child.is_dir(): shutil.rmtree(child,ignore_errors=True)
        return info,mp3

    def handle_music_command(self,room,text,requester):
        raw=text.strip()
        if not raw.lower().startswith(".sa "): return False
        query=raw[4:].strip()
        if not query: self.send_room_text(room,"❌ اكتب: .sa اسم الأغنية"); return True
        now=time.time(); last=self.music_last.get(requester,0)
        if now-last<MUSIC_COOLDOWN: self.send_room_text(room,f"⏳ انتظر {int(MUSIC_COOLDOWN-(now-last))+1} ثانية."); return True
        self.music_last[requester]=now
        def worker():
            try:
                public_base = _public_base_url()
                if not public_base: raise RuntimeError("لا يوجد رابط عام للصوت؛ أنشئ Railway Public Domain أو ضع PUBLIC_BASE_URL")
                info,path=self._music_download(query); title=str(info.get("title") or query); artist=str(info.get("uploader") or info.get("channel") or "YouTube"); duration=int(info.get("duration") or 0); url=public_base+"/media/"+path.name
                self.send_room_text(room,f"🎵 {title}\n🎤 {artist}\n👤 الطلب: {requester}"); self.send_room_media(room,url,"audio",duration)
            except Exception as e: self.log("[MUSIC] failed:",repr(e)); self.send_room_text(room,"❌ تعذر تشغيل الأغنية: "+str(e)[:300])
        threading.Thread(target=worker,name="music-request",daemon=True).start(); self.send_room_text(room,"⏳ جاري البحث عن الأغنية وتحضير الصوت..."); return True

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

    def handle_gift_command(self, room: str, text: str, sender_name: str = ""):
        raw=text.strip(); m=re.match(r"^sa@([^@]+)@(.+)$",raw,re.I)
        if not m: return False
        gift_id=m.group(1).strip(); target=m.group(2).strip().lstrip("@"); item=GIFT_CATALOG.get(gift_id)
        if not item or not target:
            self.send_room_text(room,"❌ الصيغة: sa@رقم_الهدية@اسم_المستخدم"); return True
        try:
            sender_name = str(sender_name or BOT_ID).strip()
            # Giant Chat point costs; owner/masters have unlimited points.
            cost=int(GIFT_COSTS.get(str(gift_id),0)); charged=False
            if not _is_master_name(sender_name):
                balance=_get_points(sender_name)
                if balance < cost:
                    self.send_room_text(room,f"❌ رصيدك غير كافٍ. الهدية تحتاج {cost} نقطة، ورصيدك {balance}."); return True
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
            self.send_room_media(room, gift_url, "image")
            self.send_room_text(room, f"🎁 {item[0]} {item[1]} | 📤 {sender_name} ➜ 📥 {target} | 💰 {cost} نقطة")
        except Exception as e:
            self.log("[GIFT] failed:",repr(e)); self.send_room_text(room,"❌ تعذر تجهيز الهدية: "+str(e)[:180])
        return True

    def _send_help(self, room=None, private_to=None, page=1):
        text=_command_help(page)
        if private_to: self.send_private_text(private_to,text)
        elif room: self.send_room_text(room,text)

    def _handle_management_command(self, room, body, sender):
        """Giant-style persistent management commands. Returns True if consumed."""
        text=str(body or "").strip()
        low=text.casefold()
        # Help is available to everyone.
        if low in ("اوامر","الاوامر","help","مساعدة"):
            key=(str(room), _norm_user(sender))
            self.help_pages[key]=1
            self._send_help(room=room, private_to=sender if room == BOT_MASTER else None, page=1)
            return True
        if low in ("ns","n","التالي","القائمة التالية","next"):
            key=(str(room), _norm_user(sender))
            page=int(self.help_pages.get(key,1) or 1)+1
            if page>4: page=1
            self.help_pages[key]=page
            self._send_help(room=room, private_to=sender if room == BOT_MASTER else None, page=page)
            return True
        if low in ("نقاطي","points"):
            pts=_get_points(sender)
            self.send_private_text(sender, "♾️ نقاطك: لا محدود" if pts is None else f"💰 نقاطك: {pts}")
            return True
        if low in ("توب","top"):
            data=_points_data(); rows=[]
            for v in data.values():
                try: rows.append((int(v.get("points",0)),v.get("username", "")))
                except Exception: pass
            rows.sort(reverse=True)
            msg="🏆 المتصدرين:\n"+"\n".join(f"{i}. @{u} — {p}" for i,(p,u) in enumerate(rows[:10],1)) if rows else "🏆 لا توجد نقاط بعد."
            self.send_room_text(room,msg)
            return True
        if low in ("المسترات", "masters"):
            masters=_master_list()
            names=[BOT_MASTER] + [x for x in masters if _norm_user(x)!=_norm_user(BOT_MASTER)]
            msg="👑 الماسترز:\n"+"\n".join(f"{i}. @{u}" for i,u in enumerate(names,1)) if names and any(names) else "👑 لا يوجد ماستر مسجل."
            self.send_room_text(room,msg)
            return True
        if not _is_master_name(sender):
            return False
        # Add/remove master. Only the owner from BOT_MASTER may alter master list.
        if low.startswith("mas@"):
            if _norm_user(sender) != _norm_user(BOT_MASTER):
                self.send_private_text(sender,"🚫 إضافة الماسترز متاحة لصاحب البوت فقط."); return True
            target=text[4:].strip().lstrip("@");
            if not target: self.send_private_text(sender,"❌ الصيغة: mas@اسم المستخدم"); return True
            masters=_master_list()
            if not any(_norm_user(x)==_norm_user(target) for x in masters): masters.append(target); _save_local_json(MASTERS_FILE,masters)
            self.send_private_text(sender,f"✅ تم إضافة @{target} كماستر متحكم بالبوت."); return True
        if low.startswith("umas@") or low.startswith("umas "):
            if _norm_user(sender) != _norm_user(BOT_MASTER):
                self.send_private_text(sender,"🚫 إزالة الماسترز متاحة لصاحب البوت فقط."); return True
            target=text[5:].strip().lstrip("@"); masters=[x for x in _master_list() if _norm_user(x)!=_norm_user(target)]; _save_local_json(MASTERS_FILE,masters)
            self.send_private_text(sender,f"✅ تم إزالة @{target} من الماسترز."); return True
        if low.startswith("sb@"):
            if not _is_master_name(sender):
                self.send_private_text(sender,"🚫 أمر النقاط للماستر فقط."); return True
            m=re.match(r"^sb@([^@]+)@(-?\d+)$",text,re.I)
            if not m: self.send_private_text(sender,"❌ الصيغة: sb@اسم المستخدم@عدد النقاط"); return True
            target,amount=m.group(1).strip(),int(m.group(2)); new=_add_points(target,amount)
            self.send_private_text(sender,f"✅ تم تعديل نقاط @{target} بمقدار {amount}. الرصيد: {new}"); return True
        if low.startswith("s@"):
            target=text[2:].strip().lstrip("@");
            if not target: self.send_private_text(sender,"❌ الصيغة: s@اسم المستخدم"); return True
            data=_verified_data(); data[_norm_user(target)]={"username":target,"verified_by":sender,"created_at":int(time.time())}; _save_local_json(VERIFIED_FILE,data)
            self.send_private_text(sender,f"✅ تم توثيق @{target} لاستخدام البوت."); return True
        if low.startswith("ازالة توثيق@") or low.startswith("إزالة توثيق@") or low.startswith("uns@"): 
            prefix="uns@" if low.startswith("uns@") else text.split("@",1)[0]+"@"
            target=text[len(prefix):].strip().lstrip("@"); data=_verified_data(); data.pop(_norm_user(target),None); _save_local_json(VERIFIED_FILE,data)
            self.send_private_text(sender,f"✅ تم إزالة توثيق @{target}."); return True
        if low.startswith("vip@"):
            target=text[4:].strip().lstrip("@");
            if not target: self.send_private_text(sender,"❌ الصيغة: Vip@اسم المستخدم"); return True
            data=_vip_data(); data[_norm_user(target)]={"username":target,"granted_by":sender,"created_at":int(time.time())}; _save_local_json(VIP_FILE,data)
            self.send_private_text(sender,f"✅ تم توثيق VIP @{target}."); return True
        if low.startswith("unvip@") or low.startswith("un vip@"):
            target=text[text.casefold().find("vip@")+4:].strip().lstrip("@"); data=_vip_data(); data.pop(_norm_user(target),None); _save_local_json(VIP_FILE,data)
            self.send_private_text(sender,f"✅ تم إزالة VIP @{target}."); return True
        # Publishing: master says `انشر` or `انشر@description`, then sends an image.
        if low == "انشر" or low.startswith("انشر@"):
            desc=text[5:].strip() if low.startswith("انشر@") else ""
            # The image may be sent later in a room or in private chat.
            # Key the pending publish by sender, not by the command room, so
            # sending the image from another room still completes the publish.
            self.publish_pending[_norm_user(sender)]={"description":desc,"source_room":str(room or ""),"created_at":time.time()}
            self.send_private_text(sender,"🖼️ تم استلام أمر النشر. أرسل الصورة الآن خلال دقيقتين في الروم أو الخاص، وسيتم نشرها في جميع الغرف." + (f"\n📝 الوصف: {desc}" if desc else ""))
            return True
        return False

    def _handle_publish_media(self, room, sender, media_url, description=""):
        if not media_url: return False
        # Accept the pending image from ANY room (or private chat).
        key=_norm_user(sender); pending=self.publish_pending.get(key)
        if not pending: return False
        if time.time()-pending.get("created_at",0)>120:
            self.publish_pending.pop(key,None); self.send_private_text(sender,"⌛ انتهت مهلة النشر، أرسل أمر انشر من جديد."); return True
        desc=pending.get("description",description or "")
        source_room=str(pending.get("source_room") or room or "")
        self.publish_pending.pop(key,None)
        rooms=list(self.known_rooms) or ([self.room] if self.room else [])
        # In rooms, the successful publish message contains ONLY the reaction
        # controls. The publish status/result is sent privately to the master.
        caption=_message_template(
            "publish", "reaction_only",
            "🆔 {code}\n👍 lk@{code}\n❤️ lv@{code}\n👎 dl@{code}\n💬 cm@{code} msg\n🚨 report@{code} msg",
            publisher=sender, description=desc or "منشور صورة",
            source_label=source_room, code=uuid.uuid4().hex[:8],
            like="", love="", dislike="", comment="", report="", room=source_room
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
        self.send_private_text(sender,f"✅ تم نشر الصورة في {ok} غرفة." + (f"\n❌ أخطاء: {len(errors)}" if errors else ""))
        # Errors are also visible in the source room so the master can notice them.
        if errors and source_room:
            self.send_room_text(source_room, "❌ خطأ في النشر: " + " | ".join(f"{r}: {e[:60]}" for r,e in errors)[:170])
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
        username = str(event.get(22, "") or "").strip()
        role = str(event.get(8, "") or "").strip().lower()
        count = str(event.get(23, "") or "").strip()
        reconnected = str(event.get(24, "") or "").strip()
        # Do not log room message contents, usernames, room names, or media events.

        # Keep the live membership state in sync.  The APK itself uses these
        # exact event names and RoomEvent fields.
        if event_type == "user_joined" and username:
            self.room_users[room][username] = role or "none"
            self.last_joined_room = room
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

        # Music/gifts require verification; masters are always allowed.
        is_verified = _norm_user(frm) in _verified_data() or _is_master_name(frm)
        if re.match(r"^sa@[^@]+@.+$", body.strip(), re.I):
            if not is_verified:
                self.send_room_text(room, f"🔒 @{frm} غير موثّق لاستخدام الهدايا.")
                return
            if self.handle_gift_command(room, body, frm):
                return
        if body.strip().lower().startswith(".sa "):
            if not is_verified:
                self.send_room_text(room, f"🔒 @{frm} غير موثّق لاستخدام الأغاني.")
                return
            if self.handle_music_command(room, body, frm):
                return

        # Keep a small per-room message history for diagnostics.
        self.last_messages[room].append((frm, body, event_id))
        self.last_messages[room] = self.last_messages[room][-50:]

        if self._handle_management_command(room, body, frm):
            return

        # Master/admin commands.
        if _is_master_name(frm):
            if self._handle_management_command(room, body, frm):
                return
            parts = body.strip().split()
            if parts:
                cmd = parts[0].lower()
                target = parts[1].lstrip("@").strip() if len(parts) >= 2 else ""
                try:
                    if cmd in ("a@", "admin") and target:
                        self.send_admin(room, target, "admin")
                    elif cmd in ("o@", "owner") and target:
                        self.send_admin(room, target, "owner")
                    elif cmd in ("k@", "kick") and target:
                        self.send_admin(room, target, "kick")
                    elif cmd in ("b@", "ban") and target:
                        self.send_admin(room, target, "ban")
                    elif cmd in ("u@", "unban") and target:
                        self.send_admin(room, target, "member")
                    elif cmd in ("دخول", "join", "ادخل", "enter") and target:
                        # Master can command the bot from private chat: "دخول اسم الغرفة".
                        # Joining is done on the existing WebSocket; no reconnect is needed.
                        # Keep every previously joined room. room_join is sent
                        # for the new room without replacing the current room.
                        self.join_room(target)
                        self.send_private_text(BOT_MASTER, f"✅ دخلت الغرفة: {target} | الغرف الحالية: {len(self.known_rooms)}")
                    elif cmd in ("خروج", "leave", "exit"):
                        if target:
                            ok = self.leave_room(target)
                            self.send_private_text(BOT_MASTER, f"{'✅ خرجت من الغرفة' if ok else '❌ تعذر الخروج'}: {target}")
                        else:
                            rooms = self.leave_all_rooms()
                            self.send_private_text(BOT_MASTER, f"✅ خرجت من جميع الغرف. العدد: {len(rooms)}")
                    elif cmd in ("invmsg", "رسالةدعوة"):
                        template = body.split(None, 1)[1].strip() if len(parts) >= 2 else "{sender} يدعوك للغرفة {room}"
                        self.invite_message_template = template
                        self.send_private_text(BOT_MASTER, f"✅ تم تغيير نص الدعوة إلى: {template}")
                    elif cmd in ("inv", "دعوات", "invite"):
                        # In a room: `inv` always uses THIS room's name in the invitation.
                        # From private master chat: `inv اسم_الغرفة` targets that explicit room.
                        target_room = target if target else room
                        if target_room and target_room != BOT_MASTER:
                            self.request_occupants(target_room)
                            self.send_private_text(BOT_MASTER, f"📨 بدأت دعوات جميع الغرف النشطة. اسم الدعوة: {target_room}")
                    elif cmd in ("say", "قل") and len(parts) >= 2:
                        self.send_room_text(room, body.split(None, 1)[1])
                    elif cmd in ("help", "مساعدة") and AUTO_HELP:
                        self.send_room_text(room, "أوامر البوت: .sa اسم/رابط الأغنية، sa@رقم_الهدية@اسم، k@ اسم للطرد، b@ اسم للحظر، a@ اسم مشرف، o@ اسم مالك، دخول اسم_الغرفة، خروج [اسم_الغرفة]، inv، invmsg نص الدعوة، say النص")
                    else:
                        return
                    self.log("[ADMIN/MASTER]", cmd, target)
                    if cmd in ("k@", "kick", "b@", "ban") and target:
                        try:
                            action_ar = "الطرد" if cmd in ("k@", "kick") else "الحظر"
                            self.send_private_text(BOT_MASTER, f"✅ تم إرسال أمر {action_ar} الفعلي إلى @{target} في الغرفة {room}.")
                        except Exception as e2:
                            self.log("[ADMIN] confirmation failed:", repr(e2))
                except Exception as e:
                    self.log("[ADMIN] failed:", e)
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
            if "room_event" in result:
                self.handle_room_event(result)
            if result.get("users") or result.get("room_admin"):
                self.process_occupants_for_invite(result)
            if result.get("stream_event"):
                self.log("[STREAM]", result["stream_event"])
            if result.get("room_admin"):
                self.log("[ROOM_ADMIN]", result["room_admin"])
            if result.get("chat_message"):
                # Private master commands are also accepted as ChatMessage frames.
                cm = result["chat_message"]
                try:
                    frm = str(cm.get(3, "") or "").strip()
                    body = str(cm.get(5, "") or "").strip()
                    media_url = str(cm.get(6, "") or "").strip()
                    if frm and media_url and self._handle_publish_media(self.room, frm, media_url):
                        return
                    if _is_master_name(frm) and body:
                        if self._handle_management_command(self.room, body, frm):
                            return
                    if _is_master_name(frm) and body:
                        # Reuse room command handling with the command-context room.
                        ctx_room = self.room
                        parts = body.split(None, 1)
                        cmd = parts[0].lower() if parts else ""
                        arg = parts[1].strip() if len(parts) == 2 else ""
                        if cmd in ("inv", "دعوات", "invite"):
                            target_room = arg if arg else ctx_room
                            self.request_occupants(target_room)
                        elif cmd in ("دخول", "join", "ادخل", "enter") and arg:
                            target_room = arg
                            self.join_room(target_room)
                            self.send_private_text(BOT_MASTER, f"✅ دخلت الغرفة: {target_room} | الغرف الحالية: {len(self.known_rooms)}")
                        elif cmd in ("خروج", "leave", "exit"):
                            if arg:
                                ok = self.leave_room(arg)
                                self.send_private_text(BOT_MASTER, f"{'✅ خرجت من الغرفة' if ok else '❌ تعذر الخروج'}: {arg}")
                            else:
                                rooms = self.leave_all_rooms()
                                self.send_private_text(BOT_MASTER, f"✅ خرجت من جميع الغرف. العدد: {len(rooms)}")
                        elif cmd in ("invmsg", "رسالةدعوة") and arg:
                            self.invite_message_template = arg
                            self.send_private_text(BOT_MASTER, f"✅ تم تغيير رسالة الدعوة إلى: {arg}")
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

        self.known_rooms.add(self.room)
        self.join_room(self.room, force=True)

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
                        self.ws = RawWebSocket(url, list(header_lines), timeout=20, debug=RAW_DIAGNOSTIC)
                        self.ws.connect()
                        self.log("[WS] CONNECTED:", url)
                        self.log("[WS] custom headers:", [x.split(":",1)[0] + ": <redacted>" if x.lower().startswith(("username:", "password:")) else x for x in header_lines])
                        self.bootstrap_after_connect()

                        while not self.stop_event.is_set():
                            try:
                                kind, message = self.ws.recv()
                            except socket.timeout:
                                # An idle room is normal. Do not reconnect just
                                # because no WebSocket frame arrived during the
                                # read timeout.
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
                                raise ConnectionError(f"WebSocket closed by server: {message}")
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
        print("=== Talkinchat Bot V21 - Talkin + YouTube Cookies + Giant Gift Cards ===", flush=True)
        self.asset_server = start_asset_server()
        if not BOT_ID or not BOT_PWD or not self.room:
            raise SystemExit("Set BOT_ID, BOT_PWD and GROUP_TO_JOIN in .env first.")
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception as e:
                self.last_error = str(e)
                print("[BOT] error:", repr(e), flush=True)
            if not self.stop_event.is_set():
                print("[BOT] reconnecting in 10s...", flush=True)
                time.sleep(10)


if __name__ == "__main__":
    TalkinBot().start()
