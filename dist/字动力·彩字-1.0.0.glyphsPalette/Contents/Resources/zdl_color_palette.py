"""Read native color palettes without changing their slot numbering."""
from math import isfinite

from AppKit import NSColor, NSColorSpace
from Foundation import NSArray, NSNumber

ARRAYS = (NSArray, list, tuple)


def normalize_color(entry):
    if isinstance(entry, NSColor):
        color = entry.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
        if color is None:
            raise ValueError("无法转换为 sRGB")
        components = (color.redComponent(), color.greenComponent(), color.blueComponent(),
                      color.alphaComponent())
        if not all(isfinite(value) for value in components):
            raise ValueError("sRGB 分量无效")
        return tuple(round(255 * min(1, max(0, value))) for value in components)

    if not isinstance(entry, ARRAYS) or len(entry) not in (2, 4):
        raise ValueError("颜色数组须为灰度与 Alpha 或 RGBA")
    if not all(isinstance(value, (int, float, NSNumber)) and not isinstance(value, bool)
               for value in entry):
        raise ValueError("颜色分量必须是数值")
    components = tuple(float(value) for value in entry)
    if not all(value.is_integer() and 0 <= value <= 255 for value in components):
        raise ValueError("数组分量须为 0–255 整数")
    if len(components) == 2:
        gray, alpha = components
        components = (gray, gray, gray, alpha)
    return tuple(int(value) for value in components)


def read_palettes(font):
    if font is None:
        return ()
    rows = font.customParameters["Color Palettes"]
    if rows is None:
        return ()
    if not isinstance(rows, ARRAYS) or any(not isinstance(row, ARRAYS) for row in rows):
        raise ValueError("不支持的 Color Palettes 结构。")

    def read_slot(entry):
        try:
            return stored_rgba(entry)
        except (TypeError, ValueError, ArithmeticError, AttributeError, RuntimeError):
            return None

    return tuple(tuple(read_slot(entry) for entry in row) for row in rows)


def stored_rgba(entry):
    """Return the verified Glyphs file/CPAL channels, without color conversion."""
    if not isinstance(entry, NSColor):
        return normalize_color(entry)
    from math import floor
    space = entry.colorSpace()
    # Glyphs' native Palette sheet canonicalizes black/gray wells to generic
    # gray NSColors. Its file writer stores (white, alpha), which read_palettes
    # already expands to RGBA for array entries. Preserve those raw channels.
    if space == NSColorSpace.genericGrayColorSpace():
        gray, alpha = entry.whiteComponent(), entry.alphaComponent()
        if any(not isfinite(value) or not 0 <= value <= 1 for value in (gray, alpha)):
            raise ValueError("颜色原始分量超出已验证范围。")
        return tuple(floor(value * 255 + 0.5) for value in (gray, gray, gray, alpha))
    if space not in (NSColorSpace.genericRGBColorSpace(), NSColorSpace.sRGBColorSpace(),
                     NSColorSpace.displayP3ColorSpace()):
        raise ValueError("此颜色空间的 Glyphs 保存行为尚未验证。")
    values = (entry.redComponent(), entry.greenComponent(), entry.blueComponent(), entry.alphaComponent())
    if any(not isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError("颜色原始分量超出已验证范围。")
    return tuple(floor(value * 255 + 0.5) for value in values)


def stored_snapshot(rows):
    if rows is None:
        return ()
    return tuple(tuple(stored_rgba(cell) for cell in row) for row in rows)
