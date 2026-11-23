"""Read and write ASE and GPL swatches in sRGB."""
from math import isfinite
from struct import Struct
from pathlib import Path
from dataclasses import dataclass

@dataclass(frozen=True)
class Swatch:
    name: str
    rgba: tuple


ASE_HEADER = Struct(">4sHHI")
ASE_BLOCK = Struct(">HI")
ASE_NAME_LENGTH = Struct(">H")
ASE_MODELS = {b"RGB ": Struct(">3fH"), b"Gray": Struct(">fH")}


def read_gpl(data):
    lines = data.decode("utf-8-sig").splitlines()
    if not lines or lines[0].strip() != "GIMP Palette":
        raise ValueError("文件缺少 GIMP Palette 标识。")
    colors = []
    for number, line in enumerate(lines[1:], 2):
        line = line.strip()
        if not line or line.startswith(("#", "Name:", "Columns:", "Channels:")):
            continue
        parts = line.split(maxsplit=3)
        components = parts[:3]
        if len(components) != 3 or any(not value.isascii() or not value.isdecimal() for value in components):
            raise ValueError(f"GPL 第 {number} 行的 RGB 无效。")
        rgb = tuple(map(int, components))
        if any(value > 255 for value in rgb):
            raise ValueError(f"GPL 第 {number} 行的 RGB 超出 0–255。")
        colors.append(Swatch(parts[3] if len(parts) == 4 else "", (*rgb, 255)))
    return tuple(colors)


def read_ase(data):
    if len(data) < ASE_HEADER.size:
        raise ValueError("ASE 文件头不完整。")
    signature, major, _, count = ASE_HEADER.unpack_from(data)
    if signature != b"ASEF" or major != 1:
        raise ValueError("仅支持 Adobe Swatch Exchange 1.x。")
    offset = ASE_HEADER.size
    colors = []
    for number in range(1, count + 1):
        if len(data) - offset < ASE_BLOCK.size:
            raise ValueError(f"ASE 第 {number} 块的头部不完整。")
        kind, length = ASE_BLOCK.unpack_from(data, offset)
        start = offset + ASE_BLOCK.size
        offset = start + length
        if offset > len(data):
            raise ValueError(f"ASE 第 {number} 块的数据不完整。")
        if kind in (0xC001, 0xC002):
            continue
        if kind != 1 or length < 2:
            raise ValueError(f"ASE 第 {number} 块的类型或长度无效。")
        name_length = ASE_NAME_LENGTH.unpack_from(data, start)[0]
        model_offset = start + 2 + 2 * name_length
        if not name_length or model_offset + 4 > offset or data[model_offset - 2:model_offset] != b"\x00\x00":
            raise ValueError(f"ASE 第 {number} 块的色样名称无效。")
        name = data[start + 2:model_offset - 2].decode("utf-16-be")
        model = data[model_offset:model_offset + 4]
        value_format = ASE_MODELS.get(model)
        if value_format is None:
            raise ValueError(f"ASE 第 {number} 块使用 {model.decode('ascii', 'replace').strip()}，当前支持 RGB 和灰度。")
        if model_offset + 4 + value_format.size != offset:
            raise ValueError(f"ASE 第 {number} 块的颜色数据长度不符。")
        *values, color_type = value_format.unpack_from(data, model_offset + 4)
        if color_type == 1:
            raise ValueError(f"ASE 第 {number} 块是专色，无法导入。")
        if color_type not in (0, 2) or any(not isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError(f"ASE 第 {number} 块的颜色分量无效。")
        rgb = tuple(round(value * 255) for value in values)
        colors.append(Swatch(name, (*(rgb if len(rgb) == 3 else rgb * 3), 255)))
    if offset != len(data):
        raise ValueError("ASE 文件包含未声明的数据。")
    return tuple(colors)


def write_gpl(name, swatches):
    clean = lambda value: " ".join(value.splitlines())
    lines = ["GIMP Palette", f"Name: {clean(name)}", "Columns: 0", "#"]
    for index, swatch in enumerate(swatches):
        rgb = " ".join(str(v) for v in swatch.rgba[:3])
        lines.append(f"{rgb}\t{clean(swatch.name) or f'Color {index}'}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_ase(name, swatches):
    blocks = []
    for index, swatch in enumerate(swatches):
        label = ((swatch.name or f"Color {index}").replace("\0", "") + "\0").encode("utf-16-be")
        if len(label) // 2 > 65535:
            raise ValueError(f"Color {index} 的名称超出 ASE 长度限制。")
        rgb = (value / 255 for value in swatch.rgba[:3])
        body = ASE_NAME_LENGTH.pack(len(label) // 2) + label + b"RGB " + ASE_MODELS[b"RGB "].pack(*rgb, 2)
        blocks.append(ASE_BLOCK.pack(1, len(body)) + body)
    return ASE_HEADER.pack(b"ASEF", 1, 0, len(blocks)) + b"".join(blocks)


def export_palettes(destination, palettes, file_format, *, batch):
    """Preflight names and encode the entire request before creating any files."""
    import tempfile
    import unicodedata
    writer = {"ase": write_ase, "gpl": write_gpl}[file_format]
    destination = Path(destination)
    encoded, seen = [], set()
    for index, (name, swatches) in enumerate(palettes):
        base = safe_filename(name)
        candidate = base
        while unicodedata.normalize("NFC", candidate).casefold() in seen:
            candidate += f" - Palette {index}"
        seen.add(unicodedata.normalize("NFC", candidate).casefold())
        path = destination / f"{candidate}.{file_format}" if batch else destination
        encoded.append((path, writer(name, swatches)))
    if batch:
        created = []
        try:
            for path, data in encoded:
                with path.open("xb") as stream:
                    created.append(path)
                    stream.write(data)
        except Exception:
            for path in created:
                path.unlink()
            raise
    else:
        path, data = encoded[0]
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data)
                stream.close()
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)


def safe_filename(name):
    name = "".join("_" if c in ":/\\\0" or ord(c) < 32 else c for c in name)
    return name.strip(" .")[:60] or "Palette"
