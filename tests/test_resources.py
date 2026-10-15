import json
import subprocess

import pytest

from hai_proof.resources import GB, ResourceError, ResourceGate, _meminfo, local_memory, parse_mem, self_rss


def cp(out="", rc=0):
    return subprocess.CompletedProcess([], rc, out.encode(), b"")


class FakeEx:
    def __init__(self, host_avail_gb, containers=(), networks=("tp-r1-a-net", "bridge")):
        self.host = list(host_avail_gb)  # successive MemAvailable readings
        self.containers = list(containers)
        self.networks = list(networks)
        self.removed = []

    def host_shell(self, command, *, timeout=None, check=True):
        avail = self.host.pop(0) if len(self.host) > 1 else self.host[0]
        return cp(f"MemTotal:       {64 * 1024 * 1024} kB\nMemAvailable:   {int(avail * 1024 * 1024)} kB\n")

    def docker(self, args, *, input=None, timeout=None, check=True):
        if args[0] == "ps":
            return cp("\n".join(self.containers))
        if args[:2] == ["network", "ls"]:
            return cp("\n".join(self.networks))
        return cp()

    def remove(self, name):
        self.removed.append(name)
        self.containers.remove(name)


def gate(ex, tmp_path, *, local=(30 * GB, 64 * GB), rss=(100,), **kw):
    rss = list(rss)
    logs = []
    g = ResourceGate(ex, "R1", tmp_path, need_host=18 * GB, log=logs.append, sleep=lambda s: None,
                     local_mem=lambda: local, rss=lambda: rss.pop(0) if len(rss) > 1 else rss[0], **kw)
    return g, logs


def test_parse_mem_and_meminfo():
    assert parse_mem("8g") == 8 * GB and parse_mem("512m") == 512 * 1024**2 and parse_mem("1024") == 1024
    with pytest.raises(ValueError):
        parse_mem("lots")
    assert _meminfo("MemTotal: 2048 kB\nMemAvailable: 1024 kB\n") == (1024 * 1024, 2048 * 1024)
    assert _meminfo("nothing") is None


def test_real_machine_readers():
    lm = local_memory()
    assert lm is None or 0 < lm[0] <= lm[1]
    r = self_rss()
    assert r is None or r > 0


def test_clean_pass_records_snapshot(tmp_path):
    ex = FakeEx([40], containers=["tp-r1-a-proxy", "tp-r1-b-proxy"])
    g, logs = gate(ex, tmp_path)
    s = g.check("B5 rep 0")
    assert s.run_containers == [] and s.other_containers == [] and s.waited_s == 0
    assert s.networks == ["tp-r1-a-net"] and s.host_avail == 40 * GB
    rec = json.loads((tmp_path / "resources.jsonl").read_text().splitlines()[0])
    assert rec["where"] == "B5 rep 0" and rec["local_avail"] == 30 * GB
    assert logs == []


def test_leaks_removed_and_other_runs_warned(tmp_path):
    ex = FakeEx([40], containers=["tp-r1-a-proxy", "tp-r1-b-b7-rep1-abc123", "tp-old-a-b9-rep0-ffffff"])
    g, logs = gate(ex, tmp_path)
    s = g.check("B9 rep 1")
    assert ex.removed == ["tp-r1-b-b7-rep1-abc123"] and s.removed == ["tp-r1-b-b7-rep1-abc123"]
    assert s.other_containers == ["tp-old-a-b9-rep0-ffffff"]  # warned about, never removed
    assert any("leaked trial containers" in m for m in logs) and any("other runs" in m for m in logs)


def test_waits_for_host_memory_then_continues(tmp_path):
    ex = FakeEx([10, 12, 25])
    g, logs = gate(ex, tmp_path, poll_s=30)
    s = g.check("F5 rep 2")
    assert s.waited_s == 60 and s.host_avail == 25 * GB
    assert sum("waiting before F5 rep 2" in m for m in logs) == 2


def test_stops_when_memory_stays_short(tmp_path):
    g, _ = gate(FakeEx([40]), tmp_path, local=(1 * GB, 64 * GB), wait_s=90, poll_s=30)
    with pytest.raises(ResourceError, match="controller machine 1.0 GB free"):
        g.check("B7 rep 0")
    rec = json.loads((tmp_path / "resources.jsonl").read_text().splitlines()[-1])
    assert rec["waited_s"] == 90


def test_controller_growth_warning_and_missing_host_meminfo(tmp_path):
    class NoShell(FakeEx):
        def host_shell(self, command, *, timeout=None, check=True):
            raise NotImplementedError

    g, logs = gate(NoShell([0]), tmp_path, rss=(100 * 1024**2, 1300 * 1024**2))
    g.check("a")
    s = g.check("b")
    assert s.host_avail is None  # not gated, logged once
    assert sum("host memory unavailable" in m for m in logs) == 1
    assert any("controller memory grew" in m for m in logs)
