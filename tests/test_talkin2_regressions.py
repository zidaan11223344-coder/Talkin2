from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot as bot_module
from cricket_game import CricketGame
from cricket_integration import CricketIntegration
from cricket_result import render_result_image


class CricketIntegrationRegressions(unittest.TestCase):
    def make_integration(self, root, room_messages, private_messages, media_messages, is_verified=None, send_all_rooms_text=None):
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
            log=lambda *_args: None,
        )

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

            integration.handle("North", "N1", "1")
            self.assertEqual(integration.game.current()["stage"], "lobby")
            integration.handle("North", "N1", "Join")
            integration.handle("South", "S1", "Join")
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
            first.handle("North", "N1", "1")
            first.handle("North", "N1", "Join")
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
            first.handle("North", "Master", "1")
            first.handle("North", "N1", "Join")
            first.handle("South", "S1", "Join")
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

    def test_each_player_gets_six_balls_in_both_innings_and_lead_does_not_end_match_early(self):
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
            self.assertEqual({room for room, _ in first_team_announcements}, {"North", "South", "Lobby"})
            self.assertEqual(len(first_team_announcements), 3)
            for _, text in first_team_announcements:
                self.assertIn("North (2 لاعبين): @N1، @N2", text)
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
            for player in ("N1", "N2"):
                self.assertEqual(batting_counts[(1, player)], 6)
                self.assertEqual(bowling_counts[(2, player)], 6)
            for player in ("S1", "S2"):
                self.assertEqual(bowling_counts[(1, player)], 6)
                self.assertEqual(batting_counts[(2, player)], 6)
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
                    current = data["match"]
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
            self.assertIn("كل لاعب يرسل Join", setup_text)
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

    def test_decorated_username_matches_game_stats_and_keeps_display_name(self):
        decorated = "♥☼هـــــ☼ـــادي☼♥اا"
        with patch.object(bot_module, "_game_stats_data", return_value={
            "هادياا": {
                "username": "هادياا",
                "games": {"star": {"plays": 21}},
            }
        }):
            level, label, plays = bot_module._game_level_info(decorated)
            welcome = bot_module._game_welcome(decorated, "North")
            self.assertEqual(level, 2)
            self.assertEqual(plays, 21)
            self.assertIn(label, welcome)
            self.assertIn(decorated, welcome)
            self.assertIn("🏅 مستوى الألعاب: 2", welcome)

    def test_new_player_gets_level_and_star_welcome(self):
        decorated = "♥☼هـــــ☼ـــادي☼♥اا"
        with patch.object(bot_module, "_game_stats_data", return_value={}):
            welcome = bot_module._game_welcome(decorated, "North")
            self.assertIn(decorated, welcome)
            self.assertIn("🏅 مستوى الألعاب: 1", welcome)
            self.assertIn("⭐ ترتيب النجوم", welcome)

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
                # Numbered options from the room are rejected even while a private menu is pending.
                self.assertTrue(bot._handle_management_command_impl("North", "3", "Master", is_private=False))
                self.assertEqual(saved, [])
                self.assertIn("خاص", private[-1][1])
                self.assertTrue(bot._handle_management_command_impl("", "3", "Master", is_private=True))
                self.assertEqual(saved, [("North", {"flood": True})])

            self.assertTrue(bot._handle_management_command_impl("North", "حماية@North", "Master", is_private=False))
            self.assertIn("خاص", private[-1][1])
            self.assertEqual(public, [], "the protection menu must never be published in a room")
            self.assertTrue(bot._handle_management_command_impl("", "حماية@North", "Guest", is_private=True))
            self.assertIn("مخصصة", private[-1][1])

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
