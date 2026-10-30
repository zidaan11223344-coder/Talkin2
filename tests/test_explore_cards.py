from pathlib import Path

import bot as bot_module


def _bare_bot():
    instance = bot_module.TalkinBot.__new__(bot_module.TalkinBot)
    instance.reaction_targets = {}
    instance.user_photos = {}
    return instance


def test_explore_emoji_clusters_keep_modifiers_zwj_and_flags():
    text = "😀👨‍👩‍👧‍👦👍🏽🇸🇦"
    clusters = []
    index = 0
    while index < len(text):
        end = bot_module._explore_emoji_cluster_end(text, index)
        if end > index:
            clusters.append(text[index:end])
            index = end
        else:
            index += 1
    assert clusters == ["😀", "👨‍👩‍👧‍👦", "👍🏽", "🇸🇦"]


def test_explore_card_renders_compound_emoji_sequences(tmp_path, monkeypatch):
    if not bot_module.PIL_AVAILABLE:
        return
    rendered = []
    monkeypatch.setattr(
        bot_module, "_draw_color_emoji",
        lambda _draw, _xy, token, size: rendered.append(token) or size,
    )
    monkeypatch.setattr(bot_module, "BASE_DIR", Path(tmp_path))
    card = bot_module.render_explore_card(
        "😀😃😄😁😆😅😂🤣☺ 👨‍👩‍👧‍👦 👍🏽 🇸🇦", "مستخدم", ""
    )
    try:
        assert card.is_file()
        with bot_module.Image.open(card) as image:
            assert image.size == (1080, 1500)
            assert image.format == "JPEG"
        assert set("😀😃😄😁😆😅😂🤣☺").issubset(set(rendered))
        assert "👨‍👩‍👧‍👦" in rendered
        assert "👍🏽" in rendered
        assert "🇸🇦" in rendered
    finally:
        card.unlink(missing_ok=True)


def test_ax_publishes_card_and_saves_reaction_target(monkeypatch, tmp_path):
    instance = _bare_bot()
    room_messages = []
    media_messages = []
    private_messages = []
    render_calls = []
    instance._find_publish_filter_hit = lambda _text: False
    instance._lookup_profile_photo = lambda _sender: ""
    instance._active_rooms = lambda: ["غرفة"]
    instance._verify_public_media_url = lambda *_args: True
    instance.send_room_text = lambda room, text: room_messages.append((room, text)) or True
    instance.send_room_media = lambda room, url, kind: media_messages.append((room, url, kind)) or True
    instance.send_private_text = lambda user, text: private_messages.append((user, text)) or True
    monkeypatch.setattr(
        bot_module, "render_explore_card",
        lambda *args: render_calls.append(args) or tmp_path / "card.jpg",
    )
    monkeypatch.setattr(bot_module, "_public_base_url", lambda: "https://media.example")

    assert instance._handle_explore_command("غرفة", "ax@نص مع 😀", "ناشر")
    assert render_calls[0][0] == "نص مع 😀"
    assert media_messages == [("غرفة", "https://media.example/publish/card.jpg", "image")]
    assert len(room_messages) == 1
    assert "نص مع 😀" not in room_messages[0][1]
    assert "lk@" in room_messages[0][1] and "x@" in room_messages[0][1]
    target = next(iter(instance.reaction_targets.values()))
    assert target["kind"] == "explore" and target["description"] == "نص مع 😀"
    assert private_messages and "تم نشر اكسبلور" in private_messages[0][1]


def test_x_reposts_explore_image_and_names_reposter():
    instance = _bare_bot()
    room_messages = []
    media_messages = []
    instance.send_room_text = lambda room, text: room_messages.append((room, text)) or True
    instance.send_room_media = lambda room, url, kind: media_messages.append((room, url, kind)) or True
    instance.reaction_targets["e5f6"] = {
        "kind": "explore", "media_url": "https://media.example/explore.jpg",
        "caption": "✨ اكسبلور\n👤 @author\n🔁 x@e5f6 — إعادة نشر",
        "created_at": bot_module.time.time(),
    }

    assert instance._handle_explore_repost_command("غرفة", "x@e5f6", "مُعيد")
    assert media_messages == [("غرفة", "https://media.example/explore.jpg", "image")]
    assert "أعاد النشر: @مُعيد" in room_messages[0][1]


def test_long_arabic_messages_are_split_into_safe_websocket_packets(monkeypatch):
    instance = _bare_bot()
    packets = []
    instance._report_oversize_delivery = lambda *_args: None
    instance._send_long_text_to_telegram = lambda *_args, **_kwargs: True
    instance._send_oversize_notice = lambda *_args, **_kwargs: True
    instance.send_private_text = lambda *_args, **_kwargs: True
    instance.send_query = lambda payload: packets.append(payload) or True
    monkeypatch.setattr(bot_module, "BOT_MASTER", "master")

    original = "ط" * 700
    assert instance._send_text_packets("room_message", original, room="غرفة") is True
    assert len(packets) > 1
    assert all(len(packet) <= 1008 for packet in packets)
    chunks = [bot_module.as_text(bot_module.decode_message(packet)[5][0]) for packet in packets]
    assert "".join(chunks) == original
