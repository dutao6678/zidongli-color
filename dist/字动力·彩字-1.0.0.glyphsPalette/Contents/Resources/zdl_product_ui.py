"""Product footer and independent information windows."""
from pathlib import Path
import json
import objc
from AppKit import (NSButton, NSTextField, NSView, NSScrollView, NSWindow, NSColor, NSFont,
    NSBezierPath, NSAttributedString, NSTextAlignmentLeft, NSFontAttributeName, NSForegroundColorAttributeName,
    NSMakeRect, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSBackingStoreBuffered)

FOOTER_HEIGHT = 30


class CZStats7ZDLColorProductStaticText(NSTextField):
    def menuForEvent_(self, event):
        return None

    def hitTest_(self, point):
        return None


class CZStats7ZDLColorProductContentView(NSView):
    def isFlipped(self):
        return True

    def menuForEvent_(self, event):
        return None


class CZStats7ZDLColorProductCircleButton(NSButton):
    # Same 24px / 2px inset / 14pt white-bold rendering as the series'
    # FPRProductButton (PaletteResponsive.m); no authorization state is shared.
    def drawRect_(self, dirty_rect):
        bounds = self.bounds()
        color = self.circle_color
        (color.colorWithAlphaComponent_(0.7) if self.isHighlighted() else color).setFill()
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(
            2, 2, max(0, bounds.size.width - 4), max(0, bounds.size.height - 4))).fill()
        text = NSAttributedString.alloc().initWithString_attributes_(self.title(), {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(14),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
        })
        size = text.size()
        text.drawAtPoint_(((bounds.size.width - size.width) / 2,
                          (bounds.size.height - size.height) / 2))


def metadata():
    return json.loads((Path(__file__).parent / 'product-info.json').read_text(encoding='utf-8'))


def footer_layout(width, content_bottom, viewport_height):
    """Append only; original module frames and the host scroll view stay intact."""
    top = max(content_bottom + 4, viewport_height - FOOTER_HEIGHT)
    inset = min(10, max(0, (width - 90) / 2))
    help_x = max(32, width - inset - 24)
    info_x = help_x - 30
    return dict(vip=(inset, top+4, max(0, min(64, info_x - inset - 2)), 22),
                info=(info_x, top+3, 24, 24),
                help=(help_x, top+3, 24, 24), height=top+FOOTER_HEIGHT)


def static_label(text, size=13, *, bold=False):
    label = CZStats7ZDLColorProductStaticText.wrappingLabelWithString_(text)
    label.setFont_((NSFont.boldSystemFontOfSize_ if bold else NSFont.systemFontOfSize_)(size))
    label.setTextColor_(NSColor.labelColor())
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setMaximumNumberOfLines_(0)
    return label


def circle_button(title, target, action, color, label):
    try:
        # Reuse the existing pure rendering component when present, never its
        # product window singleton, client, grant or authorization state.
        cls = objc.lookUpClass('FPRProductButton')
        if not cls.instancesRespondToSelector_('setCircleColor:'):
            cls = CZStats7ZDLColorProductCircleButton
    except objc.nosuchclass_error:
        cls = CZStats7ZDLColorProductCircleButton
    button = cls.buttonWithTitle_target_action_(title, target, action)
    if cls == CZStats7ZDLColorProductCircleButton:
        button.circle_color = color
    else:
        button.setCircleColor_(color)
    button.setBordered_(False)
    button.setRefusesFirstResponder_(True)
    button.setToolTip_(label)
    button.setAccessibilityLabel_(label)
    return button


def update_footer_license(button, status):
    state = status["state"]
    title = {"active": "VIP", "expired": "已过期", "revoked": "已注销"}.get(state, "未激活")
    color = (NSColor.colorWithSRGBRed_green_blue_alpha_(232 / 255, 161 / 255, 27 / 255, 1)
             if state == "active" else NSColor.systemGrayColor())
    button.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(11),
        NSForegroundColorAttributeName: color,
    }))
    button.setAccessibilityLabel_(title)


def create_footer(body, target):
    vip = NSButton.buttonWithTitle_target_action_("", target, "showLicense:")
    vip.setAlignment_(NSTextAlignmentLeft)
    update_footer_license(vip, {"state": "missing"})
    vip.setBordered_(False)
    vip.setRefusesFirstResponder_(True)
    vip.setToolTip_("打开字动力·彩字授权窗口")
    controls = dict(vip=vip,
        info=circle_button('i', target, 'showProductInfo:', NSColor.systemBlueColor(), '字动力·彩字信息'),
        help=circle_button('?', target, 'showProductHelp:', NSColor.systemGrayColor(), '字动力·彩字帮助中心'))
    for control in controls.values():
        body.addSubview_(control)
    return controls


HELP_TEXT = '''色彩套系
预置库用于选择套系。刷新只读取当前字体的原生色板；导入套系和导出套系用于保存及交换配色。

快速着色
单击颜色块，立即为选中字形图层着色。在普通色块的右键菜单中选择“编辑颜色”，打开 Glyphs 原生颜色选择器；确认后写入，取消保持原色。
“*”是前景色，独立于普通颜色槽。点击“+”添加颜色；没有原生色板时会自动创建。

删除颜色槽
右键普通色块，选择“删除色块”后直接执行。引用该槽的图层改用前一槽；删除 Color 0 时改为前景色。后续编号左移，全部母版及所有色板同步。前景色不能删除。

全字库处理
“母版范围”选择当前母版或全部母版。“均衡随机”“选中随机”“全部随机”按各自范围处理；操作前核对目标字体与母版。

统计 / 概况
“重新统计”刷新六项数据。“查看颜色对应”检查配色。TrueType 余量随字体结构变化刷新；黄色和红色表示空间逐渐减少，无法准确计算时显示“待计算”。

撤销与保存
⌘Z 撤销，⇧⌘Z 重做。删除颜色槽时，色板与全部图层引用一起恢复。修改后保存 Glyphs 工程以保留颜色及映射。

产品入口
左下角显示未激活、VIP 或已过期。点击可打开授权窗口。蓝色“i”显示本产品信息，“?”打开本帮助中心。'''


class ProductWindows:
    """Application-lifetime windows, with no palette/document/font ownership."""
    def __init__(self):
        self.windows = {}

    def _show(self, key, title, content, height):
        if key not in self.windows:
            window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(500, 250, 540, height),
                NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
                NSBackingStoreBuffered, False)
            window.setReleasedWhenClosed_(False)
            window.setTitle_(title)
            body = CZStats7ZDLColorProductContentView.alloc().initWithFrame_(NSMakeRect(0, 0, 540, height))
            window.setContentView_(body)
            heading = static_label(title, 18, bold=True)
            heading.setFrame_(NSMakeRect(20, 18, 500, 28))
            body.addSubview_(heading)
            scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(16, 62, 508, height-78))
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            text = static_label(content)
            text_width = 480
            text_height = text.cell().cellSizeForBounds_(NSMakeRect(0, 0, text_width-16, 10000)).height
            document = CZStats7ZDLColorProductContentView.alloc().initWithFrame_(
                NSMakeRect(0, 0, text_width, max(height-78, text_height+16)))
            text.setFrame_(NSMakeRect(8, 6, text_width-16, text_height+8))
            document.addSubview_(text)
            scroll.setDocumentView_(document)
            body.addSubview_(scroll)
            self.windows[key] = window
            window.center()
        window = self.windows[key]
        window.makeKeyAndOrderFront_(None)
        return window

    def info(self):
        data = metadata()
        content = f"版本：{data['version']}\n\n{data['copyright']}\n\n{data['description']}"
        probe = static_label(content)
        text_height = probe.cell().cellSizeForBounds_(NSMakeRect(0, 0, 464, 10000)).height
        height = max(180, 94 + text_height)
        return self._show('info', data['name']+' · 插件信息', content, height)

    def help(self):
        return self._show('help', metadata()['name']+' · 帮助中心', HELP_TEXT, 600)


product_windows = ProductWindows()
