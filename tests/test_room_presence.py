import re
import time
from types import SimpleNamespace
from unittest.mock import patch

import bot as bot_module


def test_la_room_roster_requests_live_occupants_and_replies_in_public_or_private():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.ws = object()
    bot._pending_room_lists = {}
    queries = []
    private_messages = []
    public_results = []
    private_results = []
    bot.send_query = lambda query: queries.append(query)
    bot.send_private_text = lambda user, text: private_messages.append((user, text)) or True
    bot._extract_room_list_users = lambda _result: [
        {"username": "Alice"}, {"username": "alice"}, {"username": "test-bot"}, {"username": "Bob"}
    ]
    bot._send_room_list = lambda room, title, users, empty, sender="": public_results.append((room, title, users, sender))
    bot._send_private_list = lambda sender, title, users, empty: private_results.append((sender, title, users))

    with patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
        bot_module.member_shop, "active", return_value=False
    ):
        assert bot._room_list_commands("Source", "la@Hall", "Player", is_private=False)
        public_pending = bot._pending_room_lists[bot_module._norm_room("Hall")]
        assert public_pending["code"] == "la"
        assert public_pending["private_response"] is False
        assert public_pending["response_room"] == "Source"
        assert bot._complete_pending_room_list({"_occupants_room": "Hall"})

        assert bot._room_list_commands("Source", "la@Hall", "Player", is_private=True)
        private_pending = bot._pending_room_lists[bot_module._norm_room("Hall")]
        assert private_pending["private_response"] is True
        assert bot._complete_pending_room_list({"_occupants_room": "Hall"})

    assert len(queries) == 2
    assert len(public_results) == 1
    assert public_results[0][0] == "Source"
    assert [row["username"] for row in public_results[0][2]] == ["Alice", "Bob"]
    assert len(private_results) == 1
    assert [row["username"] for row in private_results[0][2]] == ["Alice", "Bob"]
    assert private_messages == []  # no noisy "fetching..." DM for a public command


def test_room_roster_pages_are_limited_to_thirty_and_reset_numbering():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._result_pages = {}
    sent = []
    bot.send_room_text = lambda room, text: sent.append((room, text)) or True
    users = [{"username": f"Member{i:02d}"} for i in range(65)]

    bot._send_room_list("Hall", "🟢 المتواجدون الآن في Hall", users, sender="Player")

    state = bot._result_pages[("room_message", "Hall", "Player")]
    assert len(state["pages"]) == 3
    row_counts = []
    for page in state["pages"]:
        numbers = [int(match.group(1)) for match in re.finditer(r"(?m)^(\d+)\. @", page)]
        row_counts.append(len(numbers))
        assert numbers == list(range(1, len(numbers) + 1))
    assert row_counts == [30, 30, 5]
    assert "للقائمة التالية اكتب Ns" in sent[0][1]


def test_la_text_roster_response_returns_list_in_command_room():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._pending_room_lists = {
        bot_module._norm_room("Target"): {
            "room": "Target", "code": "la", "sender": "Player",
            "request_type": "occupants_list", "response_room": "Source",
            "private_response": False,
        }
    }
    public = []
    private = []
    bot._send_room_list = lambda room, title, users, empty, sender="": public.append((room, title, users, sender))
    bot.send_private_text = lambda user, text: private.append((user, text)) or True
    bot.log = lambda *_args: None

    handled = bot._complete_pending_room_list_text(
        "Target", "User List: Members 1/1 (Total: 2):\n1. @Alice\n2. @Bob"
    )

    assert handled
    assert public[0][0] == "Source"
    assert "المتواجدون الآن في Target" in public[0][1]
    assert [item["username"] for item in public[0][2]] == ["Alice", "Bob"]
    assert bot._pending_room_lists == {}


def test_la_request_timeout_reports_missing_server_response_in_command_room():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._pending_room_lists = {
        bot_module._norm_room("Target"): {
            "room": "Target", "code": "la", "request_id": "req-1",
            "response_room": "Source", "private_response": False,
        }
    }
    sent = []
    bot.send_room_text = lambda room, text: sent.append((room, text)) or True

    assert bot._room_list_response_timeout(bot_module._norm_room("Target"), "req-1")
    assert sent[0][0] == "Source"
    assert "لم يصل رد المتواجدين" in sent[0][1]
    assert not bot._pending_room_lists


def test_ns_advances_room_gift_page_when_sender_identity_format_changes():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._result_pages = {
        ("room_message", "Hall", "@AhMeD"): {
            "pages": ["🎁 القائمة الأولى", "🎁 القائمة الثانية"],
            "part": 1, "kwargs": {"room": "Hall"},
        }
    }
    bot._filter_list_state = {}
    bot._filter_list_key = lambda room, sender: (room, sender)
    bot._transfer_log_pages = {}
    bot.help_pages = {}
    packets = []
    bot.send_query = lambda payload: packets.append(bytes(payload)) or True

    assert bot._handle_management_command("Hall", "ns", "ahmed", is_private=False)
    body = bot_module.as_text(bot_module.decode_message(packets[-1])[5][0])
    assert "🎁 القائمة الثانية" in body
    assert bot._result_pages[("room_message", "Hall", "@AhMeD")]["part"] == 2
    assert len(packets[-1]) < 1008


def test_report_reactions_are_delivered_only_to_master_private_chat():
    for kind in ("music", "image"):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.reaction_targets = {
            "a1b2": {
                "publisher": "Publisher", "kind": kind, "title": "Track or photo",
                "created_at": time.time(),
            }
        }
        bot._master_reply_local = SimpleNamespace(rerouting=False)
        private, public, logs = [], [], []
        bot.send_private_text = lambda user, text: private.append((user, text)) or True
        bot.send_room_text = lambda room, text: public.append((room, text)) or True
        bot.log = lambda *args: logs.append(args)
        with patch.object(bot_module, "BOT_MASTER", "RoomMaster"):
            assert bot._handle_reaction_command("Hall", "report@a1b2 spam report", "Reporter")
        assert len(private) == 1
        assert private[0][0] == "RoomMaster"
        assert "Reporter" in private[0][1] and "a1b2" in private[0][1]
        assert public == []
        assert bot._master_reply_local.rerouting is False


def test_new_commands_are_classified_before_verification_gate():
    assert bot_module._looks_like_bot_command("la@Hall")
    assert bot_module._looks_like_bot_command("sby 1")
    assert bot_module._looks_like_bot_command("store")
    assert bot_module._looks_like_bot_command("متجر")
    assert bot_module._looks_like_bot_command("ايدي")
    assert bot_module._looks_like_bot_command("id@Ahmed")


def test_id_command_queries_server_and_returns_numeric_user_id():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.ws = object()
    bot._pending_room_lists = {}
    queries = []
    replies = []
    bot.send_query = lambda query: queries.append(query)
    bot.send_room_text = lambda room, text: replies.append((room, text))
    bot.send_private_text = lambda user, text: replies.append((user, text))
    bot._extract_room_list_users = lambda _result: [
        {"username": "Ahmed", "user_id": "3456782", "role": "member"}
    ]

    with patch.object(bot_module, "_stored_user_id", return_value=""), patch.object(
        bot_module, "_remember_roster"
    ):
        assert bot._room_list_commands("Hall", "ايدي@Ahmed", "Requester", is_private=False)
        pending = bot._pending_room_lists[bot_module._norm_room("Hall")]
        assert pending["code"] == "uid"
        assert pending["target"] == "Ahmed"
        assert pending["request_type"] == "members_list"
        assert bot._complete_pending_room_list({"_occupants_room": "Hall"})

    assert len(queries) == 1
    assert replies[-1][0] == "Hall"
    assert replies[-1][1] == "3456782"


def test_id_command_returns_cached_id_as_plain_number():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    replies = []
    bot.send_room_text = lambda room, text: replies.append((room, text))
    with patch.object(bot_module, "_stored_user_id", return_value="3456782"):
        assert bot._room_list_commands("Hall", "ايدي", "Ahmed", is_private=False)
    assert replies == [("Hall", "3456782")]


def test_id_command_is_routed_before_master_only_management_gate():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    calls = []
    bot._room_list_commands = lambda room, text, sender, is_private: calls.append(
        (room, text, sender, is_private)
    ) or True

    assert bot._handle_management_command("Hall", "ايدي", "RegularMember", is_private=False)
    assert calls == [("Hall", "ايدي", "RegularMember", False)]


def test_la_command_is_routed_before_master_only_management_gate():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    calls = []
    bot._room_list_commands = lambda room, text, sender, is_private: calls.append(
        (room, text, sender, is_private)
    ) or True

    assert bot._handle_management_command("Hall", "la@سوريانا", "RegularMember", is_private=False)
    assert calls == [("Hall", "la@سوريانا", "RegularMember", False)]


def test_shop_and_purchase_commands_pass_for_regular_members():
    import threading
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._room_list_commands = lambda *_args, **_kwargs: False
    bot._pending_named_commands = {}
    bot._pending_protection_number = {}
    bot._master_reply_local = threading.local()
    calls = []
    bot._handle_management_command_impl = lambda room, body, sender, is_private=False: calls.append(
        (room, body, sender, is_private)
    ) or True
    bot._remember_bot_action = lambda *_args, **_kwargs: None

    assert bot._handle_management_command("Hall", "store", "RegularMember", is_private=False)
    assert bot._handle_management_command("Hall", "sby 1", "RegularMember", is_private=False)
    assert [call[1] for call in calls] == ["store", "sby 1"]


def test_stored_user_id_looks_up_case_insensitively_across_rooms():
    with patch.object(bot_module, "_persistent_rosters", return_value={
        "version": 1,
        "rooms": {"hall": {"ahmed": {"username": "Ahmed", "user_id": "3456782"}}},
    }):
        assert bot_module._stored_user_id("@AHMED", "Hall") == "3456782"
