"""Persistent batch data stored exclusively in the plug-in namespace."""
from zdl_license import authorized_write
from collections import Counter
from datetime import datetime, timezone

from AppKit import NSChangeDone

_LEGACY_PROTECTION_KEY = "com.zidongli.color.batch.lockedMasters.v1"
_CLEANUP_SESSION_KEY = "com.zidongli.color.batch.legacyMetadataChecked.v1"
LAST_RUN = "com.zidongli.color.batch.lastRandom.v1"


@authorized_write
def remove_legacy_protection(font):
    """Remove only the retired glyph metadata. Check once per open document."""
    document = font.parent
    if not document or font.tempData[_CLEANUP_SESSION_KEY]:
        return
    changed = False
    manager = document.undoManager()
    undo_enabled = manager and manager.isUndoRegistrationEnabled()
    if undo_enabled:
        manager.disableUndoRegistration()
    try:
        for glyph in font.glyphs:
            data = glyph.userData
            if _LEGACY_PROTECTION_KEY in data.keys():
                del data[_LEGACY_PROTECTION_KEY]
                changed = True
        font.tempData[_CLEANUP_SESSION_KEY] = True
    finally:
        if undo_enabled:
            manager.enableUndoRegistration()
        if changed and not document.isDocumentEdited():
            document.updateChangeCount_(NSChangeDone)


@authorized_write
def store_random_run(font, seed, palette, slots, masters, mode, assignments):
    font.userData[LAST_RUN] = {
        "seed": str(seed), "palette": palette, "slots": list(slots),
        "masters": list(masters), "mode": mode, "time": datetime.now(timezone.utc).isoformat(),
        "counts": {str(slot): count for slot, count in Counter(assignments.values()).items()},
        "assignments": assignments,
    }
    record = font.userData[LAST_RUN]
    if str(record["seed"]) != str(seed) or len(record["assignments"]) != len(assignments):
        raise RuntimeError("无法验证随机分配记录")
