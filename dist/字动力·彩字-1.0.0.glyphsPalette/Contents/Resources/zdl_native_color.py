"""Native Glyphs picker discovery and safe Palette transaction boundaries."""
import json

from AppKit import NSApplication, NSColor, NSColorSpace
from zdl_color_palette import stored_rgba


def font_info_sheet():
    """Do not ask a controller to create Font Info just to test its lifetime."""
    for window in NSApplication.sharedApplication().windows():
        if window.identifier() == "GSFontInfoWindow" and window.attachedSheet() is not None:
            return window
    return None


def require_palette_write_boundary():
    if font_info_sheet() is not None:
        raise ValueError("原生字体信息窗口仍在编辑草稿，色板写入将在窗口结束后执行。")


def picker_rgba(color):
    """Match Glyphs' stored channels; convert non-RGB picker modes once."""
    if not isinstance(color, NSColor):
        raise ValueError("原生颜色选择器未返回有效颜色。")
    try:
        return stored_rgba(color)
    except ValueError:
        rgb = color.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
        if rgb is None:
            raise ValueError("此原生颜色无法转换为色板所需的 RGB。")
        return stored_rgba(rgb)


def slot_request(kind, font, palette, index, rows, raw_identity):
    """Bind delayed edits to identities, never to a possibly shifted number."""
    state = json.loads(raw_identity) if raw_identity else None
    return dict(kind=kind, font=font, palette=palette, index=index,
                slot_id=state['slots'][index] if state and index is not None else None,
                palette_id=state['palettes'][palette]['id'] if state else None,
                shape=tuple(len(row) for row in rows or ()),
                colors=tuple(tuple(stored_rgba(c) for c in row) for row in rows or ()))


def resolve_request(request, rows, raw_identity):
    state = json.loads(raw_identity) if raw_identity else None
    if request['slot_id']:
        if not state or request['slot_id'] not in state['slots']:
            raise ValueError("排队的颜色槽已被删除，请重新选择。")
        palette = next((i for i, p in enumerate(state['palettes'])
                        if p['id'] == request['palette_id']), None)
        if palette is None:
            raise ValueError("排队的套系已被删除，请重新选择。")
        return palette, state['slots'].index(request['slot_id'])
    if request['kind'] == 'add':
        return request['palette'], None
    # A font with no identity can acquire one after the first queued add.
    # Only an unchanged original prefix establishes the old slot's identity.
    colors = tuple(tuple(stored_rgba(c) for c in row) for row in rows or ())
    original = request['colors']
    if (len(colors) != len(original)
            or any(tuple(row[:len(old)]) != old for row, old in zip(colors, original))):
        raise ValueError("原生色板或排队槽位已变化，请重新选择，未写入任何颜色。")
    palette, index = request['palette'], request['index']
    if not 0 <= palette < len(rows) or not 0 <= index < len(rows[palette]):
        raise ValueError("排队的颜色编号已变化，请重新选择。")
    return palette, index
