"""Talkin2 adapter for the standalone persistent cricket engine."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from cricket_game import CricketGame


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


class CricketIntegration:
    """Route cricket commands and deliver engine events through Talkin2."""

    START_COMMANDS = {
        "تشغيل الكركت", "تشغيل الكركيت", "تشغيل الكريكيت", "cricket on", ".cr 1",
    }
    STOP_COMMANDS = {
        "إيقاف الكركت", "ايقاف الكركت", "إيقاف الكركيت", "ايقاف الكركيت",
        "إيقاف الكريكيت", "ايقاف الكريكيت", "cricket off", ".ct 0",
    }

    def __init__(
        self,
        data_dir: str | Path,
        *,
        persist: Callable | None = None,
        is_master: Callable[[str], bool],
        send_room_text: Callable[[str, str], object],
        send_room_media: Callable[[str, str, str], object],
        public_base: Callable[[], str],
        reward: Callable[[str, int], object] | None = None,
        log: Callable[..., object] = print,
    ):
        self.game = CricketGame(Path(data_dir) / "cricket_state.json", persist=persist, reward=reward)
        self.is_master = is_master
        self.send_room_text = send_room_text
        self.send_room_media = send_room_media
        self.public_base = public_base
        self.log = log
        self._cursors: dict[str, int] = {}

    @staticmethod
    def _low(value: str) -> str:
        return str(value or "").strip().casefold().translate(_DIGITS)

    @staticmethod
    def _room_key(room: str) -> str:
        return " ".join(str(room or "").strip().casefold().split())

    def _asset_url(self, filename: str) -> str:
        base = str(self.public_base() or "").rstrip("/")
        if not base:
            return ""
        if str(filename).startswith("cricket_result_"):
            return f"{base}/cricket-media/{filename}"
        return f"{base}/assets/{filename}"

    def deliver(self, room: str) -> None:
        room_key = self._room_key(room)
        cursor = int(self._cursors.get(room_key, 0))
        try:
            events = self.game.events_after(room, cursor)
            for event in events:
                for filename in event.get("images", []) or []:
                    url = self._asset_url(filename)
                    if url:
                        try:
                            self.send_room_media(room, url, "image")
                        except Exception as exc:
                            self.log("[CRICKET] image delivery failed", repr(exc))
                text = str(event.get("text") or "").strip()
                if text:
                    self.send_room_text(room, text)
                cursor = max(cursor, int(event.get("id", cursor) or cursor))
            self._cursors[room_key] = cursor
        except Exception as exc:
            self.log("[CRICKET] event delivery failed", repr(exc))

    def _reply_error(self, room: str, result: str | None) -> None:
        if result:
            self.send_room_text(room, str(result))

    def handle(self, room: str, sender: str, text: str, *, is_private: bool = False) -> bool:
        """Return True when the message belongs to cricket."""
        low = self._low(text)
        room = str(room or "").strip()
        sender = str(sender or "").strip().lstrip("@")

        if low in self.START_COMMANDS:
            if not self.is_master(sender):
                self.send_room_text(room, "🔒 تشغيل الكركيت للماستر فقط.")
                return True
            result = self.game.set_enabled(room, True)
            self._reply_error(room, result if result.startswith("❌") or result.startswith("⛔") else None)
            if not result.startswith(("❌", "⛔")):
                self._reply_error(room, self.game.begin_setup(room))
            self.deliver(room)
            return True

        if low in self.STOP_COMMANDS:
            if not self.is_master(sender):
                self.send_room_text(room, "🔒 إيقاف الكركيت للماستر فقط.")
                return True
            result = self.game.set_enabled(room, False)
            self._reply_error(room, result if result.startswith("❌") else None)
            if result and not result.startswith("❌"):
                self.send_room_text(room, result)
            self.deliver(room)
            return True

        # Private messages are used for the master switch only. Player actions
        # remain room-scoped so a private number cannot affect a match.
        if is_private:
            return False

        match = self.game.current()
        if not isinstance(match, dict):
            return False

        result: str | None = None
        if low in {"join", "انضمام"}:
            result = self.game.join(room, sender)
        elif match.get("stage") == "setup" and low in {"1", "2", "3", "4"}:
            if not self.is_master(sender):
                self.send_room_text(room, "🔒 اختيار عدد لاعبي الكركيت للماستر فقط.")
                return True
            result = self.game.select_player_count(room, int(low))
        elif match.get("stage") == "lobby" and low in {"bot", "بوت", "ضد البوت", "solo", "vs bot"}:
            result = self.game.play_bot(room, sender)
        elif match.get("stage") == "teams" and low in {"1", "2"}:
            result = self.game.choose_team(room, "attack" if low == "1" else "defense")
        elif match.get("stage") == "live" and re.fullmatch(r"[0-6]", low):
            result = self.game.submit_ball(room, sender, int(low))
        else:
            return False

        self._reply_error(room, result)
        self.deliver(room)
        return True
