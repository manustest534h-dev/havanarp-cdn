#!/usr/bin/env python3

import argparse
import concurrent.futures
from io import BytesIO
import json
import math
import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path

import texture2ddecoder
from PIL import Image

from texture_thumbnails import decode_name
from vfs_archive import HEADER, parse_declared, replace_payloads


ASTC_RECORD = struct.Struct("<32sIIHHBBBBI")
IMG_HEADER = struct.Struct("<4sI")
IMG_RECORD = struct.Struct("<II24s")
TEXTURE_HEADER = struct.Struct("<HHHHII")
PVR_HEADER = struct.Struct("<IIQIIIIIIIII")
TEXTDB_HEADER = (
    "cat=0 name=Default onfoot=5 slow=5 fast=5 "
    "defaultformat=2 defaultstream=0"
)
ENCODING_DXT1 = 0x83F0
ENCODING_DXT5 = 0x83F3
ENCODING_ETC1 = 0x8D64
ENCODING_ETC_ALPHA = 0x8033
ENCODING_PVRTC4 = 0x8C02
SKIN_FIRST_ID = 17083
RESERVED_MODEL_ID = 17496
DATA_REGISTRATIONS = {
    "!client/data/gta.dat": (
        b"IDE data\\maps\\orp\\orp_skins_02.ide",
        b"IDE data\\maps\\orp\\lr_skins.ide",
    ),
    "!client/mod_imgs.cfg": (
        b"texdb\\orp_skins_02.img          0",
        b"texdb\\lr_skins.img                 0",
    ),
    "!client/mod_texdbs.cfg": (
        b"orp_skins_02        none                1",
        b"lr_skins            none                1",
    ),
}


@dataclass(frozen=True)
class AstcTexture:
    name: str
    offset: int
    size: int
    width: int
    height: int
    block_width: int
    block_height: int
    mip_count: int
    flags: int


@dataclass(frozen=True)
class EncodedTexture:
    name: str
    width: int
    height: int
    alpha: bool
    image_crc32: str


def hash_name(name: str) -> int:
    value = 0
    for byte in name.encode("ascii"):
        value = (value + ((value << 5) + byte)) & 0xFFFFFFFF
    value = (value + (value >> 5)) & 0xFFFFFFFF
    return value & 0xFFFF


def read_astc_textures(path: Path) -> list[AstcTexture]:
    data = path.read_bytes()
    if data[:8] != b"ASTCARC\0":
        raise ValueError("unsupported ASTC archive")
    version, count = struct.unpack_from("<II", data, 8)
    if version != 3:
        raise ValueError(f"unsupported ASTC archive version: {version}")

    textures = []
    offset = 16
    for _ in range(count):
        values = ASTC_RECORD.unpack_from(data, offset)
        offset += ASTC_RECORD.size
        raw_name, payload_offset, size, width, height, block_width, block_height, mip_count, reserved, flags = values
        if reserved:
            raise ValueError(f"unexpected ASTC reserved value for {raw_name!r}")
        textures.append(
            AstcTexture(
                name=raw_name.split(b"\0", 1)[0].decode("ascii"),
                offset=payload_offset,
                size=size,
                width=width,
                height=height,
                block_width=block_width,
                block_height=block_height,
                mip_count=mip_count,
                flags=flags,
            )
        )
    if len({texture.name.lower() for texture in textures}) != len(textures):
        raise ValueError("duplicate ASTC texture names")
    return textures


def read_img_names(path: Path) -> set[str]:
    with path.open("rb") as stream:
        magic, count = IMG_HEADER.unpack(stream.read(IMG_HEADER.size))
        if magic != b"VER2":
            raise ValueError("unsupported IMG archive")
        names = set()
        for _ in range(count):
            _, _, raw_name = IMG_RECORD.unpack(stream.read(IMG_RECORD.size))
            name = raw_name.split(b"\0", 1)[0].decode("ascii").lower()
            if name in names:
                raise ValueError(f"duplicate IMG entry: {name}")
            names.add(name)
    return names


def target_size(width: int, height: int, max_size: int) -> tuple[int, int]:
    if max(width, height) <= max_size:
        return width, height
    scale = max_size / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def astc_top_size(texture: AstcTexture) -> int:
    blocks_x = math.ceil(texture.width / texture.block_width)
    blocks_y = math.ceil(texture.height / texture.block_height)
    return blocks_x * blocks_y * 16


def decode_texture(
    archive: bytes, texture: AstcTexture, max_size: int
) -> tuple[Image.Image, bool]:
    top_size = astc_top_size(texture)
    raw = archive[texture.offset : texture.offset + top_size]
    if len(raw) != top_size:
        raise ValueError(f"truncated ASTC payload: {texture.name}")
    bgra = texture2ddecoder.decode_astc(
        raw,
        texture.width,
        texture.height,
        texture.block_width,
        texture.block_height,
    )
    image = Image.frombytes("RGBA", (texture.width, texture.height), bgra)
    image = Image.merge(
        "RGBA",
        (
            image.getchannel("B"),
            image.getchannel("G"),
            image.getchannel("R"),
            image.getchannel("A"),
        ),
    )
    size = target_size(image.width, image.height, max_size)
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)

    alpha = image.getchannel("A")
    has_alpha = alpha.getextrema()[0] < 250
    if not has_alpha:
        image.putalpha(255)
    return image, has_alpha


def mip_images(image: Image.Image) -> list[Image.Image]:
    levels = [image]
    while levels[-1].size != (1, 1):
        width, height = levels[-1].size
        levels.append(
            levels[-1].resize(
                (max(1, width // 2), max(1, height // 2)),
                Image.Resampling.LANCZOS,
            )
        )
    return levels


def encode_dxt_level(image: Image.Image, alpha: bool) -> bytes:
    output = BytesIO()
    image.save(output, format="DDS", pixel_format="DXT5" if alpha else "DXT1")
    data = output.getvalue()
    if data[:4] != b"DDS " or len(data) <= 128:
        raise ValueError("invalid Pillow DDS output")
    return data[128:]


def encode_dxt(image: Image.Image, alpha: bool) -> bytes:
    return b"".join(encode_dxt_level(level, alpha) for level in mip_images(image))


def rgb565_bytes(image: Image.Image) -> bytes:
    output = bytearray()
    rgb = image.convert("RGB").tobytes()
    for offset in range(0, len(rgb), 3):
        red, green, blue = rgb[offset : offset + 3]
        value = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
        output.extend(value.to_bytes(2, "little"))
    return bytes(output)


def encode_etc_alpha(image: Image.Image) -> bytes:
    width, height = image.size
    color = rgb565_bytes(image)
    half_width = max(1, width // 2)
    half_height = max(1, height // 2)
    alpha = (
        image.resize((half_width, half_height), Image.Resampling.LANCZOS)
        .getchannel("A")
        .tobytes()
    )
    packed_alpha = bytearray()
    for offset in range(0, len(alpha), 3):
        chunk = alpha[offset : offset + 3]
        packed_alpha.extend(chunk)
        packed_alpha.extend(b"\0" * (8 - len(chunk)))
    payload_size = (
        width * height * 2
        + (width // 2) * (height // 2) * 8 // 3
    )
    packed_alpha = packed_alpha[: payload_size - len(color)]
    packed_alpha.extend(b"\0" * (payload_size - len(color) - len(packed_alpha)))
    return color + packed_alpha


def read_pvr_payload(path: Path, expected_width: int, expected_height: int) -> bytes:
    data = path.read_bytes()
    if len(data) < PVR_HEADER.size:
        raise ValueError(f"truncated PVR output: {path}")
    values = PVR_HEADER.unpack_from(data)
    version, _, _, _, _, height, width, depth, surfaces, faces, mip_count, metadata_size = values
    if version != 0x03525650:
        raise ValueError(f"invalid PVR header: {path}")
    if (width, height) != (expected_width, expected_height):
        raise ValueError(f"unexpected PVR dimensions: {path}")
    if depth != 1 or surfaces != 1 or faces != 1 or mip_count < 1:
        raise ValueError(f"unsupported PVR layout: {path}")
    return data[PVR_HEADER.size + metadata_size :]


def run_pvrtex(
    tool: Path,
    image_path: Path,
    output_path: Path,
    texture_format: str,
    quality: str,
    mipmaps: bool = True,
) -> bytes:
    command = [
        str(tool),
        "-i",
        str(image_path),
        "-f",
        texture_format,
    ]
    if mipmaps:
        command.append("-m")
    command.extend(
        [
            "-q",
            quality,
            "-o",
            str(output_path),
            "-shh",
        ]
    )
    subprocess.run(command, check=True)
    with Image.open(image_path) as image:
        return read_pvr_payload(output_path, image.width, image.height)


def encode_one_texture(
    archive: bytes,
    texture: AstcTexture,
    cache_dir: Path,
    pvrtex_tool: Path,
    max_size: int,
) -> EncodedTexture:
    metadata_path = cache_dir / f"{texture.name}.json"
    payload_paths = {
        extension: cache_dir / f"{texture.name}.{extension}"
        for extension in ("dxt", "etc", "pvr", "dxt.tmb", "etc.tmb", "pvr.tmb")
    }
    if metadata_path.is_file() and all(path.is_file() for path in payload_paths.values()):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return EncodedTexture(
            name=texture.name,
            width=metadata["width"],
            height=metadata["height"],
            alpha=metadata["alpha"],
            image_crc32=metadata["image_crc32"],
        )

    image, alpha = decode_texture(archive, texture, max_size)
    png_path = cache_dir / f"{texture.name}.png"
    etc_path = cache_dir / f"{texture.name}.etc.pvr"
    pvr_path = cache_dir / f"{texture.name}.pvr.pvr"
    thumbnail_path = cache_dir / f"{texture.name}.thumbnail.png"
    thumbnail_etc_path = cache_dir / f"{texture.name}.thumbnail.etc.pvr"
    thumbnail_pvr_path = cache_dir / f"{texture.name}.thumbnail.pvr.pvr"
    image.save(png_path)

    dxt = encode_dxt(image, alpha)
    if alpha:
        etc = encode_etc_alpha(image)
    else:
        etc = run_pvrtex(
            pvrtex_tool, png_path, etc_path, "ETC1", "etcfast"
        )
    pvr = run_pvrtex(
        pvrtex_tool,
        png_path,
        pvr_path,
        "PVRTC1_4" if alpha else "PVRTC1_4_RGB",
        "pvrtcfast",
    )

    thumbnail = image.resize((8, 8), Image.Resampling.LANCZOS)
    thumbnail.save(thumbnail_path)
    dxt_thumbnail = encode_dxt_level(thumbnail, alpha)
    if alpha:
        etc_thumbnail = encode_etc_alpha(thumbnail)
    else:
        etc_thumbnail = run_pvrtex(
            pvrtex_tool,
            thumbnail_path,
            thumbnail_etc_path,
            "ETC1",
            "etcfast",
            False,
        )
    pvr_thumbnail = run_pvrtex(
        pvrtex_tool,
        thumbnail_path,
        thumbnail_pvr_path,
        "PVRTC1_4" if alpha else "PVRTC1_4_RGB",
        "pvrtcfast",
        False,
    )

    payload_paths["dxt"].write_bytes(dxt)
    payload_paths["etc"].write_bytes(etc)
    payload_paths["pvr"].write_bytes(pvr)
    payload_paths["dxt.tmb"].write_bytes(dxt_thumbnail)
    payload_paths["etc.tmb"].write_bytes(etc_thumbnail)
    payload_paths["pvr.tmb"].write_bytes(pvr_thumbnail)
    image_crc32 = f"{zlib.crc32(image.tobytes()) & 0xFFFFFFFF:08x}"
    metadata_path.write_text(
        json.dumps(
            {
                "width": image.width,
                "height": image.height,
                "alpha": alpha,
                "image_crc32": image_crc32,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    png_path.unlink(missing_ok=True)
    etc_path.unlink(missing_ok=True)
    pvr_path.unlink(missing_ok=True)
    thumbnail_path.unlink(missing_ok=True)
    thumbnail_etc_path.unlink(missing_ok=True)
    thumbnail_pvr_path.unlink(missing_ok=True)
    return EncodedTexture(
        name=texture.name,
        width=image.width,
        height=image.height,
        alpha=alpha,
        image_crc32=image_crc32,
    )


def texture_record(
    name: str,
    encoding: int,
    width: int,
    height: int,
    payload: bytes,
) -> bytes:
    return TEXTURE_HEADER.pack(
        hash_name(name),
        encoding,
        width,
        height | 0x8000,
        len(payload) + 4,
        0,
    ) + payload


def build_textdb(
    textures: list[EncodedTexture],
    cache_dir: Path,
    output_dir: Path,
    extension: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dat = bytearray()
    tmb = bytearray()
    offsets = []
    lines = [TEXTDB_HEADER]
    for texture in textures:
        offsets.append(len(dat))
        encoding = {
            "dxt": ENCODING_DXT5 if texture.alpha else ENCODING_DXT1,
            "etc": ENCODING_ETC_ALPHA if texture.alpha else ENCODING_ETC1,
            "pvr": ENCODING_PVRTC4,
        }[extension]
        payload = (cache_dir / f"{texture.name}.{extension}").read_bytes()
        thumbnail = (
            cache_dir / f"{texture.name}.{extension}.tmb"
        ).read_bytes()
        dat.extend(
            texture_record(
                texture.name,
                encoding,
                texture.width,
                texture.height,
                payload,
            )
        )
        tmb.extend(
            texture_record(texture.name, encoding, 8, 8, thumbnail)
        )
        line = (
            f'"{texture.name}" width={texture.width} height={texture.height} '
            f"img={texture.image_crc32}"
        )
        if texture.alpha:
            line += " alphamode=2"
        lines.append(line)

    (output_dir / f"lr_skins.{extension}.dat").write_bytes(dat)
    (output_dir / f"lr_skins.{extension}.tmb").write_bytes(tmb)
    (output_dir / f"lr_skins.{extension}.toc").write_bytes(
        struct.pack(f"<I{len(offsets)}i", len(dat), *offsets)
    )
    (output_dir / "lr_skins.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def model_mapping(ped_models: list[dict]) -> list[tuple[int, dict]]:
    mapping = []
    model_id = SKIN_FIRST_ID
    for model in ped_models:
        if model["modelName"] == "null":
            continue
        if model_id == RESERVED_MODEL_ID:
            model_id += 1
        mapping.append((model_id, model))
        model_id += 1
    if len(mapping) != 432 or mapping[-1][0] != 17515:
        raise ValueError("unexpected skin ID mapping")
    return mapping


def build_ide_and_ids(
    ped_models_path: Path,
    img_path: Path,
    ide_path: Path,
    ids_path: Path,
) -> set[int]:
    ped_models = json.loads(ped_models_path.read_text(encoding="utf-8"))
    mapping = model_mapping(ped_models)
    img_names = read_img_names(img_path)
    expected_names = {
        f"{model['modelName']}.dff".lower() for _, model in mapping
    }
    if img_names != expected_names:
        raise ValueError(
            f"IMG/ped mismatch: missing={sorted(expected_names - img_names)}, "
            f"extra={sorted(img_names - expected_names)}"
        )

    lines = ["peds", "# Live Russia skins imported by HavanaRP"]
    ids = [
        "model_id\tsource_id\tmodel_name\ttxd_name\tanim_group\t"
        "anim_file\tsource_dff"
    ]
    for model_id, model in mapping:
        anim_group = model["animGroup"]
        female = "woman" in anim_group
        ped_class = "CIVFEMALE" if female else "CIVMALE"
        stat = "STAT_TOUGH_GIRL" if female else "STAT_TOUGH_GUY"
        anim_file = model["animFile"] or "null"
        lines.append(
            f"{model_id}, {model['modelName']}, {model['txdName']}, "
            f"{ped_class}, {stat}, {anim_group}, 0, 1, {anim_file}, "
            "7, 0, PED_TYPE_GEN, VOICE_GEN_NOVOICE, VOICE_GEN_NOVOICE"
        )
        ids.append(
            f"{model_id}\t{model['id']}\t{model['modelName']}\t"
            f"{model['txdName']}\t{anim_group}\t{anim_file}\t"
            f"{model['modelName']}.dff"
        )
    lines.append("end")
    ide_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    ids_path.write_text("\n".join(ids) + "\n", encoding="utf-8")
    return {model_id for model_id, _ in mapping}


def encoded_name(name: str) -> bytes:
    if not name.startswith("!"):
        raise ValueError(f"VFS name must start with !: {name}")
    raw_name = name.encode("ascii")
    key = len(raw_name) & 0xFF
    return bytes(byte ^ key for byte in raw_name)


def build_vfs_record(
    archive: bytes,
    template_index: int,
    name: str,
    payload: bytes,
) -> bytes:
    records = parse_declared(archive)
    template = records[template_index]
    header = bytearray(archive[template.offset : template.content_offset])
    encoded = encoded_name(name)
    header = header[: HEADER.size]
    struct.pack_into("<I", header, 18, len(payload))
    struct.pack_into("<I", header, 22, len(payload))
    struct.pack_into("<I", header, 26, len(encoded))
    return bytes(header) + encoded + payload


def add_vfs_records(
    source: Path,
    destination: Path,
    additions: list[tuple[str, bytes]],
) -> None:
    archive = source.read_bytes()
    records = parse_declared(archive)
    directory_template = next(
        index for index, record in enumerate(records) if record.packed_size == 0
    )
    file_template = next(
        index
        for index, record in enumerate(records)
        if record.packed_size and decode_name(record.name).startswith("!client/")
    )
    existing = {decode_name(record.name) for record in records}
    duplicate = existing & {name for name, _ in additions}
    if duplicate:
        raise ValueError(f"VFS entries already exist: {sorted(duplicate)}")

    last_name = decode_name(records[-1].name)
    insertion_offset = (
        records[-1].end_offset
        if last_name.startswith("!client/")
        else records[-1].offset
    )
    inserted = bytearray()
    for name, payload in additions:
        template = directory_template if not payload else file_template
        inserted.extend(build_vfs_record(archive, template, name, payload))
    result = archive[:insertion_offset] + inserted + archive[insertion_offset:]
    result_names = {
        decode_name(record.name) for record in parse_declared(result)
    }
    missing = {name for name, _ in additions} - result_names
    if missing:
        raise ValueError(f"VFS entries failed name encoding: {sorted(missing)}")
    destination.write_bytes(result)


def add_data_registrations(archive_path: Path) -> None:
    archive = archive_path.read_bytes()
    replacements = {}
    found = set()
    for index, record in enumerate(parse_declared(archive)):
        name = decode_name(record.name)
        if name not in DATA_REGISTRATIONS:
            continue
        anchor, registration = DATA_REGISTRATIONS[name]
        payload = archive[record.content_offset : record.end_offset]
        if registration in payload.splitlines():
            found.add(name)
            continue
        line_ending = b"\r\n" if b"\r\n" in payload else b"\n"
        anchor_with_ending = anchor + line_ending
        if payload.count(anchor_with_ending) != 1:
            raise ValueError(f"registration anchor missing in {name}")
        replacements[index] = payload.replace(
            anchor_with_ending,
            anchor_with_ending + registration + line_ending,
            1,
        )
        found.add(name)
    missing = DATA_REGISTRATIONS.keys() - found
    if missing:
        raise ValueError(f"registration files missing: {sorted(missing)}")
    archive_path.write_bytes(replace_payloads(archive, replacements))


def validate_data_registrations(archive_path: Path) -> None:
    archive = archive_path.read_bytes()
    registrations = {}
    for record in parse_declared(archive):
        name = decode_name(record.name)
        if name in DATA_REGISTRATIONS:
            registrations[name] = set(
                archive[record.content_offset : record.end_offset].splitlines()
            )
    for name, (_, registration) in DATA_REGISTRATIONS.items():
        if registration not in registrations.get(name, set()):
            raise ValueError(f"registration missing from {name}")


def collect_ide_ids(archive_path: Path) -> dict[int, list[str]]:
    ids: dict[int, list[str]] = {}
    archive = archive_path.read_bytes()
    for record in parse_declared(archive):
        name = decode_name(record.name)
        if not name.lower().endswith(".ide"):
            continue
        payload = archive[record.content_offset : record.end_offset]
        for raw_line in payload.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(b"#"):
                continue
            first = line.split(b",", 1)[0].strip()
            if not first.isdigit():
                continue
            model_id = int(first)
            ids.setdefault(model_id, []).append(name)
    return ids


def build_archives(
    source_dir: Path,
    output_dir: Path,
    img_path: Path,
    ide_path: Path,
    textdb_root: Path,
    skin_ids: set[int],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    add_vfs_records(
        source_dir / ".custom3",
        output_dir / ".custom3",
        [("!client/texdb/lr_skins.img", img_path.read_bytes())],
    )
    for extension in ("dxt", "etc", "pvr"):
        database = textdb_root / extension
        additions = [
            ("!client/texdb/lr_skins/", b""),
            (
                f"!client/texdb/lr_skins/lr_skins.{extension}.dat",
                (database / f"lr_skins.{extension}.dat").read_bytes(),
            ),
            (
                f"!client/texdb/lr_skins/lr_skins.{extension}.tmb",
                (database / f"lr_skins.{extension}.tmb").read_bytes(),
            ),
            (
                f"!client/texdb/lr_skins/lr_skins.{extension}.toc",
                (database / f"lr_skins.{extension}.toc").read_bytes(),
            ),
            (
                "!client/texdb/lr_skins/lr_skins.txt",
                (database / "lr_skins.txt").read_bytes(),
            ),
        ]
        add_vfs_records(
            source_dir / f".custom3_{extension}",
            output_dir / f".custom3_{extension}",
            additions,
        )
    add_vfs_records(
        source_dir / ".data",
        output_dir / ".data",
        [("!client/data/maps/orp/lr_skins.ide", ide_path.read_bytes())],
    )
    add_data_registrations(output_dir / ".data")
    validate_data_registrations(output_dir / ".data")
    ids = collect_ide_ids(output_dir / ".data")
    if not skin_ids.issubset(ids):
        raise ValueError("not all new skin IDs are present in the data archive")
    for model_id in skin_ids:
        if ids[model_id] != ["!client/data/maps/orp/lr_skins.ide"]:
            raise ValueError(
                f"new skin ID collision {model_id}: {ids[model_id]}"
            )
    if RESERVED_MODEL_ID not in ids:
        raise ValueError(f"reserved object ID {RESERVED_MODEL_ID} disappeared")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build collision-free Live Russia skin archives for HavanaRP."
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-img", type=Path, required=True)
    parser.add_argument("--source-astc", type=Path, required=True)
    parser.add_argument("--ped-models", type=Path, required=True)
    parser.add_argument("--pvrtex-tool", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-size", type=int, default=512)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    if not args.pvrtex_tool.is_file():
        raise FileNotFoundError(args.pvrtex_tool)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = args.output_dir / "texture-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    textures = read_astc_textures(args.source_astc)
    archive = args.source_astc.read_bytes()
    encoded = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        futures = {
            executor.submit(
                encode_one_texture,
                archive,
                texture,
                cache_dir,
                args.pvrtex_tool,
                args.max_size,
            ): texture.name
            for texture in textures
        }
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            encoded[result.name] = result
            completed += 1
            if completed % 50 == 0 or completed == len(textures):
                print(f"encoded {completed}/{len(textures)} textures", flush=True)

    ordered = [encoded[texture.name] for texture in textures]
    textdb_root = args.output_dir / "textdb"
    for extension in ("dxt", "etc", "pvr"):
        build_textdb(
            ordered,
            cache_dir,
            textdb_root / extension,
            extension,
        )

    ide_path = args.output_dir / "lr_skins.ide"
    ids_path = args.output_dir / "live-russia-skin-ids.tsv"
    skin_ids = build_ide_and_ids(
        args.ped_models,
        args.source_img,
        ide_path,
        ids_path,
    )
    build_archives(
        args.source_dir,
        args.output_dir / "fixed",
        args.source_img,
        ide_path,
        textdb_root,
        skin_ids,
    )
    summary = {
        "skins": len(skin_ids),
        "textures": len(textures),
        "alpha_textures": sum(texture.alpha for texture in ordered),
        "first_skin_id": min(skin_ids),
        "last_skin_id": max(skin_ids),
        "reserved_model_ids": [RESERVED_MODEL_ID],
        "max_texture_size": args.max_size,
    }
    (args.output_dir / "build-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
