"""Private local imports; never replaces production zdl_* entries in sys.modules."""
from pathlib import Path
import builtins,sys,types,hashlib
_NAMESPACES={}
class Namespace:
 def __init__(self,resources):
  self.resources=Path(resources).resolve();self.modules={}
  self.prefix='zdl_native_private_'+hashlib.sha256(str(self.resources).encode()).hexdigest()[:12]+'_'
  self.allowed={p.stem for p in self.resources.glob('*.py') if p.stem not in ['plugin','zdl_namespace'] and not p.name.startswith('._')}
 def module(self,name):
  if name in self.modules:return self.modules[name]
  if name not in self.allowed:raise ImportError('Not a packaged module: '+name)
  key=self.prefix+name;mod=types.ModuleType(key);mod.__file__=str(self.resources/(name+'.py'));mod.__package__=''
  def scoped_import(n,g=None,l=None,fromlist=(),level=0):
   if not level and n in self.allowed:return self.module(n)
   return builtins.__import__(n,g,l,fromlist,level)
  mod.__dict__['__builtins__']=dict(vars(builtins),__import__=scoped_import);self.modules[name]=mod;sys.modules[key]=mod
  try:
   exec(compile(Path(mod.__file__).read_bytes(),mod.__file__,'exec'),mod.__dict__)
  except BaseException:
   self.modules.pop(name,None);sys.modules.pop(key,None);raise
  return mod
def namespace(resources):
 key=str(Path(resources).resolve())
 if key not in _NAMESPACES:_NAMESPACES[key]=Namespace(resources)
 return _NAMESPACES[key]
