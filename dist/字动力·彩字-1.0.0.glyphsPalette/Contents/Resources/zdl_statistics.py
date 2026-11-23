"""Document-scoped, read-only statistics tracking. No font writes or undo routing.

GSGlyph.changeCount is observed; the document save token is not a statistics
revision (it also changes for non-statistical UI work). Count definitions remain
in the original GlyphIndex, and capacity accounting remains in zdl_capacity.
"""
from time import perf_counter
import weakref
from itertools import islice
import objc
from Foundation import NSObject
from GlyphsApp import Glyphs, DOCUMENTDIDCLOSE
from zdl_color_model import GlyphIndex
import zdl_capacity as capacity


class CZStatsCacheObserver(NSObject):
    def observeValueForKeyPath_ofObject_change_context_(self, key, obj, change, context):
        state = self.state_ref()
        if state is None or state.closed:
            return
        if str(key) == 'changeCount':
            state.dirty[id(obj)] = obj
        else:
            state.root_dirty = True
            if str(key) == 'glyphs':
                state.collection_dirty = True
        state.registry().wake()


class DocumentStatistics:
    def __init__(self, registry, font):
        self.registry = weakref.ref(registry)
        self.font, self.document = font, font.parent
        self.closed = False
        self.indexes = {}
        self.cancelled = set()
        self.dirty = {}
        self.watches = []
        self.fingerprints = {}
        self.capacity_records = {}
        self.capacity_seen = {}
        self.glyphs = list(font.glyphs)
        self.watch_position = 0
        self.root_dirty = False
        self.collection_dirty = False
        self.capacity = self.capacity_key = None
        self.content_epoch = 0
        self.scan_starts = 0
        self.partial_flushes = 0
        self.checked_glyphs = 0
        self.watch_failures = []
        self.observer = CZStatsCacheObserver.alloc().init()
        self.observer.state_ref = weakref.ref(self)
        for key in ('glyphs', 'fontMasters', 'instances', 'customParameters'):
            self.watch(font, key)
        self.export_key = capacity.export_signature(font)
        self.palette_key = None
        self.current_rows = self.palette()

    def watch(self, obj, key):
        try:
            obj.addObserver_forKeyPath_options_context_(self.observer, key, 0, None)
            self.watches.append((obj, key))
        except Exception as error:
            self.watch_failures.append((key, str(error)))

    def palette(self):
        return self.registry().rows(self.font)

    def fingerprint(self, glyph):
        rows = self.current_rows
        slots = len(rows[0]) if rows and all(len(r) == len(rows[0]) and all(c is not None for c in r) for r in rows) else 0
        return glyph.name, capacity._record(glyph, tuple(m.id for m in self.font.masters), slots)

    def watch_step(self, limit=96):
        end = min(len(self.glyphs), self.watch_position + limit)
        for glyph in self.glyphs[self.watch_position:end]:
            self.watch(glyph, 'changeCount')
            self.fingerprints[id(glyph)] = self.fingerprint(glyph)
        self.watch_position = end

    def forget_glyph_watches(self):
        keep = []
        for obj, key in self.watches:
            if key == 'changeCount':
                try: obj.removeObserver_forKeyPath_(self.observer, key)
                except Exception: pass
            else: keep.append((obj, key))
        self.watches = keep

    def close(self):
        self.closed = True
        for obj, key in self.watches:
            try: obj.removeObserver_forKeyPath_(self.observer, key)
            except Exception: pass
        self.watches.clear()
        self.dirty.clear()
        self.indexes.clear()
        self.fingerprints.clear()
        self.capacity_records = {}
        self.capacity_seen.clear()
        self.glyphs.clear()
        self.font = self.document = None

    def poll(self, selected=(), limit=96):
        capacity_changed = False
        stats_changed = False
        if len(self.font.glyphs) != len(self.glyphs) or self.collection_dirty:
            self.forget_glyph_watches()
            self.glyphs = list(self.font.glyphs)
            self.watch_position = 0
            self.fingerprints.clear()
            self.capacity_records = {}
            self.capacity_seen.clear()
            self.dirty.clear()
            self.indexes.clear()
            self.cancelled.clear()
            self.collection_dirty = False
            stats_changed = capacity_changed = True
        export_key = capacity.export_signature(self.font)
        palette_key = self.palette()
        self.current_rows = palette_key
        if export_key != self.export_key or palette_key != self.palette_key:
            if self.palette_key is not None:
                capacity_changed = True
            self.export_key, self.palette_key = export_key, palette_key
        self.root_dirty = False
        self.watch_step(limit)
        # Small, defensive current-selection check; never iterate the font to
        # discover a changed glyph. KVO covers non-selected model mutations.
        for glyph in tuple(selected)[:16]:
            if id(glyph) in self.fingerprints:
                self.dirty[id(glyph)] = glyph
        started = perf_counter()
        work = list(islice(self.dirty, limit))
        for key in work:
            glyph = self.dirty.pop(key)
            if glyph.parent != self.font:
                self.collection_dirty = True
                continue
            previous = self.fingerprints.get(key)
            current = self.fingerprint(glyph)
            self.checked_glyphs += 1
            if previous and previous[0] != current[0]:
                self.indexes.clear()
                self.cancelled.clear()
                stats_changed = capacity_changed = True
            for index in tuple(self.indexes.values()):
                old = index.items.get(glyph.name)
                index.update(glyph)
                stats_changed |= old != index.items.get(glyph.name)
            baseline = self.capacity_seen.get(current[0], self.capacity_records.get(current[0], previous[1] if previous else None))
            if baseline != current[1]:
                capacity_changed = True
                self.capacity_seen[current[0]] = current[1]
            self.fingerprints[key] = current
            if perf_counter() - started >= .004:
                break
        if capacity_changed:
            self.content_epoch += 1
            self.capacity = self.capacity_key = None
        if stats_changed:
            self.partial_flushes += 1
        return stats_changed, capacity_changed


class StatisticsCache:
    def __init__(self, owner, rows):
        self.owner = objc.WeakRef(owner)
        self.rows = rows
        self.documents = {}
        Glyphs.addCallback(self.document_closed, DOCUMENTDIDCLOSE)

    def get(self, font):
        if not font or not font.parent:
            return None
        document = font.parent
        if document not in self.documents:
            self.documents[document] = DocumentStatistics(self, font)
        return self.documents[document]

    def wake(self):
        owner = self.owner()
        if owner is not None:
            owner.queue_palette_stats()

    def document_closed(self, note):
        doc = note.object() if hasattr(note, 'object') else note
        self.close_document(doc)

    def close_document(self, document):
        state = self.documents.pop(document, None)
        if state:
            state.close()

    def close(self):
        Glyphs.removeCallback(self.document_closed)
        for document in tuple(self.documents):
            self.close_document(document)

    def index(self, font, masters, force=False):
        state = self.get(font)
        key = tuple(masters)
        if force:
            state.cancelled.discard(key)
            state.indexes.pop(key, None)
        if key in state.cancelled:
            return None, False
        created = key not in state.indexes
        if created:
            state.indexes[key] = GlyphIndex(font, key)
            state.scan_starts += 1
        return state.indexes[key], created
