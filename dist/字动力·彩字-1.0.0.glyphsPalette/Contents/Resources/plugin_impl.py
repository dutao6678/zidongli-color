"""Glyphs 3 native sidebar for 字动力·彩字."""
import sys
import json
from collections import Counter
from math import ceil
from pathlib import Path
from time import perf_counter

import objc
from AppKit import (
    NSBezierPath, NSBezelStyleFlexiblePush, NSButton, NSColor, NSFont, NSGraphicsContext,
    NSMakeRect, NSOpenPanel, NSSavePanel, NSBox, NSBoxCustom, NSNoBorder, NSWindowAbove, NSApplication, NSPopUpButton, NSScrollView, NSScrollerStyleLegacy,
    NSTrackingArea, NSTrackingMouseEnteredAndExited, NSTrackingActiveInKeyWindow,
    NSTrackingInVisibleRect,
    NSTextField, NSView, NSViewHeightSizable, NSViewWidthSizable, NSViewMinXMargin, NSViewMaxXMargin, NSViewMinYMargin, NSAlert, NSAlertFirstButtonReturn, NSAlertSecondButtonReturn, NSAlertThirdButtonReturn, NSMenu, NSMenuItem, NSEvent,
    NSWindowWillCloseNotification, NSWindowDidResignKeyNotification, NSWindowDidBecomeKeyNotification,
    NSWindowWillBeginSheetNotification, NSWindowDidEndSheetNotification, NSApplicationWillTerminateNotification, NSPanel, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSBackingStoreBuffered,
    NSProgressIndicator, NSModalResponseOK, NSAppearanceNameAqua, NSAppearanceNameDarkAqua,
    NSFontAttributeName, NSForegroundColorAttributeName, NSTextAlignmentCenter, NSLineBreakByCharWrapping,
)
from Foundation import NSAttributedString, NSLog, NSNotificationCenter, NSRunLoop, NSRunLoopCommonModes, NSThread, NSTimer, NSUndoManagerDidUndoChangeNotification, NSUndoManagerDidRedoChangeNotification, NSUserDefaults, NSUserDefaultsDidChangeNotification
from PyObjCTools.AppHelper import callAfter
from GlyphsApp import Glyphs, UPDATEINTERFACE
from GlyphsApp.plugins import PalettePlugin

# Python's embedded import can otherwise write unsealed cache files inside the bundle.
_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    from zdl_color_model import (
        FOREGROUND, GlyphIndex, color_index, color_label, native_layers, palette_problem,
        plan_changes, read_palettes, tooltip,
    )
    from zdl_license import STORE, require_write
    from zdl_license_ui import LicenseWindow
    from zdl_statistics import StatisticsCache
    from zdl_color_undo import apply_changes
    from zdl_color_palette import normalize_color, stored_rgba
    from zdl_native_color import font_info_sheet, picker_rgba, slot_request, resolve_request
    from zdl_product_ui import create_footer, footer_layout, product_windows, update_footer_license
    from zdl_palette_identity import KEY as IDENTITY_KEY
    import zdl_capacity as capacity
    from zdl_batch import Batch
    from zdl_batch_data import remove_legacy_protection
    from zdl_palette_import import Swatch, export_palettes, read_ase, read_gpl, safe_filename
    from zdl_palette_management import (
        LABELS, add_color_slot, commit, delete_backup, deletion_plan, edited_slot, identity_labels,
        reorder_slots, safe_delete_slot, palette_undo_manager, PALETTE_COMMITTED,
        palette_snapshot, parameter_rows, plan_palette, references, validate_palette_references,
    )
finally:
    sys.dont_write_bytecode = _write_bytecode
    del _write_bytecode

PAGE = 48
USER_PRESETS = "com.zidongli.color.userPresets.v1"
BATCH_CONFIRM_THRESHOLD = 100
INSET = 8
GAP = 5
SECTION_GAP = 12
CONTROL_HEIGHT = 29
TITLE_SIZE = 12.5
CONTROL_SIZE = 12
TEXT_SIZE = 11.5
STATS_FILTER_TITLE = "查看颜色对应"
STATS_ROWS = ("TrueType 余量", "总字形", "已着色", "未着色", "缺层", "异常")
STATS_ROW_HEIGHT = 25
HINT_SIZE = 11
SWATCH_LABEL_SIZE = 11.5
PAGE_BUTTON_WIDTH = 62
MIN_SWATCH_WIDTH = 37
SWATCH_HEIGHT = 36
CHIP_Y = 15.5
SWATCH_GAP = 5
SECTION_TITLES = ("色彩套系", "快速着色", "全字库处理", "统计 / 概况")
BATCH_ACTIONS = (
    ("random", "均衡随机", "在处理范围内均衡分配颜色，仅处理尚未着色的字形"),
    ("selected", "选中随机", "仅重新分配 Glyphs 字格中选中的字形"),
    ("all", "全部随机", "重新分配处理范围内全部有效字形，包含已着色字形"),
)


class CZStats7ZDLColorSwatchButton(NSButton):
    def mouseDown_(self, event):
        # Every left click colors; editing is exclusively in the context menu.
        self.click_count = 1
        objc.super(CZStats7ZDLColorSwatchButton, self).mouseDown_(event)

    def menuForEvent_(self, event):
        return self.target().swatch_menu(self.tag())

    def mouseEntered_(self, event):
        self.hovered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self.hovered = False
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirty_rect):
        rgba = self.rgba
        adding = self.tag() < 0
        foreground = self.tag() == FOREGROUND
        selected = self.selected_slot
        hovered = self.isEnabled() and (self.hovered or self.isHighlighted())
        width = self.bounds().size.width
        chip_rect = NSMakeRect(1.5, CHIP_Y, max(1, width - 3), 17)
        chip = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(chip_rect, 8.5, 8.5)
        NSColor.windowBackgroundColor().setFill()
        chip.fill()
        if rgba is not None and rgba[3] < 255:
            NSGraphicsContext.saveGraphicsState()
            try:
                chip.addClip()
                NSColor.separatorColor().setFill()
                for x in range(2, int(width - 1), 4):
                    for y in range(16, 33, 4):
                        if ((x - 2) // 4 + (y - 16) // 4) % 2:
                            NSBezierPath.fillRect_(NSMakeRect(x, y, 4, 4))
            finally:
                NSGraphicsContext.restoreGraphicsState()
        if rgba is not None:
            NSColor.colorWithSRGBRed_green_blue_alpha_(*(v / 255 for v in rgba)).setFill()
            chip.fill()
        elif not (adding or foreground):
            NSColor.secondaryLabelColor().setStroke()
            NSBezierPath.strokeLineFromPoint_toPoint_((width / 2 - 4, CHIP_Y + 8.5), (width / 2 + 4, CHIP_Y + 8.5))
        if selected or hovered:
            stroke = NSColor.controlAccentColor() if selected else NSColor.labelColor()
            stroke.setStroke()
            chip.setLineWidth_(2 if selected else 1.5)
        else:
            (NSColor.secondaryLabelColor() if adding or foreground else NSColor.separatorColor()).setStroke()
            chip.setLineWidth_(1)
        chip.stroke()
        if selected and hovered:
            NSColor.controlAccentColor().colorWithAlphaComponent_(0.16).setFill()
            chip.fill()
        if adding:
            x = chip_rect.origin.x + chip_rect.size.width / 2
            y = chip_rect.origin.y + chip_rect.size.height / 2
            arm, half_weight = 3.75, 0.625
            plus = NSBezierPath.bezierPath()
            plus.appendBezierPathWithRect_(NSMakeRect(x - arm, y - half_weight, 2 * arm, 2 * half_weight))
            plus.appendBezierPathWithRect_(NSMakeRect(x - half_weight, y - arm, 2 * half_weight, 2 * arm))
            NSColor.labelColor().setFill()
            plus.fill()
            return
        color = NSColor.controlAccentColor() if selected else NSColor.labelColor()
        label = NSAttributedString.alloc().initWithString_attributes_("*" if foreground else str(self.tag()), {
            NSFontAttributeName: NSFont.systemFontOfSize_(14 if foreground else SWATCH_LABEL_SIZE),
            NSForegroundColorAttributeName: color,
        })
        label.drawAtPoint_(((width - label.size().width) / 2, 0))



class CZStats7ZDLLayoutButton(NSButton):
    def drawRect_(self, dirty_rect):
        rect = self.bounds()
        width, height = rect.size
        active = self.isEnabled()
        fill = NSColor.labelColor().colorWithAlphaComponent_(0.16 if active else 0.08)
        if active and self.isHighlighted():
            fill = NSColor.labelColor().colorWithAlphaComponent_(0.27)
        fill.setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 5, 5).fill()
        disclosure = getattr(self, "section_expanded", None)
        color = NSColor.labelColor() if active else NSColor.disabledControlTextColor()
        font = (NSFont.boldSystemFontOfSize_(TITLE_SIZE) if disclosure is not None
                else NSFont.systemFontOfSize_(CONTROL_SIZE))
        label = NSAttributedString.alloc().initWithString_attributes_(self.title(), {
            NSFontAttributeName: font, NSForegroundColorAttributeName: color,
        })
        label.drawAtPoint_(((width - label.size().width) / 2, (height - label.size().height) / 2))
        if disclosure is not None:
            color.setFill()
            for x in (13, width - 13):
                center = height / 2
                triangle = NSBezierPath.bezierPath()
                if disclosure:
                    direction = 1 if self.isFlipped() else -1
                    points = ((x - 3.5, center - 2 * direction), (x + 3.5, center - 2 * direction),
                              (x, center + 3 * direction))
                else:
                    points = ((x - 2, center - 3.5), (x - 2, center + 3.5), (x + 3, center))
                triangle.moveToPoint_(points[0])
                triangle.lineToPoint_(points[1])
                triangle.lineToPoint_(points[2])
                triangle.closePath()
                triangle.fill()


class CZStats7ZDLLayoutPopup(NSPopUpButton):
    def drawRect_(self, dirty_rect):
        rect = self.bounds()
        width, height = rect.size
        enabled = self.isEnabled()
        NSColor.labelColor().colorWithAlphaComponent_(0.16 if enabled else 0.08).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 5, 5).fill()
        arrow_width = 18
        x = width - 12
        y = height / 2
        arrow = NSMakeRect(x - arrow_width / 2, y - 11, arrow_width, 22)
        (NSColor.controlAccentColor() if enabled else NSColor.tertiaryLabelColor()).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(arrow, 4, 4).fill()
        NSColor.whiteColor().setStroke()
        path = NSBezierPath.bezierPath()
        path.setLineWidth_(1.4)
        for direction in (-1, 1):
            path.moveToPoint_((x - 3.5, y + direction * 3))
            path.lineToPoint_((x, y + direction * 6.5))
            path.lineToPoint_((x + 3.5, y + direction * 3))
        path.stroke()


class CZStats7ZDLStatsTable(NSView):
    def isFlipped(self):
        return True

    def drawRect_(self, dirty_rect):
        width, height = self.bounds().size
        NSColor.labelColor().colorWithAlphaComponent_(0.28).setStroke()
        NSBezierPath.strokeRect_(NSMakeRect(0.5, 0.5, width - 1, height - 1))
        split = self.column_width
        NSBezierPath.strokeLineFromPoint_toPoint_((split, 0), (split, height))
        for index in range(1, len(STATS_ROWS)):
            y = index * STATS_ROW_HEIGHT + 0.5
            NSBezierPath.strokeLineFromPoint_toPoint_((0, y), (width, y))


class CZStats7ZDLColorFlippedView(NSView):
    def isFlipped(self):
        return True


class CZStats7ZDLStatsPopupLabel(NSTextField):
    def hitTest_(self, point):
        return None


class CZStats7ZDLColorFormView(NSScrollView):
    def resizeSubviewsWithOldSize_(self, old_size):
        objc.super(CZStats7ZDLColorFormView, self).resizeSubviewsWithOldSize_(old_size)
        layout = getattr(self, "layout_callback", None)
        if layout:
            layout()


class CZStats7IntegratedColorGlyphsPalette(PalettePlugin):
    @objc.python_method
    def settings(self):
        self.name = "字动力·彩字"
        self.min = 230
        self.max = 500
        self.dialog = CZStats7ZDLColorFormView.alloc().initWithFrame_(NSMakeRect(0, 0, 250, 305))
        self.dialog.setHasVerticalScroller_(True)
        self.dialog.setScrollerStyle_(NSScrollerStyleLegacy)
        self.dialog.setAutohidesScrollers_(False)
        self.dialog.setDrawsBackground_(False)
        self.dialog.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.body = CZStats7ZDLColorFlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 250, 305))
        self.dialog.setDocumentView_(self.body)
        self._active_font = None
        self._palettes = ()
        self._palette_labels = ()
        self._palette_metadata = None
        self._preset_window = None
        self._palette_error = ""
        self._view_index = 0
        self._page = 0
        self._selection_count = 0
        self._color_edit = None
        self._pending_palette_operations = []
        self._palette_operation_timer = None
        self._sync_binding = None
        self._observed_undo_managers = set()
        self._undo_index_dirty = False
        self._sync_document_closed = False
        self._sync_draft = None
        self._sync_timer = None
        self._stats_timer = None
        self._add_editor_timer = None
        self._add_editor_request = None
        self._next_stats_paint = 0.0
        self._color_edit_identity = None
        self._identity_issue = ""
        self._index = None
        self._index_timer = None
        self._scan_perf = None
        self._index_revision = 0
        self._stats_key = None
        self._swatch_key = None
        self._foreground_preferences = None
        self._laying_out = False
        self.expanded = [True, True, False, False]
        self.sections = [self.button(title, "toggleSection:", index) for index, title in enumerate(SECTION_TITLES)]
        self.dividers = []
        for _ in self.sections[1:]:
            line = NSBox.alloc().init()
            line.setBoxType_(NSBoxCustom)
            line.setBorderType_(NSNoBorder)
            line.setFillColor_(NSColor.labelColor().colorWithAlphaComponent_(0.14))
            self.body.addSubview_(line)
            self.dividers.append(line)
        self.palette = self.popup("switchPalette:")
        self.palette.cell().setUsesItemFromMenu_(False)
        self.palette.cell().setMenuItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, ""))
        self.palette_title = CZStats7ZDLStatsPopupLabel.wrappingLabelWithString_("")
        self.palette_title.setFont_(NSFont.systemFontOfSize_(CONTROL_SIZE))
        self.palette_title.cell().setLineBreakMode_(NSLineBreakByCharWrapping)
        self.palette_title.setAccessibilityElement_(False)
        self.palette.addSubview_(self.palette_title)
        self.refresh_button = self.button("刷新", "refreshPalette:")
        self.presets_button = self.button("预置库", "addPreset:")
        self.refresh_button.setToolTip_("重新读取当前字体的原生色板")
        self.import_button = self.button("导入套系", "importPalette:")
        self.export_button = self.button("导出套系", "exportPalette:")
        self.palette_note = self.label("正在读取原生色板", HINT_SIZE)
        self.swatches = []
        self.previous = self.button("上一页", "changePage:", -1)
        self.following = self.button("下一页", "changePage:", 1)
        self.page_label = self.label("")
        self.page_label.setAlignment_(NSTextAlignmentCenter)
        self.status = self.label("")
        self.status.setHidden_(True)
        self._batch = None
        self._batch_timer = None
        self._batch_result = ""
        self._capacity = self._capacity_scan = self._capacity_timer = None
        self._capacity_font = None
        self._capacity_key = None
        self._capacity_epoch = 0
        self._quick_alert = self._quick_alert_parent = None
        self._quick_guard = self._quick_timer = None
        self._batch_scope_all = False
        self.batch_scan = self.button("母版范围", "batchScope:")
        self.batch_scan.setToolTip_("选择当前母版或全部母版")
        self.batch_actions = []
        for tag, (_, title, full) in enumerate(BATCH_ACTIONS):
            button = self.button(title, "batchAction:", tag)
            button.setToolTip_(full)
            self.batch_actions.append(button)
        self.batch_result = self.label("", HINT_SIZE)
        self.batch_result.setTextColor_(NSColor.secondaryLabelColor())
        self.stats_note = self.label("", HINT_SIZE)
        self.stats_table = CZStats7ZDLStatsTable.alloc().init()
        self.stats_table.column_width = 88
        self.body.addSubview_(self.stats_table)
        self.stats_cells = []
        for name in STATS_ROWS:
            label = NSTextField.labelWithString_(name)
            value = NSTextField.labelWithString_("—")
            for cell in (label, value):
                cell.setFont_(NSFont.systemFontOfSize_(TEXT_SIZE))
                self.stats_table.addSubview_(cell)
            self.stats_cells.append((label, value))
        self.stats_refresh = self.button("重新统计", "refreshStats:")
        self.stats_cancel = self.button("取消", "cancelStats:")
        self.stats_palette = self.popup("filterColor:")
        self.stats_palette.cell().setUsesItemFromMenu_(False)
        self.stats_palette.cell().setMenuItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, ""))
        self.stats_palette.setAccessibilityLabel_(STATS_FILTER_TITLE)
        self.stats_filter_label = CZStats7ZDLStatsPopupLabel.wrappingLabelWithString_(STATS_FILTER_TITLE)
        self.stats_filter_label.setFont_(NSFont.systemFontOfSize_(TEXT_SIZE))
        self.stats_filter_label.setAlignment_(NSTextAlignmentCenter)
        self.stats_filter_label.cell().setLineBreakMode_(NSLineBreakByCharWrapping)
        self.stats_filter_label.setAccessibilityElement_(False)
        self.stats_palette.addSubview_(self.stats_filter_label)
        self.product_footer = create_footer(self.body, self)
        self._license_timer = None
        self._license_window = LicenseWindow()
        self._license_view = None
        # Use a weak callback to avoid retaining the plugin through its view.
        weak = objc.WeakRef(self)
        self.dialog.layout_callback = lambda: weak() and weak().arrange()
        self._capacity_registry = capacity.Registry()
        self._statistics_cache = StatisticsCache(self, read_palettes)
        self._stats_capacity_ticket = None
        self.refresh_state()

    @objc.python_method
    def start(self):
        Glyphs.addCallback(self.schedule_refresh, UPDATEINTERFACE)
        for name in (NSUndoManagerDidUndoChangeNotification, NSUndoManagerDidRedoChangeNotification):
            NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(self, "capacityUndoChanged:", name, None)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "syncWindowFocused:", NSWindowDidBecomeKeyNotification, None
        )
        self.bind_palette_sync()
        weak = objc.WeakRef(self)

        def refresh_license(timer):
            target = weak()
            if target is None:
                timer.invalidate()
            else:
                target.licenseTick_(timer)

        self._license_timer = NSTimer.timerWithTimeInterval_repeats_block_(1.0, True, refresh_license)
        NSRunLoop.mainRunLoop().addTimer_forMode_(self._license_timer, NSRunLoopCommonModes)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "foregroundDefaultsChanged:", NSUserDefaultsDidChangeNotification, None
        )

    @objc.python_method
    def __del__(self):
        try:
            if hasattr(self, "_capacity_registry"):self._capacity_registry.close()
            if hasattr(self, "_statistics_cache"):
                self._statistics_cache.close()
            if self._license_timer:
                self._license_timer.invalidate()
            self.stop_capacity()
            self.cancel_quick()
            for name in (NSUndoManagerDidUndoChangeNotification, NSUndoManagerDidRedoChangeNotification):
                NSNotificationCenter.defaultCenter().removeObserver_name_object_(self, name, None)
            self.cancel_palette_operations()
            self.stop_palette_sync()
            NSNotificationCenter.defaultCenter().removeObserver_name_object_(
                self, NSUserDefaultsDidChangeNotification, None
            )
            Glyphs.removeCallback(self.schedule_refresh)
        except (AttributeError, TypeError):
            pass

    @objc.python_method
    def __file__(self):
        return __file__

    @objc.python_method
    def button(self, title, action=None, tag=0):
        view = CZStats7ZDLLayoutButton.buttonWithTitle_target_action_(title, self if action else None, action)
        view.setRefusesFirstResponder_(True)
        view.setFont_(NSFont.systemFontOfSize_(CONTROL_SIZE))
        view.setTag_(tag)
        self.body.addSubview_(view)
        return view

    @objc.python_method
    def label(self, text, size=TEXT_SIZE):
        view = NSTextField.wrappingLabelWithString_(text)
        view.setFont_(NSFont.systemFontOfSize_(size))
        view.setTextColor_(NSColor.labelColor())
        view.setMaximumNumberOfLines_(0)
        self.body.addSubview_(view)
        return view

    @objc.python_method
    def popup(self, action):
        view = CZStats7ZDLLayoutPopup.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 1, 1), False)
        view.setTarget_(self)
        view.setAction_(action)
        view.setBezelStyle_(NSBezelStyleFlexiblePush)
        view.setFont_(NSFont.systemFontOfSize_(CONTROL_SIZE))
        self.body.addSubview_(view)
        return view

    @objc.python_method
    def context(self):
        controller = self.windowController()
        document = controller.document() if controller else None
        return controller, document.font if document else None

    @objc.python_method
    def common_timer(self, seconds, selector):
        timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            seconds, self, selector, None, False)
        NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
        return timer

    @objc.python_method
    def schedule_refresh(self, sender):
        guard=self._quick_guard
        if guard is not None:
            _,current=self.context()
            if current!=guard.font or tuple(current.selectedLayers or ())!=getattr(self,'_quick_selection',()):self.cancel_quick()
        if self._sync_document_closed or not self.dialog.window():
            return
        if not self._sync_binding:
            self.bind_palette_sync()
        if self._sync_draft:
            self.queue_palette_sync()
        elif self._sync_timer is None:
            self._sync_timer = self.common_timer(.18, "paletteSyncTick:")

    def foregroundDefaultsChanged_(self, notification):
        self.schedule_refresh(notification)

    @objc.python_method
    def foreground_rgba(self):
        controller, _ = self.context()
        window = self.dialog.window()
        if not controller or not window:
            return None
        appearance = window.effectiveAppearance()
        dark = appearance.bestMatchFromAppearancesWithNames_(
            [NSAppearanceNameAqua, NSAppearanceNameDarkAqua]
        ) == NSAppearanceNameDarkAqua
        keys = ("GSColorForeground", "GSColorForegroundDark")
        try:
            native_colors = tuple(Glyphs.colorDefaults[key] for key in keys)
            edit = controller.activeEditViewController()
            graphic = edit.graphicView() if edit else None
            if graphic and graphic.respondsToSelector_("foregroundColor"):
                if native_colors != self._foreground_preferences and graphic.respondsToSelector_("setupColors"):
                    graphic.setupColors()
                self._foreground_preferences = native_colors
                current = graphic.foregroundColor()
                if current is not None:
                    return normalize_color(current)

            # Before an edit tab exists, use the native appearance preference;
            # for inherited defaults, resolve AppKit's dynamic text color in this window.
            rgba = []
            appearance.performAsCurrentDrawingAppearance_(
                lambda: rgba.append(normalize_color(native_colors[dark] or NSColor.textColor()))
            )
            return rgba[0]
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return None

    @objc.python_method
    def palette_row(self):
        return self._palettes[self._view_index] if self._palettes else ()

    @objc.python_method
    def palette_sync_log(self, event):
        NSLog("ZDLPaletteSync prototype event=%@ doc=%@", event, str(self._sync_binding[1].fileURL().lastPathComponent())
              if self._sync_binding and self._sync_binding[1].fileURL() else "unbound-or-unsaved")

    @objc.python_method
    def stop_palette_sync(self):
        self.unbind_palette_sync()
        NSNotificationCenter.defaultCenter().removeObserver_name_object_(
            self, NSWindowDidBecomeKeyNotification, None)

    @objc.python_method
    def unbind_palette_sync(self):
        center = NSNotificationCenter.defaultCenter()
        if self._sync_timer:
            self._sync_timer.invalidate()
            self._sync_timer = None
        if self._sync_binding:
            _, _, _, observers = self._sync_binding
            self.palette_sync_log("unbind")
            for name, obj, _ in observers:
                center.removeObserver_name_object_(self, name, obj)
        self._sync_binding = None
        self._sync_draft = None
        self._undo_index_dirty = False
        if self._stats_timer:
            self._stats_timer.invalidate()
            self._stats_timer = None
        self.cancel_added_editor()
        self.observe_undo_managers(None)

    @objc.python_method
    def observe_undo_managers(self, document):
        managers = ({document.undoManager(), palette_undo_manager(document)} - {None}) if document else set()
        center = NSNotificationCenter.defaultCenter()
        for name in (NSUndoManagerDidUndoChangeNotification, NSUndoManagerDidRedoChangeNotification):
            for manager in self._observed_undo_managers - managers:
                center.removeObserver_name_object_(self, name, manager)
            for manager in managers - self._observed_undo_managers:
                center.addObserver_selector_name_object_(self, "syncUndoChanged:", name, manager)
        self._observed_undo_managers = managers

    @objc.python_method
    def bind_palette_sync(self, window=None):
        controller, font = self.context()
        document = controller.document() if controller else None
        if not document or not font:
            self.unbind_palette_sync()
            return
        if window is None and self._sync_binding and self._sync_binding[:2] == (font, document):
            window = self._sync_binding[2]
        if self._sync_binding and self._sync_binding[:3] == (font, document, window):
            self.observe_undo_managers(document)
            return
        same_document = self._sync_binding and self._sync_binding[:2] == (font, document)
        pending, index_dirty = self._sync_draft, self._undo_index_dirty
        self.unbind_palette_sync()
        observers = [(NSWindowWillCloseNotification, controller.window(), "syncDocumentClosed:"),
                     (PALETTE_COMMITTED, document, "syncPaletteCommitted:")]
        if window:
            observers.extend([(NSWindowWillBeginSheetNotification, window, "syncSheetBegan:"),
                              (NSWindowDidEndSheetNotification, window, "syncSheetEnded:")])
        self._sync_binding = (font, document, window, observers)
        center = NSNotificationCenter.defaultCenter()
        for name, obj, callback in observers:
            if obj is not None:
                center.addObserver_selector_name_object_(self, callback, name, obj)
        self.observe_undo_managers(document)
        self.palette_sync_log("bind")
        if same_document and pending:
            self._sync_draft = pending
            self._undo_index_dirty = index_dirty
            self.queue_palette_sync()

    def syncWindowFocused_(self, note):
        controller, font = self.context()
        if not controller or not font:
            return
        window = note.object()
        if window == controller.window():
            self.bind_palette_sync()
        elif window.identifier() == "GSFontInfoWindow" and Glyphs.font == font:
            self.bind_focused_font_info(controller, window)

    @objc.python_method
    def bind_focused_font_info(self, controller, window):
        # Glyphs 3532 exposes the documented getter without the "loaded" variant.
        # Query it only after Font Info is visible, since it may create a window.
        getter = getattr(controller, "fontInfoWindowController", None)
        info = getter() if getter else None
        if info and info.window() == window:
            self.bind_palette_sync(window)

    def syncDocumentClosed_(self, note):
        if self._active_font and self._active_font.parent:
            self._statistics_cache.close_document(self._active_font.parent)
        self.stop_capacity()
        self.cancel_quick()
        self._sync_document_closed = True
        self.cancel_palette_operations()
        self.end_color_edit("document-close")
        self.stop_index()
        self._index = None
        self.stop_palette_sync()

    def syncSheetBegan_(self, note):
        if self._sync_binding and note.object() == self._sync_binding[2]:
            self.end_color_edit("host-sheet-begin")
            self.palette_sync_log("sheet-begin")

    def syncSheetEnded_(self, note):
        if self._sync_binding and note.object() == self._sync_binding[2]:
            self.palette_sync_log("sheet-end")
            self.queue_palette_sync()
            self.schedule_palette_operations()

    def syncUndoChanged_(self, note):
        if note.object() not in self._observed_undo_managers:
            return
        self.invalidate_capacity()
        self.palette_sync_log("undo-or-redo")
        self._undo_index_dirty |= self._index is not None
        self.queue_palette_sync()

    def syncPaletteCommitted_(self, note):
        self.invalidate_capacity()
        if self._sync_binding and note.object() == self._sync_binding[1]:
            self.queue_palette_sync()

    @objc.python_method
    def queue_palette_sync(self):
        if self._sync_document_closed:
            return
        was_urgent = bool(self._sync_draft)
        self._sync_draft = True
        if not self._sync_binding or self._batch is not None or not self.dialog.window():
            return
        if self._sync_timer is not None:
            if was_urgent:
                return
            self._sync_timer.invalidate()
        self._sync_timer = self.common_timer(0, "paletteSyncTick:")

    def paletteSyncTick_(self, timer):
        if timer != self._sync_timer:
            return
        self._sync_timer = None
        if self._sync_document_closed or not self.dialog.window() or self._batch is not None:
            return
        controller, active = self.context()
        if not controller or not active:
            return
        if not self._sync_binding or self._sync_binding[:2] != (active, controller.document()):
            self.bind_palette_sync()
        urgent = bool(self._sync_draft)
        self._sync_draft = None
        self.refresh_state(sync_only=urgent, defer_stats=urgent)

    @objc.python_method
    def queue_palette_stats(self):
        if self._stats_timer is None and not self._sync_document_closed and self.dialog.window():
            self._stats_timer = self.common_timer(.04, "paletteStatsTick:")

    def paletteStatsTick_(self, timer):
        if timer != self._stats_timer:return
        self._stats_timer = None
        if self._sync_document_closed or not self.dialog.window() or self._batch is not None:return
        _, font = self.context()
        if font != self._active_font or self._sync_draft:return
        self._undo_index_dirty = False
        self.statistics_poll(font, tuple(font.selectedLayers or ()) if font else ())
        if font and self.expanded[3] and self._index is None:
            self.start_index()
        self.update_stats()
        self.arrange()

    @objc.python_method
    def refresh_state(self, *, sync_only=False, swatch_page=None, defer_stats=False):
        controller, font = self.context()
        if self._batch is not None:
            return
        if self._sync_binding and controller:
            self.observe_undo_managers(controller.document())
        font_changed = font != self._active_font
        if font_changed:
            previous = self._statistics_cache.documents.get(self._active_font.parent) if self._active_font and self._active_font.parent else None
            if previous is not None:
                previous.capacity, previous.capacity_key = self._capacity, self._capacity_key
            self._sync_document_closed = False
            self.stop_capacity()
            self.cancel_quick()
            self._capacity = None
            self._capacity_font = font
            self.end_color_edit()
            self._active_font = font
            self._batch_result = ""
            self.batch_result.setStringValue_("")
            self._view_index = self._page = 0
            self.status.setStringValue_("")
            self.stop_index()
            self._index = None
            state = self._statistics_cache.get(font)
            if state is not None:
                self._capacity, self._capacity_key = state.capacity, state.capacity_key
        licensed = self.refresh_license_ui()
        if font and not sync_only and licensed:
            try:
                remove_legacy_protection(font)
            except Exception as error:
                self.status.setStringValue_(f"旧版批量记录清理失败：{error}")
        unsupported = False
        try:
            palettes = read_palettes(font)
            problem = palette_problem(palettes) if font else "请先打开字体。"
        except (TypeError, ValueError, AttributeError) as error:
            palettes, problem = (), str(error)
            unsupported = True
        metadata = (font.userData[LABELS], font.userData[IDENTITY_KEY]) if font else None
        names, issue = identity_labels(font, parameter_rows(font)) if font and not unsupported else ((), "")
        self._identity_issue = issue
        if font_changed or (palettes, problem, metadata, names) != (
                self._palettes, self._palette_error, self._palette_metadata, self._palette_labels):
            self._palette_metadata = metadata
            self._palette_labels = names
            same_shape = tuple(map(len, palettes)) == tuple(map(len, self._palettes))
            self._palettes, self._palette_error = palettes, problem
            self._view_index = min(self._view_index, max(0, len(palettes) - 1))
            if not same_shape:
                self._page = 0
            self.palette.removeAllItems()
            empty_title = "不支持的色板结构" if unsupported else "无原生色板"
            titles = [f"{name} · {i}" if name else f"Palette {i}" for i, (name, _) in enumerate(self._palette_labels)]
            self.palette.addItemsWithTitles_(titles or [empty_title])
            self.palette.selectItemAtIndex_(self._view_index)
            self._swatch_key = None
        self.ensure_capacity(font)
        selected_title = self.palette.itemAtIndex_(self._view_index).title()
        if self.palette_title.stringValue() != selected_title:
            self.palette_title.setStringValue_(selected_title)
            self.palette.setAccessibilityLabel_(selected_title)
            self.palette.setToolTip_(selected_title)
        if swatch_page is not None:
            self._page = min(swatch_page, max(0, (len(self.palette_row()) - 1) // PAGE))
        self.palette.setEnabled_(bool(palettes))
        self.presets_button.setEnabled_(bool(font) and licensed)
        self.import_button.setEnabled_(bool(font) and licensed)
        self.export_button.setEnabled_(bool(palettes) and not problem and licensed)
        self.refresh_button.setEnabled_(bool(font))
        self.stats_refresh.setEnabled_(bool(font))
        row = self.palette_row()
        invalid = [str(index) for index, rgba in enumerate(row) if rgba is None]
        invalid_note = f"无效色槽：{', '.join(invalid)}" if invalid else ""
        self.palette_note.setStringValue_(problem or invalid_note or issue)
        self.palette_note.setToolTip_(invalid_note or problem or issue or None)
        selection = list(font.selectedLayers or ()) if font else []
        self._selection_count = len(selection)
        self.statistics_poll(font, selection)
        if font and self.expanded[3] and (self._index is None or self._index.next_position < self._index.total) and not self._index_timer:
            self.start_index()
        self.rebuild_swatches()
        self.update_swatch_selection(selection)
        if defer_stats or self._undo_index_dirty:
            self.arrange()
            self.queue_palette_stats()
        else:
            self.update_stats()
            self.arrange()

    @objc.python_method
    def rebuild_swatches(self):
        row = self.palette_row()
        names = self._palette_labels[self._view_index][1] if self._palette_labels else ()
        key = (row, self._page, names)
        if key != self._swatch_key:
            for button in self.swatches:
                button.removeFromSuperview()
            self.swatches = []
            self._swatch_key = key
            start = self._page * PAGE
            slots = [(FOREGROUND, None), *enumerate(row[start:start + PAGE], start)]
            if start + PAGE >= len(row):
                slots.append((-1, None))
            for index, rgba in slots:
                button = CZStats7ZDLColorSwatchButton.alloc().initWithFrame_(NSMakeRect(
                    0, 0, MIN_SWATCH_WIDTH, SWATCH_HEIGHT
                ))
                button.rgba = rgba
                button.hovered = button.selected_slot = False
                button.click_count = 1
                button.setTitle_("+" if index < 0 else "*" if index == FOREGROUND else str(index))
                button.setTarget_(self)
                button.setAction_("swatchClick:")
                button.setRefusesFirstResponder_(True)
                button.setTag_(index)
                button.setBordered_(False)
                tracking = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                    button.bounds(), NSTrackingMouseEnteredAndExited |
                    NSTrackingActiveInKeyWindow | NSTrackingInVisibleRect, button, None
                )
                button.addTrackingArea_(tracking)
                self.body.addSubview_(button)
                title = "新增颜色 · 右键添加预置或导入 ASE/GPL" if index < 0 else tooltip(index, rgba)
                if 0 <= index < len(names) and names[index]:
                    title = f"{names[index]} · {title}"
                button.setToolTip_(title)
                button.setAccessibilityLabel_(title)
                self.swatches.append(button)
        licensed = (self._license_view or {}).get("state") == "active"
        for button in self.swatches:
            button.setEnabled_(licensed)
        foreground = self.swatches[0]
        rgba = self.foreground_rgba()
        if foreground.rgba != rgba:
            foreground.rgba = rgba
            foreground.setNeedsDisplay_(True)
        pages = max(1, (len(row) + PAGE - 1) // PAGE)
        self.previous.setEnabled_(self._page > 0)
        self.following.setEnabled_(self._page < pages - 1)
        self.page_label.setStringValue_(f"{self._page + 1} / {pages}")

    @objc.python_method
    def update_swatch_selection(self, selection):
        # Only colors shared by every selected target appear selected.
        shared = {button.tag() for button in self.swatches if button.rgba is not None}
        if self._palette_error:
            shared.clear()
        shared.add(FOREGROUND)
        if not selection:
            shared.clear()
        for layer in selection:
            if not shared:
                break
            if layer.isColorPaletteLayer():
                colors = (layer,)
            elif layer.parent:
                colors = native_layers(layer.parent, layer.associatedMasterId or layer.layerId)
            else:
                colors = ()
            try:
                shared.intersection_update(color_index(color) for color in colors)
            except (ValueError, TypeError):
                shared.clear()
        for button in self.swatches:
            selected = button.tag() in shared
            if selected != button.selected_slot:
                button.selected_slot = selected
                button.setNeedsDisplay_(True)

    @objc.python_method
    def arrange(self):
        if self._laying_out:
            return
        self._laying_out = True
        try:
            clip = self.dialog.contentView().bounds().size
            width = max(1, clip.width)
            inner = max(1, width - 2 * INSET)
            y = GAP

            def place(view, x, top, span, height):
                view.setHidden_(False)
                frame = NSMakeRect(x, top, max(1, span), height)
                if view.frame() != frame:
                    view.setFrame_(frame)
                    view.setNeedsDisplay_(True)

            def row(*views, widths=None, min_height=0):
                nonlocal y
                if not visible:
                    for view in views:
                        view.setHidden_(True)
                    return
                if widths is None:
                    widths = [(inner - GAP * (len(views) - 1)) / len(views)] * len(views)
                height = max(min_height, max(
                    (ceil(view.cell().cellSizeForBounds_(NSMakeRect(0, 0, max(1, span), 10000)).height)
                     if isinstance(view, NSTextField)
                     else CONTROL_HEIGHT)
                    for view, span in zip(views, widths)
                ))
                x = INSET
                for view, span in zip(views, widths):
                    place(view, x, y, span, height)
                    x += span + GAP
                y += height + GAP

            def note(view):
                if visible and view.stringValue():
                    row(view)
                else:
                    view.setHidden_(True)

            for idx, header in enumerate(self.sections):
                visible = self.expanded[idx]
                if idx:
                    y += SECTION_GAP / 2 - GAP
                    place(self.dividers[idx - 1], INSET, y, inner, 1)
                    y += 1 + SECTION_GAP / 2
                header.section_expanded = visible
                header.setNeedsDisplay_(True)
                place(header, INSET, y, inner, CONTROL_HEIGHT)
                y += CONTROL_HEIGHT + GAP
                if idx == 0:
                    text_width = max(1, inner - 33)
                    height = ceil(self.palette_title.cell().cellSizeForBounds_(
                        NSMakeRect(0, 0, text_width, 10000)).height)
                    row(self.palette, min_height=height + 8)
                    self.palette_title.setFrame_(NSMakeRect(
                        8, (self.palette.bounds().size.height - height) / 2, text_width, height))
                    row(self.presets_button, self.refresh_button)
                    row(self.import_button, self.export_button)
                    note(self.palette_note)
                elif idx == 1:
                    header.setToolTip_(self.status.toolTip() or self.status.stringValue() or None)
                    if visible:
                        cols = min(5, max(1, int((inner + SWATCH_GAP) // (MIN_SWATCH_WIDTH + SWATCH_GAP))))
                        span = (inner - SWATCH_GAP * (cols - 1)) / cols
                        for start in range(0, len(self.swatches), cols):
                            buttons = self.swatches[start:start + cols]
                            for offset, button in enumerate(buttons):
                                x = INSET + offset * (span + SWATCH_GAP)
                                place(button, x, y, span, SWATCH_HEIGHT)
                            y += SWATCH_HEIGHT + GAP
                    else:
                        for button in self.swatches:
                            button.setHidden_(True)
                    visible = visible and len(self.palette_row()) > PAGE
                    side = min(PAGE_BUTTON_WIDTH, inner / 3)
                    row(self.previous, self.page_label, self.following,
                        widths=(side, inner - 2 * (side + GAP), side))
                elif idx == 2:
                    random, selected, all_random = self.batch_actions
                    row(self.batch_scan, random)
                    row(selected, all_random)
                    note(self.batch_result)
                else:
                    scanning = self._index_timer is not None
                    self.stats_refresh.setHidden_(scanning or not visible)
                    self.stats_cancel.setHidden_(not scanning or not visible)
                    label = self.stats_filter_label
                    available = max(1, (inner - GAP) / 2 - 22)
                    label_height = ceil(label.cell().cellSizeForBounds_(NSMakeRect(0, 0, available, 10000)).height)
                    action = self.stats_cancel if scanning else self.stats_refresh
                    row(action, self.stats_palette, min_height=label_height + 6)
                    if visible:
                        label.setFrame_(NSMakeRect(
                            3, (self.stats_palette.bounds().size.height - label_height) / 2,
                            available, label_height))
                        label.setTextColor_(NSColor.labelColor() if self.stats_palette.isEnabled()
                                            else NSColor.disabledControlTextColor())
                    self.stats_table.setHidden_(not visible)
                    if visible:
                        place(self.stats_table, INSET, y, inner, len(STATS_ROWS) * STATS_ROW_HEIGHT)
                        self.stats_table.column_width = inner * .355
                        split = self.stats_table.column_width
                        for i, (name, value) in enumerate(self.stats_cells):
                            top = i * STATS_ROW_HEIGHT + (STATS_ROW_HEIGHT - 17) / 2
                            name.setAlignment_(NSTextAlignmentCenter)
                            place(name, 2, top, split - 4, 17)
                            place(value, split + 8, top, inner - split - 12, 17)
                        y += len(STATS_ROWS) * STATS_ROW_HEIGHT + GAP
                    note(self.stats_note)
            footer = footer_layout(width, y, clip.height)
            for name, control in self.product_footer.items():
                place(control, *footer[name])
            height = footer['height']
            if self.body.frame().size != (width, height):
                self.body.setFrameSize_((width, height))
        finally:
            self._laying_out = False

    @objc.python_method
    def refresh_license_ui(self):
        value = STORE.status()
        if self._license_view != value:
            self._license_view = value
            update_footer_license(self.product_footer['vip'], value)
            self._license_window.refresh(value)
            if value["state"] != "active":
                for control in (self.presets_button, self.import_button, self.export_button,
                                self.batch_scan, *self.swatches, *self.batch_actions):
                    control.setEnabled_(False)
        return value["state"] == "active"

    @objc.python_method
    def license_allows_action(self):
        if self.refresh_license_ui():
            return True
        self.palette_message(self._license_view.get("message", "请先激活字动力·彩字。"))
        return False

    def licenseTick_(self, timer):
        if timer != self._license_timer:
            return
        prior = self._license_view
        licensed = self.refresh_license_ui()
        if prior != self._license_view:
            if not licensed:
                self.cancel_quick()
                self.cancel_palette_operations()
                self.cancel_added_editor()
                self.end_color_edit("license-unavailable")
            self.refresh_state(sync_only=True)

    def showLicense_(self, sender):
        self._license_window.show(self)

    def copyLicenseMachine_(self, sender):
        self._license_window.copy()

    def importLicense_(self, sender):
        self._license_window.import_file(self)

    def closeLicense_(self, sender):
        self._license_window.window.orderOut_(None)

    def deactivateLicense_(self, sender):
        self._license_window.deactivate(self)

    def showDeactivationReceipts_(self, sender):
        self._license_window.show_receipts(self)

    def selectDeactivationReceipt_(self, sender):
        self._license_window.receipts.update()

    def copyDeactivationReceipt_(self, sender):
        self._license_window.receipts.copy()

    def exportDeactivationReceipt_(self, sender):
        self._license_window.receipts.export()

    def closeDeactivationReceipts_(self, sender):
        self._license_window.receipts.close()

    def showProductInfo_(self, sender):
        product_windows.info()

    def showProductHelp_(self, sender):
        product_windows.help()

    def toggleSection_(self, sender):
        index = sender.tag()
        self.expanded[index] = not self.expanded[index]
        if self.expanded[index] and index in (2, 3) and self._index is None:
            self.start_index()
        self.update_stats()
        self.arrange()
        if self.expanded[index] and index >= 2:
            self.body.scrollRectToVisible_(self.sections[index].frame())

    def switchPalette_(self, sender):
        self.end_color_edit()
        self._view_index = max(0, sender.indexOfSelectedItem())
        self._page = 0
        self.status.setStringValue_("仅切换面板色板，字形编号未改动。")
        self.refresh_state()

    def changePage_(self, sender):
        self._page += sender.tag()
        self.refresh_state()

    def refreshPalette_(self, sender):
        self.refresh_state()

    def openNative_(self, sender):
        if not self.license_allows_action():
            return
        controller, font = self.context()
        if font:
            controller.showFontInfoWindowWithTabSelected_(0)
            window = NSApplication.sharedApplication().keyWindow()
            if window and window.identifier() == "GSFontInfoWindow":
                self.bind_focused_font_info(controller, window)

    def swatchClick_(self, sender):
        if not self.license_allows_action():return
        if sender.tag()<0:self.add_slot();return
        self.applyColor_(sender)


    @objc.python_method
    def swatch_menu(self, index):
        menu = NSMenu.alloc().init()
        usage = ("查看使用情况", "showSlotUsage:")
        if index < 0:
            actions = (("打开预置库", "addPreset:"), ("导入 ASE / GPL…", "importPalette:"), ("保存所看套系为预置", "saveCurrentPreset:"), ("Glyphs 字体信息", "openNative:"),
                       ("确认原位置改色并保留名称…", "reconcileIdentity:"),
                       ("删除所看备用色板…", "deleteBackup:"))
        elif index == FOREGROUND:
            actions = (usage,)
        else:
            actions = (("编辑颜色", "editSlot:"), usage, ("删除色块", "deleteSlot:"),
                       ("移动色槽…", "moveSlot:"))
        menu.setAutoenablesItems_(False)
        licensed = STORE.status()["state"] == "active"
        for title, action in actions:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(self)
            item.setTag_(index)
            item.setEnabled_(licensed or action == "showSlotUsage:")
            menu.addItem_(item)
        return menu

    @objc.python_method
    def palette_message(self, text):
        self.status.setStringValue_(text)
        self.status.setToolTip_(text)
        self.arrange()

    @objc.python_method
    def refresh_palette_write(self, *, index=None, remapped=False):
        page = self._page if index is None else index // PAGE
        if remapped and self._index is not None:
            self._undo_index_dirty = True
        self.refresh_state(sync_only=True, swatch_page=page, defer_stats=True)
        controller, _ = self.context()
        view = controller.activeViewController() if controller else None
        if view and view.respondsToSelector_("forceRedraw"):
            view.forceRedraw()
        Glyphs.redraw()

    @objc.python_method
    def add_slot(self):
        if not self.license_allows_action():
            return
        _, font = self.context()
        if not font or self._batch is not None:
            return
        if self.defer_palette_operation("add"):
            return
        self.end_color_edit()
        try:
            index = add_color_slot(font)
            self.refresh_palette_write(index=index)
            self.palette_message(f"已新增 Color {index}。右键色块可编辑。")
            self.cancel_added_editor()
            self._add_editor_request = (font, self._view_index, index, parameter_rows(font),
                                        font.userData[IDENTITY_KEY])
            self._add_editor_timer = self.common_timer(.05, "openAddedSlotTick:")
        except Exception as error:
            self.palette_message(str(error))

    @objc.python_method
    def cancel_added_editor(self):
        if self._add_editor_timer:
            self._add_editor_timer.invalidate()
            self._add_editor_timer = None
        self._add_editor_request = None

    def openAddedSlotTick_(self, timer):
        if timer != self._add_editor_timer:
            return
        request = self._add_editor_request
        self.cancel_added_editor()
        if not request or self._sync_document_closed or self._color_edit:
            return
        font, palette, index, rows, identity = request
        if (self.context()[1] == font and Glyphs.font == font and self._view_index == palette
                and parameter_rows(font) == rows and font.userData[IDENTITY_KEY] == identity):
            self.open_color_editor(index, automatic=True)

    @objc.python_method
    def apply_palette_plan(self, font, plan, *, replace=False):
        if not self.license_allows_action():
            return
        self.end_color_edit()
        validate_palette_references(font, plan.after)
        backup = len(plan.after) > len(plan.before or ()) and plan.target > 0
        action = "替换整套配色" if replace else ("添加为备用色板" if backup else "应用到当前色板")
        order = None
        if replace:
            order = [None if i == plan.target else i for i in range(len(plan.after))]
        names = tuple(label if i == plan.target else None for i, label in enumerate(plan.labels))
        commit(font, plan.before, plan.after, labels=names, palette_order=order, undo_name=action)
        self._view_index = 0
        self._page = 0
        self.refresh_palette_write()
        self.palette.selectItemAtIndex_(0)
        name = plan.labels[plan.target][0]
        self.palette_message(f"{action} · Palette {plan.target} · {name}")

    @objc.python_method
    def user_presets(self):
        try:
            raw = NSUserDefaults.alloc().initWithSuiteName_("com.zidongli.color.glyphs.candidate3").stringForKey_(USER_PRESETS)
            if raw is None:
                # Read existing presets without changing the stable product's preferences.
                raw = NSUserDefaults.standardUserDefaults().stringForKey_(USER_PRESETS)
            records = json.loads(raw or "[]")
            return records if isinstance(records, list) else []
        except (TypeError, ValueError):
            return []

    @objc.python_method
    def remember_preset(self, name, kind, swatches):
        require_write()
        entry = {"name": name, "description": kind, "colors": [
            {"name": swatch.name, "rgb": list(swatch.rgba[:3]), "alpha": swatch.rgba[3],
             "hex": color_label(swatch.rgba)} for swatch in swatches
        ]}
        records = self.user_presets()
        if entry not in records:
            NSUserDefaults.alloc().initWithSuiteName_("com.zidongli.color.glyphs.candidate3").setObject_forKey_(
                json.dumps(records + [entry], ensure_ascii=False), USER_PRESETS)

    def saveCurrentPreset_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        if not font or self._batch is not None:
            return
        try:
            raw, normalized = palette_snapshot(font)
            index = self._view_index
            row = normalized[index]
            if None in row:
                raise ValueError("请先修复当前套系中的无效颜色。")
            name, names = identity_labels(font, raw)[0][index]
            name = name or f"{font.familyName} · Palette {index}"
            swatches = tuple(Swatch(names[i] if i < len(names) else "", rgba) for i, rgba in enumerate(row))
            self.remember_preset(name, "自定义套系", swatches)
            self.palette_message(f"已保存预置 · {name}")
        except (TypeError, ValueError, IndexError) as error:
            self.palette_message(str(error))

    @objc.python_method
    def palette_scroll(self, width, height, content_height):
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        body = CZStats7ZDLColorFlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, width - 16, content_height))
        scroll.setDocumentView_(body)
        return scroll, body

    @objc.python_method
    def palette_text(self, body, text, frame, size=12, bold=False):
        view = NSTextField.labelWithString_(text)
        view.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        view.setFrame_(frame)
        body.addSubview_(view)

    @objc.python_method
    def preview_chip(self, body, rgba, frame, description):
        chip = NSBox.alloc().initWithFrame_(frame)
        chip.setBoxType_(NSBoxCustom)
        chip.setBorderType_(NSNoBorder)
        chip.setCornerRadius_(4)
        chip.setFillColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(*(v / 255 for v in rgba)))
        chip.setToolTip_(description)
        body.addSubview_(chip)

    def addPreset_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        if not font or self._batch is not None:
            return
        self._presets = json.loads(Path(__file__).with_name("Presets.json").read_text(encoding="utf-8")) + self.user_presets()
        if self._preset_window:
            self._preset_window.close()
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 696, 414), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False)
        panel.setTitle_("色彩套系预置库")
        panel.setReleasedWhenClosed_(False)
        scroll, body = self.palette_scroll(696, 414, ceil(len(self._presets) / 2) * 148 + 14)
        panel.setContentView_(scroll)
        for index, preset in enumerate(self._presets):
            x, y = 12 + index % 2 * 334, 10 + index // 2 * 148
            card = CZStats7ZDLColorFlippedView.alloc().initWithFrame_(NSMakeRect(x, y, 320, 138))
            card.setWantsLayer_(True)
            card.layer().setCornerRadius_(8)
            card.layer().setBorderWidth_(1)
            card.layer().setBorderColor_(NSColor.separatorColor().CGColor())
            body.addSubview_(card)
            self.palette_text(card, f"{preset['name']}  ·  {len(preset['colors'])} 色槽", NSMakeRect(12, 8, 296, 20), 14, True)
            self.palette_text(card, preset["description"], NSMakeRect(12, 32, 296, 16), 11)
            for i, entry in enumerate(preset["colors"][:19]):
                self.preview_chip(card, (*entry["rgb"], entry.get("alpha", 255)), NSMakeRect(
                    12 + i % 10 * 29, 55 + i // 10 * 22, 25, 17),
                    f"{i} · {entry['name']} · {entry['hex']}")
            button = NSButton.buttonWithTitle_target_action_("选择并预览", self, "previewPreset:")
            button.setTag_(index)
            button.setFrame_(NSMakeRect(12, 103, 296, 27))
            card.addSubview_(button)
        self._preset_font = font
        self._preset_window = panel
        panel.center()
        panel.makeKeyAndOrderFront_(None)

    def previewPreset_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        if font != self._preset_font or self._batch is not None:
            return
        preset = self._presets[sender.tag()]
        swatches = tuple(Swatch(entry["name"], (*entry["rgb"], entry.get("alpha", 255))) for entry in preset["colors"])
        self._preset_window.orderOut_(None)
        self.show_palette_preview(font, preset["name"], "内置预置", swatches)

    def importPalette_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        window = self.dialog.window()
        if not font or not window or window.attachedSheet() or self._batch is not None:
            return
        panel = NSOpenPanel.openPanel()
        panel.setAllowedFileTypes_(["ase", "gpl"])

        def import_file(result):
            if result != NSModalResponseOK or self.context()[1] != font or self._batch is not None:
                return
            try:
                path = Path(panel.URL().path())
                parser = {".ase": read_ase, ".gpl": read_gpl}[path.suffix.lower()]
                swatches = parser(path.read_bytes())
                callAfter(self.show_palette_preview, font, path.stem, path.suffix[1:].upper(), swatches, path.name)
            except (KeyError, OSError, ValueError, RuntimeError) as error:
                callAfter(self.show_palette_error, window, "导入失败", str(error))

        panel.beginSheetModalForWindow_completionHandler_(window, import_file)

    @objc.python_method
    def show_palette_error(self, window, title, message):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("关闭")
        alert.beginSheetModalForWindow_completionHandler_(window, None)

    @objc.python_method
    def show_palette_preview(self, font, name, kind, swatches, filename=None):
        if not self.license_allows_action():
            return
        window = self.dialog.window()
        if not window or window.attachedSheet() or self.context()[1] != font or self._batch is not None:
            return
        try:
            plan = plan_palette(font, name, swatches)
            maximum = validate_palette_references(font, plan.after)
            replace_index = min(self._view_index, len(plan.before or ()) - 1)
            replacement = None
            if plan.before:
                try:
                    replacement = plan_palette(font, name, swatches, replace_index=replace_index)
                    validate_palette_references(font, replacement.after)
                except (TypeError, ValueError):
                    replacement = None
        except (TypeError, ValueError, RuntimeError) as error:
            self.show_palette_error(window, "无法应用预置", str(error))
            return
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"已选择，尚未应用 · {name}")
        duplicates = sum(count - 1 for count in Counter(swatch.rgba for swatch in swatches).values())
        next_count = len(plan.after[0])
        alert.setInformativeText_(
            f"{filename or name} · {kind} · {plan.incoming} 色\n"
            f"Palette 0 槽位 {plan.original} → {next_count} · 沿用 {plan.inherited}"
            + (f"\n最高现有引用 Color {maximum}。" if maximum >= 0 else "")
            + (f"\n全部现有色板末尾追加 {plan.expansion} 槽，旧编号不变。" if plan.expansion else "")
            + ("\n应用会替换 Palette 0；添加备用会在末尾新增。" if plan.before else "")
            + (f"\n包含 {duplicates} 个重复色值，按原编号保留。" if duplicates else "")
        )
        # Render large inputs in a native text view; Cocoa lays out the scroll buffer.
        from AppKit import NSTextView
        text = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 428, 190))
        text.setEditable_(False)
        text.setVerticallyResizable_(True)
        text.textContainer().setWidthTracksTextView_(True)
        text.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11, 0))
        rows = []
        previews = [("应用到 Palette 0／作为备用", plan)]
        if replacement and replace_index > 0:
            previews.append((f"替换 Palette {replace_index}", replacement))
        for title, choice in previews:
            rows.append(title)
            for index, (raw_color, label) in enumerate(zip(choice.after[choice.target], choice.labels[choice.target][1])):
                rgba = stored_rgba(raw_color)
                origin = "输入" if index < choice.incoming else "沿用"
                rows.append(f"{index:02d}  {origin}  {color_label(rgba)}   {' / '.join(map(str, rgba[:3]))}   {label or f'Color {index}'}")
        text.setString_("\n".join(rows))
        preview = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 442, 190))
        preview.setHasVerticalScroller_(True)
        preview.setDocumentView_(text)
        alert.setAccessoryView_(preview)
        alert.addButtonWithTitle_("应用到当前色板")
        alert.addButtonWithTitle_("取消")
        identity_before = font.userData[IDENTITY_KEY]
        legacy_before = font.userData[LABELS]
        if plan.before:
            alert.addButtonWithTitle_("添加为备用色板")
        if replacement:
            alert.addButtonWithTitle_(f"替换 Palette {replace_index} 的整套配色")

        def confirmed(result):
            if result not in (NSAlertFirstButtonReturn, NSAlertThirdButtonReturn, NSAlertThirdButtonReturn + 1):
                return
            if self.context()[1] != font or self._batch is not None:
                return
            try:
                if (plan_palette(font, name, swatches) != plan
                        or identity_before != font.userData[IDENTITY_KEY] or legacy_before != font.userData[LABELS]):
                    raise ValueError("色板已变化，请重新预览。")
                replacing = result == NSAlertThirdButtonReturn + 1
                chosen = replacement if replacing else (
                    plan if result == NSAlertFirstButtonReturn else plan_palette(font, name, swatches, backup=True))
                if chosen and self.license_allows_action():
                    self.apply_palette_plan(font, chosen, replace=replacing)
                if filename and self.license_allows_action():
                    self.remember_preset(name, f"导入 · {kind}", swatches)
            except Exception as error:
                self.palette_message(str(error))

        alert.beginSheetModalForWindow_completionHandler_(window, confirmed)

    def exportPalette_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        window = self.dialog.window()
        if not font or not window or window.attachedSheet() or self._batch is not None:
            return
        try:
            raw, colors = palette_snapshot(font)
            labels, _ = identity_labels(font, raw)
        except (TypeError, ValueError) as error:
            self.palette_message(str(error))
            return
        choices = CZStats7ZDLColorFlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 314, 30))
        fmt = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 150, 28), False)
        fmt.addItemsWithTitles_(["ASE", "GPL"])
        scope = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(160, 0, 154, 28), False)
        scope.addItemsWithTitles_(["当前套系", "全部套系"])
        choices.addSubview_(fmt)
        choices.addSubview_(scope)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("导出色彩套系")
        alert.setAccessoryView_(choices)
        alert.addButtonWithTitle_("取消")
        alert.addButtonWithTitle_("继续")
        active = self._view_index

        def choose(result):
            if result != NSAlertSecondButtonReturn or self.context()[1] != font:
                return
            batch = scope.indexOfSelectedItem() == 1
            indices = range(len(colors)) if batch else (active,)
            payload = []
            for i in indices:
                if None in colors[i]:
                    callAfter(self.show_palette_error, window, "导出失败", f"Palette {i} 含无效颜色，请先修复色槽。")
                    return
                name, names = labels[i]
                payload.append((name or f"Palette {i}", tuple(
                    Swatch(names[j] if j < len(names) else "", rgba) for j, rgba in enumerate(colors[i]))))
            file_format = "ase" if fmt.indexOfSelectedItem() == 0 else "gpl"
            callAfter(self.choose_export_destination, window, tuple(payload), file_format, batch)

        alert.beginSheetModalForWindow_completionHandler_(window, choose)

    @objc.python_method
    def choose_export_destination(self, window, payload, file_format, batch):
        if not self.license_allows_action():
            return
        def choose_location():
            if batch:
                panel = NSOpenPanel.openPanel()
                panel.setCanChooseFiles_(False)
                panel.setCanChooseDirectories_(True)
                panel.setCanCreateDirectories_(True)
                panel.setPrompt_("导出")
            else:
                panel = NSSavePanel.savePanel()
                panel.setAllowedFileTypes_([file_format])
                panel.setNameFieldStringValue_(f"{safe_filename(payload[0][0])}.{file_format}")

            def write(result):
                if result != NSModalResponseOK:
                    return
                try:
                    if not self.license_allows_action():
                        return
                    export_palettes(panel.URL().path(), payload, file_format, batch=batch)
                    self.palette_message(f"已导出 {len(payload)} 个 {file_format.upper()} 文件。")
                except (OSError, ValueError) as error:
                    self.palette_message(f"导出失败：{error}")

            panel.beginSheetModalForWindow_completionHandler_(window, write)

        if any(swatch.rgba[3] != 255 for _, row in payload for swatch in row):
            warning = NSAlert.alloc().init()
            warning.setMessageText_(f"{file_format.upper()} 无法保留透明度")
            warning.setInformativeText_("继续导出时，文件只保存 RGB。字体工程的透明度会保留。")
            warning.addButtonWithTitle_("取消")
            warning.addButtonWithTitle_("继续导出")
            warning.beginSheetModalForWindow_completionHandler_(
                window, lambda result: callAfter(choose_location) if result == NSAlertSecondButtonReturn else None)
        else:
            choose_location()

    def editSlot_(self, sender):
        if not self.license_allows_action():
            return
        self.open_color_editor(sender.tag())

    @objc.python_method
    def color_editor_blocker(self):
        app = NSApplication.sharedApplication()
        modal = app.modalWindow()
        if modal:
            return f"modal:{modal.className()}"
        for window in app.windows():
            if window.attachedSheet() is not None:
                return f"sheet:{window.attachedSheet().className()}"
        return ""

    @objc.python_method
    def color_editor_log(self, event):
        NSLog("ZDLColorEditor build24.3 event=%@ main=%@ host=%@", event,
              str(bool(NSThread.isMainThread())), self.color_editor_blocker() or "none")

    @objc.python_method
    def open_color_editor(self, index, *, automatic=False):
        if not self.license_allows_action():
            return
        if not NSThread.isMainThread():
            callAfter(self.open_color_editor, index, automatic=automatic)
            return
        _, font = self.context()
        parent = self.dialog.window()
        if not font or not parent or self._batch is not None:
            return
        if self.defer_palette_operation("edit", index):
            return
        if self.color_editor_blocker():
            self.palette_message("请先完成当前窗口，再编辑颜色。")
            return
        try:
            rows, colors = palette_snapshot(font)
            palette = self._view_index
            if not 0 <= palette < len(rows) or not 0 <= index < len(rows[palette]):
                raise ValueError("颜色编号已变化，请重新选择。")
            picker_class = objc.lookUpClass("BFColorPickerPopover")
            anchor = next((button for button in self.swatches if button.tag() == index), None)
            if anchor is None or anchor.window() != parent:
                raise ValueError("请先显示要编辑的颜色槽。")
            self.end_color_edit("replaced")
            # Glyphs' shared picker owns the embedded shared NSColorPanel view.
            # A temporary picker can leave AppKit appearance callbacks referring
            # to its released view controller after the popover closes.
            picker = picker_class.sharedPopover()
            if picker.isShown():
                raise ValueError("请先完成已经打开的原生颜色选择器。")
            initial = rows[palette][index]
            color = initial if isinstance(initial, NSColor) else NSColor.colorWithSRGBRed_green_blue_alpha_(
                *(value / 255 for value in (colors[palette][index] or (0, 0, 0, 255))))
            session = dict(font=font, palette=palette, index=index, rows=rows, picker=picker,
                           parent=parent, accepted=None,
                           picker_modal=picker.showModal(), picker_delegate=picker.delegate(),
                           identity=(font.userData[LABELS], font.userData[IDENTITY_KEY]))
            self._color_edit = session
            picker.setDelegate_(None)
            picker.setColor_(color)
            picker.setTarget_(self)
            picker.setAction_("nativeColorAccepted:")
            # Glyphs' own picker supplies its own controls and Confirm/Cancel.
            # Its modal setting commits only on Confirm, not on every drag.
            picker.setShowModal_(True)
            center = NSNotificationCenter.defaultCenter()
            for name, obj in ((NSWindowWillCloseNotification, parent),
                              (NSApplicationWillTerminateNotification, None)):
                center.addObserver_selector_name_object_(self, "colorEditorLifecycle:", name, obj)
            self.color_editor_log("native-open")
            try:
                picker.showRelativeToRect_ofView_preferredEdge_(anchor.bounds(), anchor, 0)
            finally:
                # The native call returns after its own modal session has ended.
                # No Palette write occurs while it owns the event loop.
                self.end_color_edit("native-finished")
            if session['accepted'] is None:
                self.color_editor_log("native-cancelled")
                return
            if (self.context()[1] != font or Glyphs.font != font or self._sync_document_closed
                    or session['identity'] != (font.userData[LABELS], font.userData[IDENTITY_KEY])):
                raise ValueError("字体、套系或槽位已变化，未提交颜色，请重新打开。")
            rgba = session['accepted']
            if stored_rgba(rows[palette][index]) != rgba:
                commit(font, rows, edited_slot(rows, palette, index, rgba), undo_name="编辑颜色")
                self.refresh_palette_write(index=index)
            self.color_editor_log("native-committed")
        except Exception as error:
            self.end_color_edit("native-error")
            self.palette_message(str(error))
        finally:
            self.schedule_palette_operations()

    def nativeColorAccepted_(self, sender):
        session = self._color_edit
        if session and sender == session['picker']:
            session['accepted'] = picker_rgba(sender.color())

    def colorEditorLifecycle_(self, notification):
        self.end_color_edit("application-terminate" if notification.name() == NSApplicationWillTerminateNotification
                            else "document-close")

    @objc.python_method
    def end_color_edit(self, reason="context-change", *, closing=False):
        if not self._color_edit:
            return
        if not NSThread.isMainThread():
            callAfter(self.end_color_edit, reason, closing=closing)
            return
        session, self._color_edit = self._color_edit, None
        center = NSNotificationCenter.defaultCenter()
        for name, obj in ((NSWindowWillCloseNotification, session['parent']),
                          (NSApplicationWillTerminateNotification, None)):
            center.removeObserver_name_object_(self, name, obj)
        picker = session['picker']
        if picker.target() == self:
            if picker.isShown():
                picker.close()
            picker.setTarget_(None)
            picker.setAction_(None)
        # Font Info's BFPopoverColorWell uses the nonmodal shared picker and
        # installs its color-well binding after showRelativeToRect returns.
        # Leaving our confirmation mode on would prevent that binding from
        # observing the native editor's changes on the next use.
        picker.setShowModal_(session['picker_modal'])
        picker.setDelegate_(session['picker_delegate'])
        self.color_editor_log(reason)

    @objc.python_method
    def defer_palette_operation(self, kind, index=None):
        # The host's Font Info sheet owns an isolated, uncommitted Palette.
        # Receive the command now, but never replace its backing parameter.
        if font_info_sheet() is None:
            return False
        _, font = self.context()
        if not font or self._sync_document_closed:
            return True
        try:
            request = slot_request(kind, font, self._view_index, index, parameter_rows(font),
                                   font.userData[IDENTITY_KEY])
            self._pending_palette_operations.append(request)
            self.palette_message(f"已接收 {len(self._pending_palette_operations)} 项颜色操作，原生窗口关闭后自动执行。")
            self.palette_note.setStringValue_("颜色操作已排队，原生窗口关闭后自动执行")
            self.schedule_palette_operations()
        except Exception as error:
            self.palette_message(str(error))
        return True

    @objc.python_method
    def schedule_palette_operations(self):
        if (self._pending_palette_operations and self._palette_operation_timer is None
                and not self._sync_document_closed):
            self._palette_operation_timer = self.common_timer(.1, "paletteOperationTick:")

    @objc.python_method
    def cancel_palette_operations(self):
        if self._palette_operation_timer is not None:
            self._palette_operation_timer.invalidate()
            self._palette_operation_timer = None
        self._pending_palette_operations = []

    def paletteOperationTick_(self, timer):
        if timer != self._palette_operation_timer:
            return
        self._palette_operation_timer = None
        if self._sync_document_closed:
            self.cancel_palette_operations()
            return
        if self.color_editor_blocker() or self._color_edit or self._batch is not None:
            self.schedule_palette_operations()
            return
        if not self._pending_palette_operations:
            return
        request = self._pending_palette_operations.pop(0)
        font = request['font']
        try:
            if self.context()[1] != font or Glyphs.font != font:
                raise ValueError("活动字体已切换，原字体的排队操作未执行。")
            palette, index = resolve_request(request, parameter_rows(font), font.userData[IDENTITY_KEY])
            self._view_index = palette
            self.refresh_state(sync_only=True, defer_stats=True)
            if request['kind'] == 'add':
                self.add_slot()
                if self._pending_palette_operations:
                    self.cancel_added_editor()
            elif request['kind'] == 'edit':
                self.open_color_editor(index)
            else:
                sender = NSMenuItem.alloc().init()
                sender.setTag_(index)
                self.deleteSlot_(sender)
        except Exception as error:
            self.palette_message(str(error))
        finally:
            self.schedule_palette_operations()


    def showSlotUsage_(self, sender):
        _, font = self.context()
        if not font:
            return
        slot = sender.tag()
        try:
            if slot == FOREGROUND:
                slot_count = len(self.palette_row())
                title = tooltip(FOREGROUND, None)
            else:
                _, colors = palette_snapshot(font)
                if not 0 <= slot < len(colors[0]):
                    raise ValueError("颜色编号已变化，请重新选择。")
                slot_count = len(colors[0])
                title = tooltip(slot, colors[self._view_index][slot])
            all_refs, unknown = references(font, slot_count)
            matching = [ref for ref in all_refs if ref.index == slot]
        except (TypeError, ValueError) as error:
            self.palette_message(str(error))
            return
        names = sorted({ref.glyph.name for ref in matching})
        masters = ", ".join(sorted({ref.master for ref in matching})) or "无"
        text = f"{title}\n{len(names):,} 字形 · {len(matching):,} 图层\n母版：{masters}"
        if unknown:
            text += f"\n另有 {len(unknown):,} 条未知颜色引用。"
        alert = NSAlert.alloc().init()
        alert.setMessageText_("颜色使用情况")
        alert.setInformativeText_(text)
        alert.addButtonWithTitle_("好")
        if names:
            alert.addButtonWithTitle_("打开字形")
        window = self.dialog.window()
        if window:
            def open_names(result):
                if result == NSAlertSecondButtonReturn and self.context()[1] == font:
                    font.newTab("".join("/" + name for name in names))
            alert.beginSheetModalForWindow_completionHandler_(window, open_names)

    @objc.python_method
    def confirm_palette_operation(self, font, rows, title, message, operation, field=None):
        window = self.dialog.window()
        if not window or self._batch is not None or window.attachedSheet():
            return
        self.end_color_edit()
        snapshot = (font.userData[LABELS], font.userData[IDENTITY_KEY])
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        if field is not None:
            alert.setAccessoryView_(field)
        alert.addButtonWithTitle_("取消")
        alert.addButtonWithTitle_("确认")

        def confirmed(result):
            if result != NSAlertSecondButtonReturn or self.context()[1] != font:
                return
            try:
                if (self._batch is not None or parameter_rows(font) != rows
                        or snapshot != (font.userData[LABELS], font.userData[IDENTITY_KEY])):
                    raise ValueError("色板或身份已变化，请重新确认。")
                if not self.license_allows_action():
                    return
                operation()
                self.refresh_palette_write(remapped=True)
                self.palette_message("操作完成。")
            except Exception as error:
                self.palette_message(str(error))

        alert.beginSheetModalForWindow_completionHandler_(window, confirmed)

    def deleteBackup_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        index = self._view_index
        rows = parameter_rows(font) if font else None
        if not rows or not 0 < index < len(rows):
            self.palette_message("请先切换到要删除的备用色板。")
            return
        self.confirm_palette_operation(font, rows, f"删除备用 Palette {index}？",
                                       "Palette 0 和颜色槽编号保持原样。",
                                       lambda: delete_backup(font, rows, index))

    def moveSlot_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        rows = parameter_rows(font) if font else None
        source = sender.tag()
        if not rows or not 0 <= source < len(rows[0]):
            return
        count = len(rows[0])
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 190, 25))
        field.setStringValue_(str(source))

        def move():
            target_text = field.stringValue().strip()
            if not target_text.isascii() or not target_text.isdecimal() or not 0 <= int(target_text) < count:
                raise ValueError(f"请输入 0 到 {count-1} 之间的编号。")
            order = list(range(count))
            order.insert(int(target_text), order.pop(source))
            reorder_slots(font, rows, order)

        self.confirm_palette_operation(font, rows, f"移动 Color {source} 到指定编号",
                                       f"输入 0 到 {count-1}。所有套系和字形的颜色引用按同一映射更新。",
                                       move, field)

    def reconcileIdentity_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        rows = parameter_rows(font) if font else None
        if not rows or not font.userData[IDENTITY_KEY]:
            self.palette_message("当前没有可核对的 v2 身份记录。")
            return
        self.confirm_palette_operation(font, rows, "按原编号保留名称？",
            "仅适用于明确只改了颜色或透明度的情形。若移动、替换或删除了槽位，请先核对实际对应关系。",
            lambda: commit(font, rows, rows, reconcile=True, undo_name="确认原位置改色"))

    def deleteSlot_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        if not font or not self.dialog.window():
            return
        if self.defer_palette_operation("delete", sender.tag()):
            return
        self.end_color_edit()
        index = sender.tag()
        try:
            rows, _ = palette_snapshot(font, complete=True)
            safe_delete_slot(font, rows, index)
            self.refresh_palette_write(remapped=True)
            self.palette_message(f"已删除 Color {index}。")
        except Exception as error:
            self.palette_message(str(error))

    @objc.python_method
    def capacity_timer(self, selector):
        timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(.012, self, selector, None, True)
        NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
        return timer

    @objc.python_method
    def capacity_revision_key(self, font=None):
        font = self.context()[1] if font is None else font
        if not font:return None
        tracker=self._capacity_registry.get(font)
        return (font, tracker.epoch, len(font.glyphs))

    @objc.python_method
    def capacity_state_changed(self):
        key = self.capacity_revision_key()
        return key != self._capacity_key

    def capacityUndoChanged_(self, notification):
        _,font=self.context()
        if not font or not font.parent:return
        managers={font.parent.undoManager(),palette_undo_manager(font.parent)}
        managers.update(l.parent.undoManager() for l in tuple(font.selectedLayers or ())[:16] if l.parent)
        if notification.object() not in managers:return
        self.invalidate_capacity()
        self.cancel_quick()
        self._undo_index_dirty = True
        if self._batch is not None and self._batch.stage in ("容量检查", "待风险确认"):
            self._batch.abort("字体已撤销或重做，请重新操作。")
        self.queue_palette_stats()

    @objc.python_method
    def stop_capacity(self):
        if self._capacity_timer:self._capacity_timer.invalidate()
        self._capacity_timer = self._capacity_scan = None

    @objc.python_method
    def invalidate_capacity(self, force=False):
        self.stop_capacity()
        _,font=self.context()
        if font and force:
            tracker=self._capacity_registry.get(font);tracker.inventory=None;tracker.root_dirty=True
        self._capacity=None;self._capacity_key=None
        if hasattr(self,'stats_cells') and self.stats_cells:self.stats_cells[0][1].setStringValue_("待计算")
        self.ensure_capacity(font)

    @objc.python_method
    def ensure_capacity(self, font):
        if not font or self._sync_document_closed or self._batch is not None or not self.dialog.window():return
        if self._capacity_font != font:
            self.stop_capacity();self._capacity_font=font;self._capacity=None;self._capacity_key=None
        tracker=self._capacity_registry.get(font);tracker.statistics=self._statistics_cache.get(font);rows=read_palettes(font)
        targets=tuple({l.parent.name:l.parent for l in (font.selectedLayers or ()) if l.parent}.values())
        inv=tracker.snapshot(rows,targets)
        if inv is not None:
            self._capacity=inv;self._capacity_key=self.capacity_revision_key(font)
            state=self._statistics_cache.get(font);state.capacity_records=inv.records
            state.capacity_seen.clear()
            return
        self._capacity=None
        if self._capacity_scan is None:
            scan=tracker.scan(rows)
            if scan is None:self._capacity=tracker.inventory;self._capacity_key=self.capacity_revision_key(font);return
            self._capacity_scan=scan;self._stats_capacity_ticket=tracker.epoch
            self._capacity_timer=self.capacity_timer("capacityTick:")

    def capacityTick_(self, timer):
        if timer!=self._capacity_timer:return
        if self.context()[1]!=self._capacity_font or not self.dialog.window():self.stop_capacity();return
        tracker=self._capacity_registry.get(self._capacity_font);tracker.watch_step(64)
        if tracker.epoch!=self._stats_capacity_ticket:
            self.stop_capacity();self.ensure_capacity(self._capacity_font);return
        if self._capacity_scan.step(64):
            result=self._capacity_scan.result;rows=read_palettes(self._capacity_font)
            slots=len(rows[0]) if rows and len({len(r) for r in rows})==1 and all(c is not None for r in rows for c in r) else 0
            if result.signature!=capacity.export_signature(self._capacity_font) or result.base_total!=len(self._capacity_font.glyphs) or result.slot_count!=slots:
                self.stop_capacity();self.ensure_capacity(self._capacity_font);return
            if tracker.cold_changed:
                tracker.cold_changed=False;self.stop_capacity();self.ensure_capacity(self._capacity_font);return
            tracker.accept(self._capacity_scan.result);self._capacity=tracker.inventory
            self._capacity_key=self.capacity_revision_key(self._capacity_font)
            state=self._statistics_cache.get(self._capacity_font);state.capacity_records=self._capacity.records;state.capacity_seen.clear()
            self.stop_capacity();self.update_stats();self.arrange()

    @objc.python_method
    def capacity_snapshot(self):
        self.ensure_capacity(self.context()[1])
        return self._capacity

    @objc.python_method
    def cancel_quick(self):
        if self._quick_timer:self._quick_timer.invalidate()
        self._quick_timer = self._quick_guard = None
        alert, parent = self._quick_alert, self._quick_alert_parent
        self._quick_alert = self._quick_alert_parent = None
        if alert and parent and parent.attachedSheet() == alert.window():
            parent.endSheet_(alert.window());alert.window().orderOut_(None)

    @objc.python_method
    def apply_quick_guard(self, guard, confirmed=False):
        if self._quick_guard is not guard:return
        if self.context()[1] != guard.font or tuple(guard.font.selectedLayers or ())!=getattr(self,"_quick_selection",()) or read_palettes(guard.font) != self._quick_epoch_rows:
            raise capacity.StructureError("字体或色板已变化，请重新着色。")
        guard.authorize(confirmed)
        self.cancel_quick()
        applied = capacity.apply_atomic(guard.font, guard.changes, apply_changes)
        self._quick_projection=guard.result
        self.refresh_mutation(guard.font, applied)
        message = f"已更新 {len(guard.changes)} 个字形目标"
        if guard.result.known and guard.result.remaining == 0:message += "；容量已耗尽，不能再增加字形资源。"
        elif guard.result.known and guard.result.remaining <= capacity.RESERVE:message += "；剩余空间已进入预留提醒区。"
        self.status.setStringValue_(message)

    @objc.python_method
    def confirm_quick_guard(self, guard):
        window = self.dialog.window()
        if not window:raise capacity.StructureError("文字窗口已关闭，未执行着色。")
        alert = NSAlert.alloc().init()
        alert.setMessageText_("请确认本次着色")
        alert.setInformativeText_("\n\n".join(guard.warnings)+"\n\n确认后继续；取消不会写入。")
        alert.addButtonWithTitle_("取消")
        alert.addButtonWithTitle_("继续")
        self._quick_alert, self._quick_alert_parent = alert, window
        def answered(result):
            if self._quick_guard is not guard:return
            self._quick_alert = self._quick_alert_parent = None
            if result != NSAlertSecondButtonReturn:
                self.cancel_quick();self.status.setStringValue_("已取消，本次未写入。")
            else:
                try:self.apply_quick_guard(guard, True)
                except Exception as error:self.cancel_quick();self.status.setStringValue_(str(error))
            self.arrange()
        alert.beginSheetModalForWindow_completionHandler_(window, answered)

    def quickCapacityTick_(self, timer):
        if timer != self._quick_timer:return
        guard = self._quick_guard
        try:
            if self.context()[1] != guard.font or tuple(guard.font.selectedLayers or ())!=getattr(self,"_quick_selection",()) or read_palettes(guard.font) != self._quick_epoch_rows:
                raise capacity.StructureError("字体或色板已变化，请重新着色。")
            if not guard.step(64):return
            self._quick_timer.invalidate();self._quick_timer = None
            if guard.requires_confirmation:self.confirm_quick_guard(guard)
            else:self.apply_quick_guard(guard)
        except Exception as error:
            self.cancel_quick();self.status.setStringValue_(str(error))
        self.arrange()

    def applyColor_(self, sender):
        if not self.license_allows_action():
            return
        if self._batch is not None:
            return
        _, font = self.context()
        if not font:
            return
        try:
            index = sender.tag()
            if index != FOREGROUND and read_palettes(font) != self._palettes:
                self.refresh_state()
                self.status.setStringValue_("原生色板已变化，请重新点击。")
                return
            row = self.palette_row()
            if index != FOREGROUND and (self._palette_error or not 0 <= index < len(row) or row[index] is None):
                return
            selection = list(font.selectedLayers or ())
            if not selection:
                return
            changes, skipped = plan_changes(selection, index)
            if changes:
                self.cancel_quick()
                self._quick_guard = capacity.Guard(font, changes, read_palettes(font), prior=self.capacity_snapshot())
                self._quick_epoch_rows = read_palettes(font)
                self._quick_selection = tuple(selection)
                if self._quick_guard.prior is not None and len(changes)<=16 and self._quick_guard.step(64):
                    guard=self._quick_guard
                    if guard.requires_confirmation:self.confirm_quick_guard(guard)
                    else:self.apply_quick_guard(guard)
                    return
                self._quick_timer = self.capacity_timer("quickCapacityTick:")
                self.status.setStringValue_("正在检查本次着色容量…")
                self.arrange()
                return
            message = f"已更新 {len(changes)} 个字形目标" if changes else "没有需要更新的字形目标"
            if skipped:
                message += f"；跳过 {len(skipped)} 个"
                self.status.setToolTip_("\n".join(skipped))
                message += f"。{skipped[0].partition('：')[2]}"
            else:
                self.status.setToolTip_(None)
            self.status.setStringValue_(message)
        except (capacity.CapacityError, capacity.StructureError, capacity.ConfirmationRequired) as error:
            self.cancel_quick();self.status.setStringValue_(str(error))
        except Exception as error:
            self.status.setStringValue_("未完成着色，请在宏面板查看错误。")
            print(f"字动力·彩字：{error}")
        self.arrange()

    @objc.python_method
    def refresh_mutation(self, font, changes):
        projection=getattr(self,'_quick_projection',None);self._quick_projection=None
        tracker=self._capacity_registry.get(font)
        accepted=projection is not None and tracker.committed(projection,{c.glyph.name for c in changes})
        if accepted:
            self._capacity=tracker.inventory;self._capacity_key=self.capacity_revision_key(font)
            state=self._statistics_cache.get(font);state.capacity_records=self._capacity.records;state.capacity_seen.clear()
        else:self._capacity=None
        if self._index and self._index.font==font:
            for change in changes:self._index.update(change.glyph)
            self._index_revision+=1
        if accepted:
            # The quick transaction changes layers, not palette identity or rows.
            # Paint actual committed data now; normal model notifications still
            # reconcile external palette/selection changes independently.
            self.update_swatch_selection(list(font.selectedLayers or ()))
            self.update_stats();self.arrange();self.queue_palette_stats()
        else:self.refresh_state()

    @objc.python_method
    def statistics_poll(self, font, selection=()):
        if not font:return
        state = self._statistics_cache.get(font)
        if state is None:return
        glyphs = []
        for layer in tuple(selection)[:16]:
            if layer.parent and layer.parent not in glyphs:glyphs.append(layer.parent)
        changed, capacity_changed = state.poll(glyphs)
        if capacity_changed:self._capacity=None
        if changed:self._index_revision += 1
        scope = tuple(self.batch_scope(font)[0])
        index = state.indexes.get(scope)
        if index is not self._index:
            self.stop_index()
            self._index = index
            self._stats_key = None
        if state.dirty or state.watch_position < len(state.glyphs):
            self.queue_palette_stats()
        elif self._capacity is None and self._capacity_scan is None:
            self.ensure_capacity(font)

    @objc.python_method
    def stop_index(self):
        if self._index_timer:
            self._index_timer.invalidate()
            self._index_timer = None

    @objc.python_method
    def start_index(self, force=False):
        if self._batch is not None:return
        _, font = self.context()
        masters = self.batch_scope(font)[0] if font else []
        if not masters:return
        index, created = self._statistics_cache.index(font, masters, force=force)
        if index is None:return
        if index is self._index and self._index_timer and not force:return
        self.stop_index()
        self._index = index
        if created:
            self._scan_perf = [perf_counter(), 0.0, 0.0]
            self._next_stats_paint = 0.0
            self._index_revision += 1
        if index.next_position < index.total:
            self._index_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(.02, self, "scanIndex:", None, True)
        self.update_stats()
        self.arrange()

    def refreshStats_(self, sender):
        self.invalidate_capacity(force=True)
        self.start_index(force=True)

    def cancelStats_(self, sender):
        if self._index_timer:
            self.stop_index()
            if self._index:
                state = self._statistics_cache.get(self._index.font)
                scope = self._index.master_ids
                state.indexes.pop(scope, None)
                state.cancelled.add(scope)
            self._index = None
            self._stats_key = None
            self.update_stats()
            self.stats_note.setStringValue_("已取消。点击「重新统计」再次扫描。")
            self.arrange()

    @objc.python_method
    def index_matches(self, font):
        return bool(font and font == self._index.font and len(font.glyphs) == self._index.total
                    and tuple(self.batch_scope(font)[0]) == self._index.master_ids)

    def scanIndex_(self, timer):
        if timer != self._index_timer:
            return
        _, font = self.context()
        if not self._index or font != self._index.font or not self.dialog.window():
            self.stop_index()
            self._index = None
            return
        if not self.index_matches(font):
            self.stop_index()
            self._index = None
            self.update_stats()
            self.arrange()
            return
        started = perf_counter()
        self._statistics_cache.get(font).watch_step(96)
        done = self._index.scan(96)
        elapsed = perf_counter() - started
        self._scan_perf[1] += elapsed
        self._scan_perf[2] = max(self._scan_perf[2], elapsed)
        if done:
            self.stop_index()
            self._index_revision += 1
            self._scan_perf[0] = perf_counter() - self._scan_perf[0]
        if done or started >= self._next_stats_paint:
            self._next_stats_paint = started + .10
            self.update_stats()
            self.arrange()

    @objc.python_method
    def batch_scope(self, font):
        if self._batch_scope_all:
            return [master.id for master in font.masters], f"全部母版 · {len(font.masters)} 个"
        master = font.selectedFontMaster
        return ([master.id], f"当前母版 · {master.name}") if master else ([], "未选母版")

    def batchScope_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        window = self.dialog.window()
        if not font or not window or self._batch is not None:
            return
        menu = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 260, 26), False)
        menu.addItemsWithTitles_([f"当前母版 · {font.selectedFontMaster.name}", "全部母版"])
        menu.selectItemAtIndex_(int(self._batch_scope_all))
        alert = NSAlert.alloc().init()
        alert.setMessageText_("选择母版范围")
        alert.setAccessoryView_(menu)
        alert.addButtonWithTitle_("取消")
        alert.addButtonWithTitle_("确定")

        def set_scope(result):
            if result == NSAlertSecondButtonReturn:
                self._batch_scope_all = menu.indexOfSelectedItem() == 1
                self.refresh_state()
                if self.expanded[3] and self._index is None:
                    self.start_index()

        alert.beginSheetModalForWindow_completionHandler_(window, set_scope)

    def batchAction_(self, sender):
        if not self.license_allows_action():
            return
        _, font = self.context()
        window = self.dialog.window()
        if not font or not window or window.attachedSheet() or self._batch is not None:
            return
        mode = BATCH_ACTIONS[sender.tag()][0]
        masters, scope = self.batch_scope(font)
        try:
            palettes = read_palettes(font)
            if palette_problem(palettes):
                return
        except (TypeError, ValueError, AttributeError) as error:
            self.palette_message(str(error))
            return
        valid = [i for i, color in enumerate(palettes[0]) if color is not None and i < FOREGROUND]
        if not masters or not valid:
            return
        targets = None
        if mode == "selected":
            targets = tuple(font.selection or ())
            if not targets:
                return
        self.end_color_edit()
        if self._index_timer:
            self.stop_index()
            self._index = None
            self._stats_key = None
        index = self._index
        self.cancel_quick()
        capacity_snapshot = self.capacity_snapshot()
        self.stop_capacity()
        self._capacity = None
        self._batch = Batch(font, masters, 0, valid, mode,
                            targets=targets, on_glyph=index.update if index else None, capacity_snapshot=capacity_snapshot)
        self._batch_palette_snapshot = palettes
        self._batch_result = ""
        self.make_batch_sheet(window, scope)
        self._batch_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            .012, self, "tickBatch:", None, True
        )
        self.update_stats()
        self.arrange()

    @objc.python_method
    def make_batch_sheet(self, window, scope):
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 430, 164), NSWindowStyleMaskTitled, NSBackingStoreBuffered, False
        )
        content = panel.contentView()
        self._batch_sheet = panel
        self._batch_window = window
        self._batch_scope_label = NSTextField.labelWithString_(scope)
        self._batch_scope_label.setFont_(NSFont.boldSystemFontOfSize_(14))
        content.addSubview_(self._batch_scope_label)
        self._batch_progress_text = NSTextField.wrappingLabelWithString_("正在预检查")
        content.addSubview_(self._batch_progress_text)
        self._batch_progress = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 12))
        self._batch_progress.setIndeterminate_(False)
        content.addSubview_(self._batch_progress)
        self._batch_cancel_button = NSButton.buttonWithTitle_target_action_("取消", self, "cancelBatch:")
        self._batch_cancel_button.setKeyEquivalent_("\x1b")
        content.addSubview_(self._batch_cancel_button)
        self._batch_confirm_button = NSButton.buttonWithTitle_target_action_("确认执行", self, "confirmBatch:")
        content.addSubview_(self._batch_confirm_button)
        self.layout_batch_sheet(confirm=False)
        window.beginSheet_completionHandler_(panel, None)

    @objc.python_method
    def layout_batch_sheet(self, *, confirm):
        panel = self._batch_sheet
        width = panel.contentView().bounds().size.width
        risk = bool(confirm and self._batch and self._batch.stage == "待风险确认")
        height = 330 if risk else 148 if confirm else 164
        if panel.contentView().bounds().size.height != height:
            panel.setContentSize_((width, height))

        for view, top, size in (
            (self._batch_scope_label, 8, 21),
            (self._batch_progress_text, 34, 230 if risk else 54),
            (self._batch_progress, 97, 12),
        ):
            view.setFrame_(NSMakeRect(20, height - top - size, width - 40, size))
            view.setAutoresizingMask_(NSViewMinYMargin | NSViewWidthSizable)

        cancel_width = 106 if confirm else 82
        if confirm:
            button_gap = 10
            cancel_x = (width - 2 * cancel_width - button_gap) / 2
            confirm_x = cancel_x + cancel_width + button_gap
            self._batch_confirm_button.setFrame_(NSMakeRect(confirm_x, 14, cancel_width, 30))
            self._batch_confirm_button.setAutoresizingMask_(NSViewMinXMargin | NSViewMaxXMargin)
        else:
            cancel_x = (width - cancel_width) / 2
        self._batch_cancel_button.setFrame_(NSMakeRect(cancel_x, 14, cancel_width, 30))
        self._batch_cancel_button.setAutoresizingMask_(NSViewMinXMargin | NSViewMaxXMargin)
        self._batch_confirm_button.setHidden_(not confirm)
        self._batch_progress.setHidden_(confirm)

    def cancelBatch_(self, sender):
        if self._batch is not None and self._batch.stage not in ("回滚", "已停止", "完成"):
            self._batch.abort("已取消")

    @objc.python_method
    def configure_batch(self, batch):
        if batch.mode != "all" or len(batch.plan) <= BATCH_CONFIRM_THRESHOLD:
            batch.begin_writes()
            return
        self._batch_confirm_button.setTitle_("确认执行")
        self.layout_batch_sheet(confirm=True)
        self._batch_progress_text.setStringValue_(
            f"即将重新分配 {len(batch.plan):,} 个字形的颜色。\n"
            "完成后无法通过一次 Cmd+Z 恢复。"
        )

    def confirmBatch_(self, sender):
        batch = self._batch
        if not batch:return
        try:
            if batch.stage == "待确认":batch.begin_writes()
            elif batch.stage == "待风险确认":batch.confirm_capacity()
            else:return
            self.layout_batch_sheet(confirm=False)
        except Exception as error:batch.abort(str(error))

    @objc.python_method
    def show_batch_capacity_notice(self, batch):
        self.layout_batch_sheet(confirm=True)
        self._batch_confirm_button.setTitle_("继续")
        self._batch_progress_text.setStringValue_("\n\n".join(batch.capacity_guard.warnings)+"\n\n确认后继续；取消不会写入。")
        self._batch_progress_text.setToolTip_(self._batch_progress_text.stringValue())

    def tickBatch_(self, timer):
        batch = self._batch
        if not batch:
            return
        if batch.stage not in ("回滚", "完成", "已停止") and not STORE.can_write():
            self.refresh_license_ui()
            batch.abort("授权已过期或不可用")
        if batch.stage in ("待确认", "待风险确认"):
            return
        if batch.stage in ("预检查", "分配颜色", "容量检查", "写入"):
            try:
                if read_palettes(batch.font) != self._batch_palette_snapshot:
                    batch.abort("原生色板已变化")
            except (TypeError, ValueError, AttributeError):
                batch.abort("无法验证原生色板")
        # Keep the same cap and per-glyph native checks; two extra milliseconds
        # avoid needless UI wakeups when native validation fills a write slice.
        batch.step(budget=.008 if batch.stage == "写入" else .006)
        if batch.stage == "待确认":
            self.configure_batch(batch)
        if batch.stage == "待风险确认":
            self.show_batch_capacity_notice(batch)
            return
        if batch.stage in ("完成", "已停止"):
            self.finish_batch()
            return
        if batch.stage != "待确认":
            value = batch.position if batch.stage in ("预检查", "容量检查") else batch.processed
            target = batch.total if batch.stage in ("预检查", "容量检查") else len(batch.assignments)
            text = (f"{batch.stage} · {value:,}/{target:,} · 跳过 {sum(batch.skips.values()):,}"
                    if batch.stage != "回滚" else f"正在回滚 · 剩余 {len(batch.applied):,} 项")
            self._batch_progress_text.setStringValue_(text)
            self._batch_progress.setMaxValue_(max(1, target))
            self._batch_progress.setDoubleValue_(value)
            self._batch_cancel_button.setEnabled_(batch.stage != "回滚")

    @objc.python_method
    def finish_batch(self):
        batch = self._batch
        self._batch_timer.invalidate()
        self._batch_timer = None
        if batch.stage == "完成":
            items = "，".join(f"{reason} {count:,}" for reason, count in batch.skips.items())
            self._batch_result = f"处理 {batch.processed:,} 字 · 跳过 {sum(batch.skips.values()):,} 字"
            self._batch_result += f" · 新建 {batch.created:,} 层 · 改号 {batch.changed:,} 层"
            if items:
                self._batch_result += " · " + items
        elif batch.failures:
            self._batch_result = f"回滚有 {len(batch.failures):,} 项异常。{batch.failures[0]}"
        else:
            self._batch_result = f"{batch.error}，本次改动已恢复。"
        self._batch = None
        tracker=self._capacity_registry.get(batch.font)
        if batch.stage=="完成" and tracker.committed(batch.capacity_guard.result,set(batch.plan)):
            self._capacity=tracker.inventory;self._capacity_key=self.capacity_revision_key(batch.font)
        else:self._capacity=None
        self.ensure_capacity(batch.font)
        if self._sync_draft:
            self.queue_palette_sync()
        self._batch_window.endSheet_(self._batch_sheet)
        self._batch_sheet.orderOut_(None)
        self._batch_sheet = self._batch_window = None
        self._index_revision += 1
        self.batch_result.setStringValue_(self._batch_result)
        self.batch_result.setToolTip_(self._batch_result)
        self.refresh_state()
        controller, _ = self.context()
        view = controller.activeViewController() if controller else None
        if view and view.respondsToSelector_("forceRedraw"):
            view.forceRedraw()
        Glyphs.redraw()

    @objc.python_method
    def update_stats(self):
        index = self._index
        running = self._index_timer is not None
        batch_running = self._batch is not None
        _, font = self.context()
        enabled_batch = bool(font and font.selectedFontMaster and not batch_running
                             and (self._license_view or {}).get("state") == "active")
        usable = bool(self._palettes and not self._palette_error and any(self._palettes[0]))
        self.batch_scan.setEnabled_(enabled_batch)
        for (mode, _, _), button in zip(BATCH_ACTIONS, self.batch_actions):
            button.setEnabled_(enabled_batch and usable
                               and (mode != "selected" or (self.expanded[2] and bool(font.selection))))
        self.stats_cancel.setEnabled_(running)
        row = self.palette_row()
        inv = self._capacity if font == self._capacity_font else None
        remaining = inv.remaining if inv and inv.known else None
        values = (remaining,) + ((index.total, index.colored, index.uncolored, index.missing, index.invalid_count(len(row)))
            if index and not running else (None,) * 5)
        for (_, cell), value in zip(self.stats_cells, values):
            cell.setStringValue_(f"{value:,}" if value is not None else "—")
        label, number = self.stats_cells[0]
        number.setStringValue_(f"{remaining:,}" if remaining is not None else "待计算")
        number.setTextColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(.77,.23,.23,1) if inv and inv.tone == 'red' else NSColor.colorWithSRGBRed_green_blue_alpha_(.76,.55,.12,1) if inv and inv.tone == 'gold' else NSColor.labelColor())
        hint = "当前字体还能安全容纳的额外字形资源数量，已考虑颜色层和导出所需空间。"
        label.setToolTip_(hint); number.setToolTip_(hint)
        self.stats_note.setStringValue_(
            f"正在统计 {index.next_position:,} / {index.total:,}" if running and index else ""
        )
        if inv and inv.hard_limit:
            self.stats_note.setStringValue_("当前字体已超过容量上限。")
        elif inv and not inv.known and not running:
            self.stats_note.setStringValue_("容量暂时无法准确计算；着色前将提示风险并由您确认。")
        elif inv and inv.known and inv.remaining == 0:
            self.stats_note.setStringValue_("当前字体容量已耗尽，不能再增加字形资源。")
        elif inv and inv.known and inv.remaining <= capacity.RESERVE:
            self.stats_note.setStringValue_("剩余空间已进入预留提醒区，仍可在最大容量内继续。")
        enabled = bool(index and not running and self.expanded[3])
        start = self._page * PAGE
        slots = ((FOREGROUND, None), *enumerate(row[start:start+PAGE], start)) if enabled else ()
        key = (id(index), self._index_revision, slots,
               tuple(index.indices[slot] for slot, _ in slots), enabled)
        if key == self._stats_key:
            return
        self._stats_key = key
        self.stats_palette.removeAllItems()
        hint = STATS_FILTER_TITLE
        self.stats_palette.setToolTip_(f"{hint} · 第 {self._page + 1} 页" if len(row) > PAGE else hint)
        self.stats_palette.addItemWithTitle_(hint)
        for slot, rgba in slots:
            count = index.indices[slot]
            proportion = count / index.colored if index.colored else 0
            label = "前景色 *" if slot == FOREGROUND else f"{slot} · {color_label(rgba)}"
            title = f"{label} · {count:,} 字 · {proportion:.1%}"
            self.stats_palette.addItemWithTitle_(title)
            item = self.stats_palette.lastItem()
            item.setTag_(slot)
            item.setEnabled_(bool(count))
            item.setToolTip_(tooltip(slot, rgba))
        self.stats_palette.menu().setAutoenablesItems_(False)
        self.stats_palette.setEnabled_(enabled)

    def filterColor_(self, sender):
        if self._index is None or sender.indexOfSelectedItem() <= 0:
            return
        names = sorted(self._index.by_color[sender.selectedItem().tag()])
        sender.selectItemAtIndex_(0)
        _, font = self.context()
        if names and font == self._index.font:
            font.newTab("".join("/" + name for name in names))
