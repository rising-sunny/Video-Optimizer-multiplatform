"""Apply native hooks to the implementation globals, including re-export modules."""
import sys
from pathlib import Path
import ast
import copy
from contextlib import contextmanager

def implementation(editorial):
    function=editorial.build
    module=sys.modules.get(function.__module__)
    if module is None or module.__dict__ is not function.__globals__:
        raise RuntimeError('workflow_native_implementation_unavailable')
    if not getattr(module,'__file__',None) or not Path(module.__file__).is_file():
        raise RuntimeError('workflow_native_source_unavailable')
    return module

def native_function(editorial,name):
    """Use the native body after its obsolete manual-migration sentinel only.

    The source-pinned file, sandbox, validation, rendering and review body stay
    unchanged. A different guard or function shape is never removed.
    """
    source=Path(editorial.__file__)
    tree=ast.parse(source.read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    first=node.body[0]
    expected=ast.parse("raise Blocked('generation_moved_to_codex_chat')").body[0]
    if ast.dump(first)!=ast.dump(expected):return getattr(editorial,name)
    if name not in ('build','invoke') or len(node.body)<2:
        raise RuntimeError('workflow_native_migration_shape_changed')
    node=copy.deepcopy(node);node.body=node.body[1:]
    tree=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(tree)
    # Function globals must stay the actual implementation namespace so the
    # existing manual_editorial source/music/review hooks take effect.
    code=compile(tree,str(source)+'::workflow-native','exec')
    namespace={};exec(code,editorial.__dict__,namespace)
    return namespace[name]

@contextmanager
def enabled(editorial,job,channel):
    """Enable the authorized native entry point and retain saved input snapshots."""
    import workflow_common as c
    old_build,old_invoke=editorial.build,editorial.invoke
    original_load=getattr(editorial,'load',None)
    music=getattr(editorial,'mp',None);original_catalogue=getattr(music,'catalogue',None)
    job=Path(job)
    def load(path,*args,**kwargs):
        if original_load is not None and Path(path)==Path(editorial.ROOT)/'runtime/production/history.json' and (job/'history-input.json').is_file():
            saved=c.read(job/'history-input.json')
            return dict(channels={ch:{network:[dict(row,description=row.get('text','')) for row in rows]
                for network,rows in networks.items()} for ch,networks in saved.items()})
        return original_load(path,*args,**kwargs)
    def catalogue(directory,selected_channel,topic):
        if Path(directory)!=job or selected_channel!=channel:raise RuntimeError('workflow_music_scope_changed')
        if (job/'music-input.json').is_file():
            music.rights(channel)
            return c.read(job/'music-input.json')
        return original_catalogue(directory,selected_channel,topic)
    try:
        editorial.build=native_function(editorial,'build')
        editorial.invoke=native_function(editorial,'invoke')
        if original_load is not None:editorial.load=load
        if original_catalogue is not None:music.catalogue=catalogue
        yield
    finally:
        editorial.build,editorial.invoke=old_build,old_invoke
        if original_load is not None:editorial.load=original_load
        if original_catalogue is not None:music.catalogue=original_catalogue
