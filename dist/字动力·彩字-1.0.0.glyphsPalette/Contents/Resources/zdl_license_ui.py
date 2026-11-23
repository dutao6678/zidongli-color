"""Native modeless activation window with separate source and term labels."""
import weakref
from Foundation import NSTimer
from zdl_license_presentation import presentation
from pathlib import Path

from AppKit import (NSBackingStoreBuffered, NSButton, NSColor, NSFont, NSMakeRect, NSModalResponseOK,
                    NSOpenPanel, NSPasteboard, NSPasteboardTypeString, NSTextField, NSWindow,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskTitled)
from zdl_license import STORE
from zdl_receipts_ui import ReceiptWindow
from AppKit import NSAlert, NSAlertSecondButtonReturn
from zdl_product_ui import CZStats7ZDLColorProductContentView, static_label


def label_for(status):
    return presentation(status)['title']


class LicenseWindow:
    def __init__(self):
        self.window = None
        self.code = ""
        self.receipts = ReceiptWindow(STORE)
        self.confirming = False
        self.timer = None
        self.last_notice = ""

    def show(self, target):
        if self.window is None:
            self.build(target)
        try:
            self.code = STORE.machine()
            self.machine.setStringValue_(self.code)
        except Exception:
            self.code = ""
            self.machine.setStringValue_("无法读取设备标识，请重新打开授权窗口重试。")
        self.copy_button.setEnabled_(bool(self.code))
        self.import_button.setEnabled_(bool(self.code))
        self.last_notice = None
        self.refresh(STORE.status())
        self.window.makeKeyAndOrderFront_(None)
        self.start_refresh_timer()

    def build(self, target):
        width, height = 570, 277
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("字动力·彩字 · 授权")
        body = CZStats7ZDLColorProductContentView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        self.window.setContentView_(body)

        def label(title, frame, **options):
            field = static_label(title, **options)
            field.setFrame_(NSMakeRect(*frame))
            body.addSubview_(field)
            return field

        def button(title, selector, frame):
            control = NSButton.buttonWithTitle_target_action_(title, target, selector)
            control.setFrame_(NSMakeRect(*frame))
            body.addSubview_(control)
            return control

        label("字动力·彩字", (22, 14, 360, 26), size=18, bold=True)
        self.state = label("", (450, 17, 98, 22), size=14, bold=True)
        self.fields = {}
        for key, title, y in (("source", "授权来源", 50), ("term", "授权类型", 71),
                              ("end", "到期时间", 92), ("remaining", "剩余时间", 113)):
            caption = label(title, (22, y, 80, 20))
            caption.setTextColor_(NSColor.secondaryLabelColor())
            self.fields[key] = label("—", (110, y, 438, 20))
        label("本机机器码", (22, 142, 526, 20))
        self.machine = NSTextField.alloc().initWithFrame_(NSMakeRect(22, 164, 526, 24))
        self.machine.setEditable_(False)
        self.machine.setSelectable_(True)
        self.machine.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11, 0))
        body.addSubview_(self.machine)
        self.copy_button = button("复制机器码", "copyLicenseMachine:", (22, 197, 122, 30))
        self.import_button = button("导入授权文件…", "importLicense:", (156.6666666667, 197, 122, 30))
        self.deactivate_button = button("注销此设备", "deactivateLicense:", (291.3333333333, 197, 122, 30))
        self.receipts_button = button("查看注销凭证", "showDeactivationReceipts:", (426, 197, 122, 30))
        button("关闭", "closeLicense:", (426, 231, 122, 30))
        self.notice = label("", (22, 235, 390, 26), size=12)
        self.notice.setTextColor_(NSColor.secondaryLabelColor())
        self.window.center()

    def refresh(self, value):
        if self.window is None:
            return
        view = presentation(value)
        self.deactivate_button.setEnabled_(view['state'] in ('active', 'expired') and not self.confirming)
        self.receipts_button.setEnabled_(value.get('reason') != 'native_unavailable')
        self.state.setStringValue_(view['title'])
        self.state.setTextColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(232 / 255, 161 / 255, 27 / 255, 1)
                                 if view['gold'] else NSColor.systemGrayColor())
        for key, field in self.fields.items():
            field.setStringValue_(view[key])
        # Preserve copy/import feedback when the same verified verdict is polled.
        if view['notice'] != self.last_notice:
            self.last_notice = view['notice']
            self.notice.setStringValue_(view['notice'])

    def start_refresh_timer(self):
        if self.timer is not None:
            return
        reference = weakref.ref(self)

        def tick(timer):
            owner = reference()
            if owner is None or owner.window is None or not owner.window.isVisible():
                timer.invalidate()
                if owner is not None:
                    owner.timer = None
                return
            # Recheck the native verdict: no persisted activation boolean and
            # no cached verdict used to continue past expiry or revocation.
            owner.refresh(STORE.status())

        self.timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(1.0, True, tick)

    def copy(self):
        if not self.code:
            return
        clipboard = NSPasteboard.generalPasteboard()
        clipboard.clearContents()
        clipboard.setString_forType_(self.code, NSPasteboardTypeString)
        self.notice.setStringValue_("已复制机器码。")

    def import_file(self, target):
        if self.window is None or self.window.attachedSheet() or not self.code:
            return
        panel = NSOpenPanel.openPanel()
        panel.setTitle_("导入彩字正式许可证")
        panel.setMessage_("请选择字动力·彩字的 .czlicense 文件。")
        panel.setAllowedFileTypes_(["czlicense"])
        panel.setAllowsOtherFileTypes_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)

        def done(response):
            if response != NSModalResponseOK or panel.URL() is None:
                return
            try:
                STORE.install(Path(panel.URL().path()))
                target.refresh_state(sync_only=True)
                self.refresh(STORE.status())
                self.notice.setStringValue_("激活成功。")
            except Exception as failure:
                self.notice.setStringValue_(f"未激活该许可证：{failure}")

        panel.beginSheetModalForWindow_completionHandler_(self.window, done)

    def notify(self, target):
        target.licenseTick_(target._license_timer)
        target.refresh_state(sync_only=True)

    def deactivate(self, target):
        if self.confirming or not self.window or self.window.attachedSheet():return
        def busy():
            return any(getattr(target,k,None) is not None for k in ('_batch','_quick_guard','_color_edit')) or bool(getattr(target,'_pending_palette_operations',()))
        if busy():
            self.notice.setStringValue_('请先完成或取消着色、容量预检及颜色编辑，再注销设备。');return
        try:prepared=STORE.prepare_deactivation()
        except Exception as e:self.notice.setStringValue_(str(e));return
        token=prepared['token'];alert=NSAlert.alloc().init()
        alert.setMessageText_('确认注销此设备的授权？')
        alert.setInformativeText_('注销后，这台电脑将无法继续使用彩字的着色和配色功能。已有字体和配色数据不会受到影响。\n\n如需更换电脑，请保存注销凭证，并将凭证与新电脑机器码一起提供给作者核对。')
        cancel=alert.addButtonWithTitle_('取消');confirm=alert.addButtonWithTitle_('确认注销')
        cancel.setKeyEquivalent_('\r');confirm.setKeyEquivalent_('');alert.window().setDefaultButtonCell_(cancel.cell())
        self.confirming=True;self.deactivate_button.setEnabled_(False)
        def done(response):
            self.confirming=False
            if response!=NSAlertSecondButtonReturn:
                try:STORE.cancel_deactivation(token)
                except Exception:pass
                self.refresh(STORE.status());return
            try:
                if not self.window.isVisible() or busy():raise ValueError('窗口或任务状态已变化，请重新确认。')
                STORE.deactivate(token)
            except Exception as e:
                self.notify(target);self.refresh(STORE.status());self.notice.setStringValue_(str(e));return
            self.notify(target);self.refresh(STORE.status())
            self.notice.setStringValue_('此设备已注销，凭证已保留在本机历史中。')
            self.show_receipts(target)
        alert.beginSheetModalForWindow_completionHandler_(self.window,done)

    def show_receipts(self,target):
        try:self.receipts.show(target)
        except Exception as e:self.notice.setStringValue_('注销历史无法读取，原文件已保留：'+str(e))
