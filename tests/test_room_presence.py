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
        assert bot._complete_pending_room_list({"_occupants_room": "Hall"})

        assert bot._room_list_commands("Source", "la@Hall", "Player", is_private=True)
        private_pending = bot._pending_room_lists[bot_module._norm_room("Hall")]
        assert private_pending["private_response"] is True
        assert bot._complete_pending_room_list({"_occupants_room": "Hall"})

    assert len(queries) == 2
    assert len(public_results) == 1
    assert public_results[0][0] == "Hall"
    assert [row["username"] for row in public_results[0][2]] == ["Alice", "Bob"]
    assert len(private_results) == 1
    assert [row["username"] for row in private_results[0][2]] == ["Alice", "Bob"]


def test_new_commands_are_classified_before_verification_gate():
    assert bot_module._looks_like_bot_command("la@Hall")
    assert bot_module._looks_like_bot_command("sby 1")
    assert bot_module._looks_like_bot_command("store")
    assert bot_module._looks_like_bot_command("متجر")
