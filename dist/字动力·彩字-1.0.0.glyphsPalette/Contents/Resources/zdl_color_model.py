"""Native Color Palette data, master targets and cached glyph counts."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256

from GlyphsApp import GSLayer

from zdl_color_palette import read_palettes

PALETTES = "Color Palettes"
OWNER = "com.zidongli.color.layer.v1"
LEGACY_OWNER = "com.zidongli.color.probe.layer"
GEOMETRY = "com.zidongli.color.generatedGeometry.v1"
FOREGROUND = 0xFFFF


def palette_problem(rows):
    if not rows:
        return "字体没有 Color Palettes。"
    if len({len(row) for row in rows}) > 1:
        return "色板槽位数量不一致，已暂停着色。"
    if not rows[0]:
        return "原生色板为空。"
    return ""


def color_label(rgba):
    if rgba is None:
        return "无效色槽"
    return "#" + "".join(f"{value:02X}" for value in rgba[:3])


def tooltip(index, rgba):
    if index == FOREGROUND:
        return "前景色 * · 0xFFFF · 跟随呈现环境"
    if rgba is None:
        return f"颜色 {index} · 无效色槽"
    return f"颜色 {index} · {color_label(rgba)} · RGBA {', '.join(map(str, rgba))}"


def native_layers(glyph, master_id):
    return [layer for layer in glyph.layers
            if layer.associatedMasterId == master_id and layer.isColorPaletteLayer()]


def color_index(layer):
    value = layer.attributes["colorPalette"]
    return int(value) if value is not None else None


def geometry(layer):
    coordinates = (round(layer.width, 5), tuple((bool(path.closed), tuple(
        (str(node.type), round(node.position.x, 5), round(node.position.y, 5))
        for node in path.nodes
    )) for path in layer.paths))
    return sha256(repr(coordinates).encode()).hexdigest()


def outline(layer):
    if len(layer.components):
        return layer.copyDecomposedLayer()
    return layer


def create_color_layer(source, index):
    """Use the prototype's native GSLayer + path copies, resolving components on a copy."""
    resolved = outline(source)
    if not len(resolved.paths):
        raise ValueError("母版没有可复制的轮廓")
    if any(not path.closed for path in resolved.paths):
        raise ValueError("母版包含开放轮廓，请先检查")
    layer = GSLayer()
    layer.associatedMasterId = source.layerId
    layer.width = source.width
    layer.shapes = [path.copy() for path in resolved.paths]
    layer.attributes["colorPalette"] = index
    layer.userData[OWNER] = 1
    layer.userData[GEOMETRY] = geometry(layer)
    return layer


@dataclass
class Change:
    glyph: object
    layer: object
    before: int | None
    after: int
    created: bool = False


def plan_changes(selection, index):
    """One glyph/master target per selection. An explicitly selected color layer wins."""
    targets = {}
    for layer in selection:
        glyph = layer.parent
        if glyph is None:
            continue
        master_id = layer.associatedMasterId or layer.layerId
        key = (glyph.name, master_id)
        current = targets.setdefault(key, (glyph, {}))
        if layer.isColorPaletteLayer():
            current[1][layer.layerId] = layer
    changes, skipped = [], []
    for (name, master_id), (glyph, chosen) in targets.items():
        source = glyph.layers[master_id]
        if source is None or not source.isMasterLayer:
            skipped.append(f"{name}：未找到关联母版")
            continue
        layers = native_layers(glyph, master_id)
        if len(chosen) == 1:
            layer = next(iter(chosen.values()))
        elif len(layers) == 1:
            layer = layers[0]
        elif len(layers) > 1:
            skipped.append(f"{name}：有多条颜色层，请在原生图层中选一条")
            continue
        else:
            try:
                layer = create_color_layer(source, index)
            except ValueError as error:
                skipped.append(f"{name}：{error}")
                continue
            changes.append(Change(glyph, layer, None, index, True))
            continue
        old = color_index(layer)
        if old != index:
            changes.append(Change(glyph, layer, old, index))
    return changes, skipped


def inspect_targets(selection, slot_count):
    messages = []
    visited = set()
    for selected in selection:
        glyph = selected.parent
        if glyph is None:
            continue
        master_id = selected.associatedMasterId or selected.layerId
        key = glyph.name, master_id
        if key in visited:
            continue
        visited.add(key)
        master = glyph.layers[master_id]
        if master is None or not master.isMasterLayer:
            messages.append(f"{glyph.name}：母版缺失")
            continue
        layers = native_layers(glyph, master_id)
        prefix = f"{glyph.name} · {master.name}"
        if not layers:
            messages.append(f"{prefix}：缺少颜色层")
            continue
        signature = geometry(outline(master))
        for layer in layers:
            index = color_index(layer)
            owner = ("本版生成" if layer.userData[OWNER] == 1 else
                     "原型生成" if layer.userData[LEGACY_OWNER] == 1 else "手工或外部")
            current = geometry(outline(layer))
            parts = [owner]
            if len(master.components):
                parts.append("组件母版")
            if index != FOREGROUND and (index is None or not 0 <= index < slot_count):
                parts.append("异常编号")
            if current != signature:
                parts.append("与母版轮廓不同")
            original = layer.userData[GEOMETRY]
            if original and current != original:
                parts.append("颜色层已手工调整")
            elif original and signature != original:
                parts.append("母版或组件轮廓已变化")
            messages.append(f"{prefix} · {layer.name}：" + "、".join(parts))
    return messages


class GlyphIndex:
    """A master-scoped inventory with a single entry per glyph."""
    def __init__(self, font, master_id):
        self.font = font
        self.master_ids = (master_id,) if isinstance(master_id, str) else tuple(master_id)
        self.total = len(font.glyphs)
        self.next_position = 0
        self.items = {}
        self.by_color = defaultdict(set)
        self.eligible = self.colored = self.uncolored = self.missing = 0
        self.indices = Counter()

    def scan(self, limit):
        end = min(self.total, self.next_position + limit)
        for position in range(self.next_position, end):
            self.update(self.font.glyphs[position])
        self.next_position = end
        return end == self.total

    def update(self, glyph):
        name = glyph.name
        eligible = missing = False
        indices = set()
        if glyph.export:
            for master_id in self.master_ids:
                master = glyph.layers[master_id]
                if master is None or not len(master.shapes):
                    continue
                eligible = True
                layers = native_layers(glyph, master_id)
                missing |= not layers
                indices.update(color_index(layer) for layer in layers)
        current = (eligible, bool(indices), missing, frozenset(indices))
        old = self.items.get(name)
        if old == current:
            return
        if old is not None:
            self.adjust(name, old, -1)
        self.items[name] = current
        self.adjust(name, current, 1)

    def adjust(self, name, row, delta):
        eligible, colored, missing, indices = row
        self.eligible += delta * eligible
        self.colored += delta * colored
        self.uncolored += delta * (eligible and not colored)
        self.missing += delta * missing
        for index in indices:
            self.indices[index] += delta
            if delta == 1:
                self.by_color[index].add(name)
            else:
                self.by_color[index].discard(name)

    def invalid_count(self, slots):
        return len(set().union(*(names for index, names in self.by_color.items()
                 if index != FOREGROUND and (index is None or not 0 <= index < slots))))
