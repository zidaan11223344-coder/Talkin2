import threading

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
    assert len(packets[0]) <= 1008
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
        assert len(packet) <= 1008
