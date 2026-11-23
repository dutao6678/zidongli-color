"""Apply and replay quick color edits using the native undo manager."""
from zdl_batch import quiet_undo, restore_change, write_change
from zdl_license import authorized_write


def _check_replay(glyph, changes, forward):
    for item in changes:
        if item.glyph != glyph:
            raise ValueError("撤销或重做目标已变化。")
        if item.created:
            current = glyph.layers[item.layer.layerId]
            expected = None if forward else item.layer
        else:
            current = item.layer.attributes["colorPalette"]
            expected = item.before if forward else item.after
        if current != expected:
            raise ValueError("颜色图层已变化，未撤销或重做。")


def _register(manager, glyph, changes, forward):
    @authorized_write
    def replay(target):
        try:
            _check_replay(target, changes, forward)
            completed = []
            operation = write_change if forward else restore_change
            inverse = restore_change if forward else write_change
            with quiet_undo(target):
                try:
                    for item in (changes if forward else reversed(changes)):
                        completed.append(item)
                        operation(item)
                except Exception:
                    for item in reversed(completed):
                        inverse(item)
                    raise
            _register(manager, target, changes, not forward)
        except Exception as error:
            print(f"字动力·彩字：{error}")

    manager.registerUndoWithTarget_handler_(glyph, invoke_replay(replay))


def invoke_replay(replay):
    # A replay can be rejected before a native write while leaving other
    # Glyphs undo targets alone. The existing undo group belongs to Glyphs.
    def callback(target):
        try:
            replay(target)
        except Exception as error:
            print(f"字动力·彩字：{error}")
    return callback


@authorized_write
def apply_changes(font, changes):
    groups = {}
    for change in changes:
        groups.setdefault(change.glyph.name, []).append(change)
    applied = []
    font.disableUpdateInterface()
    try:
        for group in groups.values():
            glyph = group[0].glyph
            manager = glyph.undoManager()
            if (not manager or not manager.isUndoRegistrationEnabled()
                    or not manager.respondsToSelector_("registerUndoWithTarget:handler:")):
                raise RuntimeError("当前字形无法登记授权保护的撤销。")
            glyph.beginUndo()
            try:
                with quiet_undo(glyph):
                    for change in group:
                        write_change(change)
                        applied.append(change)
                _register(manager, glyph, tuple(group), False)
            finally:
                glyph.endUndo()
    finally:
        font.enableUpdateInterface()
    return applied
