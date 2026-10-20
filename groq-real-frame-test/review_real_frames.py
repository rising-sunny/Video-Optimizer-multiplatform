"""Offline evaluation on four real-video fixtures; never publishes or enables fallback."""
import argparse,base64,hashlib,json,os,re,time
from pathlib import Path

def parse_answer(content):
 text=str(content or '').strip();text=re.sub(r'^```(?:json)?\s*|\s*```$','',text)
 d=json.loads(text)
 for k in ['approve','main_text_readable','main_text_fully_visible']:
  if type(d.get(k)) is not bool:raise ValueError('Invalid reviewer schema')
 if not isinstance(d.get('primary_text'),str):raise ValueError('Missing OCR')
 return d

def grade(answer,case):
 checks={k:answer.get(k)==expected for k,expected in case['expected'].items()}
 text=answer['primary_text'].upper()
 for word in case.get('required_words',[]):checks['read_'+word]=word.upper() in text
 return checks

def main():
 p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True);args=p.parse_args();folder=args.directory
 from dotenv import load_dotenv
 load_dotenv(folder/'.env',override=False);key=os.environ.get('GROQ_API_KEY')
 if not key:raise SystemExit('GROQ_API_KEY missing; no requests sent.')
 pack=json.loads((folder/'fixtures.json').read_text());assert len(pack['cases'])==4
 for c in pack['cases']:assert hashlib.sha256(base64.b64decode(c['image_base64'])).hexdigest()==c['sha256']
 import requests
 session=requests.Session();session.headers.update({'Authorization':'Bearer '+key})
 prompt=('Review this single frame from a vertical English history short. Evaluate visible layout only. '
 'Return only one JSON object with approve (boolean), main_text_readable (boolean), '
 'main_text_fully_visible (boolean), primary_text (transcribe the large headline exactly as visible; '
 'do not invent missing or unreadable words), critical_issues (array of short strings). '
 'Approve only if the main headline is readable, fully inside the frame, and has no critical layout defect. '
 'Reject clipped or unreadable main text. Historical grain, black-and-white footage and small source labels '
 'are intentional and do not alone require rejection. Do not verify historical accuracy, copyright or '
 'motion from this still; those cannot be established by this test. Do not infer missing text from prior knowledge.')
 report={'scope':'real_frame_layout_probe_only','model':'qwen/qwen3.8-27b','production_changed':False,'cases':[]}
 for case in pack['cases']:
  row={'case':case['case'],'fixture':case['fixture_name'],'expected':case['expected']};started=time.monotonic()
  try:
   response=session.post('https://api.groq.com/openai/v1/chat/completions',json={'model':report['model'],'messages':[{'role':'user','content':[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+case['image_base64']}}]}],'max_completion_tokens':384},timeout=60)
   row.update(http_status=response.status_code,seconds=round(time.monotonic()-started,2))
   if response.ok:
    data=response.json();row['usage']=data.get('usage',{});answer=parse_answer(data.get('choices',[{}])[0].get('message',{}).get('content'));row['answer']=answer;row['checks']=grade(answer,case);row['passed']=all(row['checks'].values())
   else:row['passed']=False
  except Exception as exc:row.update(passed=False,error_type=type(exc).__name__,seconds=round(time.monotonic()-started,2))
  report['cases'].append(row)
  print('CASE_RESULT',json.dumps(row,ensure_ascii=False),flush=True)
  if row.get('http_status') in [401,403,429]:report['stopped_reason']='auth_or_rate_limit';break
  time.sleep(1)
 report['passed_cases']=sum(bool(x.get('passed')) for x in report['cases']);report['total_cases']=4;report['all_passed']=len(report['cases'])==4 and report['passed_cases']==4
 report['limitations']='Small still-image layout benchmark. Does not validate research tools, factual accuracy, attribution/licensing, full video motion/audio, cost, complete fallback or production readiness.'
 path=folder/'resultado-fotogramas.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2));os.chmod(path,0o600)
 print('REAL_FRAME_TEST_SUMMARY',json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False),flush=True)
 return 0 if report['all_passed'] else 2
if __name__=='__main__':raise SystemExit(main())
