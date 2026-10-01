"""Unit tests for the structure-extraction module (text_to_json).

These cover the pure, network-free parts of the pipeline: section
splitting, atomic-unit splitting, chunk packing and result merging.
The model call (`call_model` / `structure_text`) is intentionally not
exercised here, since it requires a live API key and network access.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.text_to_json import (
    MAX_CHUNK_SIZE,
    PreparedChunk,
    build_chunks,
    merge_results,
    pack_units_into_chunks,
    split_into_atomic_units,
    split_into_sections,
)


# ---------------------------------------------------------------------
# split_into_sections
# ---------------------------------------------------------------------

def test_split_into_sections_tags_known_anchors() -> None:
    text = (
        "شماره ثبت: 123\n"
        "عنوان طرح : آزمون\n"
        "ماده 1: متن ماده\n"
        "نظر اداره کل تدوین قوانین\n"
        "بند 1: نظر کارشناسی\n"
    )

    sections = split_into_sections(text)
    kinds = [section.kind for section in sections]

    assert kinds[0] == "generic"
    assert "operative_text" in kinds
    assert "review_tadvin" in kinds


def test_split_into_sections_without_anchor_is_generic() -> None:
    sections = split_into_sections("متن بدون لنگر")

    assert len(sections) == 1
    assert sections[0].kind == "generic"
    assert sections[0].text == "متن بدون لنگر"


# ---------------------------------------------------------------------
# split_into_atomic_units
# ---------------------------------------------------------------------

def test_split_into_atomic_units_keeps_each_article_whole() -> None:
    text = "ماده 1: متن اول\nماده 2: متن دوم\nماده 3: متن سوم\n"

    units = split_into_atomic_units(text)

    assert len(units) == 3
    assert units[0].startswith("ماده 1")
    assert units[1].startswith("ماده 2")
    assert units[2].startswith("ماده 3")


def test_split_into_atomic_units_splits_notes() -> None:
    text = "تبصره 1: الف\nتبصره 2: ب\n"

    units = split_into_atomic_units(text)

    assert len(units) == 2
    assert units[0].startswith("تبصره 1")


def test_split_into_atomic_units_returns_whole_text_when_no_boundary() -> None:
    text = "متن ساده بدون هیچ مرزی"

    assert split_into_atomic_units(text) == [text]


# ---------------------------------------------------------------------
# pack_units_into_chunks
# ---------------------------------------------------------------------

def test_pack_units_into_chunks_packs_up_to_max_size() -> None:
    assert pack_units_into_chunks(["AAAAA", "BBBBB"], max_size=6) == [
        "AAAAA",
        "BBBBB",
    ]

    assert pack_units_into_chunks(["AAAAAA", "BB"], max_size=10) == [
        "AAAAAABB"
    ]


def test_pack_units_into_chunks_keeps_oversized_unit_whole() -> None:
    oversized = "X" * 20

    assert pack_units_into_chunks([oversized], max_size=5) == [oversized]


# ---------------------------------------------------------------------
# merge_results
# ---------------------------------------------------------------------

def test_merge_results_groups_by_kind_and_preserves_order() -> None:
    outputs = [{"id": 1}, {"id": 2}, {"id": 3}]
    kinds = ["a", "b", "a"]

    assert merge_results(outputs, kinds) == {
        "a": [{"id": 1}, {"id": 3}],
        "b": [{"id": 2}],
    }


# ---------------------------------------------------------------------
# build_chunks
# ---------------------------------------------------------------------

def test_build_chunks_tags_every_chunk() -> None:
    text = "عنوان طرح : آزمون\n" + "ماده 1: " + ("الف " * 300) + "\nماده 2: پایان\n"

    chunks = build_chunks(text)

    assert chunks
    assert all(isinstance(chunk, PreparedChunk) for chunk in chunks)
    assert all(chunk.kind == "operative_text" for chunk in chunks)
    assert all(chunk.guidance for chunk in chunks)
    assert all(chunk.text.strip() for chunk in chunks)


def test_build_chunks_never_splits_an_oversized_unit() -> None:
    huge_article = "ماده 1: " + ("الف " * 1000)

    chunks = build_chunks(huge_article)

    assert len(chunks) == 1
    assert len(chunks[0].text) > MAX_CHUNK_SIZE