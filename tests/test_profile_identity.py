import copy
import queue
import threading

import bot as bot_module


def _new_profile_bot():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.ws = object()
    bot.sent_queries = []
    bot.private_messages = []
    bot.room_messages = []
    bot.send_query = lambda packet: bot.sent_queries.append(bytes(packet)) or True
    bot.send_private_text = lambda user, text: bot.private_messages.append((user, text)) or True
    bot.send_room_text = lambda room, text: bot.room_messages.append((room, text)) or True
    bot.log = lambda *_args, **_kwargs: None
    return bot


def _respond(bot, username, user_id):
    return bot._handle_profile_other_payload({
        "handler": "profile_other", "type": username, "user_id": str(user_id),
    })


def test_id_command_uses_app_profile_other_query_and_validates_response_name():
    bot = _new_profile_bot()
    assert bot._room_list_commands("Hall", "id@Ahmed", "Requester", is_private=False)
    packet = bot_module.decode_message(bot.sent_queries[0])
    assert bot_module.as_text(packet[1][0]) == "profile_other"
    assert bot_module.as_text(packet[2][0]) == "Ahmed"
    assert bot_module.as_text(packet[8][0])
    assert "أبحث عن ID" in bot.room_messages[0][1]

    # A stale response for another profile must not satisfy this lookup.
    assert bot._handle_profile_other_payload({
        "handler": "profile_other", "type": "Mallory", "user_id": "8888",
    })
    assert bot._profile_lookup_active["username"] == "Ahmed"
    assert _respond(bot, "Ahmed", "3456782")
    assert "3456782" in bot.room_messages[-1][1]
    assert bot._profile_lookup_active is None


def test_on_message_queues_json_text_frames_for_profile_handler():
    bot = _new_profile_bot()
    bot._event_queue = queue.PriorityQueue()
    bot._event_queue_lock = threading.Lock()
    bot._event_queue_seq = 0
    bot._process_message = lambda _ws, payload: None

    bot.on_message(object(), '{"handler":"profile_other"}')
    priority, _seq, _ws, payload = bot._event_queue.get_nowait()
    assert priority == 0
    assert payload == '{"handler":"profile_other"}'


def test_points_identity_refresh_persists_name_and_server_id(monkeypatch):
    bot = _new_profile_bot()
    accounts = {"alice": {"username": "Alice", "points": 1234}}
    monkeypatch.setattr(bot_module, "_points_data", lambda: accounts)
    monkeypatch.setattr(bot_module, "_is_primary_master", lambda _name: True)

    def mutate_points(updater):
        work = copy.deepcopy(accounts)
        result, changed = updater(work, [])
        if changed:
            accounts.clear()
            accounts.update(work)
        return result

    monkeypatch.setattr(bot_module, "_mutate_points_state", mutate_points)

    assert bot._start_user_id_refresh("points", "RootMaster", True)
    assert "بدأت مزامنة IDs" in bot.private_messages[0][1]
    request = bot_module.decode_message(bot.sent_queries[0])
    assert bot_module.as_text(request[1][0]) == "profile_other"
    assert bot_module.as_text(request[2][0]) == "Alice"

    assert _respond(bot, "Alice", "3456782")
    assert accounts["alice"]["username"] == "Alice"
    assert accounts["alice"]["user_id"] == "3456782"
    assert any("جلبت ID لـ: 1" in text and "حدثت ID لـ: 1" in text
               for _user, text in bot.private_messages)
    assert "points" not in bot._id_refresh_jobs


def test_vip_identity_update_preserves_existing_record(monkeypatch):
    data = {"alice": {"username": "Alice", "verified_by": "Root", "created_at": 12}}
    saved = []
    monkeypatch.setattr(bot_module, "_vip_data", lambda: data)
    monkeypatch.setattr(bot_module, "_save_local_json", lambda path, value: saved.append((path, copy.deepcopy(value))))

    result = bot_module._update_vip_user_id("Alice", "3456782")
    assert result["ok"] and result["changed"]
    assert saved[-1][1]["alice"]["username"] == "Alice"
    assert saved[-1][1]["alice"]["verified_by"] == "Root"
    assert saved[-1][1]["alice"]["user_id"] == "3456782"


def test_refresh_commands_are_master_classified_and_user_id_command_is_a_bot_command():
    assert bot_module._looks_like_admin_command("تحديث ايدي ملفvip")
    assert bot_module._looks_like_admin_command("حدث ايديهات ملف النقاط")
    assert bot_module._looks_like_bot_command("id@Ahmed")


def test_duplicate_saved_user_id_is_rejected_as_ambiguous(monkeypatch):
    monkeypatch.setattr(bot_module, "_points_data", lambda: {
        "alice": {"username": "Alice", "user_id": "111", "points": 10},
        "alias": {"username": "Alicia", "user_id": "111", "points": 20},
    })
    result = bot_module._points_identity_status("Alice", "111")
    assert result == {"ok": False, "error": "ambiguous_user_id"}


def test_actual_points_transfer_preserves_both_saved_ids(monkeypatch, tmp_path):
    accounts = {
        "alice": {"username": "Alice", "user_id": "111", "points": 1000},
        "bob": {"username": "Bob", "user_id": "222", "points": 50},
    }
    saved = []
    monkeypatch.setattr(bot_module, "POINTS_FILE", tmp_path / "points.json")
    monkeypatch.setattr(bot_module, "_STATE_DB_ENABLED", False)
    monkeypatch.setattr(bot_module, "_STATE_DB", None)
    monkeypatch.setattr(bot_module, "_POINTS_CACHE", copy.deepcopy(accounts))
    monkeypatch.setattr(bot_module, "_POINTS_TRANSFER_CACHE", [])
    monkeypatch.setattr(
        bot_module, "_save_local_json",
        lambda _path, payload, **_kwargs: saved.append(copy.deepcopy(payload)),
    )

    rejected = bot_module._transfer_points(
        "Alice", "Bob", 100, allow_alias_source=False, require_exact_target=True,
        expected_sender_id="999", expected_target_id="222",
    )
    assert not rejected["ok"] and rejected["error"] == "sender_id_mismatch"
    assert saved == []

    result = bot_module._transfer_points(
        "Alice", "Bob", 100, allow_alias_source=False, require_exact_target=True,
        expected_sender_id="111", expected_target_id="222",
    )
    assert result["ok"]
    state = saved[-1]["accounts"]
    assert state["alice"]["points"] == 900 and state["alice"]["user_id"] == "111"
    assert state["bob"]["points"] == 150 and state["bob"]["user_id"] == "222"


def test_sb_transfer_requires_exact_saved_name_and_matching_ids(monkeypatch):
    bot = _new_profile_bot()
    accounts = {
        "alice": {"username": "Alice", "user_id": "111", "points": 1000},
        "bob": {"username": "Bob", "user_id": "222", "points": 50},
    }
    monkeypatch.setattr(bot_module, "_points_data", lambda: accounts)
    transfer_calls = []
    monkeypatch.setattr(bot_module, "_transfer_points", lambda *args, **kwargs: (
        transfer_calls.append((args, kwargs)) or {
            "ok": True, "sender": "Alice", "recipient": "Bob",
            "sender_balance": 900, "recipient_balance": 150,
        }
    ))

    assert bot._start_identity_checked_transfer("Alice", "Bob", 100)
    assert _respond(bot, "Alice", "111")
    assert len(bot.sent_queries) == 2
    assert _respond(bot, "Bob", "999")  # valid lookup, but wrong ID for the saved points account

    assert transfer_calls == []
    assert any("ID الخادم لا يطابق" in text and "لم يتغير أي رصيد" in text
               for _user, text in bot.private_messages)


def test_sb_transfer_runs_only_after_both_saved_ids_match(monkeypatch):
    bot = _new_profile_bot()
    accounts = {
        "alice": {"username": "Alice", "user_id": "111", "points": 1000},
        "bob": {"username": "Bob", "user_id": "222", "points": 50},
    }
    monkeypatch.setattr(bot_module, "_points_data", lambda: accounts)
    transfer_calls = []
    monkeypatch.setattr(bot_module, "_transfer_points", lambda *args, **kwargs: (
        transfer_calls.append((args, kwargs)) or {
            "ok": True, "sender": "Alice", "recipient": "Bob",
            "sender_balance": 900, "recipient_balance": 150,
        }
    ))

    assert bot._start_identity_checked_transfer("Alice", "Bob", 100)
    assert _respond(bot, "Alice", "111")
    assert transfer_calls == []
    assert _respond(bot, "Bob", "222")

    assert len(transfer_calls) == 1
    args, kwargs = transfer_calls[0]
    assert args == ("Alice", "Bob", 100)
    assert kwargs["allow_alias_source"] is False
    assert kwargs["require_exact_target"] is True
    assert kwargs["expected_sender_id"] == "111"
    assert kwargs["expected_target_id"] == "222"
    assert any("تم تحويل" in text for _user, text in bot.private_messages)
