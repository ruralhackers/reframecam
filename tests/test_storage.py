"""Storage abstraction tests — local backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import storage


def test_save_photo_writes_to_correct_kind_directory(seeded_stations: list[str], data_root: Path) -> None:
    locator = storage.save_photo(
        "bosque-comestible", "2026-03-12_a4f3.jpg", b"<bytes>", "viewer"
    )
    assert locator == "photos/bosque-comestible/viewer/2026-03-12_a4f3.jpg"

    on_disk = data_root / "photos" / "bosque-comestible" / "viewer" / "2026-03-12_a4f3.jpg"
    assert on_disk.read_bytes() == b"<bytes>"


def test_round_trip_save_read(seeded_stations: list[str]) -> None:
    storage.save_photo("casa-do-pobo", "x.jpg", b"hello", "thumb")
    assert storage.read_photo("casa-do-pobo", "x.jpg", "thumb") == b"hello"


def test_photo_url_format(seeded_stations: list[str]) -> None:
    url = storage.photo_url("ies-ponte-caldelas", "abc.jpg", "thumb")
    assert url == "/photos/ies-ponte-caldelas/thumb/abc.jpg"


def test_delete_photo_removes_all_kinds(seeded_stations: list[str], data_root: Path) -> None:
    for kind in ("viewer", "thumb"):
        storage.save_photo("bosque-comestible", "z.jpg", b"<>", kind)
    for kind in ("viewer", "thumb"):
        assert (data_root / "photos" / "bosque-comestible" / kind / "z.jpg").is_file()

    storage.delete_photo("bosque-comestible", "z.jpg")

    for kind in ("viewer", "thumb"):
        assert not (data_root / "photos" / "bosque-comestible" / kind / "z.jpg").exists()


def test_delete_photo_tolerates_missing_files(seeded_stations: list[str]) -> None:
    storage.delete_photo("bosque-comestible", "never-existed.jpg")  # no raise


def test_save_photo_rejects_unknown_kind(seeded_stations: list[str]) -> None:
    with pytest.raises(ValueError, match="unknown photo kind"):
        storage.save_photo("bosque-comestible", "x.jpg", b"<>", "preview")


def test_ensure_storage_layout_creates_dirs(data_root: Path) -> None:
    storage.ensure_storage_layout(["alpha", "beta"])
    for slug in ("alpha", "beta"):
        for kind in ("viewer", "thumb"):
            assert (data_root / "photos" / slug / kind).is_dir()
