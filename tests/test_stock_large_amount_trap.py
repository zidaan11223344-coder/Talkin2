import threading
from unittest.mock import patch

import bot as bot_module


def _market_bot():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._stock_market_lock = threading.RLock()
    bot.stock_market_round = {"id": 7, "started_at": 900.0, "ends_at": 2000.0}
    bot._stock_market_seen = set()
    bot._stock_market_user_cooldowns = {}
    bot.stock_investments = []
    bot.stock_market_history = []
    bot.stock_pending = {}
    bot._pending_bomb_targets = {}
    bot.ludo_games = {}
    bot.pending_bot_choices = {}
    bot._snake_command = lambda *_args: False
    bot._ludo_command = lambda *_args: False
    bot._handle_pending_bot_choice = lambda *_args: False
    bot._save_stock_investments = lambda: None
    bot._configured_room_language = lambda _room: "ar"
    bot.send_room_text = lambda *_args: None
    bot.send_private_text = lambda *_args: None
    bot.log = lambda *_args: None
    return bot


def test_oil_and_land_billion_suffix_orders_are_accepted_and_debited():
    commands = (
        ("نفط 30b", 3, 30_000_000_000), ("النفط 30b", 3, 30_000_000_000),
        ("oil 30b", 3, 30_000_000_000), ("نفط 50b", 3, 50_000_000_000),
        ("أرض 30b", 4, 30_000_000_000), ("الأرض 30b", 4, 30_000_000_000),
        ("land 30b", 4, 30_000_000_000),
    )
    for command, expected_asset, expected_amount in commands:
        bot = _market_bot()
        point_updates = []
        messages = []
        bot.send_room_text = lambda room, text: messages.append((room, text))

        def apply_once(username, delta, transaction_id, reason, **_kwargs):
            point_updates.append((username, delta, transaction_id, reason))
            return {"ok": True, "balance": 0}

        with patch.object(bot_module, "_is_verified_user", return_value=True), \
             patch.object(bot_module, "_games_enabled_for_room", return_value=True), \
             patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once), \
             patch.object(bot_module.time, "time", return_value=1000.0):
            assert bot.handle_game_command("Hall", command, "Player") is True, command

        assert len(bot.stock_investments) == 1, command
        row = bot.stock_investments[0]
        assert row["asset"] == expected_asset, command
        assert row["amount"] == expected_amount, command
        assert row["trap"] is (expected_asset == 3), command
        assert point_updates[0][1] == -expected_amount, command
        assert any("تم قبول الاستثمار" in text for _room, text in messages), command
        if expected_asset == 3:
            assert any("100%" in text and "فخ" in text for _room, text in messages), command


def test_oil_50b_is_a_persisted_trap_with_a_full_loss_message():
    bot = _market_bot()
    amount = 50_000_000_000
    saved_history = []
    bot._record_stock_market_history = lambda row: saved_history.append(dict(row)) or True
    room_messages, private_messages, point_updates = [], [], []
    bot.send_room_text = lambda room, text: room_messages.append((room, text))
    bot.send_private_text = lambda user, text: private_messages.append((user, text))

    def apply_once(username, delta, transaction_id, reason, **_kwargs):
        point_updates.append((username, delta, transaction_id, reason))
        return {"ok": True, "balance": max(0, int(delta))}

    with patch.object(bot_module, "_is_verified_user", return_value=True), \
         patch.object(bot_module, "_games_enabled_for_room", return_value=True), \
         patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once), \
         patch.object(bot_module.time, "time", return_value=1000.0):
        assert bot.handle_game_command("Hall", "نفط 50b", "Player") is True
    assert len(bot.stock_investments) == 1
    assert bot.stock_investments[0]["amount"] == amount
    assert bot.stock_investments[0]["trap"] is True
    bot.stock_investments[0]["due_at"] = 900.0

    with patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once), \
         patch.object(bot_module, "_record_game", return_value=None), \
         patch.object(bot_module, "_save_local_json", return_value=None), \
         patch.object(bot_module, "_get_points", return_value=0), \
         patch.object(bot_module, "STOCK_MARKET_ROOM_ANNOUNCEMENTS_ENABLED", True), \
         patch.object(bot_module.secrets, "randbelow", side_effect=AssertionError("trap must be deterministic")):
        assert bot._process_stock_market_investments(now=1000.0) == 1

    assert saved_history[0]["outcome"] == "loss"
    assert saved_history[0]["change_percent"] == 100
    assert saved_history[0]["change"] == amount
    assert saved_history[0]["payout"] == 0
    assert len(point_updates) == 1
    assert point_updates[0][0] == "Player"
    assert point_updates[0][1] == -amount
    assert not bot.stock_investments
    result_room_messages = [text for _room, text in room_messages if "نتيجة البورصة" in text]
    assert len(result_room_messages) == 1
    assert "وقعت بالفخ" in result_room_messages[0]
    assert "100%" in result_room_messages[0]
    assert len(private_messages) == 1
    assert "وقعت بالفخ" in private_messages[0][1]
    assert "100%" in private_messages[0][1]


def test_oil_stakes_of_any_size_always_settle_as_a_full_loss():
    for amount in (10, 1_000_000, 30_000_000_000):
        bot = _market_bot()
        bot.stock_investments = [{
            "id": f"oil-trap-{amount}", "event_id": 7, "username": "Player", "room": "Hall",
            "asset": 3, "amount": amount, "started_at": 100.0, "due_at": 900.0,
            "status": "active", "trap": True,
        }]
        histories, room_messages, private_messages = [], [], []
        bot._record_stock_market_history = lambda row: histories.append(dict(row)) or True
        bot.send_room_text = lambda room, text: room_messages.append((room, text))
        bot.send_private_text = lambda user, text: private_messages.append((user, text))

        with patch.object(bot_module, "_get_points", return_value=0), \
             patch.object(bot_module, "_record_game", return_value=None), \
             patch.object(bot_module, "_save_local_json", return_value=None), \
             patch.object(bot_module, "STOCK_MARKET_ROOM_ANNOUNCEMENTS_ENABLED", True), \
             patch.object(bot_module.secrets, "randbelow", side_effect=AssertionError("oil must never profit")):
            assert bot._process_stock_market_investments(now=1000.0) == 1, amount

        result = histories[0]
        assert result["outcome"] == "loss", amount
        assert result["change_percent"] == 100, amount
        assert result["change"] == amount, amount
        assert result["payout"] == 0, amount
        assert not bot.stock_investments, amount
        assert "وقعت بالفخ" in room_messages[0][1], amount
        assert "وقعت بالفخ" in private_messages[0][1], amount
