import threading
from unittest.mock import patch

import bot as bot_module


def test_oversized_top_result_is_paginated_without_generic_notice():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._master_reply_local = threading.local()
    bot._master_reply_local.tracking = True
    bot._master_reply_local.command_text = "top"
    bot._master_reply_local.command_sender = "Player"
    bot._master_reply_local.command_room = "Hall"
    bot._silent_master_local = threading.local()
    bot._localize_room_text = lambda _room, text: text
    bot._effective_room_language = lambda _room: "ar"
    bot._result_pages = {}
    packets = []
    bot.send_query = lambda payload: packets.append(bytes(payload)) or True
    bot.log = lambda *_args: None

    lines = ["🏆 توب النقاط"] + [f"{index}. @Player{index:02d} — {index * 10_000:,} نقطة" for index in range(50)]
    message = "\n".join(lines)
    assert len(bot_module.encode_query("room_message", type_="text", room="Hall", body=message)) > 1008

    assert bot.send_room_text("Hall", message) is True

    assert len(packets) == 1
    assert len(packets[0]) <= bot_module.SAFE_COMMAND_REPLY_BYTES
    state = bot._result_pages[("room_message", "Hall", "Player")]
    assert len(state["pages"]) > 1
    bodies = state["pages"]
    combined = "\n".join(bodies)
    for index in range(50):
        assert f"@Player{index:02d}" in combined
    assert all("تم تجاهل رسالتك بسبب حجم كبير" not in body for body in bodies)
    assert state["part"] == 1
    for index, page in enumerate(bodies):
        footer = "\n\n📌 اكتب ns للقائمة التالية." if index < len(bodies) - 1 else "\n\n✅ انتهت القوائم."
        packet = bot_module.encode_query("room_message", type_="text", room="Hall", body=page + footer)
        assert len(packet) <= bot_module.SAFE_COMMAND_REPLY_BYTES


def test_points_top_keeps_fifteen_members_and_uses_safe_pages():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._master_reply_local = threading.local()
    bot._master_reply_local.tracking = True
    bot._master_reply_local.command_text = "top"
    bot._master_reply_local.command_private = True
    bot._master_reply_local.command_sender = "Viewer"
    bot._master_reply_local.command_room = ""
    bot._silent_master_local = threading.local()
    bot._result_pages = {}
    packets = []
    bot.send_query = lambda payload: packets.append(bytes(payload)) or True
    bot.log = lambda *_args: None
    accounts = {
        f"Player{i}" + "X" * 42: {
            "username": f"Player{i}" + "X" * 42,
            "points": 2_000_000_000 - i * 10_000,
        }
        for i in range(1, 17)
    }

    with patch.object(bot_module, "_points_data", return_value=accounts):
        assert bot._handle_management_command_impl("", "top", "Viewer", is_private=True) is True

    assert packets and all(len(packet) <= bot_module.SAFE_COMMAND_REPLY_BYTES for packet in packets)
    state = bot._result_pages[("chat_message", "", "Viewer")]
    assert len(state["pages"]) > 1
    joined = "\n".join(state["pages"])
    for i in range(1, 16):
        assert f"Player{i}" in joined
    assert "Player16" not in joined
    for index, page in enumerate(state["pages"]):
        if index < len(state["pages"]) - 1:
            footer = "\n\n📌 Type ns for the next list." if state["language"] == "en" else "\n\n📌 اكتب ns للقائمة التالية."
        else:
            footer = "\n\n✅ End of list." if state["language"] == "en" else "\n\n✅ انتهت القوائم."
        payload = bot_module.encode_query("chat_message", type_="text", to="Viewer", body=page + footer)
        assert len(payload) <= bot_module.SAFE_COMMAND_REPLY_BYTES
