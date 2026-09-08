"""Raw PNG tEXt chunk read/write — the SillyTavern-compatible character card
embedding mechanism (no Pillow needed; we never resize, client sends final bytes).

Format (verified against SillyTavern's own character-card-parser.js):
  - Card JSON lives in a `tEXt` chunk keyed "chara" (v2) — we also write "ccv3"
    (v3) with the same payload + an `assets` array, since real SillyTavern
    writes both for compatibility and reads ccv3 first, falling back to chara.
  - The chunk VALUE is base64(utf8(json_string)) — tEXt values must be
    Latin-1-safe; base64 is ASCII, so this is always valid.
  - Extra binary blobs (extra reference images, voice sample, the crop image)
    ride the v3 spec's asset mechanism: one tEXt chunk per asset, keyed
    "chara-ext-asset_:{path}", value = base64(raw bytes) (no utf8 step — it's
    already binary). Referenced from `assets: [{type, uri: "embeded://path",
    name, ext}]`.
"""

import base64
import json
import struct
import zlib

_SIG = b"\x89PNG\r\n\x1a\n"
_CHARA_KEY = b"chara"
_CCV3_KEY = b"ccv3"
_ASSET_PREFIX = "chara-ext-asset_:"


def _iter_chunks(png: bytes):
    """Yield (ctype: bytes, data: bytes, start: int, end: int) for every chunk.
    `start`/`end` bound the WHOLE chunk (length+type+data+crc) in `png`."""
    if png[:8] != _SIG:
        raise ValueError("not a PNG file")
    pos = 8
    n = len(png)
    while pos < n:
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        ctype = png[pos + 4:pos + 8]
        data_start = pos + 8
        data_end = data_start + length
        end = data_end + 4  # + CRC
        yield ctype, png[data_start:data_end], pos, end
        pos = end
        if ctype == b"IEND":
            break


def _make_chunk(ctype: bytes, data: bytes) -> bytes:
    body = ctype + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _make_text_chunk(keyword: str, value_bytes: bytes) -> bytes:
    # tEXt data = keyword + \x00 + text. Keyword must be Latin-1; value is
    # already base64 (pure ASCII) so a plain latin-1 encode is safe & lossless.
    data = keyword.encode("latin-1") + b"\x00" + value_bytes
    return _make_chunk(b"tEXt", data)


def _text_chunks(png: bytes) -> list[tuple[str, bytes]]:
    """[(keyword, raw_value_bytes)] for every tEXt chunk (value NOT decoded)."""
    out = []
    for ctype, data, _, _ in _iter_chunks(png):
        if ctype != b"tEXt":
            continue
        try:
            kw, _, val = data.partition(b"\x00")
            out.append((kw.decode("latin-1"), val))
        except Exception:
            continue
    return out


def read_card_json(png: bytes) -> dict | None:
    """ccv3 first, fall back to chara — matches real SillyTavern's read order."""
    chunks = dict(_text_chunks(png))
    for key in (_CCV3_KEY.decode(), _CHARA_KEY.decode()):
        raw = chunks.get(key)
        if not raw:
            continue
        try:
            return json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception:
            continue
    return None


def read_asset(png: bytes, path: str) -> bytes | None:
    """Raw bytes of an embedded `chara-ext-asset_:{path}` chunk, or None."""
    want = _ASSET_PREFIX + path
    for kw, raw in _text_chunks(png):
        if kw == want:
            try:
                return base64.b64decode(raw)
            except Exception:
                return None
    return None


def list_asset_paths(png: bytes) -> list[str]:
    out = []
    for kw, _ in _text_chunks(png):
        if kw.startswith(_ASSET_PREFIX):
            out.append(kw[len(_ASSET_PREFIX):])
    return out


def write_card(png: bytes, data_fields: dict, assets: dict[str, bytes] | None = None) -> bytes:
    """Return new PNG bytes with the card JSON (chara+ccv3) and asset blobs
    written in. `data_fields` is the V2 "data" object (name/description/... +
    `extensions.wayward`). `assets` is {path: raw_bytes} — pass a full
    replacement set each call (an omitted existing asset is dropped); pass the
    same dict back from `list_asset_paths`+`read_asset` to preserve one you're
    not touching.

    Strips ALL prior chara/ccv3/chara-ext-asset_ chunks first (old ones would
    otherwise leak: card-parser tools read the FIRST matching chunk, and PNGs
    tolerate duplicate keywords with no defined precedence)."""
    if png[:8] != _SIG:
        raise ValueError("not a PNG file")

    v2 = {"spec": "chara_card_v2", "spec_version": "2.0", "data": data_fields}
    asset_list = [
        {"type": "icon" if p in ("crop", "main") else ("x_wayward_voice" if p.startswith("voice") else "x_wayward_image"),
         "uri": f"embeded://{p}", "name": p, "ext": p.rsplit(".", 1)[-1] if "." in p else "bin"}
        for p in (assets or {})
    ]
    v3_data = {**data_fields, "assets": asset_list} if asset_list else data_fields
    v3 = {"spec": "chara_card_v3", "spec_version": "3.0", "data": v3_data}

    new_chunks = [
        _make_text_chunk("chara", base64.b64encode(json.dumps(v2, ensure_ascii=False).encode("utf-8"))),
        _make_text_chunk("ccv3", base64.b64encode(json.dumps(v3, ensure_ascii=False).encode("utf-8"))),
    ]
    for path, raw in (assets or {}).items():
        new_chunks.append(_make_text_chunk(_ASSET_PREFIX + path, base64.b64encode(raw)))

    out = bytearray(_SIG)
    inserted = False
    for ctype, data, start, end in _iter_chunks(png):
        if ctype == b"tEXt":
            kw = data.split(b"\x00", 1)[0].decode("latin-1", "ignore")
            if kw in ("chara", "ccv3") or kw.startswith(_ASSET_PREFIX):
                continue  # dropped — replaced by new_chunks below
        if ctype == b"IEND" and not inserted:
            for c in new_chunks:
                out += c
            inserted = True
        out += png[start:end]
    if not inserted:  # no IEND found (malformed) — append anyway
        for c in new_chunks:
            out += c
    return bytes(out)


def make_solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Tiny solid-color PNG, built by hand (no Pillow) — the bundled default
    portrait for a character with no art yet."""
    r, g, b = rgb
    row = bytes([0]) + bytes((r, g, b)) * width  # filter byte 0 (None) + pixels
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        _SIG
        + _make_chunk(b"IHDR", ihdr)
        + _make_chunk(b"IDAT", zlib.compress(raw, 9))
        + _make_chunk(b"IEND", b"")
    )
