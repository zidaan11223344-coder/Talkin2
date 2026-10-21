import threading
from collections import defaultdict
from unittest.mock import patch

import bot as bot_module


def test_wager_cooldown_is_two_minutes_and_independent_per_game():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.game_lock = threading.RLock()
    bot.game_cooldown = defaultdict(float)
    now = [1_000.0]
    with patch.object(bot_module.time, "time", lambda: now[0]):
        assert bot._game_ready("Player", "Hall", 120.0, "bet") == (True, 0)
        now[0] += 1
        ready, remaining = bot._game_ready("Player", "Hall", 120.0, "bet")
        assert not ready and remaining == 120
        assert bot._game_ready("Player", "Hall", 120.0, "duel") == (True, 0)


def test_wager_queue_uses_two_minutes_and_canonicalizes_aliases():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.game_lock = threading.RLock()
    bot.wager_waiting = {}
    bot._cleanup_expired_wagers = lambda: None
    calls = []
    bot._game_cooldown_notice = lambda room, user, cooldown, game: calls.append(
        (room, user, cooldown, game)
    ) or False
    assert bot._queue_wager("Hall", "Player", "مراهنة", 100) is True
    assert calls == [("Hall", "Player", 120.0, "bet")]
