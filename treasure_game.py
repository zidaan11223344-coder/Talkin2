"""Persistent TalkinChat mining game: treasures, inventory, redemption and diamond leaderboard."""
from __future__ import annotations
import json, os, random, threading, time, uuid
from pathlib import Path

DATA_PATH = Path(os.getenv("BOT_DATA_DIR") or os.getenv("PERSISTENT_DATA_DIR") or Path(__file__).resolve().parent / "data") / "treasure_game.json"
LOCK = threading.RLock()
COOLDOWN_SECONDS = 30
DAY_SECONDS = 24 * 60 * 60
DAILY_DIAMOND_SPAWNS = 15

# weights are relative probabilities; they are normalized automatically.
ITEMS = {
    "نحاس": {"label": "النحاس", "symbol": "🪙", "points": 5, "weight": 27.0, "diamond": False, "image": "treasure_copper.png"},
    "حديد": {"label": "الحديد", "symbol": "⚙️", "points": 15, "weight": 18.0, "diamond": False, "image": "treasure_iron.png"},
    "ياقوت": {"label": "الياقوت الأحمر", "symbol": "❤️", "points": 50, "weight": 8.0, "diamond": False, "image": "treasure_ruby.png"},
    "الماس": {"label": "الألماس العادي", "symbol": "💎", "points": 100, "weight": 4.0, "diamond": True, "image": "diamond_normal.jpg"},
    "الماس_ازرق": {"label": "الألماس الأزرق النادر", "symbol": "💙", "points": 250, "weight": 1.5, "diamond": True, "image": "diamond_blue.jpg"},
    "الماس_بنفسجي": {"label": "الألماس البنفسجي النادر جداً", "symbol": "💜", "points": 500, "weight": 0.8, "diamond": True, "image": "diamond_purple.jpg"},
    "الماس_احمر": {"label": "الألماس الأحمر الأسطوري", "symbol": "❤️", "points": 1000, "weight": 0.4, "diamond": True, "image": "diamond_red.jpg"},
    "الماس_اسود": {"label": "الألماس الأسود شديد الندرة", "symbol": "🖤", "points": 2500, "weight": 0.2, "diamond": True, "image": "diamond_black.jpg"},
    "الماس_ملكي": {"label": "الألماس الملكي", "symbol": "👑", "points": 5000, "weight": 0.1, "diamond": True, "image": "diamond_royal.jpg"},
}
FAIL_WEIGHT = 40.0
ALIASES = {
    "نحاس": "نحاس", "النحاس": "نحاس", "copper": "نحاس",
    "حديد": "حديد", "الحديد": "حديد", "iron": "حديد",
    "ياقوت": "ياقوت", "الياقوت": "ياقوت", "ruby": "ياقوت",
    "الماس": "الماس", "الماسة": "الماس", "الالماس": "الماس", "ألماس": "الماس", "diamond": "الماس",
    "الماس الازرق": "الماس_ازرق", "الألماس الأزرق": "الماس_ازرق", "الماس_ازرق": "الماس_ازرق",
    "الماس البنفسجي": "الماس_بنفسجي", "الماس_بنفسجي": "الماس_بنفسجي",
    "الماس الاحمر": "الماس_احمر", "الماس_احمر": "الماس_احمر",
    "الماس الاسود": "الماس_اسود", "الماس_اسود": "الماس_اسود",
    "الماس الملكي": "الماس_ملكي", "الماس_ملكي": "الماس_ملكي",
}
DIAMOND_KEYS = [k for k, v in ITEMS.items() if v["diamond"]]


def _load():
    try:
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save(data):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_PATH.with_name(DATA_PATH.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA_PATH)


def _user_key(user_id):
    return str(user_id or "").strip().casefold()


def _player(data, user_id, username=""):
    key = _user_key(user_id)
    players = data.setdefault("players", {})
    row = players.setdefault(key, {"user_id": str(user_id), "username": str(username or user_id), "inventory": {}, "diamonds_found": 0, "last_mine": 0})
    if username:
        row["username"] = str(username).strip().lstrip("@")
    row.setdefault("inventory", {})
    row.setdefault("diamonds_found", 0)
    row.setdefault("last_mine", 0)
    return row


def _random_diamond_spawns(start):
    return sorted(random.uniform(start, start + DAY_SECONDS) for _ in range(DAILY_DIAMOND_SPAWNS))


def _diamond_schedule(data, now):
    schedule = data.get("diamond_schedule")
    if not isinstance(schedule, dict) or not isinstance(schedule.get("times"), list):
        cycle_end = now + DAY_SECONDS
        schedule = {"cycle_end": cycle_end, "times": _random_diamond_spawns(now)}
    else:
        cycle_end = float(schedule.get("cycle_end", 0) or 0)
        times = [float(value) for value in schedule.get("times", [])]
        if cycle_end <= 0:
            cycle_end = now + DAY_SECONDS
            times = _random_diamond_spawns(now)
        while now >= cycle_end:
            # Unclaimed spawns expire at the end of their 24-hour cycle.
            times = _random_diamond_spawns(cycle_end)
            cycle_end += DAY_SECONDS
        schedule = {"cycle_end": cycle_end, "times": sorted(times)}
    data["diamond_schedule"] = schedule
    return schedule


def mine(user_id, username="", now=None):
    """Mine every 30 seconds; the first miner after a random daily spawn gets a diamond."""
    now = float(now if now is not None else time.time())
    with LOCK:
        data = _load(); row = _player(data, user_id, username)
        remaining = COOLDOWN_SECONDS - (now - float(row.get("last_mine", 0) or 0))
        if remaining > 0:
            return {"ok": False, "remaining": int(remaining)}
        row["last_mine"] = now
        schedule = _diamond_schedule(data, now)
        if schedule["times"] and schedule["times"][0] <= now:
            schedule["times"].pop(0)
            diamond_items = [(k, float(v["weight"])) for k, v in ITEMS.items() if v["diamond"]]
            chosen = random.choices([p[0] for p in diamond_items], weights=[p[1] for p in diamond_items], k=1)[0]
        else:
            # Diamonds are available only through the 15 randomized daily spawns.
            pool = [(None, FAIL_WEIGHT)] + [(k, float(v["weight"])) for k, v in ITEMS.items() if not v["diamond"]]
            chosen = random.choices([p[0] for p in pool], weights=[p[1] for p in pool], k=1)[0]
        if chosen is None:
            _save(data)
            return {"ok": True, "found": False}
        row["inventory"][chosen] = int(row["inventory"].get(chosen, 0) or 0) + 1
        item = ITEMS[chosen]
        if item["diamond"]:
            row["diamonds_found"] = int(row.get("diamonds_found", 0) or 0) + 1
        _save(data)
        return {"ok": True, "found": True, "item": chosen, "label": item["label"], "symbol": item["symbol"], "diamond": item["diamond"], "image": item["image"], "points": item["points"]}


def give_test_diamond(user_id, username=""):
    """Grant the next diamond type to the master for testing the room image flow."""
    with LOCK:
        data = _load()
        index = int(data.get("test_diamond_index", 0) or 0) % len(DIAMOND_KEYS)
        key = DIAMOND_KEYS[index]
        row = _player(data, user_id, username)
        row["inventory"][key] = int(row["inventory"].get(key, 0) or 0) + 1
        row["diamonds_found"] = int(row.get("diamonds_found", 0) or 0) + 1
        data["test_diamond_index"] = (index + 1) % len(DIAMOND_KEYS)
        _save(data)
        item = ITEMS[key]
        return {"ok": True, "item": key, "label": item["label"], "symbol": item["symbol"], "diamond": True, "image": item["image"], "points": item["points"]}


def inventory(user_id, username=""):
    with LOCK:
        data = _load(); row = _player(data, user_id, username); _save(data)
        return dict(row.get("inventory", {}))


def leaderboard(limit=15):
    with LOCK:
        data = _load()
        rows = []
        for row in (data.get("players") or {}).values():
            if not isinstance(row, dict): continue
            count = int(row.get("diamonds_found", 0) or 0)
            if count > 0: rows.append((count, str(row.get("username") or row.get("user_id") or "لاعب")))
        rows.sort(key=lambda x: (-x[0], x[1].casefold()))
        return rows[:max(1, int(limit))]


def begin_redemption(user_id, username, item_name):
    """Reserve and remove all of one item; caller credits points, then commits or rolls back."""
    key = ALIASES.get(str(item_name or "").strip().casefold())
    if not key or key not in ITEMS:
        return {"ok": False, "error": "unknown"}
    with LOCK:
        data = _load(); row = _player(data, user_id, username)
        amount = int(row["inventory"].get(key, 0) or 0)
        if amount <= 0: return {"ok": False, "error": "empty", "item": key}
        points = amount * int(ITEMS[key]["points"])
        row["inventory"][key] = 0
        data.setdefault("redemptions", []).append({"id": uuid.uuid4().hex, "user_id": str(user_id), "username": str(username), "item": key, "quantity": amount, "points": points, "time": time.time(), "status": "pending"})
        data["redemptions"] = data["redemptions"][-2000:]
        _save(data)
        return {"ok": True, "item": key, "label": ITEMS[key]["label"], "quantity": amount, "points": points, "txid": data["redemptions"][-1]["id"]}


def finish_redemption(txid, success):
    with LOCK:
        data = _load()
        for row in reversed(data.get("redemptions", [])):
            if row.get("id") == txid and row.get("status") == "pending":
                row["status"] = "complete" if success else "rolled_back"
                if not success:
                    player = (data.get("players") or {}).get(_user_key(row.get("user_id")))
                    if player is not None:
                        inv = player.setdefault("inventory", {})
                        inv[row["item"]] = int(inv.get(row["item"], 0) or 0) + int(row["quantity"])
                _save(data)
                return


def format_cooldown(seconds):
    seconds = max(0, int(seconds)); hours, rem = divmod(seconds, 3600); minutes, seconds = divmod(rem, 60)
    if hours: return f"{hours} ساعة و{minutes} دقيقة"
    if minutes and seconds: return f"{minutes} دقيقة و{seconds} ثانية"
    if minutes: return f"{minutes} دقيقة"
    return f"{seconds} ثانية"
