"""Glyphs SDK bootstrap. Packaged imports use a private namespace, without test hooks."""
from pathlib import Path
import importlib.util,sys,hashlib
ROOT=Path(__file__).resolve().parent
name='zdl_cz_bootstrap_'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
_bytecode=sys.dont_write_bytecode
try:
 sys.dont_write_bytecode=True
 if name not in sys.modules:
  spec=importlib.util.spec_from_file_location(name,ROOT/'zdl_namespace.py');module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
finally:
 sys.dont_write_bytecode=_bytecode
ZDL_NAMESPACE=sys.modules[name].namespace(ROOT)
CZStats7IntegratedColorGlyphsPalette=ZDL_NAMESPACE.module('plugin_impl').CZStats7IntegratedColorGlyphsPalette
