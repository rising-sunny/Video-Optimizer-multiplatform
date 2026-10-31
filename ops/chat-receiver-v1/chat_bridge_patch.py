"""Narrow source adapters. Existing legacy approval and publication gates are retained."""
import ast,textwrap

def replace(source,node,text):
    lines=source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno]=[textwrap.indent(textwrap.dedent(text).strip()+'\n',' '*node.col_offset)]
    value=''.join(lines);compile(value,'chat_bridge_candidate','exec');return value

def core_candidate(source):
    tree=ast.parse(source)
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='approval')
    if 'verify_chat_approval' in ast.get_source_segment(source,function):raise RuntimeError('chat_approval_adapter_already_installed')
    matches=[n for n in function.body if isinstance(n,ast.If) and any(isinstance(v,ast.Constant) and v.value=='vision_tool_evidence_missing' for v in ast.walk(n))]
    if len(matches)!=1 or matches[0].orelse:raise RuntimeError('unexpected_approval_guard')
    original=ast.get_source_segment(source,matches[0])
    text="if trace.get('review_origin')=='codex_chat':\n    from chat_receiver import verify_chat_approval\n    verify_chat_approval(directory,channel,date,trace,a)\nelse:\n"+textwrap.indent(textwrap.dedent(original),'    ')
    value=replace(source,matches[0],text)
    new=next(n for n in ast.parse(value).body if isinstance(n,ast.FunctionDef) and n.name=='approval')
    guard=next(n for n in new.body if isinstance(n,ast.If) and n.orelse and isinstance(n.orelse[0],ast.If))
    if ast.dump(guard.orelse[0])!=ast.dump(matches[0]):raise RuntimeError('legacy_approval_changed')
    return value

def remote_candidate(source):
    tree=ast.parse(source)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Publisher')
    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    if 'require_publication_authorization' in ast.get_source_segment(source,node):raise RuntimeError('chat_publication_adapter_already_installed')
    first=node.body[0]
    if not isinstance(first,ast.Expr) or not isinstance(first.value,ast.Call) or not isinstance(first.value.func,ast.Name) or first.value.func.id!='approval':raise RuntimeError('unexpected_publisher_approval_order')
    lines=source.splitlines(keepends=True)
    indent=' '*first.col_offset
    lines.insert(first.end_lineno,indent+"if not self.dry:\n"+indent+"    from chat_receiver import require_publication_authorization\n"+indent+"    require_publication_authorization(self.directory,self.job)\n")
    value=''.join(lines);compile(value,'chat_publisher_candidate','exec')
    new=next(n for n in ast.parse(value).body if isinstance(n,ast.ClassDef) and n.name=='Publisher')
    run=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    if [ast.dump(n) for n in run.body[:1]+run.body[2:]]!=[ast.dump(n) for n in node.body]:raise RuntimeError('existing_publisher_changed')
    return value
