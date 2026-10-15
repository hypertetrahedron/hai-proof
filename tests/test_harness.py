import subprocess

from hai_proof import __version__
from hai_proof.claudedata import cache_misses
from hai_proof.harness import code_hash, harness_info


def req(read, write):
    return {"usage": {"cache_read": read, "cache_write": write}}


def test_cache_misses():
    assert cache_misses([]) == 0
    # warm cache: each request re-reads the previous prefix
    assert cache_misses([req(0, 10_000), req(10_000, 500), req(10_500, 800)]) == 0
    # a cold re-read after a long tool call, then warm again
    assert cache_misses([req(0, 10_000), req(10_000, 500), req(0, 11_000), req(11_000, 300)]) == 1
    # a partial re-read below half of the prefix counts; above half does not
    assert cache_misses([req(0, 10_000), req(4_000, 6_500)]) == 1
    assert cache_misses([req(0, 10_000), req(6_000, 4_500)]) == 0


def test_code_hash_tracks_image_files(tmp_path):
    (tmp_path / "image" / "base").mkdir(parents=True)
    f = tmp_path / "image" / "base" / "hai_proof_grade.py"
    f.write_text("x = 1\n")
    h = code_hash(tmp_path)
    assert h == code_hash(tmp_path) and len(h) == 12
    f.write_bytes(b"x = 1\r\n")  # line endings alone don't change it
    assert code_hash(tmp_path) == h
    f.write_text("x = 2\n")
    assert code_hash(tmp_path) != h


def test_harness_info_without_git(tmp_path):
    info = harness_info(tmp_path)
    assert info["version"] == __version__ and len(info["code_hash"]) == 12
    assert info["git_commit"] is None and info["git_dirty"] is None


def test_harness_info_with_git(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    git("init", "-q")
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "f").write_text("a")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    info = harness_info(tmp_path)
    assert info["git_commit"] and info["git_dirty"] is False
    (tmp_path / "image" / "f").write_text("b")
    assert harness_info(tmp_path)["git_dirty"] is True
