import copy
import threading

import bot as bot_module


def test_roster_is_keyed_by_numeric_id_and_keeps_old_display_names(monkeypatch):
    stored = {"rooms": {}}

    monkeypatch.setattr(bot_module, "_persistent_rosters", lambda: copy.deepcopy(stored))
    monkeypatch.setattr(
        bot_module,
        "_save_persistent_rosters",
        lambda rooms: stored.update({"rooms": copy.deepcopy(rooms)}),
    )

    bot_module._remember_roster("Hall", [{"username": "Ahmed", "role": "member", "user_id": "3456782"}])
    bot_module._remember_roster("Hall", [{"username": "Ahmad", "role": "admin", "user_id": "3456782"}])

    room_key = bot_module._norm_room("Hall")
    roster = stored["rooms"][room_key]
    assert list(roster) == ["3456782"]
    assert roster["3456782"]["username"] == "Ahmad"
    assert "Ahmed" in roster["3456782"]["aliases"]
    assert bot_module._stored_user_id("Ahmed", "Hall") == "3456782"
    assert bot_module._stored_user_id("Ahmad", "Hall") == "3456782"
    assert bot_module._stored_username_for_id("3456782", "Hall") == "Ahmad"
    assert set(bot_module._stored_user_aliases("Ahmed", "Hall")) == {"Ahmed", "Ahmad"}


def test_legacy_game_and_points_records_resolve_through_numeric_id(monkeypatch):
    id_by_name = {"OldName": "7654321", "NewName": "7654321", "7654321": "7654321"}
    monkeypatch.setattr(bot_module, "_stored_user_id", lambda value, preferred_room="": id_by_name.get(str(value or "").lstrip("@"), ""))

    legacy_games = {
        "oldname": {
            "username": "OldName",
            "games": {"cricket": {"plays": 17, "points": 0, "staked": 0}},
        }
    }
    matches = bot_module._game_record_matches(legacy_games, "NewName")
    assert len(matches) == 1
    assert matches[0][0] == "oldname"
    # Names are the primary live-command key; the numeric ID remains a
    # compatibility fallback for legacy records and background persistence.
    assert bot_module._user_identity_key("NewName") == "newname"

    legacy_points = {"oldname": {"username": "OldName", "points": 1234}}
    candidates = bot_module._points_account_candidates(legacy_points, "NewName")
    assert candidates == [("oldname", legacy_points["oldname"])]

    # Existing verification records also follow the same Talkin account ID.
    assert bot_module._saved_identity_matches({"OldName": True}, "NewName")


def test_ambiguous_same_name_requires_room_context(monkeypatch):
    roster = {
        "rooms": {
            bot_module._norm_room("Hall A"): {
                "111": {"username": "Alex", "user_id": "111", "aliases": []},
            },
            bot_module._norm_room("Hall B"): {
                "222": {"username": "Alex", "user_id": "222", "aliases": []},
            },
        }
    }
    monkeypatch.setattr(bot_module, "_persistent_rosters", lambda: copy.deepcopy(roster))

    assert bot_module._stored_user_id("Alex") == ""
    assert bot_module._stored_user_id("Alex", "Hall A") == "111"
    assert bot_module._stored_user_id("Alex", "Hall B") == "222"
    previous = bot_module._set_identity_context("Alex", "Hall B")
    try:
        assert bot_module._stored_user_id("Alex") == "222"
    finally:
        bot_module._restore_identity_context(previous)


def test_background_member_id_sync_is_throttled_and_uses_members_list(monkeypatch):
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.ws = object()
    bot._pending_room_lists = {}
    bot._room_id_sync_lock = threading.RLock()
    bot._room_id_sync_last = {}
    sent = threading.Event()
    packets = []

    def send_query(payload):
        packets.append(payload)
        sent.set()

    bot.send_query = send_query
    bot.log = lambda *args, **kwargs: None

    assert bot._schedule_room_id_sync("Hall") is True
    pending = bot._pending_room_lists[bot_module._norm_room("Hall")]
    assert pending["code"] == "id_sync"
    assert pending["request_type"] == "members_list"
    assert sent.wait(2)
    assert len(packets) == 1
    assert bot._schedule_room_id_sync("Hall") is False
    pending["timer"].cancel()


def test_mining_command_waits_for_background_members_list_then_runs_by_numeric_id(monkeypatch):
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.ws = object()
    bot._pending_room_lists = {}
    bot._room_id_sync_lock = threading.RLock()
    bot._room_id_sync_last = {}
    bot.room_users = {}
    bot.send_room_text = lambda *_args, **_kwargs: None
    bot.send_query = lambda *_args, **_kwargs: None
    bot._send_room_id_sync_request = lambda *_args, **_kwargs: None
    bot.log = lambda *_args, **_kwargs: None
    bot._extract_room_list_users = lambda result: result.get("users", [])

    executed = threading.Event()
    calls = []

    def execute(room, text, sender, user_id):
        calls.append((room, text, sender, user_id))
        executed.set()
        return True

    bot._execute_mining_command_with_id = execute
    monkeypatch.setattr(bot_module, "_remember_roster", lambda *_args, **_kwargs: None)

    assert bot._request_mining_identity_lookup("Hall", "Ahmed", "الماس") is True
    pending = bot._pending_room_lists[bot_module._norm_room("Hall")]
    assert pending["code"] == "mine_uid"
    assert pending["request_type"] == "members_list"

    assert bot._complete_pending_room_list({
        "_occupants_room": "Hall",
        "users": [{"username": "♥Ahmed", "user_id": "3456782", "role": "member"}],
    }) is True
    assert executed.wait(2)
    assert calls == [("Hall", "الماس", "Ahmed", "3456782")]
