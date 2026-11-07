"""Catarsis serif cards with pixel fitting and unchanged archival captions."""
import copy
import math
import re
from contextlib import contextmanager

FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
SERIFS=('/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf')
VERSION='catarsis-serif-and-phrases-v50'
CONDENSE=.72

def lines(text,font,width):
    result=[]
    for paragraph in str(text).splitlines() or ['']:
        current=''
        for word in paragraph.split():
            trial=(current+' '+word).strip()
            if current and font.getlength(trial)>width:result.append(current);current=word
            else:current=trial
        result.append(current)
    return result

def serif(size):
    from PIL import ImageFont
    for path in SERIFS:
        try:return ImageFont.truetype(path,size)
        except OSError:pass
    raise RuntimeError('workflow_catarsis_serif_missing')

def layout(text,*,caption=False,style='center'):
    from PIL import ImageFont
    if style not in ('center','left','invert','red','word','caption'):
        raise RuntimeError('workflow_card_style_unknown')
    if caption:
        for size in range(78,63,-2):
            font=ImageFont.truetype(FONT,size);wrapped=lines(text,font,920)
            gap=round(size*.30);height=len(wrapped)*(size+gap)-gap
            if len(wrapped)<=4 and height<=410 and all(font.getlength(s)<=920 for s in wrapped):
                return font,wrapped,size,gap,height
    else:
        maximum=760 if style=='word' else 92 if style=='caption' else 210
        minimum=44 if style=='caption' else 96 if len(str(text).split())>10 else 112
        for size in range(maximum,minimum-1,-2):
            font=serif(size)
            wrapped=[str(text).upper()] if style=='word' else lines(text,font,842/CONDENSE)
            gap=round(size*.20)
            # Actual glyph bounds, rather than nominal font size, determine height.
            heights=[font.getbbox(s or ' ')[3]-font.getbbox(s or ' ')[1]+8 for s in wrapped]
            height=sum(heights)+max(0,len(wrapped)-1)*gap
            rows=1 if style=='word' else 3 if len(str(text).split())<=10 else 6
            if len(wrapped)<=rows and height<=850 and all((font.getbbox(s)[2]-font.getbbox(s)[0]+8)*CONDENSE<=842 for s in wrapped):
                return font,wrapped,size,gap,height
    raise RuntimeError('workflow_visible_text_does_not_fit')

def card(text,style='center'):
    from PIL import Image,ImageDraw
    font,wrapped,size,gap,height=layout(text,style=style)
    bg,fg=((242,240,234),(8,8,8)) if style=='invert' else ((186,14,22),(242,240,234)) if style=='red' else ((0,0,0),(242,240,234))
    image=Image.new('RGB',(1080,1920),bg)
    y=round(1920*.28 if style=='left' else 1920*.45-height/2)
    for line in wrapped:
        l,t,r,b=font.getbbox(line or ' ')
        layer=Image.new('RGBA',(max(1,r-l+8),max(1,b-t+8)))
        ImageDraw.Draw(layer).text((4-l,4-t),line,font=font,fill=fg)
        layer=layer.resize((max(1,round(layer.width*CONDENSE)),layer.height),Image.Resampling.LANCZOS)
        image.paste(layer,(86 if style=='left' else (1080-layer.width)//2,y),layer)
        y+=layer.height+gap
    return image

def caption(text):
    from PIL import Image,ImageDraw
    font,wrapped,size,gap,height=layout(text,caption=True)
    image=Image.new('RGBA',(1080,1920),(0,0,0,0));draw=ImageDraw.Draw(image)
    draw.rectangle((0,1380,1080,1850),fill=(0,0,0,248));y=1400
    for line in wrapped:
        draw.text((540,y),line,font=font,fill='white',anchor='mt',stroke_width=1,stroke_fill='black')
        y+=size+gap
    return image

def phrases(text):
    """Use only contiguous original words; no factual rewrite or paraphrase."""
    words=str(text).split()
    if len(words)<=7:return [' '.join(words)]
    candidates=[]
    for i in range(3,len(words)-2):
        if words[i-1].endswith(('.',',',';',':','!','?')):
            candidates.append((0,abs(i-len(words)/2),i))
        elif words[i].lower() in ('about','with','and','but','then'):
            candidates.append((1,abs(i-len(words)/2),i))
    boundary=min(candidates)[2] if candidates else len(words)//2
    parts=[' '.join(words[:boundary]),' '.join(words[boundary:])]
    # A long technical noun can make seven words wider than an ordinary sentence.
    # Keep a conjunction with its clause when a third phrase improves fitting.
    for i,part in enumerate(parts):
        local=part.split()
        if len(part)>52:
            joins=[n for n in range(2,len(local)-2) if local[n].lower() in ('and','with','about')]
            if joins:
                n=joins[0];parts[i:i+1]=[' '.join(local[:n]),' '.join(local[n:])];break
    return parts

def sequence_for_display(sequence,fps=30):
    """Keep every original scene boundary and every source word, in integer frames."""
    output=[];at=0.;previous=0;card_index=0
    for original in sequence:
        at+=float(original['seconds']);end=round(at*fps);frames=end-previous;previous=end
        if frames<=0:raise RuntimeError('workflow_card_frames_invalid')
        spec=copy.deepcopy(original)
        if spec.get('kind')!='card':output.append(spec);continue
        parts=phrases(spec.get('text',''))
        # A short card is kept whole rather than rushing two fragments.
        if len(parts)>1 and (frames<72 or any(len(p.split())/(frames/fps)*len(parts)>4 for p in parts)):
            parts=[' '.join(str(spec.get('text','')).split())]
        sizes=[len(p.split()) for p in parts];weights=sum(sizes)
        ends=[round(frames*sum(sizes[:i+1])/max(1,weights)) for i in range(len(parts))]
        prior=0
        for i,(part,last) in enumerate(zip(parts,ends)):
            child=copy.deepcopy(spec);child['text']=part;child['seconds']=(last-prior)/fps;prior=last
            child['kinetic']=bool(spec.get('kinetic',True));child['motion']='hold'
            # Respect explicitly requested variants; add restrained variety to default cards.
            if child.get('style','center')=='center':child['style']='left' if card_index%3==1 else 'center'
            output.append(child);card_index+=1
        if ' '.join(p['text'] for p in output[-len(parts):])!=' '.join(str(original.get('text','')).split()):
            raise RuntimeError('workflow_card_words_changed')
    if round(sum(float(s['seconds']) for s in output)*fps)!=round(at*fps):
        raise RuntimeError('workflow_card_timing_changed')
    return output

@contextmanager
def renderer(editor,plan):
    old_card,old_overlay,old_build=editor.text_card,editor.overlay_layer,editor.build_shots
    namespace=old_build.__globals__
    old_globals={key:namespace.get(key) for key in ('text_card','overlay_layer','build_shots')}
    # encoder_profile uses a private render namespace; the style wrapper keeps
    # that actual render function in its original_render closure.
    render=getattr(editor,'render',old_build)
    if 'original_render' in getattr(render.__code__,'co_freevars',()):
        render=render.__closure__[render.__code__.co_freevars.index('original_render')].cell_contents
    spaces=[]
    for space in (namespace,getattr(render,'__globals__',{})):
        if '_kinetic' in space and not any(space is existing for existing,_ in spaces):
            spaces.append((space,space['_kinetic']))
    old_kinetic=getattr(editor,'_kinetic',None)
    def clear_entry(image,index,echo):
        # No blur or doubled glyphs, including in the intermediate entry frames.
        return editor._zoomed(image,1+.035*(1-min(index/5,1)))
    assets=plan['assets']
    def build(project,sequence):
        visible=sequence_for_display(sequence,getattr(editor,'FPS',30))
        for scene in visible:
            index=scene.get('media')
            if scene.get('kind') in ('media','overlay') and type(index) is int and 0<=index<len(assets):
                label=assets[index].get('label')
                if not label:raise RuntimeError('workflow_existing_label_missing')
                scene.update(kind='overlay',text=label,kinetic=False)
        return old_build(project,visible)
    try:
        editor.text_card,editor.overlay_layer,editor.build_shots=card,caption,build
        namespace.update(text_card=card,overlay_layer=caption,build_shots=build)
        if old_kinetic is not None:editor._kinetic=clear_entry
        for space,_ in spaces:space['_kinetic']=clear_entry
        yield
    finally:
        for space,old in spaces:space['_kinetic']=old
        if old_kinetic is not None:editor._kinetic=old_kinetic
        namespace.update(old_globals)
        editor.text_card,editor.overlay_layer,editor.build_shots=old_card,old_overlay,old_build
