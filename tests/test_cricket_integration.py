from pathlib import Path

from cricket_integration import CricketIntegration


def test_master_toggle_and_player_count_are_persistent(tmp_path: Path):
    messages = []
    writes = []

    def save(path, value):
        writes.append((Path(path).name, value.get("enabled")))

    integration = CricketIntegration(
        tmp_path,
        persist=save,
        is_master=lambda username: username.casefold() == "master",
        send_room_text=lambda room, text: messages.append((room, text)),
        send_room_media=lambda *_args: None,
        public_base=lambda: "https://bot.example",
    )

    assert integration.handle("Room A", "master", "تشغيل الكركت") is True
    assert integration.game.current()["stage"] == "setup"
    assert integration.handle("Room A", "master", "٢") is True
    assert integration.game.current()["stage"] == "lobby"
    assert writes

    restarted = CricketIntegration(
        tmp_path,
        persist=save,
        is_master=lambda username: username.casefold() == "master",
        send_room_text=lambda room, text: messages.append((room, text)),
        send_room_media=lambda *_args: None,
        public_base=lambda: "https://bot.example",
    )
    assert restarted.game.enabled("Room A") is True
    assert restarted.game.current()["target_players"] == 2


def test_any_player_can_toggle_cricket(tmp_path: Path):
    messages = []
    integration = CricketIntegration(
        tmp_path,
        is_master=lambda username: username == "master",
        send_room_text=lambda room, text: messages.append((room, text)),
        send_room_media=lambda *_args: None,
        public_base=lambda: "https://bot.example",
    )

    assert integration.handle("Room A", "player", ".cr 1") is True
    assert integration.game.enabled("Room A") is True
    assert integration.game.current()["stage"] == "setup"
    assert integration.handle("Room A", "player", ".ct 0") is True
    assert integration.game.enabled("Room A") is False
