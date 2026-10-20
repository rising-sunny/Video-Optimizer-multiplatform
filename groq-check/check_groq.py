"""Bounded text/vision probe. No secrets in arguments, output, or reports."""
import argparse,base64,io,json,os,re,secrets,time
from pathlib import Path

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,default=Path.cwd());ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
 from dotenv import load_dotenv
 # Match project precedence; never instantiate GroqAiClient, which unsets proxies.
 for name in ('.env','.env.txt'):load_dotenv(args.repo/name,override=False)
 key=os.environ.get('GROQ_API_KEY');report={'scope':'text_and_synthetic_image_probe_only','key_present':bool(key),'production_changed':False}
 def finish(code):
  args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');os.chmod(args.out,0o600);print(json.dumps(report,ensure_ascii=False,indent=2));return code
 if not key:report['state']='missing_key';return finish(2)
 import requests
 session=requests.Session();session.headers.update({'Authorization':'Bearer '+key});base='https://api.groq.com/openai/v1/'
 def request(path,body=None):
  try:
   started=time.monotonic();r=session.get(base+path,timeout=45) if body is None else session.post(base+path,json=body,timeout=60)
   if not r.ok:return None,{'http_status':r.status_code}
   return r.json(),{'http_status':r.status_code,'seconds':round(time.monotonic()-started,2)}
  except Exception as e:return None,{'error_type':type(e).__name__}
 catalog,result=request('models');report['authentication']=result
 if catalog is None:report['state']='catalog_failed';return finish(2)
 ids={x['id'] for x in catalog.get('data',[]) if isinstance(x,dict) and isinstance(x.get('id'),str)};report['available_model_count']=len(ids)
 text=next((m for m in ['llama-3.1-8b-instant','openai/gpt-oss-20b','llama-3.3-70b-versatile'] if m in ids),None)
 if text:
  data,result=request('chat/completions',{'model':text,'messages':[{'role':'user','content':'Reply with exactly GROQ_TEXT_OK.'}],'max_completion_tokens':128});result.update(model=text)
  if data:
   result['passed']='GROQ_TEXT_OK' in str(data.get('choices',[{}])[0].get('message',{}).get('content',''));result['usage']=data.get('usage',{})
  report['text']=result
 from PIL import Image,ImageDraw,ImageFont
 im=Image.new('RGB',(1000,640),'white');draw=ImageDraw.Draw(im)
 font_path=next((p for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','C:/Windows/Fonts/arialbd.ttf'] if Path(p).is_file()),None)
 font=ImageFont.truetype(font_path,58) if font_path else ImageFont.load_default(size=58)
 code=str(secrets.randbelow(900000)+100000);draw.text((35,20),'CODE '+code,font=font,fill='black')
 draw.polygon([(230,160),(80,440),(380,440)],fill='red');draw.ellipse((600,170,890,460),fill='blue')
 # Deliberately clip the baseline of the bottom text: layout ability is scored separately.
 draw.text((30,615),'BOTTOM CAPTION',font=font,fill='black')
 stream=io.BytesIO();im.save(stream,format='PNG');encoded='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()
 candidates=sorted(m for m in ids if re.fullmatch(r'[A-Za-z0-9._/-]{1,150}',m) and (m.startswith('meta-llama/llama-4-scout-') or m.startswith('meta-llama/llama-4-maverick-') or 'vision' in m.lower() or ('qwen' in m.lower() and 'vl' in m.lower())))[:2]
 report['vision_candidates_tested']=candidates;report['vision']=[]
 for model in candidates:
  data,result=request('chat/completions',{'model':model,'messages':[{'role':'user','content':[{'type':'text','text':'Inspect this image. Return only JSON with keys code (digits only), left_shape, left_color, right_shape, right_color, bottom_text_clipped (boolean). Use English. Read the code from the image.'},{'type':'image_url','image_url':{'url':encoded}}]}],'max_completion_tokens':384});result['model']=model
  if data:
   result['usage']=data.get('usage',{});content=str(data.get('choices',[{}])[0].get('message',{}).get('content','')).strip();content=re.sub(r'^```(?:json)?\s*|\s*```$','',content)
   try:
    answer=json.loads(content);result['image_understanding_passed']=str(answer.get('code'))==code and 'triangle' in str(answer.get('left_shape','')).lower() and 'red' in str(answer.get('left_color','')).lower() and 'circle' in str(answer.get('right_shape','')).lower() and 'blue' in str(answer.get('right_color','')).lower();result['clipping_detected']=answer.get('bottom_text_clipped') is True
   except Exception:result['image_understanding_passed']=False;result['response_format_passed']=False
  report['vision'].append(result)
 report['candidate_detection_note']='Candidate IDs are heuristics, not a complete official capability catalog. No matching candidate does not prove all account models lack vision.'
 report['state']='basic_vision_available' if any(x.get('image_understanding_passed') for x in report['vision']) else 'vision_not_confirmed'
 report['limitations']='Synthetic fixture only. Does not validate editorial judgment, historical facts, web research, licenses, cost, or a complete autonomous fallback.'
 return finish(0 if report['state']=='basic_vision_available' else 2)
if __name__=='__main__':raise SystemExit(main())
