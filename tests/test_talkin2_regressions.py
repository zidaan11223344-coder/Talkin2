from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import bot as bot_module
from cricket_game import CricketGame
from cricket_integration import CricketIntegration
from cricket_result import render_result_image


class IncomingEventDedupRegressions(unittest.TestCase):
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
        self.assertEqual(saved[0][1], {"replies": {"ق": ["بقلبي"]}})

    def test_departure_command_uses_last_user_and_dedicated_reply(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._last_departed_user_by_room = {bot_module._norm_room("North"): "left_user"}
        bot.departure_replies = {"ق": ["بقلبي"]}
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        self.assertTrue(bot._handle_departure_reply_command("North", "ق"))
        self.assertIn("left_user", sent[0][1])
        self.assertIn("بقلبي", sent[0][1])


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


class RawWebSocketTransportRegressions(unittest.TestCase):
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
            self.assertTrue(any("اكتمل الفريق الأول" in text for _, text in room_messages[1:]))

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

    def test_cr1_starts_fresh_setup_instead_of_resuming_persisted_match(self):
        with tempfile.TemporaryDirectory() as temp:
            room_messages, private_messages, media_messages = [], [], []
            integration = self.make_integration(Path(temp), room_messages, private_messages, media_messages)
            integration.handle("North", "Master", ".cr 1", is_private=True)
            integration.handle("North", "N1", ".cr 1")
            integration.handle("North", "N1", "2")
            integration.handle("North", "N1", "Join")
            self.assertEqual(integration.game.current()["stage"], "lobby")
            old_match_id = integration.game.current()["id"]
            def add_finished_match_result(data):
                data["match"] = None
                integration.game._emit(
                    data, [{"key": "north", "name": "North"}],
                    "🏆 نتيجة مباراة قديمة", ("cricket_result_old.png",),
                )
            integration.game.state.mutate(add_finished_match_result)
            integration.handle("North", "N1", ".cr 1")
            fresh = integration.game.current()
            self.assertEqual(fresh["stage"], "setup")
            self.assertNotEqual(fresh["id"], old_match_id)
            self.assertEqual(fresh["rooms"][0]["players"], [])
            self.assertIn("إعداد مباراة الكركيت", room_messages[-1][1])
            self.assertFalse(any("مباراة قديمة" in text for _, text in room_messages[-2:]))
            self.assertFalse(any("cricket_result_old.png" in url for _, url, _ in media_messages))

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
                north_code = north_match["join_code"]
                east_code = east_match["join_code"]
                self.assertNotEqual(north_match["id"], east_match["id"])
                self.assertNotEqual(north_code, east_code)

                # A room must not accidentally join the neighboring match's code.
                wrong_code = next(code for code in ("000000", "FFFFFF", "ABCDEF", "123456")
                                  if code not in {north_code, east_code})
                integration.handle("South", "S1", f"Join@{wrong_code}")
                self.assertIsNone(integration.game.current("South"))

                # A bare Join cannot guess between simultaneous waiting games.
                integration.handle("South", "S1", "Join")
                self.assertTrue(any("توجد عدة مباريات انتظار" in text for room, text in messages if room == "South"))

                for index in range(1, count + 1):
                    integration.handle("South", f"S{index}", f"Join@{north_code}")
                    integration.handle("West", f"W{index}", f"Join@{east_code}")

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
                (room, text) for room, text in room_messages if "اكتمل الفريق الأول" in text
            ]
            self.assertEqual({room for room, _ in first_team_announcements}, {"North"})
            self.assertEqual(len(first_team_announcements), 1)
            self.assertIn("North (2 لاعبين): @N1، @N2", first_team_announcements[0][1])
            self.assertIn("رمز هذه المباراة", first_team_announcements[0][1])
            self.assertEqual(integration.game.current()["stage"], "lobby")

            for player in ("S1", "S2"):
                integration.handle("South", player, "Join")
            integration.handle("North", "N1", "1")

            started = [(room, text) for room, text in room_messages if "بدأت لعبة الكركيت" in text]
            self.assertEqual({room for room, _ in started}, {"North", "South"})
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
            self.assertEqual(integration.game.get_points("S1") + integration.game.get_points("S2"), 200_000)

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
            self.assertIn("Join@", setup_text)
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
        self.assertEqual(level, 7)
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
            self.assertEqual(level, 3)
            self.assertEqual(plays, 50)
            self.assertIn(label, welcome)
            self.assertIn(decorated, welcome)
            self.assertIn("🏅 مستوى الألعاب: 3", welcome)

    def test_new_player_gets_level_and_star_welcome(self):
        decorated = "♥☼هـــــ☼ـــادي☼♥اا"
        with patch.object(bot_module, "_game_stats_data", return_value={}):
            welcome = bot_module._game_welcome(decorated, "North")
            self.assertIn(decorated, welcome)
            self.assertNotIn("🏅 مستوى الألعاب", welcome)
            self.assertNotIn("⭐ ترتيب النجوم", welcome)
            self.assertIn("🎯 جولاتك: 0", welcome)

    def test_game_level_welcome_starts_at_exactly_50_games(self):
        with patch.object(bot_module, "_game_stats_data", return_value={
            "player": {"username": "player", "games": {"star": {"plays": 49}}}
        }):
            before = bot_module._game_welcome("player", "North")
        with patch.object(bot_module, "_game_stats_data", return_value={
            "player": {"username": "player", "games": {"star": {"plays": 50}}}
        }):
            after = bot_module._game_welcome("player", "North")
        self.assertNotIn("🏅 مستوى الألعاب", before)
        self.assertIn("🏅 مستوى الألعاب", after)

    def test_join_welcome_uses_vip_only_before_50_games(self):
        with patch.object(bot_module, "_is_vip_user", side_effect=lambda name: name == "vip"):
            with patch.object(bot_module, "_game_stats_data", return_value={}):
                self.assertIsNone(bot_module._join_welcome_message("regular", "North"))
                vip_welcome = bot_module._join_welcome_message("vip", "North")
            self.assertIn("عضو Vip", vip_welcome)

    def test_join_welcome_uses_game_level_at_50_games(self):
        records = {"regular": {"username": "regular", "games": {"star": {"plays": 50}}}}
        with patch.object(bot_module, "_is_vip_user", return_value=False), patch.object(
            bot_module, "_game_stats_data", return_value=records
        ):
            welcome = bot_module._join_welcome_message("regular", "North")
        self.assertIn("🏅 مستوى الألعاب", welcome)

    def test_sb_uses_sender_balance_and_msb_is_master_private_only(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        room_replies = []
        private_replies = []
        bot.send_room_text = lambda room, text: room_replies.append((room, text))
        bot.send_private_text = lambda user, text: private_replies.append((user, text))
        changes = []
        with patch.object(bot_module, "_is_verified_user", return_value=True), patch.object(
            bot_module, "_get_points", return_value=1000
        ), patch.object(bot_module, "_add_points", side_effect=lambda user, amount: changes.append((user, amount)) or 900):
            self.assertTrue(bot._handle_management_command_impl("North", "sb@target@100", "member"))
        self.assertIn(("member", -100), changes)
        self.assertIn(("target", 100), changes)

        changes.clear()
        with patch.object(bot_module, "_is_primary_master", return_value=True), patch.object(
            bot_module, "_add_points", side_effect=lambda user, amount: changes.append((user, amount)) or 100
        ):
            self.assertTrue(bot._handle_management_command_impl("", "msb@target@100", "Master", is_private=True))
        self.assertEqual(changes, [("target", 100)])

        with patch.object(bot_module, "_is_primary_master", return_value=True):
            self.assertTrue(bot._handle_management_command("North", "msb@target@100", "Master"))
        self.assertTrue(any("خاص البوت" in text for _, text in room_replies))

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

    def test_million_bank_result_has_no_artificial_reveal_sleep(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        bot._game_cooldown_notice = lambda *_args: True
        sent = []
        bot.send_room_text = lambda room, text: sent.append((room, text))
        with patch.object(bot_module.secrets, "randbelow", return_value=99), patch.object(
            bot_module, "_record_game", lambda *_args: None
        ), patch.object(bot_module.time, "sleep", side_effect=AssertionError("unexpected delay")):
            self.assertTrue(bot._million_bank_game("North", "Player"))
        self.assertEqual(len(sent), 2)
        self.assertIn("جاري البحث", sent[0][1])
        self.assertIn("لم يحالفه الحظ", sent[1][1])

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
            bot._join_rooms_serially = lambda rooms, sender: joined.append((rooms, sender))
            self.assertTrue(bot._handle_management_command_impl("", "دخول غرفي", "Master", is_private=True))

        self.assertEqual(joined, [(["North", "South"], "Master")])
        self.assertIn("2 غرفة", sent[-1])

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
                with patch.object(bot_module, "_room_manager", return_value=True):
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
        with patch.object(bot_module, "_room_manager", return_value=True), patch.object(
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

        result = bot._music_fast_source("fast song")

        self.assertTrue(audius_started.wait(1))
        self.assertEqual(result["url"], "https://cdn.example/fast.mp3")

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

    def test_oversized_game_result_is_split_into_room_messages_not_telegram(self):
        bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
        packets = []
        bot.send_query = lambda payload: packets.append(payload)
        bot.log = lambda *_args: None
        bot._send_long_text_to_telegram = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("game results should stay in the room")
        )
        text = "🏆 انتهت مباراة الكركيت\n" + "\n".join(
            f"💰 @Player{i} +200,000 نقطة — جائزة الفريق الأول والثاني" for i in range(20)
        )

        with patch.dict(bot_module.os.environ, {"WS_MAX_MESSAGE_BYTES": "300"}):
            self.assertTrue(bot._send_text_packets("room_message", text, room="North"))

        self.assertGreater(len(packets), 1)
        decoded = [bot_module.decode_message(packet) for packet in packets]
        self.assertTrue(all(len(packet) <= 300 for packet in packets))
        self.assertTrue(all(fields[6][0].decode("utf-8") == "North" for fields in decoded))
        self.assertEqual("".join(fields[5][0].decode("utf-8") for fields in decoded), text)

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

            expected = {"N1": 66_667, "N2": 66_667, "N3": 66_666}
            self.assertEqual(sum(amount for _, amount in awarded), 200_000)
            self.assertEqual(dict(awarded), expected)
            self.assertEqual(captured[0]["player_awards"], expected)
            self.assertEqual(sum(game.get_points(name) for name in expected), 200_000)
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


if __name__ == "__main__":
    unittest.main()
