import shop
import bot as bot_module


def test_temporary_protection_is_scoped_and_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "SHOP_PATH", tmp_path / "shop.json")
    now = [1_000.0]
    monkeypatch.setattr(shop.time, "time", lambda: now[0])

    ok, error = shop.purchase("Player", 1)
    assert ok and not error
    assert shop.active("user_bomb", username="Player")
    assert not shop.active("user_bomb", username="Other")
    duplicate, message = shop.purchase("Player", 1)
    assert not duplicate and "فعال" in message

    ok, error = shop.purchase("Player", 2, "Room A")
    assert ok and not error
    assert shop.active("room_bomb", room="Room A")
    assert not shop.active("room_bomb", room="Room B")

    now[0] += 3_601
    assert not shop.active("user_bomb", username="Player")
    assert not shop.active("room_bomb", room="Room A")


def test_welcome_perks_are_persistent_unlocks(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "SHOP_PATH", tmp_path / "shop.json")
    ok, error = shop.purchase("Player", 5)
    assert ok and not error
    assert shop.active("custom_welcome", username="Player")
    assert not shop.active("image_welcome", username="Player")
    ok, error = shop.purchase("Player", 5)
    assert not ok and "بالفعل" in error
    ok, error = shop.purchase("Player", 6)
    assert ok and not error
    assert shop.active("image_welcome", username="Player")


def test_shop_catalog_fits_talkin_message_limit():
    text = shop.render_catalog()
    packet = bot_module.encode_query("chat_message", type_="text", to="Player", body=text)
    assert len(packet) <= 1008
    assert "sby 1 إلى sby 6" in text
    assert "ترحيب_صورة" in text


def test_every_shop_item_can_be_activated_in_isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "SHOP_PATH", tmp_path / "shop.json")
    for item_id, item in shop.ITEMS.items():
        ok, error = shop.purchase("Tester", item_id, "Test Room")
        assert ok and not error, (item_id, error)
        if item["kind"].startswith("room_"):
            assert shop.active(item["kind"], room="Test Room")
        else:
            assert shop.active(item["kind"], username="Tester")


def test_regular_member_can_buy_and_activate_all_items_via_sby(tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr(shop, "SHOP_PATH", tmp_path / "shop.json")
    monkeypatch.setattr(bot_module, "_resolve_points_account", lambda *_args: ("tester", {}))
    monkeypatch.setattr(bot_module, "_points_balance", lambda _account: 10**12)
    monkeypatch.setattr(bot_module, "_add_points", lambda *_args: True)
    monkeypatch.setattr(bot_module, "_github_sync_after_local_save", lambda *_args: None)

    bot = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    bot._room_list_commands = lambda *_args, **_kwargs: False
    bot._pending_named_commands = {}
    bot._pending_protection_number = {}
    bot._master_reply_local = threading.local()
    bot._remember_bot_action = lambda *_args, **_kwargs: None
    bot.send_private_text = lambda *_args, **_kwargs: True

    for item_id, item in shop.ITEMS.items():
        assert bot._handle_management_command(
            "Test Room", f"sby {item_id}", "RegularMember", is_private=False
        )
        if item["kind"].startswith("room_"):
            assert shop.active(item["kind"], room="Test Room")
        else:
            assert shop.active(item["kind"], username="RegularMember")
