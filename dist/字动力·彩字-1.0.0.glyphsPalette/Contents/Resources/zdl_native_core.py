"""Bundled, narrow native core. No Glyphs setters and no Python algorithm fallback."""
from pathlib import Path
import ctypes,hashlib,json,os,stat,subprocess,threading,time
ROOT=Path(__file__).resolve().parent
_LOCK=threading.RLock()
_CLIENT=None
class NativeUnavailable(RuntimeError):pass
_MESSAGES={'verified':'授权有效。','expired':'授权已过期。','license_revoked':'此许可证已在本机注销，不能重新激活。','clock_rollback':'检测到系统时间回退，请校正系统时间。','clock_record':'本地时间校验记录损坏。','state_busy':'授权事务正在执行，请稍后重试。','longer_license_preserved':'现有授权期限更长，已保留原许可证。','commit_uncertain':'授权提交结果尚未确认，请重新查看状态。','no_installed_license':'请先激活字动力·彩字。','not_yet_valid':'许可证尚未生效。'}
_MESSAGES.update({'state_temp':'无法创建授权事务临时文件，请检查磁盘空间及权限。','state_write':'授权资料写入失败，请检查磁盘空间及权限。','state_sync':'授权资料同步失败，提交未完成。','state_replace':'无法提交授权资料，请检查磁盘及权限。','state_readback':'授权资料回读未确认，请重新核查状态。','ledger_size':'注销历史超过容量限制，原历史不会删除。','not_deactivatable':'当前没有可注销的已核验许可证。','confirmation_invalid':'确认已失效，请重新打开注销确认。','confirmation_changed':'确认期间许可证或注销历史已变化，请重新核对。','confirmation_busy':'存在未结束的注销确认，请稍后重试。','deactivation_failed':'注销未完成，请重新检查设备状态与凭证。','receipt_missing':'未找到这份注销凭证。','ledger_identity':'注销账本产品、版本或本机归属不匹配。','receipt_integrity':'注销凭证完整性或设备身份校验失败。','receipt_license':'注销凭证与原签名许可证不一致。','ledger_duplicate':'注销账本存在重复事件或授权。','commit_uncertain':'注销提交结果尚未确认，请重新检查状态及历史凭证，不要认为操作未发生。'})
def _read_json(pointer,release):
 if not pointer:raise NativeUnavailable('原生组件无响应。')
 try:return json.loads(ctypes.string_at(pointer).decode('utf8'))
 finally:release(pointer)
class NativeCore:
 def __init__(self):
  self._integrity_records={}
  self.manifest=json.loads((ROOT/'native-manifest.json').read_text(encoding='utf-8'))
  self.verify()
  bundle=ROOT.parent.parent
  p=subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(bundle)],capture_output=True,timeout=10)
  if p.returncode:raise NativeUnavailable('候选资源签名校验失败。')
  self.a=ctypes.CDLL(str(ROOT/'Native/libCZAuthC3.dylib'),mode=ctypes.RTLD_LOCAL)
  self.b=ctypes.CDLL(str(ROOT/'Native/libCZAlgorithmsC3.dylib'),mode=ctypes.RTLD_LOCAL)
  def signature(lib,name,args):
   fn=getattr(lib,name);fn.argtypes=args;fn.restype=ctypes.c_void_p;return fn
  self.afree=signature(self.a,'zdl_cz4_free_v1',[ctypes.c_void_p]);self.afree.restype=None
  self.bfree=signature(self.b,'zdl_cz4_compute_free_v1',[ctypes.c_void_p]);self.bfree.restype=None
  self._status=signature(self.a,'zdl_cz4_status_v1',[]);self._machine=signature(self.a,'zdl_cz4_machine_v1',[])
  self._write_allowed=getattr(self.a,'zdl_cz4_write_allowed_v1');self._write_allowed.argtypes=[];self._write_allowed.restype=ctypes.c_int32
  self._info=signature(self.a,'zdl_cz4_info_v1',[])
  self._import=signature(self.a,'zdl_cz4_import_v1',[ctypes.c_char_p,ctypes.c_ssize_t])
  self._prepare=signature(self.a,'zdl_cz4_deactivation_prepare_v1',[])
  self._deactivate=signature(self.a,'zdl_cz4_deactivation_commit_v1',[ctypes.c_char_p,ctypes.c_ssize_t])
  self._cancel_deactivation=signature(self.a,'zdl_cz4_deactivation_cancel_v1',[ctypes.c_char_p,ctypes.c_ssize_t])
  self._receipts=signature(self.a,'zdl_cz4_receipts_v1',[])
  self._receipt=signature(self.a,'zdl_cz4_receipt_v1',[ctypes.c_char_p,ctypes.c_ssize_t])
  self._compute=signature(self.b,'zdl_cz4_compute_v1',[ctypes.c_char_p,ctypes.c_ssize_t])
  info=_read_json(self._info(),self.afree)
  if info.get('abi')!=1 or Path(info.get('bundle','')).resolve()!=bundle.resolve():raise NativeUnavailable('加载了不属于当前候选的原生模块。')
  self.state_directory=Path(info['stateDirectory']);self.verify()
 def verify(self):
  for name,record in self.manifest['libraries'].items():
   try:
    with os.fdopen(os.open(ROOT/'Native'/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
     before=os.fstat(f.fileno())
     if not stat.S_ISREG(before.st_mode) or before.st_size!=record['size']:raise NativeUnavailable('原生模块类型或大小不匹配。')
     stamp=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns,before.st_mode)
     if self._integrity_records.get(name)!=stamp:
      digest=hashlib.sha256(f.read()).hexdigest()
      after=os.fstat(f.fileno())
      final=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_mode)
      if stamp!=final or digest!=record['sha256']:raise NativeUnavailable('原生模块完整性校验失败。')
      self._integrity_records[name]=stamp
   except OSError as e:raise NativeUnavailable('原生模块缺失或无法读取。') from e
 def can_write(self):
  self.verify();allowed=self._write_allowed();self.verify();return allowed==1
 def status(self):
  self.verify();v=_read_json(self._status(),self.afree);self.verify();v['message']=_MESSAGES.get(v.get('reason'),v.get('reason','授权状态不可用。'));return v
 def machine(self):
  self.verify();v=_read_json(self._machine(),self.afree)
  if 'machine' not in v:raise NativeUnavailable('无法读取本机机器码。')
  return v['machine']
 def install_bytes(self,data):
  self.verify();v=_read_json(self._import(data,len(data)),self.afree);self.verify()
  if v.get('state')!='active' or not v.get('imported'):raise NativeUnavailable(_MESSAGES.get(v.get('reason'),v.get('reason','许可证不可用。')))
  return v
 def prepare_deactivation(self):
  self.verify();v=_read_json(self._prepare(),self.afree);self.verify()
  if not v.get('prepared'):raise NativeUnavailable(_MESSAGES.get(v.get('reason'),v.get('reason','无法准备注销。')))
  return v
 def deactivate(self,token):
  if not isinstance(token,str) or len(token)!=36:raise NativeUnavailable('确认令牌无效。')
  data=token.encode('utf8');self.verify();v=_read_json(self._deactivate(data,len(data)),self.afree);self.verify()
  if not v.get('committed') or v.get('state')!='revoked':raise NativeUnavailable(_MESSAGES.get(v.get('reason'),v.get('reason','注销结果尚未确认。')))
  return v
 def cancel_deactivation(self,token):
  if not isinstance(token,str) or len(token)!=36:raise NativeUnavailable('确认令牌无效。')
  data=token.encode('utf8');self.verify();v=_read_json(self._cancel_deactivation(data,len(data)),self.afree);self.verify()
  if not v.get('cancelled'):raise NativeUnavailable('确认取消未完成。')
 def receipts(self):
  self.verify();v=_read_json(self._receipts(),self.afree);self.verify()
  if 'receipts' not in v:raise NativeUnavailable(_MESSAGES.get(v.get('reason'),v.get('reason','注销历史无法读取。')))
  return v['receipts']
 def receipt(self,event):
  if not isinstance(event,str) or len(event)!=36:raise NativeUnavailable('凭证事件编号无效。')
  data=event.encode('utf8');self.verify();v=_read_json(self._receipt(data,len(data)),self.afree);self.verify()
  if 'receipt' not in v:raise NativeUnavailable(_MESSAGES.get(v.get('reason'),v.get('reason','注销凭证无法读取。')))
  return v['receipt']
 def calculate_timed(self,request):
  self.verify();t=time.perf_counter();data=json.dumps(request,ensure_ascii=False,allow_nan=False).encode();encoding=time.perf_counter()-t
  if not 1<=len(data)<=8_000_000:raise NativeUnavailable('计算输入超出支持范围。')
  t=time.perf_counter();pointer=self._compute(data,len(data));abi=time.perf_counter()-t
  t=time.perf_counter();v=_read_json(pointer,self.bfree);decoding=time.perf_counter()-t;self.verify()
  if v.get('state')!='ok':raise NativeUnavailable('原生计算已拒绝：'+str(v.get('reason','unknown')))
  return v,dict(pythonEncodeSeconds=encoding,ctypesCallSeconds=abi,pythonDecodeSeconds=decoding)
 def calculate(self,request):return self.calculate_timed(request)[0]
def core():
 global _CLIENT
 with _LOCK:
  if _CLIENT is None:_CLIENT=NativeCore()
  return _CLIENT
def balanced(names,slots,seed):return dict(core().calculate(dict(op='balanced',names=list(names),slots=list(slots),seed=str(seed)))['assignments'])
def delete_map(indices,removed,count):return core().calculate(dict(op='deleteMap',indices=list(indices),removed=removed,count=count))['indices']
def cycle_slots(count):return core().calculate(dict(op='cycleSlots',count=count))['slots']
def feature_codes(entries,owner):return core().calculate(dict(op='featureCodes',entries=entries,owner=owner))['codes']
