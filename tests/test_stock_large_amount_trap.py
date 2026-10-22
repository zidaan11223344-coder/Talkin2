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


def test_all_manual_assets_accept_30b_and_keep_their_amount():
    commands = (
        ("ذهب 30b", 1), ("gold 30b", 1),
        ("نفط 30b", 3), ("النفط 30b", 3), ("oil 30b", 3),
        ("أرض 30b", 4), ("الأرض 30b", 4), ("land 30b", 4),
    )
    for command, expected_asset in commands:
        bot = _market_bot()
        point_updates, messages = [], []
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
        assert row["amount"] == 30_000_000_000, command
        assert "trap" not in row, command
        assert point_updates[0][1] == -30_000_000_000, command
        assert any("تم قبول الاستثمار" in text and "ربح أو خسارة" in text for _, text in messages), command
        assert all("فخ" not in text for _, text in messages), command


def test_any_stock_asset_above_30b_is_rejected_without_debit():
    commands = ("ذهب 30.1b", "فضة 31b", "نفط 50b", "أرض 32b")
    for command in commands:
        bot = _market_bot()
        messages, debits = [], []
        bot.send_room_text = lambda room, text: messages.append((room, text))

        def apply_once(username, delta, transaction_id, reason, **_kwargs):
            debits.append(delta)
            return {"ok": True, "balance": 1_000_000_000_000}

        with patch.object(bot_module, "_is_verified_user", return_value=True), \
             patch.object(bot_module, "_games_enabled_for_room", return_value=True), \
             patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once), \
             patch.object(bot_module.time, "time", return_value=1000.0):
            assert bot.handle_game_command("Hall", command, "Player") is True, command

        assert not debits, command
        assert not bot.stock_investments, command
        assert any("30b" in text and "سقف" in text for _, text in messages), command


def test_oil_outcome_and_percentage_are_randomly_set_by_the_market():
    cases = (
        # stake, market outcome draw, market percentage draw, outcome, percent, payout
        (1_000, 0, 25, "profit", 25, 1_250),
        (10_000_000_000, 1, 70, "loss", 70, 3_000_000_000),
        (10_000_000_000, 1, 100, "loss", 100, 0),
    )
    for amount, outcome_draw, percent_draw, expected_outcome, expected_percent, expected_payout in cases:
        bot = _market_bot()
        bot.stock_investments = [{
            "id": f"oil-random-{amount}-{outcome_draw}-{percent_draw}",
            "event_id": 7, "username": "Player", "room": "Hall", "asset": 3,
            "amount": amount, "started_at": 100.0, "due_at": 900.0, "status": "active",
        }]
        histories, room_messages, private_messages, point_ops = [], [], [], []
        bot._record_stock_market_history = lambda row: histories.append(dict(row)) or True
        bot.send_room_text = lambda room, text: room_messages.append((room, text))
        bot.send_private_text = lambda user, text: private_messages.append((user, text))

        def apply_once(username, delta, transaction_id, reason, **_kwargs):
            point_ops.append((username, delta, transaction_id, reason))
            return {"ok": True, "balance": delta}

        with patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once), \
             patch.object(bot_module, "_get_points", return_value=0), \
             patch.object(bot_module, "_record_game", return_value=None), \
             patch.object(bot_module, "_save_local_json", return_value=None), \
             patch.object(bot_module, "STOCK_MARKET_ROOM_ANNOUNCEMENTS_ENABLED", True), \
             patch.object(bot_module.secrets, "randbelow", side_effect=[outcome_draw, percent_draw]) as random_draw:
            assert bot._process_stock_market_investments(now=1000.0) == 1, amount

        result = histories[0]
        assert result["outcome"] == expected_outcome, amount
        assert result["change_percent"] == expected_percent, amount
        assert result["payout"] == expected_payout, amount
        assert random_draw.call_count == 2
        assert not bot.stock_investments
        assert all("فخ" not in text for _, text in room_messages + private_messages)
        if expected_payout == 0:
            assert point_ops == []
        else:
            assert point_ops[0][1] == expected_payout
