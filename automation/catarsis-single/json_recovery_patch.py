"""Preserve the existing parser and broker routes; add one unambiguous suffix."""
import ast

BATCH = 'cf2a22d4f40f453fba2b3af137b716d1'


def replace(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError('single_json_source_shape_changed')
    result = text.replace(before, after, 1)
    ast.parse(result)
    return result


def shorts_handoff(text):
    text = replace(text,
        "    dsml=bool(suffix.strip())\n",
        "    redundant_close = isinstance(data,dict) and suffix.strip()=='}'\n"
        "    if redundant_close:suffix=''\n"
        "    dsml=bool(suffix.strip())\n")
    return replace(text, "    changes=[]\n",
        "    changes=[]\n"
        "    if redundant_close:changes.append(dict(kind='removed_single_redundant_object_close',count=1))\n")


def shorts_handoff_resume(text):
    for name, args, call in (
        ('start', 'broker,batch', 'resume(broker,batch)'),
        ('perform', 'batch', 'resume(batch)'),
    ):
        text = replace(text, f'def {name}({args}):\n',
            f'def {name}({args}):\n'
            f"    if batch=='{BATCH}':\n"
            f'        from shorts_single_json import {name} as resume\n'
            f'        return {call}\n')
    return text


def documentary_service(text):
    return replace(text,
        "{'generation_start','generation_start_single','generation_revise_style','publication_start','request_today'}",
        "{'generation_start','generation_start_single','generation_resume_saved_handoffs','generation_revise_style','publication_start','request_today'}")
