import json
import threading

from treasure_mining import COOLDOWN_SECONDS, DIAMOND_KEYS, ITEMS, MiningStore, resolve_item_keys


def build_store(path, outcomes):
    queue = list(outcomes)

    def choose():
        return queue.pop(0) if queue else None

    return MiningStore(path, chooser=choose)


def test_dig_is_keyed_by_numeric_user_id_and_cooldown_persists(tmp_path):
    path = tmp_path / "mining_game.json"
    store = build_store(path, ["diamond_blue", None])

    first = store.dig("3456782", "Ahmed", now=10_000)
    assert first["ok"] is True
    assert first["item_key"] == "diamond_blue"
    assert first["diamonds_found"] == 1
    assert store.inventory("3456782")["inventory"]["diamond_blue"] == 1

    # A changed display name still resolves to the same numeric-ID record.
    blocked = store.dig("3456782", "أحمد الجديد", now=10_000 + 3600)
    assert blocked["error"] == "cooldown"
    assert blocked["remaining"] == 3600
    assert store.inventory("3456782")["username"] == "Ahmed"

    # The next attempt is accepted exactly when the two-hour boundary is met.
    second = store.dig("3456782", "أحمد الجديد", now=10_000 + COOLDOWN_SECONDS)
    assert second["ok"] is True
    assert second["item_key"] is None
    assert store.inventory("3456782")["username"] == "أحمد الجديد"
    assert store.inventory("3456782")["diamonds_found"] == 1


def test_distinct_numeric_ids_never_share_inventory_even_with_same_name(tmp_path):
    store = build_store(tmp_path / "mining_game.json", ["copper", "iron"])
    store.dig("10001", "SameName", now=20_000)
    store.dig("10002", "SameName", now=20_000)

    first = store.inventory("10001")["inventory"]
    second = store.inventory("10002")["inventory"]
    assert first["copper"] == 1 and first["iron"] == 0
    assert second["iron"] == 1 and second["copper"] == 0


def test_two_concurrent_attempts_commit_only_one_mine(tmp_path):
    store = build_store(tmp_path / "mining_game.json", ["ruby"])
    barrier = threading.Barrier(3)
    results = []

    def run():
        barrier.wait()
        results.append(store.dig("2222", "Player", now=30_000))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert sum(bool(result.get("ok")) for result in results) == 1
    assert sum(result.get("error") == "cooldown" for result in results) == 1
    assert store.inventory("2222")["inventory"]["ruby"] == 1


def test_redemption_reservation_is_persisted_before_credit_and_restorable(tmp_path):
    path = tmp_path / "mining_game.json"
    store = build_store(path, ["copper", "diamond_royal"])
    store.dig("300", "Miner", now=40_000)
    store.dig("300", "Miner", now=40_000 + COOLDOWN_SECONDS)

    reserved = store.reserve_redemption("300", "Miner", DIAMOND_KEYS)
    assert reserved["ok"] is True
    assert reserved["pending"]["items"] == {"diamond_royal": 1}
    assert reserved["pending"]["points"] == ITEMS["diamond_royal"]["price"]
    assert store.inventory("300")["inventory"]["diamond_royal"] == 0

    # A restart still sees the pending transaction and will reuse its ID with
    # the idempotent points ledger rather than reserving/crediting it again.
    restarted = MiningStore(path)
    pending = restarted.pending_redemption("300")
    assert pending["id"] == reserved["pending"]["id"]
    assert restarted.complete_redemption("300", pending["id"]) is True
    assert restarted.pending_redemption("300") is None
    assert restarted.complete_redemption("300", pending["id"]) is False


def test_inventory_persistence_and_diamond_leaderboard(tmp_path):
    path = tmp_path / "mining_game.json"
    store = build_store(path, ["diamond_clear", "diamond_blue", "iron"])
    store.dig("9", "First", now=50_000)
    store.dig("9", "First", now=50_000 + COOLDOWN_SECONDS)
    store.dig("12", "Second", now=50_000)

    restarted = MiningStore(path)
    assert restarted.inventory("9")["diamonds_found"] == 2
    assert restarted.leaderboard(10)[0]["user_id"] == "9"
    assert restarted.leaderboard(10)[0]["diamonds_found"] == 2


def test_item_aliases_cover_redeem_commands():
    assert resolve_item_keys("الماس") == DIAMOND_KEYS
    assert resolve_item_keys("R نحاس") is None
    assert resolve_item_keys("الماس الأزرق") == ("diamond_blue",)
    assert resolve_item_keys("royal diamond") == ("diamond_royal",)


def test_outcome_distribution_is_complete_and_normalized():
    from treasure_mining import OUTCOME_KEYS, OUTCOME_WEIGHTS

    assert sum(OUTCOME_WEIGHTS) == 10_000
    assert len(OUTCOME_KEYS) == len(OUTCOME_WEIGHTS)
    assert len(DIAMOND_KEYS) == 6
