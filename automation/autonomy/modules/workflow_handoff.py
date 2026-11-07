"""Recognize one precise premature-close defect in native platform metadata."""
import json


def pairs(items):
    value={}
    for key,item in items:
        if key in value:raise ValueError('duplicate_json_key')
        value[key]=item
    return value


def metadata_closures(text):
    decoder=json.JSONDecoder(object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite_json_number')))
    value,end=decoder.raw_decode(text)
    metadata=value.get('metadata') if isinstance(value,dict) else None
    if (not isinstance(metadata,dict) or set(metadata)!={'youtube','tags'}
        or not isinstance(metadata['youtube'],dict) or 'tags' in metadata['youtube']
        or not isinstance(metadata['tags'],list) or not isinstance(value.get('facebook'),dict)
        or not text[end:].lstrip().startswith(',"instagram"')):
        raise ValueError('unexpected_handoff_suffix')
    # Tokenize actual JSON strings (not string contents). Only two structural
    # object closes are removed; every text byte, credit and URL is preserved.
    found={};index=0
    while index<len(text):
        if text[index]!='"':index+=1;continue
        key,stop=decoder.raw_decode(text,index)
        after=stop
        while after<len(text) and text[after].isspace():after+=1
        if after<len(text) and text[after]==':' and key in ('tags','instagram'):
            if key in found:raise ValueError('ambiguous_metadata_boundary')
            comma=index-1
            while comma>=0 and text[comma].isspace():comma-=1
            if comma<0 or text[comma]!=',':raise ValueError('metadata_boundary_missing')
            close=comma-1
            while close>=0 and text[close].isspace():close-=1
            if close<0 or text[close]!='}':raise ValueError('metadata_boundary_not_a_close')
            found[key]=close
        index=stop
    if set(found)!={'tags','instagram'}:raise ValueError('metadata_boundaries_missing')
    repaired=''.join(char for i,char in enumerate(text) if i not in set(found.values()))
    result=decoder.decode(repaired)
    if (set(result['metadata'])!={'youtube','facebook','instagram'}
        or 'facebook' in result or not isinstance(result['metadata']['youtube']['tags'],list)
        or not isinstance(result.get('thumbnail'),dict)):
        raise ValueError('metadata_repaired_shape_invalid')
    return result,[dict(kind='removed_two_premature_platform_metadata_closes',count=2,
        string_values_and_credits_unchanged=True)]
