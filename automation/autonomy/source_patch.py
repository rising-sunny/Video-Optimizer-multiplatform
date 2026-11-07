"""Narrow adaptations of the actual installed sources; never replace unknown code."""
import ast

def replace(text,before,after):
    if text.count(before)!=1:raise RuntimeError('workflow_installed_source_shape_changed')
    value=text.replace(before,after,1);ast.parse(value);return value

def shorts_handoff(text):
    if 'removed_single_redundant_object_close' not in text:
        text=replace(text,"    dsml=bool(suffix.strip())\n",
            "    redundant_close=isinstance(data,dict) and suffix.strip()=='}'\n"
            "    if redundant_close:suffix=''\n    dsml=bool(suffix.strip())\n")
        text=replace(text,"    changes=[]\n","    changes=[]\n    if redundant_close:changes.append(dict(kind='removed_single_redundant_object_close',count=1))\n")
    if 'from workflow_handoff import metadata_closures' not in text:
        text=replace(text,"        raise ValueError('unexpected_handoff_suffix')\n",
            "        from workflow_handoff import metadata_closures\n        return metadata_closures(candidate.lstrip())\n")
    return text

def generation_service(text):
    if 'workflow_service.install(GenerationBroker, OPERATIONS)' in text:return text
    result=text.rstrip()+"\n\nimport workflow_service\nworkflow_service.install(GenerationBroker, OPERATIONS)\n"
    ast.parse(result);return result

def generation_worker(text):
    if 'from workflow_native import implementation' not in text:
        text=replace(text,
            'def build(editorial, folder, channel, day, topic, batch, guard, *, recovery=None, prepare=None):\n',
            'def build(editorial, folder, channel, day, topic, batch, guard, *, recovery=None, prepare=None):\n'
            '    from workflow_native import implementation\n    editorial = implementation(editorial)\n')
    if "'workflow_common.py','workflow_jobs.py'" not in text:
        text=replace(text,"    module_names = (", "    module_names = ('workflow_common.py','workflow_jobs.py','workflow_native.py','workflow_recovery.py','workflow_service.py',")
    if 'with enabled(editorial, folder, channel), manual_editorial' not in text:
        text=replace(text,
            '    with manual_editorial(editorial, folder, batch, channel, day, guard, recovery=recovery):\n',
            '    from workflow_native import enabled\n'
            '    with enabled(editorial, folder, channel), manual_editorial(editorial, folder, batch, channel, day, guard, recovery=recovery):\n')
    if "'workflow_preparation.py','workflow_inputs.py'" not in text:
        text=replace(text,"    module_names = (", "    module_names = ('workflow_preparation.py','workflow_inputs.py',")
    if "'workflow_handoff.py'" not in text:
        text=replace(text,"    module_names = (", "    module_names = ('workflow_handoff.py',")
    return text

def deepseek_editor(text):
    if "'provider-response-'+fingerprint" not in text:
        text=replace(text,"                    text = message['content']\n",
            "                    text = message['content']\n"
            "                    write(budget.root/('provider-response-'+fingerprint+'.json'),dict(output=str(output),provider_content=text,finish_reason='stop'))\n")
    if 'workflow_recovery.install(globals())' not in text:
        text=text.rstrip()+"\n\nimport workflow_recovery\nworkflow_recovery.install(globals())\n"
    ast.parse(text);return text

def generation_tools(text):
    if '_workflow_register(server, links)' in text:return text
    node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='register')
    lines=text.splitlines(keepends=True)
    lines.insert(node.end_lineno,"\n    from workflow_tools import register as _workflow_register\n    _workflow_register(server, links)\n")
    result=''.join(lines);ast.parse(result);return result

def documentary_service(text):
    if 'workflow_service.bind_documentary(parent)' not in text:
        text=replace(text,'    parent.documentary=DocumentaryBroker(parent)\n',
            '    parent.documentary=DocumentaryBroker(parent)\n    import workflow_service\n    workflow_service.bind_documentary(parent)\n')
    if 'workflow_service.guard_operation(op)' not in text:
        text=replace(text,"        op=r.get('operation') if isinstance(r,dict) else None\n",
            "        op=r.get('operation') if isinstance(r,dict) else None\n"
            "        if workflow_service.guard_operation(op):return denied('workflow_deployment_in_progress')\n")
    return text
