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
