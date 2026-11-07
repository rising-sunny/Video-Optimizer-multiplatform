"""Pixel-fitted cards and visible existing archival labels; no text rewriting."""
import copy
from contextlib import contextmanager

FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

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

def layout(text,*,caption=False):
    from PIL import ImageFont
    width=920;maximum=78 if caption else 150;minimum=64 if caption else 96
    for size in range(maximum,minimum-1,-2):
        font=ImageFont.truetype(FONT if caption or len(str(text))>60 else BOLD,size)
        wrapped=lines(text,font,width)
        gap=round(size*.30);height=len(wrapped)*(size+gap)-gap
        rows=4 if caption else 3 if len(str(text))<=45 else 6
        if len(wrapped)<=rows and height<=(410 if caption else 870) and all(font.getlength(line)<=width for line in wrapped):
            return font,wrapped,size,gap,height
    raise RuntimeError('workflow_visible_text_does_not_fit')

def card(text,style='center'):
    from PIL import Image,ImageDraw
    font,wrapped,size,gap,height=layout(text)
    image=Image.new('RGB',(1080,1920),'black');draw=ImageDraw.Draw(image)
    y=round(1920*.45-height/2)
    for line in wrapped:
        draw.text((540,y),line,font=font,fill=(245,244,240),anchor='mt',stroke_width=1)
        y+=size+gap
    return image

def caption(text):
    from PIL import Image,ImageDraw
    font,wrapped,size,gap,height=layout(text,caption=True)
    image=Image.new('RGBA',(1080,1920),(0,0,0,0));draw=ImageDraw.Draw(image)
    draw.rectangle((0,1380,1080,1850),fill=(0,0,0,248))
    y=1400
    for line in wrapped:
        draw.text((540,y),line,font=font,fill='white',anchor='mt',stroke_width=1,stroke_fill='black')
        y+=size+gap
    return image

@contextmanager
def renderer(editor,plan):
    old_card,old_overlay,old_build=editor.text_card,editor.overlay_layer,editor.build_shots
    namespace=old_build.__globals__
    old_globals={key:namespace.get(key) for key in ('text_card','overlay_layer','build_shots')}
    assets=plan['assets']
    def build(project,sequence):
        visible=copy.deepcopy(sequence)
        for scene in visible:
            index=scene.get('media')
            if scene.get('kind') in ('media','overlay') and type(index) is int and 0<=index<len(assets):
                label=assets[index].get('label')
                if not label:raise RuntimeError('workflow_existing_label_missing')
                scene.update(kind='overlay',text=label)
        return old_build(project,visible)
    try:
        editor.text_card,editor.overlay_layer,editor.build_shots=card,caption,build
        namespace.update(text_card=card,overlay_layer=caption,build_shots=build)
        yield
    finally:
        namespace.update(old_globals)
        editor.text_card,editor.overlay_layer,editor.build_shots=old_card,old_overlay,old_build
