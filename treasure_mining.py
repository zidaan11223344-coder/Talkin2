"""Persistent mining-game rules and inventory transactions for TalkinChat.

The caller supplies the bot's JSON load/save functions so state writes go
through the existing database/GitHub backup pipeline. Player records are keyed
only by numeric Talkin user IDs; usernames are retained for display/audit.
"""
from __future__ import annotations

import copy
import json
import os
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

COOLDOWN_SECONDS = 2 * 60 * 60

# Price values are centralized so the point economy can be adjusted without
# changing the mining, inventory, or redemption algorithms.
ITEMS = {
    "copper": {
        "name": "النحاس", "icon": "🟤", "price": 25_000,
        "image": "copper_ore.jpg", "kind": "ore",
    },
    "iron": {
        "name": "الحديد", "icon": "⚙️", "price": 75_000,
        "image": "iron_ore.jpg", "kind": "ore",
    },
    "ruby": {
        "name": "الياقوت", "icon": "🔴", "price": 200_000,
        "image": "ruby.jpg", "kind": "gem",
    },
    "diamond_clear": {
        "name": "الألماس العادي", "icon": "💎", "price": 500_000,
        "image": "diamond_clear.jpg", "kind": "diamond",
    },
    "diamond_blue": {
        "name": "الألماس الأزرق", "icon": "🔷", "price": 1_000_000,
        "image": "diamond_blue.jpg", "kind": "diamond",
    },
    "diamond_purple": {
        "name": "الألماس البنفسجي", "icon": "💜", "price": 2_000_000,
        "image": "diamond_purple.jpg", "kind": "diamond",
    },
    "diamond_red": {
        "name": "الألماس الأحمر", "icon": "❤️", "price": 4_000_000,
        "image": "diamond_red.jpg", "kind": "diamond",
    },
    "diamond_black": {
        "name": "الألماس الأسود", "icon": "🖤", "price": 7_500_000,
        "image": "diamond_black.jpg", "kind": "diamond",
    },
    "diamond_royal": {
        "name": "الألماس الملكي", "icon": "👑", "price": 15_000_000,
        "image": "diamond_royal.jpg", "kind": "diamond",
    },
}
DIAMOND_KEYS = tuple(key for key, item in ITEMS.items() if item["kind"] == "diamond")

# Weights sum to 10,000. A failed dig still consumes the two-hour cooldown.
OUTCOME_KEYS = (
    None,
    "copper", "iron", "ruby", "diamond_clear", "diamond_blue",
    "diamond_purple", "diamond_red", "diamond_black", "diamond_royal",
)
OUTCOME_WEIGHTS = (4500, 2800, 1600, 700, 220, 90, 45, 25, 15, 5)

_ALIAS_TO_KEYS = {
    "نحاس": ("copper",), "النحاس": ("copper",), "copper": ("copper",),
    "حديد": ("iron",), "الحديد": ("iron",), "iron": ("iron",),
    "ياقوت": ("ruby",), "الياقوت": ("ruby",), "ruby": ("ruby",),
    "الماس": DIAMOND_KEYS, "الألماس": DIAMOND_KEYS, "الالماس": DIAMOND_KEYS,
    "ماس": DIAMOND_KEYS, "diamond": DIAMOND_KEYS, "diamonds": DIAMOND_KEYS,
    "الماس العادي": ("diamond_clear",), "ألماس عادي": ("diamond_clear",),
    "diamond clear": ("diamond_clear",), "clear diamond": ("diamond_clear",), "diamond": DIAMOND_KEYS,
    "الماس الازرق": ("diamond_blue",), "الماس الأزرق": ("diamond_blue",),
    "ألماس ازرق": ("diamond_blue",), "blue diamond": ("diamond_blue",), "diamond blue": ("diamond_blue",),
    "الماس البنفسجي": ("diamond_purple",), "الماس البنفسجى": ("diamond_purple",),
    "purple diamond": ("diamond_purple",), "diamond purple": ("diamond_purple",),
    "الماس الاحمر": ("diamond_red",), "الماس الأحمر": ("diamond_red",),
    "red diamond": ("diamond_red",), "diamond red": ("diamond_red",),
    "الماس الاسود": ("diamond_black",), "الماس الأسود": ("diamond_black",),
    "black diamond": ("diamond_black",), "diamond black": ("diamond_black",),
    "الماس الملكي": ("diamond_royal",), "الماسي الملكي": ("diamond_royal",),
    "royal diamond": ("diamond_royal",), "diamond royal": ("diamond_royal",),
}


def resolve_item_keys(value: str) -> tuple[str, ...] | None:
    """Map an Arabic/English treasure name to one or more inventory keys."""
    token = " ".join(str(value or "").strip().casefold().split())
    token = token.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    token = token.replace("ى", "ي")
    # The alias table contains both canonical Arabic spellings and common
    # hamza-free spellings; normalize its keys with the same routine lazily.
    for alias, keys in _ALIAS_TO_KEYS.items():
        normalized = " ".join(alias.casefold().split())
        normalized = normalized.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
        if token == normalized:
            return tuple(keys)
    return None


def _valid_user_id(user_id: str) -> str:
    value = str(user_id or "").strip()
    if not value.isdigit():
        raise ValueError("a numeric Talkin user_id is required")
    return value


class MiningStore:
    """Thread-safe state store for mining attempts, inventory and redemptions."""

    def __init__(
        self,
        path: str | Path,
        load_json: Callable | None = None,
        save_json: Callable | None = None,
        *,
        chooser: Callable[[], str | None] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self.load_json = load_json or self._load_file
        self.save_json = save_json or self._save_file
        self.chooser = chooser or self._random_outcome
        self.clock = clock
        self.lock = threading.RLock()

    def _load_file(self, path, default):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else copy.deepcopy(default)
        except (OSError, ValueError, TypeError):
            return copy.deepcopy(default)

    def _save_file(self, path, data):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _load_state(self) -> dict:
        raw = self.load_json(self.path, {"version": 1, "players": {}})
        if not isinstance(raw, dict):
            raw = {}
        players = raw.get("players")
        if not isinstance(players, dict):
            players = {}
        return {"version": 1, "players": players}

    def _save_state(self, data: dict) -> None:
        self.save_json(self.path, data)

    @staticmethod
    def _player(state: dict, user_id: str, username: str) -> dict:
        players = state.setdefault("players", {})
        player = players.get(user_id)
        if not isinstance(player, dict):
            player = {}
            players[user_id] = player
        player["username"] = str(username or player.get("username") or "").strip().lstrip("@")
        inventory = player.get("inventory")
        if not isinstance(inventory, dict):
            inventory = {}
        player["inventory"] = {
            key: max(0, int(inventory.get(key, 0) or 0)) for key in ITEMS
        }
        return player

    @staticmethod
    def _random_outcome() -> str | None:
        return random.choices(OUTCOME_KEYS, weights=OUTCOME_WEIGHTS, k=1)[0]

    def dig(self, user_id: str, username: str, *, now: float | None = None) -> dict:
        """Commit one attempt and any found item before returning its result."""
        uid = _valid_user_id(user_id)
        moment = float(self.clock() if now is None else now)
        with self.lock:
            state = self._load_state()
            player = self._player(state, uid, username)
            if isinstance(player.get("pending_redemption"), dict):
                return {"ok": False, "error": "pending_redemption"}
            try:
                last = float(player.get("last_mine_at", 0) or 0)
            except (TypeError, ValueError):
                last = 0.0
            remaining = max(0, int(COOLDOWN_SECONDS - (moment - last) + 0.999)) if last > 0 else 0
            if remaining:
                return {"ok": False, "error": "cooldown", "remaining": remaining}

            item_key = self.chooser()
            if item_key not in ITEMS:
                item_key = None
            player["last_mine_at"] = moment
            player["mines_count"] = max(0, int(player.get("mines_count", 0) or 0)) + 1
            player["inventory"] = player.get("inventory", {})
            if item_key:
                player["inventory"][item_key] = int(player["inventory"].get(item_key, 0) or 0) + 1
                player["found_total"] = max(0, int(player.get("found_total", 0) or 0)) + 1
                if item_key in DIAMOND_KEYS:
                    player["diamonds_found"] = max(0, int(player.get("diamonds_found", 0) or 0)) + 1
            operation = {
                "id": uuid.uuid4().hex,
                "at": int(moment),
                "item": item_key,
            }
            history = player.setdefault("mine_history", [])
            if not isinstance(history, list):
                history = player["mine_history"] = []
            history.append(operation)
            del history[:-50]
            self._save_state(state)
            return {
                "ok": True,
                "operation_id": operation["id"],
                "item_key": item_key,
                "item": copy.deepcopy(ITEMS[item_key]) if item_key else None,
                "diamonds_found": int(player.get("diamonds_found", 0) or 0),
                "cooldown_until": moment + COOLDOWN_SECONDS,
            }

    def inventory(self, user_id: str, username: str = "") -> dict:
        uid = _valid_user_id(user_id)
        with self.lock:
            state = self._load_state()
            player = state.get("players", {}).get(uid, {})
            if not isinstance(player, dict):
                player = {}
            current_name = str(player.get("username") or "").strip().lstrip("@")
            requested_name = str(username or "").strip().lstrip("@")
            if requested_name and requested_name != current_name:
                player["username"] = requested_name
                state.setdefault("players", {})[uid] = player
                self._save_state(state)
            inventory = player.get("inventory") if isinstance(player.get("inventory"), dict) else {}
            return {
                "username": requested_name or current_name,
                "inventory": {key: max(0, int(inventory.get(key, 0) or 0)) for key in ITEMS},
                "diamonds_found": max(0, int(player.get("diamonds_found", 0) or 0)),
                "found_total": max(0, int(player.get("found_total", 0) or 0)),
                "pending_redemption": copy.deepcopy(player.get("pending_redemption"))
                if isinstance(player.get("pending_redemption"), dict) else None,
            }

    def leaderboard(self, limit: int = 10) -> list[dict]:
        with self.lock:
            state = self._load_state()
            rows = []
            for uid, player in (state.get("players") or {}).items():
                if not isinstance(player, dict):
                    continue
                total = max(0, int(player.get("diamonds_found", 0) or 0))
                if total:
                    rows.append({
                        "user_id": str(uid),
                        "username": str(player.get("username") or "مستخدم").strip().lstrip("@"),
                        "diamonds_found": total,
                    })
            rows.sort(key=lambda row: (-row["diamonds_found"], row["username"].casefold(), row["user_id"]))
            return rows[:max(1, int(limit))]

    def reserve_redemption(
        self,
        user_id: str,
        username: str,
        item_keys: tuple[str, ...] | list[str],
        quantity: int | None = None,
        *,
        now: float | None = None,
    ) -> dict:
        """Remove inventory into a durable journal before points are credited."""
        uid = _valid_user_id(user_id)
        selected_keys = tuple(key for key in item_keys if key in ITEMS)
        if not selected_keys:
            return {"ok": False, "error": "unknown_item"}
        if quantity is not None and int(quantity) <= 0:
            return {"ok": False, "error": "invalid_quantity"}
        moment = float(self.clock() if now is None else now)
        with self.lock:
            state = self._load_state()
            player = self._player(state, uid, username)
            existing = player.get("pending_redemption")
            if isinstance(existing, dict):
                return {"ok": False, "error": "pending_redemption", "pending": copy.deepcopy(existing)}
            inventory = player["inventory"]
            available = sum(int(inventory.get(key, 0) or 0) for key in selected_keys)
            if available <= 0:
                return {"ok": False, "error": "empty_inventory"}
            take_total = available if quantity is None else int(quantity)
            if take_total > available:
                return {"ok": False, "error": "insufficient_items", "available": available}
            remaining = take_total
            breakdown = {}
            # Select common items first when redeeming a quantity from all gems,
            # preserving rarer finds unless the player explicitly names them.
            for key in selected_keys:
                take = min(remaining, int(inventory.get(key, 0) or 0))
                if take:
                    breakdown[key] = take
                    inventory[key] -= take
                    remaining -= take
                if remaining == 0:
                    break
            points = sum(ITEMS[key]["price"] * count for key, count in breakdown.items())
            pending = {
                "id": uuid.uuid4().hex,
                "username": str(username or "").strip().lstrip("@"),
                "items": breakdown,
                "points": int(points),
                "created_at": int(moment),
            }
            player["pending_redemption"] = pending
            self._save_state(state)
            return {"ok": True, "pending": copy.deepcopy(pending), "remaining_inventory": copy.deepcopy(inventory)}

    def pending_redemption(self, user_id: str) -> dict | None:
        uid = _valid_user_id(user_id)
        with self.lock:
            state = self._load_state()
            player = state.get("players", {}).get(uid, {})
            pending = player.get("pending_redemption") if isinstance(player, dict) else None
            return copy.deepcopy(pending) if isinstance(pending, dict) else None

    def complete_redemption(self, user_id: str, transaction_id: str) -> bool:
        uid = _valid_user_id(user_id)
        txid = str(transaction_id or "").strip()
        if not txid:
            return False
        with self.lock:
            state = self._load_state()
            player = state.get("players", {}).get(uid, {})
            pending = player.get("pending_redemption") if isinstance(player, dict) else None
            if not isinstance(pending, dict) or str(pending.get("id") or "") != txid:
                return False
            history = player.setdefault("redemption_history", [])
            if not isinstance(history, list):
                history = player["redemption_history"] = []
            history.append(copy.deepcopy(pending))
            del history[:-50]
            player.pop("pending_redemption", None)
            self._save_state(state)
            return True
