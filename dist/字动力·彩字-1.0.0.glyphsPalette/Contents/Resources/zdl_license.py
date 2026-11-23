"""Candidate native authorization; original Python write scopes are preserved."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import os,stat
from zdl_native_core import core,NativeUnavailable
_SCOPE=ContextVar("zdl_color_write_transaction",default=False)
class LicenseDenied(ValueError):pass
class LicenseRevoked(LicenseDenied):pass

def read_regular(path,limit):
 with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
  if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise LicenseDenied('所选文件不是普通文件。')
  data=f.read(limit+1)
 if len(data)>limit:raise LicenseDenied('许可证文件过大。')
 return data
class LicenseStore:
 def machine(self):
  try:return core().machine()
  except Exception as e:raise LicenseDenied(str(e)) from e
 def can_write(self):
  try:return core().can_write()
  except Exception:return False
 def status(self):
  try:return core().status()
  except Exception as e:return dict(state='invalid',reason='native_unavailable',message=str(e))
 def install(self,path):
  if path.suffix.lower()!='.czlicense':raise LicenseDenied('请选择正式的 .czlicense 文件。')
  try:return core().install_bytes(read_regular(path,65536))
  except Exception as e:raise LicenseDenied(str(e)) from e
 def prepare_deactivation(self):return core().prepare_deactivation()
 def deactivate(self,token):return core().deactivate(token)
 def cancel_deactivation(self,token):return core().cancel_deactivation(token)
 def receipts(self):return core().receipts()
 def receipt(self,event):return core().receipt(event)
 def protected_state_directory(self):return core().state_directory
STORE=LicenseStore()

def require_write():
    if not _SCOPE.get() and not STORE.can_write():
        value = STORE.status()
        message = value.get("message", "授权不可用。") if value["state"] != "active" else "授权状态在检查期间变化，请重试。"
        raise LicenseDenied(message)

@contextmanager
def restore_write():
    """Only used by a batch restoring snapshots of its own earlier writes."""
    token = _SCOPE.set(True)
    try:
        yield
    finally:
        _SCOPE.reset(token)

def authorized_write(function):
    @wraps(function)
    def apply(*args, **kwargs):
        require_write()
        with restore_write():
            return function(*args, **kwargs)
    return apply
