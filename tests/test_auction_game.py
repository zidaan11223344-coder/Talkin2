import copy
from pathlib import Path

import bot as bot_module
from auction_game import (
    AUCTION_ITEMS,
    BID_INCREMENT,
    BIDDING_DURATION_SECONDS,
    MAX_IMAGE_BYTES,
    MAX_PARTICIPANTS,
    TURN_TIMEOUT_SECONDS,
    AuctionGame,
    parse_bid_amount,
    parse_room_command,
    parse_toggle_command,
)


def make_game(tmp_path, *, chosen=None, clock=None):
    memory = {"state": None}

    def load(_path, default):
        return copy.deepcopy(memory["state"] if memory["state"] is not None else default)

    def save(_path, data):
        memory["state"] = copy.deepcopy(data)

    chooser = (lambda items: chosen or items[0])
    game = AuctionGame(
        tmp_path / "auction.json", load, save, chooser=chooser,
        clock=clock or (lambda: 1_700_000_000),
    )
    return game, memory


def register_players(game, count=3):
    for number in range(1, count + 1):
        assert game.join(str(number), f"Player{number}")["ok"]


def test_command_parsing_and_master_toggle_aliases():
    assert parse_toggle_command("شغل لعبة مزاد") is True
    assert parse_toggle_command("اوقف لعبه مزاد") is False
    assert parse_room_command("ابي افتح لعبة مزاد") == "open"
    assert parse_room_command("مزايده") == "join"
    assert parse_room_command("ابدأ المزاد") == "start"
    assert parse_room_command("زايد") == "bid"
    assert parse_room_command("زايد 10m") == "bid"
    assert parse_room_command("bid 1.01b") == "bid"
    assert parse_bid_amount("زايد 10m") == 10_000_000
    assert parse_bid_amount("زايد 10b") == 10_000_000_000
    assert parse_bid_amount("bid 1.01b") == 1_010_000_000
    assert parse_bid_amount("زايد 1b10m") == 1_010_000_000
    assert parse_bid_amount("زايد 10m10b") == 10_010_000_000
    assert parse_bid_amount("زايد ١١٠،٠٠٠،٠٠٠") == 110_000_000
    assert parse_room_command("تمرير") == "pass"
    assert parse_room_command("اقفل المزاد") == "close"
    assert parse_room_command("حديث عادي") is None


def test_registration_early_start_and_automatic_start_at_five(tmp_path):
    game, _ = make_game(tmp_path)
    assert game.open_auction("host", "Host", "Hall")["error"] == "disabled"
    game.set_enabled(True)
    opened = game.open_auction("host", "Host", "Hall")
    assert opened["ok"]
    assert opened["auction"]["phase"] == "registration"

    assert game.start("host", "Host")["error"] == "not_enough_players"
    assert game.join("1", "Player1")["ok"]
    assert game.join("2", "Player2")["ok"]
    assert game.start("other", "Other")["error"] == "not_opener"
    assert game.join("3", "Player3")["ok"]
    started = game.start("host", "Host")
    assert started["ok"]
    assert started["auction"]["phase"] == "bidding"
    assert started["auction"]["current_bid"] == 0
    assert started["auction"]["turn_username"] == "Player1"
    assert started["auction"]["deadline_at"] - started["auction"]["started_at"] == BIDDING_DURATION_SECONDS

    game.cancel("host", "Host")
    game.open_auction("host", "Host", "Hall")
    for number in range(1, MAX_PARTICIPANTS + 1):
        result = game.join(str(number), f"Player{number}")
    assert result["auto_started"] is True
    assert result["auction"]["phase"] == "bidding"
    assert game.join("6", "Player6")["error"] == "registration_closed"


def test_bids_require_current_turn_and_explicit_amount_above_minimum(tmp_path):
    game, _ = make_game(tmp_path)
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")

    assert game.bid("outsider", "Outsider", 100_000_000, 1_000_000_000)["error"] == "not_participant"
    assert game.bid("2", "Player2", 200_000_000, 1_000_000_000)["error"] == "not_your_turn"
    assert game.bid("1", "Player1", 99_000_000, 1_000_000_000)["error"] == "bid_too_low"
    first = game.bid("1", "Player1", 100_000_000, 100_000_000)
    assert first["amount"] == AUCTION_ITEMS[0]["starting_price"] == 100_000_000
    assert first["next_turn_username"] == "Player2"
    assert game.bid("3", "Player3", 120_000_000, 1_000_000_000)["error"] == "not_your_turn"
    assert game.bid("2", "Player2", 109_999_999, 1_000_000_000)["error"] == "bid_too_low"
    second = game.bid("2", "Player2", 250_000_000, 250_000_000)
    assert second["amount"] == 250_000_000
    assert second["next_turn_username"] == "Player3"
    assert game.active()["highest_bidder_name"] == "Player2"
    assert game.active()["bid_count"] == 2
    assert game.bid("3", "Player3", 260_000_000, 259_999_999)["error"] == "insufficient"


def test_bid_arriving_after_seven_second_turn_deadline_is_rejected(tmp_path):
    now = {"value": 1_700_000_000.0}
    game, _ = make_game(tmp_path, clock=lambda: now["value"])
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")
    now["value"] += TURN_TIMEOUT_SECONDS

    result = game.bid("1", "Player1", 100_000_000, 1_000_000_000)
    assert result["error"] == "turn_expired"
    assert game.active()["bid_count"] == 0


def test_pass_moves_to_next_turn_and_all_passes_settle_the_high_bid(tmp_path):
    game, _ = make_game(tmp_path)
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")
    game.bid("1", "Player1", 100_000_000, 100_000_000)

    assert game.pass_turn("3", "Player3")["error"] == "not_your_turn"
    assert game.pass_turn("2", "Player2")["next_turn_username"] == "Player3"
    assert game.pass_turn("3", "Player3")["next_turn_username"] == "Player1"
    charges = []

    def charge(username, delta, txid, reason):
        charges.append((username, delta, txid, reason))
        return {"ok": True}

    closed = game.pass_turn("1", "Player1", apply_delta=charge)
    assert closed["status"] == "sold"
    assert closed["auto_closed"] is True
    assert closed["result"]["winner"] == "Player1"
    assert charges[0][1] == -100_000_000
    assert game.active() is None


def test_passing_every_turn_without_a_bid_closes_without_sale(tmp_path):
    game, _ = make_game(tmp_path)
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")
    game.pass_turn("1", "Player1")
    game.pass_turn("2", "Player2")
    result = game.pass_turn("3", "Player3")
    assert result["status"] == "no_bids"
    assert result["auto_closed"] is True
    assert game.active() is None


def test_every_collectible_has_a_distinct_starting_price_between_one_hundred_million_and_one_billion():
    prices = [item["starting_price"] for item in AUCTION_ITEMS]
    assert len(set(prices)) == len(AUCTION_ITEMS)
    assert min(prices) == 100_000_000
    assert max(prices) == 1_000_000_000
    assert all(100_000_000 <= price <= 1_000_000_000 for price in prices)


def test_first_bid_uses_the_selected_item_starting_price(tmp_path):
    chosen = AUCTION_ITEMS[-1]
    game, _ = make_game(tmp_path, chosen=chosen)
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")
    bid = game.bid("1", "Player1", 1_000_000_000, 1_000_000_000)
    assert bid["amount"] == chosen["starting_price"] == 1_000_000_000


def test_bidding_expires_after_sixty_seconds_and_rejects_late_bids(tmp_path):
    now = {"value": 1_700_000_000.25}
    game, _ = make_game(tmp_path, clock=lambda: now["value"])
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    started = game.start("host", "Host")["auction"]
    assert started["deadline_at"] == started["started_at"] + BIDDING_DURATION_SECONDS

    now["value"] += TURN_TIMEOUT_SECONDS - 0.01
    assert game.bid("1", "Player1", 100_000_000, 100_000_000)["ok"]
    now["value"] = float(started["deadline_at"])
    assert game.bid("2", "Player2", 110_000_000, 1_000_000_000)["error"] == "expired"


def test_timeout_automatically_settles_top_bid_only_in_participant_rooms(tmp_path, monkeypatch):
    now = {"value": 1_700_000_000.0}
    game, _ = make_game(tmp_path, clock=lambda: now["value"])
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    for name in ("Player1", "Player2", "Player3"):
        game.join(name.casefold(), name, room="Hall")
    started = game.start("host", "Host")["auction"]
    game.bid("player1", "Player1", 100_000_000, 100_000_000)

    timers = []

    class FakeTimer:
        def __init__(self, interval, function, args=(), kwargs=None):
            self.interval = float(interval)
            self.function = function
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = False
            self.cancelled = False
            timers.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(bot_module.threading, "Timer", FakeTimer)
    charges = []

    def apply_delta(username, delta, txid, reason):
        charges.append((username, delta, txid, reason))
        return {"ok": True}

    monkeypatch.setattr(bot_module, "_apply_points_delta_once", apply_delta)
    monkeypatch.setattr(bot_module, "_games_enabled_for_room", lambda _room: True)
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._auction_game = game
    bot.connected_rooms = {"Hall", "UnrelatedHall"}
    bot._auction_timeout_lock = bot_module.threading.RLock()
    bot._effective_room_language = lambda _room: "en"
    sent = []
    bot.send_room_text = lambda room, text: sent.append((room, text))

    assert bot._schedule_auction_timeout(started)
    timer = timers[-1]
    assert timer.interval == TURN_TIMEOUT_SECONDS
    now["value"] = started["deadline_at"]
    timer.function(*timer.args, **timer.kwargs)

    assert game.active() is None
    assert charges[0][0] == "Player1"
    assert charges[0][1] == -AUCTION_ITEMS[0]["starting_price"]
    assert len(sent) == 1 and sent[0][0] == "Hall"
    assert "60-second bidding window ended" in sent[0][1]


def test_player_turn_is_automatically_passed_after_seven_seconds(tmp_path, monkeypatch):
    now = {"value": 1_700_000_000.0}
    game, _ = make_game(tmp_path, clock=lambda: now["value"])
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    for name in ("Player1", "Player2", "Player3"):
        game.join(name.casefold(), name, room="Hall")
    started = game.start("host", "Host")["auction"]

    timers = []
    class FakeTimer:
        def __init__(self, interval, function, args=(), kwargs=None):
            self.interval = float(interval)
            self.function = function
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = False
            self.cancelled = False
            timers.append(self)
        def start(self):
            self.started = True
        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(bot_module.threading, "Timer", FakeTimer)
    monkeypatch.setattr(bot_module, "_games_enabled_for_room", lambda _room: True)
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._auction_game = game
    bot.connected_rooms = {"Hall"}
    bot._auction_timeout_lock = bot_module.threading.RLock()
    bot._effective_room_language = lambda _room: "en"
    sent = []
    bot.send_room_text = lambda room, text: sent.append((room, text))

    assert bot._schedule_auction_timeout(started)
    first_timer = timers[-1]
    assert first_timer.interval == TURN_TIMEOUT_SECONDS
    now["value"] += TURN_TIMEOUT_SECONDS
    first_timer.function(*first_timer.args, **first_timer.kwargs)

    active = game.active()
    assert active["turn_username"] == "Player2"
    assert "player1" in active["passed_since_bid"]
    assert any("passed automatically" in text for _room, text in sent)
    assert timers[-1].interval == TURN_TIMEOUT_SECONDS


def test_winner_is_charged_once_and_redemption_can_return_authentic_profit(tmp_path, monkeypatch):
    game, _ = make_game(tmp_path)
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")
    first = game.bid("1", "Player1", 100_000_000, 500_000_000)
    second = game.bid("2", "Player2", 110_000_000, 500_000_000)

    ledger = {}

    def apply_delta(username, delta, txid, reason):
        if txid not in ledger:
            ledger[txid] = (username, delta, reason)
        return {"ok": True, "already_applied": len(ledger) > 0}

    closed = game.close("host", "Host", apply_delta=apply_delta)
    assert closed["status"] == "sold"
    award = closed["result"]
    assert award["winner"] == "Player2"
    assert first["amount"] == AUCTION_ITEMS[0]["starting_price"]
    assert second["amount"] == first["amount"] + BID_INCREMENT
    assert award["bid"] == 110_000_000
    assert award["redemption_value"] == 110_000_000
    assert len(ledger) == 1
    assert next(iter(ledger.values()))[1] == -110_000_000

    inventory = game.inventory("2", "Player2")
    assert len(inventory) == 1
    assert inventory[0]["status"] == "available"
    monkeypatch.setattr("auction_game.random.random", lambda: 0.25)
    redeemed = game.redeem("2", "Player2", inventory[0]["id"][:8], apply_delta)
    assert redeemed["ok"]
    assert redeemed["authentic"] is True
    assert redeemed["points"] == 110_825_000
    assert len(ledger) == 2
    assert game.inventory("2", "Player2") == []
    assert game.redeem("2", "Player2", inventory[0]["id"][:8], apply_delta)["error"] == "item_not_found"


def test_counterfeit_redemption_takes_one_and_a_quarter_percent_and_keeps_outcome_on_retry(tmp_path, monkeypatch):
    game, _ = make_game(tmp_path)
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")
    game.bid("1", "Player1", 100_000_000, 100_000_000)
    ledger = {}
    closed = game.close("host", "Host", apply_delta=lambda *_args: {"ok": True})
    item_id = closed["result"]["auction_id"][:8]
    monkeypatch.setattr("auction_game.random.random", lambda: 0.75)

    attempts = []
    def fail_once(username, delta, txid, reason):
        attempts.append((username, delta, txid, reason))
        return {"ok": False, "error": "persistence_failed"}

    pending = game.redeem("1", "Player1", item_id, fail_once)
    assert pending["pending"] is True
    assert attempts[0][1] == 98_750_000
    monkeypatch.setattr("auction_game.random.random", lambda: 0.1)
    recovered = game.redeem("1", "Player1", item_id, lambda *_args: {"ok": True})
    assert recovered["ok"] is True
    assert recovered["authentic"] is False
    assert recovered["outcome"] == "counterfeit"
    assert recovered["points"] == 98_750_000


def test_pending_settlement_recovers_idempotently_after_temporary_ledger_failure(tmp_path):
    game, _ = make_game(tmp_path)
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")
    game.bid("1", "Player1", 100_000_000, 100_000_000)
    attempts = []

    def fail_once(username, delta, txid, reason):
        attempts.append((username, delta, txid, reason))
        return {"ok": False, "error": "persistence_failed"}

    pending = game.close("host", "Host", apply_delta=fail_once)
    assert pending["pending"]
    assert game.active()["phase"] == "settling"

    committed = {}

    def apply_once(username, delta, txid, reason):
        if txid not in committed:
            committed[txid] = (username, delta, reason)
        return {"ok": True, "already_applied": len(committed) > 0}

    recovered = game.recover_pending_settlement(apply_once)
    assert recovered["status"] == "sold"
    assert game.active() is None
    assert len(committed) == 1
    assert game.inventory("1", "Player1")


def test_disabling_cancels_an_unsettled_round_without_charging_anyone(tmp_path):
    game, _ = make_game(tmp_path)
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    register_players(game, 3)
    game.start("host", "Host")
    game.bid("1", "Player1", 100_000_000, 1_000_000_000)
    result = game.set_enabled(False)
    assert result["cancelled_active"]
    assert game.active() is None
    assert game.inventory("1", "Player1") == []


def test_all_auction_product_images_are_under_fifty_kilobytes():
    assets = Path(bot_module.ASSETS_DIR) / "treasures"
    assert AUCTION_ITEMS
    assert {item["key"] for item in AUCTION_ITEMS} >= {"jade_seal", "king_crown", "royal_scepter", "phoenix_amulet", "royal_chalice", "amber_orb"}
    for item in AUCTION_ITEMS:
        assert "diamond" not in item["key"]
        assert "diamond" not in item["name_en"].casefold()
        image = assets / item["image"]
        assert image.is_file(), item["image"]
        assert image.stat().st_size <= MAX_IMAGE_BYTES, (item["image"], image.stat().st_size)


def test_room_open_sends_localized_global_announcement_and_small_item_images(tmp_path, monkeypatch):
    game, _ = make_game(tmp_path, chosen=AUCTION_ITEMS[0])
    game.set_enabled(True)
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._auction_game = game
    bot.connected_rooms = {"ArabicHall", "EnglishHall"}
    bot._effective_room_language = lambda room: "en" if room == "EnglishHall" else "ar"
    bot._game_public_image = lambda path, route="assets/treasures": f"https://assets.example/{route}/{path.name}"
    bot.log = lambda *_args, **_kwargs: None
    sent_text = []
    sent_media = []
    bot.send_room_text = lambda room, text: sent_text.append((room, text))
    bot.send_room_media = lambda room, url, media_type: sent_media.append((room, url, media_type)) or True
    monkeypatch.setattr(bot_module, "_is_verified_user", lambda _name: True)
    monkeypatch.setattr(bot_module, "_games_enabled_for_room", lambda _room: True)
    monkeypatch.setattr(bot_module, "_is_primary_master", lambda _name: False)

    assert bot._handle_auction_room_command("EnglishHall", "Guest", "bid") is True
    assert len(sent_text) == 1 and sent_text[0][0] == "EnglishHall"
    assert "closed" in sent_text[0][1].casefold()
    sent_text.clear()
    assert bot._handle_auction_room_command("ArabicHall", "Host", "افتح مزاد")
    assert len(sent_text) == 4
    assert any(room == "ArabicHall" and "بدأ التسجيل" in text for room, text in sent_text)
    assert any(room == "EnglishHall" and "Registration is open" in text for room, text in sent_text)
    assert all("100m" in text for _room, text in sent_text if "بدأ التسجيل" in text or "Registration is open" in text)
    assert any("بالدور" in text and "110m أو 10b" in text for room, text in sent_text if room == "ArabicHall")
    assert any("bidding runs in turns" in text and "110m or 10b" in text for room, text in sent_text if room == "EnglishHall")
    assert any("قطعة المزاد:" in text and "قد لا تكون كل قطع المزاد أصلية؛ فاحذر أن تغامر بكل ثروتك" in text for room, text in sent_text if room == "ArabicHall")
    assert any("auction item:" in text.casefold() and "not every auction item may be authentic" in text.casefold() for room, text in sent_text if room == "EnglishHall")
    assert sorted(sent_media) == sorted([
        ("ArabicHall", "https://assets.example/assets/treasures/auction_imperial_jade.jpg", "image"),
        ("EnglishHall", "https://assets.example/assets/treasures/auction_imperial_jade.jpg", "image"),
    ])


def test_active_round_silently_ignores_out_of_turn_commands_and_accepts_amounts(tmp_path, monkeypatch):
    game, _ = make_game(tmp_path, chosen=AUCTION_ITEMS[0])
    game.set_enabled(True)
    game.open_auction("name:host", "Host", "ArabicHall")
    game.join("name:player1", "Player1", room="ArabicHall")
    game.join("name:player2", "Player2", room="EnglishHall")
    game.join("name:player3", "Player3", room="ArabicHall")
    game.start("name:host", "Host")

    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._auction_game = game
    bot.connected_rooms = {"ArabicHall", "EnglishHall", "OtherHall"}
    bot._effective_room_language = lambda room: "en" if room == "EnglishHall" else "ar"
    sent = []
    bot.send_room_text = lambda room, text: sent.append((room, text))
    monkeypatch.setattr(bot_module, "_is_verified_user", lambda name: name != "Guest")
    monkeypatch.setattr(bot_module, "_games_enabled_for_room", lambda _room: True)
    monkeypatch.setattr(bot_module, "_is_primary_master", lambda _name: False)
    monkeypatch.setattr(bot_module, "_get_points", lambda _name: 1_000_000_000)

    assert bot._handle_auction_room_command("EnglishHall", "Guest", "مزايده")
    assert len(sent) == 1 and sent[0][0] == "EnglishHall"
    assert "An auction is already running" in sent[0][1]

    sent.clear()
    assert bot._handle_auction_room_command("ArabicHall", "Guest", "زايد 200m")
    assert sent == []

    assert bot._handle_auction_room_command("EnglishHall", "Player2", "bid 200m")
    assert sent == []
    assert game.active()["bid_count"] == 0

    sent.clear()
    assert bot._handle_auction_room_command("ArabicHall", "Player1", "زايد 120m")
    assert sorted(room for room, _text in sent) == ["ArabicHall", "EnglishHall"]
    assert all("120m" in text for _room, text in sent)

    sent.clear()
    assert bot._handle_auction_room_command("ArabicHall", "Player1", "زايد 100m")
    assert sent == []
    assert game.active()["highest_bidder_name"] == "Player1"
    assert game.active()["current_bid"] == 120_000_000
    assert game.active()["turn_username"] == "Player2"

    sent.clear()
    assert bot._handle_auction_room_command("ArabicHall", "Player1", "زايد 1b")
    assert sent == []
    assert game.active()["bid_count"] == 1

    assert bot._handle_auction_room_command("EnglishHall", "Player2", "bid 250m")
    assert game.active()["highest_bidder_name"] == "Player2"
    assert game.active()["current_bid"] == 250_000_000
    assert game.active()["turn_username"] == "Player3"

    sent.clear()
    assert bot._handle_auction_room_command("OtherHall", "Player1", "bid")
    assert len(sent) == 1 and sent[0][0] == "OtherHall"
    assert "المزاد مغلق في هذه الغرفة" in sent[0][1]
    assert game.active()["bid_count"] == 2


def test_closed_auction_replies_in_nonparticipant_room_without_global_broadcast(tmp_path, monkeypatch):
    game, _ = make_game(tmp_path)
    game.set_enabled(True)
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._auction_game = game
    bot.connected_rooms = {"ParticipantHall", "OtherHall"}
    bot._effective_room_language = lambda _room: "ar"
    sent = []
    bot.send_room_text = lambda room, text: sent.append((room, text))
    monkeypatch.setattr(bot_module, "_is_primary_master", lambda _name: False)

    assert bot._handle_auction_room_command("OtherHall", "Guest", "مزايده")
    assert bot._handle_auction_room_command("OtherHall", "Guest", "زايد")
    assert len(sent) == 2
    assert all(room == "OtherHall" for room, _text in sent)
    assert all("المزاد مغلق" in text and "انتظر" in text for _room, text in sent)


def test_auction_collectible_appears_in_sv_and_redeems_through_red_auction(tmp_path, monkeypatch):
    game, _ = make_game(tmp_path, chosen=AUCTION_ITEMS[0])
    game.set_enabled(True)
    game.open_auction("host", "Host", "Hall")
    for name in ("Player1", "Player2", "Player3"):
        assert game.join("name:" + name.casefold(), name)["ok"]
    game.start("host", "Host")
    game.bid("name:player1", "Player1", AUCTION_ITEMS[0]["starting_price"], AUCTION_ITEMS[0]["starting_price"])
    ledger = {}

    def apply_delta(username, delta, txid, reason):
        ledger[txid] = (username, delta, reason)
        return {"ok": True}

    closed = game.close("host", "Host", apply_delta=apply_delta)
    assert closed["status"] == "sold"

    class EmptyMiningStore:
        def inventory(self, _user_id, username):
            return {"username": username, "inventory": {}, "diamonds_found": 0}

    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._auction_game = game
    bot._resume_pending_mining_redemption = lambda *_args: None
    language = {"value": "ar"}
    bot._effective_room_language = lambda _room: language["value"]
    sent = []
    bot.send_room_text = lambda room, text: sent.append((room, text))
    monkeypatch.setattr(bot_module, "MINING_STORE", EmptyMiningStore())
    monkeypatch.setattr(bot_module, "_apply_points_delta_once", apply_delta)
    monkeypatch.setattr("auction_game.random.random", lambda: 0.25)

    assert bot._execute_mining_command_with_id("Hall", "sv", "Player1", "name:player1")
    assert any("مقتنيات المزاد العالمي" in text and "red auction" in text for _room, text in sent)
    language["value"] = "en"
    sent.clear()
    assert bot._execute_mining_command_with_id("Hall", "sv", "Player1", "name:player1")
    assert any("World auction collectibles" in text and "Imperial Jade Seal" in text for _room, text in sent)
    english_inventory = sent[-1][1]
    assert not any("\u0600" <= character <= "\u06ff" for character in english_inventory)
    assert bot._execute_mining_command_with_id("Hall", f"red auction {closed['result']['auction_id'][:8]}", "Player1", "name:player1")
    assert any("authentic (+0.75% profit)" in text and "100,750,000" in text for _room, text in sent)
    assert ledger[f"auction-redemption:{closed['result']['auction_id']}"][1] == 100_750_000


def test_only_primary_master_can_toggle_auction_and_off_cancels_open_round(tmp_path, monkeypatch):
    game, _ = make_game(tmp_path)
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._auction_game = game
    bot.connected_rooms = set()
    notices = []
    bot.send_private_text = lambda user, text: notices.append((user, text))
    bot._effective_room_language = lambda _room: "ar"
    bot.send_room_text = lambda *_args: None
    monkeypatch.setattr(bot_module, "_is_primary_master", lambda name: name == "Master")

    assert bot._handle_auction_private_command("Other", "شغل لعبة مزاد")
    assert not game.enabled()
    assert "مخصص" in notices[-1][1]

    assert bot._handle_auction_private_command("Master", "شغل لعبة مزاد")
    assert game.enabled()
    game.open_auction("name:master", "Master", "Hall")
    assert bot._handle_auction_private_command("Master", "اوقف لعبة مزاد")
    assert not game.enabled()
    assert game.active() is None
    assert "إيقاف" in notices[-1][1]


def test_auction_help_is_localized_for_english_rooms():
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._effective_room_language = lambda _room: "en"
    help_text = bot_module._default_help_sections()[3][3]
    localized = bot._localize_room_text("EnglishHall", help_text)
    auction_section = localized.split("🔨", 1)[1]
    assert "World auction" in auction_section
    assert "Open auction" in auction_section
    assert "Join auction" in auction_section
    assert "50/50 chance" in auction_section
    assert "1.25% loss" in auction_section
    assert "up to 60 seconds" in auction_section and "7 seconds" in auction_section
    assert "bid <amount>" in auction_section
    assert "10m (10 million)" in auction_section
    assert "10b or 1b (billions)" in auction_section
    assert "ignored silently" in auction_section
    assert not any("\u0600" <= character <= "\u06ff" for character in auction_section)
