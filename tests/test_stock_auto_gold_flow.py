import threading
from unittest.mock import patch

import bot as bot_module


def test_stock_command_warns_and_requires_confirmation_instead_of_old_choice_menu():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._stock_auto_gold_pending = {}
    bot._configured_room_language = lambda _room: "ar"
    messages = []
    bot.send_room_text = lambda room, text: messages.append((room, text))

    with patch.object(bot_module, "_is_verified_user", return_value=True), \
         patch.object(bot_module, "_games_enabled_for_room", return_value=True), \
         patch.object(bot_module, "_get_points", return_value=2_000_000_000), \
         patch.object(bot_module.time, "time", return_value=1000.0):
        assert bot.handle_game_command("Hall", "بورصة", "Player") is True

    key = (bot_module._norm_room("Hall"), bot_module._norm_user("Player"))
    assert bot._stock_auto_gold_pending[key]["amount"] == 1_000_000_000
    warning = messages[-1][1]
    assert "قد تخسر كامل المبلغ" in warning
    assert "بحد أقصى مليار" in warning
    assert "موافق" in warning
    assert "أرسل رقم الخيار" not in warning

    bot._stock_market_is_open = lambda: False
    bot._start_stock_market_round = lambda **_kwargs: {"id": 5}
    bot._stock_market_invest = lambda room, sender, asset, amount: messages.append((room, f"INVEST:{asset}:{amount}")) or True
    with patch.object(bot_module, "_is_verified_user", return_value=True), \
         patch.object(bot_module, "_games_enabled_for_room", return_value=True), \
         patch.object(bot_module, "_get_points", return_value=2_000_000_000), \
         patch.object(bot_module.time, "time", return_value=1010.0):
        assert bot.handle_game_command("Hall", "موافق", "Player") is True
    assert messages[-1][1] == "INVEST:1:1000000000"
    assert key not in bot._stock_auto_gold_pending
