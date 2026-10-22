from __future__ import annotations

import os
import json
import subprocess
import tempfile
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import bot as bot_module
from cricket_game import CricketGame
from cricket_integration import CricketIntegration
from cricket_result import render_result_image


class ProfileStatusRegressions(unittest.TestCase):
    def test_requested_default_profile_status_is_sent_whole_under_ws_limit(self):
        expected = (
            '<B><H2><p style="background-color:#FFFFFF;">\n'
            '<font color=#8B6508>☕️ COFFEE BOT</font><br>\n'
            '<font color=#007C91>🛡️ بوت حماية وألعاب وأغاني</font><br>\n'
            '<font color=#247A00>🛡️ Protection, Games & Music Bot</font><br>\n'
            '<font color=#A9005B>🎮 الألعاب والأوامر: a1 • a2 • a3 • a4 • a5 • a6</font><br>\n'
            '<font color=#71368A>🎮 GAMES & COMMANDS: a1 • a2 • a3 • a4 • a5 • a6</font><br>\n'
            '<font color=#B05A00>🚪 دخول@اسم الغرفة</font><br>\n'
            '<font color=#8B3A00>🌐 اختر اللغة: 1 أو 2</font><br>\n'
            '<font color=#007A45>🚪 join@room</font><br>\n'
            '<font color=#005C4B>🌐 Choose language: 1 or 2</font><br>\n'
            '<font color=#8B0000>♟️ MASTER:</font><br>\n'
            '<font color=#8B0000>∫♚∫اݪـــۛــ⃮ـۿــ𓏺𓏺ـيّـــّٰـبــۃ∫♚∫</font>\n'
            '</p></H2></B>'
        )
        self.assertEqual(bot_module.BOT_BASE_STATUS, expected)
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []
        bot.send_query = lambda payload: sent.append(payload)
        bot.log = lambda *_args: None
        self.assertTrue(bot._set_profile_status(bot_module.BOT_BASE_STATUS))
        self.assertEqual(len(sent), 1)
        self.assertLessEqual(len(sent[0]), bot_module._ws_payload_limit())
        fields = bot_module.decode_message(sent[0])
        self.assertEqual(bot_module.as_text(fields[11][0]), expected)
        self.assertNotIn(5, fields)


class IncomingEventDedupRegressions(unittest.TestCase):
    def test_english_game_catalogs_and_protection_menu_are_localized(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_languages = {bot_module._norm_room("EnglishRoom"): "en"}
        sent = []
        bot._send_text_packets = lambda packet, text, **kwargs: sent.append(text) or True
        bot._send_help_chunks = lambda packet, text, **kwargs: sent.append(text) or True

        for page, count in ((1, 6), (2, 2), (3, 6), (4, 2), (5, 2), (6, 2)):
            for part in range(1, count + 1):
                bot._send_help_section(room="EnglishRoom", page=page, part=part)
        self.assertTrue(any("First token to the finish wins" in text for text in sent))
        self.assertTrue(any("protection@room" in text.lower() for text in sent))
        self.assertFalse(any(any("\u0600" <= char <= "\u06ff" for char in text) for text in sent))

        arabic_menu = (
            "🛡️ قائمة حماية الغرفة\n━━━━━━━━━━━━\n"
            "1️⃣ تشغيل حماية الغرفة من السب\n2️⃣ إيقاف حماية الغرفة من السب\n"
            "3️⃣ تشغيل حماية الفلود (هجوم الدخول المتزامن + حظر IP)\n4️⃣ إيقاف حماية الفلود\n"
            "5️⃣ تشغيل حماية الدخول والخروج (تكرار الدخول)\n6️⃣ إيقاف حماية الدخول والخروج\n"
            "7️⃣ تعيين حد رسائل الفلود\n8️⃣ تشغيل حظر الحسابات بلا صورة\n"
            "9️⃣ إيقاف حظر الحسابات بلا صورة\n━━━━━━━━━━━━\n📌 أرسل رقم الخيار الآن."
        )
        translated = bot._localize_room_text("EnglishRoom", arabic_menu)
        self.assertIn("Room protection settings", translated)
        self.assertNotIn("حماية", translated)

    def test_ludo_dynamic_results_are_english_only_for_english_rooms(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_languages = {bot_module._norm_room("EnglishRoom"): "en"}
        english = bot._localize_room_text(
            "EnglishRoom", "🎲 لودو: اختر عدد اللاعبين\n1 مع البوت\n2 لاعبين\n3 لاعبين\n4 لاعبين"
        )
        self.assertIn("How to play", english)
        self.assertIn("type rool", english)
        result = bot._localize_room_text("EnglishRoom", "🎯 الآن دور @player1، اكتب rool.")
        self.assertEqual(result, "🎯 @player1, it is your turn — type rool to roll.")
        arabic_bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        arabic_bot.room_languages = {bot_module._norm_room("ArabicRoom"): "ar"}
        original = "🎯 الآن دور @player1، اكتب rool."
        self.assertEqual(arabic_bot._localize_room_text("ArabicRoom", original), original)

        game_bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        game_bot._ludo_lock = threading.RLock()
        game_bot.ludo_games = {}
        game_bot.room_languages = {bot_module._norm_room("EnglishRoom"): "en"}
        game_bot._board_game_cooldown_notice = lambda *_args, **_kwargs: True
        game_bot._schedule_board_game_timeout = lambda *_args, **_kwargs: None
        sent = []
        game_bot.send_room_text = lambda room, text: sent.append(text)
        self.assertTrue(game_bot._ludo_command_unlocked("EnglishRoom", "player1", "لودو"))
        self.assertEqual(game_bot.ludo_games["ludo:EnglishRoom"]["lang"], "en")
        self.assertIn("First token to the finish wins", sent[0])

    def test_common_game_result_templates_translate_to_english(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_languages = {bot_module._norm_room("EnglishRoom"): "en"}
        coin = "🪙 لعبة العملة\n━━━━━━━━━━━━━━\n@player\n🎯 اختيارك: وجه\n🪙 النتيجة: كتابة\n🏆 فزت!\n🎁 +1,000 نقطة\n💰 رصيدك: 1,000"
        translated = bot._localize_room_text("EnglishRoom", coin)
        self.assertIn("Coin toss", translated)
        self.assertIn("Heads", translated)
        self.assertIn("Tails", translated)
        self.assertFalse(any("\u0600" <= char <= "\u06ff" for char in translated))

    def test_snake_and_social_games_follow_the_room_language(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_languages = {bot_module._norm_room("EnglishRoom"): "en"}
        bot.snake_games = {}
        bot._board_game_cooldown_notice = lambda *_args, **_kwargs: True
        bot._schedule_board_game_timeout = lambda *_args, **_kwargs: None
        bot._send_game_cover = lambda *_args, **_kwargs: None
        starts = []
        bot._broadcast_game_start = lambda text, _game: starts.append(text)
        self.assertTrue(bot._snake_command("EnglishRoom", "player1", "ثعبان"))
        self.assertEqual(bot.snake_games["snake:EnglishRoom"]["lang"], "en")
        self.assertIn("Snake & Ladders started", starts[0])

        bot.room_users = {"EnglishRoom": {"player1": "member", "player2": "member"}}
        messages = []
        bot.send_room_text = lambda room, text: messages.append(text)
        with patch.object(bot_module.secrets, "choice", return_value="player2"), patch.object(
            bot_module.secrets, "randbelow", return_value=78
        ):
            self.assertTrue(bot._social_pair_game("EnglishRoom", "player1", "حبك"))
        self.assertIn("compatibility: 78%", messages[0])
        self.assertFalse(any("\u0600" <= char <= "\u06ff" for char in messages[0]))

    def test_distinct_joining_users_are_not_deduplicated(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        first_join = ("user_joined", "North", "", "", "", "", "account_a", "")
        second_join = ("user_joined", "North", "", "", "", "", "account_b", "")
        self.assertFalse(bot._is_duplicate_incoming("room", first_join))
        self.assertFalse(bot._is_duplicate_incoming("room", second_join))
        self.assertTrue(bot._is_duplicate_incoming("room", second_join))

    def test_reconnect_notice_sends_reason_to_master_and_telegram_without_secrets(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = "North"
        bot._telegram_chat_id = "98765"
        private = []
        logs = []
        bot.send_private_text = lambda username, text: private.append((username, text)) or True
        bot.log = lambda *args: logs.append(args)
        telegram = []
        bot._telegram_api = lambda method, **payload: telegram.append((method, payload)) or {"ok": True}

        with patch.object(bot_module, "BOT_MASTER", "Master"), patch.object(
            bot_module, "BOT_ID", "TalkinBot"
        ), patch.object(bot_module, "TELEGRAM_BOT_TOKEN", "telegram-token-test"):
            bot._send_reconnect_notice("ConnectionResetError: password=hunter2; socket closed")

        self.assertEqual(private[0][0], "Master")
        self.assertIn("ConnectionResetError", private[0][1])
        self.assertNotIn("hunter2", private[0][1])
        self.assertEqual(telegram[0][0], "sendMessage")
        self.assertEqual(telegram[0][1]["chat_id"], "98765")
        self.assertNotIn("hunter2", telegram[0][1]["text"])

    def test_fast_join_pair_bans_both_and_keeps_banning_later_joins(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {"North": {"alpha": "member", "beta": "member", "gamma": "member"}}
        with patch.object(bot_module, "_is_master_name", return_value=False), patch.object(
            bot_module, "_is_room_creator", return_value=False
        ):
            self.assertEqual(bot_module._join_flood_candidates(bot, "North", "alpha", now=100.0), [])
            early = bot_module._join_flood_candidates(bot, "North", "beta", now=100.5)
            self.assertEqual(set(early), {"alpha", "beta"})
            bot._join_flood_banned[bot_module._norm_room("North")].update(
                bot_module._norm_user(name) for name in early
            )
            self.assertEqual(
                bot_module._join_flood_candidates(bot, "North", "gamma", now=101.0),
                ["gamma"],
            )

    def test_steal_and_marriage_candidates_are_scoped_to_the_live_room_roster(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {
            "North": {"sender": "member", "north_user": "member", "banned_user": "outcast"},
            "South": {"south_user": "member"},
        }
        with patch.object(bot_module, "_is_master_name", return_value=False):
            self.assertEqual(
                bot._room_member_usernames_for_steal(" north ", "sender"),
                ["north_user"],
            )
        self.assertEqual(bot._fun_room_members("NORTH", "sender"), ["north_user"])

    def test_failed_steal_sends_failure_card_not_success_card(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent_text, cards = [], []
        bot._game_cooldown_notice = lambda *_args: True
        bot._room_member_usernames_for_steal = lambda *_args: ["victim"]
        bot._steal_protected = lambda *_args: False
        bot.send_room_text = lambda room, text: sent_text.append((room, text))
        bot._send_game_winner_card = lambda key, winner, rooms: cards.append((key, winner, rooms))
        with patch.object(bot_module, "_get_points", return_value=1000), patch.object(
            bot_module, "_record_game"
        ), patch.object(bot_module.secrets, "randbelow", return_value=95):
            self.assertTrue(bot._steal_game("North", "thief"))
        self.assertTrue(any("لم تتم السرقة" in text for _room, text in sent_text))
        self.assertEqual(cards, [("اسرق_فشل", "thief", ["North"])])

    def test_steal_failure_sends_original_art_without_winner_overlay(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []
        bot.log = lambda *_args: None
        bot._game_public_image = lambda path, route="games": f"https://media.test/{route}/{path.name}"
        bot._verify_public_media_url = lambda *_args: None
        bot.send_room_media = lambda *args: sent.append(args)
        with patch.object(bot_module, "_public_base_url", return_value="https://media.test"), patch.object(
            bot_module, "render_game_winner_card"
        ) as render:
            self.assertTrue(bot._send_game_winner_card("اسرق_فشل", "thief", ["North"]))
        render.assert_not_called()
        self.assertEqual(sent, [("North", "https://media.test/assets/game_steal_failure.jpg", "image")])

    def test_social_pair_game_uses_only_live_members_in_the_same_room(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {
            "North": {"sender": "member", "north_user": "member"},
            "South": {"south_user": "member"},
        }
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        with patch.object(bot_module.secrets, "choice", return_value="north_user"), patch.object(
            bot_module.secrets, "randbelow", return_value=73
        ):
            self.assertTrue(bot._social_pair_game("North", "sender", "حبك"))
        self.assertIn("@north_user", sent[0][1])
        self.assertIn("73%", sent[0][1])
        self.assertNotIn("south_user", sent[0][1])

    def test_departure_replies_are_separate_from_existing_auto_replies(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.departure_replies = {}
        bot.departure_replies_file = Path("departure_replies.json")
        bot.auto_replies = {"hello": {"trigger": "hello", "replies": ["legacy"]}}
        private, saved = [], []
        bot.send_private_text = lambda user, text: private.append((user, text))
        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_save_local_json", side_effect=lambda path, value: saved.append((Path(path).name, value))
        ):
            self.assertTrue(bot._handle_management_command_impl("", "+ds@ق@بقلبي", "Master", is_private=True))
        self.assertEqual(bot.departure_replies, {"ق": ["بقلبي"]})
        self.assertEqual(bot.auto_replies["hello"]["replies"], ["legacy"])
        self.assertEqual(saved[0][0], "departure_replies.json")
        self.assertEqual(saved[0][1], {"farewell_enabled": True, "replies": {"ق": ["بقلبي"]}})
        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_save_local_json", side_effect=lambda path, value: saved.append((Path(path).name, value))
        ):
            self.assertTrue(bot._handle_management_command_impl("", "+ds@س@سلام", "Master", is_private=True))
        self.assertEqual(bot.departure_replies["س"], ["سلام"])

    def test_departure_command_uses_last_user_and_dedicated_reply(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._last_departed_user_by_room = {bot_module._norm_room("North"): "left_user"}
        bot.departure_replies = {"ق": ["بقلبي"]}
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        self.assertTrue(bot._handle_departure_reply_command("North", "ق"))
        self.assertIn("left_user", sent[0][1])
        self.assertIn("بقلبي", sent[0][1])
    def test_departure_command_accepts_any_single_character_key(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._last_departed_user_by_room = {bot_module._norm_room("North"): "left_user"}
        bot.departure_replies = {"س": ["سلام يا {username}"]}
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        self.assertTrue(bot._handle_departure_reply_command("North", "س"))
        self.assertIn("سلام يا left_user", sent[0][1])


class CommandLanguageAndReconnectRegressions(unittest.TestCase):
    def test_room_reply_language_follows_saved_room_setting_for_all_commands(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_languages = {
            bot_module._norm_room("ArabicRoom"): "ar",
            bot_module._norm_room("EnglishRoom"): "en",
        }
        bot._english_room_exact_translations = {"رد عربي": "English reply"}
        observed = []

        def inspect_language(result):
            event = result["room_event"]
            room = event[13]
            observed.append((bot._effective_room_language(room),
                             bot._localize_room_text(room, "رد عربي")))

        bot._handle_room_event_impl = inspect_language
        bot.handle_room_event({"room_event": {1: "text", 2: "Alice", 6: "help", 13: "ArabicRoom"}})
        bot.handle_room_event({"room_event": {1: "text", 2: "Bob", 6: "مساعدة", 13: "EnglishRoom"}})

        self.assertEqual(observed, [("ar", "رد عربي"), ("en", "English reply")])
        self.assertEqual(bot._effective_room_language("ArabicRoom"), "ar")
        self.assertEqual(bot._effective_room_language("EnglishRoom"), "en")

    def test_numeric_game_choice_uses_the_saved_room_language(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_languages = {bot_module._norm_room("Hall"): "ar"}
        observed = []
        bot._handle_room_event_impl = lambda result: observed.append(
            bot._effective_room_language(result["room_event"][13])
        )
        bot.handle_room_event({"room_event": {1: "text", 2: "Alice", 6: "ludo", 13: "Hall"}})
        bot.handle_room_event({"room_event": {1: "text", 2: "Alice", 6: "1", 13: "Hall"}})
        self.assertEqual(observed, ["ar", "ar"])

    def test_auto_rejoin_sends_one_join_then_waits_for_server_ack(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.connected_rooms = set()
        bot._pending_room_joins = {}
        bot._intentional_leaves = set()
        bot.blocked_rooms = set()
        bot._auto_rejoin_lock = threading.Lock()
        bot._auto_rejoin_pending = set()
        bot._auto_rejoin_waiting_ack = set()
        bot._auto_rejoin_state = {}
        bot._connection_generation = 1
        bot._room_bulk_lock = threading.RLock()
        bot.log = lambda *_args: None
        attempts = []
        delays = []
        bot.join_room = lambda room, **kwargs: attempts.append((room, kwargs)) or True

        class ImmediateThread:
            def __init__(self, target=None, **_kwargs):
                self.target = target
            def start(self):
                self.target()

        with patch.object(bot_module.threading, "Thread", ImmediateThread), patch.object(
            bot_module.time, "sleep", lambda delay: delays.append(delay)
        ):
            for _ in range(12):
                bot._schedule_auto_rejoin("Hall", delay=0)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(delays), 1)
        self.assertLessEqual(delays[0], 15.0)
        self.assertEqual(bot._auto_rejoin_waiting_ack, {"Hall"})
        state = next(iter(bot._auto_rejoin_state.values()))
        self.assertEqual(len(state["attempts"]), 1)

    def test_auto_rejoin_timeout_does_not_resend_join(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._pending_room_joins = {"hall": {"room": "Hall", "requested_by": ""}}
        bot._auto_rejoin_waiting_ack = {"hall"}
        bot.connected_rooms = set()
        bot.known_rooms = {"Hall"}
        bot.blocked_rooms = set()
        bot.log = lambda *_args: None
        bot._schedule_auto_rejoin = lambda *_args, **_kwargs: self.fail("timeout must not resend room_join")
        with patch.object(bot_module, "_save_persistent_rooms"):
            bot._join_timeout("hall")
        self.assertEqual(bot._auto_rejoin_waiting_ack, {"hall"})
        self.assertEqual(bot.known_rooms, {"Hall"})

    def test_server_join_ack_clears_one_request_wait_state(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.connected_rooms = set()
        bot.known_rooms = set()
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot._blocked_room_reasons = {}
        bot._auto_rejoin_pending = set()
        bot._auto_rejoin_waiting_ack = {"Hall"}
        bot._auto_rejoin_lock = threading.Lock()
        bot._auto_rejoin_state = {"Hall": {"attempts": [1.0], "joined_at": 0.0}}
        bot._pending_room_joins = {}
        bot.room_users = {}
        bot._master_online_rooms = set()
        bot._room_entry_times = {}
        bot._room_entry_users = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        bot.request_room_occupants = lambda *_args, **_kwargs: True
        bot.send_room_text = lambda *_args, **_kwargs: True
        bot.log = lambda *_args: None
        with patch.object(bot_module, "_save_persistent_rooms"):
            bot._handle_room_event_impl({"room_event": {1: "you_joined", 13: "Hall"}})
        self.assertIn("Hall", bot.connected_rooms)
        self.assertEqual(bot._auto_rejoin_waiting_ack, set())

    def test_new_socket_clears_stale_room_join_acknowledgements(self):
        class Timer:
            cancelled = False
            def cancel(self):
                self.cancelled = True

        timer = Timer()
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.connected_rooms = {"Hall"}
        bot._pending_room_joins = {"hall": {"timer": timer}}
        bot._auto_rejoin_pending = {"hall"}
        bot._auto_rejoin_waiting_ack = {"hall"}
        bot._auto_rejoin_lock = threading.Lock()
        bot._reset_room_connection_state()
        self.assertEqual(bot.connected_rooms, set())
        self.assertEqual(bot._pending_room_joins, {})
        self.assertEqual(bot._auto_rejoin_pending, set())
        self.assertEqual(bot._auto_rejoin_waiting_ack, set())
        self.assertTrue(timer.cancelled)


class ProtectionAuthorizationRegressions(unittest.TestCase):
    def test_legacy_protection_flags_are_disabled_without_authorization_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protection = root / "room_protection.json"
            moderation = root / "moderation.json"
            mf = root / "mf.json"
            protection.write_text(json.dumps({"rooms": {"Hall": {
                "swear": True, "flood": True, "joinleave": True, "no_photo": True,
                "repeat_limit": 11,
            }}}), encoding="utf-8")
            moderation.write_text(json.dumps({"rooms": {"Hall": {"enabled": True}} ,
                                               "bot_protection_enabled": True}), encoding="utf-8")
            mf.write_text(json.dumps({"enabled": True, "words": ["bad"]}), encoding="utf-8")
            with patch.object(bot_module, "PROTECTION_FILE", protection), patch.object(
                bot_module, "MODERATION_FILE", moderation
            ), patch.object(bot_module, "MF_FILE", mf):
                self.assertEqual(
                    bot_module._room_protection_cfg("Hall"),
                    {"swear": False, "flood": False, "joinleave": False,
                     "no_photo": False, "repeat_limit": 11},
                )
                self.assertFalse(bot_module._room_moderation_config("Hall")["enabled"])
                self.assertFalse(bot_module._bot_protection_enabled())
                self.assertFalse(bot_module._load_moderation_config()[0])


class RuntimeCleanupRegressions(unittest.TestCase):
    def test_cleanup_worker_runs_once_then_waits_one_hour(self):
        class StopAfterWait:
            def __init__(self):
                self.waited = []

            def is_set(self):
                return False

            def wait(self, seconds):
                self.waited.append(seconds)
                return True

        stop = StopAfterWait()
        with patch.object(bot_module, "CLEANUP_INTERVAL_SECONDS", 3600), patch.object(
            bot_module, "_cleanup_runtime_files"
        ) as cleanup:
            bot_module._runtime_cleanup_worker(stop_event=stop)
        cleanup.assert_called_once_with(bot=None)
        self.assertEqual(stop.waited, [3600])

    def test_cleanup_removes_old_generated_files_but_preserves_persistent_json(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            data_dir = base / "bot_data"
            generated = base / "generated_music"
            data_dir.mkdir()
            generated.mkdir()
            state = data_dir / "member_state.json"
            state.write_text('{"balance": 12}', encoding="utf-8")
            temporary = generated / "old_track.mp3"
            temporary.write_bytes(b"old")
            old = time.time() - 7200
            os.utime(temporary, (old, old))
            with patch.object(bot_module, "BASE_DIR", base), patch.object(
                bot_module, "DATA_DIR", data_dir
            ), patch.object(bot_module, "CLEANUP_MAX_AGE_SECONDS", 3600), patch.object(
                bot_module, "CLEANUP_GENERATED_ENABLED", True
            ), patch.object(bot_module, "CLEANUP_AUDIO_ENABLED", False), patch.object(
                bot_module, "CLEANUP_CACHE_ENABLED", False
            ), patch.object(bot_module, "CLEANUP_TMP_ENABLED", False), patch.object(
                bot_module, "CLEANUP_LOG_ENABLED", False
            ):
                result = bot_module._cleanup_runtime_files()
            self.assertFalse(temporary.exists())
            self.assertTrue(state.exists())
            self.assertEqual(result["files"], 1)


class RoomExclusionRegressions(unittest.TestCase):
    def test_unauthorized_room_is_persisted_skipped_and_only_manual_join_clears_it(self):
        class NoOpTimer:
            def __init__(self, *_args, **_kwargs):
                self.daemon = True
            def start(self):
                pass
            def cancel(self):
                pass

        with tempfile.TemporaryDirectory() as temp:
            blocked_file = Path(temp) / "blocked_rooms.json"
            bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
            bot.room = "Forbidden"
            bot.known_rooms = {"Forbidden", "Other"}
            bot.connected_rooms = {"Forbidden", "Other"}
            bot.room_users = {"Forbidden": {"Member": "member"}}
            bot.blocked_rooms = set()
            bot._blocked_room_reasons = {}
            bot.log = lambda *_args: None
            saved_room_lists = []

            with patch.object(bot_module, "BLOCKED_ROOMS_FILE", blocked_file), patch.object(
                bot_module, "_save_persistent_rooms",
                side_effect=lambda rooms: saved_room_lists.append(set(rooms)),
            ):
                bot._mark_room_blocked("Forbidden", "🚫 محظور", persistent=True)
                self.assertEqual(bot_module._persistent_blocked_rooms(), ["Forbidden"])
                self.assertEqual(bot.known_rooms, {"Other"})
                self.assertEqual(bot._active_rooms(), ["Other"])

                # Simulate a process restart with a stale tracked list: the
                # persisted denied-room file still suppresses automatic joins.
                restored = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
                restored.room = "Forbidden"
                restored.known_rooms = {"Forbidden", "Other"}
                restored.connected_rooms = {"Forbidden"}
                restored.room_users = {}
                restored.blocked_rooms = set(bot_module._persistent_blocked_rooms())
                restored._blocked_room_reasons = {}
                restored._blocked_room_notices = set()
                restored._pending_room_joins = {}
                restored._last_join_sent = {}
                restored._join_lock = threading.Lock()
                restored.log = lambda *_args: None
                sent_queries = []
                restored.send_query = lambda payload: sent_queries.append(payload)
                restored._save_blocked_rooms = lambda: bot_module._save_persistent_blocked_rooms(
                    restored.blocked_rooms
                )

                with patch.object(bot_module.threading, "Timer", NoOpTimer):
                    self.assertFalse(restored.join_room("Forbidden"))
                    self.assertEqual(sent_queries, [])
                    self.assertEqual(restored._active_rooms(), ["Other"])
                    self.assertTrue(restored.join_room("Forbidden", requested_by="Master"))

                self.assertEqual(len(sent_queries), 1)
                self.assertNotIn("Forbidden", restored.blocked_rooms)
                self.assertEqual(bot_module._persistent_blocked_rooms(), [])
                self.assertTrue(saved_room_lists)

    def test_room_list_import_does_not_restore_a_blocked_room(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.blocked_rooms = {"Forbidden"}
        bot.known_rooms = set()
        bot.log = lambda *_args: None
        with patch.object(bot_module, "_save_persistent_rooms"):
            bot._process_room_list([{"name": "Forbidden"}, {"name": "Other"}])
        self.assertEqual(bot.known_rooms, {"Other"})

    def test_manual_join_reports_a_room_already_listed_as_connected(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.connected_rooms = {"RoomA"}
        bot._pending_room_joins = {}
        bot._room_bulk_lock = threading.RLock()
        bot.log = lambda *_args: None
        calls = []

        def join(room, force=False, requested_by=""):
            calls.append(("join", room, force, requested_by))
            return True

        bot.join_room = join
        bot.send_private_text = lambda *_args: None
        with patch.object(bot_module.time, "sleep"):
            result = bot._join_rooms_serially(["RoomA"], sender="Master")
        self.assertEqual(result, {"sent": 0, "skipped": 1})
        self.assertEqual(calls, [])

    def test_occupants_response_alone_does_not_mark_room_connected(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.invite_room = "RemoteRoom"
        bot.last_joined_room = ""
        bot.room = ""
        bot.connected_rooms = set()
        bot.bot_room_roles = {}
        bot.room_users = {}
        bot.invite_pending = False
        bot._users_from_room_admin = lambda *_args: []
        bot.process_occupants_for_invite({"_occupants_room": "RemoteRoom", "room_admin": {}})
        self.assertEqual(bot.connected_rooms, set())


class RawWebSocketTransportRegressions(unittest.TestCase):
    def test_socket_closed_is_classified_as_quiet_reconnect(self):
        self.assertTrue(bot_module._is_normal_ws_close_reason("socket closed"))
        self.assertTrue(bot_module._is_normal_ws_close_reason("WebSocket closed by server"))
        self.assertTrue(bot_module._is_normal_ws_close_reason("close code': 1000"))
        self.assertFalse(bot_module._is_normal_ws_close_reason("TLS handshake failed"))

    def test_reconnect_notice_suppresses_socket_closed(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.log = lambda *_args: None
        self.assertFalse(bot._send_reconnect_notice("socket closed"))

    def test_recv_drops_inbound_payload_over_configured_inbound_limit_without_closing_socket(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
                self.sent = []
            def recv(self, _size):
                chunk, self.payload = self.payload, b""
                return chunk
            def sendall(self, payload):
                self.sent.append(payload)

        oversized = b"x" * 1009
        frame = b"\x82\x7e" + len(oversized).to_bytes(2, "big") + oversized
        ws = bot_module.RawWebSocket.__new__(bot_module.RawWebSocket)
        ws.sock = FakeSocket(frame)
        ws._recvbuf = bytearray()
        ws.timeout = 1
        ws.permessage_deflate = False
        with patch.dict(bot_module.os.environ, {"WS_MAX_INBOUND_BYTES": "1008"}):
            kind, details = ws.recv()
        self.assertEqual(kind, "oversize")
        self.assertEqual(details["size"], 1009)
        self.assertEqual(ws.sock.sent, [])

    def test_send_binary_enforces_absolute_1008_byte_cap(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []
            def sendall(self, payload):
                self.sent.append(payload)

        ws = bot_module.RawWebSocket.__new__(bot_module.RawWebSocket)
        ws.sock = FakeSocket()
        ws._send_lock = bot_module.threading.Lock()
        with patch.dict(bot_module.os.environ, {"WS_MAX_MESSAGE_BYTES": "5000"}), patch("builtins.print"):
            ws.send_binary(b"x" * 1009)
        self.assertEqual(ws.sock.sent, [])

    def test_transient_eagain_waits_for_readability_and_continues(self):
        class FakeSocket:
            def __init__(self):
                self.calls = 0
            def recv(self, _size):
                self.calls += 1
                if self.calls == 1:
                    raise BlockingIOError(11, "Resource temporarily unavailable")
                return b"ok"

        ws = bot_module.RawWebSocket.__new__(bot_module.RawWebSocket)
        ws.sock = FakeSocket()
        ws._recvbuf = bytearray()
        ws.timeout = 1
        with patch.object(bot_module.select, "select", return_value=([], [], [])) as wait_readable:
            self.assertEqual(ws._recv_exact(2), b"ok")
        self.assertEqual(ws.sock.calls, 2)
        wait_readable.assert_called_once()


class CricketIntegrationRegressions(unittest.TestCase):
    def make_integration(self, root, room_messages, private_messages, media_messages, is_verified=None, send_all_rooms_text=None, bot_name="Talkin2"):
        return CricketIntegration(
            root,
            is_master=lambda name: str(name).casefold() == "master",
            is_configured_master=lambda name: str(name).casefold() == "master",
            is_verified=is_verified or (lambda _name: True),
            send_all_rooms_text=send_all_rooms_text,
            send_room_text=lambda room, text: room_messages.append((room, text)),
            send_room_media=lambda room, url, kind: media_messages.append((room, url, kind)),
            send_private_text=lambda user, text: private_messages.append((user, text)),
            public_base=lambda: "https://bot.example",
            bot_name=bot_name,
            log=lambda *_args: None,
        )

    def test_join_acknowledgement_is_sent_before_game_event_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            room_messages, private_messages, media_messages = [], [], []
            integration = self.make_integration(Path(temp), room_messages, private_messages, media_messages)
            integration.game.set_enabled("North", True)
            integration.game.start("North", 1, mode="rooms")
            room_messages.clear()

            self.assertTrue(integration.handle("North", "N1", "Join"))
            self.assertIn("تم الانضمام إلى الفريق الأول", room_messages[0][1])
            self.assertIn("N1", integration.game.current()["rooms"][0]["players"])
            self.assertTrue(any("بدأت لعبة الكريكيت" in text for _, text in room_messages[1:]))

    def test_legacy_single_match_state_is_migrated_to_matches_map(self):
        with tempfile.TemporaryDirectory() as temp:
            game = CricketGame(Path(temp) / "cricket_state.json")
            legacy_match = {
                "id": "legacy-match",
                "stage": "lobby",
                "target_players": 1,
                "setup_room": "north",
                "mode": "rooms",
                "rooms": [{"key": "north", "name": "North", "players": []}],
                "teams": {},
            }
            game.state.mutate(lambda data: data.update(enabled=True, match=legacy_match))
            self.assertEqual(game.current("North")["id"], "legacy-match")
            self.assertIsNone(game.join("North", "N1"))
            saved = game.state.load()
            self.assertIsNone(saved["match"])
            self.assertIn("legacy-match", saved["matches"])
            self.assertEqual(saved["matches"]["legacy-match"]["rooms"][0]["players"], ["N1"])

    def test_private_master_toggle_and_cross_room_turn_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            room_messages, private_messages, media_messages = [], [], []
            root = Path(temp)
            integration = self.make_integration(root, room_messages, private_messages, media_messages)

            integration.handle("North", "intruder", ".cr 1", is_private=True)
            self.assertFalse(integration.game.enabled())
            self.assertIn("للماستر المحدد", private_messages[-1][1])
            integration.handle("North", "intruder", ".cr 0", is_private=True)
            self.assertFalse(integration.game.enabled())
            self.assertIn("للماستر المحدد", private_messages[-1][1])

            # The master toggles the service privately; a verified member then
            # opens the room-only player-count setup with `.cr 1`.
            integration.handle("North", "Master", ".cr 1")
            self.assertFalse(integration.game.enabled())
            self.assertIn("فعّل اللعبة", room_messages[-1][1])
            integration.handle("North", "Master", ".cr 0")
            self.assertFalse(integration.game.enabled())
            self.assertIn("لا توجد مباراة", room_messages[-1][1])
            integration.handle("North", "Master", "cricket on")
            self.assertFalse(integration.game.enabled())
            self.assertIn("خاص البوت", room_messages[-1][1])

            integration.handle("North", "Master", ".cr 1", is_private=True)
            self.assertTrue(integration.game.enabled())
            self.assertIsNone(integration.game.current())
            self.assertIn("ملفات لعبة الكركيت", private_messages[-1][1])

            integration.handle("North", "Master", ".cr 1")
            self.assertEqual(integration.game.current()["stage"], "setup")
            self.assertIn("إعداد مباراة الكركيت", room_messages[-1][1])

            integration.handle("North", "N1", "2")
            self.assertEqual(integration.game.current()["stage"], "lobby")
            integration.handle("North", "N1", "Join")
            integration.handle("North", "N2", "Join")
            integration.handle("South", "S1", "Join")
            integration.handle("South", "S2", "Join")
            self.assertEqual(integration.game.current()["stage"], "teams")

            # The initiating room chooses; the other team is assigned the opposite side.
            integration.handle("North", "N1", "1")
            match = integration.game.current()
            self.assertEqual(match["stage"], "live")
            self.assertEqual(match["teams"]["north"], "attack")
            self.assertEqual(match["teams"]["south"], "defense")

            room_messages.clear()
            integration.handle("North", "N1", "6")
            self.assertTrue(
                any(room == "South" and "دورك يا @S1" in text for room, text in room_messages),
                "the bowling turn must reach the other room after the batter submits",
            )
            room_messages.clear()
            integration.handle("South", "S1", "6")
            self.assertTrue(any("/assets/cricket_number_6.png" in url for _, url, _ in media_messages))
            self.assertTrue(any("/assets/cricket_duck.png" in url for _, url, _ in media_messages))
            self.assertTrue(any(room == "North" for room, _, _ in media_messages))
            self.assertTrue(any(room == "South" for room, _, _ in media_messages))

            # Stop is private-only and restricted to the configured master.
            integration.handle("North", "Master", ".cr 0")
            self.assertTrue(integration.game.enabled())
            integration.handle("North", "Master", ".cr 0", is_private=True)
            self.assertFalse(integration.game.enabled())
            self.assertIsNone(integration.game.current())

    def test_cr1_skips_archived_results_when_opening_a_new_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = CricketGame(root / "cricket_state.json")
            old.set_enabled("North", True)
            old.state.mutate(lambda data: old._emit(
                data, [{"key": "north", "name": "North"}],
                "🏆 نتيجة مباراة قديمة", ("cricket_result_old.png",),
            ))
            room_messages, private_messages, media_messages = [], [], []
            integration = self.make_integration(root, room_messages, private_messages, media_messages)
            self.assertIsNone(integration.game.current("North"))
            integration.handle("North", "N1", ".cr 1")
            fresh = integration.game.current("North")
            self.assertEqual(fresh["stage"], "setup")
            self.assertEqual(fresh["rooms"][0]["players"], [])
            self.assertIn("إعداد مباراة الكركيت", room_messages[-1][1])
            self.assertFalse(any("مباراة قديمة" in text for _, text in room_messages))
            self.assertFalse(any("cricket_result_old.png" in url for _, url, _ in media_messages))
            integration.handle("North", "N1", "1")
            self.assertEqual(integration.game.current("North")["stage"], "lobby")
            self.assertFalse(any("مباراة قديمة" in text for _, text in room_messages))

    def test_cr1_does_not_cancel_an_existing_match(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private, media = [], [], []
            integration = self.make_integration(Path(temp), messages, private, media)
            integration.game.set_enabled("North", True)
            integration.game.start("North", 2, mode="rooms")
            old_match = integration.game.current("North")
            messages.clear()
            self.assertTrue(integration.handle("North", "N1", ".cr 1"))
            current = integration.game.current("North")
            self.assertEqual(current["id"], old_match["id"])
            self.assertEqual(current["stage"], "lobby")
            self.assertTrue(any("مباراة مفتوحة بالفعل" in text for _, text in messages))
            self.assertFalse(any("أُلغيت المباراة" in text for _, text in messages))

    def test_stale_terminal_match_is_ignored_when_starting_new_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            game = CricketGame(Path(temp) / "cricket_state.json")
            game.state.mutate(lambda data: data.update(
                enabled=True,
                matches={"old-finished": {
                    "id": "old-finished", "stage": "finished", "created_at": 1,
                    "rooms": [{"key": "north", "name": "North", "players": ["OldPlayer"]}],
                }},
            ))
            self.assertIsNone(game.begin_setup("North"))
            current = game.current("North")
            self.assertIsNotNone(current)
            self.assertNotEqual(current["id"], "old-finished")
            self.assertEqual(current["stage"], "setup")
            self.assertEqual([match["id"] for match in game.matches()], [current["id"]])

    def test_join_from_second_room_skips_old_match_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first_messages, private_messages, first_media = [], [], []
            first = self.make_integration(root, first_messages, private_messages, first_media)
            first.handle("North", "Master", ".cr 1", is_private=True)
            first.handle("North", "N1", ".cr 1")
            first.handle("North", "N1", "2")
            first.handle("North", "N1", "Join")
            first.handle("North", "N2", "Join")
            self.assertEqual(first.game.current()["stage"], "lobby")

            def add_stale_image(data):
                first.game._emit(
                    data, [{"key": "south", "name": "South"}],
                    "صورة من مباراة قديمة", ("cricket_number_4.png",),
                )
            first.game.state.mutate(add_stale_image)

            second_messages, second_media = [], []
            second = self.make_integration(root, second_messages, [], second_media)
            second.handle("South", "S1", "Join")
            second.handle("South", "S2", "Join")
            self.assertEqual(second.game.current()["stage"], "teams")
            self.assertEqual(second_media, [])
            self.assertFalse(any("مباراة قديمة" in text for _, text in second_messages))

    def test_verified_member_can_stop_current_room_match_with_cr0(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private_messages, media = [], [], []
            integration = self.make_integration(Path(temp), messages, private_messages, media)
            integration.handle("North", "Master", ".cr 1", is_private=True)
            integration.handle("North", "N1", ".cr 1")
            integration.handle("North", "N1", "1")
            integration.handle("North", "N1", "Join")
            self.assertIsNotNone(integration.game.current())
            integration.handle("North", "N1", ".cr 0")
            self.assertIsNone(integration.game.current())
            self.assertTrue(integration.game.enabled())
            self.assertIn("تم إيقاف مباراة الكركيت", messages[-1][1])

            integration.handle("North", "N2", ".cr 0")
            self.assertIsNone(integration.game.current())
            self.assertIn("لا توجد مباراة", messages[-1][1])

    def test_restart_resumes_a_saved_batting_choice_without_replaying_old_events(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            room_messages, private_messages, media_messages = [], [], []
            first = self.make_integration(root, room_messages, private_messages, media_messages)
            first.handle("North", "Master", "تشغيل لعبه الكركيت", is_private=True)
            first.handle("North", "Master", ".cr 1")
            first.handle("North", "Master", "2")
            first.handle("North", "N1", "Join")
            first.handle("North", "N2", "Join")
            first.handle("South", "S1", "Join")
            first.handle("South", "S2", "Join")
            first.handle("North", "N1", "1")
            first.handle("North", "N1", "4")

            before = len(room_messages)
            restarted = self.make_integration(root, room_messages, private_messages, media_messages)
            self.assertFalse(restarted.handle("South", "S1", "hello"))
            resumed = room_messages[before:]
            self.assertTrue(any(room == "South" and "دورك يا @S1" in text for room, text in resumed))
            self.assertTrue(any(room == "North" and "حُفظ اختيار الهجوم" in text for room, text in resumed))
            self.assertFalse(any("إعداد مباراة الكركيت" in text for _, text in resumed))

    def test_direct_cricket_one_starts_a_solo_bot_match(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private, media = [], [], []
            integration = self.make_integration(Path(temp), messages, private, media)
            integration.game.set_enabled("Hall", True)
            self.assertTrue(integration.handle("Hall", "Player", "cricket 1"))
            self.assertEqual(integration.game.current()["mode"], "solo")
            self.assertTrue(integration.handle("Hall", "Player", "Join"))
            self.assertEqual(integration.game.current()["stage"], "live")
            deliveries = 0
            while integration.game.current() is not None:
                self.assertTrue(integration.handle("Hall", "Player", "6"))
                deliveries += 1
                self.assertLess(deliveries, 13)
            self.assertGreaterEqual(deliveries, 1)
            self.assertTrue(any("الكرة 1/6" in text for _, text in messages))
            self.assertTrue(any("انتهت مباراة الكركيت" in text for _, text in messages))
            self.assertTrue(any("cricket_number_6.png" in url for _, url, _ in media))
            self.assertTrue(any("cricket_result_" in url for _, url, _ in media))

    def test_cr2_starts_room_vs_room_and_rejects_same_room_second_team(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private, media = [], [], []
            integration = self.make_integration(Path(temp), messages, private, media)
            integration.game.set_enabled("North", True)
            integration.handle("North", "N1", ".cr 2")
            match = integration.game.current()
            self.assertEqual(match["mode"], "rooms")
            self.assertEqual(match["target_players"], 2)
            integration.handle("North", "N1", "Join")
            integration.handle("North", "N2", "Join")
            integration.handle("North", "N3", "Join")
            self.assertEqual(len(integration.game.current()["rooms"]), 1)
            self.assertEqual(integration.game.current()["stage"], "lobby")
            integration.handle("South", "S1", "Join")
            integration.handle("South", "S2", "Join")
            self.assertEqual(len(integration.game.current()["rooms"]), 2)
            self.assertEqual(integration.game.current()["stage"], "teams")

    def test_cr1_setup_is_one_player_per_side_across_two_rooms(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private, media = [], [], []
            integration = self.make_integration(Path(temp), messages, private, media)
            integration.game.set_enabled("North", True)
            integration.handle("North", "N1", ".cr 1")
            integration.handle("North", "N1", "1")
            match = integration.game.current()
            self.assertEqual(match["mode"], "rooms")
            self.assertEqual(match["target_players"], 1)
            integration.handle("North", "N1", "Join")
            self.assertEqual(integration.game.current()["stage"], "lobby")
            integration.handle("South", "S1", "Join")
            match = integration.game.current()
            self.assertEqual(match["stage"], "teams")
            self.assertEqual([len(item["players"]) for item in match["rooms"]], [1, 1])

    def test_independent_simultaneous_room_matches_support_one_through_four_players(self):
        for count in range(1, 5):
            with self.subTest(players_per_room=count), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / f"count-{count}"
                root.mkdir()
                messages, private, media = [], [], []
                integration = self.make_integration(root, messages, private, media)
                integration.game.set_enabled("Master", True)

                for room, prefix in (("North", "N"), ("East", "E")):
                    captain = f"{prefix}1"
                    integration.handle(room, captain, ".cr 1")
                    integration.handle(room, captain, str(count))
                    for index in range(1, count + 1):
                        integration.handle(room, f"{prefix}{index}", "Join")

                north_match = integration.game.current("North")
                east_match = integration.game.current("East")
                self.assertNotEqual(north_match["id"], east_match["id"])

                # Plain Join deterministically pairs with the oldest complete lobby.
                integration.handle("South", "S1", "Join")
                self.assertEqual(integration.game.current("South")["id"], north_match["id"])
                integration.handle("West", "W1", "Join")
                self.assertEqual(integration.game.current("West")["id"], east_match["id"])

                for index in range(2, count + 1):
                    integration.handle("South", f"S{index}", "Join")
                    integration.handle("West", f"W{index}", "Join")

                self.assertFalse(any(
                    internal_id in text
                    for _, text in messages
                    for internal_id in (north_match["id"], east_match["id"])
                ))

                self.assertEqual(integration.game.current("North")["stage"], "teams")
                self.assertEqual(integration.game.current("East")["stage"], "teams")
                self.assertEqual(
                    [len(item["players"]) for item in integration.game.current("North")["rooms"]],
                    [count, count],
                )
                self.assertEqual(
                    [len(item["players"]) for item in integration.game.current("East")["rooms"]],
                    [count, count],
                )

                integration.handle("North", "N1", "1")
                integration.handle("East", "E1", "2")
                self.assertEqual(integration.game.current("North")["stage"], "live")
                self.assertEqual(integration.game.current("East")["stage"], "live")
                self.assertEqual(integration.game.current("North")["batting_team"], "attack")
                self.assertEqual(integration.game.current("East")["batting_team"], "defense")

                resumed_messages, resumed_private, resumed_media = [], [], []
                restarted = self.make_integration(
                    root, resumed_messages, resumed_private, resumed_media,
                )
                self.assertEqual(len(restarted.game.matches()), 2)
                restarted._resume_after_restart()
                self.assertEqual(
                    {room for room, _ in resumed_messages},
                    {"North", "South", "East", "West"},
                )

                # Resolve one ball in each match, and prove the other game's state is untouched.
                integration.handle("North", "N1", "1")
                integration.handle("South", "S1", "2")
                self.assertEqual(integration.game.current("North")["balls"], 1)
                self.assertEqual(integration.game.current("East")["balls"], 0)
                integration.handle("East", "E1", "2")
                integration.handle("West", "W1", "3")
                self.assertEqual(integration.game.current("North")["balls"], 1)
                self.assertEqual(integration.game.current("East")["balls"], 1)

                for room, other_pair in (("North", ("East", "West")), ("South", ("East", "West")),
                                         ("East", ("North", "South")), ("West", ("North", "South"))):
                    room_text = "\n".join(text for target, text in messages if target == room)
                    self.assertFalse(any(name in room_text for name in other_pair))

    def test_numbers_in_non_participating_room_are_not_cricket_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private, media = [], [], []
            integration = self.make_integration(Path(temp), messages, private, media)
            integration.game.set_enabled("North", True)
            integration.handle("North", "N1", ".cr 2")
            integration.handle("North", "N1", "Join")
            integration.handle("North", "N2", "Join")
            messages.clear()
            self.assertFalse(integration.handle("Other", "Stranger", "6"))
            self.assertEqual(messages, [])

    def test_cr_b_opens_bot_setup_and_accepts_multiple_players_in_one_room(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private, media = [], [], []
            integration = self.make_integration(Path(temp), messages, private, media)
            integration.game.set_enabled("Hall", True)
            integration.handle("Hall", "Player", ".cr b")
            match = integration.game.current()
            self.assertEqual(match["mode"], "solo")
            self.assertEqual(match["stage"], "setup")
            integration.handle("Hall", "Player", "3")
            for player in ("P1", "P2", "P3"):
                integration.handle("Hall", player, "Join")
            match = integration.game.current()
            self.assertEqual(match["stage"], "live")
            self.assertIn("__sboot_cricket_bot__", match["teams"])

    def test_bot_match_uses_configured_nickname_instead_of_repository_name(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private, media = [], [], []
            integration = self.make_integration(
                Path(temp), messages, private, media, bot_name="𝐒𝐎𝐔☀𝐑𝐄𝐀"
            )
            integration.game.set_enabled("Hall", True)
            integration.handle("Hall", "Player", ".cr b")
            self.assertIn("𝐒𝐎𝐔☀𝐑𝐄𝐀", messages[-1][1])
            integration.handle("Hall", "Player", "1")
            integration.handle("Hall", "Player", "Join")
            self.assertTrue(any("𝐒𝐎𝐔☀𝐑𝐄𝐀" in text for _, text in messages))

    def test_batter_stays_until_out_and_bowler_rotates_every_six_balls(self):
        with tempfile.TemporaryDirectory() as temp:
            room_messages, private_messages, media_messages = [], [], []
            integration = self.make_integration(
                Path(temp), room_messages, private_messages, media_messages,
                send_all_rooms_text=lambda text: [
                    room_messages.append((room, text)) for room in ("North", "South", "Lobby")
                ],
            )
            integration.handle("North", "Master", ".cr 1", is_private=True)
            integration.handle("North", "Master", ".cr 1")
            integration.handle("North", "N1", ".cr 2")
            for player in ("N1", "N2"):
                integration.handle("North", player, "Join")
            first_team_announcements = [
                (room, text) for room, text in room_messages if text.startswith("🏏 بدأت لعبة الكريكيت")
            ]
            self.assertEqual({room for room, _ in first_team_announcements}, {"North", "South", "Lobby"})
            self.assertEqual(len(first_team_announcements), 3)
            self.assertIn("غرفة North", first_team_announcements[0][1])
            self.assertIn("عدد الفريق: 2 لاعبين", first_team_announcements[0][1])
            self.assertIn("للانضمام أرسل Join", first_team_announcements[0][1])
            self.assertNotIn("Join@", first_team_announcements[0][1])
            self.assertEqual(integration.game.current()["stage"], "lobby")

            for player in ("S1", "S2"):
                integration.handle("South", player, "Join")
            integration.handle("North", "N1", "1")

            started = [(room, text) for room, text in room_messages if "بدأت مباراة الكريكيت" in text]
            self.assertEqual({room for room, _ in started}, {"North", "South", "Lobby"})
            for _, text in started:
                self.assertIn("North (2 لاعبين): @N1، @N2", text)
                self.assertIn("South (2 لاعبين): @S1، @S2", text)

            batting_counts, bowling_counts = {}, {}

            def play_delivery(bat_value, bowl_value):
                match = integration.game.current()
                self.assertIsNotNone(match)
                innings = int(match["innings"])
                batting = match["batting_team"]
                bowling = "defense" if batting == "attack" else "attack"
                batter = integration.game._next_player(match, batting, batting=True)
                bowler = integration.game._next_player(match, bowling, batting=False)
                bat_room = integration.game._room_for_team(match, batting)
                bowl_room = integration.game._room_for_team(match, bowling)
                batting_counts[(innings, batter)] = batting_counts.get((innings, batter), 0) + 1
                bowling_counts[(innings, bowler)] = bowling_counts.get((innings, bowler), 0) + 1
                integration.handle(bat_room["name"], batter, str(bat_value))
                integration.handle(bowl_room["name"], bowler, str(bowl_value))

            for ball_index in range(6):
                room_messages.clear()
                play_delivery(1, 2)
                if ball_index == 0:
                    self.assertTrue(room_messages)
                    self.assertTrue(all(room in {"North", "South"} for room, _ in room_messages))
                    self.assertTrue(any(
                        "أرسل رقم 1" in text and "أرسل رقم 2" in text
                        for _, text in room_messages
                    ))
            match = integration.game.current()
            self.assertEqual((match["innings"], match["balls"]), (1, 6))

            for _ in range(6):
                play_delivery(1, 2)
            match = integration.game.current()
            self.assertEqual((match["innings"], match["balls"]), (2, 0))

            for _ in range(3):
                play_delivery(6, 1)
            match = integration.game.current()
            self.assertEqual(match["innings"], 2)
            self.assertGreater(match["scores"]["defense"], match["scores"]["attack"])
            self.assertEqual(match["balls"], 3, "a target lead must not end the defense innings early")

            for _ in range(9):
                play_delivery(6, 1)
            self.assertIsNone(integration.game.current())
            # The batter remains at the crease until OUT, even for all 12
            # team balls; the defender changes after six consecutive balls.
            self.assertEqual(batting_counts[(1, "N1")], 12)
            self.assertNotIn((1, "N2"), batting_counts)
            self.assertEqual(bowling_counts[(1, "S1")], 6)
            self.assertEqual(bowling_counts[(1, "S2")], 6)
            self.assertEqual(batting_counts[(2, "S1")], 12)
            self.assertNotIn((2, "S2"), batting_counts)
            self.assertEqual(bowling_counts[(2, "N1")], 6)
            self.assertEqual(bowling_counts[(2, "N2")], 6)
            self.assertEqual(integration.game.get_points("S1") + integration.game.get_points("S2"), 1_000_000_000)

    def test_first_team_attacks_then_roles_switch_and_same_bowler_gets_hattrick(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, private, media = [], [], []
            integration = self.make_integration(Path(temp), messages, private, media)
            integration.handle("North", "Master", ".cr 1", is_private=True)
            integration.handle("North", "N1", ".cr 1")
            integration.handle("North", "N1", "4")
            for player in ("N1", "N2", "N3", "N4"):
                integration.handle("North", player, "Join")
            for player in ("S1", "S2", "S3", "S4"):
                integration.handle("South", player, "Join")
            integration.handle("North", "N1", "1")
            match = integration.game.current()
            self.assertEqual(match["batting_team"], "attack")
            self.assertEqual(match["teams"]["north"], "attack")
            self.assertEqual(match["teams"]["south"], "defense")

            def resolve_wicket(batter):
                def mutate(data):
                    current = integration.game._match_for_room(data, "North")
                    integration.game._resolve_ball(
                        data, current, integration.game._participants(current),
                        {"value": 4, "room_key": "north", "room": "North", "sender": batter},
                        {"value": 4, "room_key": "south", "room": "South", "sender": "S1"},
                    )
                integration.game.state.mutate(mutate)

            for batter in ("N1", "N2"):
                resolve_wicket(batter)
            # Talkin2's rule: the same defender dismissing two batters in a
            # row earns the hat-trick. Finish the remaining innings ball so
            # the role switch is also verified.
            hattrick_events = integration.game.events_after("North", 0)
            self.assertTrue(any("هاتريك" in str(event.get("text")) for event in hattrick_events))
            resolve_wicket("N3")
            resolve_wicket("N4")

            transition = [event.get("text", "") for event in integration.game.state.load().get("events", [])
                          if "الشوط الأول انتهى" in str(event.get("text", ""))]
            self.assertTrue(transition)
            match = integration.game.current()
            self.assertIsNotNone(match)
            self.assertEqual(match["innings"], 2)
            self.assertEqual(match["batting_team"], "defense")
            self.assertTrue(any("cricket_hattrick.png" in image for event in hattrick_events for image in event.get("images", [])))

    def test_only_verified_members_can_start_or_join_cricket(self):
        with tempfile.TemporaryDirectory() as temp:
            room_messages, private_messages, media_messages = [], [], []
            integration = self.make_integration(
                Path(temp), room_messages, private_messages, media_messages,
                is_verified=lambda name: str(name).casefold() in {"master", "verified"},
            )
            integration.handle("Room", "Master", "تشغيل لعبه الكركيت", is_private=True)
            self.assertIsNone(integration.game.current())

            integration.handle("Room", "Guest", ".cr 1")
            self.assertIsNone(integration.game.current())
            self.assertIn("موثقين", room_messages[-1][1])

            integration.handle("Room", "Verified", ".cr 1")
            self.assertEqual(integration.game.current()["stage"], "setup")
            setup_text = room_messages[-1][1]
            self.assertIn("إعداد مباراة الكركيت", setup_text)
            self.assertIn("اختر عدد اللاعبين داخل هذه الغرفة فقط", setup_text)
            self.assertIn("ترسل الغرفة الثانية Join", setup_text)
            self.assertNotIn("Join@", setup_text)
            integration.handle("Room", "Verified", ".cr 2")
            self.assertEqual(integration.game.current()["stage"], "lobby")
            integration.handle("Room", "Guest", "Join")
            self.assertEqual(integration.game.current()["rooms"][0]["players"], [])
            self.assertIn("موثقين", room_messages[-1][1])

            integration.handle("Room", "Verified", "Join")
            self.assertEqual(integration.game.current()["rooms"][0]["players"], ["Verified"])


class BotGameAndMusicRegressions(unittest.TestCase):
    def test_legacy_compact_stats_are_found_for_decorated_username(self):
        decorated = "𝐒𝐎𝐔☀𝐑𝐄𝐀"
        legacy = {
            "sourea": {
                "username": "SOUREA",
                "games": {"star": {"plays": 3890, "points": 12}},
            }
        }
        with patch.object(bot_module, "_game_stats_data", return_value=legacy):
            level, _label, plays = bot_module._game_level_info(decorated)
            stats = bot_module._game_stats(decorated, "star")
        self.assertEqual(plays, 3890)
        self.assertEqual(level, 8)
        self.assertEqual(stats["plays"], 3890)

    def test_record_game_merges_into_legacy_compact_stats(self):
        decorated = "𝐒𝐎𝐔☀𝐑𝐄𝐀"
        legacy = {
            "sourea": {
                "username": "SOUREA",
                "games": {"star": {"plays": 3890, "points": 12, "staked": 0}},
            }
        }
        with patch.object(bot_module, "_game_stats_data", return_value=legacy), patch.object(
            bot_module, "_queue_local_json_save"
        ), patch.object(bot_module, "_save_game_levels_snapshot"):
            bot_module._record_game(decorated, "star", 5)
        self.assertEqual(set(legacy), {"sourea"})
        self.assertEqual(legacy["sourea"]["games"]["star"]["plays"], 3891)

    def test_restore_games_command_sums_duplicate_records_and_is_master_only(self):
        legacy = {
            "sourea": {"username": "SOUREA", "games": {"star": {"plays": 3890}}},
            "sou☀rea": {"username": "𝐒𝐎𝐔☀𝐑𝐄𝐀", "games": {"coin": {"plays": 10}}},
        }
        admin = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        admin._room_list_commands = lambda *_args: False
        replies = []
        admin.send_private_text = lambda user, text: replies.append((user, text))
        with patch.object(bot_module, "_is_primary_master", side_effect=lambda name: name == "Master"), patch.object(
            bot_module, "_game_stats_data", return_value=legacy
        ), patch.object(bot_module, "_queue_local_json_save"), patch.object(
            bot_module, "_save_game_levels_snapshot"
        ):
            self.assertTrue(admin._handle_management_command_impl(
                "", "إضافة العاب@𝐒𝐎𝐔☀𝐑𝐄𝐀@4000", "Master", is_private=True
            ))
            self.assertIn("العدد السابق: 3900", replies[-1][1])
            self.assertIn("العدد الحالي: 4000", replies[-1][1])
            self.assertEqual(len(legacy), 1)
            self.assertEqual(bot_module._game_level_info("𝐒𝐎𝐔☀𝐑𝐄𝐀")[2], 4000)
            self.assertTrue(admin._handle_management_command_impl(
                "", "إضافة العاب@𝐒𝐎𝐔☀𝐑𝐄𝐀@5000", "Guest", is_private=True
            ))
        self.assertIn("مخصص للماستر", replies[-1][1])

    def test_game_top10_collapses_decorated_duplicate_records(self):
        data = {
            "sourea": {"username": "sourea", "games": {"star": {"plays": 3927}}},
            "sou☀rea": {"username": "𝐒𝐎𝐔☀𝐑𝐄𝐀", "games": {"star": {"plays": 3927}}},
            "𝐬𝐨𝐮𝐫𝐞𝐚": {"username": "𝐒𝐎𝐔𝐑𝐄𝐀", "games": {"star": {"plays": 3927}}},
            "other": {"username": "other", "games": {"star": {"plays": 4246}}},
        }
        with patch.object(bot_module, "_game_stats_data", return_value=data):
            rows = bot_module._game_top10()
            rendered = bot_module._game_top10_message()
        self.assertEqual(sum(1 for row in rows if bot_module._game_name_key(row[3]) == "sourea"), 1)
        self.assertIn("لعب 3927", rendered)
        self.assertEqual(rendered.count("3927"), 1)

    def test_persisted_game_files_are_deduped_with_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stats_file = root / "game_stats.json"
            levels_file = root / "game_levels.json"
            stats_backup = root / "game_stats.duplicates-backup.json"
            levels_backup = root / "game_levels.duplicates-backup.json"
            stats = {
                "sourea": {"username": "sourea", "games": {"star": {"plays": 3927}}},
                "sou☀rea": {"username": "𝐒𝐎𝐔☀𝐑𝐄𝐀", "games": {"star": {"plays": 3927}}},
            }
            levels = {"version": 1, "players": {
                "sourea": {"username": "sourea", "plays": 3927},
                "sou☀rea": {"username": "𝐒𝐎𝐔☀𝐑𝐄𝐀", "plays": 3927},
            }}
            stats_file.write_text(__import__("json").dumps(stats), encoding="utf-8")
            levels_file.write_text(__import__("json").dumps(levels), encoding="utf-8")
            with patch.object(bot_module, "_GAME_STATS_CACHE", stats), patch.object(
                bot_module, "GAME_STATS_FILE", stats_file
            ), patch.object(bot_module, "GAME_LEVELS_FILE", levels_file), patch.object(
                bot_module, "GAME_STATS_DEDUPE_BACKUP_FILE", stats_backup
            ), patch.object(bot_module, "GAME_LEVELS_DEDUPE_BACKUP_FILE", levels_backup
            ):
                bot_module._dedupe_persisted_game_files()
            saved_stats = __import__("json").loads(stats_file.read_text(encoding="utf-8"))
            saved_levels = __import__("json").loads(levels_file.read_text(encoding="utf-8"))
            self.assertEqual(len(saved_stats), 1)
            self.assertEqual(len(saved_levels["players"]), 1)
            self.assertTrue(stats_backup.is_file())
            self.assertTrue(levels_backup.is_file())
            self.assertEqual(saved_stats["sourea"]["games"]["star"]["plays"], 3927)

    def test_decorated_username_matches_game_stats_and_keeps_display_name(self):
        decorated = "♥☼هـــــ☼ـــادي☼♥اا"
        with patch.object(bot_module, "_game_stats_data", return_value={
            "هادياا": {
                "username": "هادياا",
                "games": {"star": {"plays": 50}},
            }
        }):
            level, label, plays = bot_module._game_level_info(decorated)
            welcome = bot_module._game_welcome(decorated, "North")
            self.assertEqual(level, 1)
            self.assertEqual(plays, 50)
            self.assertIn(label, welcome)
            self.assertIn(decorated, welcome)
            self.assertIn("🏅 مستوى الألعاب: 1", welcome)

    def test_new_player_gets_level_and_star_welcome(self):
        decorated = "♥☼هـــــ☼ـــادي☼♥اا"
        with patch.object(bot_module, "_game_stats_data", return_value={}):
            welcome = bot_module._game_welcome(decorated, "North")
            self.assertIn(decorated, welcome)
            self.assertIn("🏅 مستوى الألعاب: 1", welcome)
            self.assertIn("🎯 عدد الألعاب: 0", welcome)

    def test_game_level_advances_every_500_games_not_at_50(self):
        with patch.object(bot_module, "_game_stats_data", return_value={
            "player": {"username": "player", "games": {"star": {"plays": 49}}}
        }):
            before = bot_module._game_welcome("player", "North")
        with patch.object(bot_module, "_game_stats_data", return_value={
            "player": {"username": "player", "games": {"star": {"plays": 50}}}
        }):
            after = bot_module._game_welcome("player", "North")
        self.assertIn("🏅 مستوى الألعاب: 1", before)
        self.assertIn("🏅 مستوى الألعاب: 1", after)
        with patch.object(bot_module, "_game_stats_data", return_value={
            "player": {"username": "player", "games": {"star": {"plays": 500}}}
        }):
            next_level = bot_module._game_welcome("player", "North")
        self.assertIn("🏅 مستوى الألعاب: 2", next_level)

    def test_join_welcome_does_not_duplicate_vip_for_member_with_game_level(self):
        with patch.object(bot_module, "_is_vip_user", side_effect=lambda name: name == "vip"):
            with patch.object(bot_module, "_game_stats_data", return_value={
                "vip": {"username": "vip", "games": {"star": {"plays": 18}}}
            }):
                regular_welcome = bot_module._join_welcome_message("regular", "North")
                vip_welcome = bot_module._join_welcome_message("vip", "North")
            self.assertIn("🏅 مستوى الألعاب: 1", regular_welcome)
            self.assertNotIn("عضو Vip", vip_welcome)
            self.assertIn("🏅 مستوى الألعاب: 1", vip_welcome)

    def test_join_welcome_uses_game_level_at_50_games(self):
        records = {"regular": {"username": "regular", "games": {"star": {"plays": 50}}}}
        with patch.object(bot_module, "_is_vip_user", return_value=False), patch.object(
            bot_module, "_game_stats_data", return_value=records
        ):
            welcome = bot_module._join_welcome_message("regular", "North")
        self.assertIn("🏅 مستوى الألعاب", welcome)

    def test_master_join_welcome_uses_the_same_game_profile_as_members(self):
        records = {"master": {"username": "Master", "games": {"star": {"plays": 1234}}}}
        with patch.object(bot_module, "BOT_MASTER", "Master"), patch.object(
            bot_module, "_is_vip_user", return_value=False
        ), patch.object(bot_module, "_game_stats_data", return_value=records):
            master_welcome = bot_module._join_welcome_message("Master", "North")
            regular_welcome = bot_module._join_welcome_message("Member", "North")
            self.assertEqual(master_welcome, bot_module._game_welcome("Master", "North"))
        self.assertIn("عدد الألعاب: 1234", master_welcome)
        self.assertIn("عدد الألعاب: 0", regular_welcome)

    def test_sb_uses_sender_balance_and_msb_is_master_private_only(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        room_replies = []
        private_replies = []
        bot.send_room_text = lambda room, text: room_replies.append((room, text))
        bot.send_private_text = lambda user, text: private_replies.append((user, text))
        changes = []
        transfers = []
        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_transfer_points",
            side_effect=lambda sender, target, amount: transfers.append((sender, target, amount)) or {
                "ok": True, "sender": sender, "recipient": target, "amount": amount,
                "sender_balance": 900, "recipient_balance": 1100,
            },
        ), patch.object(bot_module, "_get_points", return_value=1000):
            self.assertTrue(bot._handle_management_command_impl("North", "sb@target@100", "member"))
        self.assertEqual(transfers, [("member", "target", 100)])
        self.assertEqual(changes, [])

        changes.clear()
        with patch.object(bot_module, "_is_primary_master", return_value=True), patch.object(
            bot_module, "_add_points", side_effect=lambda user, amount: changes.append((user, amount)) or 100
        ):
            self.assertTrue(bot._handle_management_command_impl("", "msb@target@100", "Master", is_private=True))
        self.assertEqual(changes, [("target", 100)])

        deductions = []
        with patch.object(bot_module, "_is_primary_master", return_value=True), patch.object(
            bot_module, "_deduct_points",
            side_effect=lambda target, amount, actor="": deductions.append((target, amount, actor)) or {
                "ok": True, "username": target, "amount": amount, "balance": 900,
            },
        ):
            self.assertTrue(bot._handle_management_command_impl("", "-sb@target@100", "Master", is_private=True))
        self.assertEqual(deductions, [("target", 100, "Master")])
        self.assertIn("900", private_replies[-1][1])

        with patch.object(bot_module, "_is_primary_master", return_value=True):
            self.assertTrue(bot._handle_management_command("North", "msb@target@100", "Master"))
        self.assertTrue(any("خاص البوت" in text for _, text in room_replies))

        with patch.object(bot_module, "_is_primary_master", return_value=True):
            self.assertTrue(bot._handle_management_command("North", "-sb@target@100", "Master"))
        self.assertTrue(any("خاص البوت" in text for _, text in room_replies))

        with patch.object(bot_module, "_is_primary_master", return_value=False):
            self.assertTrue(bot._handle_management_command_impl("", "-sb@target@100", "OtherMaster", is_private=True))
        self.assertIn("BOT_MASTER", private_replies[-1][1])
        self.assertTrue(bot_module._looks_like_admin_command("-sb@target@100"))

    def test_private_master_deduction_passes_through_management_wrapper(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args, **_kwargs: False
        bot._master_reply_local = threading.local()
        bot._remember_bot_action = lambda *_args, **_kwargs: None
        sent = []

        def send_private(user, text):
            sent.append((user, text))
            if getattr(bot._master_reply_local, "tracking", False):
                bot._master_reply_local.private_replied = True
            return True

        bot.send_private_text = send_private
        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_is_primary_master", return_value=True
        ), patch.object(bot_module, "_deduct_points", return_value={
            "ok": True, "username": "target", "amount": 25, "balance": 75,
        }) as deduct:
            self.assertTrue(bot._handle_management_command("", "-sb@target@25", "Master", is_private=True))
        deduct.assert_called_once_with("target", 25, actor="Master")
        self.assertIn("75", sent[-1][1])

    def test_verified_sb_is_allowed_through_public_management_gate(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._master_reply_local = __import__("threading").local()
        bot.send_room_text = lambda *_args: None
        bot.send_private_text = lambda *_args: None
        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_get_points", return_value=1000
        ), patch.object(bot_module, "_add_points", return_value=900):
            self.assertTrue(bot._handle_management_command("North", "sb@target@100", "member"))

    def test_box_number_reply_uses_normalized_room_key(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.pending_bot_choices = {}
        output = []
        bot.send_room_text = lambda room, text: output.append((room, text))
        bot._game_cooldown_notice = lambda *_args: True
        bot._bot_win_reward = lambda: 100
        bot._game_award = lambda _name, reward: reward

        with patch.object(bot_module.secrets, "randbelow", return_value=1), patch.object(
            bot_module, "_record_game", lambda *_args: None
        ):
            self.assertTrue(bot._box_bot_game("Main Room", "Tester", "صندوق"))
            self.assertTrue(bot._handle_pending_bot_choice(" main   room ", "2", "TESTER"))
        self.assertTrue(any("✅ ربحت" in text for _, text in output))

    def test_english_game_aliases_reach_canonical_handlers(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stock_pending = {}
        bot.pending_bot_choices = {}
        bot._snake_command = lambda *_args: False
        bot._ludo_command = lambda *_args: False
        bot._handle_pending_bot_choice = lambda *_args: False
        bot.send_room_text = lambda *_args: None
        routed = []
        bot._queue_fixed_game = lambda room, sender, name, prize: routed.append((name, prize)) or True
        bot._coin_bot_game = lambda room, sender, choice=None: routed.append(("coin", choice)) or True
        bot._queue_wager = lambda room, sender, game, amount: routed.append((game, amount)) or True
        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_games_enabled_for_room", return_value=True
        ):
            self.assertTrue(bot.handle_game_command("Hall", "fishing", "Player"))
            self.assertTrue(bot.handle_game_command("Hall", "coin@heads", "Player"))
            self.assertTrue(bot.handle_game_command("Hall", "bet 25", "Player"))
        self.assertEqual(routed, [("سنارة", 500), ("coin", "وجه"), ("رهان", 25)])
        for command in ("fishing", "snare", "lookalike@Player", "bet 25", "investment@100"):
            self.assertTrue(bot_module._looks_like_bot_command(command), command)
        self.assertEqual(bot_module._normalize_game_command_text("coin@tails"), "عملة@كتابة")

    def test_game_broadcast_prioritizes_origin_room_with_short_gap(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._active_rooms = lambda: ["Alpha", "Beta", "Hall"]
        bot._game_broadcast_lock = threading.Lock()
        sent, gaps = [], []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        bot.log = lambda *_args: None
        with patch.object(bot_module.time, "sleep", side_effect=gaps.append):
            self.assertEqual(bot.broadcast_game_rooms("challenge", first_room="Hall"), 3)
        self.assertEqual([room for room, _ in sent], ["Hall", "Alpha", "Beta"])
        self.assertEqual(gaps, [0.05, 0.05])

    def test_wager_opening_uses_fast_game_broadcast_from_origin_room(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.game_lock = threading.Lock()
        bot.wager_waiting = {}
        bot._cleanup_expired_wagers = lambda: None
        bot._game_cooldown_notice = lambda *_args: True
        sent = []
        bot.broadcast_game_rooms = lambda text, first_room="": sent.append((first_room, text)) or 1
        with patch.object(bot_module, "_get_points", return_value=100), patch.object(
            bot_module, "_add_points", return_value=80
        ):
                self.assertTrue(bot._queue_wager("North", "Player", "رهان", 20))
        self.assertEqual(sent[0][0], "North")
        self.assertIn("بدأت لعبة رهان", sent[0][1])

    def test_expired_wager_refunds_reserved_stake_without_competitor(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.game_lock = threading.RLock()
        bot.wager_waiting = {
            "رهان": {"id": "wager-123", "user": "Player", "room": "North", "stake": 5_000_000_000,
                     "reserved": True, "game": "رهان", "created": 100.0}
        }
        bot._effective_room_language = lambda _room: "ar"
        bot.log = lambda *_args: None
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        with patch.object(bot_module.time, "time", return_value=221.0), patch.object(
            bot_module, "_apply_points_delta_once", return_value={"ok": True, "balance": 5_000_000_000}
        ) as apply:
            bot._cleanup_expired_wagers()
        self.assertFalse(bot.wager_waiting)
        self.assertEqual(apply.call_args.args[:3], ("Player", 5_000_000_000, "wager-timeout-refund:wager-123"))
        self.assertEqual(len(sent), 1)
        self.assertIn("أُعيد مبلغ", sent[0][1])
        self.assertIn("Player", sent[0][1])

    def test_expired_wager_refund_retries_after_points_persistence_failure(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.game_lock = threading.RLock()
        bot.wager_waiting = {
            "رهان": {"id": "wager-retry", "user": "Player", "room": "North", "stake": 5_000,
                     "reserved": True, "game": "رهان", "created": 100.0}
        }
        bot._effective_room_language = lambda _room: "ar"
        bot.log = lambda *_args: None
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        with patch.object(bot_module.time, "time", return_value=221.0), patch.object(
            bot_module, "_apply_points_delta_once",
            side_effect=[{"ok": False, "error": "persistence_failed"}, {"ok": True, "balance": 5_000}],
        ) as apply:
            bot._cleanup_expired_wagers()
            self.assertIn("رهان", bot.wager_waiting)
            self.assertNotIn("_refund_pending", bot.wager_waiting["رهان"])
            self.assertFalse(sent)
            bot._cleanup_expired_wagers()
        self.assertEqual(apply.call_count, 2)
        self.assertEqual(apply.call_args_list[0].args[2], apply.call_args_list[1].args[2])
        self.assertFalse(bot.wager_waiting)
        self.assertEqual(len(sent), 1)

    def test_stock_market_worker_checks_expired_wagers_periodically(self):
        class StopAfterOneIteration:
            def __init__(self):
                self.iterations = 0
            def is_set(self):
                return self.iterations >= 1
            def wait(self, _seconds):
                self.iterations += 1

        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stop_event = StopAfterOneIteration()
        bot._stock_market_next_announcement = bot_module.time.time() + 3600
        bot._active_rooms = lambda: []
        bot._cleanup_expired_wagers = lambda: cleanups.append(True)
        bot._process_stock_market_investments = lambda _now: None
        cleanups = []
        bot._stock_market_worker()
        self.assertEqual(cleanups, [True])

    def test_second_wager_uses_first_players_stake_even_if_command_amount_is_smaller(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.game_lock = threading.RLock()
        bot.wager_waiting = {
            "رهان": {"user": "Ahmed", "room": "North", "stake": 1_000_000_000,
                     "reserved": True, "game": "رهان", "created": bot_module.time.time()}
        }
        bot._cleanup_expired_wagers = lambda: None
        bot._game_cooldown_notice = lambda *_args: True
        bot.send_room_text = lambda *_args: None
        resolved = []
        bot._wager_result = lambda first, second, game: resolved.append((first, second, game))
        deducted = []
        with patch.object(bot_module, "_get_points", return_value=2_000_000_000), patch.object(
            bot_module, "_add_points", side_effect=lambda user, amount: deducted.append((user, amount))
        ):
            self.assertTrue(bot._queue_wager("South", "Said", "رهان", 100_000))
        first, second, game = resolved[0]
        self.assertEqual(game, "رهان")
        self.assertEqual(first["stake"], 1_000_000_000)
        self.assertEqual(second["stake"], 1_000_000_000)
        self.assertEqual(deducted, [("Said", -1_000_000_000)])

    def test_second_wager_is_rejected_when_balance_cannot_cover_first_players_stake(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.game_lock = threading.RLock()
        bot.wager_waiting = {
            "رهان": {"user": "Ahmed", "room": "North", "stake": 1_000_000_000,
                     "reserved": True, "game": "رهان", "created": bot_module.time.time()}
        }
        bot._cleanup_expired_wagers = lambda: None
        bot._game_cooldown_notice = lambda *_args: True
        messages, resolved = [], []
        bot.send_room_text = lambda _room, text: messages.append(text)
        bot._wager_result = lambda *_args: resolved.append(True)
        with patch.object(bot_module, "_get_points", return_value=100_000), patch.object(
            bot_module, "_add_points"
        ) as add_points:
            self.assertTrue(bot._queue_wager("South", "Said", "رهان", 100_000))
        self.assertFalse(resolved)
        add_points.assert_not_called()
        self.assertTrue(bot.wager_waiting["رهان"])
        self.assertTrue(messages)

    def test_matched_billion_wager_deducts_full_stake_from_loser_for_either_winner(self):
        stake = 1_000_000_000
        for game_name in ("رهان", "مراهنة", "مضاربة", "استثمار", "حظي"):
            for roll, expected_winner, expected_loser in (
                (0, "Ahmed", "Said"), (1, "Said", "Ahmed")
            ):
              with self.subTest(game=game_name, winner=expected_winner):
                bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
                bot.game_lock = threading.RLock()
                # Ahmed's stake was already reserved while the challenge waited.
                balances = {"Ahmed": stake, "Said": 2 * stake}
                bot.wager_waiting = {
                    game_name.casefold(): {"user": "Ahmed", "room": "North", "stake": stake,
                                           "reserved": True, "game": game_name, "created": bot_module.time.time()}
                }
                bot._cleanup_expired_wagers = lambda: None
                bot._game_cooldown_notice = lambda *_args: True
                sent, records = [], []
                bot.send_room_text = lambda room, text: sent.append((room, text))
                bot._send_game_winner_card = lambda *_args: None

                def add_points(user, delta):
                    balances[user] += delta
                    return balances[user]

                with patch.object(bot_module, "_get_points", side_effect=lambda user: balances[user]), \
                     patch.object(bot_module, "_add_points", side_effect=add_points), \
                     patch.object(bot_module, "_record_game", side_effect=lambda *args: records.append(args)), \
                     patch.object(bot_module.secrets, "randbelow", return_value=roll):
                    self.assertTrue(bot._queue_wager("South", "Said", game_name, 100_000))

                winner_balance = balances[expected_winner]
                loser_balance = balances[expected_loser]
                self.assertEqual(winner_balance, 3 * stake)  # Own stake returned + opponent's stake.
                self.assertEqual(loser_balance, stake)  # One billion was debited; no extra debit.
                self.assertEqual(len(records), 2)
                loser_record = next(item for item in records if item[0] == expected_loser)
                winner_record = next(item for item in records if item[0] == expected_winner)
                self.assertEqual(loser_record[2], -stake)
                self.assertEqual(loser_record[3], stake)
                self.assertEqual(winner_record[2], stake)
                self.assertTrue(any("-1b" in text for _, text in sent))

    def test_million_bank_result_has_no_artificial_reveal_sleep(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._game_cooldown_notice = lambda *_args: True
        bot._configured_room_language = lambda _room: "ar"
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            bot_module, "MONEY_GAME_WIN_STATE_FILE", Path(temp_dir) / "money-state.json"
        ), patch.object(bot_module.secrets, "randbelow", return_value=99), patch.object(
            bot_module, "_record_game", lambda *_args: None
        ), patch.object(bot_module.time, "sleep", side_effect=AssertionError("unexpected delay")):
            self.assertTrue(bot._million_bank_game("North", "Player"))
        self.assertEqual(len(sent), 2)
        self.assertIn("جاري البحث", sent[0][1])
        self.assertIn("لم يحالفه الحظ", sent[1][1])

    def test_million_bank_uses_one_minute_cooldown_and_three_percent_win_chance(self):
        for roll, won in ((2, True), (3, False)):
            with self.subTest(roll=roll):
                bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
                cooldowns, sent, awards = [], [], []
                bot._game_cooldown_notice = lambda _room, _user, seconds, _name: cooldowns.append(seconds) or True
                bot.send_room_text = lambda room, text: sent.append((room, text))
                bot._configured_room_language = lambda _room: "ar"
                bot.user_photos = {}
                bot._lookup_profile_photo = lambda _user: ""
                bot.connected_rooms = set()
                bot.log = lambda *_args: None
                bot._game_award = lambda user, amount: awards.append((user, amount))

                def send_card(_game, _winner, rooms, send_delay=0.0, before_each_room=None):
                    if before_each_room:
                        for target_room in rooms:
                            before_each_room(target_room)

                bot._send_game_winner_card = send_card
                with tempfile.TemporaryDirectory() as temp_dir, patch.object(
                    bot_module, "MONEY_GAME_WIN_STATE_FILE", Path(temp_dir) / "money-state.json"
                ), patch.object(
                    bot_module, "MONEY_GAME_WIN_HISTORY_FILE", Path(temp_dir) / "money-winners.json"
                ), patch.object(bot_module.secrets, "randbelow", return_value=roll), patch.object(
                    bot_module, "_record_game", return_value=None
                ):
                    self.assertTrue(bot._million_bank_game("North", "Player"))
                    history = bot_module._load_local_json(bot_module.MONEY_GAME_WIN_HISTORY_FILE, {})
                self.assertEqual(cooldowns, [60.0])
                self.assertEqual(bool(awards), won)
                self.assertEqual(awards, ([ ("Player", 1_000_000) ] if won else []))
                self.assertIn("تم الحصول على المليون" if won else "لم يحالفه الحظ", sent[-1][1])
                self.assertEqual(bool(history.get("million")), won)

    def test_billion_uses_configured_one_minute_cooldown_and_three_percent_win_chance(self):
        for roll, won in ((2, True), (3, False)):
            with self.subTest(roll=roll):
                bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
                cooldowns, sent, awards = [], [], []
                bot._snake_command = lambda *_args: False
                bot._ludo_command = lambda *_args: False
                bot.stock_pending = {}
                bot._handle_pending_bot_choice = lambda *_args: False
                bot._game_cooldown_notice = lambda _room, _user, seconds, _name: cooldowns.append(seconds) or True
                bot.send_room_text = lambda room, text: sent.append((room, text))
                bot._configured_room_language = lambda _room: "ar"
                bot.send_room_media = lambda *_args: None
                bot.user_photos = {bot_module._norm_user("Player"): "photo"}
                bot._active_rooms = lambda: ["North"]
                bot.log = lambda *_args: None
                bot._game_award = lambda user, amount: awards.append((user, amount))
                with tempfile.TemporaryDirectory() as temp_dir, patch.object(
                    bot_module, "MONEY_GAME_WIN_STATE_FILE", Path(temp_dir) / "money-state.json"
                ), patch.object(
                    bot_module, "MONEY_GAME_WIN_HISTORY_FILE", Path(temp_dir) / "money-winners.json"
                ), patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
                    bot_module, "_games_enabled_for_room", return_value=True
                ), patch.object(bot_module.secrets, "randbelow", return_value=roll), patch.object(
                    bot_module, "_record_game", return_value=None
                ), patch.object(bot_module, "_public_base_url", return_value=""):
                    self.assertTrue(bot.handle_game_command("North", "billion", "Player"))
                    history = bot_module._load_local_json(bot_module.MONEY_GAME_WIN_HISTORY_FILE, {})
                self.assertEqual(cooldowns, [60.0])
                self.assertEqual(bool(awards), won)
                self.assertEqual(awards, ([ ("Player", 1_000_000_000) ] if won else []))
                self.assertIn("تم الحصول على المليار" if won else "لم يحصل على المليار", sent[-1][1])
                self.assertEqual(bool(history.get("billion")), won)

    def test_money_winner_long_text_is_local_and_short_game_specific_text_precedes_card(self):
        for game in ("million", "billion"):
            with self.subTest(game=game):
                bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
                sent, cards, awards, pair_order = [], [], [], []
                bot._game_cooldown_notice = lambda *_args: True
                bot._configured_room_language = lambda room: "en" if room == "South" else "ar"
                expected_local = bot_module._money_game_win_text(game, "Player", "ar")
                expected_remote = bot_module._money_game_short_win_text(game, "Player", "en")

                def send_text(target_room, text):
                    sent.append((target_room, text))
                    if text in (expected_local, expected_remote):
                        pair_order.append(("text", target_room))

                bot.send_room_text = send_text
                bot.send_room_media = lambda *_args: None
                bot.user_photos = {}
                bot._lookup_profile_photo = lambda _user: ""
                bot.connected_rooms = {"North", "South"}
                bot._active_rooms = lambda: ["South", "North"]
                bot.log = lambda *_args: None
                bot._game_award = lambda user, amount: awards.append((user, amount))

                def send_winner_card(game_key, winner_name, target_rooms, send_delay=0.0,
                                     before_each_room=None):
                    cards.append((game_key, winner_name, target_rooms, send_delay))
                    for target_room in target_rooms:
                        before_each_room(target_room)
                        pair_order.append(("image", target_room))

                bot._send_game_winner_card = send_winner_card
                if game == "billion":
                    bot._snake_command = lambda *_args: False
                    bot._ludo_command = lambda *_args: False
                    bot.stock_pending = {}
                    bot._handle_pending_bot_choice = lambda *_args: False

                with tempfile.TemporaryDirectory() as temp_dir, patch.object(
                    bot_module, "MONEY_GAME_WIN_STATE_FILE", Path(temp_dir) / "money-state.json"
                ), patch.object(
                    bot_module, "MONEY_GAME_WIN_HISTORY_FILE", Path(temp_dir) / "money-winners.json"
                ), patch.object(bot_module.secrets, "randbelow", return_value=0), patch.object(
                    bot_module, "_record_game", return_value=None
                ), patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
                    bot_module, "_games_enabled_for_room", return_value=True
                ), patch.object(bot_module, "_public_base_url", return_value=""), patch.object(
                    bot_module.time, "sleep", return_value=None
                ):
                    if game == "million":
                        bot._million_bank_game("North", "Player")
                    else:
                        bot.handle_game_command("North", "billion", "Player")

                winner_texts = [
                    (room, text) for room, text in sent
                    if "جاري البحث" not in text and "Searching for" not in text
                ]
                self.assertEqual(winner_texts[0], ("North", bot_module._money_game_win_text(game, "Player", "ar")))
                self.assertEqual(winner_texts[1], ("South", bot_module._money_game_short_win_text(game, "Player", "en")))
                self.assertNotIn("🌹", winner_texts[1][1])
                arabic_short = bot_module._money_game_short_win_text(game, "Player", "ar")
                if game == "billion":
                    self.assertIn("💵", winner_texts[1][1])
                    self.assertIn("💸", arabic_short)
                else:
                    self.assertIn("🟩", winner_texts[1][1])
                    self.assertIn("🟨", arabic_short)
                self.assertNotIn("Prize:", winner_texts[1][1])
                self.assertEqual(cards[0][2], ["North", "South"])
                self.assertEqual(pair_order, [
                    ("text", "North"), ("image", "North"),
                    ("text", "South"), ("image", "South"),
                ])
                self.assertTrue(awards)

    def test_winner_card_sends_room_callback_immediately_before_each_image(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        order = []
        bot.user_photos = {}
        bot._lookup_profile_photo = lambda _user: ""
        bot._effective_room_language = lambda _room: "ar"
        bot.send_room_media = lambda room, _url, _kind: order.append(("image", room))
        bot._verify_public_media_url = lambda *_args: True
        bot.log = lambda *_args: None

        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir)
            (assets_dir / "prize.jpg").write_bytes(b"test-image")
            with patch.object(bot_module, "ASSETS_DIR", assets_dir), patch.object(
                bot_module, "GAME_IMAGE_FILES", {"million": "prize.jpg"}
            ), patch.object(bot_module, "_public_base_url", return_value="https://media.example"), patch.object(
                bot_module, "render_game_winner_card", return_value=type("Card", (), {"name": "winner.jpg"})()
            ):
                result = bot._send_game_winner_card(
                    "million", "Winner", ["North", "South"],
                    before_each_room=lambda room: order.append(("text", room)),
                )

        self.assertTrue(result)
        self.assertEqual(order, [
            ("text", "North"), ("image", "North"),
            ("text", "South"), ("image", "South"),
        ])

    def test_master_can_open_and_close_million_and_billion_win_rates(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args: False
        replies = []
        bot.send_private_text = lambda _user, text: replies.append(text)
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            bot_module, "MONEY_GAME_SETTINGS_FILE", Path(temp_dir) / "money-settings.json"
        ), patch.object(bot_module, "_is_master_name", return_value=True):
            for command in ("فتح المليون", "غلق المليون", "فتح مليار", "غلق مليار"):
                self.assertTrue(bot._handle_management_command_impl("", command, "Master", is_private=True))
            self.assertEqual(bot_module._load_local_json(bot_module.MONEY_GAME_SETTINGS_FILE, {}), {
                "million": False, "billion": False,
            })
        self.assertIn("نسبة الربح الآن 30%", replies[0])
        self.assertIn("عادت نسبة الربح إلى 3%", replies[1])

    def test_money_game_wins_are_separated_and_each_game_has_independent_persistent_gap(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            bot_module, "MONEY_GAME_WIN_STATE_FILE", Path(temp_dir) / "money-state.json"
        ), patch.object(bot_module.secrets, "randbelow", return_value=0):
            # Even an RNG that returns a win every time cannot produce
            # consecutive jackpots; the gap is separate for each game type.
            results = (
                bot_module._money_game_roll("billion"),
                bot_module._money_game_roll("million"),
                bot_module._money_game_roll("billion"),
                bot_module._money_game_roll("million"),
                bot_module._money_game_roll("billion"),
                bot_module._money_game_roll("million"),
            )
        self.assertEqual(results, (True, True, False, False, True, True))

    def test_enter_my_rooms_joins_every_saved_room(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.known_rooms = set()
        bot._room_list_commands = lambda *_args: False
        sent = []
        bot.send_private_text = lambda _user, text: sent.append(text)
        joined = []

        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(bot_module, "_persistent_rooms", return_value=["North", "South", "North"]), patch.object(
            bot_module, "_is_primary_master", return_value=True
        ), patch.object(bot_module.threading, "Thread", ImmediateThread):
            bot._join_rooms_serially = lambda rooms, sender, fast_restore=False: joined.append(
                (rooms, sender, fast_restore)
            )
            self.assertTrue(bot._handle_management_command_impl("", "دخول غرفي", "Master", is_private=True))

        self.assertEqual(joined, [(["North", "South"], "Master", False)])
        self.assertIn("2 غرفة", sent[-1])

    def test_enter_server_rooms_fetches_then_joins_in_one_operation(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.known_rooms = set()
        bot._room_list_commands = lambda *_args: False
        bot._effective_room_language = lambda _room: "ar"
        requested = []
        bot._request_full_room_sync = lambda sender, room, language=None, join_after=False: requested.append(
            (sender, room, language, join_after)
        ) or True
        bot.send_private_text = lambda *_args: None
        with patch.object(bot_module, "_is_primary_master", return_value=True), patch.object(
            bot_module, "_is_master_name", return_value=True
        ):
            self.assertTrue(
                bot._handle_management_command_impl("", "دخول الغرف", "Master", is_private=True)
            )
        self.assertEqual(requested, [("Master", "", "ar", True)])

    def test_fast_room_restore_sends_all_rooms_without_waiting_for_ack(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.connected_rooms = set()
        bot._pending_room_joins = {"north": {"created": time.time()}}
        bot._room_bulk_lock = threading.RLock()
        bot.join_room = lambda room, **_kwargs: True
        bot.log = lambda *_args: None
        with patch.dict(bot_module.os.environ, {"FAST_ROOM_RESTORE_DELAY_SECONDS": "0.08"}), patch.object(
            bot_module.time, "sleep", lambda *_args: None
        ):
            result = bot._join_rooms_serially(["North", "South"], fast_restore=True)
        self.assertEqual(result, {"sent": 2, "skipped": 0})

    def test_points_top_collapses_decorated_duplicate_accounts(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.send_private_text = lambda _user, text: setattr(bot, "top_message", text)
        with patch.object(bot_module, "_points_data", return_value={
            "sourea": {"username": "sourea", "points": 1_000_000_000},
            "decorated": {"username": "𝐒𝐎𝐔☀𝐑𝐄𝐀", "points": 2_000_000_000},
            "other": {"username": "other", "points": 3_000_000},
        }):
            self.assertTrue(bot._handle_management_command_impl("", "توب النقاط", "Master", is_private=True))
        self.assertEqual(bot.top_message.count("𝐒𝐎𝐔☀𝐑𝐄𝐀"), 1)
        self.assertNotIn("sourea — 1b", bot.top_message)
        self.assertIn("𝐒𝐎𝐔☀𝐑𝐄𝐀 — 2b", bot.top_message)

    def test_auto_ban_candidate_allows_known_non_supervision_roles_only(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {"North": {
            "Owner": "owner", "Admin": "admin", "Moderator": "moderator",
            "Member": "member", "NoRank": "none", "OtherRank": "vip",
        }}
        with patch.object(bot_module, "_is_master_name", side_effect=lambda name: str(name).casefold() == "master"), patch.object(
            bot_module, "_is_room_creator", return_value=False
        ):
            for protected in ("Owner", "Admin", "Moderator", "Master"):
                self.assertFalse(bot_module._auto_ban_candidate(bot, "North", protected), protected)
            self.assertTrue(bot_module._auto_ban_candidate(bot, "North", "Member"))
            self.assertTrue(bot_module._auto_ban_candidate(bot, "North", "NoRank"))
            self.assertTrue(bot_module._auto_ban_candidate(bot, "North", "OtherRank"))
            # A blank event field must not erase a known moderator/owner rank.
            self.assertFalse(bot_module._auto_ban_candidate(bot, "North", "Admin", ""))
            self.assertFalse(bot_module._auto_ban_candidate(bot, "North", "UnknownUser", ""))
            self.assertFalse(bot_module._auto_ban_candidate(bot, "North", "NewAdmin", "admin"))

    def test_profanity_filter_bans_every_room_rank_but_never_the_master(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {"North": {
            "Owner": "owner", "Admin": "admin", "Moderator": "moderator",
            "Member": "member", "VIP": "vip",
        }}
        with patch.object(bot_module, "_is_master_name", side_effect=lambda name: str(name).casefold() == "master"), patch.object(
            bot_module, "_is_room_creator", return_value=False
        ):
            for ordinary in ("Owner", "Admin", "Moderator", "Member", "VIP", "NoRank", "UnknownUser"):
                self.assertTrue(bot_module._profanity_ban_candidate(bot, "North", ordinary), ordinary)
            self.assertFalse(bot_module._profanity_ban_candidate(bot, "North", "Master"))
            self.assertTrue(bot_module._profanity_ban_candidate(bot, "North", "NewAdmin", "room_admin"))
        with patch.object(bot_module, "BOT_ID", "test-bot"):
            self.assertFalse(bot_module._profanity_ban_candidate(bot, "North", "test-bot"))

    def test_private_protection_menu_has_nine_options_and_applies_only_from_master_dm(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.last_joined_room = ""
        bot._pending_protection_number = {}
        bot._room_list_commands = lambda *_args: False
        private, public, saved = [], [], []
        bot.send_private_text = lambda user, text: private.append((user, text))
        bot.send_room_text = lambda room, text: public.append((room, text))
        is_master = lambda name: str(name).casefold() == "master"
        with patch.object(bot_module, "_is_primary_master", side_effect=is_master):
            self.assertTrue(bot._handle_management_command_impl("", "حماية@North", "Master", is_private=True))
            menu = private[-1][1]
            options = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
            self.assertEqual(sorted(menu.index(item) for item in options), [menu.index(item) for item in options])
            self.assertIn("حظر IP", menu)
            self.assertIn("حظر الحسابات بلا صورة", menu)
            self.assertIn("North", bot._pending_protection_number[bot_module._norm_user("Master")]["room"])

            with patch.object(bot_module, "_save_room_protection", side_effect=lambda room, **changes: saved.append((room, changes))), patch.object(
                bot_module, "_save_room_moderation", lambda *_args, **_kwargs: None
            ):
                # A room creator/master may use the numbered menu in the same room.
                with patch.object(bot_module, "_is_room_creator", return_value=True):
                    self.assertTrue(bot._handle_management_command_impl("North", "3", "Master", is_private=False))
                self.assertEqual(saved, [("North", {"flood": True})])
                self.assertTrue(public)
                self.assertTrue(bot._handle_management_command_impl("", "حماية@North", "Master", is_private=True))
                self.assertTrue(bot._handle_management_command_impl("", "3", "Master", is_private=True))
            self.assertEqual(saved, [("North", {"flood": True}), ("North", {"flood": True})])

            self.assertTrue(bot._handle_management_command_impl("North", "حماية@North", "Master", is_private=False))
            self.assertIn("قائمة حماية الغرفة", public[-1][1])
            self.assertTrue(bot._handle_management_command_impl("", "حماية@North", "Guest", is_private=True))
            self.assertIn("ماستر", private[-1][1])

    def test_room_protection_menu_keeps_current_room_for_options_five_and_six(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = "RoomA"
        bot.last_joined_room = "RoomB"
        bot._pending_protection_number = {}
        bot._room_list_commands = lambda *_args: False
        bot.send_room_text = lambda *_args: None
        saved = []
        with patch.object(bot_module, "_is_room_creator", return_value=True), patch.object(
            bot_module, "_is_master_name", return_value=False
        ), patch.object(bot_module, "_is_primary_master", return_value=False), patch.object(
            bot_module, "_save_room_protection", side_effect=lambda room, **changes: saved.append((room, changes))
        ):
            self.assertTrue(bot._handle_management_command_impl("RoomA", "حماية", "Creator", is_private=False))
            self.assertTrue(bot._handle_management_command_impl("RoomA", "5", "Creator", is_private=False))
            self.assertTrue(bot._handle_management_command_impl("RoomA", "حماية", "Creator", is_private=False))
            self.assertTrue(bot._handle_management_command_impl("RoomA", "6", "Creator", is_private=False))
        self.assertEqual(saved, [("RoomA", {"joinleave": True}), ("RoomA", {"joinleave": False})])

    def test_inv_finishes_without_leaving_the_room(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.invites_enabled = True
        bot.invite_silent_master = False
        bot.invite_lock = __import__("threading").Lock()
        bot.invite_pending = True
        bot.invite_sent = set()
        bot._inv_response_room = "North"
        bot._inv_response_to = ""
        bot.send_private_invite = lambda username, room: True
        bot.send_room_text = lambda *_args: None
        bot.log = lambda *_args: None
        bot.leave_room = lambda *_args: (_ for _ in ()).throw(AssertionError("inv must not leave the room"))
        bot._finish_invites("North", ["Member"])
        self.assertFalse(bot.invite_pending)

    def test_a1_ns_advances_one_management_section_and_m_command_is_supported(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.help_pages = {}
        bot.help_page_part = {}
        bot.help_game_part = {}
        bot._room_list_commands = lambda *_args: False
        shown = []
        bot._send_help = lambda **kwargs: shown.append(kwargs)
        actions = []
        bot.request_admin_action = lambda *args, **kwargs: actions.append((args, kwargs))
        with patch.object(bot_module, "_is_primary_master", side_effect=lambda name: str(name).casefold() == "master"), patch.object(
            bot_module, "_is_master_name", side_effect=lambda name: str(name).casefold() == "master"
        ):
            self.assertTrue(bot._handle_management_command_impl("", "a1", "Master", is_private=True))
            self.assertTrue(bot._handle_management_command_impl("", "ns", "Master", is_private=True))
            self.assertTrue(bot._handle_management_command_impl("North", "m@Guest", "Master", is_private=True))
        self.assertEqual([(x["page"], x["game_part"]) for x in shown], [(1, 1), (1, 2)])
        self.assertTrue(bot_module._looks_like_admin_command("m@Guest"))
        self.assertEqual(actions[0][0][1:3], ("Guest", "member"))
        sections = bot_module._default_help_sections()
        rendered = []
        bot._send_help_chunks = lambda _packet, text, **_kwargs: rendered.append(text)
        bot._send_help_section(private_to="Master", page=1, part=1)
        self.assertIn("m@اسم", sections[1][1])
        self.assertNotIn("bl@", sections[1][0])
        self.assertIn("اكتب ns", rendered[0])
        self.assertTrue(bot_module._looks_like_admin_command("حماية@North"))
        self.assertIn("snare", sections[3][3])
        for page in (1, 3):
            for idx, section in enumerate(sections[page]):
                if page == 3:
                    footer = "" if idx == 0 else (
                        "\n\n📌 للقائمة التالية اكتب ns" if idx < len(sections[page]) - 1
                        else "\n\n📌 هذه آخر قائمة في A3."
                    )
                else:
                    footer = (
                        "\n\n📌 للقائمة التالية اكتب ns" if idx < len(sections[page]) - 1
                        else "\n\n✅ انتهت أقسام هذه القائمة."
                    )
                packet_type = "chat_message" if page == 1 else "room_message"
                target = {"to": "Master"} if page == 1 else {"room": "Test"}
                packet = bot_module.encode_query(
                    packet_type, type_="text", body=section + footer, **target
                )
                self.assertLessEqual(len(packet), 1008, f"help page={page} part={idx + 1}")

    def test_normal_song_request_sends_audio_before_caption_without_full_download(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        sent = []
        bot.send_room_text = lambda room, text: sent.append(("text", room, text))
        bot.send_room_media = lambda room, url, kind, duration=0: sent.append(("media", room, url, kind, duration)) or True
        bot._audius_live_source = lambda _query: {
            "url": "https://cdn.example/track.mp3", "duration": 42,
            "title": "Fast Track", "uploader": "Artist",
        }
        bot._music_download = lambda _query: (_ for _ in ()).throw(AssertionError("full download should not be used"))
        bot._active_rooms = lambda: ["Room A", "Room B"]
        bot.connected_rooms = {"Room A", "Room B"}
        bot.log = lambda *_args: None
        bot.report_master_error = lambda *_args: None

        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(bot_module, "_public_base_url", lambda: "https://bot.example"), patch.object(
            bot_module, "_record_media_publication", lambda *_args: None
        ), patch.object(bot_module.threading, "Thread", ImmediateThread):
            self.assertTrue(bot.handle_music_command(
                "Room A", ".sa Fast Track", "Tester",
                with_reactions=False,
            ))

        media_index = next(i for i, item in enumerate(sent) if item[0] == "media")
        caption_index = next(i for i, item in enumerate(sent) if item[0] == "text" and "تم تشغيل الأغنية" in item[2])
        self.assertLess(media_index, caption_index)
        self.assertEqual(sent[media_index][1:4], ("Room A", "https://cdn.example/track.mp3", "audio"))

    def test_normal_song_uses_direct_audio_before_full_download(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        sent = []
        bot.send_room_text = lambda room, text: sent.append(("text", room, text))
        bot.send_room_media = lambda room, url, kind, duration=0: sent.append(("media", room, url, kind, duration)) or True
        bot._audius_live_source = lambda _query: None
        bot._music_live_source = lambda query: {
            "url": "https://cdn.example/direct.mp3", "duration": 35,
            "title": query, "uploader": "Direct source",
        }
        bot._music_download = lambda _query: (_ for _ in ()).throw(AssertionError("full download should be fallback only"))
        bot.log = lambda *_args: None
        bot.report_master_error = lambda *_args: None

        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(bot_module, "_public_base_url", lambda: "https://bot.example"), patch.object(
            bot_module, "_record_media_publication", lambda *_args: None
        ), patch.object(bot_module.threading, "Thread", ImmediateThread):
            self.assertTrue(bot.handle_music_command("Hall", ".sa Fast Song", "Tester", with_reactions=False))

        self.assertTrue(any(item[0] == "media" and item[2] == "https://cdn.example/direct.mp3" for item in sent))

    def test_music_fast_source_uses_first_ready_resolver(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        audius_started = threading.Event()

        def slow_audius(_query):
            audius_started.set()
            time.sleep(0.25)
            return {"url": "https://cdn.example/slow.mp3", "title": "slow"}

        bot._audius_live_source = slow_audius
        bot._music_live_source = lambda _query: {
            "url": "https://cdn.example/fast.mp3", "title": "fast", "uploader": "Direct",
        }
        bot.log = lambda *_args: None

        sources = iter(bot._music_fast_sources("fast song"))
        result = next(sources)
        alternate = next(sources)

        self.assertTrue(audius_started.wait(1))
        self.assertEqual(result["url"], "https://cdn.example/fast.mp3")
        self.assertEqual(alternate["url"], "https://cdn.example/slow.mp3")
        self.assertIn("direct", bot._music_source_latency_ewma)
        self.assertIn("Audius", bot._music_source_latency_ewma)

    def test_normal_music_uses_next_fast_source_if_first_media_send_is_rejected(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        candidates = [
            {"url": "https://cdn.example/first.mp3", "title": "Song", "duration": 30, "source": "first"},
            {"url": "https://cdn.example/second.mp3", "title": "Song", "duration": 30, "source": "second"},
        ]
        bot._music_fast_sources = lambda _query: iter(candidates)
        sent = []
        bot.send_room_text = lambda room, text: sent.append(("text", room, text))
        def send_media(room, url, kind, duration=0):
            sent.append(("media", room, url, kind, duration))
            return url.endswith("second.mp3")
        bot.send_room_media = send_media
        bot.log = lambda *_args: None
        bot.report_master_error = lambda *_args: None

        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(bot_module, "_spotify_track_metadata", side_effect=AssertionError("plain title must not wait for Spotify")), patch.object(
            bot_module, "_public_base_url", lambda: "https://bot.example"
        ), patch.object(bot_module, "_record_media_publication", lambda *_args: None), patch.object(
            bot_module.threading, "Thread", ImmediateThread
        ):
            self.assertTrue(bot.handle_music_command("Hall", ".sa Fast Song", "Tester", with_reactions=False))

        media_urls = [item[2] for item in sent if item[0] == "media"]
        self.assertEqual(media_urls, ["https://cdn.example/first.mp3", "https://cdn.example/second.mp3"])
        self.assertEqual(bot.music_current[bot_module._norm_user("Tester")]["url"], "https://cdn.example/second.mp3")

    def test_live_music_moves_to_next_source_when_fastest_cannot_start(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        bot._last_live_play_status_by_room = {}
        bot._music_fast_sources = lambda _query: iter([
            {"url": "https://cdn.example/first-live.mp3", "title": "Song", "duration": 30, "source": "first"},
            {"url": "https://cdn.example/second-live.mp3", "title": "Song", "duration": 30, "source": "second"},
        ])
        bot._bot_is_room_owner = lambda _room: True
        attempts = []
        def play(room, url, duration=0):
            attempts.append(url)
            started = url.endswith("second-live.mp3")
            bot._last_live_play_status_by_room[room] = "started" if started else "failed"
            return started
        bot._play_music_in_live_room = play
        bot.send_room_text = lambda *_args: True
        bot.log = lambda *_args: None
        bot.report_master_error = lambda *_args: None

        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(bot_module, "_public_base_url", lambda: "https://bot.example"), patch.object(
            bot_module, "_record_media_publication", lambda *_args: None
        ), patch.object(bot_module.threading, "Thread", ImmediateThread):
            self.assertTrue(bot.handle_music_command("Hall", ".sa Fast Song", "Tester", with_reactions=False, live_stream=True))
        self.assertEqual(attempts, ["https://cdn.example/first-live.mp3", "https://cdn.example/second-live.mp3"])

    def test_queued_live_track_resolves_alternate_excluding_failed_url(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        calls = []
        fallback = {"url": "https://cdn.example/backup.mp3", "source": "backup", "duration": 45}
        def sources(query, exclude_urls=None):
            calls.append((query, set(exclude_urls or ())))
            return iter([fallback])
        bot._music_fast_sources = sources
        track = {
            "url": "https://cdn.example/failed.mp3",
            "fallback_search_query": "song artist",
            "fallback_source_iterator": iter(()),
            "attempted_source_urls": {"https://cdn.example/failed.mp3"},
        }
        result = bot._next_music_fallback_source("Hall", track)
        self.assertEqual(result, fallback)
        self.assertEqual(calls, [("song artist", {"https://cdn.example/failed.mp3"})])

    def test_spotify_link_is_resolved_before_playable_source_search(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        searched, sent = [], []
        bot.send_room_text = lambda room, text: sent.append(("text", room, text))
        bot.send_room_media = lambda room, url, kind, duration=0: sent.append(("media", room, url, kind, duration)) or True
        bot._audius_live_source = lambda query: (
            searched.append(query) or {
                "url": "https://cdn.example/spotify-match.mp3", "duration": 30,
                "title": "Never Gonna Give You Up", "uploader": "Artist",
            }
        )
        bot.log = lambda *_args: None
        bot.report_master_error = lambda *_args: None

        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(bot_module, "_spotify_track_metadata", return_value={
            "title": "Never Gonna Give You Up", "artist": "Rick Astley",
            "search_query": "Never Gonna Give You Up Rick Astley", "source": "Spotify",
        }), patch.object(bot_module, "_public_base_url", lambda: "https://bot.example"), patch.object(
            bot_module, "_record_media_publication", lambda *_args: None
        ), patch.object(bot_module.threading, "Thread", ImmediateThread):
            self.assertTrue(bot.handle_music_command(
                "Hall", ".sa https://open.spotify.com/track/example", "Tester", with_reactions=False,
            ))

        self.assertEqual(searched, ["Never Gonna Give You Up Rick Astley"])
        self.assertTrue(any(item[0] == "media" and item[2] == "https://cdn.example/spotify-match.mp3" for item in sent))

    def test_spotify_oembed_resolves_track_title_and_artist_without_api_credentials(self):
        response = type("Response", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"title": "Song Name", "author_name": "Artist"},
        })()
        with patch.object(bot_module, "SPOTIFY_CLIENT_ID", ""), patch.object(
            bot_module, "SPOTIFY_CLIENT_SECRET", ""
        ), patch.object(bot_module, "_SPOTIFY_TRACK_CACHE", {}), patch.object(
            bot_module.requests, "get", return_value=response
        ) as mocked_get:
            metadata = bot_module._spotify_track_metadata("https://open.spotify.com/track/abc123")

        self.assertEqual(metadata["search_query"], "Song Name Artist")
        self.assertEqual(metadata["source"], "Spotify")
        self.assertEqual(mocked_get.call_args.args[0], "https://open.spotify.com/oembed")

    def test_lookalike_search_falls_back_to_wikimedia_when_bing_has_no_results(self):
        bing = type("Response", (), {"raise_for_status": lambda self: None, "text": "no image metadata"})()
        commons = type("Response", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"query": {"pages": [
                {"imageinfo": [{"thumburl": "https://upload.wikimedia.org/test.jpg", "mime": "image/jpeg"}]}
            ]}},
        })()
        with patch.object(bot_module.requests, "get", side_effect=[bing, commons]):
            urls = bot_module._search_lookalike_images("test celebrity", limit=3)
        self.assertIn("https://upload.wikimedia.org/test.jpg", urls)

    def test_room_audio_packet_contains_actual_room_and_attachment_url(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.log = lambda *_args: None

        class FakeWebSocket:
            payload = None
            def send_binary(self, payload):
                self.payload = payload

        bot.ws = FakeWebSocket()
        self.assertTrue(bot.send_room_media("North", "https://cdn.example/song.mp3", "audio", 42))
        fields = bot_module.decode_message(bot.ws.payload)
        text = lambda field: fields[field][0].decode("utf-8")
        self.assertEqual(text(1), "room_message")
        self.assertEqual(text(2), "audio")
        self.assertEqual(text(3), "42")
        self.assertEqual(text(6), "North")
        self.assertEqual(text(7), "https://cdn.example/song.mp3")

    def test_oversized_game_result_is_dropped_locally_without_telegram_or_websocket(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        packets = []
        bot.send_query = lambda payload: packets.append(payload)
        bot.log = lambda *_args: None
        telegram = []
        bot._send_long_text_to_telegram = lambda text, title="": telegram.append((text, title)) or True
        text = "🏆 انتهت مباراة الكركيت\n" + "\n".join(
            f"💰 @Player{i} +200,000 نقطة — جائزة الفريق الأول والثاني" for i in range(20)
        )
        self.assertGreater(
            len(bot_module.encode_query("room_message", type_="text", body=text, room="North")),
            1008,
        )

        with patch.dict(bot_module.os.environ, {"WS_MAX_MESSAGE_BYTES": "1008"}):
            self.assertFalse(bot._send_text_packets("room_message", text, room="North"))

        self.assertEqual(len(packets), 1)
        notice_fields = bot_module.decode_message(packets[0])
        self.assertIn("تم تجاهل رسالتك بسبب حجم كبير", bot_module.as_text(notice_fields[5][0]))
        self.assertEqual(telegram, [])

    def test_send_query_hard_caps_payload_at_1008_and_drops_text_locally(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []
        telegram = []
        bot.ws = type("FakeWebSocket", (), {"send_binary": lambda _self, payload: sent.append(payload)})()
        bot.log = lambda *_args: None
        bot._send_long_text_to_telegram = lambda text, title="": telegram.append((text, title)) or True
        text = "x" * 2000
        payload = bot_module.encode_query("room_message", type_="text", body=text, room="North")

        with patch.dict(bot_module.os.environ, {"WS_MAX_MESSAGE_BYTES": "5000"}):
            self.assertFalse(bot.send_query(payload))

        # Low-level transport has no command-sender context. It must drop and
        # log only; _send_text_packets owns the single user-facing notice.
        self.assertEqual(sent, [])
        self.assertEqual(telegram, [])

    def test_oversized_private_text_is_dropped_and_notifies_recipient(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []
        bot.send_query = lambda payload: sent.append(payload) or True
        bot.log = lambda *_args: None
        username = "SenderUser"
        with patch.dict(bot_module.os.environ, {"WS_MAX_MESSAGE_BYTES": "1008"}):
            self.assertFalse(bot._send_text_packets(
                "chat_message", "x" * 2000, to=username,
                oversize_notice_user=username,
            ))
        self.assertEqual(len(sent), 1)
        notice_fields = bot_module.decode_message(sent[0])
        self.assertEqual(bot_module.as_text(notice_fields[4][0]), username)
        self.assertEqual(
            bot_module.as_text(notice_fields[5][0]),
            f"👤 @{username} تم تجاهل رسالتك بسبب حجم كبير.",
        )

    def test_oversized_notice_uses_the_command_executor_name(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []
        bot.send_query = lambda payload: sent.append(payload) or True
        bot.log = lambda *_args: None
        decorated_master = "∫♚∫اݪـــۛــ⃮ـۿــ𓏺𓏺ـيّـــّٰـبــۃ∫♚∫"
        with patch.dict(bot_module.os.environ, {"WS_MAX_MESSAGE_BYTES": "1008"}):
            self.assertFalse(bot._send_text_packets(
                "chat_message", "x" * 2000, to=decorated_master,
                oversize_notice_user=decorated_master,
            ))
        notice_fields = bot_module.decode_message(sent[0])
        self.assertEqual(
            bot_module.as_text(notice_fields[5][0]),
            f"👤 @{decorated_master} تم تجاهل رسالتك بسبب حجم كبير.",
        )

    def test_lower_configured_limit_drops_without_1008_notice(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []
        bot.send_query = lambda payload: sent.append(payload) or True
        bot.log = lambda *_args: None
        with patch.dict(bot_module.os.environ, {"WS_MAX_MESSAGE_BYTES": "500"}):
            self.assertFalse(bot._send_text_packets("chat_message", "x" * 700, to="Player"))
        self.assertEqual(sent, [])

    def test_only_payloads_over_1008_bytes_are_dropped_and_notified(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []
        bot.send_query = lambda payload: sent.append(bytes(payload)) or True
        bot.log = lambda *_args: None
        exactly_1008 = "x" * 979
        exactly_1009 = "x" * 980
        self.assertEqual(
            len(bot_module.encode_query("room_message", type_="text", body=exactly_1008, room="Hall")),
            1008,
        )
        self.assertEqual(
            len(bot_module.encode_query("room_message", type_="text", body=exactly_1009, room="Hall")),
            1009,
        )
        with patch.dict(bot_module.os.environ, {"WS_MAX_MESSAGE_BYTES": "1008"}):
            self.assertTrue(bot._send_text_packets("room_message", exactly_1008, room="Hall"))
            self.assertFalse(bot._send_text_packets("room_message", exactly_1009, room="Hall"))
        self.assertEqual(len(sent), 2)
        self.assertEqual(len(sent[0]), 1008)
        self.assertNotIn(exactly_1009, bot_module.as_text(bot_module.decode_message(sent[1])[5][0]))
        self.assertIn("تم تجاهل رسالتك بسبب حجم كبير", bot_module.as_text(bot_module.decode_message(sent[1])[5][0]))

    def test_games_command_opens_the_a3_catalog_and_sets_ns_navigation(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stock_pending = {}
        bot.help_pages = {}
        bot.help_page_part = {}
        bot.help_game_part = {}
        bot._room_list_commands = lambda *_args: False
        bot._snake_command = lambda *_args: False
        bot._ludo_command = lambda *_args: False
        bot._handle_pending_bot_choice = lambda *_args: False
        sent = []
        bot._send_text_packets = lambda packet_type, text, **kwargs: sent.append(
            (packet_type, text, kwargs)
        ) or True

        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_looks_like_bot_command", return_value=True
        ):
            self.assertTrue(bot.handle_game_command("North", "العاب", "Player"))

        key = ("North", bot_module._norm_user("Player"))
        self.assertEqual(bot.help_pages[key], 3)
        self.assertEqual(bot.help_page_part[key], 1)
        self.assertEqual(bot.help_game_part[key], 1)
        self.assertEqual(sent[0][0], "room_message")
        self.assertEqual(sent[0][1], bot_module._default_help_sections()[3][0])
        self.assertIn("13.", sent[0][1])
        self.assertIn("اكتب ns", sent[0][1])
        self.assertTrue(
            bot._handle_management_command_impl("North", "ns", "Player", is_private=False)
        )
        self.assertEqual(bot.help_page_part[key], 2)
        self.assertEqual(sent[1][1].split("\n\n📌", 1)[0], bot_module._default_help_sections()[3][1])

    def test_normal_song_request_broadcasts_to_all_active_rooms(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        sent = []
        bot.send_room_text = lambda room, text: sent.append(("text", room, text))
        bot.send_room_media = lambda room, url, kind, duration=0: sent.append(("media", room, url, kind, duration)) or True
        bot._audius_live_source = lambda _query: {
            "url": "https://cdn.example/track.mp3", "duration": 42,
            "title": "Fast Track", "uploader": "Artist",
        }
        bot._music_download = lambda _query: (_ for _ in ()).throw(AssertionError("full download should not be used"))
        bot._active_rooms = lambda: ["Room A", "Room B", "Room C"]
        bot.log = lambda *_args: None
        bot.report_master_error = lambda *_args: None

        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(bot_module, "_public_base_url", lambda: "https://bot.example"), patch.object(
            bot_module, "_record_media_publication", lambda *_args: None
        ), patch.object(bot_module.threading, "Thread", ImmediateThread):
            self.assertTrue(bot.handle_music_command(
                "Room A", ".sa Fast Track", "Tester",
                broadcast_all=True, with_reactions=False,
            ))

        media_rooms = [item[1] for item in sent if item[0] == "media"]
        self.assertEqual(media_rooms, ["Room A", "Room B", "Room C"])
        last_media = max(i for i, item in enumerate(sent) if item[0] == "media")
        first_caption = min(i for i, item in enumerate(sent) if item[0] == "text" and "تم تشغيل الأغنية" in item[2])
        self.assertLess(last_media, first_caption)

    def test_live_broadcast_falls_back_when_audius_is_unavailable(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        bot._bot_is_room_owner = lambda _room: True
        bot._audius_live_source = lambda _query: None
        bot._music_live_source = lambda _query: {
            "url": "https://cdn.example/fallback.mp3", "duration": 30,
            "title": "Fallback Song", "uploader": "Backup",
        }
        bot._play_music_in_live_room = lambda room, url, duration: True
        bot.log = lambda *_args: None
        bot.report_master_error = lambda *_args: None
        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)
        with patch.object(bot_module.threading, "Thread", ImmediateThread), patch.object(
            bot_module, "_record_media_publication", lambda *_args: None
        ):
            self.assertTrue(bot.handle_music_command(
                "Syria", ".sa Fallback Song", "Tester",
                live_stream=True, with_reactions=False,
            ))
        self.assertTrue(any("تم تشغيل الأغنية في البث" in text for _, text in sent))

    def test_live_broadcast_can_play_downloaded_local_file_without_public_url(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        sent, played = [], []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        bot._bot_is_room_owner = lambda _room: True
        bot._audius_live_source = lambda _query: None
        bot._music_live_source = lambda _query: None
        local_path = Path("/tmp/talkin2-local-fallback.mp3")
        bot._music_download = lambda _query: ({"title": "Local", "duration": 30}, local_path)
        bot._play_music_in_live_room = lambda room, url, duration: played.append((room, url, duration)) or True
        bot.log = lambda *_args: None
        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)
        with patch.object(bot_module.threading, "Thread", ImmediateThread), patch.object(
            bot_module, "_record_media_publication", lambda *_args: None
        ), patch.object(bot_module, "_public_base_url", lambda: ""):
            self.assertTrue(bot.handle_music_command(
                "Hall", ".sa Local", "Tester", live_stream=True, with_reactions=False,
            ))
        self.assertEqual(played, [("Hall", str(local_path), 30)])
        self.assertTrue(any("تم تشغيل الأغنية في البث" in text for _, text in sent))

    def test_music_failure_is_reported_in_room_without_private_master_error(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot.music_current = {}
        bot.reaction_targets = {}
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        bot._audius_live_source = lambda _query: None
        bot._music_download = lambda _query: (_ for _ in ()).throw(RuntimeError("source unavailable"))
        bot.log = lambda *_args: None
        bot.report_master_error = lambda *_args: (_ for _ in ()).throw(AssertionError("should not DM master"))

        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch.object(bot_module, "_public_base_url", lambda: "https://bot.example"), patch.object(
            bot_module.threading, "Thread", ImmediateThread
        ):
            self.assertTrue(bot.handle_music_command("Hall", ".sa dua", "Tester", with_reactions=False))
        self.assertTrue(any("تعذر جلب الأغنية" in text for _, text in sent))

    def test_live_broadcast_skips_local_path_audio_attachments(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent_packets = []
        bot.send_query = lambda packet: sent_packets.append(packet)
        bot.send_room_text = lambda *_args: None
        bot.log = lambda *_args: None
        bot._live_room_is_active = lambda _room: (
            "Hall", {"room_id": "room-id", "session_id": "session-id"}, True
        )
        bot._livekit_active_Hall = True
        bot._livekit_source_Hall = object()
        class FakeLoop:
            @staticmethod
            def is_closed():
                return False
        bot._livekit_loop_Hall = FakeLoop()
        bot._reassert_live_speaker = lambda *_args: True
        bot._feed_livekit_audio = lambda *_args: True
        bot._live_ready_rooms = set()
        bot._last_live_play_status_by_room = {}
        class NoStartThread:
            def __init__(self, **_kwargs):
                pass
            def start(self):
                pass
        with patch.object(bot_module, "_public_base_url", lambda: ""), patch.object(
            bot_module.threading, "Thread", NoStartThread
        ):
            self.assertTrue(bot._play_music_in_live_room("Hall", "/tmp/local-song.mp3", 30))
        self.assertEqual(sent_packets, [])

    def test_room_protection_exempts_owner_and_moderator_but_not_member(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {
            "Room": {
                "Owner": "owner",
                "Moderator": "moderator",
                "Member": "member",
            }
        }
        with patch.object(bot_module, "_is_master_name", return_value=False), patch.object(
            bot_module, "_is_room_creator", return_value=False
        ):
            self.assertTrue(bot_module._room_manager(bot, "Room", "Owner"))
            self.assertTrue(bot_module._room_manager(bot, "Room", "Moderator"))
            self.assertFalse(bot_module._room_manager(bot, "Room", "Member"))

    def test_cricket_help_has_sixth_page_and_hides_bl_at_alias(self):
        sections = bot_module._default_help_sections()
        self.assertEqual(len(sections[3]), 6)
        self.assertIn(".cr 1", sections[3][5])
        self.assertIn(".cr 0", sections[3][5])
        self.assertIn("موثقين", sections[3][5])
        self.assertIn(".cr 4", sections[3][5])
        self.assertIn("start cricket game", sections[3][5])
        self.assertNotIn("bl@", sections[1][0])
        self.assertNotIn("حظر بكل الغرف", sections[1][0])


    def test_audio_start_waits_for_the_same_frame_count_it_requires_for_success(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stop_event = threading.Event()
        bot.log = lambda *_args: None

        class FakeSource:
            def capture_frame(self, _frame):
                return None

        class FakeLoop:
            @staticmethod
            def is_closed():
                return False

        reached_four_frames = threading.Event()
        allow_remaining_frames = threading.Event()

        class FakeStdout:
            def __init__(self):
                self.read_count = 0

            def read(self, size):
                self.read_count += 1
                if self.read_count == 5:
                    reached_four_frames.set()
                    if not allow_remaining_frames.wait(timeout=2):
                        return b""
                if self.read_count <= 6:
                    return b"\x00" * size
                return b""

        class FakeProcess:
            def __init__(self):
                self.stdout = FakeStdout()
                self.stderr = types.SimpleNamespace(read=lambda: b"")

            def kill(self):
                pass

            def wait(self, **_kwargs):
                pass

        process = FakeProcess()
        bot._livekit_source_Hall = FakeSource()
        bot._livekit_loop_Hall = FakeLoop()
        livekit_module = types.ModuleType("livekit")
        livekit_module.rtc = types.SimpleNamespace(AudioFrame=lambda **_kwargs: object())
        result = []

        with patch.object(bot_module.subprocess, "Popen", return_value=process), patch.dict(
            sys.modules, {"livekit": livekit_module}
        ):
            caller = threading.Thread(
                target=lambda: result.append(bot._feed_livekit_audio("Hall", "https://audio.test/song.mp3", 20)),
                daemon=True,
            )
            caller.start()
            self.assertTrue(reached_four_frames.wait(timeout=2))
            time.sleep(0.05)
            self.assertTrue(caller.is_alive(), "must wait for all required audio frames")
            allow_remaining_frames.set()
            caller.join(timeout=3)

        self.assertFalse(caller.is_alive())
        self.assertEqual(result, [True])


    def test_master_can_disable_and_enable_departure_replies_persistently(self):
        with tempfile.TemporaryDirectory() as temp:
            bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
            bot._room_list_commands = lambda *_args: False
            bot.departure_replies = {"س": ["عاد بسلامة"]}
            bot.departure_farewell_enabled = True
            bot.departure_replies_file = Path(temp) / "departure_replies.json"
            replies = []
            bot.send_private_text = lambda _to, text: replies.append(text)
            bot._last_departed_user_by_room = {bot_module._norm_room("Room"): "leaver"}
            room_replies = []
            bot.send_room_text = lambda _room, text: room_replies.append(text)

            with patch.object(bot_module, "_is_master_name", return_value=True):
                self.assertTrue(bot._handle_management_command_impl("", "توديع@off", "Master", is_private=True))
            self.assertFalse(bot.departure_farewell_enabled)
            self.assertTrue(bot._handle_departure_reply_command("Room", "س"))
            self.assertEqual(room_replies, ["👤 leaver عاد بسلامة"])
            self.assertTrue(bot._handle_departure_reply_command("Room", "x"))
            self.assertEqual(len(room_replies), 1)
            for trigger in ("ب", "ح", "ق"):
                self.assertTrue(bot._handle_departure_reply_command("Room", trigger))
            self.assertEqual(len(room_replies), 4)
            saved = bot_module._load_local_json(bot.departure_replies_file, {})
            self.assertFalse(saved["farewell_enabled"])
            self.assertEqual(saved["replies"], {"س": ["عاد بسلامة"]})

            with patch.object(bot_module, "_is_master_name", return_value=True):
                self.assertTrue(bot._handle_management_command_impl("", "ds@on", "Master", is_private=True))
            self.assertTrue(bot.departure_farewell_enabled)
            self.assertTrue(bot._handle_departure_reply_command("Room", "x"))
            self.assertEqual(len(room_replies), 5)
            self.assertIn("غادرنا بالسلامة", room_replies[-1])

    def test_cricket_requires_saved_verification_even_when_global_gate_is_disabled(self):
        with patch.object(bot_module, "VERIFICATION_ENABLED", False), patch.object(
            bot_module, "_verified_data", lambda: {"verified": True}
        ), patch.object(bot_module, "_vip_data", lambda: {"vip": True}), patch.object(
            bot_module, "_is_master_name", lambda name: str(name).casefold() == "master"
        ):
            self.assertTrue(bot_module._is_cricket_verified_member("Verified"))
            self.assertTrue(bot_module._is_cricket_verified_member("VIP"))
            self.assertTrue(bot_module._is_cricket_verified_member("Master"))
            self.assertFalse(bot_module._is_cricket_verified_member("Guest"))

    def test_cricket_verification_matches_saved_username_record_and_at_prefix(self):
        with patch.object(bot_module, "_verified_data", return_value={
            "legacy-key": {"username": "Verified_Player"},
        }), patch.object(bot_module, "_vip_data", return_value={}), patch.object(
            bot_module, "_is_master_name", return_value=False
        ):
            self.assertTrue(bot_module._is_cricket_verified_member("@verified_player"))
            self.assertTrue(bot_module._is_verified_user(" Verified_Player "))
            self.assertFalse(bot_module._is_cricket_verified_member("other_player"))

    def test_cricket_verification_reads_nested_and_list_legacy_records(self):
        with patch.object(bot_module, "_verified_data", return_value={
            "users": ["List_Verified"],
            "records": {"entry": {"name": "Nested_Verified"}},
        }), patch.object(bot_module, "_vip_data", return_value={}), patch.object(
            bot_module, "_is_master_name", return_value=False
        ):
            self.assertTrue(bot_module._is_cricket_verified_member("List_Verified"))
            self.assertTrue(bot_module._is_cricket_verified_member("Nested_Verified"))

    def test_decorated_verified_name_is_recognized_by_game_and_cricket_gates(self):
        saved_name = "✧Ａlice_𓆩✧"
        with patch.object(bot_module, "_verified_data", return_value={
            "old-record-key": {"username": saved_name, "verified_by": "Staff"},
        }), patch.object(bot_module, "_vip_data", return_value={}), patch.object(
            bot_module, "_is_master_name", return_value=False
        ):
            self.assertTrue(bot_module._is_verified_user("Alice"))
            self.assertTrue(bot_module._is_cricket_verified_member("alice"))
            self.assertEqual(
                bot_module._verified_identity_candidate("opaque-id", "Alice"),
                "Alice",
            )
            self.assertFalse(bot_module._is_verified_user("Staff"))

    def test_decorated_verification_fallback_refuses_ambiguous_collisions(self):
        records = {
            "first": {"username": "a-b"},
            "second": {"username": "a-b✧"},
        }
        self.assertFalse(bot_module._saved_identity_matches(records, "a-b!"))
        self.assertTrue(bot_module._saved_identity_matches(records, "a-b"))

    def test_vi_command_still_saves_a_new_verified_account(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args, **_kwargs: False
        sent = []
        saved = []
        bot.send_private_text = lambda target, message: sent.append((target, message))
        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_is_verification_manager", return_value=True
        ), patch.object(
            bot_module, "_verified_data", return_value={}
        ), patch.object(bot_module, "_vip_data", return_value={}), patch.object(
            bot_module, "_save_local_json", side_effect=lambda path, data: saved.append((path, data))
        ):
            self.assertTrue(bot._handle_management_command_impl("", "vi@New_User", "Master", is_private=True))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0][0], bot_module.VERIFIED_FILE)
        self.assertIn("new_user", saved[0][1])
        self.assertIn("تم توثيق", sent[-1][1])

    def test_winner_awards_are_split_exactly_and_passed_to_result_card(self):
        with tempfile.TemporaryDirectory() as temp:
            awarded = []
            game = CricketGame(Path(temp) / "cricket_state.json", reward=lambda name, amount: awarded.append((name, amount)))
            match = game._new_match("North", "north", "live", 3)
            match["id"] = "awardtest"
            match["rooms"] = [
                {"key": "north", "name": "North", "players": ["N1", "N2", "N3"]},
                {"key": "south", "name": "South", "players": ["S1", "S2", "S3"]},
            ]
            match["teams"] = {"north": "attack", "south": "defense"}
            match["scores"] = {"attack": 25, "defense": 10}
            match["player_scores"] = {"N1": 10, "N2": 8, "N3": 7, "S1": 4, "S2": 3, "S3": 3}
            captured = []
            with patch("cricket_result.render_result_image", side_effect=lambda **kwargs: captured.append(kwargs) or "cricket_result_awardtest.png"):
                def finish(data):
                    data["match"] = match
                    game._finish(data, match, game._participants(match))
                game.state.mutate(finish)

            expected = {"N1": 333_333_334, "N2": 333_333_333, "N3": 333_333_333}
            self.assertEqual(sum(amount for _, amount in awarded), 1_000_000_000)
            self.assertEqual(dict(awarded), expected)
            self.assertEqual(captured[0]["player_awards"], expected)
            self.assertEqual(sum(game.get_points(name) for name in expected), 1_000_000_000)
            self.assertTrue(any("cricket_result_awardtest.png" in event["images"] for event in game.events_after("North", 0)))

    def test_scorecard_renderer_accepts_per_player_awards(self):
        with tempfile.TemporaryDirectory() as temp:
            filename = render_result_image(
                match_id="visualtest",
                team1_name="North", team1_players=["N1", "N2"], team1_score=18,
                team2_name="South", team2_players=["S1", "S2"], team2_score=12,
                player_scores={"N1": 10, "N2": 8, "S1": 7, "S2": 5},
                player_awards={"N1": 100_000, "N2": 100_000},
                winner="North", prize=200_000, output_dir=temp,
            )
            path = Path(temp) / filename
            self.assertGreater(path.stat().st_size, 0)
            from PIL import Image
            with Image.open(path) as image:
                self.assertEqual(image.size, (1500, 900))


class PointsAndPublishingHardeningRegressions(unittest.TestCase):
    def test_snapshot_reconciliation_keeps_only_the_highest_duplicate_balance(self):
        merged = bot_module._merge_points_snapshots(
            {"sourea": {"username": "sourea", "points": 5_000_000_000}},
            {"decorated": {"username": "𝐒𝐎𝐔☀𝐑𝐄𝐀", "points": 7_000_000_000}},
        )
        self.assertEqual(len(merged["accounts"]), 1)
        self.assertEqual(next(iter(merged["accounts"].values()))["points"], 7_000_000_000)
        self.assertEqual(merged["version"], 2)

    def test_snapshot_reconciliation_does_not_guess_between_ambiguous_names(self):
        merged = bot_module._merge_points_snapshots(
            {
                "one": {"username": "A-B", "points": 1_000},
                "two": {"username": "AB", "points": 2_000},
            },
            {"three": {"username": "A.B", "points": 3_000}},
        )
        self.assertEqual(len(merged["accounts"]), 3)

    def test_transfer_resolves_exact_decorated_username_and_commits_both_balances(self):
        decorated = "឵⇠\n𓆩〭〬🌸⃝ʀɛʍǟռ🥂⸼꯭᪳⃕🖇〭〬𓆪"
        accounts = {
            "sender": {"username": "sender", "points": 2_000_000_000},
            "target": {"username": decorated, "points": 5_000_000_000},
        }
        saved = []
        with patch.object(bot_module, "_POINTS_CACHE", None), patch.object(
            bot_module, "_POINTS_TRANSFER_CACHE", None
        ), patch.object(bot_module, "_STATE_DB_ENABLED", False), patch.object(
            bot_module, "_points_data", return_value=accounts
        ), patch.object(bot_module, "_save_local_json", side_effect=lambda path, data, **_kw: saved.append(data)):
            result = bot_module._transfer_points("sender", decorated, 1_000_000_000)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sender_balance"], 1_000_000_000)
        self.assertEqual(result["recipient_balance"], 6_000_000_000)
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(saved[0]["transfer_history"]), 1)

    def test_master_deduction_commits_exact_account_without_overdraft_and_audits_it(self):
        accounts = {"client": {"username": "Decorated_Client", "points": 500}}
        saved = []
        with patch.object(bot_module, "_POINTS_CACHE", None), patch.object(
            bot_module, "_POINTS_TRANSFER_CACHE", None
        ), patch.object(bot_module, "_STATE_DB_ENABLED", False), patch.object(
            bot_module, "_points_data", return_value=accounts
        ), patch.object(
            bot_module, "_save_local_json", side_effect=lambda path, data, **_kw: saved.append(data)
        ):
            result = bot_module._deduct_points("Decorated_Client", 125, actor="Master")
        self.assertTrue(result["ok"])
        self.assertEqual(result["balance"], 375)
        self.assertEqual(len(saved), 1)
        committed = saved[0]
        self.assertEqual(committed["accounts"]["client"]["points"], 375)
        self.assertEqual(committed["transfer_history"][-1]["reason"], "master_deduction by @Master")

    def test_master_deduction_rejects_aliases_and_insufficient_balance_without_saving(self):
        accounts = {"saved_record_key": {"username": "Decorated_Client", "points": 50}}
        saved = []
        with patch.object(bot_module, "_POINTS_CACHE", None), patch.object(
            bot_module, "_POINTS_TRANSFER_CACHE", None
        ), patch.object(bot_module, "_STATE_DB_ENABLED", False), patch.object(
            bot_module, "_points_data", return_value=accounts
        ), patch.object(
            bot_module, "_save_local_json", side_effect=lambda path, data, **_kw: saved.append(data)
        ):
            alias = bot_module._deduct_points("Client", 10, actor="Master")
            insufficient = bot_module._deduct_points("Decorated_Client", 51, actor="Master")
        self.assertEqual(alias["error"], "target_not_found")
        self.assertEqual(insufficient["error"], "insufficient")
        self.assertEqual(saved, [])

    def test_transfer_rejects_unmatched_recipient_without_creating_ghost_account(self):
        accounts = {
            "sender": {"username": "sender", "points": 2_000},
            "target": {"username": "Decorated_Target", "points": 5_000},
        }
        saved = []
        with patch.object(bot_module, "_POINTS_CACHE", None), patch.object(
            bot_module, "_POINTS_TRANSFER_CACHE", None
        ), patch.object(bot_module, "_STATE_DB_ENABLED", False), patch.object(
            bot_module, "_points_data", return_value=accounts
        ), patch.object(bot_module, "_save_local_json", side_effect=lambda path, data, **_kw: saved.append(data)):
            result = bot_module._transfer_points("sender", "other_name", 100)
        self.assertEqual(result["error"], "target_not_found")
        self.assertEqual(saved, [])

    def test_billion_and_million_records_and_leaderboards_are_available_in_both_languages(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        private = []
        bot.send_private_text = lambda user, text: private.append((user, text))
        bot.send_room_text = lambda room, text: private.append((room, text))
        stats = {"plays": 3, "points": 2_000_000_000, "staked": 900_000_000}
        top_rows = [(2_000_000_000, 900_000_000, 3, "Player")]
        with patch.object(bot_module, "_game_stats", return_value=stats), patch.object(
            bot_module, "_game_top", return_value=top_rows
        ):
            for command, expected in (
                ("سجل المليار", "سجل لعبة المليار"),
                ("billion history", "Billion game record"),
                ("سجل المليون", "سجل لعبة المليون"),
                ("million record", "Million game record"),
                ("توب المليار", "توب المليار"),
                ("top b", "Top Billion"),
                ("توب المليون", "توب المليون"),
                ("topm", "Top Million"),
            ):
                self.assertTrue(bot._handle_management_command_impl("North", command, "Player", is_private=True))
                self.assertIn(expected, private[-1][1])

    def test_points_top_shows_fifteen_and_points_summary_shows_full_file_rank(self):
        accounts = {
            f"Player{i}": {"username": f"Player{i}", "points": 2_000_000_000 - i * 10_000}
            for i in range(1, 19)
        }
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        private = []
        bot.send_private_text = lambda user, text: private.append((user, text))
        bot.send_room_text = lambda room, text: private.append((room, text))
        with patch.object(bot_module, "_points_data", return_value=accounts), patch.object(
            bot_module, "_get_points", return_value=2_000_000_000
        ), patch.object(bot_module, "_game_level", return_value=(1551, "سيد الألعاب")):
            self.assertTrue(bot._handle_management_command_impl("North", "توب النقاط", "Viewer", is_private=True))
            top_message = private[-1][1]
            self.assertIn("Player15", top_message)
            self.assertNotIn("Player16", top_message)
            summary = bot_module._points_summary_text("Player18")
            top_summary = bot_module._points_summary_text("Player1")
        self.assertIn("🏆 ترتيبك في ملف النقاط: #18", summary)
        self.assertIn("🏆 ترتيب التوب: #1", top_summary)

    def test_milyari_and_milyoni_show_last_month_game_winners_not_balances(self):
        now = int(time.time())
        history = {
            "billion": [
                {"username": "BillionWinner", "at": now - 60},
                {"username": "BillionWinner", "at": now - 120},
                {"username": "OldBillionWinner", "at": now - 31 * 86400},
            ],
            "million": [
                {"username": "MillionWinner", "at": now - 90},
                {"username": "OldMillionWinner", "at": now - 31 * 86400},
            ],
        }
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._result_pages = {}
        private = []
        bot.send_private_text = lambda user, text: private.append((user, text))
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "money-winners.json"
            history_path.write_text(json.dumps(history), encoding="utf-8")
            with patch.object(bot_module, "MONEY_GAME_WIN_HISTORY_FILE", history_path), patch.object(
                bot_module, "_points_data", side_effect=AssertionError("wallet balances must not be read")
            ):
                for command, expected, excluded, title in (
                    ("ملياري", "@BillionWinner", "@OldBillionWinner", "توب الفائزين بلعبة المليار"),
                    ("مليارات", "@BillionWinner", "@OldBillionWinner", "توب الفائزين بلعبة المليار"),
                    ("مليارت", "@BillionWinner", "@OldBillionWinner", "توب الفائزين بلعبة المليار"),
                    ("مليوني", "@MillionWinner", "@OldMillionWinner", "توب الفائزين بلعبة المليون"),
                    ("ملايين", "@MillionWinner", "@OldMillionWinner", "توب الفائزين بلعبة المليون"),
                ):
                    self.assertTrue(bot._handle_management_command_impl("", command, "Viewer", is_private=True))
                    message = private[-1][1]
                    self.assertIn(title, message)
                    self.assertIn(expected, message)
                    self.assertNotIn(excluded, message)
                    self.assertNotIn("رصيد", message)
                    self.assertNotIn("نقطة", message)

    def test_milyari_top_is_sorted_by_wins_and_limited_to_fifteen_members(self):
        now = int(time.time())
        records = [
            {"username": f"Billionaire{i}", "at": now - i * 100 - win_index}
            for i in range(1, 18)
            for win_index in range(18 - i)
        ]
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._result_pages = {}
        sent = []
        bot.send_private_text = lambda user, text: sent.append(text)
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "money-winners.json"
            history_path.write_text(json.dumps({"billion": records}), encoding="utf-8")
            with patch.object(bot_module, "MONEY_GAME_WIN_HISTORY_FILE", history_path), patch.object(
                bot_module, "_points_data", side_effect=AssertionError("wallet balances must not be read")
            ):
                self.assertTrue(bot._handle_management_command_impl("", "ملياري", "Viewer", is_private=True))
        message = sent[-1]
        self.assertIn("@Billionaire1 — 17 فوز", message)
        self.assertIn("@Billionaire15 — 3 فوز", message)
        self.assertNotIn("@Billionaire16", message)
        self.assertLess(message.index("@Billionaire1"), message.index("@Billionaire15"))
        self.assertNotIn("رصيد", message)
        self.assertNotIn("نقطة", message)

    def test_money_winner_top_list_paginates_long_names_and_ns_advances(self):
        now = int(time.time())
        names = [f"𓆩〭〬🌸⃝{'م' * 24}{i:02d}𓆪" for i in range(15)]
        records = [{"username": name, "at": now - index} for index, name in enumerate(names)]
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._result_pages = {}
        bot._transfer_log_pages = {}
        bot.help_pages = {}
        bot.help_page_part = {}
        bot.help_game_part = {}
        bot._room_list_commands = lambda *_args: False
        sent, next_packets = [], []
        bot.send_private_text = lambda user, text: sent.append((user, text))
        bot.send_query = lambda payload: next_packets.append(bytes(payload)) or True
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "money-winners.json"
            history_path.write_text(json.dumps({"billion": records}), encoding="utf-8")
            with patch.object(bot_module, "MONEY_GAME_WIN_HISTORY_FILE", history_path):
                self.assertTrue(bot._handle_management_command_impl("", "ملياري", "Viewer", is_private=True))

        self.assertEqual(len(sent), 1)
        self.assertIn("القائمة 1/", sent[0][1])
        self.assertIn("اكتب ns", sent[0][1])
        state = bot._result_pages[("chat_message", "", "Viewer")]
        self.assertGreater(len(state["pages"]), 1)
        combined = "\n".join(state["pages"])
        for name in names:
            self.assertIn(name, combined)
        for index, page in enumerate(state["pages"]):
            footer = "\n\n📌 اكتب ns للقائمة التالية." if index < len(state["pages"]) - 1 else "\n\n✅ انتهت القوائم."
            payload = bot_module.encode_query("chat_message", type_="text", to="Viewer", body=page + footer)
            self.assertLessEqual(len(payload), 1008)
        self.assertTrue(bot._handle_management_command_impl("", "ns", "Viewer", is_private=True))
        next_body = bot_module.as_text(bot_module.decode_message(next_packets[-1])[5][0])
        self.assertIn(state["pages"][1], next_body)
        self.assertLessEqual(len(next_packets[-1]), 1008)

    def test_room_command_content_is_not_logged_when_room_message_logging_is_disabled(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        logs = []
        bot.log = lambda *args: logs.append(" ".join(map(str, args)))
        with patch.object(bot_module, "LOG_ROOM_MESSAGES", False), patch.object(
            bot_module, "_save_local_json"
        ) as save_action:
            bot._remember_bot_action("SecretRoom", "ذهب 1b", "PrivateName")
        self.assertEqual(logs, [])
        save_action.assert_called_once()
        self.assertEqual(save_action.call_args.args[1]["command"], "ذهب 1b")

    def test_successful_github_file_sync_logs_are_quiet_by_default(self):
        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

        missing = Response()
        missing.status_code = 404
        with patch.object(bot_module, "GITHUB_SYNC_ENABLED", True), patch.object(
            bot_module, "LOG_GITHUB_SYNC_SUCCESS", False
        ), patch.object(bot_module, "_github_url", return_value="https://example.invalid/file"), patch.object(
            bot_module, "_github_headers", return_value={}
        ), patch.object(bot_module.requests, "get", return_value=missing), patch.object(
            bot_module.requests, "put", return_value=Response()
        ), patch("builtins.print") as printed:
            self.assertTrue(bot_module._github_put_file("points.json", {}))
            printed.assert_not_called()

    def test_image_publish_schedules_worker_and_returns_without_waiting(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sender = "publisher"
        bot.publish_pending = {
            bot_module._norm_user(sender): {"description": "hello", "created_at": time.time()}
        }
        bot._find_publish_filter_hit = lambda _text: None
        replies, worker_calls, threads = [], [], []
        bot.send_private_text = lambda user, text: replies.append((user, text))
        bot._publish_media_worker = lambda *args: worker_calls.append(args)

        class DeferredThread:
            def __init__(self, target, **kwargs):
                self.target, self.kwargs = target, kwargs
                threads.append(self)
            def start(self):
                self.started = True

        with patch.object(bot_module.threading, "Thread", DeferredThread):
            self.assertTrue(bot._handle_publish_media("North", sender, "https://image.invalid/test.jpg"))
        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0].started)
        self.assertEqual(worker_calls, [])
        self.assertNotIn(bot_module._norm_user(sender), bot.publish_pending)
        self.assertTrue(any("استقبال الأوامر" in text for _user, text in replies))

    def test_stream_member_event_initializes_missing_room_roster(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {}
        bot._stream_member_cache = {}
        with patch.object(bot_module, "_remember_roster") as remember:
            self.assertTrue(bot._cache_stream_member_event({
                2: "member", 8: "member", 13: "NewRoom", 14: "12345", 42: True,
            }))
        self.assertEqual(bot.room_users["NewRoom"]["member"], "member")
        remember.assert_called_once()

    def test_room_join_event_initializes_missing_room_roster(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.room_users = {}
        bot.known_rooms = set()
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot._master_online_rooms = set()
        bot._room_entry_times = {}
        bot._room_entry_users = {}
        bot.custom_welcome_enabled = False
        bot.custom_welcomes = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        with patch.object(bot_module, "_room_protection_cfg", return_value={}), patch.object(
            bot_module, "_save_persistent_rooms"
        ), patch.object(bot_module, "_remember_roster"), patch.object(
            bot_module, "_join_welcome_message", return_value=None
        ):
            bot._handle_room_event_impl({"room_event": {1: "user_joined", 8: "member", 13: "NewRoom", 22: "Member"}})
        self.assertEqual(bot.room_users["NewRoom"]["Member"], "member")

    def test_banning_a_member_does_not_mistake_command_actor_for_removed_bot(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.room_users = {"North": {"Target": "member"}}
        bot.known_rooms = {"North"}
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot.connected_rooms = {"North"}
        bot.pending_admin_lock = threading.Lock()
        bot.pending_admin_actions = {}
        bot.last_admin_actions = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        bot._schedule_auto_rejoin = lambda *_args, **_kwargs: self.fail(
            "an ambiguous actor field must not schedule a bot rejoin"
        )
        bot.log = lambda *_args: None

        with patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
            bot_module, "_save_persistent_rooms"
        ):
            bot._handle_room_event_impl({"room_event": {
                1: "role_changed", 13: "North", 22: "test-bot",
                31: "outcast",
            }})

        self.assertIn("North", bot.connected_rooms)
        self.assertEqual(bot.room_users["North"].get("Target"), "member")

    def test_user_left_packet_prefers_banned_target_over_bot_actor(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.room_users = {"North": {"Target": "member"}}
        bot.known_rooms = {"North"}
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot.connected_rooms = {"North"}
        bot._master_online_rooms = set()
        bot._room_entry_times = {}
        bot._room_entry_users = {}
        bot.custom_welcome_enabled = False
        bot.custom_welcomes = {}
        bot.pending_admin_lock = threading.Lock()
        bot.pending_admin_actions = {}
        bot.last_admin_actions = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        bot._schedule_auto_rejoin = lambda *_args, **_kwargs: self.fail("banning another user must not trigger bot rejoin")
        bot.send_room_text = lambda *_args: None
        bot.log = lambda *_args: None
        with patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
            bot_module, "_room_protection_cfg", return_value={}
        ), patch.object(bot_module, "_save_persistent_rooms"), patch.object(
            bot_module, "_remember_roster"
        ):
            bot._handle_room_event_impl({"room_event": {
                1: "user_left", 13: "North", 17: "Target", 22: "test-bot",
            }})
        self.assertIn("North", bot.connected_rooms)
        self.assertNotIn("Target", bot.room_users["North"])

    def test_unexpected_bot_leave_reports_server_reason_to_master_privately(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.room_users = {"North": {"test-bot": "owner"}}
        bot.known_rooms = {"North"}
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot.connected_rooms = {"North"}
        bot._master_online_rooms = set()
        bot._room_entry_times = {}
        bot._room_entry_users = {}
        bot._intentional_leaves = set()
        bot.custom_welcome_enabled = False
        bot.custom_welcomes = {}
        bot.pending_admin_lock = threading.Lock()
        bot.pending_admin_actions = {}
        bot.last_admin_actions = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        bot._schedule_auto_rejoin = lambda *_args, **_kwargs: None
        bot.send_room_text = lambda *_args: None
        private_notices = []
        bot.send_private_text = lambda user, text: private_notices.append((user, text)) or True
        bot.log = lambda *_args: None
        with patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
            bot_module, "BOT_MASTER", "Master"
        ), patch.object(bot_module, "_room_protection_cfg", return_value={}), patch.object(
            bot_module, "_save_persistent_rooms"
        ), patch.object(bot_module, "_remember_roster"):
            bot._handle_room_event_impl({"room_event": {
                1: "user_left", 13: "North", 17: "test-bot", 22: "RoomAdmin",
                "reason": "removed by room admin",
            }})
        self.assertEqual(len(private_notices), 1)
        self.assertEqual(private_notices[0][0], "Master")
        self.assertIn("North", private_notices[0][1])
        self.assertIn("removed by room admin", private_notices[0][1])
        self.assertIn("RoomAdmin", private_notices[0][1])

    def test_explicit_role_change_of_bot_still_triggers_rejoin_recovery(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.room_users = {"North": {}}
        bot.known_rooms = {"North"}
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot.connected_rooms = {"North"}
        bot.pending_admin_lock = threading.Lock()
        bot.pending_admin_actions = {}
        bot.last_admin_actions = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        scheduled = []
        bot._schedule_auto_rejoin = lambda room, **_kwargs: scheduled.append(room)
        bot.log = lambda *_args: None
        private_notices = []
        bot.send_private_text = lambda user, text: private_notices.append((user, text)) or True

        with patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
            bot_module, "BOT_MASTER", "Master"
        ), patch.object(
            bot_module, "_save_persistent_rooms"
        ):
            bot._handle_room_event_impl({"room_event": {
                1: "role_changed", 13: "North", 17: "test-bot",
                31: "outcast",
            }})

        self.assertNotIn("North", bot.connected_rooms)
        self.assertEqual(scheduled, ["North"])
        self.assertEqual(private_notices[0][0], "Master")
        self.assertIn("outcast", private_notices[0][1])

    def test_telegram_poll_loop_is_inert_when_this_process_is_not_the_owner(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        api_calls = []
        bot._telegram_api = lambda *args, **kwargs: api_calls.append((args, kwargs))
        with patch.object(bot_module, "TELEGRAM_BOT_TOKEN", "test-token"), patch.object(
            bot_module, "TELEGRAM_POLL_ENABLED", False
        ):
            bot._telegram_poll_loop()
        self.assertEqual(api_calls, [])

    def test_join_routes_to_active_ludo_and_snake_before_cricket(self):
        room_key = bot_module._norm_room("North")
        for game_key in (f"ludo:{room_key}", f"snake:{room_key}"):
            with self.subTest(game=game_key):
                bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
                bot.ludo_games = {}
                bot.snake_games = {}
                if game_key.startswith("ludo:"):
                    bot.ludo_games[game_key] = {"players": ["Host"], "started": False}
                else:
                    bot.snake_games[game_key] = {"players": ["Host"]}
                routed = []
                bot._run_game_command_async = lambda *args: routed.append(args) or True
                with patch.object(bot_module, "_is_verified_user", return_value=True):
                    self.assertTrue(bot._route_active_board_game_join("North", "Player", "join"))
                self.assertEqual(routed, [("North", "join", "Player")])

    def test_board_game_join_router_requires_active_game_and_verified_user(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.ludo_games = {}
        bot.snake_games = {}
        routed = []
        bot._run_game_command_async = lambda *args: routed.append(args) or True
        with patch.object(bot_module, "_is_verified_user", return_value=True):
            self.assertFalse(bot._route_active_board_game_join("North", "Player", "join"))
        room_key = bot_module._norm_room("North")
        bot.snake_games[f"snake:{room_key}"] = {"players": ["Host"]}
        with patch.object(bot_module, "_is_verified_user", return_value=False):
            self.assertFalse(bot._route_active_board_game_join("North", "Player", "join"))
        self.assertEqual(routed, [])

    def test_bot_wide_transfer_history_is_newest_first_and_paginated(self):
        history = [
            {"sender": "A", "recipient": "B", "amount": n, "timestamp": n}
            for n in range(1, 18)
        ]
        with patch.object(bot_module, "_points_data", return_value={}), patch.object(
            bot_module, "_POINTS_TRANSFER_CACHE", history
        ):
            page1, total, pages = bot_module._all_point_transfer_history(page=1, page_size=8)
            page2, total2, pages2 = bot_module._all_point_transfer_history(page=2, page_size=8)
            page3, _, _ = bot_module._all_point_transfer_history(page=3, page_size=8)
        self.assertEqual((total, pages), (17, 3))
        self.assertEqual((total2, pages2), (17, 3))
        self.assertEqual([row["amount"] for row in page1], list(range(17, 9, -1)))
        self.assertEqual([row["amount"] for row in page2], list(range(9, 1, -1)))
        self.assertEqual([row["amount"] for row in page3], [1])

    def test_global_transfer_log_is_master_only_and_always_private(self):
        guest = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        guest._room_list_commands = lambda *_args: False
        guest_replies = []
        guest.send_private_text = lambda who, text: guest_replies.append((who, text))
        with patch.object(bot_module, "_is_master_name", return_value=False), patch.object(
            bot_module, "_all_point_transfer_history"
        ) as get_log:
            self.assertTrue(guest._handle_management_command_impl("Room", "سجل التحويل", "Guest", is_private=False))
        self.assertFalse(get_log.called)
        self.assertEqual(guest_replies[0][0], "Guest")
        self.assertIn("للماستر فقط", guest_replies[0][1])

        master = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        master._room_list_commands = lambda *_args: False
        master_replies = []
        master.send_private_text = lambda who, text: master_replies.append((who, text))
        history_entry = {
            "sender": "Sender", "recipient": "Recipient", "amount": 1000,
            "timestamp": 1700000000, "sender_balance_after": 3000,
            "recipient_balance_after": 5000, "reason": "transfer", "id": "transaction-id",
        }
        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_all_point_transfer_history", return_value=([history_entry], 1, 1)
        ) as get_log:
            self.assertTrue(master._handle_management_command_impl("Room", "transfer history", "Master", is_private=False))
        get_log.assert_called_once_with(page=1, page_size=bot_module._POINT_TRANSFER_HISTORY_PAGE_SIZE)
        self.assertEqual(master_replies[0][0], "Master")
        self.assertIn("@Sender → @Recipient", master_replies[0][1])
        self.assertIn("1k", master_replies[0][1])
        self.assertIn("1/1", master_replies[0][1])

    def test_global_transfer_log_uses_list_one_then_ns_for_next_list(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args: False
        bot._master_reply_local = threading.local()
        bot._result_pages = {}
        bot._filter_list_state = {}
        bot._remember_bot_action = lambda *_args, **_kwargs: None
        replies = []
        bot.send_private_text = lambda who, text: replies.append((who, text))

        def page_data(page, page_size):
            self.assertEqual(page_size, bot_module._POINT_TRANSFER_HISTORY_PAGE_SIZE)
            sender = "Newest" if page == 1 else "Older"
            rows = [{
                "sender": sender, "recipient": "Target", "amount": page,
                "timestamp": 1700000000 - page, "sender_balance_after": 10,
                "recipient_balance_after": 20, "reason": "transfer",
            }]
            return rows, 17, 3

        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_all_point_transfer_history", side_effect=page_data
        ), patch.object(
            bot_module, "_format_all_point_transfer_history_page",
            side_effect=[
                ("قائمة 1/3\n@Newest\nاكتب ns", 3),
                ("قائمة 2/3\n@Older\nاكتب ns", 3),
                ("قائمة 3/3\n@Oldest", 3),
            ],
        ):
            self.assertTrue(bot._handle_management_command("Room", "سجل التحويل", "Master", is_private=True))
            self.assertTrue(bot._handle_management_command("Room", "ns", "Master", is_private=True))
            self.assertTrue(bot._handle_management_command("Room", "ns", "Master", is_private=True))
            self.assertTrue(bot._handle_management_command("Room", "ns", "Master", is_private=True))
        self.assertEqual(len(replies), 4)
        self.assertIn("قائمة 1/3", replies[0][1])
        self.assertIn("اكتب ns", replies[0][1])
        self.assertIn("@Newest", replies[0][1])
        self.assertIn("قائمة 2/3", replies[1][1])
        self.assertIn("@Older", replies[1][1])
        self.assertIn("قائمة 3/3", replies[2][1])
        self.assertIn("@Oldest", replies[2][1])
        self.assertIn("آخر قائمة", replies[3][1])
        self.assertNotIn(bot_module._norm_user("Master"), bot._transfer_log_pages)

    def test_recipient_transfer_history_filters_and_paginates_all_matching_rows(self):
        rows = [
            {"recipient_key": "target-key", "recipient": "Target", "sender": f"Sender{i}", "amount": i}
            for i in range(5)
        ] + [
            {"recipient_key": "other-key", "recipient": "Other", "sender": "OtherSender", "amount": 99}
        ]
        with patch.object(bot_module, "_points_data", return_value={}), patch.object(
            bot_module, "_resolve_points_account", return_value=("target-key", {"username": "Target"})
        ), patch.object(bot_module, "_POINTS_TRANSFER_CACHE", rows):
            page, total, pages = bot_module._all_point_transfer_history(
                page=2, page_size=bot_module._POINT_TRANSFER_HISTORY_PAGE_SIZE, recipient="Target"
            )
        self.assertEqual(total, 5)
        self.assertEqual(pages, 2)
        self.assertEqual([row["sender"] for row in page], ["Sender1", "Sender0"])

    def test_recipient_transfer_log_command_is_master_only_and_starts_private_pages(self):
        master = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        master._room_list_commands = lambda *_args: False
        master._master_reply_local = threading.local()
        master._result_pages = {}
        master._filter_list_state = {}
        master._remember_bot_action = lambda *_args, **_kwargs: None
        replies = []
        master.send_private_text = lambda who, text: replies.append((who, text))
        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_points_data", return_value={}
        ), patch.object(
            bot_module, "_resolve_points_account", return_value=("target-key", {"username": "Target"})
        ), patch.object(
            bot_module, "_format_all_point_transfer_history_page", return_value=("قائمة 1/2", 2)
        ) as format_page:
            self.assertTrue(master._handle_management_command("Room", "سجل تحويل@Target", "Master", is_private=True))
        format_page.assert_called_once_with(1, False, recipient="Target")
        self.assertEqual(master._transfer_log_pages[bot_module._norm_user("Master")], 1)
        self.assertEqual(master._transfer_log_targets[bot_module._norm_user("Master")], "Target")
        self.assertEqual(replies, [("Master", "قائمة 1/2")])

        master._master_reply_local = threading.local()
        master._filter_list_state = {}
        master._result_pages = {}
        master._remember_bot_action = lambda *_args, **_kwargs: None
        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_all_point_transfer_history", return_value=([], 4, 2)
        ) as get_log, patch.object(
            bot_module, "_format_all_point_transfer_history_page", return_value=("قائمة 2/2", 2)
        ) as format_page:
            self.assertTrue(master._handle_management_command("Room", "ns", "Master", is_private=True))
        get_log.assert_called_once_with(page=1, page_size=bot_module._POINT_TRANSFER_HISTORY_PAGE_SIZE, recipient="Target")
        format_page.assert_called_once_with(2, False, recipient="Target")
        self.assertEqual(replies[-1], ("Master", "قائمة 2/2"))

    def test_global_transfer_log_page_fits_ws_limit_with_extremely_long_fields(self):
        huge_entry = {
            "sender": "مرسل" * 2_000,
            "recipient": "مستلم" * 2_000,
            "amount": 1_000_000_000,
            "timestamp": 1_700_000_000,
            "sender_balance_after": 9_000_000_000,
            "recipient_balance_after": 9_000_000_000,
            "reason": "سبب تحويل طويل جدًا " * 2_000,
        }
        with patch.object(
            bot_module, "_all_point_transfer_history",
            return_value=([dict(huge_entry) for _ in range(bot_module._POINT_TRANSFER_HISTORY_PAGE_SIZE)], 100, 34),
        ) as get_history:
            message, pages = bot_module._format_all_point_transfer_history_page(1, english=False)
        get_history.assert_called_once_with(page=1, page_size=bot_module._POINT_TRANSFER_HISTORY_PAGE_SIZE)
        self.assertEqual(pages, 34)
        packet = bot_module.encode_query("chat_message", type_="text", to="Master", body=message)
        self.assertLessEqual(len(packet), bot_module._ws_payload_limit())
        self.assertLessEqual(len(message.encode("utf-8")), 800)


class FollowupFeatureRegressions(unittest.TestCase):
    def test_crop_menu_and_plant_confirmation_follow_room_language(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.game_lock = threading.Lock()
        bot.crop_plots = {}
        bot._effective_room_language = lambda _room: "en"
        bot._game_cooldown_notice = lambda *_args: True
        bot._save_crop_plots = lambda: None
        bot._result_pages = {}
        bot._send_text_packets = lambda _packet_type, text, **kwargs: self.messages.append((kwargs.get("room"), text))
        bot.send_room_text = lambda room, text: self.messages.append((room, text))
        self.messages = []
        self.assertTrue(bot._crop_command("Farm", "Tester", "زرع"))
        self.assertIn("Crop menu", self.messages[-1][1])
        self.assertIn("farm@🍎", self.messages[-1][1])
        crop_durations = [
            int(line.split("m=", 1)[0].rsplit(" ", 1)[1])
            for line in self.messages[-1][1].splitlines() if "m=" in line
        ]
        self.assertTrue(crop_durations)
        self.assertLessEqual(max(crop_durations), 60)
        self.assertEqual(max(crop_durations), 60)
        self.assertTrue(bot._crop_command("Farm", "Tester", "زرع@🍎"))
        self.assertIn("Planted 🍎 successfully", self.messages[-1][1])
        self.assertIn("sent to your private messages", self.messages[-1][1])

    def test_harvest_result_is_delivered_only_to_player_private(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.game_lock = threading.Lock()
        bot.crop_plots = {
            "decorated-account|🍎|1": {
                "username": "𓆩DecoratedName𓆪", "crop": "🍎", "minutes": 5,
                "reward": 1000, "finish": 0, "room": "Farm Room",
            }
        }
        bot._crop_retry_after = {}
        bot._game_award = lambda _name, reward: 7000 + reward
        bot._save_crop_plots = lambda: None
        bot._configured_room_language = lambda _room: "en"
        bot.send_room_text = lambda room, text: self.sent.append((room, text))
        bot.send_private_text = lambda user, text: self.private_sent.append((user, text))
        bot.log = lambda *_args: None
        self.sent, self.private_sent = [], []
        with patch.object(bot_module, "_record_game", lambda *_args: None):
            self.assertEqual(bot._process_due_crop_plots(now=1), 1)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.private_sent[0][0], "𓆩DecoratedName𓆪")
        self.assertIn("Your harvest is ready", self.private_sent[0][1])
        self.assertIn("Farm room: Farm Room", self.private_sent[0][1])
        self.assertFalse(bot.crop_plots)

    def test_english_shot_catches_dragon_first_then_regular_animals(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stock_pending = {}
        bot._snake_command = lambda *_args: False
        bot._ludo_command = lambda *_args: False
        bot._handle_pending_bot_choice = lambda *_args: False
        bot._fishing_lock = threading.RLock()
        bot._fishing_event = {"id": 1, "started_at": 100.0, "ends_at": 700.0}
        bot._fishing_shots = set()
        bot._fishing_pending_shots = set()
        bot._fishing_dragon_pending = ""
        bot._fishing_dragon_caught = False
        bot._active_rooms = lambda: ["Garden", "EnglishHall", "ArabicHall"]
        bot._configured_room_language = lambda room: "en" if room in {"EnglishHall", "Garden"} else "ar"
        bot._game_award = lambda _name, reward: reward
        bot.send_room_text = lambda room, text: self.messages.append((room, text))
        bot._send_game_winner_card = lambda *args: self.cards.append(args)
        bot._queue_dragon_hunter_broadcast = lambda username, room, reward: bot._broadcast_dragon_hunter_result(username, room, reward)
        bot.log = lambda *_args: None
        self.messages, self.cards = [], []
        self.assertEqual(bot_module._normalize_game_command_text("Shot"), "شوت")
        self.assertEqual(bot_module._normalize_game_command_text("شوت"), "شوت")
        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_games_enabled_for_room", return_value=True
        ), patch.object(bot_module, "_record_game", lambda *_args: None), patch.object(
            bot_module, "_save_local_json"
        ):
            with patch.object(bot_module.time, "time", return_value=200.0), patch.object(
                bot_module.secrets, "choice", return_value=("🐇", "أرنب بري", "Wild rabbit", 5_000)
            ):
                self.assertTrue(bot.handle_game_command("Garden", "Shot", "Hunter"))
            with patch.object(bot_module.time, "time", return_value=321.0), patch.object(
                bot_module.secrets, "choice", return_value=("🐇", "أرنب بري", "Wild rabbit", 5_000)
            ):
                self.assertTrue(bot.handle_game_command("Garden", "شوت", "Hunter"))
        self.assertEqual(len(self.cards), 1)
        self.assertEqual(self.cards[0], ("hunt_dragon", "Hunter", ["Garden"]))
        dragon_results = {room: text for room, text in self.messages if "🐉🏆" in text}
        self.assertEqual(set(dragon_results), {"Garden", "EnglishHall", "ArabicHall"})
        self.assertIn("caught the dragon", dragon_results["EnglishHall"])
        self.assertIn("غرفة الصيد: Garden", dragon_results["ArabicHall"])
        self.assertEqual(sum("+1m" in text for text in dragon_results.values()), 3)
        self.assertTrue(any("🐇 Wild rabbit" in text and "Reward: +5k" in text for _, text in self.messages))

    def test_shot_outside_trip_still_awards_a_regular_animal(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stock_pending = {}
        bot._snake_command = lambda *_args: False
        bot._ludo_command = lambda *_args: False
        bot._handle_pending_bot_choice = lambda *_args: False
        bot._fishing_lock = threading.RLock()
        bot._fishing_event = None
        bot._fishing_pending_shots = set()
        bot._fishing_dragon_pending = ""
        bot._fishing_dragon_caught = False
        bot._configured_room_language = lambda _room: "ar"
        bot._game_award = lambda _name, reward: reward
        bot._send_game_winner_card = lambda *_args: self.fail("ordinary animal must not send dragon card")
        messages = []
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot.log = lambda *_args: None

        def choose_regular_animal(animals):
            self.assertEqual({animal[3] for animal in animals}, {5_000})
            return next(animal for animal in animals if animal[2] == "Fox")

        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_games_enabled_for_room", return_value=True
        ), patch.object(bot_module.secrets, "choice", side_effect=choose_regular_animal), patch.object(
            bot_module, "_record_game", lambda *_args: None
        ):
            self.assertTrue(bot.handle_game_command("Garden", "Shot", "Hunter"))
        self.assertIn("🦊 ثعلب", messages[-1][1])
        self.assertIn("+5k", messages[-1][1])

    def test_shot_has_a_two_minute_per_user_cooldown_across_rooms(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stock_pending = {}
        bot._snake_command = lambda *_args: False
        bot._ludo_command = lambda *_args: False
        bot._handle_pending_bot_choice = lambda *_args: False
        bot._fishing_lock = threading.RLock()
        bot._fishing_event = None
        bot._fishing_pending_shots = set()
        bot._fishing_cooldowns = {}
        bot._fishing_dragon_pending = ""
        bot._fishing_dragon_caught = False
        bot._configured_room_language = lambda _room: "ar"
        awards, messages = [], []
        bot._game_award = lambda _name, reward: awards.append(reward) or len(awards) * reward
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot._send_game_winner_card = lambda *_args: self.fail("ordinary animal must not send a dragon card")
        bot.log = lambda *_args: None
        animal = ("🐇", "أرنب بري", "Wild rabbit", 5_000)
        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_games_enabled_for_room", return_value=True
        ), patch.object(bot_module, "_record_game", lambda *_args: None):
            with patch.object(bot_module.time, "time", return_value=1_000.0), patch.object(
                bot_module.secrets, "choice", return_value=animal
            ):
                bot.handle_game_command("Room A", "Shot", "Hunter")
            with patch.object(bot_module.time, "time", return_value=1_100.0):
                bot.handle_game_command("Room B", "شوت", "Hunter")
            with patch.object(bot_module.time, "time", return_value=1_120.0), patch.object(
                bot_module.secrets, "choice", return_value=animal
            ):
                bot.handle_game_command("Room B", "شوت", "Hunter")
        self.assertEqual(awards, [5_000, 5_000])
        self.assertTrue(any("فاصل الصيد دقيقتان" in text for _, text in messages))
        self.assertEqual(sum("حصاد" in text or "نتيجة رحلة الصيد" in text for _, text in messages), 2)

    def test_fishing_announcement_mentions_guaranteed_dragon_in_all_active_rooms(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._fishing_lock = threading.RLock()
        bot._active_rooms = lambda: ["ArabicHall", "EnglishHall"]
        bot._configured_room_language = lambda room: "en" if room == "EnglishHall" else "ar"
        messages = []
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot.log = lambda *_args: None
        event = bot._start_fishing_event(now=100.0)
        self.assertEqual(event["ends_at"], 700.0)
        self.assertEqual({room for room, _ in messages}, {"ArabicHall", "EnglishHall"})
        self.assertIn("أول من يرسل شوت أو Shot", dict(messages)["ArabicHall"])
        self.assertIn("first Shot catches", dict(messages)["EnglishHall"])

    def test_dragon_hunter_badge_is_saved_and_added_to_room_join_welcome(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._dragon_hunters_lock = threading.RLock()
        bot.dragon_hunters = {}
        bot.room = ""
        bot.room_users = {}
        bot.known_rooms = set()
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot._master_online_rooms = set()
        bot._room_entry_times = {}
        bot._room_entry_users = {}
        bot.custom_welcome_enabled = False
        bot.custom_welcomes = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        bot._configured_room_language = lambda _room: "en"
        messages, saved = [], []
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot.log = lambda *_args: None
        with patch.object(bot_module, "BOT_ID", "bot-id"), patch.object(
            bot_module, "BOT_MASTER", "master-id"
        ), patch.object(bot_module, "_save_local_json", side_effect=lambda *args: saved.append(args)), patch.object(
            bot_module, "_room_protection_cfg", return_value={}
        ), patch.object(bot_module, "_save_persistent_rooms"), patch.object(
            bot_module, "_remember_roster"
        ), patch.object(bot_module, "_join_welcome_message", return_value=None):
            self.assertTrue(bot._record_dragon_hunter("Hunter", "Garden"))
            self.assertTrue(bot._is_dragon_hunter("hunter"))
            bot._handle_room_event_impl({"room_event": {
                1: "user_joined", 8: "member", 13: "EnglishHall", 22: "Hunter",
            }})
        self.assertEqual(saved[0][0], bot_module.DRAGON_HUNTERS_FILE)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][0], "EnglishHall")
        self.assertIn("Welcome back, Dragon Hunter @Hunter", messages[0][1])

    def test_dragon_winner_card_with_avatar_stays_below_50kb(self):
        if not bot_module.PIL_AVAILABLE:
            self.skipTest("Pillow is unavailable")
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            avatar = Image.new("RGBA", (116, 116), (70, 130, 190, 255))
            with patch.object(bot_module, "BASE_DIR", Path(temp)), patch.object(
                bot_module, "_load_sender_avatar", return_value=avatar
            ):
                card = bot_module.render_game_winner_card(
                    "hunt_dragon", "Hunter", "https://example.invalid/avatar.jpg", language="en"
                )
            self.assertTrue(card.is_file())
            self.assertLessEqual(card.stat().st_size, 50 * 1024)

    def test_myrooms_paginates_thirty_rooms_and_ns_shows_final_page(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.connected_rooms = {f"Room {i:02d}" for i in range(1, 32)}
        bot._result_pages = {}
        bot._transfer_log_pages = {}
        bot._transfer_log_languages = {}
        bot._room_list_commands = lambda *_args: False
        bot._effective_room_language = lambda _room: "ar"
        bot.help_pages = {}
        bot.help_page_part = {}
        bot.help_game_part = {}
        bot._send_text_packets = lambda packet, text, **kwargs: self.sent.append((packet, text, kwargs))
        private_sent = []
        bot.send_private_text = lambda _user, text: private_sent.append(text)
        self.sent = []
        with patch.object(bot_module, "_is_master_name", return_value=True):
            self.assertTrue(bot._handle_management_command_impl("", "myrooms", "Master", is_private=True))
            self.assertTrue(bot._handle_management_command_impl("", "ns", "Master", is_private=True))
        self.assertEqual(len(private_sent), 1)
        self.assertIn("Complete bot rooms (31) — server", private_sent[0])
        self.assertIn("Type ns for the next list", private_sent[0])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("📄 List 2/2", self.sent[0][1])
        self.assertIn("Room 31", self.sent[0][1])
        self.assertIn("✅ End of list", self.sent[0][1])
        self.assertFalse(bot._result_pages)

    def test_myrooms_long_names_are_paginated_under_the_websocket_limit(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._result_pages = {}
        bot._effective_room_language = lambda _room: "ar"
        sent = []
        bot.send_private_text = lambda _user, text: sent.append(text)
        names = [f"𓆩〭〬🌸⃝{'م' * 24}{i:02d}𓆪" for i in range(30)]
        bot._send_room_names_pages("Master", "", names, from_server=True, language="ar")

        state = bot._result_pages[("chat_message", "", "Master")]
        self.assertGreater(len(state["pages"]), 1)
        self.assertIn("📄 القائمة 1/", sent[0])
        self.assertIn("اكتب ns", sent[0])
        combined = "\n".join(state["pages"])
        for name in names:
            self.assertIn(name, combined)
        for index, page in enumerate(state["pages"]):
            footer = "\n\n📌 اكتب ns للقائمة التالية." if index < len(state["pages"]) - 1 else "\n\n✅ انتهت القوائم."
            payload = bot_module.encode_query(
                "chat_message", type_="text", to="Master", body=page + footer
            )
            self.assertLessEqual(len(payload), 1008)


class NewMarketAndModerationRegressions(unittest.TestCase):
    def test_management_wrapper_does_not_send_generic_command_received_ack(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args, **_kwargs: False
        bot._master_reply_local = threading.local()
        bot._handle_management_command_impl = lambda *_args, **_kwargs: True
        bot._remember_bot_action = lambda *_args, **_kwargs: None
        sent = []
        bot.send_private_text = lambda user, text: sent.append((user, text))
        bot.send_room_text = lambda room, text: sent.append((room, text))
        with patch.object(bot_module, "_is_master_name", return_value=True):
            self.assertTrue(bot._handle_management_command("", "test command", "Master", is_private=True))
        self.assertEqual(sent, [])

    def test_stock_points_delta_is_atomic_idempotent_and_never_overdraws(self):
        accounts = {"player": {"username": "Player", "points": 500}}
        history = []
        investment = {
            "id": "market-1", "event_id": 7, "username": "Player", "room": "Hall",
            "asset": 1, "amount": 100, "started_at": 10.0, "due_at": 70.0,
            "status": "pending_debit",
        }
        with patch.object(bot_module, "_POINTS_CACHE", accounts), patch.object(
            bot_module, "_POINTS_TRANSFER_CACHE", history
        ), patch.object(bot_module, "_STATE_DB_ENABLED", False), patch.object(
            bot_module, "_save_local_json", return_value=None
        ):
            first = bot_module._apply_points_delta_once(
                "PLAYER", -100, "stock-market-debit:market-1", "stock market",
                stock_market_investment=investment,
            )
            retry = bot_module._apply_points_delta_once(
                "Player", -100, "stock-market-debit:market-1", "stock market",
                stock_market_investment=investment,
            )
            self.assertEqual(first["balance"], 400)
            self.assertTrue(retry["already_applied"])
            self.assertEqual(retry["balance"], 400)
            self.assertEqual(bot_module._POINTS_TRANSFER_CACHE[0]["stock_market_investment"], investment)
            bot_module._POINTS_TRANSFER_CACHE[0].pop("stock_market_investment")
            enriched_retry = bot_module._apply_points_delta_once(
                "Player", -100, "stock-market-debit:market-1", "stock market",
                stock_market_investment=investment,
            )
            self.assertTrue(enriched_retry["already_applied"])
            self.assertEqual(enriched_retry["balance"], 400)
            self.assertEqual(bot_module._POINTS_TRANSFER_CACHE[0]["stock_market_investment"], investment)
            overdraw = bot_module._apply_points_delta_once("Player", -500, "market-debit-2", "stock market")
            self.assertEqual(overdraw["error"], "insufficient")
            credit = bot_module._apply_points_delta_once("Player", 25, "market-credit-1", "stock market")
            credit_retry = bot_module._apply_points_delta_once("Player", 25, "market-credit-1", "stock market")
            self.assertEqual(credit["balance"], 425)
            self.assertTrue(credit_retry["already_applied"])
            self.assertEqual(credit_retry["balance"], 425)
            self.assertEqual(len(bot_module._POINTS_TRANSFER_CACHE), 2)

    def test_missing_stock_file_investment_is_recovered_from_point_debit_journal(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_investments = []
        bot.stock_market_history = []
        bot.log = lambda *_args: None
        saved = []
        bot._save_stock_investments = lambda: saved.append([dict(row) for row in bot.stock_investments])
        investment = {
            "id": "recover-1", "event_id": 8, "username": "Player", "room": "Hall",
            "asset": 2, "amount": 100_000, "started_at": 100.0, "due_at": 160.0,
        }
        transactions = [{
            "id": "stock-market-debit:recover-1", "timestamp": 110, "sender": "Player",
            "amount": 100_000, "stock_market_investment": investment,
        }]
        with patch.object(bot_module, "_POINTS_TRANSFER_CACHE", transactions), patch.object(
            bot_module, "_points_data", return_value={}
        ):
            self.assertEqual(bot._recover_stock_market_investments_from_points_history(), 1)
            self.assertEqual(bot._recover_stock_market_investments_from_points_history(), 0)
        self.assertEqual(len(bot.stock_investments), 1)
        self.assertEqual(bot.stock_investments[0]["id"], "recover-1")
        self.assertEqual(bot.stock_investments[0]["status"], "pending_debit")
        self.assertEqual(bot.stock_investments[0]["due_at"], 160.0)
        self.assertEqual(len(saved), 1)

    def test_stock_recovery_skips_investment_with_existing_payout_transaction(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_investments = []
        bot.stock_market_history = []
        bot.log = lambda *_args: None
        bot._save_stock_investments = lambda: self.fail("settled investment must not be reconstructed")
        investment = {
            "id": "paid-1", "username": "Player", "room": "Hall", "asset": 1,
            "amount": 100, "started_at": 100.0, "due_at": 160.0,
        }
        transactions = [
            {"id": "stock-market-debit:paid-1", "sender": "Player", "amount": 100,
             "stock_market_investment": investment},
            {"id": "stock-market-payout:paid-1", "sender": "stock_market", "amount": 105},
        ]
        with patch.object(bot_module, "_POINTS_TRANSFER_CACHE", transactions), patch.object(
            bot_module, "_points_data", return_value={}
        ):
            self.assertEqual(bot._recover_stock_market_investments_from_points_history(), 0)
        self.assertEqual(bot.stock_investments, [])

    def test_legacy_pending_stock_migration_refunds_old_debit_once(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_market_history = []
        bot.stock_investments = [
            {"id": "legacy-active", "username": "Player", "amount": 500,
             "status": "active", "due_at": 160.0},
            {"id": "legacy-not-debited", "username": "Player", "amount": 300,
             "status": "pending_debit", "due_at": 170.0},
            {"id": "legacy-active-no-journal", "username": "Player", "amount": 200,
             "status": "active", "due_at": 180.0},
        ]
        bot.log = lambda *_args: None
        saved = []
        bot._save_stock_investments = lambda: saved.append([dict(row) for row in bot.stock_investments])
        point_ops = []

        def apply_once(username, delta, transaction_id, reason):
            point_ops.append((username, delta, transaction_id, reason))
            return {"ok": True, "balance": 1_000}

        transactions = [{"id": "stock-market-debit:legacy-active"}]
        with patch.object(bot_module, "_points_data", return_value={}), patch.object(
            bot_module, "_POINTS_TRANSFER_CACHE", transactions
        ), patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once):
            self.assertEqual(bot._migrate_legacy_stock_market_investments(), 2)
            self.assertEqual(bot._migrate_legacy_stock_market_investments(), 0)

        self.assertEqual(len(point_ops), 1)
        self.assertEqual(point_ops[0][1], 500)
        self.assertEqual(point_ops[0][2], "stock-market-migration-refund:legacy-active")
        self.assertEqual(bot.stock_investments[0]["status"], "pending_settlement")
        self.assertEqual(bot.stock_investments[0]["balance_mode"], "deferred")
        self.assertEqual(bot.stock_investments[1]["status"], "pending_settlement")
        self.assertFalse(bot.stock_investments[1]["migrated_from_entry_debit"])
        self.assertEqual(bot.stock_investments[2]["status"], "active")
        self.assertNotIn("balance_mode", bot.stock_investments[2])
        self.assertEqual(len(saved), 1)

    def test_pending_debit_recovery_reuses_idempotent_debit_and_refreshes_journal(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_investments = [{
            "id": "resume-1", "event_id": 2, "username": "Player", "room": "Hall",
            "asset": 1, "amount": 100, "started_at": 100.0, "due_at": 1_000.0,
            "status": "pending_debit",
        }]
        bot._save_stock_investments = lambda: None
        calls = []

        def apply_once(username, delta, transaction_id, reason, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "already_applied": True, "balance": 400}

        with patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once):
            self.assertEqual(bot._process_stock_market_investments(now=500.0), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["stock_market_investment"]["id"], "resume-1")
        self.assertEqual(bot.stock_investments[0]["status"], "active")

    def test_billion_cooldown_can_be_set_through_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ)
            env.update({"BILLION_GAME_COOLDOWN_SECONDS": "137", "BOT_DATA_DIR": temp})
            result = subprocess.run(
                [sys.executable, "-c", "import bot; print('COOLDOWN=', bot.BILLION_GAME_COOLDOWN_SECONDS)"],
                cwd=Path(__file__).resolve().parents[1], env=env,
                capture_output=True, text=True, timeout=60, check=True,
            )
        self.assertIn("COOLDOWN= 137.0", result.stdout)

    def test_stock_order_parser_accepts_arabic_english_and_numeric_assets(self):
        self.assertEqual(bot_module._parse_stock_market_order("ذهب 100000"), (1, 100000))
        self.assertEqual(bot_module._parse_stock_market_order("gold@100,000"), (1, 100000))
        self.assertEqual(bot_module._parse_stock_market_order("بورصة@2@75000"), (2, 75000))
        self.assertEqual(bot_module._parse_stock_market_order("نفط ١٠٠٠٠٠"), (3, 100000))
        self.assertEqual(bot_module._parse_stock_market_order("land 50000"), (4, 50000))
        self.assertIsNone(bot_module._parse_stock_market_order("market tomorrow"))

    def test_manual_stock_command_opens_immediately_for_ten_minutes(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stock_pending = {}
        bot.stock_investments = []
        bot._stock_market_lock = threading.RLock()
        bot.stock_market_round = None
        bot._stock_market_round_seq = 0
        bot._stock_market_seen = set()
        bot._stock_market_next_announcement = 0
        bot.connected_rooms = {"ArabicHall", "EnglishHall"}
        bot._active_rooms = lambda: ["ArabicHall", "EnglishHall"]
        bot._configured_room_language = lambda room: "en" if room == "EnglishHall" else "ar"
        bot._queue_stock_market_round_broadcast = lambda _rooms: None
        bot._snake_command = lambda *_args: False
        bot._ludo_command = lambda *_args: False
        bot._handle_pending_bot_choice = lambda *_args: False
        bot._game_cooldown_notice = lambda *_args: True
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        bot._save_stock_investments = lambda: None
        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_games_enabled_for_room", return_value=True
        ), patch.object(bot_module, "_looks_like_bot_command", return_value=True), patch.object(
            bot_module.time, "time", return_value=1_000.0
        ):
            self.assertTrue(bot.handle_game_command("ArabicHall", "بورصة", "Player"))
        self.assertEqual(len(sent), 1)
        for asset in ("ذهب", "فضة", "نفط", "أرض"):
            self.assertIn(asset, sent[0][1])
        self.assertIn("100000", sent[0][1])
        self.assertEqual(bot.stock_market_round["ends_at"], 1_600.0)
        self.assertEqual(bot._stock_market_next_announcement, 1_600.0)
        self.assertEqual(bot.stock_pending[(bot_module._norm_room("ArabicHall"), bot_module._norm_user("Player"))]["kind"], "market_choice")

    def test_stock_investment_has_two_minute_cooldown_and_repeats_within_round(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_market_round = {"id": 1, "started_at": 0.0, "ends_at": 5_000.0}
        bot._stock_market_seen = set()
        bot._stock_market_user_cooldowns = {}
        bot.stock_investments = []
        bot._save_stock_investments = lambda: None
        bot._configured_room_language = lambda _room: "en"
        bot.log = lambda *_args: None
        messages, point_ops = [], []
        bot.send_room_text = lambda room, text: messages.append((room, text))

        def apply_once(username, delta, transaction_id, reason, **kwargs):
            point_ops.append((username, delta, transaction_id, reason))
            return {"ok": True, "balance": 1_000}

        with patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once), patch.object(
            bot_module, "_get_points", return_value=1_000
        ):
            with patch.object(bot_module.time, "time", return_value=1_000.0):
                bot._stock_market_invest("Market", "Player", 1, 100, expected_round_id=1)
            with patch.object(bot_module.time, "time", return_value=1_100.0):
                bot._stock_market_invest("Market", "Player", 2, 100, expected_round_id=1)
            with patch.object(bot_module.time, "time", return_value=1_120.0):
                bot._stock_market_invest("Market", "Player", 2, 100, expected_round_id=1)
            with patch.object(bot_module.time, "time", return_value=1_240.0):
                bot._stock_market_invest("Market", "Player", 2, 100, expected_round_id=1)
        self.assertEqual(point_ops, [])
        self.assertEqual(len(bot.stock_investments), 3)
        self.assertTrue(any("2-minute cooldown" in text for _, text in messages))

    def test_stock_investment_checks_balance_and_pending_commitments_without_debit(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_market_round = {"id": 1, "started_at": 0.0, "ends_at": 5_000.0}
        bot._stock_market_seen = set()
        bot._stock_market_user_cooldowns = {}
        bot.stock_investments = [{
            "id": "pending-1", "username": "Player", "amount": 50,
            "status": "pending_settlement", "balance_mode": "deferred",
        }]
        bot._save_stock_investments = lambda: None
        bot._configured_room_language = lambda _room: "ar"
        bot.log = lambda *_args: None
        messages = []
        bot.send_room_text = lambda room, text: messages.append((room, text))

        with patch.object(bot_module, "_get_points", return_value=100), patch.object(
            bot_module.time, "time", return_value=1_000.0
        ), patch.object(bot_module, "_apply_points_delta_once") as apply_once:
            bot._stock_market_invest("Market", "Player", 1, 60, expected_round_id=1)

        apply_once.assert_not_called()
        self.assertEqual(len(bot.stock_investments), 1)
        self.assertIn("50 نقطة", messages[-1][1])
        self.assertNotIn("Player", bot._stock_market_user_cooldowns)

    def test_stock_investment_settles_profit_or_loss_after_one_minute_without_showing_percent(self):
        cases = (
            (0, 0, "profit", 1), (0, 49, "profit", 50),
            (1, 0, "loss", 1), (1, 49, "loss", 50),
        )
        for outcome_draw, percent_draw, outcome, expected_percent in cases:
            with self.subTest(outcome=outcome, expected_percent=expected_percent):
                bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
                bot._stock_market_lock = threading.RLock()
                bot.stock_investments = [{
                    "id": "market-test", "username": "Player", "asset": 1,
                    "amount": 100_000, "due_at": 900.0, "room": "ArabicHall",
                    "status": "active",
                }]
                bot.stock_market_history = []
                bot._configured_room_language = lambda active_room: "en" if active_room == "EnglishHall" else "ar"
                bot._save_stock_investments = lambda: None
                bot.log = lambda *_args: None
                messages, private_messages, point_ops = [], [], []
                bot.send_room_text = lambda room, text: messages.append((room, text))
                bot.send_private_text = lambda user, text: private_messages.append((user, text))

                def apply_once(username, delta, transaction_id, reason, **kwargs):
                    point_ops.append((username, delta, transaction_id, reason))
                    return {"ok": True, "balance": delta}

                with patch.object(bot_module, "_apply_points_delta_once", side_effect=apply_once), \
                     patch.object(bot_module.secrets, "randbelow", side_effect=[outcome_draw, percent_draw]), \
                     patch.object(bot_module, "_record_game", return_value=None), \
                     patch.object(bot_module, "_save_local_json", return_value=None):
                    self.assertEqual(bot._process_stock_market_investments(now=1_000.0), 1)

                change = 100_000 * expected_percent // 100
                expected_payout = 100_000 + change if outcome == "profit" else 100_000 - change
                if expected_payout == 0:
                    self.assertEqual(point_ops, [])
                else:
                    self.assertEqual(point_ops[0][1], expected_payout)
                    self.assertNotIn("%", point_ops[0][3])
                self.assertEqual(bot.stock_market_history[0]["change_percent"], expected_percent)
                self.assertEqual(bot.stock_market_history[0]["change"], change)
                self.assertFalse(bot.stock_investments)
                result_by_room = dict(messages)
                self.assertEqual(set(result_by_room), {"ArabicHall"})
                self.assertIn("نتيجة البورصة", result_by_room["ArabicHall"])
                result = private_messages[0][1]
                self.assertNotIn("%", result)
                self.assertNotIn("%", result_by_room["ArabicHall"])
                self.assertIn("الخسارة" if outcome == "loss" else "الربح", result)
                self.assertEqual(len(private_messages), 1)
                self.assertEqual(private_messages[0][0], "Player")
                self.assertIn("غرفة الاستثمار: ArabicHall", result)

    def test_stock_history_is_private_paginated_and_ns_from_room_continues_it(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_market_history = [
            {"id": str(i), "username": "Player", "asset": 1 + (i % 4), "amount": 100_000,
             "outcome": "profit" if i % 2 else "loss", "change_percent": 5,
             "change": 5_000, "status": "settled", "started_at": 1_700_000_000 + i,
             "settled_at": 1_700_000_060 + i, "room": f"Hall{i}"}
            for i in range(7)
        ]
        bot.stock_investments = []
        bot._configured_room_language = lambda _room: "ar"
        bot._result_pages = {}
        private, packets = [], []
        bot.send_private_text = lambda user, text: private.append((user, text))
        bot._send_text_packets = lambda packet_type, text, **kwargs: packets.append((packet_type, text, kwargs))
        bot._room_list_commands = lambda *_args, **_kwargs: False
        self.assertTrue(bot._stock_history_command("Hall", "Player"))
        self.assertEqual(private[0][0], "Player")
        self.assertIn("سجل بورصتي", private[0][1])
        self.assertNotIn("%", private[0][1])
        self.assertEqual(len(bot._result_pages[("chat_message", "", "Player")]["pages"]), 3)
        self.assertTrue(bot._handle_management_command_impl("Hall", "ns", "Player", is_private=False))
        self.assertEqual(packets[-1][0], "chat_message")
        self.assertEqual(packets[-1][2], {"to": "Player"})
        self.assertIn("القائمة 2/3", packets[-1][1])

    def test_stock_history_persists_each_settlement_once(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_market_history = []
        writes = []
        with patch.object(bot_module, "_save_local_json", side_effect=lambda path, data: writes.append((path, data))):
            row = {"id": "market-1", "username": "Player", "amount": 100, "asset": 1, "status": "settled"}
            self.assertTrue(bot._record_stock_market_history(row))
            self.assertTrue(bot._record_stock_market_history(row))
        self.assertEqual(len(bot.stock_market_history), 1)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], bot_module.STOCK_MARKET_HISTORY_FILE)

    def test_recovered_stock_settlement_accepts_the_full_zero_to_one_hundred_range(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._stock_market_lock = threading.RLock()
        bot.stock_market_history = []
        bot.stock_investments = [{
            "id": "old-market", "username": "Player", "asset": 1, "amount": 100_000,
            "due_at": 0, "room": "Hall", "status": "paying", "outcome": "profit",
            "change_percent": 100, "change": 100_000,
        }]
        bot._save_stock_investments = lambda: None
        bot._active_rooms = lambda: ["Hall"]
        bot._configured_room_language = lambda _room: "ar"
        bot.send_room_text = lambda *_args: None
        bot.send_private_text = lambda *_args: None
        bot.log = lambda *_args: None
        with patch.object(bot_module, "_apply_points_delta_once", return_value={"ok": True, "balance": 120_000}) as apply, patch.object(
            bot_module, "_save_local_json", return_value=None
        ), patch.object(bot_module, "_record_game", return_value=None):
            self.assertEqual(bot._process_stock_market_investments(now=100), 1)
        self.assertEqual(apply.call_args.args[1], 200_000)
        self.assertEqual(bot.stock_market_history[0]["change_percent"], 100)
        self.assertEqual(bot.stock_market_history[0]["change"], 100_000)

    def test_plus_mf_accepts_unicode_word_persists_and_confirms_privately(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args, **_kwargs: False
        bot.moderation_enabled = False
        bot.banned_words = set()
        bot.log = lambda *_args: None
        private = []
        bot.send_private_text = lambda user, text: private.append((user, text))
        with patch.object(bot_module, "_is_master_name", return_value=True), patch.object(
            bot_module, "_save_moderation_config", return_value=[]
        ) as save_moderation, patch.object(bot_module, "_save_mf_config", return_value=[]):
            self.assertTrue(bot._handle_management_command_impl("", "+mf@الكلمه", "Master", is_private=True))
        self.assertIn("الكلمه", bot.banned_words)
        self.assertEqual(save_moderation.call_count, 1)
        self.assertIn("تمت إضافة الكلمة", private[-1][1])

    def test_new_gifts_and_highest_crop_are_wired_to_assets_and_rewards(self):
        expected_gifts = {
            "18": "gift_18_farm.jpg", "19": "gift_19_tractor.jpg", "20": "gift_20_barn.jpg",
            "21": "gift_21_diamond.jpg", "22": "gift_22_cat.jpg", "23": "gift_23_dog.jpg",
            "24": "gift_24_console.jpg", "25": "gift_25_trophy.jpg", "26": "gift_26_helicopter.jpg",
            "27": "gift_27_watch.jpg", "28": "gift_28_cupcake.jpg", "29": "gift_29_dolphin.jpg",
            "30": "gift_30_island.jpg", "31": "gift_31_rose_bouquet.jpg",
            "32": "gift_32_heart_pendant.jpg", "33": "gift_33_love_letter.jpg",
            "34": "gift_34_chocolate_box.jpg", "35": "gift_35_teddy_heart.jpg",
            "36": "gift_36_valentine_cake.jpg", "37": "gift_37_diamond_ring.jpg",
            "38": "gift_38_perfume.jpg", "39": "gift_39_heart_balloons.jpg",
            "40": "gift_40_love_hamper.jpg",
        }
        self.assertEqual(len(bot_module.GIFT_CATALOG), 40)
        for gift_id, expected_file in expected_gifts.items():
            self.assertIn(gift_id, bot_module.GIFT_CATALOG)
            self.assertEqual([path.name for path in bot_module.GIFT_IMAGE_FILES[gift_id]], [expected_file])
            self.assertTrue((bot_module.ASSETS_DIR / expected_file).is_file())
            self.assertLess((bot_module.ASSETS_DIR / expected_file).stat().st_size, 50_000)
            self.assertGreater(bot_module.GIFT_COSTS[gift_id], 0)

        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.crop_plots = {}
        bot.game_lock = threading.RLock()
        bot._game_cooldown_notice = lambda *_args: True
        bot._save_crop_plots = lambda: None
        bot._configured_room_language = lambda _room: "ar"
        messages = []
        bot.send_room_text = lambda room, text: messages.append(text)
        with patch.object(bot_module.time, "time", return_value=1_000.0):
            self.assertTrue(bot._crop_command("Hall", "Player", "زرع@🌳"))
        plot = next(iter(bot.crop_plots.values()))
        self.assertEqual(plot["reward"], 500_000_000)
        self.assertEqual(plot["minutes"], 60)

    def test_gift_help_shows_thirty_items_in_one_compact_list_and_ns_reports_end(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._effective_room_language = lambda _room: "en"
        bot._result_pages = {}
        bot.help_pages = {}
        packets = []
        bot._send_text_packets = lambda packet_type, text, **kwargs: packets.append((packet_type, text, kwargs))
        bot._room_list_commands = lambda *_args, **_kwargs: False
        bot.gift_help("Hall", "Player")
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0][0], "room_message")
        self.assertIn("List 1/2", packets[0][1])
        self.assertIn("30 🏝️ Island=", packets[0][1])
        self.assertNotIn("31 💐 Rose bouquet=", packets[0][1])
        self.assertNotIn("sa@id@username", packets[0][1])
        self.assertIn("ns for the next list", packets[0][1])
        self.assertLess(len(packets[0][1].encode("utf-8")), 1008)
        state = bot._result_pages[("room_message", "Hall", "Player")]
        self.assertEqual(len(state["pages"]), 2)
        self.assertTrue(bot._handle_management_command_impl("Hall", "ns", "Player", is_private=False))
        self.assertIn("List 2/2", packets[-1][1])
        self.assertIn("40 🧺 Romantic hamper=", packets[-1][1])
        self.assertIn("sa@id@username", packets[-1][1])
        self.assertIn("End of list", packets[-1][1])

    def test_gift_help_uses_ns_for_each_thirty_item_page(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._effective_room_language = lambda _room: "en"
        bot._result_pages = {}
        bot._room_list_commands = lambda *_args, **_kwargs: False
        packets = []
        bot._send_text_packets = lambda packet_type, text, **kwargs: packets.append((packet_type, text, kwargs))
        catalog = {str(i): ("🎁", f"Gift{i}") for i in range(1, 62)}
        english_names = {str(i): f"Gift{i}" for i in range(1, 62)}
        costs = {str(i): i for i in range(1, 62)}
        with patch.object(bot_module, "GIFT_CATALOG", catalog), patch.object(
            bot_module, "GIFT_CATALOG_EN", english_names
        ), patch.object(bot_module, "GIFT_COSTS", costs):
            bot.gift_help("Hall", "Player")
            state = bot._result_pages[("room_message", "Hall", "Player")]
            self.assertEqual(len(state["pages"]), 3)
            self.assertIn("Gift30=30", state["pages"][0])
            self.assertNotIn("Gift31=31", state["pages"][0])
            self.assertIn("Gift60=60", state["pages"][1])
            self.assertIn("Gift61=61", state["pages"][2])
            self.assertTrue(bot._handle_management_command_impl("Hall", "ns", "Player", is_private=False))
            self.assertIn("List 2/3", packets[-1][1])
            self.assertTrue(bot._handle_management_command_impl("Hall", "ns", "Player", is_private=False))
            self.assertIn("List 3/3", packets[-1][1])

    def test_crop_menu_is_paginated_in_thirty_item_lists_with_ns(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._effective_room_language = lambda _room: "ar"
        bot._result_pages = {}
        packets = []
        bot._send_text_packets = lambda packet_type, text, **kwargs: packets.append((packet_type, text, kwargs))
        self.assertTrue(bot._crop_command("Hall", "Player", "زرع"))
        self.assertEqual(len(packets), 1)
        self.assertIn("القائمة 1/1", packets[0][1])
        crop_rows = [line for line in packets[0][1].splitlines() if "=" in line]
        self.assertEqual(len(crop_rows), 24)
        self.assertLessEqual(len(crop_rows), 30)
        self.assertIn("🍎 5د=", packets[0][1])
        self.assertIn("🌳 90د=", packets[0][1])
        self.assertNotRegex(packets[0][1], r"(?:120|180|240|360|480|600|720)د=")
        self.assertIn("500m", packets[0][1])
        self.assertIn("اكتب ns", packets[0][1])

    def test_social_hunt_uses_generic_stock_photos_and_excludes_sender(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._effective_room_language = lambda _room: "ar"
        bot._fun_room_members = lambda room, sender: ["MaleTarget", "FemaleTarget"]
        bot._picture_gender_hint = lambda name: "female" if name == "FemaleTarget" else "male"
        bot.user_photos = {
            "maletarget": "https://profiles.example/male.jpg",
            "femaletarget": "https://profiles.example/female.jpg",
        }
        bot._game_cooldown_notice = lambda *_args: True
        bot._game_public_image = lambda path, route="games": f"https://media.example/{route}/{path.name}"
        bot.log = lambda *_args: None
        media, texts = [], []
        bot.send_room_media = lambda room, url, kind: media.append((room, url, kind)) or True
        bot.send_room_text = lambda room, text: texts.append(text)
        with patch.object(bot_module.secrets, "choice", side_effect=lambda seq: seq[0]), patch.object(
            bot_module.random, "choice", side_effect=lambda seq: seq[0]
        ):
            self.assertTrue(bot._random_social_hunt_game("Hall", "Player", "صيد مزه"))
            first_woman_photo = media[-1][1]
            self.assertTrue(bot._random_social_hunt_game("Hall", "Player", "صيد مزه"))
            second_woman_photo = media[-1][1]
            self.assertTrue(bot._random_social_hunt_game("Hall", "Player", "صيد مز"))
            first_man_photo = media[-1][1]
            self.assertTrue(bot._random_social_hunt_game("Hall", "Player", "صيد مز"))
            second_man_photo = media[-1][1]
        self.assertEqual(first_woman_photo, second_woman_photo)
        self.assertEqual(first_man_photo, second_man_photo)
        self.assertEqual(first_woman_photo, "https://profiles.example/female.jpg")
        self.assertEqual(first_man_photo, "https://profiles.example/male.jpg")
        self.assertTrue(all("صورة بروفايل العضو المختار" in text for text in texts))
        self.assertIn("@Player اصطاد مزه: @FemaleTarget", texts[0])
        self.assertIn("@Player اصطادت مز: @MaleTarget", texts[2])
        self.assertTrue(all(path.is_file() for paths in bot_module.SOCIAL_HUNT_IMAGE_FILES.values() for path in paths))
        self.assertEqual(set(bot_module.SOCIAL_HUNT_IMAGE_FILES), {"woman", "man"})
        bot._effective_room_language = lambda _room: "en"
        with patch.object(bot_module.secrets, "choice", side_effect=lambda seq: seq[0]):
            self.assertTrue(bot._random_social_hunt_game("Hall", "Player", "صيد مزه"))
        self.assertIn("Beauty Hunt", texts[-1])
        self.assertIn("selected member's profile photo", texts[-1])
        self.assertIn("@Player caught a beauty: @FemaleTarget", texts[-1])
        self.assertEqual(bot_module._normalize_game_command_text("hunt a beauty"), "صيد مزه")
        self.assertEqual(bot_module._normalize_game_command_text("my ex"), "طليقي")
        for command in ("صيد مزه", "صيد مز", "طليقي", "خلع", "طلاق"):
            self.assertTrue(bot_module._looks_like_bot_command(command))

    def test_social_hunt_falls_back_to_any_live_member_when_gender_is_unknown(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._effective_room_language = lambda _room: "ar"
        bot._fun_room_members = lambda _room, _sender: ["MysteryMember"]
        bot._picture_gender_hint = lambda _name: "unknown"
        bot._game_cooldown_notice = lambda *_args: True
        bot._game_public_image = lambda path, route="games": f"https://media.example/{route}/{path.name}"
        bot.send_room_media = lambda *_args: True
        messages = []
        bot.send_room_text = lambda _room, text: messages.append(text)
        with patch.object(bot_module.secrets, "choice", side_effect=lambda seq: seq[0]), patch.object(
            bot_module.random, "choice", side_effect=lambda seq: seq[0]
        ):
            self.assertTrue(bot._random_social_hunt_game("Hall", "Player", "صيد مز"))
        self.assertIn("@MysteryMember", messages[-1])

    def test_court_games_pick_a_random_member_and_return_the_requested_judgments(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._effective_room_language = lambda _room: "ar"
        bot._fun_room_members = lambda room, sender: ["Target"]
        texts = []
        bot.send_room_text = lambda room, text: texts.append(text)
        with patch.object(bot_module.secrets, "choice", return_value="Target"):
            for command in ("طليقي", "خلع", "طلاق"):
                self.assertTrue(bot._court_social_game("Hall", "Player", command))
        all_text = "\n".join(texts)
        self.assertIn("طليقك هو @Target", all_text)
        self.assertIn("بانتظار حكم المحكمة", all_text)
        self.assertIn("حكم القاضي بخلع @Player من @Target", all_text)
        self.assertIn("كامل النفقات للمخلوع @Player", all_text)
        self.assertIn("طلاق @Target طلاقاً بالثلاث", all_text)
        self.assertIn("المطلق: @Player", all_text)

    def test_bl_is_master_only_and_bans_every_connected_room_without_leaving(self):
        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        denied = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        denied._room_list_commands = lambda *_args: False
        denied_messages = []
        denied.send_private_text = lambda user, text: denied_messages.append((user, text))
        with patch.object(bot_module, "_is_master_name", return_value=False):
            self.assertTrue(denied._handle_management_command_impl("", "bl@Target", "Member", is_private=True))
        self.assertIn("مخصص للماستر فقط", denied_messages[0][1])

        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args: False
        bot.connected_rooms = {"RoomB", "RoomA"}
        bot.room = "StaleRoom"
        bot._room_bulk_lock = threading.RLock()
        bot.log = lambda *_args: None
        calls, messages, leave_calls = [], [], []
        bot.request_admin_action = lambda room, target, operation, requester, announce_room=False: calls.append(
            (room, target, operation, requester, announce_room)
        ) or True
        bot.send_private_text = lambda user, text: messages.append((user, text))
        bot.leave_room = lambda *args: leave_calls.append(args)
        with patch.object(bot_module, "_is_master_name", side_effect=lambda name: name == "Master"), patch.object(
            bot_module.threading, "Thread", ImmediateThread
        ), patch.object(bot_module.time, "sleep", return_value=None), patch.dict(
            bot_module.os.environ, {"GLOBAL_BAN_DELAY_SECONDS": "0.25"}
        ):
            self.assertTrue(bot._handle_management_command_impl("", "bl@Target", "Master", is_private=True))
        self.assertEqual([row[0] for row in calls], ["RoomA", "RoomB"])
        self.assertTrue(all(row[1:4] == ("Target", "ban", "Master") for row in calls))
        self.assertFalse(leave_calls)
        self.assertEqual(bot.connected_rooms, {"RoomA", "RoomB"})
        self.assertIn("البوت لا يغادر الغرف", messages[-1][1])

    def test_single_room_ban_does_not_schedule_leave_or_unnecessary_rejoin(self):
        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                return None

        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.connected_rooms = {"North"}
        bot.pending_admin_lock = threading.Lock()
        bot.pending_admin_actions = {}
        bot.room_users = {"North": {}}
        bot.last_admin_actions = {}
        bot._master_reply_local = threading.local()
        bot._master_reply_local.tracking = False
        bot.send_admin = lambda *_args: True
        bot.log = lambda *_args: None
        bot.send_private_text = lambda *_args: None
        bot.send_room_text = lambda *_args: None
        rejoin_calls, leave_calls = [], []
        bot._schedule_auto_rejoin = lambda room, delay=2.0: rejoin_calls.append((room, delay))
        bot.leave_room = lambda *args: leave_calls.append(args)
        with patch.object(bot_module, "_save_local_json"), patch.object(
            bot_module.threading, "Thread", ImmediateThread
        ):
            self.assertTrue(bot.request_admin_action("North", "Target", "ban", "Master"))
        self.assertFalse(rejoin_calls)
        self.assertEqual(bot.connected_rooms, {"North"})
        self.assertFalse(leave_calls)

    def test_leave_room_flushes_backup_before_room_leave_packet(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._intentional_leaves = set()
        bot.blocked_rooms = set()
        bot.known_rooms = {"North"}
        bot.connected_rooms = {"North"}
        bot.room_users = {"North": {}}
        bot._last_join_sent = {}
        bot._join_lock = threading.RLock()
        bot._server_room_catalog = ["North"]
        bot.log = lambda *_args: None
        events = []
        bot.send_query = lambda _payload: events.append("leave") or True
        with patch.object(bot_module, "_flush_github_backup", side_effect=lambda: events.append("backup") or True), patch.object(
            bot_module, "_save_persistent_rooms"
        ):
            self.assertTrue(bot.leave_room("North"))
        self.assertEqual(events[:2], ["backup", "leave"])


class NewFeatureRegressions(unittest.TestCase):
    def test_compact_money_amounts_for_stock_and_wagers(self):
        self.assertEqual(bot_module._parse_stock_market_order("ذهب 1m"), (1, 1_000_000))
        self.assertEqual(bot_module._parse_stock_market_order("gold 1b"), (1, 1_000_000_000))
        self.assertEqual(bot_module._parse_stock_market_order("فضة 2.5m"), (2, 2_500_000))
        self.assertEqual(bot_module._parse_compact_amount("١m"), 1_000_000)
        self.assertEqual(bot_module._parse_compact_amount("1b"), 1_000_000_000)
        self.assertTrue(bot_module._looks_like_bot_command("ذهب 1m"))
        self.assertTrue(bot_module._looks_like_bot_command("gold 1m"))
        self.assertTrue(bot_module._looks_like_bot_command("حظي 1b"))

        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.stock_pending = {}
        bot._snake_command = lambda *_args: False
        bot._ludo_command = lambda *_args: False
        bot._handle_pending_bot_choice = lambda *_args: False
        investments, wagers = [], []
        bot._stock_market_invest = lambda room, user, asset, amount, **kwargs: investments.append((asset, amount)) or True
        bot._queue_wager = lambda room, user, kind, amount: wagers.append((kind, amount)) or True
        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_games_enabled_for_room", return_value=True
        ):
            self.assertTrue(bot.handle_game_command("Hall", "ذهب 1m", "Player"))
            self.assertTrue(bot.handle_game_command("Hall", "حظي 1b", "Player"))
        self.assertEqual(investments, [(1, 1_000_000)])
        self.assertEqual(wagers, [("حظي", 1_000_000_000)])

    def test_single_invite_sends_a_fresh_private_invitation_on_each_command(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.invites_enabled = True
        bot.invite_lock = threading.Lock()
        bot.invite_sent = {"Ahmed"}
        bot.invite_message_template = "Join us in {room}"
        bot.log = lambda *_args: None
        sent = []
        bot.send_query = lambda payload: sent.append(bot_module.decode_message(payload)) or True
        self.assertTrue(bot.send_private_invite("Ahmed", "Garden", inviter="Master", allow_repeat=True))
        self.assertTrue(bot.send_private_invite("Ahmed", "Garden", inviter="Master", allow_repeat=True))
        self.assertEqual(len(sent), 2)
        for packet in sent:
            fields = {key: values[0] for key, values in packet.items()}
            self.assertEqual(fields[4], b"Ahmed")
            self.assertEqual(fields[5], b"Join us in Garden")

    def test_single_invite_reports_unsent_packet_as_failure(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.invites_enabled = True
        bot.invite_lock = threading.Lock()
        bot.invite_sent = set()
        bot.invite_message_template = "Join {room}"
        bot.log = lambda *_args: None
        bot.send_query = lambda _payload: False
        self.assertFalse(bot.send_private_invite("Ahmed", "Garden", allow_repeat=True))
        self.assertNotIn("Ahmed", bot.invite_sent)

    def test_i_at_and_arabic_daawa_name_route_to_single_user_invite_only(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.invites_enabled = True
        bot._room_list_commands = lambda *_args: False
        bot._inv_bot_owner_allowed = lambda _room: True
        bot._active_rooms = lambda: self.fail("individual invite must not start the group invitation flow")
        sent, replies = [], []
        bot.send_private_invite = lambda target, room, inviter="", allow_repeat=False: sent.append(
            (target, room, inviter, allow_repeat)
        ) or True
        bot.send_room_text = lambda room, text: replies.append((room, text))
        bot.send_private_text = lambda *_args: None
        for command in ("i@Ahmed", "دعوه Said", "دعوة Layla"):
            with patch.object(bot_module, "_is_master_name", return_value=True):
                self.assertTrue(bot._handle_management_command_impl("Garden", command, "Master", is_private=False))
        self.assertEqual([item[0] for item in sent], ["Ahmed", "Said", "Layla"])
        self.assertTrue(all(item[1:] == ("Garden", "Master", True) for item in sent))
        self.assertEqual(len(replies), 3)
        self.assertTrue(all("تم إرسال الدعوة" in reply for _, reply in replies))
        self.assertTrue(bot_module._looks_like_bot_command("دعوه Ahmed"))
        self.assertTrue(bot_module._looks_like_admin_command("دعوه Ahmed"))

    def test_ambiguous_role_changed_uses_pending_moderation_target_not_bot_actor(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.room_users = {"North": {"Target": "member"}}
        bot.known_rooms = {"North"}
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot.connected_rooms = {"North"}
        bot.pending_admin_lock = threading.Lock()
        bot.pending_admin_actions = {
            ("north", "target", "outcast"): {
                "room": "North", "target": "Target", "role": "outcast",
                "requester": "Master", "announce_room": False, "previous_role": "member",
            }
        }
        bot.last_admin_actions = {}
        bot.last_bot_bans = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        bot._schedule_auto_rejoin = lambda *_args, **_kwargs: self.fail("the bot actor must not be treated as the banned target")
        bot.send_room_text = lambda *_args: None
        bot.log = lambda *_args: None
        with patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
            bot_module, "_save_persistent_rooms"
        ), patch.object(bot_module, "_record_bot_ban"), patch.object(
            bot_module, "_save_local_json"
        ), patch.object(bot_module, "_is_master_name", return_value=True):
            bot._handle_room_event_impl({"room_event": {
                1: "role_changed", 13: "North", 17: "test-bot", 22: "Target", 31: "outcast",
            }})
        self.assertIn("North", bot.connected_rooms)
        self.assertNotIn("Target", bot.room_users["North"])
        self.assertFalse(bot.pending_admin_actions)
        ban = bot.last_bot_bans[bot_module._norm_room("North")]
        self.assertEqual(ban["target"], "Target")
        self.assertTrue(ban["active"])

    def test_user_left_with_actor_only_after_ban_does_not_trigger_rejoin(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.room_users = {"North": {"Target": "member"}}
        bot.known_rooms = {"North"}
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot.connected_rooms = {"North"}
        bot._master_online_rooms = set()
        bot._room_entry_times = {}
        bot._room_entry_users = {}
        bot._recent_room_moderation = {bot_module._norm_room("North"): {
            "target": "Target", "created_at": bot_module.time.time(), "role": "outcast",
        }}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        bot._schedule_auto_rejoin = lambda *_args, **_kwargs: self.fail("actor-only field 22 is not proof the bot left")
        bot.log = lambda *_args: None
        with patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
            bot_module, "_room_protection_cfg", return_value={}
        ), patch.object(bot_module, "_save_persistent_rooms"), patch.object(bot_module, "_remember_roster"):
            # Cover actor-only field 22 and the ambiguous field-17/field-22 order.
            for packet in (
                {1: "user_left", 13: "North", 22: "test-bot"},
                {1: "user_left", 13: "North", 17: "test-bot", 22: "Target"},
            ):
                bot._handle_room_event_impl({"room_event": packet})
        self.assertIn("North", bot.connected_rooms)
        self.assertIn("Target", bot.room_users["North"])

    def test_auto_unban_is_disabled_and_never_grants_member(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        calls = []
        bot.send_admin = lambda *args: calls.append(args)
        bot.log = lambda *_args: None
        self.assertFalse(bot._auto_unban("North", "RecentlyBanned"))
        self.assertFalse(calls)

    def test_dot_u_only_requests_unban_for_latest_confirmed_ban_in_same_room(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        room_key = bot_module._norm_room("Garden")
        bot.last_bot_bans = {room_key: {
            "room": "Garden", "target": "RecentlyBanned", "active": True,
            "undo_requested": False,
        }}
        calls, messages = [], []
        bot.request_admin_action = lambda *args, **kwargs: calls.append((args, kwargs)) or True
        bot.send_private_text = lambda who, text: messages.append((who, text))
        bot.log = lambda *_args: None
        with patch.object(bot_module, "_save_local_json"):
            self.assertTrue(bot._undo_last_bot_action("Master", "OtherRoom"))
            self.assertFalse(calls)
            self.assertTrue(bot._undo_last_bot_action("Master", "Garden"))
        self.assertEqual(calls[0][0], ("Garden", "RecentlyBanned", "member", "Master"))
        self.assertTrue(calls[0][1]["announce_room"])
        self.assertTrue(bot.last_bot_bans[room_key]["undo_requested"])
        self.assertIn("بانتظار تأكيد الخادم", messages[-1][1])

    def test_confirmed_unban_deactivates_room_ban_record(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room = ""
        bot.room_users = {"Garden": {}}
        bot.known_rooms = {"Garden"}
        bot.blocked_rooms = set()
        bot._blocked_room_notices = set()
        bot.connected_rooms = {"Garden"}
        bot.pending_admin_lock = threading.Lock()
        bot.pending_admin_actions = {
            ("garden", "target", "member"): {
                "room": "Garden", "target": "Target", "role": "member",
                "requester": "Master", "announce_room": False, "previous_role": "outcast",
            }
        }
        room_key = bot_module._norm_room("Garden")
        bot.last_bot_bans = {room_key: {
            "room": "Garden", "target": "Target", "active": True,
            "undo_requested": True,
        }}
        bot.last_admin_actions = {}
        bot._remember_inflight_command = lambda *_args, **_kwargs: None
        bot._report_monitored_event = lambda *_args, **_kwargs: None
        bot._complete_pending_room_list_text = lambda *_args, **_kwargs: False
        bot._is_duplicate_incoming = lambda *_args, **_kwargs: False
        bot.send_room_text = lambda *_args: None
        bot.log = lambda *_args: None
        with patch.object(bot_module, "_save_persistent_rooms"), patch.object(
            bot_module, "_save_local_json"
        ), patch.object(bot_module, "_is_master_name", return_value=True):
            bot._handle_room_event_impl({"room_event": {
                1: "role_changed", 13: "Garden", 17: "Target", 31: "member",
            }})
        self.assertFalse(bot.last_bot_bans[room_key]["active"])
        self.assertTrue(bot.last_bot_bans[room_key]["undone"])

    def test_payroll_requires_work_and_pays_once_then_enforces_cooldown(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        state = {"version": 1, "users": {}}
        messages, awards = [], []
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot.log = lambda *_args: None

        def load(_path, default):
            return state

        def save(_path, value, **_kwargs):
            nonlocal state
            state = value

        with patch.object(bot_module, "PAYROLL_FILE", Path("payroll-test.json")), patch.object(
            bot_module, "_load_local_json", side_effect=load
        ), patch.object(bot_module, "_save_local_json", side_effect=save), patch.object(
            bot_module, "_apply_points_delta_once",
            side_effect=lambda user, amount, txid, reason: awards.append((user, amount, txid, reason)) or {"ok": True, "balance": amount},
        ), patch.object(bot_module.secrets, "choice", return_value=("مزارع", 12_000)), patch.object(
            bot_module, "PAYROLL_COOLDOWN_SECONDS", 600
        ):
            with patch.object(bot_module.time, "time", return_value=1_000.0):
                bot._payroll_command("Hall", "Worker", "salary")
                bot._payroll_command("Hall", "Worker", "work")
                bot._payroll_command("Hall", "Worker", "salary")
                bot._payroll_command("Hall", "Worker", "salary")
            with patch.object(bot_module.time, "time", return_value=1_599.0):
                bot._payroll_command("Hall", "Worker", "work")

        self.assertEqual(len(awards), 1)
        self.assertEqual(awards[0][1], 12_000)
        self.assertTrue(awards[0][2].startswith("payroll:"))
        self.assertIn("أرسل عمل أولاً", messages[0][1])
        self.assertIn("وظيفة: مزارع", messages[1][1])
        self.assertIn("تم صرف راتبك", messages[2][1])
        self.assertIn("بعد", messages[-1][1])
        self.assertNotIn("pending", state["users"][bot_module._norm_user("Worker")])

    def test_bomb_game_is_manager_only_targets_the_named_user_and_kicks_on_wrong_wire(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {"Origin": {"Admin": "admin"}, "Other": {"Victim": "member"}}
        bot.bomb_games = {}
        bot._bomb_games_lock = threading.RLock()
        bot._active_rooms = lambda: ["Origin", "Other"]
        messages, private_messages, kicks = [], [], []
        scheduled = []
        bot._schedule_bomb_expiry = lambda key, expires_at: scheduled.append((key, expires_at))
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot.send_private_text = lambda who, text: private_messages.append((who, text))
        bot.request_admin_action = lambda *args, **kwargs: kicks.append((args, kwargs)) or True
        bot._configured_room_language = lambda _room: "ar"
        with patch.object(bot_module, "_room_manager", side_effect=lambda _bot, _room, user: user == "Admin"), patch.object(
            bot_module.secrets, "randbelow", return_value=0
        ):
            self.assertTrue(bot._bomb_command("Origin", "Admin", "Victim", "Other"))
            challenge = next(text for room, text in messages if room == "Other")
            confirmation = next(text for room, text in messages if room == "Origin")
            self.assertIn("Victim", challenge)
            self.assertIn("Admin", challenge)
            self.assertNotIn("@Victim", challenge)
            self.assertNotIn("@Admin", challenge)
            self.assertIn("30 ثانية", challenge)
            self.assertIn("إذا نجحت في التفكيك ستحصل على جائزة", challenge)
            self.assertIn("تم إرسال القنبلة", confirmation)
            self.assertIn("Other", confirmation)
            self.assertEqual(private_messages[-1][0], "Victim")
            self.assertIn("Admin", private_messages[-1][1])
            self.assertIn("Other", private_messages[-1][1])
            self.assertIn("30 ثانية", private_messages[-1][1])
            self.assertIn("ستحصل على جائزة", private_messages[-1][1])
            self.assertIn("Other", bot.bomb_games[(bot_module._norm_room("Other"), bot_module._norm_user("Victim"))]["room"])
            bomb_key = (bot_module._norm_room("Other"), bot_module._norm_user("Victim"))
            self.assertAlmostEqual(bot.bomb_games[bomb_key]["expires_at"] - bot_module.time.time(), 30.0, delta=0.1)
            self.assertEqual(scheduled, [(bomb_key, bot.bomb_games[bomb_key]["expires_at"])])
            self.assertFalse(bot._handle_bomb_wire("Other", "SomeoneElse", "2"))
            # Talkin can report a display/ID in the primary sender field while
            # the stored bomb target is the canonical username in another field.
            self.assertTrue(bot._route_room_game_input(
                "Other", "VictimDisplayId", "2", username_aliases=("Victim",)
            ))
        self.assertEqual(len(kicks), 1)
        self.assertEqual(kicks[0][0][0:3], ("Other", "Victim", "kick"))
        self.assertTrue(kicks[0][1]["announce_room"])
        source_result = [text for room, text in messages if room == "Origin"][-1]
        self.assertIn("انفجرت القنبلة", source_result)
        self.assertIn("Other", source_result)

    def test_bomb_rejects_target_missing_from_destination_room(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {"Origin": {"Admin": "admin"}, "Other": {"SomeoneElse": "member"}}
        bot._active_rooms = lambda: ["Origin", "Other"]
        messages = []
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot._configured_room_language = lambda _room: "ar"
        with patch.object(bot_module, "_room_manager", return_value=True):
            self.assertTrue(bot._bomb_command("Origin", "Admin", "Victim", "Other"))
        self.assertEqual(messages[-1][0], "Origin")
        self.assertIn("المستخدم @Victim غير موجود في الغرفة Other", messages[-1][1])

    def test_bomb_uses_database_roster_when_live_memory_is_stale(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {"Origin": {"Admin": "admin"}, "Other": {}}
        bot.db = type("DB", (), {"room_users": lambda _self, _room: [{"username": "Victim", "role": "member"}]})()
        bot.bomb_games = {}
        bot._bomb_games_lock = threading.RLock()
        bot._active_rooms = lambda: ["Origin", "Other"]
        bot._configured_room_language = lambda _room: "ar"
        bot.send_room_text = lambda *_args: True
        bot.send_private_text = lambda *_args: None
        bot._schedule_bomb_expiry = lambda *_args: None
        with patch.object(bot_module, "_room_manager", return_value=True):
            self.assertTrue(bot._bomb_command("Origin", "Admin", "Victim", "Other"))
        self.assertIn((bot_module._norm_room("Other"), bot_module._norm_user("Victim")), bot.bomb_games)

    def test_social_hunts_use_gender_matched_internet_fallback_without_profile_photo(self):
        for command, gender, expected_query in (
            ("صيد مزه", "female", "beautiful woman portrait"),
            ("صيد مز", "male", "handsome man portrait"),
        ):
            with self.subTest(command=command):
                bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
                bot.room_users = {"Room": {"Hunter": "admin", "Target": "member"}}
                bot.user_photos = {}
                bot._configured_room_language = lambda _room: "ar"
                bot._effective_room_language = lambda _room: "ar"
                bot._fun_room_members = lambda _room, _sender: ["Target"]
                bot._picture_gender_hint = lambda _name: gender
                bot._game_cooldown_notice = lambda *_args: True
                bot._lookup_profile_photo = lambda _name: ""
                bot.send_room_media = lambda _room, url, _kind: media.append(url) or True
                bot.send_room_text = lambda _room, text: messages.append(text)
                media, messages = [], []
                with patch.object(bot_module, "_search_lookalike_image", return_value=f"https://img.test/{gender}.jpg") as search:
                    self.assertTrue(bot._random_social_hunt_game("Room", "Hunter", command))
                self.assertIn(expected_query, search.call_args.args[0])
                self.assertEqual(media, [f"https://img.test/{gender}.jpg"])
                self.assertIn("صورة عشوائية من الإنترنت", messages[-1])

    def test_bomb_defusal_result_is_also_reported_in_source_room(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {"Origin": {"Admin": "admin"}, "Other": {"Victim": "member"}}
        bot.bomb_games = {}
        bot._bomb_games_lock = threading.RLock()
        bot._active_rooms = lambda: ["Origin", "Other"]
        messages = []
        bot._schedule_bomb_expiry = lambda *_args: None
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot.send_private_text = lambda *_args: None
        bot.request_admin_action = lambda *_args, **_kwargs: self.fail("defused bomb must not kick")
        bot._configured_room_language = lambda _room: "ar"
        with patch.object(bot_module, "_room_manager", return_value=True), patch.object(
            bot_module.secrets, "randbelow", return_value=0
        ):
            self.assertTrue(bot._bomb_command("Origin", "Admin", "Victim", "Other"))
        key = (bot_module._norm_room("Other"), bot_module._norm_user("Victim"))
        bot.bomb_games[key]["defuse_reward"] = 500_000
        expiry = bot.bomb_games[key]["expires_at"]
        with patch.object(bot_module, "_apply_points_delta_once", return_value={"ok": True, "balance": 500_000}) as award, patch.object(
            bot_module, "_record_game", return_value=None
        ):
            self.assertTrue(bot._handle_bomb_wire("Other", "Victim", "1"))
        self.assertEqual(award.call_args.args[0:2], ("Victim", 500_000))
        self.assertFalse(bot._expire_bomb_challenge(key, expiry))
        source_result = [text for room, text in messages if room == "Origin"][-1]
        destination_result = [text for room, text in messages if room == "Other"][-1]
        self.assertIn("نجح", source_result)
        self.assertIn("تفكيك القنبلة", source_result)
        self.assertIn("500k", source_result)
        self.assertIn("تفكيك القنبلة", destination_result)

    def test_bomb_timeout_without_wire_sends_kick_and_notifies_both_rooms_once(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.bomb_games = {}
        bot._bomb_games_lock = threading.RLock()
        key = (bot_module._norm_room("Other"), bot_module._norm_user("Victim"))
        expires_at = 2_000.0
        bot.bomb_games[key] = {
            "room": "Other", "source_room": "Origin", "target": "Victim",
            "started_by": "Admin", "wire": 2, "expires_at": expires_at,
        }
        kicks, messages = [], []
        bot.request_admin_action = lambda *args, **kwargs: kicks.append((args, kwargs)) or True
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot._configured_room_language = lambda _room: "ar"
        with patch.object(bot_module.time, "time", return_value=expires_at):
            self.assertTrue(bot._expire_bomb_challenge(key, expires_at))
            self.assertFalse(bot._expire_bomb_challenge(key, expires_at))
        self.assertEqual(len(kicks), 1)
        self.assertEqual(kicks[0][0][0:3], ("Other", "Victim", "kick"))
        self.assertTrue(kicks[0][1]["announce_room"])
        self.assertFalse(bot.bomb_games)
        self.assertEqual({room for room, _ in messages}, {"Origin", "Other"})
        self.assertTrue(all("لم يرسل Victim رقم السلك خلال 30 ثانية" in text for _, text in messages))
        self.assertTrue(all("تم إرسال طلب الطرد" in text for _, text in messages))

    def test_late_wire_after_deadline_is_not_treated_as_success_and_requests_kick(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.bomb_games = {}
        bot._bomb_games_lock = threading.RLock()
        key = (bot_module._norm_room("Hall"), bot_module._norm_user("Victim"))
        bot.bomb_games[key] = {
            "room": "Hall", "source_room": "Hall", "target": "Victim",
            "started_by": "Admin", "wire": 1, "expires_at": 2_000.0,
        }
        kicks, messages = [], []
        bot.request_admin_action = lambda *args, **kwargs: kicks.append((args, kwargs)) or True
        bot.send_room_text = lambda room, text: messages.append((room, text))
        bot._configured_room_language = lambda _room: "ar"
        with patch.object(bot_module.time, "time", return_value=2_001.0):
            self.assertTrue(bot._handle_bomb_wire("Hall", "Victim", "1"))
        self.assertEqual(len(kicks), 1)
        self.assertTrue(any("لم يرسل Victim رقم السلك خلال 30 ثانية" in text for _, text in messages))
        self.assertFalse(any("نجح Victim في تفكيك" in text for _, text in messages))

    def test_bomb_send_failure_is_reported_and_does_not_leave_a_live_challenge(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.room_users = {"Origin": {"Admin": "admin"}, "Other": {"Victim": "member"}}
        bot.bomb_games = {}
        bot._bomb_games_lock = threading.RLock()
        bot._active_rooms = lambda: ["Origin", "Other"]
        messages = []
        bot._schedule_bomb_expiry = lambda *_args: None
        def send_room_text(room, text):
            messages.append((room, text))
            return room != "Other"
        bot.send_room_text = send_room_text
        bot.send_private_text = lambda *_args: None
        bot._configured_room_language = lambda _room: "ar"
        with patch.object(bot_module, "_room_manager", return_value=True), patch.object(
            bot_module.secrets, "randbelow", return_value=0
        ):
            self.assertTrue(bot._bomb_command("Origin", "Admin", "Victim", "Other"))
        self.assertTrue(any(room == "Origin" and "فشل إرسال القنبلة" in text for room, text in messages))
        self.assertFalse(bot.bomb_games)

    def test_active_bomb_wire_is_claimed_before_cricket_or_board_games(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        calls = []
        bot._handle_bomb_wire = lambda room, username, text: calls.append(("bomb", room, username, text)) or True
        bot._route_active_board_game_join = lambda *_args: self.fail("bomb wire must not reach board-game join routing")
        bot._cricket = type("CricketStub", (), {
            "handle": lambda *_args, **_kwargs: self.fail("bomb wire must not reach Cricket")
        })()
        self.assertTrue(bot._route_room_game_input("Hall", "Victim", "2"))
        self.assertEqual(calls, [("bomb", "Hall", "Victim", "2")])

        bot._handle_bomb_wire = lambda *_args: False
        bot._route_active_board_game_join = lambda *_args: False
        bot._cricket = type("CricketStub", (), {
            "handle": lambda *_args, **_kwargs: True
        })()
        self.assertTrue(bot._route_room_game_input("Hall", "Player", "2"))

    def test_custom_gift_image_claim_is_owned_by_requesting_sender(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.custom_gift_pending = {
            bot_module._norm_user("Sender"): {
                "sender": "Sender", "receiver": "Receiver", "room": "Hall",
                "created_at": 10_000.0, "private_to": "",
            }
        }
        bot._custom_gift_pending_lock = threading.RLock()
        delivered = []
        bot._custom_gift_image_worker = lambda *args: delivered.append(args)
        with patch.object(bot_module.time, "time", return_value=10_030.0), patch.object(
            bot_module.threading, "Thread", lambda target, args, **_kwargs: type("T", (), {"start": lambda self: target(*args)})()
        ):
            self.assertFalse(bot._try_custom_gift_media("Hall", "https://img.test/a.jpg", ["Intruder"]))
            self.assertTrue(bot._try_custom_gift_media("Hall", "https://img.test/a.jpg", ["Sender"]))
        self.assertEqual(delivered[0][0:3], ("Hall", "Sender", "Receiver"))
        self.assertFalse(bot.custom_gift_pending)

    def test_dragon_hunter_welcome_expiration_is_ten_minutes(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._dragon_hunters_lock = threading.RLock()
        bot.dragon_hunters = {bot_module._norm_user("Hunter"): {"username": "Hunter", "expires_at": 1_600}}
        with patch.object(bot_module.time, "time", return_value=1_599.0):
            self.assertTrue(bot._is_dragon_hunter("Hunter"))
        with patch.object(bot_module.time, "time", return_value=1_600.0):
            self.assertFalse(bot._is_dragon_hunter("Hunter"))


class RoomSyncAndAnnouncementRegressions(unittest.TestCase):
    def test_join_timeout_reports_success_when_room_is_already_connected(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._pending_room_joins = {"syria": {"room": "سورياالحب", "requested_by": "Master"}}
        bot.connected_rooms = {"سورياالحب"}
        bot.known_rooms = set()
        bot.send_private_text = lambda user, text: sent.append((user, text))
        bot.log = lambda *_args: None
        sent = []
        with patch.object(bot_module, "_save_persistent_rooms"):
            bot._join_timeout("syria")
        self.assertEqual(len(sent), 1)
        self.assertIn("✅ البوت داخل الغرفة", sent[0][1])
        self.assertIn("سورياالحب", bot.known_rooms)
        self.assertEqual(bot.connected_rooms, {"سورياالحب"})

    def test_server_room_catalog_alone_does_not_claim_join_succeeded(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._pending_room_joins = {"syria": {"room": "سورياالحب", "requested_by": "Master"}}
        bot.connected_rooms = set()
        bot.known_rooms = {"سورياالحب"}
        bot._server_room_catalog = ["سورياالحب"]
        bot.send_private_text = lambda user, text: sent.append((user, text))
        bot.log = lambda *_args: None
        sent = []
        with patch.object(bot_module, "_save_persistent_rooms"):
            bot._join_timeout("syria")
        self.assertIn("❌ لم يتم دخول البوت إلى الغرفة", sent[0][1])
        self.assertNotIn("سورياالحب", bot.known_rooms)

    def test_server_room_list_finishes_full_sync_without_starting_joins(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.blocked_rooms = set()
        bot.known_rooms = set()
        bot._pending_full_room_sync = {"token": "x", "sender": "Master", "room": ""}
        bot._result_pages = {}
        bot._effective_room_language = lambda _room: "ar"
        bot.send_private_text = lambda *_args: None
        bot.log = lambda *_args: None
        joined = []
        bot._join_rooms_serially = lambda *args: joined.append(args)
        class ImmediateThread:
            def __init__(self, target=None, args=(), **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)
        with patch.object(bot_module.threading, "Thread", ImmediateThread), patch.object(
            bot_module, "_save_persistent_rooms"
        ):
            bot._process_room_list({"rooms": [{"name": "Room A"}, {"room": "Room B"}, {"title": "Room A"}]})
        self.assertIsNone(bot._pending_full_room_sync)
        self.assertEqual(joined, [])
        self.assertEqual(bot._server_room_catalog, ["Room A", "Room B"])
        self.assertEqual(bot.known_rooms, {"Room A", "Room B"})

    def test_empty_server_room_list_is_reported_as_a_real_response(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.blocked_rooms = set()
        bot.known_rooms = set()
        bot._pending_full_room_sync = {
            "token": "x", "sender": "Master", "room": "", "join_after": True
        }
        bot.log = lambda *_args: None
        finished = []
        bot._finish_full_room_sync = lambda rooms, from_server=False, join_after=False: finished.append(
            (rooms, from_server, join_after)
        ) or True
        bot._process_room_list({"rooms": []})
        self.assertEqual(finished, [([], True, True)])

    def test_server_room_list_extracts_numeric_protobuf_room_fields(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.blocked_rooms = set()
        bot.known_rooms = set()
        bot.log = lambda *_args: None
        with patch.object(bot_module, "_save_persistent_rooms"):
            bot._process_room_list([{1: "2024", 2: "ignored description"}, {1: "Room Numeric"}])
        self.assertIn("2024", bot.known_rooms)
        self.assertIn("Room Numeric", bot.known_rooms)

    def test_full_sync_falls_back_to_rooms_file_when_server_does_not_reply(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.blocked_rooms = set()
        bot.known_rooms = set()
        bot._pending_full_room_sync = {"token": "x", "sender": "Master", "room": ""}
        bot._result_pages = {}
        bot._effective_room_language = lambda _room: "ar"
        bot.send_private_text = lambda *_args: None
        bot._join_rooms_serially = lambda *_args: None
        with patch.object(bot_module, "_persistent_rooms", return_value=["Fallback A", "Fallback B"]), patch.object(
            bot_module, "_save_persistent_rooms"
        ):
            self.assertTrue(bot._finish_full_room_sync(["Fallback A", "Fallback B"], from_server=False))
        self.assertIsNone(bot._pending_full_room_sync)

    def test_room_sync_reports_successes_and_failures_to_requester(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_sync_jobs = {
            "sync": {"sender": "Master", "total": 2, "results": {}}
        }
        sent = []
        bot.send_private_text = lambda user, text: sent.append((user, text))
        bot._record_room_sync_result("sync", "Good", True, "تم تأكيد الدخول")
        self.assertEqual(len(sent), 0)
        bot._record_room_sync_result("sync", "Bad", False, "الغرفة محظورة")
        self.assertEqual(sent[0][0], "Master")
        self.assertIn("دخل 1 من أصل 2", sent[0][1])
        self.assertIn("Good", sent[0][1])
        self.assertIn("Bad: الغرفة محظورة", sent[0][1])

    def test_fetch_server_rooms_requests_server_list_without_joining(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args: False
        bot._request_full_room_sync = lambda sender, room, language=None, join_after=False: setattr(bot, "sync_request", (sender, room, language, join_after)) or True
        bot.send_private_text = lambda *_args: None
        with patch.object(bot_module, "_is_master_name", return_value=True):
            self.assertTrue(bot._handle_management_command_impl("", "جلب غرف السيرفر", "Master", is_private=True))
        self.assertEqual(bot.sync_request[0:2], ("Master", ""))

    def test_server_fetch_without_socket_does_not_show_saved_rooms(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.ws = None
        bot._server_room_catalog = ["OldRoom"]
        sent = []
        bot.send_private_text = lambda user, text: sent.append(text)
        with patch.object(bot_module, "_persistent_rooms", return_value=["SavedRoom"]):
            self.assertFalse(bot._request_full_room_sync("Master"))
        self.assertEqual(bot._server_room_catalog, [])
        self.assertTrue(any("لا يوجد اتصال" in text for text in sent))
        self.assertFalse(any("SavedRoom" in text for text in sent))

    def test_stock_round_announcements_are_enabled_by_default(self):
        self.assertTrue(bot_module.STOCK_MARKET_ROOM_ANNOUNCEMENTS_ENABLED)
        self.assertEqual(bot_module.STOCK_MARKET_INTERVAL_SECONDS, 600.0)


class MessageBackgroundDeliveryRegressions(unittest.TestCase):
    def test_direct_private_message_names_sender_and_confirms_success_privately(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []
        bot.send_private_text = lambda user, text: sent.append((user, text)) or True
        bot.log = lambda *_args: None

        self.assertTrue(bot._deliver_user_private_message("Sender", "Target", "hello"))
        self.assertEqual(sent[0][0], "Target")
        self.assertIn("📩 لديك رسالة من @Sender", sent[0][1])
        self.assertIn("hello", sent[0][1])
        self.assertEqual(sent[1][0], "Sender")
        self.assertIn("✅ تم إرسال الرسالة", sent[1][1])

    def test_direct_private_message_reports_failed_delivery(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        sent = []

        def fake_send(user, text):
            sent.append((user, text))
            return user != "Target"

        bot.send_private_text = fake_send
        bot.log = lambda *_args: None
        self.assertFalse(bot._deliver_user_private_message("Sender", "Target", "hello"))
        self.assertIn("❌ فشل إرسال الرسالة", sent[-1][1])

    def test_room_broadcast_command_starts_background_thread(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._room_list_commands = lambda *_args: False
        bot._active_rooms = lambda: ["Room A", "Room B"]
        bot._broadcast_room_message_worker = lambda *_args: self.fail("worker ran synchronously")
        sent = []
        bot.send_private_text = lambda user, text: sent.append((user, text)) or True
        bot.log = lambda *_args: None
        threads = []

        class DeferredThread:
            def __init__(self, target=None, args=(), **kwargs):
                self.target, self.args, self.kwargs = target, args, kwargs
                self.started = False
                threads.append(self)

            def start(self):
                self.started = True

        with patch.object(bot_module, "_is_primary_master", return_value=True), patch.object(
            bot_module.threading, "Thread", DeferredThread
        ):
            handled = bot._handle_management_command_impl(
                "", "رساله غرفه@تنبيه", "Master", is_private=True
            )
        self.assertTrue(handled)
        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0].started)
        self.assertIn("الخلفية", sent[-1][1])
        with patch.object(bot_module, "_is_primary_master", return_value=True), patch.object(
            bot_module.threading, "Thread", DeferredThread
        ):
            handled = bot._handle_management_command_impl(
                "", "room message@Hello all", "Master", is_private=True
            )
        self.assertTrue(handled)
        self.assertEqual(len(threads), 2)
        self.assertIn("Background broadcast started", sent[-1][1])

    def test_room_broadcast_worker_reports_per_room_send_results(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._active_rooms = lambda: ["Room A", "Room B"]
        bot._room_bulk_lock = threading.Lock()
        sent_rooms = []
        bot.send_room_text = lambda room, _text: sent_rooms.append(room) or (room == "Room A")
        private = []
        bot.send_private_text = lambda user, text: private.append((user, text)) or True
        bot.log = lambda *_args: None
        with patch.object(bot_module.time, "sleep", return_value=None):
            bot._broadcast_room_message_worker("Master", "notice")
        self.assertEqual(sent_rooms, ["Room A", "Room B"])
        self.assertIn("وصلت إلى 1 غرفة، وفشل 1 من 2", private[-1][1])

    def test_unknown_cached_room_role_does_not_preempt_server_stream_authorization(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.music_last = {}
        bot._bot_room_role = lambda _room: ""
        bot._bot_is_room_owner = lambda _room: False
        bot._capture_room_response_language = lambda *_args: "ar"
        room_messages = []
        bot.send_room_text = lambda _room, text: room_messages.append(text) or True
        bot.log = lambda *_args: None
        threads = []

        class DeferredThread:
            def __init__(self, target=None, args=(), **kwargs):
                self.target, self.args = target, args
                threads.append(self)

            def start(self):
                pass

        with patch.object(bot_module.threading, "Thread", DeferredThread):
            self.assertTrue(bot.handle_music_command("Room", ".sa song", "User", live_stream=True))
        self.assertEqual(len(threads), 1)
        self.assertFalse(any("يجب أن تكون رتبة البوت" in text for text in room_messages))
        self.assertFalse(any("must be an Owner" in text for text in room_messages))

    def test_stale_room_restore_candidate_is_not_reported_as_connected(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot.connected_rooms = set()
        bot._room_restore_candidates = {"room"}
        bot._pending_room_joins = {}
        bot._room_bulk_lock = threading.Lock()
        bot.blocked_rooms = set()
        bot._blocked_room_reasons = {}
        bot._join_lock = threading.Lock()
        bot._last_join_sent = {}
        sent = []
        joins = []
        bot.send_private_text = lambda user, text: sent.append((user, text))
        bot.log = lambda *_args: None
        bot.join_room = lambda target, **_kwargs: joins.append(target) or True
        bot._join_rooms_serially(["Room"], "Master", fast_restore=False)
        self.assertEqual(joins, ["Room"])
        self.assertFalse(any("البوت داخل الغرفة" in text for _user, text in sent))


if __name__ == "__main__":
    unittest.main()
