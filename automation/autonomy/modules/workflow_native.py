"""Apply native hooks to the implementation globals, including re-export modules."""
import sys
from pathlib import Path

def implementation(editorial):
    function=editorial.build
    module=sys.modules.get(function.__module__)
    if module is None or module.__dict__ is not function.__globals__:
        raise RuntimeError('workflow_native_implementation_unavailable')
    if not getattr(module,'__file__',None) or not Path(module.__file__).is_file():
        raise RuntimeError('workflow_native_source_unavailable')
    return module
