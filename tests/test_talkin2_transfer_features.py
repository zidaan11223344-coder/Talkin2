import copy
import threading
from unittest.mock import patch

import bot as bot_module
from treasure_mining import DIAMOND_KEYS, MiningStore


def test_levels_command_shows_one_complete_tier_per_numbered_page_and_ns_advances():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.help_pages = {}
    bot.help_page_part = {}
    bot.help_game_part = {}
    bot._result_pages = {}
    bot._filter_list_state = {}
    bot._effective_room_language = lambda _room: "ar"
    bot._room_list_commands = lambda *_args: False
    messages = []
    packets = []
    bot.send_room_text = lambda room, text: messages.append((room, text))
    bot.send_query = lambda packet: packets.append(packet) or True

    assert bot._handle_management_command("North", "مستويات", "Player", is_private=False)
    assert len(messages) == 1
    first_page = messages[0][1]
    assert first_page.index("📄 القائمة 1/") < first_page.index("📚 مستويات تقدم الألعاب")
    assert "كل مستوى يحتاج 500 لعبة" in first_page
    assert "المستوى الفضي" in first_page
    assert "⭐ النجوم الفضية" in first_page
    assert "1: ⭐ — مبتدئ" in first_page
    assert "2: ⭐⭐ — لاعب ناشئ" in first_page
    assert f"10: {'⭐' * 10} — أسطورة فضية" in first_page
    assert "المستوى الذهبي" not in first_page
    assert "من 0 إلى" not in first_page
    assert "500 إلى" not in first_page

    result_key = ("room_message", "North", "Player")
    assert len(bot._result_pages[result_key]["pages"]) >= len(bot_module.GAME_LEVEL_CATEGORIES)
    assert bot._handle_management_command("North", "ns", "Player", is_private=False)
    assert bot._result_pages[result_key]["part"] == 2
    next_text = bot_module.as_text(bot_module.decode_message(packets[0])[5][0])
    assert next_text.startswith("📄 القائمة 2/")
    assert "المستوى الذهبي" in next_text
    assert "🌟 النجوم الذهبية" in next_text
    assert "1: 🌟 — ذهبي مبتدئ" in next_text


def test_master_diamond_check_rotates_inventory_item_and_sends_room_image(tmp_path, monkeypatch):
    state = {"version": 1, "players": {}}
    store = MiningStore(
        tmp_path / "mining_game.json",
        load_json=lambda _path, _default: copy.deepcopy(state),
        save_json=lambda _path, data: state.update(copy.deepcopy(data)),
    )
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    sent = []
    media = []
    bot.send_room_text = lambda room, text: sent.append((room, text))
    bot.send_room_media = lambda room, url, kind: media.append((room, url, kind)) or True
    bot._game_public_image = lambda path, route="games": f"https://assets.example/{route}/{path.name}"
    bot.log = lambda *_args, **_kwargs: None
    monkeypatch.setattr(bot_module, "MINING_STORE", store)
    monkeypatch.setattr(bot_module, "_is_master_name", lambda name: name == "Master")

    assert bot_module._looks_like_bot_command("فحص الماس")
    assert bot._execute_mining_command_with_id("North", "فحص الماس", "Master", "88")
    assert bot._execute_mining_command_with_id("North", "فحص الماس", "Master", "88")
    assert DIAMOND_KEYS[0] in state["players"]["88"]["inventory"]
    assert state["players"]["88"]["inventory"][DIAMOND_KEYS[0]] == 1
    assert state["players"]["88"]["inventory"][DIAMOND_KEYS[1]] == 1
    assert len(media) == 2
    assert media[0] == ("North", "https://assets.example/assets/treasures/diamond_clear.jpg", "image")
    assert media[1] == ("North", "https://assets.example/assets/treasures/diamond_blue.jpg", "image")
    assert all("قيمة الاستبدال:" in text for _room, text in sent)

    monkeypatch.setattr(bot_module, "_is_master_name", lambda _name: False)
    assert bot._execute_mining_command_with_id("North", "فحص الماس", "Player", "99")
    assert "مخصص للماستر فقط" in sent[-1][1]
    assert "99" not in state["players"]


def test_auto_rejoin_pauses_after_three_rapid_confirmed_room_exits():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    room_key = bot_module._norm_room("Hall")
    bot.connected_rooms = set()
    bot._pending_room_joins = {}
    bot._intentional_leaves = set()
    bot.blocked_rooms = set()
    bot._auto_rejoin_lock = threading.Lock()
    bot._auto_rejoin_pending = set()
    bot._auto_rejoin_waiting_ack = set()
    bot._auto_rejoin_paused = set()
    bot._auto_rejoin_state = {
        room_key: {"attempts": [], "joined_at": bot_module.time.monotonic(), "rapid_losses": 0}
    }
    bot._connection_generation = 1
    bot._room_bulk_lock = threading.RLock()
    bot.log = lambda *_args: None
    joins = []
    notices = []
    bot.join_room = lambda room, **_kwargs: joins.append(room) or True
    bot.send_private_text = lambda user, text: notices.append((user, text)) or True

    class ImmediateThread:
        def __init__(self, target=None, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    with patch.object(bot_module.threading, "Thread", ImmediateThread), patch.object(
        bot_module.time, "sleep", lambda _delay: None
    ), patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
        bot_module, "BOT_MASTER", "Master"
    ):
        for expected_joins in (1, 2):
            bot._schedule_auto_rejoin("Hall", delay=0)
            assert len(joins) == expected_joins
            bot._auto_rejoin_waiting_ack.discard(room_key)
            bot._auto_rejoin_state[room_key]["joined_at"] = bot_module.time.monotonic()
        bot._schedule_auto_rejoin("Hall", delay=0)

    assert len(joins) == 2
    assert bot._auto_rejoin_paused == {room_key}
    assert len(notices) == 1
    assert "أوقفت إعادة الدخول التلقائية" in notices[0][1]
    assert "دخول@اسم_الغرفة" in notices[0][1]


def test_room_departure_notice_is_rate_limited_per_room():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot.log = lambda *_args: None
    bot._redact_connection_secrets = lambda text: text
    notices = []
    bot.send_private_text = lambda user, text: notices.append((user, text)) or True

    with patch.object(bot_module, "BOT_ID", "test-bot"), patch.object(
        bot_module, "BOT_MASTER", "Master"
    ), patch.object(bot_module.time, "monotonic", side_effect=[100.0, 101.0]):
        bot._send_master_room_departure_notice("Hall", "user_left")
        bot._send_master_room_departure_notice("Hall", "user_left")

    assert len(notices) == 1
    assert "إذا تكرر الخروج سريعًا فسيوقف المحاولات" in notices[0][1]
