import bot as bot_module


def test_runtime_resource_status_uses_container_limits_when_available(monkeypatch):
    monkeypatch.setattr(
        bot_module,
        "_read_cgroup_memory_limit_usage",
        lambda: (4 * 1024**3, 3 * 1024**3),
    )
    monkeypatch.setattr(bot_module, "_read_cgroup_cpu_limits", lambda: (2.5, 4))
    monkeypatch.setattr(bot_module.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(bot_module.os, "getloadavg", lambda: (8.0, 6.0, 4.0))

    metrics = bot_module._runtime_resource_status()

    assert metrics["ram_scope"] == "container"
    assert metrics["ram_total_mb"] == 4096
    assert metrics["ram_used_mb"] == 3072
    assert metrics["ram_available_mb"] == 1024
    assert metrics["ram_used_pct"] == 75
    assert metrics["cpu_scope"] == "container"
    assert metrics["cpu_count"] == 2.5
    # Load averages are host-wide, so their normalization uses host CPU count.
    assert metrics["load_pct_per_core"] == 50


def test_runtime_resource_status_labels_host_fallback_when_cgroup_limit_missing(monkeypatch):
    monkeypatch.setattr(bot_module, "_read_cgroup_memory_limit_usage", lambda: (None, None))
    monkeypatch.setattr(bot_module, "_read_host_memory_kb", lambda: (8 * 1024 * 1024, 6 * 1024 * 1024))
    monkeypatch.setattr(bot_module, "_read_cgroup_cpu_limits", lambda: (None, None))
    monkeypatch.setattr(bot_module.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(bot_module.os, "getloadavg", lambda: (2.0, 1.0, 0.5))

    metrics = bot_module._runtime_resource_status()

    assert metrics["ram_scope"] == "host"
    assert metrics["ram_total_mb"] == 8192
    assert metrics["ram_used_mb"] == 2048
    assert metrics["ram_available_mb"] == 6144
    assert metrics["cpu_scope"] == "host"
    assert metrics["cpu_count"] == 4


def test_cgroup_readers_use_tightest_ancestor_limit(tmp_path, monkeypatch):
    leaf = tmp_path / "container" / "bot"
    parent = tmp_path / "container"
    root = tmp_path
    for directory in (leaf, parent, root):
        directory.mkdir(parents=True, exist_ok=True)

    (leaf / "memory.max").write_text("max")
    (leaf / "memory.current").write_text(str(1 * 1024**3))
    (parent / "memory.max").write_text(str(3 * 1024**3))
    (parent / "memory.current").write_text(str(2 * 1024**3))
    (root / "memory.max").write_text(str(8 * 1024**3))
    (root / "memory.current").write_text(str(5 * 1024**3))

    (leaf / "cpu.max").write_text("max 100000")
    (parent / "cpu.max").write_text("200000 100000")
    (root / "cpu.max").write_text("800000 100000")
    (leaf / "cpuset.cpus.effective").write_text("0-3")

    monkeypatch.setattr(
        bot_module,
        "_cgroup_candidate_dirs",
        lambda controller: [leaf, parent, root] if controller == "unified" else [],
    )

    assert bot_module._read_cgroup_memory_limit_usage() == (3 * 1024**3, 2 * 1024**3)
    assert bot_module._read_cgroup_cpu_limits() == (2.0, 4)


def test_parse_cgroup_cpu_set_supports_ranges_and_single_cores():
    assert bot_module._parse_cgroup_cpu_set("0-2,4,6-7") == 6
    assert bot_module._parse_cgroup_cpu_set("") is None
    assert bot_module._parse_cgroup_cpu_set("bad-range") is None
