"""Atomic writes, per-actor locks, and stale-temp cleanup (storage.py)."""

from __future__ import annotations

import threading

from emberforge_lite import storage


class TestAtomicWrite:
    def test_write_bytes_replaces(self, tmp_path):
        target = tmp_path / "a" / "f.bin"
        storage.atomic_write_bytes(target, b"hello")
        assert target.read_bytes() == b"hello"
        storage.atomic_write_bytes(target, b"world")
        assert target.read_bytes() == b"world"

    def test_no_temp_left_behind(self, tmp_path):
        storage.atomic_write_text(tmp_path / "f.txt", "x")
        leftovers = list(tmp_path.glob(f"{storage.TMP_PREFIX}*"))
        assert leftovers == []


class TestReserveAndWrite:
    def test_unique_names(self, tmp_path):
        d = tmp_path / "sounds"
        a = storage.reserve_and_write(d, "s.wav", b"1", slug="hero")
        b = storage.reserve_and_write(d, "s.wav", b"2", slug="hero")
        assert a.name == "s.wav"
        assert b.name == "s-2.wav"

    def test_concurrent_reservations_do_not_collide(self, tmp_path):
        d = tmp_path / "sprites"
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            p = storage.reserve_and_write(d, "x.png", b"data", slug="hero")
            results.append(p.name)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Every writer got a distinct filename; no two resolved to the same path.
        assert len(set(results)) == 8
        assert len(list(d.iterdir())) == 8


class TestCleanStaleTemp:
    def test_removes_temp_files(self, tmp_path):
        (tmp_path / "actors").mkdir()
        stale = tmp_path / "actors" / f"{storage.TMP_PREFIX}abc.png"
        stale.write_bytes(b"partial")
        keep = tmp_path / "actors" / "real.png"
        keep.write_bytes(b"ok")
        removed = storage.clean_stale_temp(tmp_path / "actors")
        assert stale not in list((tmp_path / "actors").iterdir())
        assert keep.is_file()
        assert len(removed) == 1

    def test_missing_root_ok(self, tmp_path):
        assert storage.clean_stale_temp(tmp_path / "nope") == []


class TestActorLockReentrant:
    def test_reentrant(self):
        with storage.actor_lock("hero"):
            with storage.actor_lock("hero"):
                assert True


class TestQuietUnlink:
    def test_clean_ignores_already_gone(self, tmp_path):
        # A temp file removed between listing and unlink must not raise.
        d = tmp_path / "actors"
        d.mkdir()
        (d / f"{storage.TMP_PREFIX}a").write_bytes(b"x")
        # Second clean over an empty dir returns nothing.
        storage.clean_stale_temp(d)
        assert storage.clean_stale_temp(d) == []
