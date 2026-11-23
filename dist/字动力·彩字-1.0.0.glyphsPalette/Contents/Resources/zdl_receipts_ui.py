"""Native receipt viewer. Reads native-validated records; never writes an auth ledger."""
from datetime import datetime
from pathlib import Path
import json,os,tempfile
from AppKit import (NSWindow,NSWindowStyleMaskTitled,NSWindowStyleMaskClosable,NSBackingStoreBuffered,
                    NSMakeRect,NSButton,NSPopUpButton,NSSavePanel,NSModalResponseOK,NSPasteboard,NSPasteboardTypeString)
from zdl_product_ui import CZStats7ZDLColorProductContentView,static_label

class ReceiptWindow:
    def __init__(self,store):
        self.store=store;self.window=None;self.records=[];self.epoch=0

    def build(self,target):
        self.window=NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(0,0,570,414),NSWindowStyleMaskTitled|NSWindowStyleMaskClosable,NSBackingStoreBuffered,False)
        self.window.setReleasedWhenClosed_(False);self.window.setTitle_('字动力·彩字 · 注销凭证')
        body=CZStats7ZDLColorProductContentView.alloc().initWithFrame_(NSMakeRect(0,0,570,414));self.window.setContentView_(body)
        def label(text,frame,size=12,bold=False):
            f=static_label(text,size,bold=bold);f.setFrame_(NSMakeRect(*frame));body.addSubview_(f);return f
        label('注销凭证',(22,14,526,26),18,True)
        label('用于交给作者核对的注销申请凭据；不是作者数字签名，也不证明旧设备已彻底停用。',(22,48,526,34))
        self.choice=NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(22,88,526,26),False);self.choice.setTarget_(target);self.choice.setAction_('selectDeactivationReceipt:');body.addSubview_(self.choice)
        self.details=label('',(22,122,526,200))
        def button(text,selector,x):
            b=NSButton.buttonWithTitle_target_action_(text,target,selector);b.setFrame_(NSMakeRect(x,330,122,30));body.addSubview_(b);return b
        self.copy_button=button('复制凭证','copyDeactivationReceipt:',22)
        self.export_button=button('导出注销凭证…','exportDeactivationReceipt:',150)
        button('完成','closeDeactivationReceipts:',426)
        self.notice=label('',(22,369,526,34));self.window.center()

    def show(self,target):
        if self.window is None:self.build(target)
        self.records=self.store.receipts();self.choice.removeAllItems()
        for record in self.records:
            b=record['body'];when=datetime.fromtimestamp(b['deactivatedAt']).astimezone().strftime('%Y-%m-%d %H:%M')
            self.choice.addItemWithTitle_(b['licenseID'][:8]+' · '+when)
        self.choice.setEnabled_(bool(self.records))
        if self.records:self.choice.selectItemAtIndex_(len(self.records)-1)
        for b in (self.copy_button,self.export_button):b.setEnabled_(bool(self.records))
        self.update();self.window.makeKeyAndOrderFront_(None)

    def update(self):
        self.epoch+=1
        if not self.records:
            self.details.setStringValue_('此设备尚无注销凭证。');self.notice.setStringValue_('完成注销后，凭证会自动保留在本机历史中。');return
        index=self.choice.indexOfSelectedItem()
        if not 0<=index<len(self.records):return
        b=self.records[index]['body'];when=datetime.fromtimestamp(b['deactivatedAt']).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
        self.details.setStringValue_(f"产品名称：字动力·彩字\n产品身份：{b['product']}\n原授权编号：{b['licenseID']}\n原机器码：\n{b['oldMachine']}\n注销时间：{when}\n事件编号：{b['eventID']}\n原许可证 SHA-256：\n{b['licenseSHA256']}")
        self.notice.setStringValue_('完整凭证含原签名许可证。复制或导出不会删除本机历史。')

    def selected(self):
        index=self.choice.indexOfSelectedItem()
        if not 0<=index<len(self.records):raise ValueError('此设备尚无可选择的注销凭证。')
        header=self.records[index]['body'];record=self.store.receipt(header['eventID'])
        if {k:v for k,v in record['body'].items() if k!='licenseFile'}!=header:raise ValueError('注销历史已变化，请重新打开窗口。')
        return record

    def copy(self):
        try:
            data=json.dumps(self.selected(),ensure_ascii=False,sort_keys=True,indent=2)
            p=NSPasteboard.generalPasteboard();p.clearContents()
            if not p.setString_forType_(data,NSPasteboardTypeString):raise ValueError('无法写入剪贴板。')
            self.notice.setStringValue_('已复制完整注销凭证。')
        except Exception as e:self.notice.setStringValue_(str(e))

    def export(self):
        if not self.window or self.window.attachedSheet():return
        try:record=self.selected();data=json.dumps(record,ensure_ascii=False,sort_keys=True,indent=2).encode('utf8')
        except Exception as e:self.notice.setStringValue_(str(e));return
        panel=NSSavePanel.savePanel();panel.setTitle_('导出彩字注销凭证');panel.setAllowedFileTypes_(['czdeactivation']);panel.setAllowsOtherFileTypes_(False);panel.setCanCreateDirectories_(True);panel.setNameFieldStringValue_('彩字注销-'+record['body']['eventID']+'.czdeactivation')
        epoch=self.epoch
        def done(response):
            if response!=NSModalResponseOK or panel.URL() is None:return
            if not self.window.isVisible() or epoch!=self.epoch:return
            try:
                if self.selected()!=record:raise ValueError('凭证已变化，请重新导出。')
                path=Path(panel.URL().path());protected=self.store.protected_state_directory().resolve()
                resolved=path.resolve()
                if path.suffix.lower()!='.czdeactivation' or resolved==protected or protected in resolved.parents:raise ValueError('请选择独立的 .czdeactivation 导出文件。')
                fd,tmp=tempfile.mkstemp(prefix='.czreceipt-',dir=path.parent)
                try:
                    with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
                    os.replace(tmp,path)
                    directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
                    try:os.fsync(directory)
                    finally:os.close(directory)
                    if path.read_bytes()!=data:raise ValueError('导出回读不一致。')
                finally:
                    if os.path.exists(tmp):os.unlink(tmp)
                self.notice.setStringValue_('已导出到：'+str(path))
            except Exception as e:self.notice.setStringValue_('导出未确认，历史凭证仍保留：'+str(e))
        panel.beginSheetModalForWindow_completionHandler_(self.window,done)

    def close(self):
        self.epoch+=1
        if self.window:self.window.orderOut_(None)
