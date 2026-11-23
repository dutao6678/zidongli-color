"""Plan and apply native glyph color batches in main-thread slices."""
from zdl_license import authorized_write, restore_write
from collections import Counter
from contextlib import contextmanager
from zdl_native_core import balanced as native_balanced
from concurrent.futures import ThreadPoolExecutor, Future
import threading
_ASSIGNMENT_POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix="CZ4-color-compute")
from secrets import randbits
from time import perf_counter

from zdl_color_model import FOREGROUND, Change, color_index, create_color_layer, native_layers
from zdl_palette_management import ATTRIBUTE, set_slot

from zdl_batch_data import LAST_RUN, store_random_run
from zdl_capacity import Guard
from zdl_color_palette import read_palettes

def balanced_assignment(names, slots, seed):
    return native_balanced(names, slots, seed)


@contextmanager
def quiet_undo(owner):
    manager = owner.undoManager() if owner else None
    enabled = manager and manager.isUndoRegistrationEnabled()
    if enabled:
        manager.disableUndoRegistration()
    try:
        yield
    finally:
        if enabled:
            manager.enableUndoRegistration()


@authorized_write
def write_change(change):
    if change.created:
        change.layer.setAttribute_forKey_(change.after, ATTRIBUTE)
        change.glyph.layers.append(change.layer)
        if change.glyph.layers[change.layer.layerId] != change.layer:
            raise RuntimeError("无法验证新建颜色图层")
    else:
        set_slot(change.layer, change.after)


@authorized_write
def restore_change(change):
    if change.created:
        if not change.layer.layerId:
            return  # A failed append may never have assigned a native layer ID.
        if change.glyph.layers[change.layer.layerId] is not None:
            del change.glyph.layers[change.layer.layerId]
        if change.glyph.layers[change.layer.layerId] is not None:
            raise RuntimeError("无法移除本次创建的颜色图层")
    else:
        # Keep the original bridge object, even if the previously stored value was invalid.
        if change.before is None:
            change.layer.removeAttributeForKey_(ATTRIBUTE)
        else:
            change.layer.setAttribute_forKey_(change.before, ATTRIBUTE)
        if change.layer.attributes[ATTRIBUTE] != change.before:
            raise RuntimeError("无法恢复原始颜色编号")


class Batch:
    def __init__(self, font, masters, palette, slots, mode, *, targets=None, on_glyph=None, capacity_snapshot=None):
        self.capacity_snapshot = capacity_snapshot
        self.font, self.masters = font, tuple(masters)
        self.palette, self.slots, self.mode = palette, tuple(slots), mode
        self.colored_slots = frozenset((*self.slots, FOREGROUND))
        self.targets = font.glyphs if targets is None else targets
        self.total = len(self.targets)
        self.on_glyph = on_glyph
        self.stage = "预检查"
        self.plan = {}
        self.skips = Counter()
        self.position = self.processed = self.created = self.changed = 0
        self.pending = []
        self.applied = []
        self.seed = randbits(64)
        self.assignments = {}
        self.old_record = font.userData[LAST_RUN]
        self.record_attempted = False
        self.error = ""
        self.failures = []
        self.started = perf_counter()
        self.max_slice = 0.0

    def has_valid_color(self, layer):
        if layer is None:
            return False
        try:
            return color_index(layer) in self.colored_slots
        except (ValueError, TypeError, OverflowError):
            return False

    def preflight(self, glyph):
        if not glyph.export:
            self.skips["不导出"] += 1
            return
        targets = []
        for master_id in self.masters:
            source = glyph.layers[master_id]
            if source is None or not source.isMasterLayer or not len(source.shapes):
                self.skips["母版缺少有效轮廓"] += 1
                return
            layers = native_layers(glyph, master_id)
            if len(layers) > 1:
                self.skips["有多条颜色图层"] += 1
                return
            targets.append((source, layers[0] if layers else None))
        if self.mode == "random" and any(self.has_valid_color(layer) for _, layer in targets):
            self.skips["已有有效配色"] += 1
            return
        changes = []
        for source, layer in targets:
            if layer is not None:
                changes.append(Change(glyph, layer, layer.attributes[ATTRIBUTE], 0))
                continue
            try:
                changes.append(Change(glyph, create_color_layer(source, 0), None, 0, True))
            except ValueError:
                self.skips["母版轮廓无法建立颜色层"] += 1
                return
        self.plan[glyph.name] = changes

    def begin_writes(self):
        # Freeze only pure inputs. Small native requests fit a UI slice; avoid a needless run-loop hop.
        self._assignment_names = tuple(self.plan)
        if len(self._assignment_names) <= 1000:
            self._assignment_future = Future()
            try:
                self._assignment_future.set_result(balanced_assignment(self._assignment_names, self.slots, self.seed))
                self.accept_assignment()
            except Exception as error:
                self.abort(f"操作失败：{error}")
        else:
            # Worker never reads Glyphs objects. Actual writes and Undo stay on the main thread.
            self._assignment_future = _ASSIGNMENT_POOL.submit(balanced_assignment, self._assignment_names, self.slots, self.seed)
            self.stage = "分配颜色"

    def accept_assignment(self):
        if not self._assignment_future.done():
            return
        assignments = self._assignment_future.result()  # Errors propagate; NO Python fallback.
        if tuple(self.plan) != self._assignment_names or any(c.glyph.name != name for name, changes in self.plan.items() for c in changes):
            raise ValueError("计算期间字形身份已变化，未写入。")
        self.assignments = assignments
        for name, changes in self.plan.items():
            for change in changes:change.after = self.assignments[name]
        self.capacity_guard = Guard(self.font, [c for changes in self.plan.values() for c in changes], read_palettes(self.font), prior=self.capacity_snapshot)
        self.stage = "容量检查"

    def confirm_capacity(self):
        if self.stage != "待风险确认":
            raise ValueError("本次风险确认已失效，请重新操作。")
        self.capacity_guard.authorize(confirmed=True)
        self.capacity_checked_writes()

    def capacity_checked_writes(self):
        self.pending = iter(self.assignments)
        self.stage = "写入"

    @authorized_write
    def write_one(self, name):
        entry = self.plan[name]
        glyph = entry[0].glyph
        slot = self.assignments[name]
        pending = []
        for change in entry:
            change.after = slot
            if not change.created:
                current = change.layer.attributes[ATTRIBUTE]
                if current != change.before:
                    raise ValueError(f"{name} 的颜色引用已变化")
                if current == slot:
                    continue
            pending.append(change)
        if pending:
            with quiet_undo(glyph):
                for change in pending:
                    self.applied.append(change)
                    write_change(change)
                    self.created += change.created
                    self.changed += not change.created
            if self.on_glyph:
                self.on_glyph(glyph)
        self.processed += 1

    @authorized_write
    def finish(self):
        if self.assignments:
            self.record_attempted = True
            with quiet_undo(self.font.parent):
                store_random_run(self.font, self.seed, self.palette, self.slots, self.masters,
                                 self.mode, self.assignments)
        if self.applied or self.record_attempted:
            document = self.font.parent
            if document and not document.isDocumentEdited():
                from AppKit import NSChangeDone
                document.updateChangeCount_(NSChangeDone)
        self.stage = "完成"

    def abort(self, reason):
        self.error = reason
        self.stage = "回滚" if self.applied or self.record_attempted else "已停止"

    def rollback_one(self):
        if self.applied:
            change = self.applied.pop()
            try:
                with restore_write(), quiet_undo(change.glyph):
                    restore_change(change)
                if self.on_glyph:
                    self.on_glyph(change.glyph)
            except Exception as error:
                self.failures.append(str(error))
        else:
            if self.record_attempted:
                try:
                    with quiet_undo(self.font.parent):
                        self.font.userData[LAST_RUN] = self.old_record
                    if self.font.userData[LAST_RUN] != self.old_record:
                        raise RuntimeError("无法恢复此前的随机分配记录")
                except Exception as error:
                    self.failures.append(str(error))
            self.stage = "已停止"

    def step(self, budget=.006, cap=40):
        start = perf_counter()
        stage = self.stage
        writing = stage in ("写入", "回滚")
        try:
            if writing:
                self.font.disableUpdateInterface()
            for _ in range(cap):
                if stage == "预检查":
                    if self.position == self.total:
                        self.stage = "待确认"
                        break
                    self.preflight(self.targets[self.position])
                    self.position += 1
                elif stage == "分配颜色":
                    self.accept_assignment()
                    break
                elif stage == "容量检查":
                    if self.capacity_guard.step(64):
                        if self.capacity_guard.requires_confirmation:
                            self.stage = "待风险确认"
                        else:
                            self.capacity_guard.authorize()
                            self.capacity_checked_writes()
                        break
                elif stage == "写入":
                    target = next(self.pending, None)
                    if target is None:
                        self.finish()
                        break
                    self.write_one(target)
                elif stage == "回滚":
                    self.rollback_one()
                    if self.stage == "已停止":
                        break
                if self.stage != stage or perf_counter() - start >= budget:
                    break
        except Exception as error:
            self.abort(f"操作失败：{error}")
        finally:
            if writing:
                self.font.enableUpdateInterface()
            self.max_slice = max(self.max_slice, perf_counter() - start)
