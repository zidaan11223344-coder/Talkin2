#!/usr/bin/env python3
"""اختبار حماية غرفة Talkin بحسابات اختبار متعددة.

لا تضع كلمات المرور داخل هذا الملف. اضبط TEST_PASSWORD في البيئة، ثم شغّل:
    TEST_ACCOUNT_1=user1 TEST_ACCOUNT_2=user2 TEST_ACCOUNT_3=user3 \
    TEST_ACCOUNT_4=user4 TEST_ACCOUNT_5=user5 \
    TEST_ROOM='اسم الغرفة' TEST_MESSAGE='رسالة اختبار' \
    TEST_PASSWORD='كلمة المرور الموحدة' python3 security_chat_test.py

يمكن أيضًا وضع أسماء الحسابات في ملف JSON عبر TEST_ACCOUNTS_FILE:
    ["user1", "user2", "user3", "user4", "user5"]

هذا الملف يرسل رسالة واحدة من كل حساب بعد دخول الغرفة، ثم ينتظر الردود.
هو مخصص لاختبار غرفة تملكها أو لديك تصريح باختبارها.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

# Reuse the project's tested Talkin protocol implementation. Importing bot.py
# does not start a bot because its main block is guarded.
import bot as talkin


class TestAccountClient(talkin.TalkinBot):
    """TalkinBot connection with per-account credentials."""

    def __init__(self, username: str, password: str, room: str, log):
        self.test_username = username
        self.test_password = password
        self._test_log = log
        super().__init__()
        self.room = room

    def log(self, *parts):  # noqa: D401 - intentionally compact test logging
        self._test_log(self.test_username, " ".join(str(part) for part in parts))

    def authenticate(self):
        body = talkin.encode_auth_request(self.test_username, self.test_password)
        url = talkin.API_BASE_URL + "auth_new"
        response = self.http.post(
            url,
            data=body,
            headers={
                "Content-Type": "application/octet-stream",
                "User-Agent": "Talkinchat/1.0 (Android 12; net.chatp)",
            },
            timeout=15,
        )
        response.raise_for_status()
        self.auth = talkin.decode_auth_result(response.content)
        self.auth_server = self.auth["server"] if self.auth["server"].isdigit() else ""
        self.captcha_id = self.auth.get("id") or os.getenv("CAPTCHA_ID", "0")
        self.photo_version = self.auth.get("photo_version") or os.getenv("PHOTO_VERSION", "0")
        self.roster_version = os.getenv("ROSTER_VERSION", "0")
        result = str(self.auth.get("result") or "").lower()
        if result not in {"ok", "success", "true", "1"}:
            raise RuntimeError(self.auth.get("message") or f"Authentication rejected: {result}")
        return self.auth


def load_accounts() -> list[str]:
    filename = os.getenv("TEST_ACCOUNTS_FILE", "").strip()
    if filename:
        raw = json.loads(Path(filename).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("accounts", [])
        if not isinstance(raw, list):
            raise ValueError("TEST_ACCOUNTS_FILE يجب أن يحتوي قائمة accounts")
        names = [str(item.get("username", "") if isinstance(item, dict) else item) for item in raw]
    else:
        names = [os.getenv(f"TEST_ACCOUNT_{index}", "") for index in range(1, 6)]
    names = [name.strip().lstrip("@") for name in names if name.strip()]
    if len(names) != 5:
        raise ValueError("يجب ضبط خمسة حسابات بالضبط: TEST_ACCOUNT_1 إلى TEST_ACCOUNT_5")
    if len({name.casefold() for name in names}) != 5:
        raise ValueError("أسماء الحسابات الخمسة يجب أن تكون مختلفة")
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="اختبار حماية غرفة Talkin بخمسة حسابات")
    parser.add_argument("--dry-run", action="store_true", help="عرض الإعدادات دون تسجيل الدخول أو الإرسال")
    args = parser.parse_args()

    accounts = load_accounts()
    password = os.getenv("TEST_PASSWORD", "")
    room = os.getenv("TEST_ROOM", "").strip()
    message = os.getenv("TEST_MESSAGE", "").strip()
    wait_seconds = float(os.getenv("TEST_WAIT_SECONDS", "8"))
    send_interval = float(os.getenv("TEST_SEND_INTERVAL", "1"))

    if not password:
        raise ValueError("اضبط TEST_PASSWORD؛ كلمة المرور نفسها تستخدم للحسابات الخمسة")
    if not room:
        raise ValueError("اضبط TEST_ROOM باسم الغرفة")
    if not message:
        raise ValueError("اضبط TEST_MESSAGE بالرسالة المراد اختبارها")
    if wait_seconds < 1 or send_interval < 0:
        raise ValueError("TEST_WAIT_SECONDS يجب أن يكون >= 1 وTEST_SEND_INTERVAL >= 0")

    print(f"الحسابات: {', '.join('@' + name for name in accounts)}")
    print(f"الغرفة: {room}")
    print(f"الرسالة: {message}")
    print(f"الانتظار قبل الإرسال: {wait_seconds:g} ثانية")
    if args.dry_run:
        print("وضع المعاينة: لم يتم تسجيل الدخول أو إرسال أي رسالة.")
        return 0

    clients: list[TestAccountClient] = []
    threads: list[threading.Thread] = []
    log_lock = threading.Lock()

    def log(username: str, text: str) -> None:
        with log_lock:
            print(f"[{username}] {text}", flush=True)

    try:
        for username in accounts:
            client = TestAccountClient(username, password, room, log)
            clients.append(client)
            thread = threading.Thread(
                target=client.run_once,
                name=f"security-test-{username}",
                daemon=True,
            )
            threads.append(thread)
            thread.start()
            time.sleep(0.4)

        print(f"انتظار {wait_seconds:g} ثانية لدخول الحسابات الغرفة...", flush=True)
        time.sleep(wait_seconds)
        for index, client in enumerate(clients, start=1):
            try:
                client.send_room_text(room, message)
                log(client.test_username, f"تم إرسال الرسالة رقم {index}")
            except Exception as exc:
                log(client.test_username, f"فشل الإرسال: {exc}")
            if send_interval:
                time.sleep(send_interval)
        extra_wait = float(os.getenv("TEST_AFTER_SEND_SECONDS", "5"))
        print(f"انتظار {extra_wait:g} ثانية لمراقبة رد الحماية...", flush=True)
        time.sleep(max(0, extra_wait))
    finally:
        for client in clients:
            client.stop_event.set()
            try:
                if client.ws:
                    client.ws.close()
            except Exception:
                pass
        for thread in threads:
            thread.join(timeout=3)
    print("انتهى اختبار الحسابات الخمسة.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
