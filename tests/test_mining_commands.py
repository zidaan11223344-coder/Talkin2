import copy
from pathlib import Path

import bot as bot_module
from treasure_mining import MiningStore


def test_mining_commands_use_stable_id_and_redeem_inventory_idempotently(tmp_path, monkeypatch):
    state = {"version": 1, "players": {}}
    store = MiningStore(
        tmp_path / "mining_game.json",
        load_json=lambda _path, default: copy.deepcopy(state if state["players"] else default),
        save_json=lambda _path, data: state.update(copy.deepcopy(data)),
        chooser=lambda: "diamond_blue",
        clock=lambda: 1_000.0,
    )
    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    sent = []
    media = []
    transactions = []
    bot.send_room_text = lambda room, text: sent.append((room, text))
    bot.send_room_media = lambda room, url, media_type: media.append((room, url, media_type))
    bot._game_public_image = lambda path, route="games": f"https://assets.example/{route}/{path.name}"
    bot.log = lambda *args, **kwargs: None

    monkeypatch.setattr(bot_module, "MINING_STORE", store)
    monkeypatch.setattr(bot_module, "_record_game", lambda *args: None)
    monkeypatch.setattr(
        bot_module,
        "_apply_points_delta_once",
        lambda username, points, txid, reason: (
            transactions.append((username, points, txid, reason)) or {"ok": True}
        ),
    )
    monkeypatch.setattr(bot_module.time, "sleep", lambda _seconds: None)

    assert bot._execute_mining_command_with_id("Hall", "الماس", "Ahmed", "3456782")
    assert state["players"]["3456782"]["inventory"]["diamond_blue"] == 1
    assert any("@Ahmed" in text and "ID:" not in text for _room, text in sent)
    assert media == [("Hall", "https://assets.example/assets/treasures/diamond_blue.jpg", "image")]

    sent.clear()
    assert bot._execute_mining_command_with_id("Hall", "sv", "NewName", "3456782")
    assert any("الألماس الأزرق: 1" in text for _room, text in sent)

    sent.clear()
    assert bot._execute_mining_command_with_id("Hall", "توب الالماس", "NewName", "3456782")
    assert any("@NewName — 1 ألماسة" in text for _room, text in sent)

    sent.clear()
    assert bot._execute_mining_command_with_id("Hall", "Rdem الماس", "NewName", "3456782")
    assert len(transactions) == 1
    assert transactions[0][0] == "NewName"
    assert transactions[0][1] == 1_000_000
    assert transactions[0][3] == "treasure mining redemption"
    assert transactions[0][2].startswith("mining-redemption:")
    assert state["players"]["3456782"]["inventory"]["diamond_blue"] == 0
    assert state["players"]["3456782"].get("pending_redemption") is None
    assert any("1,000,000 نقطة" in text for _room, text in sent)

    # R is the short alias for any item and must redeem copper through the
    # same points ledger, without touching another user's inventory.
    state["players"]["3456782"]["inventory"]["copper"] = 1
    store._save_state(state)
    sent.clear()
    assert bot._execute_mining_command_with_id("Hall", "R نحاس", "NewName", "3456782")
    assert transactions[1][1] == 25_000
    assert transactions[1][3] == "treasure mining redemption"
    assert state["players"]["3456782"]["inventory"]["copper"] == 0
    assert any("25,000 نقطة" in text for _room, text in sent)

    sent.clear()
    assert bot._execute_mining_command_with_id("Hall", "متجر الكنوز", "NewName", "3456782")
    catalog = sent[-1][1]
    packet = bot_module.encode_query("room_message", room="Hall", body=catalog)
    assert len(packet) <= 1008


def test_compressed_treasure_asset_is_served_as_jpeg():
    handler = bot_module._MediaHandler.__new__(bot_module._MediaHandler)
    compressed_jpeg = Path(bot_module.ASSETS_DIR) / "treasures" / "diamond_clear.jpg"
    assert compressed_jpeg.is_file()
    assert handler._ctype(compressed_jpeg) == "image/jpeg"


def test_media_type_uses_image_signature_when_extension_is_wrong(tmp_path):
    handler = bot_module._MediaHandler.__new__(bot_module._MediaHandler)
    mislabeled = tmp_path / "image.jpg"
    mislabeled.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    assert handler._ctype(mislabeled) == "image/png"
