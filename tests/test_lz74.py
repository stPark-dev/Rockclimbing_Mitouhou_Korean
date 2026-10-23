import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import lz74  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
X_MEMORY = ROOT / "work" / "files" / "X_HUMAN" / "X_MEMORY.BIN"


def test_decode_73_block_literals_runs_and_back_references():
    # 0x73 block: literal run of 3, short run (0x7E, count 1+4) of 0x09, back reference len 3 dist 3, end
    block = bytes([0x73, 0x03, 1, 2, 3, 0x7E, 0x01, 0x09, 0x80 | (0 << 3), 0x02, 0x00])
    out, used = lz74.decode_block(block)
    assert out == bytes([1, 2, 3] + [9] * 5 + [9, 9, 9])
    assert used == len(block)


def test_decode_74_block_expands_pair_dictionary():
    # 0x74 block with one escape byte 0xEE standing for the pair (0x41, 0x42), read low byte first;
    # a literal run counts the pair as two symbols
    block = bytes([0x74, 0x01, 0xEE, 0x41, 0x42, 0x03, 0xEE, 0x43, 0x00])
    out, used = lz74.decode_block(block)
    assert out == b"ABC"
    assert used == len(block)


def test_fill_block():
    out, used = lz74.decode_block(bytes([0x40, 0x5A, 0x03, 0x00]))
    assert out == b"ZZZ" and used == 4


def test_long_run_and_stored_block():
    out, _ = lz74.decode_block(bytes([0x73, 0x7F, 0x05, 0x01, 0x07, 0x00]))
    assert out == bytes([7] * 0x105)
    out, used = lz74.decode_block(bytes([0xFF, 0x02, 0x00, 0xAA, 0xBB]))
    assert out == b"\xaa\xbb" and used == 5


def test_stream_places_blocks_every_0x2000_bytes():
    raw = bytes(range(256)) * 40  # 10240 bytes, two blocks
    stream = lz74.encode_stream(raw)
    assert lz74.decode_stream(stream)[0] == raw
    assert stream[-1] == 0


@pytest.mark.parametrize("data", [b"", b"a", b"abcabcabcabc" * 50, bytes(5000), bytes(range(256)) * 9])
def test_encode_round_trip(data):
    assert lz74.decode_stream(lz74.encode_stream(data))[0] == data


@pytest.mark.skipif(not X_MEMORY.exists(), reason="extracted disc files are not in the repository")
def test_name_entry_graphics_decode_to_tims_and_round_trip():
    data = X_MEMORY.read_bytes()
    for off in (0x0, 0xE04, 0x272C):
        raw, used = lz74.decode_stream(data[off:])
        assert raw[:4] == b"\x10\x00\x00\x00"  # TIM magic
        assert lz74.decode_stream(lz74.encode_stream(raw))[0] == raw


def test_malformed_blocks_are_rejected():
    with pytest.raises(ValueError):
        lz74.decode_stream(bytes([0x40, 0x00, 0x00, 0x40, 0x00]))  # one block expanding to 0x4000
    with pytest.raises(ValueError):
        lz74.decode_block(bytes([0xFF, 0x05, 0x00, 0xAA]))  # stored block cut short


def test_encoder_uses_pair_escapes_when_they_help():
    data = bytes(range(0, 200, 2)) * 60
    block = lz74.encode_block(data[:0x2000])
    assert block[0] == 0x74
    assert lz74.decode_block(block)[0] == data[:0x2000]


@pytest.mark.skipif(not X_MEMORY.exists(), reason="extracted disc files are not in the repository")
def test_reencoded_title_logo_fits_its_original_slot():
    menu = (ROOT / "work" / "files" / "MENU" / "KWAMENU.BIN").read_bytes()
    for off in (0x56D24, 0x59128, 0x59A54):
        raw, used = lz74.decode_stream(menu, off)
        end = off + used
        while menu[end] == 0:  # zero padding up to the next stream is free too
            end += 1
        assert len(lz74.encode_stream(raw)) <= end - off


def test_0x74_blocks_use_at_most_16_pairs():
    # the game keeps escape keys at 0x80060408 (16 bytes) and pairs at 0x80060418 (16 halfwords)
    import random
    rnd = random.Random(1)
    data = bytes(rnd.choice(range(0, 120, 3)) for _ in range(0x2000))
    block = lz74.encode_block(data)
    if block[0] == 0x74:
        assert block[1] <= 16
    assert lz74.decode_block(block)[0] == data
    with pytest.raises(ValueError):
        lz74.decode_block(bytes([0x74, 17]) + bytes(range(1, 18)) + bytes(34) + b"\x00")


def test_dp_tokens_round_trip_random_data():
    import random
    rnd = random.Random(7)
    for n in (1, 3, 17, 300, 0x2000):
        data = bytes(rnd.choice((0, 0, 1, 2, rnd.randrange(256))) for _ in range(n))
        block = bytes([0x73]) + lz74._tokens_dp(data) + b"\x00"
        assert lz74.decode_block(block)[0] == data
        assert len(block) <= len(bytes([0x73]) + lz74._tokens(data) + b"\x00")


def test_decode_0x20_block_literals_absolute_and_relative_copies():
    # 02 'A' 'B' literals; 0x80|0 + 00 00: 3 bytes from block offset 0; 0xC0|1 + 00: 4 bytes from 1 back; end
    block = bytes([0x20, 0x02, 0x41, 0x42, 0x80, 0x00, 0x00, 0xC1, 0x00, 0x00])
    out, used = lz74.decode_block(block)
    assert out == b"AB" + b"ABA" + b"AAAA"
    assert used == len(block)
