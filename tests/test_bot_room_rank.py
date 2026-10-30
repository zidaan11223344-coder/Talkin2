import bot as bot_module


def _new_bot():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.ws = object()
    bot.sent_queries = []
    bot.room_messages = []
    bot.log = lambda *_args, **_kwargs: None
    bot.send_query = lambda packet: bot.sent_queries.append(bytes(packet)) or True
    bot.send_room_text = lambda room, text: bot.room_messages.append((room, text)) or True
    bot._pending_room_lists = {}
    bot._pending_bot_room_role_checks = {}
    bot.bot_room_roles = {}
    bot.room_users = {}
    return bot


def test_short_role_codes_are_normalized_for_owner_checks():
    bot = _new_bot()
    bot.bot_room_roles[bot_module._norm_room("Hall")] = "o"
    assert bot._bot_room_role("Hall") == "owner"
    assert bot._bot_is_room_owner("Hall")
    assert bot_module._normalize_room_role("a") == "admin"
    assert bot_module._normalize_room_role("m") == "member"


def test_rank_command_sends_app_style_server_query_and_reports_bot_rank(monkeypatch):
    bot = _new_bot()
    assert bot._handle_bot_room_role_command("Hall", "Requester", "رتبتك")
    query = bot_module.decode_message(bot.sent_queries[0])
    assert bot_module.as_text(query[1][0]) == "room_admin"
    assert bot_module.as_text(query[2][0]) == "occupants_list"
    assert bot_module.as_text(query[6][0]) == "Hall"
    assert bot_module.as_text(query[4][0]) == "username"
    state = bot._pending_bot_room_role_checks[bot_module._norm_room("Hall")]
    state["timer"].cancel()

    bot._extract_room_list_users = lambda _result: [{"username": bot_module.BOT_ID, "role": "o"}]
    result = {"_occupants_room": "Hall"}
    assert bot._complete_pending_room_list(result)
    assert bot._bot_room_role("Hall") == "owner"
    assert any("Owner" in text or "أونر" in text for _room, text in bot.room_messages)


def test_missing_app_rank_retries_legacy_bot_id_query(monkeypatch):
    bot = _new_bot()
    assert bot._handle_bot_room_role_command("Hall", "Requester", "رتبتك")
    key = bot_module._norm_room("Hall")
    request_id = bot._pending_bot_room_role_checks[key]["request_id"]
    bot._pending_bot_room_role_checks[key]["timer"].cancel()
    bot._extract_room_list_users = lambda _result: []
    assert bot._complete_pending_room_list({"_occupants_room": "Hall"})
    assert len(bot.sent_queries) == 2
    fallback = bot._pending_room_lists[key]
    assert fallback["request_mode"] == "legacy"
    query = bot_module.decode_message(bot.sent_queries[1])
    assert bot_module.as_text(query[4][0]) == bot_module.BOT_ID
    assert bot._pending_bot_room_role_checks[key]["request_id"] != request_id
    bot._pending_bot_room_role_checks[key]["timer"].cancel()
