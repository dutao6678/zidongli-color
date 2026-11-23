"""Sliced, projected COLR capacity monitoring. No exporter or geometry writer.

Known static Glyphs 3532 instances use native interpolation masks, single-layer
roles, and aligned multi-layer sequences. Uncalibrated structures stay unknown and require
explicit consent; only proven absolute overflow is a capacity veto.
"""
from dataclasses import dataclass, field
from math import isfinite
from time import perf_counter
import re

from zdl_license import authorized_write

LIMIT = 65535
RESERVE = 1024
TARGET = LIMIT - RESERVE  # Reminder only; never a generation veto.
FOREGROUND = 65535
SAFE_PARAMS = frozenset(('Color Palettes','Export COLR Table','Color Palette for CPAL','vendorID','panose',
 'unicodeRanges','codePageRanges','fsType','ROS','glyphOrder','uniqueID','fileName',
 'Use Typo Metrics','typoAscender','typoDescender','typoLineGap','hheaAscender',
 'hheaDescender','hheaLineGap','winAscent','winDescent','weightClass','widthClass',
 'Disable autohinting','Autohint','Remove Overlap','copyright','license','licenseURL','description','trademark',
 'versionString','compatibleFullName','preferredFamilyName','preferredSubfamilyName',
 'postscriptFontName','postscriptFullName','familyName','styleName','Use Production Names'))

class CapacityError(ValueError): pass
class StructureError(ValueError): pass
class ConfirmationRequired(ValueError): pass

@dataclass
class GlyphRecord:
    export: bool
    rows: tuple
    problems: tuple = ()
    illegal: str = ''

@dataclass
class Inventory:
    known: bool = False
    reason: str = '当前字体容量暂时无法准确计算。'
    per_instance: tuple = ()
    gids: int | None = None
    names: frozenset = frozenset()
    base_total: int = 0
    details: tuple = ()
    records: dict = field(default_factory=dict)
    masters: tuple = ()
    signature: object = None
    revision: object = None
    font: object = None
    slot_count: int = 0
    illegal: tuple = ()
    appearance: dict = field(default_factory=dict)
    @property
    def remaining(self): return LIMIT-self.gids if self.known else None
    @property
    def hard_limit(self):return bool(self.known and self.gids is not None and self.gids>LIMIT) or any(n is not None and n>LIMIT for _,n in self.per_instance) or any(d.get('lower_bound',0)>LIMIT for d in self.details)
    @property
    def tone(self):
        if not self.known:return 'pending'
        if self.remaining<=RESERVE or self.remaining<LIMIT*.05:return 'red'
        if self.remaining<LIMIT*.20:return 'gold'
        return 'normal'


def _environment_problem():
    try:
        from GlyphsApp import Glyphs
    except ImportError:return ''
    try:known=float(Glyphs.buildNumber)==3532
    except (ValueError,TypeError):known=False
    return '' if known else '当前 Glyphs 导出版本尚未核验。'

def _parameter_problem(obj):
    for p in obj.customParameters:
        if not getattr(p,'active',True):continue
        if p.name not in SAFE_PARAMS:return '导出设置尚未核验：'+p.name
        if p.name=='Export COLR Table' and not bool(p.value):return '关闭颜色表的导出设置尚未核验。'
        if p.name=='Autohint' and bool(p.value):return '开启自动提示的导出设置尚未核验。'
    return ''

def _slot(value):
    try:
        n=int(value)
        return n if value==n else -1
    except (TypeError,ValueError,OverflowError):return -1

def _color(layer):
    try:return bool(layer.isColorPaletteLayer())
    except AttributeError:return False

def document_revision(font):
    """Public NSDocument token: stable for paint/focus, changed by edits.
    Undo/redo additionally invalidates through the palette's notification epoch.
    """
    try:
        d=font.parent
        return d.changeCountTokenForSaveOperation_(0) if d else None
    except (AttributeError,TypeError):return None

def export_signature(font):
    def params(o):return tuple((p.name,str(p.value)) for p in o.customParameters if getattr(p,'active',True) and p.name!='Color Palettes')
    def weights(i):
        try:return tuple(sorted((str(k),float(v)) for k,v in dict(i.instanceInterpolations).items()))
        except (AttributeError,TypeError,ValueError):return None
    return (tuple((m.id,tuple(getattr(m,'axes',()))) for m in font.masters),params(font),
            tuple((i.name,bool(i.active),getattr(i,'type',0),tuple(getattr(i,'axes',())),weights(i),params(i)) for i in font.instances))

def _instance_specs(font,masters):
    bits={mid:1<<n for n,mid in enumerate(masters)};specs=[]
    global_problem=_environment_problem() or _parameter_problem(font)
    for n,i in enumerate(font.instances):
        if not i.active:continue
        problem=global_problem or _parameter_problem(i);mask=0;weights={}
        if getattr(i,'type',0)!=0:problem='可变导出实例尚未核验。'
        try:
            if len(masters)==1:weights={masters[0]:1.0}
            else:weights={str(k):float(v) for k,v in dict(i.instanceInterpolations).items()}
            if not weights or any(k not in bits or not isfinite(v) or v<0 for k,v in weights.items()) or abs(sum(weights.values())-1)>1e-7:
                raise ValueError('实例插值权重尚未核验。')
            mask=sum(bits[k] for k,v in weights.items() if v!=0)
            if not mask:raise ValueError('实例没有有效的母版插值关系。')
        except (AttributeError,TypeError,ValueError) as e:problem=problem or str(e)
        specs.append({'index':n,'name':i.name,'mask':mask,'weights':weights,'reason':problem,'count':0,'base_certain':not bool(problem)})
    return specs

def _record(g,masters,slots,override=None):
    rows=[[] for _ in masters];bits={mid:1<<n for n,mid in enumerate(masters)};problems=[];illegal=''
    if not g.export:return GlyphRecord(False,tuple(tuple(x) for x in rows))
    if re.search(r'\.layer\d+$',g.name):problems.append(((1<<len(masters))-1,'已有辅助字形命名尚未核验：'+g.name))
    for l in g.layers:
        mid=l.associatedMasterId;mask=bits.get(mid,(1<<len(masters))-1)
        if _color(l):
            value=l.attributes['colorPalette']
            try:slot=int(value)
            except (TypeError,ValueError,OverflowError):slot=-1
            if mid not in bits:illegal=f'{g.name} 的颜色层关联了不存在的母版：{mid}'
            elif override is None:
                if value!=slot or (slot!=FOREGROUND and not 0<=slot<slots):illegal=f'{g.name} / {mid} 的颜色槽引用无效。'
                rows[masters.index(mid)].append(slot)
        elif l.isSpecialLayer:problems.append((mask,f'{g.name} / {mid} 的特殊插值图层尚未核验。'))
        if set(dict(l.attributes))-{'colorPalette'}:problems.append((mask,f'{g.name} / {mid} 的特殊图层属性尚未核验。'))
        for c in getattr(l,'components',()):
            if getattr(c,'smartComponentValues',None):problems.append((mask,f'{g.name} / {mid} 的智能组件尚未核验。'))
            try:target=c.component
            except Exception:target=None
            if target is None:problems.append((mask,f'{g.name} / {mid} 的组件引用尚未核验。'))
            elif getattr(target,'smartComponentAxes',None) or not target.export:problems.append((mask,f'{g.name} / {mid} 的组件导出结构尚未核验。'))
    if override is not None:rows=[list(x) for x in override]
    for n,row in enumerate(rows):
        if slots==0 and row:problems.append((1<<n,f'{g.name} / {masters[n]} 无原生色板的导出结构尚未核验。'))
        if len(set(row))!=len(row):problems.append((1<<n,f'{g.name} / {masters[n]} 存在重复颜色层角色，尚未核验。'))
        if any(x!=FOREGROUND and not 0<=x<slots for x in row):illegal=f'{g.name} / {masters[n]} 的颜色槽引用无效。'
    return GlyphRecord(True,tuple(tuple(x) for x in rows),tuple(problems),illegal)

def _helper_count(rec, mask):
    active=[row for n,row in enumerate(rec.rows) if mask & (1<<n)]
    if not active or not any(active):return 0
    if all(len(row)<=1 for row in active):return len({row for row in active if row})
    if len(set(active))==1:return len(active[0])
    return None  # Mixed multi-layer sequences need additional native calibration.

class Scan:
    """Budgeted native metadata scan; optionally patch a revision-verified snapshot."""
    def __new__(cls,font,rows=(),*,overrides=None,focus=None,prior=None):
        slots=len(rows[0]) if rows and len({len(r) for r in rows})==1 and all(c is not None for r in rows for c in r) else 0
        if (prior is not None and getattr(prior,'ledger',None) is not None
            and len(prior.ledger.records)==prior.base_total and prior.font==font
            and prior.revision==document_revision(font) and prior.signature==export_signature(font)
            and prior.base_total==len(font.glyphs) and prior.slot_count==slots
            and prior.masters==tuple(m.id for m in font.masters)):
            return IncrementalScan(font,rows,overrides=overrides,focus=focus,prior=prior)
        return super().__new__(cls)
    def __init__(self,font,rows=(),*,overrides=None,focus=None,prior=None):
        TASK_METRICS["fullScans"]+=1
        self.font=font;self.total=len(font.glyphs);self.masters=tuple(m.id for m in font.masters);self.position=0;self.result=None
        self.signature=export_signature(font);self.revision=document_revision(font)
        self.slot_count=len(rows[0]) if rows and len({len(r) for r in rows})==1 and all(x is not None for r in rows for x in r) else 0
        self.overrides=overrides or {};self.focus=set(focus) if focus is not None else None
        self.specs=_instance_specs(font,self.masters);self.records={};self.names=set();self.problem='';self.ledger=ContributionLedger(self.specs)
        self.patched=bool(prior and prior.font==font and prior.revision is not None and prior.revision==self.revision and prior.signature==self.signature and prior.base_total==self.total and prior.slot_count==self.slot_count and prior.masters==self.masters)
        if self.patched:
            self.records=dict(prior.records);self.work_names=list(self.overrides)
        else:self.work_names=None
        if not self.masters:self.problem='字体没有母版。'
        if not self.specs:self.problem='没有可核验的启用导出实例。'
    def step(self,limit=64,budget=.006):
        if self.result is not None:return True
        if len(self.font.glyphs)!=self.total:self.problem='字体结构已变化，请重新计算。'
        start=perf_counter();total=len(self.work_names) if self.patched else self.total
        if not self.problem:
            try:
                count=0
                while self.position<total and count<limit:
                    g=self.font.glyphs[self.work_names[self.position]] if self.patched else self.font.glyphs[self.position]
                    TASK_METRICS["fullRecords"]+=1
                    self.records[g.name]=_record(g,self.masters,self.slot_count,self.overrides.get(g.name))
                    self.position+=1;count+=1
                    if perf_counter()-start>=budget:break
            except Exception as e:self.problem='容量结构尚未核验：'+str(e)
            if self.position<total and not self.problem:return False
        # Counting is sliced too: no O(glyphs*instances) final timer tick.
        if not hasattr(self,'count_items'):
            self.count_items=iter(self.records.items());self.base=0;self.illegal=[];self.appearance={'no_color':set(),'partial':set(),'unknown':set()}
        if not self.problem:
            count=0
            while count<limit:
                try:name,rec=next(self.count_items)
                except StopIteration:break
                count+=1
                self.ledger.add(name,rec)
                if not rec.export:continue
                self.names.add(name);self.base+=1
                if rec.illegal:self.illegal.append(rec.illegal)
                role_masks={}
                for n,row in enumerate(rec.rows):
                    if row:role_masks[row]=role_masks.get(row,0)|(1<<n)
                union=0
                for mask in role_masks.values():union|=mask
                for spec in self.specs:
                    reason=next((why for mask,why in rec.problems if spec['mask']&mask),'')
                    if reason and not spec['reason']:spec['reason']=reason
                    helpers=_helper_count(rec,spec['mask'])
                    if helpers is None:
                        if not spec['reason']:spec['reason']=f'{name} 的多颜色层母版组合尚未核验。'
                    else:spec['count']+=helpers
                    if self.focus is None or name in self.focus:
                        if union and not union&spec['mask']:self.appearance['no_color'].add(spec['index'])
                        if any(mask&spec['mask'] and spec['mask']&~mask for mask in role_masks.values()):self.appearance['partial'].add(spec['index'])
                if perf_counter()-start>=budget:return False
            else:return False
            # An exhausted iterator is distinguished from a budgeted slice.
            try:item=next(self.count_items)
            except StopIteration:pass
            else:
                import itertools
                self.count_items=itertools.chain((item,),self.count_items);return False
        implicit=sum(n not in self.names for n in ('.notdef','space'));details=[];per=[]
        for spec in self.specs:
            reason=self.problem or spec['reason'] or (self.illegal[0] if self.illegal else '')
            n=None if reason else self.base+implicit+spec['count'];per.append((spec['name'],n))
            details.append({**spec,'gids':n,'reason':reason,'lower_bound':self.base+implicit if spec['base_certain'] and not self.problem else 0})
            if reason:self.appearance['unknown'].add(spec['index'])
        known=bool(details) and all(n is not None for _,n in per)
        reason=self.problem or next((d['reason'] for d in details if d['reason']),'')
        self.result=Inventory(known,reason,tuple(per),max(n for _,n in per) if known else None,frozenset(self.names),self.total,tuple(details),self.records,self.masters,self.signature,self.revision,self.font,self.slot_count,tuple(self.illegal),self.appearance)
        self.result.ledger=self.ledger;self.result.ledger_version=0;self.result.updates={}
        return True

def inventory(font,rows=(),**kwargs):
    scan=Scan(font,rows,**kwargs)
    while not scan.step(128):pass
    return scan.result

class Guard:
    def __init__(self,font,changes,rows,*,prior=None):
        self.font=font;self.changes=tuple(changes);self.rows=rows;self.prior=prior
        self.identities=tuple((c,str(c.glyph.name),str(c.layer.associatedMasterId)) for c in self.changes)
        self.signature=export_signature(font);self.revision=document_revision(font);self.total=len(font.glyphs)
        self.masters=tuple(m.id for m in font.masters);self.position=0;self.matrices={};self.result=None;self.scan=None
        self.done=False;self.confirmed=False;self.projected=None;self.target_masters=set()
        self.tracker=getattr(prior,"tracker",None);self.identity_position=0;self.validation_epoch=None;self.validated_epoch=None
    def observed_epoch(self):
        tracker=self.tracker
        if tracker and not tracker.closed and not tracker.failures and not tracker.root_dirty and tracker.watch_position==len(self.font.glyphs):return tracker.epoch
        return None
    def validate_identity(self,item):
        change,name,mid=item
        if str(change.glyph.name)!=name or self.font.glyphs[name]!=change.glyph or str(change.layer.associatedMasterId)!=mid:raise StructureError('目标字形身份已变化，未写入。')
        if change.created:
            if any(_color(l) and str(l.associatedMasterId)==mid for l in change.glyph.layers):raise StructureError('目标颜色层已由其他操作创建。')
        elif change.glyph.layers[change.layer.layerId]!=change.layer or change.layer.attributes['colorPalette']!=change.before:raise StructureError('目标颜色层已变化，未写入。')
    def validate_metadata(self):
        if len(self.font.glyphs)!=self.total or self.signature!=export_signature(self.font):raise StructureError('字体或导出设置已变化，请重新操作。')
        if self.revision is not None and self.revision!=document_revision(self.font):raise StructureError('字体已变化，请重新操作。')
    def validate_unchanged(self):
        self.validate_metadata()
        if self.validated_epoch is not None:
            if self.observed_epoch()!=self.validated_epoch:raise StructureError('预检后字体结构已变化，请重新操作。')
            return
        for item in self.identities:self.validate_identity(item)
    def validate_sliced(self,limit,budget):
        epoch=self.observed_epoch()
        if epoch is None:
            self.validate_unchanged();return True
        if self.validation_epoch is None:self.validation_epoch=epoch
        if epoch!=self.validation_epoch:raise StructureError('预检期间字体结构已变化，请重新操作。')
        self.validate_metadata();start=perf_counter();count=0
        while self.identity_position<len(self.identities) and count<limit:
            self.validate_identity(self.identities[self.identity_position]);self.identity_position+=1;count+=1
            if perf_counter()-start>=budget:break
        if self.identity_position<len(self.identities):return False
        self.validated_epoch=epoch;return True
    def step(self,limit=64,budget=.006):
        if self.done:return True
        if not self.changes:self.done=True;self.result=Inventory(known=False,reason='没有需要写入的目标。');return True
        start=perf_counter();slots=len(self.rows[0]) if self.rows else 0
        count=0
        while self.position<len(self.changes) and count<limit:
            c=self.changes[self.position];g=c.glyph;mid=c.layer.associatedMasterId
            if self.font.glyphs[g.name]!=g or mid not in self.masters:raise StructureError(f'{g.name} 的目标母版或字形已变化。')
            source=g.layers[mid]
            if source is None or not source.isMasterLayer:raise StructureError(f'{g.name} / {mid} 当前母版缺少有效基础层，请检查相关字形。')
            if c.after!=FOREGROUND and not 0<=c.after<slots:raise StructureError(f'{g.name} / {mid} 的目标颜色槽无效。')
            self.target_masters.add(mid)
            if g.name not in self.matrices:
                self.matrices[g.name]=[[(str(l.layerId),_slot(l.attributes['colorPalette'])) for l in g.layers if _color(l) and l.associatedMasterId==m] for m in self.masters]
            row=self.matrices[g.name][self.masters.index(mid)]
            if c.created:
                if row:raise StructureError(f'{g.name} / {mid} 颜色层已变化，请重新操作。')
                row.append(('new',c.after))
            else:
                if g.layers[c.layer.layerId]!=c.layer or c.layer.attributes['colorPalette']!=c.before:raise StructureError(f'{g.name} / {mid} 颜色引用已变化，请重新操作。')
                n=next((j for j,(key,_) in enumerate(row) if key==str(c.layer.layerId)),None)
                if n is None:raise StructureError(f'{g.name} / {mid} 未找到目标颜色层。')
                row[n]=(row[n][0],c.after)
            self.position+=1;count+=1
            if perf_counter()-start>=budget:break
        if self.position<len(self.changes):return False
        if self.scan is None:
            overrides={name:tuple(tuple(slot for _,slot in row) for row in matrix) for name,matrix in self.matrices.items()}
            self.scan=Scan(self.font,self.rows,overrides=overrides,focus=self.matrices,prior=self.prior)
        if not self.scan.step(limit,budget):return False
        if not self.validate_sliced(limit,budget):return False
        self.result=self.scan.result
        if self.result.illegal:raise StructureError('本次修改后的图层结构不合法：'+self.result.illegal[0])
        self.projected=self.result.gids
        if self.result.hard_limit:raise CapacityError('本次操作将超过TrueType最大字形数量，无法生成。')
        self.done=True;return True
    @property
    def warnings(self):
        if not self.done or not self.changes:return ()
        messages=[]
        if not self.result.known:messages.append('当前字体容量暂时无法准确计算，请确认后继续。\n原因：'+self.result.reason)
        elif self.result.remaining<=RESERVE:messages.append('当前字体剩余空间已进入预留提醒区；这不是强制限制。')
        app=self.result.appearance
        if app.get('no_color') or app.get('partial'):
            prefix='当前操作只处理选中的母版，' if len(self.target_masters)<len(self.masters) else '部分母版的颜色层对应关系尚不完整，'
            messages.append(prefix+'部分导出实例可能无法显示完整彩色字形，或彩色轮廓可能与原始实例不一致。若需要所有实例保持一致，建议选择全部母版并保持颜色层对应一致。')
        elif app.get('unknown'):messages.append('部分导出实例的着色表现尚未核验，请确认后继续。')
        return tuple(messages)
    @property
    def requires_confirmation(self):
        if not self.done or not self.changes:return False
        return not self.result.known or any(self.result.appearance.get(k) for k in ('no_color','partial','unknown'))
    def authorize(self,confirmed=False):
        if not self.done:raise StructureError('本次预检尚未完成。')
        self.validate_unchanged()
        if self.requires_confirmation and not (confirmed or self.confirmed):raise ConfirmationRequired('\n\n'.join(self.warnings))
        self.confirmed=True

def check(font,changes,rows,*,confirmed=False):
    guard=Guard(font,changes,rows)
    while not guard.step():pass
    guard.authorize(confirmed)
    return guard

@authorized_write
def apply_atomic(font,changes,apply):
    try:return apply(font,changes)
    except Exception:
        from zdl_batch import restore_change,quiet_undo
        failures=[]
        for c in reversed(changes):
            try:
                if c.created and not c.layer.layerId:continue
                with quiet_undo(c.glyph):restore_change(c)
            except Exception as e:failures.append(str(e))
        if failures:raise RuntimeError('着色失败且回滚异常：'+failures[0])
        raise

# A contribution ledger is private to a single GSFont. No font writes occur here.
from collections import Counter, ChainMap
TASK_METRICS=Counter()

def _contribution(rec, specs, name=""):
    TASK_METRICS["contributions"]+=1
    if not rec.export:return (0, '', tuple((0, '', False, False) for _ in specs))
    roles={}
    for n,row in enumerate(rec.rows):
        if row:roles[row]=roles.get(row,0)|(1<<n)
    union=0
    for mask in roles.values():union|=mask
    values=[]
    for spec in specs:
        mask=spec['mask'];reason=next((why for bits,why in rec.problems if mask&bits),'')
        helpers=_helper_count(rec,mask)
        if helpers is None:reason=reason or f'{name} 的多颜色层母版组合尚未核验。'
        values.append((helpers or 0,reason,bool(union and not union&mask),any(bits&mask and mask&~bits for bits in roles.values())))
    return (1,rec.illegal,tuple(values))

class ContributionLedger:
    def __init__(self, specs):
        self.specs=[{**s,'count':0} for s in specs];self.records={};self.parts={};self.base=0
        self.slot_names={}
        self.counts=[0]*len(specs);self.reasons=[Counter() for _ in specs];self.no_color=[0]*len(specs);self.partial=[0]*len(specs);self.illegal=Counter();self.version=0
    def add(self,name,rec):
        for row in rec.rows:
            for slot in row:self.slot_names.setdefault(slot,set()).add(name)
        part=_contribution(rec,self.specs,name);self.records[name]=rec;self.parts[name]=part;self.adjust(part,1)
    def adjust(self,part,sign):
        base,illegal,values=part;self.base+=sign*base
        if illegal:
            self.illegal[illegal]+=sign
            if not self.illegal[illegal]:del self.illegal[illegal]
        for j,(count,reason,no,partial) in enumerate(values):
            self.counts[j]+=sign*count;self.no_color[j]+=sign*no;self.partial[j]+=sign*partial
            if reason:
                self.reasons[j][reason]+=sign
                if not self.reasons[j][reason]:del self.reasons[j][reason]
    def preview(self,prior,updates,focus=None):
        parts={name:_contribution(rec,self.specs,name) for name,rec in updates.items()}
        if any(name not in self.records for name in updates):raise StructureError('容量字形集合已变化，请完整核验。')
        try:
            for name,part in parts.items():self.adjust(self.parts[name],-1);self.adjust(part,1)
            specs=[];per=[];appearance={'no_color':set(),'partial':set(),'unknown':set()}
            implicit=sum(name not in prior.names for name in ('.notdef','space'))
            first_illegal=next(iter(self.illegal),'')
            for j,spec in enumerate(self.specs):
                reason=spec['reason'] or first_illegal or next(iter(self.reasons[j]),'')
                n=None if reason else self.base+implicit+self.counts[j]
                per.append((spec['name'],n));specs.append({**spec,'count':self.counts[j],'gids':n,'reason':reason,'lower_bound':self.base+implicit if spec['base_certain'] else 0})
                if focus is None:no,partial=self.no_color[j]>0,self.partial[j]>0
                else:
                    selected=[parts.get(name,self.parts.get(name)) for name in focus]
                    no=any(p and p[2][j][2] for p in selected);partial=any(p and p[2][j][3] for p in selected)
                if no:appearance['no_color'].add(spec['index'])
                if partial:appearance['partial'].add(spec['index'])
                if reason:appearance['unknown'].add(spec['index'])
            known=bool(per) and all(n is not None for _,n in per)
            result=Inventory(known,('' if known else next((s['reason'] for s in specs if s['reason']),prior.reason or '容量结构尚未核验。')),tuple(per),max(n for _,n in per) if known else None,prior.names,prior.base_total,tuple(specs),ChainMap(updates,self.records),prior.masters,prior.signature,document_revision(prior.font),prior.font,prior.slot_count,tuple(self.illegal),appearance)
            result.ledger=self;result.ledger_version=self.version;result.updates=updates
            result.tracker=getattr(prior,"tracker",None)
            return result
        finally:
            for name,part in parts.items():self.adjust(part,-1);self.adjust(self.parts[name],1)
    def commit(self,result):
        if result.ledger_version!=self.version:raise StructureError('容量快照已被另一笔操作更新。')
        for name,rec in result.updates.items():
            old=self.records[name]
            for slot in {slot for row in old.rows for slot in row}:
                self.slot_names[slot].discard(name)
                if not self.slot_names[slot]:del self.slot_names[slot]
            self.adjust(self.parts[name],-1);self.add(name,rec)
        self.version+=1;result.ledger_version=self.version;result.records=self.records;result.updates={}

class IncrementalScan:
    def __init__(self,font,rows,*,overrides=None,focus=None,prior=None):
        TASK_METRICS["deltaScans"]+=1
        self.font=font;self.prior=prior;self.overrides=overrides or {};self.focus=focus;self.work_names=list(self.overrides);self.position=0;self.total=len(self.work_names);self.updates={};self.result=None;self.patched=True
    def step(self,limit=64,budget=.006):
        if self.result is not None:return True
        start=perf_counter();masters=self.prior.masters
        for _ in range(limit):
            if self.position==self.total:break
            name=self.work_names[self.position];g=self.font.glyphs[name]
            if g is None:raise StructureError('目标字形已删除。')
            TASK_METRICS["deltaRecords"]+=1
            self.updates[name]=_record(g,masters,self.prior.slot_count,self.overrides.get(name));self.position+=1
            if perf_counter()-start>=budget:return False
        if self.position<self.total:return False
        self.result=self.prior.ledger.preview(self.prior,self.updates,self.focus);return True

try:
    import objc, weakref
    from Foundation import NSObject
    class CZCapacityIncrementalObserver(NSObject):
        def observeValueForKeyPath_ofObject_change_context_(self,key,obj,change,context):
            tracker=self.owner_ref()
            if tracker is None or tracker.closed:return
            tracker.epoch+=1
            glyph=tracker.object_glyphs.get(id(obj))
            if glyph is not None:
                tracker.dirty[id(glyph)]=glyph
                state=tracker.statistics
                if state is not None and not state.closed:
                    state.dirty[id(glyph)]=glyph
                    registry=state.registry()
                    if registry:registry.wake()
                if str(key) in ('layers','shapes'):tracker.layer_resync.add(id(glyph))
            elif str(key) in ('customParameters','userData'):tracker.benign_root_dirty=True
            else:tracker.root_dirty=True
except ImportError:
    CZCapacityIncrementalObserver=None

class Tracker:
    """KVO-backed capacity epoch; NSDocument tokens remain a fallback and guard.

    A revision change requires observed model events, complete observer coverage
    and matching export/slot signatures. Unexplained tokens, unknown coverage,
    collection changes and structural root changes require a full scan.
    """
    def __init__(self,font):
        self.font=font;self.epoch=0;self.closed=False;self.dirty={};self.root_dirty=False;self.benign_root_dirty=False;self.inventory=None;self.watches=[];self.failures=[];self.watched={};self.glyph_watches={};self.layer_watches={};self.object_glyphs={};self.layer_resync=set();self.seen_ids=set();self.watch_position=0;self.cold_changed=False;self.initial_revision=document_revision(font)
        self.statistics=None
        self.metrics=Counter(fullScans=0,deltaScans=0,commits=0,revisionReconciliations=0)
        self.observer=CZCapacityIncrementalObserver.alloc().init() if CZCapacityIncrementalObserver else None
        if self.observer:self.observer.owner_ref=weakref.ref(self)
        for key in ('glyphs','fontMasters','instances','customParameters','userData'):self.watch(font,key)
    def watch(self,obj,key,group=None):
        if self.observer is None:self.failures.append(key);return
        try:
            obj.addObserver_forKeyPath_options_context_(self.observer,key,0,None)
            (self.watches if group is None else group).append((obj,key))
        except Exception as e:self.failures.append((key,str(e)))
    def remove_group(self,group):
        for obj,key in group:
            try:obj.removeObserver_forKeyPath_(self.observer,key)
            except Exception:pass
            self.object_glyphs.pop(id(obj),None)
    def watch_layers(self,glyph):
        ident=id(glyph);self.remove_group(self.layer_watches.pop(ident,[]));group=[]
        for layer in glyph.layers:
            self.object_glyphs[id(layer)]=glyph
            for key in ('attributes','associatedMasterId','name','shapes'):self.watch(layer,key,group)
            for component in layer.components:
                self.object_glyphs[id(component)]=glyph
                for key in ('componentName','pieceSettings'):self.watch(component,key,group)
        self.layer_watches[ident]=group;self.layer_resync.discard(ident)
    def watch_step(self,limit=64):
        if self.watch_position<len(self.font.glyphs):
            if document_revision(self.font)!=self.initial_revision:self.cold_changed=True
            for n in range(self.watch_position,min(len(self.font.glyphs),self.watch_position+limit)):
                g=self.font.glyphs[n];ident=id(g);self.seen_ids.add(ident)
                self.watched[ident]=(str(g.name),bool(getattr(g,'smartComponentAxes',None)))
                if ident not in self.glyph_watches:
                    self.object_glyphs[ident]=g;group=[]
                    for key in ('changeCount','layers','export','name','partsSettings'):self.watch(g,key,group)
                    self.glyph_watches[ident]=group;self.watch_layers(g)
                elif ident in self.layer_resync:self.watch_layers(g)
                self.watch_position=n+1
            if self.watch_position==len(self.font.glyphs):
                for ident in set(self.glyph_watches)-self.seen_ids:
                    self.remove_group(self.glyph_watches.pop(ident));self.remove_group(self.layer_watches.pop(ident,[]));self.watched.pop(ident,None)
    def close(self):
        self.closed=True;self.statistics=None;self.remove_group(self.watches)
        for group in self.glyph_watches.values():self.remove_group(group)
        for group in self.layer_watches.values():self.remove_group(group)
        self.watches.clear();self.glyph_watches.clear();self.layer_watches.clear();self.watched.clear();self.object_glyphs.clear();self.dirty.clear();self.inventory=None
    def compatible(self,rows):
        inv=self.inventory
        slots=len(rows[0]) if rows and len({len(r) for r in rows})==1 and all(c is not None for r in rows for c in r) else 0
        valid=bool(inv and inv.base_total==len(self.font.glyphs) and inv.signature==export_signature(self.font) and inv.masters==tuple(m.id for m in self.font.masters) and not self.root_dirty)
        if valid and inv.slot_count!=slots:
            affected=set();previous=inv.slot_count
            for slot,names in inv.ledger.slot_names.items():
                if previous==0 or slots==0 or (slot!=FOREGROUND and slot>=min(previous,slots)):affected.update(names)
            for name in affected:
                g=self.font.glyphs[name]
                if g is None:return False
                self.dirty[id(g)]=g
            inv.slot_count=slots
        return valid
    def snapshot(self,rows,targets=()):
        if not self.compatible(rows):return None
        inv=self.inventory;revision=document_revision(self.font)
        complete=self.watch_position==len(self.font.glyphs) and not self.failures
        if revision!=inv.revision and (not complete or not (self.dirty or self.benign_root_dirty)):return None
        if len(inv.records)!=inv.base_total:
            # No export instances/masters: retain an honest unknown diagnostic,
            # not a fabricated exact ledger or a new empty scan on each repaint.
            if (not inv.details or not inv.masters) or (not self.dirty and revision==inv.revision):
                inv.revision=revision;inv.capacity_epoch=self.epoch;self.dirty.clear();self.benign_root_dirty=False
                return inv
            return None
        work=dict(self.dirty)
        for g in targets:work[id(g)]=g
        if len(work)>32:return None  # Background reconciliation remains sliced.
        updates={}
        for ident,g in work.items():
            if ident in self.layer_resync:self.watch_layers(g)
            identity=(str(g.name),bool(getattr(g,'smartComponentAxes',None)))
            if g.parent!=self.font or self.watched.get(ident)!=identity:return None
            if g.name not in inv.records:return None
            rec=_record(g,inv.masters,inv.slot_count)
            if rec.export!=inv.records[g.name].export:return None # May affect dependent components.
            if rec!=inv.records[g.name]:updates[g.name]=rec
        if updates:
            projection=inv.ledger.preview(inv,updates);inv.ledger.commit(projection);inv=projection;self.metrics['deltaScans']+=1
        if revision!=inv.revision:self.metrics['revisionReconciliations']+=1
        inv.revision=revision;self.inventory=inv
        for ident in work:self.dirty.pop(ident,None)
        inv.capacity_epoch=self.epoch;self.benign_root_dirty=False
        return inv
    def scan(self,rows):
        prior=self.snapshot(rows)
        if prior is not None:return None
        # Large dirty sets: patch only known targets, unless root/coverage is uncertain.
        if self.compatible(rows) and not self.failures and self.watch_position==len(self.font.glyphs) and self.dirty:
            inv=self.inventory;overrides={}
            for ident,g in self.dirty.items():
                if ident in self.layer_resync:self.watch_layers(g)
                if g.parent!=self.font or self.watched.get(ident)!=(str(g.name),bool(getattr(g,'smartComponentAxes',None))) or g.name not in inv.records or bool(g.export)!=inv.records[g.name].export:break
                overrides[g.name]=None
            else:
                # Re-read records without forcing a new role matrix.
                inv.revision=document_revision(self.font);self.metrics['deltaScans']+=1
                return IncrementalScan(self.font,rows,overrides=overrides,prior=inv)
        # Reuse valid observers; enumerate/reconcile membership during a full scan.
        self.watch_position=0;self.seen_ids.clear()
        self.initial_revision=document_revision(self.font);self.cold_changed=False
        self.metrics['fullScans']+=1
        return Scan(self.font,rows)
    def accept(self,result):
        if getattr(result,'updates',None):result.ledger.commit(result)
        result.records=result.ledger.records
        result.tracker=self
        result.revision=document_revision(self.font);result.capacity_epoch=self.epoch
        self.inventory=result;self.dirty.clear();self.root_dirty=False;self.benign_root_dirty=False;self.cold_changed=False
    def committed(self,result,names):
        # A known plan never consumes unrelated external changes.
        if self.root_dirty or result.base_total!=len(self.font.glyphs) or result.signature!=export_signature(self.font):self.inventory=None;return False
        if len(names)>32:
            # Reconcile observed dirty targets in existing sliced capacity task.
            # Until verified, the UI shows pending; no unverified projection is accepted.
            return False
        for g in self.dirty.values():
            if g.name not in names and (g.parent!=self.font or g.name not in result.records or _record(g,result.masters,result.slot_count)!=result.records[g.name]):self.inventory=None;return False
        if not result.known and len(result.records)!=result.base_total:
            self.accept(result);self.metrics['commits']+=1;return True
        for name in names:
            g=self.font.glyphs[name]
            if g and id(g) in self.layer_resync:self.watch_layers(g)
            if not g or _record(g,result.masters,result.slot_count)!=result.records[name]:self.inventory=None;return False
        self.accept(result);self.metrics['commits']+=1;return True

class Registry:
    def __init__(self):
        self.documents={}
        try:
            from GlyphsApp import Glyphs,DOCUMENTDIDCLOSE
            self.Glyphs=Glyphs;self.close_event=DOCUMENTDIDCLOSE;Glyphs.addCallback(self.document_closed,DOCUMENTDIDCLOSE)
        except ImportError:self.Glyphs=None
    def get(self,font):
        doc=font.parent
        if doc not in self.documents:self.documents[doc]=Tracker(font)
        return self.documents[doc]
    def document_closed(self,note):
        doc=note.object() if hasattr(note,'object') else note
        tracker=self.documents.pop(doc,None)
        if tracker:tracker.close()
    def close(self):
        if self.Glyphs:self.Glyphs.removeCallback(self.document_closed)
        for tracker in self.documents.values():tracker.close()
        self.documents.clear()
