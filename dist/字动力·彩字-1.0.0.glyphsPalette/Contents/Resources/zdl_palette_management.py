"""Transactional writes to the Glyphs Color Palettes parameter."""
from zdl_license import authorized_write
from zdl_native_core import delete_map
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
import json
from objc import pyobjc_id

from AppKit import NSChangeDone
from Foundation import NSNotificationCenter, NSMapTable

from zdl_color_model import FOREGROUND
from zdl_color_palette import normalize_color, read_palettes, stored_snapshot, stored_rgba
import zdl_palette_identity as identity
from zdl_native_color import require_palette_write_boundary

PARAMETER = "Color Palettes"
ATTRIBUTE = "colorPalette"
LABELS = "com.zidongli.color.paletteNames.v1"
DEFAULT_COLOR = (0, 0, 0, 255)
PALETTE_COMMITTED = "ZDLColorGlyphsPaletteCommitted"

# Read-only, document-local lifecycle witness. Never retain a parameter/font or
# persist native pointers. Same-shape delete/recreate must also discard old IDs.
_lifecycles = NSMapTable.weakToStrongObjectsMapTable()


def _native_lifecycle_replaced(font, raw):
    parameter = next((item for item in font.customParameters if item.name == PARAMETER), None)
    pointer = pyobjc_id(parameter) if parameter is not None else None
    previous_raw = _lifecycles.objectForKey_(font)
    previous = json.loads(previous_raw) if previous_raw else None
    replaced = bool(raw and pointer is None)
    if previous and previous[1] == raw:
        replaced = replaced or previous[2] or previous[0] != pointer
    _lifecycles.setObject_forKey_(json.dumps((pointer, raw, replaced)), font)
    return replaced


def empty_palettes(rows):
    """Absent parameter, no palettes, or palettes whose last colors were removed."""
    return rows is None or not rows or all(not row for row in rows)


def palette_snapshot(font, *, complete=False):
    colors = read_palettes(font)
    if not colors or not colors[0] or len({len(row) for row in colors}) != 1:
        raise ValueError("请先建立槽位数一致的原生色板。")
    if complete and any(color is None for row in colors for color in row):
        raise ValueError("请先在字体信息中修复无效的色槽。")
    return tuple(tuple(row) for row in font.customParameters[PARAMETER]), colors


@dataclass(frozen=True)
class Reference:
    glyph: object
    layer: object
    master: str
    index: int


def _reference_records(font, slots, masters):
    for glyph in font.glyphs:
        for layer in glyph.layers:
            if not layer.isColorPaletteLayer():
                continue
            raw = layer.attributes[ATTRIBUTE]
            master = layer.associatedMasterId
            try:
                index = int(raw)
                if isinstance(raw, (str, bytes, bool)) or float(raw) != index:
                    raise ValueError()
                if master not in masters or not (0 <= index < slots or index == FOREGROUND):
                    raise ValueError()
            except (TypeError, ValueError, OverflowError):
                yield glyph, layer, master, None, raw
                continue
            yield glyph, layer, master, index, raw


def references(font, slots):
    masters = {master.id: str(master.name) for master in font.masters}
    entries, unknown = [], []
    for glyph, layer, master, index, raw in _reference_records(font, slots, masters):
        if index is None:
            unknown.append(f"{glyph.name} / {layer.layerId}: {raw!r}")
        else:
            entries.append(Reference(glyph, layer, masters[master], index))
    return entries, unknown


def edited_slot(rows, palette, index, rgba):
    return tuple(row[:index] + (rgba,) + row[index + 1:] if slot == palette else row
                 for slot, row in enumerate(rows))


def deletion_plan(font, rows, index):
    slots = len(rows[0])
    if not 0 <= index < slots:
        raise ValueError("颜色编号已变化，请重新选择。")
    entries, unknown = references(font, slots)
    if unknown:
        raise ValueError(f"有 {len(unknown)} 条未知颜色引用。首条：{unknown[0]}")
    used = frozenset(ref.glyph.name for ref in entries if ref.index == index)
    next_indices = delete_map([ref.index for ref in entries], index, slots)
    mapped = tuple((ref, value) for ref, value in zip(entries, next_indices) if index <= ref.index < FOREGROUND)
    # Removing the final ordinary slot leaves only foreground references. Remove
    # the empty native parameter too; the transaction restores all palettes on undo.
    after = tuple(row[:index] + row[index + 1:] for row in rows) if slots > 1 else None
    return after, mapped, used


def parameter_rows(font):
    value = font.customParameters[PARAMETER]
    return None if value is None else tuple(tuple(row) for row in value)


def _signature(row):
    values = []
    for color in row:
        try:
            values.append(normalize_color(color))
        except (ValueError, TypeError, ArithmeticError, RuntimeError, AttributeError):
            values.append(None)
    return sha256(repr(values).encode()).hexdigest()


def _label_records(raw):
    try:
        records = json.loads(raw or "[]")
        return records if isinstance(records, list) else []
    except (ValueError, TypeError):
        return []


def palette_labels(font, rows):
    return palette_labels_from_snapshot(rows, font.userData[LABELS])


def palette_labels_from_snapshot(rows, raw):
    records = _label_records(raw)
    result = []
    for index, row in enumerate(rows or ()):
        record = records[index] if index < len(records) else None
        if (isinstance(record, dict) and isinstance(record.get("name"), str)
                and isinstance(record.get("colors"), list)
                and all(isinstance(name, str) for name in record["colors"])
                and record.get("signature") == _signature(row)):
            result.append((record["name"], tuple(record["colors"])))
        else:
            result.append(("", ()))
    return tuple(result)


def identity_labels(font, rows):
    legacy, raw = font.userData[LABELS], font.userData[identity.KEY]
    _native_lifecycle_replaced(font, raw)
    if not raw:
        return palette_labels_from_snapshot(rows, legacy), ""
    try:
        state = identity.read(raw)
        issue = identity.status(state, stored_snapshot(rows), legacy)
        if not issue:
            return identity.labels(state), ""
    except (TypeError, ValueError, ArithmeticError, AttributeError, RuntimeError) as error:
        issue = f"颜色身份待核对：{error}"
    return tuple(("", ()) for _ in rows or ()), issue


@dataclass(frozen=True)
class PalettePlan:
    before: tuple | None
    after: tuple
    labels: tuple
    target: int
    incoming: int
    original: int

    @property
    def expansion(self):
        return max(0, self.incoming - self.original) if self.before else 0

    @property
    def inherited(self):
        return max(0, self.original - self.incoming)


def plan_palette(font, name, swatches, *, backup=False, replace_index=None):
    row = tuple(normalize_color(swatch.rgba) for swatch in swatches)
    if not row or len(row) > FOREGROUND:
        raise ValueError("色板须包含 1 至 65,535 个颜色。")
    before = parameter_rows(font)
    labels, _ = identity_labels(font, before)
    names = tuple(swatch.name for swatch in swatches)
    original = 0
    target = 0 if replace_index is None else replace_index
    if empty_palettes(before):
        if backup or replace_index is not None:
            raise ValueError("请先应用预置建立 Palette 0。")
        after = (row,)
        labels = ((name, names),)
    else:
        existing, normalized = palette_snapshot(font)
        if not 0 <= target < len(existing) or (backup and replace_index is not None):
            raise ValueError("目标套系已变化。")
        original = len(existing[0])
        if backup and len(existing) >= FOREGROUND:
            raise ValueError("已达到最大套系数量。")
        if len(row) < original:
            if None in normalized[target][len(row):]:
                raise ValueError("目标套系的沿用槽位含无效颜色，请先修复。")
            start = len(row)
            row += existing[target][start:]
            old_names = labels[target][1]
            names += tuple(old_names[i] if i < len(old_names) else "" for i in range(start, original))
        # All palettes must have equal length. Only extend others at the end.
        extended = tuple(old + row[original:] for old in existing)
        if backup:
            target = len(existing)
            after = extended + (row,)
            labels += ((name, names),)
        else:
            after = extended[:target] + (row,) + extended[target+1:]
            labels = labels[:target] + ((name, names),) + labels[target+1:]
    return PalettePlan(before, after, labels, target, len(swatches), original)


def validate_palette_references(font, rows):
    slots = len(rows[0]) if rows else 0
    entries, unknown = references(font, FOREGROUND)
    if unknown:
        raise ValueError(f"发现 {len(unknown)} 条无法识别的颜色层引用。首条：{unknown[0]}")
    used = {ref.index for ref in entries if ref.index != FOREGROUND}
    maximum = max(used, default=-1)
    if maximum >= slots:
        raise ValueError(f"字形正在使用 Color {maximum}，拟写入的 {slots} 个槽位不足。")
    for palette, row in enumerate(rows or ()):
        for index in sorted(used):
            try:
                stored_rgba(row[index])
            except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError) as error:
                raise ValueError(f"Palette {palette} 的 Color {index} 无效，且已有字形引用。") from error
    return maximum


def add_color_slot(font):
    current = parameter_rows(font)
    if empty_palettes(current):
        commit(font, current, ((DEFAULT_COLOR,),), undo_name="新增颜色")
        return 0
    before, _ = palette_snapshot(font)
    index = len(before[0])
    if index >= FOREGROUND:
        raise ValueError("色板已达到最大槽位数量。")
    commit(font, before, tuple(row + (DEFAULT_COLOR,) for row in before), undo_name="新增颜色")
    return index


@authorized_write
def write_rows(font, rows):
    require_palette_write_boundary()
    if rows is None:
        if font.customParameters[PARAMETER] is not None:
            del font.customParameters[PARAMETER]
    else:
        font.customParameters[PARAMETER] = [list(row) for row in rows]
    if parameter_rows(font) != rows:
        raise RuntimeError("Glyphs 写入的色板与提交数据不一致。")


@authorized_write
def set_slot(layer, value):
    layer.setAttribute_forKey_(value, ATTRIBUTE)
    if layer.attributes[ATTRIBUTE] != value:
        raise RuntimeError("Glyphs 未保存颜色图层编号。")


def verify_commit(font, rows, mapped):
    current = parameter_rows(font)
    if current != rows or any(ref.layer.attributes[ATTRIBUTE] != value for ref, value in mapped):
        raise RuntimeError("提交核对发现色板或颜色图层编号不一致。")


@authorized_write
def _write_identity(font, raw):
    if raw is None:
        if font.userData[identity.KEY] is not None:
            del font.userData[identity.KEY]
    else:
        font.userData[identity.KEY] = raw
    if font.userData[identity.KEY] != raw:
        raise RuntimeError("Glyphs 未保存色板身份。")


def _reference_snapshot(font, rows):
    # Native deletion can leave layers referring to the former palette. Snapshot
    # their valid UInt16 indices without requiring an already-existing palette.
    # Deletion/reordering still enforce their own slot-range and usage checks.
    slots = FOREGROUND
    masters = {master.id for master in font.masters}
    snapshot = set()
    for glyph, layer, master, index, raw in _reference_records(font, slots, masters):
        if index is None:
            raise ValueError(f"存在未知颜色图层引用：{glyph.name} / {layer.layerId}: {raw!r}")
        snapshot.add((glyph.name, layer.layerId, master, index))
    return frozenset(snapshot)


def _register_undo(manager, font, restore):
    manager.registerUndoWithTarget_handler_(font, restore)


def palette_undo_manager(document):
    """Glyphs' document window selects the current native undo history."""
    if document is None:
        return None
    for controller in document.windowControllers():
        window = controller.window()
        if window and window.windowController() == controller:
            return window.undoManager()
    return document.undoManager()


@authorized_write
def _apply(font, before, after, mapped, raw_before, raw_after, legacy, undo_name, *, structural,
           history=None, expected_references=None):
    require_palette_write_boundary()
    if parameter_rows(font) != before or font.userData[identity.KEY] != raw_before or font.userData[LABELS] != legacy:
        raise ValueError("原生色板或名称记录已变化，请重新操作。")
    if any(ref.layer.attributes[ATTRIBUTE] != ref.index for ref, _ in mapped):
        raise ValueError("颜色图层引用已变化，请重新操作。")

    document = font.parent
    manager = history if history is not None else palette_undo_manager(document)
    if (structural or (document and undo_name)) and (not undo_name or not manager
                       or not manager.isUndoRegistrationEnabled()
                       or not manager.respondsToSelector_("registerUndoWithTarget:handler:")):
        raise RuntimeError("当前文档无法提供统一撤销，结构操作已停止。")
    references_before = _reference_snapshot(font, before) if structural else None
    if expected_references is not None and references_before != expected_references:
        raise ValueError("颜色图层引用已变化，撤销/重做未写入数据。")
    managers = {item for item in (manager, document.undoManager() if document else None) if item}
    managers.update(m for ref, _ in mapped if (m := ref.glyph.undoManager()))
    attempted = []
    references_after = None
    undo_ready = False

    def restore(target):
        if not undo_ready:
            return
        try:
            reverse = []
            for ref, index in mapped:
                glyph = target.glyphs[ref.glyph.name]
                layer = glyph.layers[ref.layer.layerId] if glyph else None
                if layer is None or layer.associatedMasterId != ref.layer.associatedMasterId:
                    raise ValueError("颜色图层已替换，无法恢复原引用。")
                reverse.append((Reference(glyph, layer, ref.master, index), ref.index))
            _apply(target, after, before, tuple(reverse), raw_after, raw_before, legacy, undo_name,
                   structural=structural, history=manager, expected_references=references_after)
        except Exception as error:
            print(f"字动力·彩字：{error}")

    def quiet():
        stack = ExitStack()
        try:
            for item in managers:
                if item.isUndoRegistrationEnabled():
                    item.disableUndoRegistration()
                    stack.callback(item.enableUndoRegistration)
            return stack
        except Exception:
            stack.close()
            raise

    font.disableUpdateInterface()
    try:
        try:
            with quiet():
                if before != after:
                    write_rows(font, after)
                for ref, new_index in mapped:
                    attempted.append(ref)
                    set_slot(ref.layer, new_index)
                if raw_before != raw_after:
                    _write_identity(font, raw_after)
                verify_commit(font, after, mapped)
                if (stored_snapshot(parameter_rows(font)) != stored_snapshot(after)
                        or font.userData[identity.KEY] != raw_after or font.userData[LABELS] != legacy):
                    raise RuntimeError("提交后色板或元数据回读失败。")
                if structural:
                    expected = set(references_before)
                    for ref, new_index in mapped:
                        key = (ref.glyph.name, ref.layer.layerId, ref.layer.associatedMasterId)
                        expected.remove(key + (ref.index,))
                        expected.add(key + (new_index,))
                    references_after = _reference_snapshot(font, after)
                    if references_after != expected:
                        raise RuntimeError("颜色图层全表回读失败。")
            if undo_name and manager:
                if not manager.isUndoRegistrationEnabled():
                    raise RuntimeError("撤销登记已禁用。")
                _register_undo(manager, font, restore)
                undo_ready = True
        except Exception as original:
            failures = []
            with quiet():
                for ref in reversed(attempted):
                    try:
                        set_slot(ref.layer, ref.index)
                    except Exception as error:
                        failures.append(error)
                try:
                    if parameter_rows(font) != before:
                        write_rows(font, before)
                    if font.userData[identity.KEY] != raw_before:
                        _write_identity(font, raw_before)
                    verify_commit(font, before, tuple((ref, ref.index) for ref in attempted))
                    if font.userData[identity.KEY] != raw_before or font.userData[LABELS] != legacy:
                        raise RuntimeError("回滚后元数据不一致。")
                    if structural and _reference_snapshot(font, before) != references_before:
                        raise RuntimeError("回滚后颜色图层引用不一致。")
                except Exception as error:
                    failures.append(error)
            if failures:
                raise RuntimeError(f"回滚验证失败，请检查字体。{failures[0]}") from original
            raise RuntimeError(f"操作失败，已恢复原数据。{original}") from original
        if undo_ready:
            try:
                manager.setActionName_(undo_name)
            except Exception as error:
                print(f"字动力·彩字：无法设置撤销标题。{error}")
    finally:
        font.enableUpdateInterface()
    if document and not document.isDocumentEdited():
        document.updateChangeCount_(NSChangeDone)
    if document:
        NSNotificationCenter.defaultCenter().postNotificationName_object_(PALETTE_COMMITTED, document)


def commit(font, before, after, mapped=(), *, labels=None, undo_name=None, palette_order=None,
           slot_order=None, reconcile=False):
    old_rows = () if empty_palettes(before) else stored_snapshot(before)
    new_rows = stored_snapshot(after)
    old_count, old_width = identity.shape(old_rows)
    new_count, new_width = identity.shape(new_rows)
    legacy, raw = font.userData[LABELS], font.userData[identity.KEY]
    lifecycle_replaced = _native_lifecycle_replaced(font, raw)
    if raw:
        state = identity.read(raw)
        issue = identity.status(state, old_rows, legacy)
        if issue or lifecycle_replaced:
            # Only an explicit designer confirmation can accept same-shape external edits.
            matching_shape = (old_count, old_width) == (len(state["palettes"]), len(state["slots"]))
            if not matching_shape or lifecycle_replaced:
                # External structural edits invalidate names/IDs, not the native
                # parameter's ability to accept writes. Rebase from the CURRENT
                # document rows, never reuse old slot names by position. Archive
                # the superseded identity; _apply keeps this in the same undo.
                previous = state
                state = identity.create(old_rows, legacy, tuple(("", ()) for _ in old_rows))
                state["revision"] = previous["revision"]
                state["archived"] = previous["archived"] + [dict(
                    reason="native-palette-structure-changed", revision=previous["revision"],
                    slots=previous["slots"], removed_palettes=previous["palettes"])]
            elif not (reconcile and state["legacy"] == identity.digest(legacy)):
                raise ValueError(issue)
    else:
        verified = palette_labels_from_snapshot(before, legacy)
        state = identity.create(old_rows, legacy, verified)
    if palette_order is None:
        palette_order = [i if i < old_count else None for i in range(new_count)]
    if slot_order is None:
        slot_order = [i if i < old_width else None for i in range(new_width)]
    structural = (palette_order != list(range(old_count)) or slot_order != list(range(old_width))
                  or bool(mapped))
    updated = identity.evolve(state, new_rows, legacy, palette_order, slot_order, labels)
    _apply(font, before, after, tuple(mapped), raw, identity.encode(updated), legacy, undo_name,
           structural=structural)


def safe_delete_slot(font, rows, index):
    after, mapped, _ = deletion_plan(font, rows, index)
    order = [i for i in range(len(rows[0])) if i != index]
    commit(font, rows, after, mapped, slot_order=order, undo_name="删除颜色")


def reorder_slots(font, rows, order):
    width = len(rows[0])
    if len(order) != width or sorted(order) != list(range(width)):
        raise ValueError("必须提供无重复的完整槽位排列。")
    if order == list(range(width)):
        return
    entries, unknown = references(font, width)
    if unknown:
        raise ValueError(f"存在未知颜色图层引用：{unknown[0]}")
    positions = {old: new for new, old in enumerate(order)}
    mapped = tuple((ref, positions[ref.index]) for ref in entries
                   if ref.index != FOREGROUND and positions[ref.index] != ref.index)
    after = tuple(tuple(row[i] for i in order) for row in rows)
    commit(font, rows, after, mapped, slot_order=order, undo_name="重排颜色")


def delete_backup(font, rows, index):
    if not 0 < index < len(rows):
        raise ValueError("仅可删除正在查看的备用色板。")
    order = [i for i in range(len(rows)) if i != index]
    commit(font, rows, tuple(rows[i] for i in order), palette_order=order, undo_name="删除备用色板")
