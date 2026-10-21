import threading
from unittest.mock import patch

import bot as bot_module


def test_timed_game_cycle_starts_with_mining_and_has_all_nine_games():
    assert list(bot_module.TIMED_TREASURE_GAMES)[0] == "rare_diamond"
    assert len(bot_module.TIMED_TREASURE_GAMES) == 9
    assert bot_module.TIMED_TREASURE_GAME_ALIASES[bot_module._normalize_timed_treasure_command("تنقيب")] == "rare_diamond"
    assert bot_module.TIMED_TREASURE_GAME_ALIASES[bot_module._normalize_timed_treasure_command("ثروة")] == "fortune_hunt"
    assert bot_module.TIMED_TREASURE_GAME_ALIASES[bot_module._normalize_timed_treasure_command("امن")] == "mercenary_escape"
    assert bot_module.resolve_item_keys("♦️") == ("diamond_red",)
    assert bot_module.resolve_item_keys("💎") == ("diamond_clear",)
    assert bot_module.resolve_item_keys("💠") == ("diamond_purple",)
    assert bot_module.resolve_item_keys("◆") == ("diamond_black",)
    assert all("❤" not in item["icon"] for item in bot_module.MINING_ITEMS.values() if item.get("kind") == "diamond")
    assert all(bot_module.resolve_item_keys(item["icon"]) == (key,) for key, item in bot_module.MINING_ITEMS.items())


def test_doctor_loser_is_refused_once_for_next_doctor_round_without_joining():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._doctor_ban_lock = threading.RLock()
    bot._rare_diamond_lock = threading.RLock()
    bot._rare_diamond_event = {
        "id": "doctor-next",
        "game_key": "imperial_sickness",
        "rooms": ["Hall"],
        "required_players": 7,
        "ends_at": bot_module.time.time() + 120,
        "players": {},
        "doctor_banned_once": {bot_module._norm_user("Loser"): {"name": "Loser"}},
    }
    sent = []
    bot.send_room_text = lambda room, text: sent.append((room, text))
    bot._effective_room_language = lambda _room: "ar"

    assert bot._join_rare_diamond_event("Hall", "Loser", "imperial_sickness") is True
    assert not bot._rare_diamond_event["players"]
    assert bot._rare_diamond_event["doctor_banned_once"][bot_module._norm_user("Loser")]
    assert len(sent) == 1
    assert "هذه الجولة فقط" in sent[0][1]


def test_doctor_loser_is_not_blocked_from_other_timed_games():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._doctor_ban_lock = threading.RLock()
    bot._rare_diamond_lock = threading.RLock()
    bot._rare_diamond_event = {
        "id": "mining-next",
        "game_key": "rare_diamond",
        "rooms": ["Hall"],
        "required_players": 5,
        "ends_at": bot_module.time.time() + 120,
        "players": {},
        "doctor_banned_once": {bot_module._norm_user("Loser"): {"name": "Loser"}},
    }
    bot.send_room_text = lambda *_args: None
    bot._effective_room_language = lambda _room: "ar"

    assert bot._join_rare_diamond_event("Hall", "Loser", "rare_diamond") is True
    assert bot._rare_diamond_event["players"][bot_module._norm_user("Loser")]["name"] == "Loser"


def test_sf_toggle_is_room_scoped_for_owner_and_rejects_admin():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.room_users = {"Hall": {"Owner": "owner", "Admin": "admin"}}
    bot.send_room_text = lambda *_args: None
    bot.send_private_text = lambda *_args: None
    control = {"disabled_rooms": [], "global_enabled": True, "results_disabled_rooms": []}

    with patch.object(bot_module, "_is_primary_master", return_value=False), \
         patch.object(bot_module, "_is_room_creator", return_value=False), \
         patch.object(bot_module, "_game_control_data", return_value=control), \
         patch.object(bot_module, "_save_game_control") as save:
        assert bot._handle_management_command_impl("Hall", "sf@off", "Owner") is True
        assert control["results_disabled_rooms"] == ["Hall"]
        save.assert_called_once_with(control)

        save.reset_mock()
        assert bot._handle_management_command_impl("Hall", "sf@off", "Admin") is True
        assert control["results_disabled_rooms"] == ["Hall"]
        save.assert_not_called()


def test_each_of_the_nine_timed_games_opens_and_accepts_its_join_command():
    for game_key, config in bot_module.TIMED_TREASURE_GAMES.items():
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.connected_rooms = {"Hall"}
        bot._rare_diamond_lock = threading.RLock()
        bot._doctor_ban_lock = threading.RLock()
        bot._rare_diamond_event = None
        bot._rare_diamond_round_seq = 0
        bot._doctor_ban_once = {}
        bot.send_room_text = lambda *_args: None
        bot._effective_room_language = lambda _room: "ar"
        bot.stock_pending = {}
        bot._pending_bomb_targets = {}
        bot.ludo_games = {}
        bot.pending_bot_choices = {}
        bot._snake_command = lambda *_args: False
        bot._ludo_command = lambda *_args: False
        bot._handle_pending_bot_choice = lambda *_args: False
        bot._capture_room_response_language = lambda *_args: None
        bot._localized_room_worker = lambda _room, _language, worker: worker
        bot._remember_bot_action = lambda *_args, **_kwargs: None

        assert bot._start_rare_diamond_event(game_key) is True, game_key
        for command in (*config["aliases"], config["join_ar"], config["join_en"]):
            command_key = bot_module._normalize_timed_treasure_command(command)
            assert bot_module.TIMED_TREASURE_GAME_ALIASES[command_key] == game_key, (game_key, command)
            assert bot_module._looks_like_bot_command(command), (game_key, command)

        class InlineThread:
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        with patch.object(bot_module, "_is_verified_user", return_value=True), \
             patch.object(bot_module, "_games_enabled_for_room", return_value=True), \
             patch.object(bot_module.threading, "Thread", InlineThread):
            assert bot._run_game_command_async("Hall", config["join_ar"], "Tester") is True, game_key
        assert bot._rare_diamond_event["game_key"] == game_key
        assert bot._rare_diamond_event["players"][bot_module._norm_user("Tester")]["name"] == "Tester"
