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
    def make_integration(self, root, room_messages, private_messages, media_messages):
        return CricketIntegration(
            root,
            is_master=lambda name: str(name).casefold() == "master",
            is_configured_master=lambda name: str(name).casefold() == "master",
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

            # The master-only switches must not work in a room.
            integration.handle("North", "Master", ".cr 1")
            self.assertFalse(integration.game.enabled())
            self.assertIn("خاص البوت", room_messages[-1][1])
            integration.handle("North", "Master", ".cr 0")
            self.assertFalse(integration.game.enabled())
            self.assertIn("خاص البوت", room_messages[-1][1])
            integration.handle("North", "Master", "cricket on")
            self.assertFalse(integration.game.enabled())
            self.assertIn("خاص البوت", room_messages[-1][1])

            integration.handle("North", "Master", ".cr 1", is_private=True)
            self.assertTrue(integration.game.enabled())
            self.assertEqual(integration.game.current()["stage"], "setup")
            self.assertIn("تشغيل لعبة الكركيت", private_messages[-1][1])

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

    def test_restart_resumes_a_saved_batting_choice_without_replaying_old_events(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            room_messages, private_messages, media_messages = [], [], []
            first = self.make_integration(root, room_messages, private_messages, media_messages)
            first.handle("North", "Master", "تشغيل لعبه الكركيت", is_private=True)
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
            self.assertTrue(integration.handle("Hall", "Player", "6"))
            self.assertTrue(any("الكرة 1/6" in text for _, text in messages))
            self.assertTrue(media, "the solo bot match should resolve and deliver a ball result")


class BotGameAndMusicRegressions(unittest.TestCase):
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
        bot._active_rooms = lambda: ["Room A"]
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
                broadcast_all=False, with_reactions=False,
            ))

        media_index = next(i for i, item in enumerate(sent) if item[0] == "media")
        caption_index = next(i for i, item in enumerate(sent) if item[0] == "text" and "تم تشغيل الأغنية" in item[2])
        self.assertLess(media_index, caption_index)
        self.assertEqual(sent[media_index][1:4], ("Room A", "https://cdn.example/track.mp3", "audio"))

    def test_cricket_help_has_sixth_page_and_hides_bl_at_alias(self):
        sections = bot_module._default_help_sections()
        self.assertEqual(len(sections[3]), 6)
        self.assertIn(".cr 1", sections[3][5])
        self.assertIn(".cr 0", sections[3][5])
        self.assertIn("كل الأعضاء", sections[3][5])
        self.assertIn("start cricket game", sections[3][5])
        self.assertNotIn("bl@", sections[1][0])
        self.assertNotIn("حظر بكل الغرف", sections[1][0])

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
