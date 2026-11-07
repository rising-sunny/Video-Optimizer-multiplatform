"""Bounded syntax/timing normalization and trusted factual-controller writes."""
import contextlib
import copy
import hashlib
import json
import math
from pathlib import Path
import re
from deepseek_runtime import Failure

VERSION='saved-json-and-timing-v44'

def _pairs(rows):
    result={}
    for key,value in rows:
        if key in result:raise ValueError('duplicate_json_key')
        result[key]=value
    return result

def parse(text):
    if not isinstance(text,str) or len(text.encode())>2*1024*1024:raise ValueError('handoff_size_or_type')
    value=text.strip();fence=re.fullmatch(r'```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n?```',value,re.I)
    if fence:value=fence[1]
    try:return json.loads(value,object_pairs_hook=_pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite_json_number'))),[]
    except json.JSONDecodeError:pass
    out=[];quoted=False;escaped=False;controls=commas=0
    for i,char in enumerate(value):
        if quoted:
            if escaped:out.append(char);escaped=False;continue
            if char=='\\':out.append(char);escaped=True;continue
            if char=='"':quoted=False
            if ord(char)<32:
                out.append(json.dumps(char)[1:-1]);controls+=1;continue
        else:
            if char=='"':quoted=True
            elif char==',':
                j=i+1
                while j<len(value) and value[j].isspace():j+=1
                if j<len(value) and value[j] in '}]':commas+=1;continue
        out.append(char)
    candidate=''.join(out)
    decoder=json.JSONDecoder(object_pairs_hook=_pairs,
        parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite_json_number')))
    data,end=decoder.raw_decode(candidate.lstrip());suffix=candidate.lstrip()[end:]
    dsml=bool(suffix.strip())
    if dsml and not re.fullmatch(r'(?:\s*</｜｜DSML｜｜ (?:parameter|invoke|calls)>){1,3}\s*',suffix):
        raise ValueError('unexpected_handoff_suffix')
    changes=[]
    if controls:changes.append(dict(kind='escaped_literal_string_controls',count=controls))
    if commas:changes.append(dict(kind='removed_trailing_structural_comma',count=commas))
    if dsml:changes.append(dict(kind='removed_known_dsml_closing_suffix'))
    if not changes:raise ValueError('unrepaired_json')
    return data,changes

def timing(plan,target=55,fps=30):
    result=copy.deepcopy(plan);seq=result['project']['sequence']
    if not isinstance(seq,list) or not 14<=len(seq)<=22:raise Failure('saved_plan_scene_count_invalid')
    original=[float(s['seconds']) for s in seq]
    if any(not math.isfinite(v) or v<=0 for v in original):raise Failure('saved_plan_scene_duration_invalid')
    minimum=[max(18,math.ceil(len(str(s.get('text','')).split())/3.5*fps)) for s in seq]
    breaks=[i for i,s in enumerate(seq) if s.get('tag')=='break']
    inferred=None
    if not breaks:
        candidates=[i for i,s in enumerate(seq) if s.get('kind')=='color' and not str(s.get('text','')).strip() and .6<=original[i]<=1.2]
        if len(candidates)==1:
            inferred=candidates[0];seq[inferred]['tag']='break';breaks=[inferred]
    if len(breaks)!=1 or seq[breaks[0]].get('kind')!='color' or not .6<=original[breaks[0]]<=1.2:
        raise Failure('saved_plan_quiet_break_invalid')
    if 50<=sum(original)<=59 and all(v*fps+1e-6>=n for v,n in zip(original,minimum)):
        return result,(dict(version=VERSION,inferred_break_index=inferred,scene_text_and_assets_unchanged=True,ai_requests=0) if inferred is not None else None)
    pause=breaks[0];frames=[minimum[i] if i!=pause else round(original[i]*fps) for i in range(len(seq))]
    spare=round(target*fps)-sum(frames)
    if spare<0:raise Failure('saved_plan_text_cannot_fit_duration')
    editable=[i for i in range(len(seq)) if i!=pause];weights={i:original[i] for i in editable};denom=sum(weights.values())
    quotas={i:spare*weights[i]/denom for i in editable}
    for i in editable:frames[i]+=math.floor(quotas[i])
    left=round(target*fps)-sum(frames)
    for i in sorted(editable,key=lambda n:(-(quotas[n]-math.floor(quotas[n])),n))[:left]:frames[i]+=1
    for scene,n in zip(seq,frames):scene['seconds']=n/fps
    return result,dict(version=VERSION,before_seconds=sum(original),after_seconds=sum(frames)/fps,
        before=original,after=[n/fps for n in frames],inferred_break_index=inferred,scene_text_and_assets_unchanged=True,ai_requests=0)

def _tree(folder):
    from autonomous_generation import tree
    return tree(folder)

def _index(folder):
    from documentary_sources import INDEX,index
    return index(folder)

def _verify_factual_write(folder,url,before,after,previous):
    from documentary_sources import INDEX,available,index
    changed={n for n in set(before)|set(after) if before.get(n)!=after.get(n)}
    if any(n not in after or (n in before and n!=INDEX) or
        (n!=INDEX and not re.fullmatch(r'factual-v41-[a-f0-9]{24}\.(?:raw|txt)',n)) for n in changed):
        raise Failure('autonomy_controller_factual_write_out_of_scope')
    current=index(folder)
    if current.get('version')!='verified-public-text-v41':raise Failure('autonomy_controller_factual_index_version')
    old=previous.get('sources',{});new=current['sources']
    if any(new.get(k)!=v for k,v in old.items()) or not set(new)-set(old)<={url}:
        raise Failure('autonomy_controller_factual_prior_evidence_changed')
    available(folder) # validates hashes and excerpts of every successful snapshot
    allowed={INDEX}
    for row in new.values():
        if row.get('state')=='available':allowed.update((row['file'],row['raw_file']))
        elif row.get('state') not in ('intent','unavailable'):raise Failure('autonomy_controller_factual_state_invalid')
    if not changed<=allowed:raise Failure('autonomy_controller_factual_unreferenced_file')
    return {n:(before.get(n),after[n]) for n in changed}

@contextlib.contextmanager
def controller_sources(folder):
    """Only the actual controller fetch function can register these changes.
    All other edits still go through Supervisor.after_agent unchanged."""
    import documentary_sources
    folder=Path(folder);original=documentary_sources.fetch_source;edits={}
    class Receipt:
        def reconcile(self,frozen):
            if frozen is None:return frozen
            result=dict(frozen)
            for name,(before,after) in edits.items():
                if result.get(name)!=before:raise Failure('autonomy_controller_factual_snapshot_binding_changed')
                result[name]=after
            return result
    def fetched(directory,url,*args,**kwargs):
        if Path(directory)!=folder:return original(directory,url,*args,**kwargs)
        before=_tree(folder);previous=_index(folder)
        try:return original(directory,url,*args,**kwargs)
        finally:
            after=_tree(folder);delta=_verify_factual_write(folder,url,before,after,previous)
            for name,(old,new) in delta.items():
                if name in edits:
                    first,last=edits[name]
                    if last!=old:raise Failure('autonomy_controller_factual_write_chain_changed')
                    edits[name]=(first,new)
                else:edits[name]=(old,new)
    documentary_sources.fetch_source=fetched
    try:yield Receipt()
    finally:documentary_sources.fetch_source=original

def normalize_result(folder,result):
    """Correct duration in the returned native plan before it is saved, including
    rebuild envelopes. Other schema defects still reach the native validator."""
    folder=Path(folder)
    if folder.parent.parent.name!='manual-catarsis' or not (folder/'style-profile.json').is_file() or not isinstance(result,dict) or result.get('blocked'):
        return result,None
    wrapper=result.get('action')=='rebuild' and isinstance(result.get('plan'),dict)
    candidate=copy.deepcopy(result['plan'] if wrapper else result);merged=[]
    if wrapper:
        for name in ('metadata','thumbnail'):
            if name not in candidate and isinstance(result.get(name),dict):candidate[name]=copy.deepcopy(result[name]);merged.append(name)
    if 'project' not in candidate or 'assets' not in candidate:return result,None
    try:normalized,receipt=timing(candidate)
    except (Failure,KeyError,TypeError,ValueError):return result,None
    if merged:receipt=dict(receipt or {},version=VERSION,merged_envelope_fields=merged,ai_requests=0)
    if receipt:
        if wrapper:
            value=copy.deepcopy(result);value['plan']=normalized;return value,receipt
        return normalized,receipt
    return result,None
