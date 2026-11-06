#!/usr/bin/env python3
"""Read the VPS Codex account limits. Never starts a thread, turn or model request."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import subprocess
import time
from zoneinfo import ZoneInfo

JOB='d1da2fe6dfb746e09694bb2129ff6f80'
BASE=Path('/home/videoagent/video-automation/runtime/manual-documentary')/JOB

class QueryFailure(RuntimeError):pass

def fetch_limits(command=None,timeout=35):
    command=command or ['/usr/bin/codex','app-server']
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        cwd=pwd.getpwuid(os.geteuid()).pw_dir,bufsize=0,start_new_session=True)
    deadline=time.monotonic()+timeout;buffer=b'';total=0
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    def send(value):
        process.stdin.write(json.dumps(value,separators=(',',':')).encode()+b'\n');process.stdin.flush()
    def response(ident):
        nonlocal buffer,total
        while time.monotonic()<deadline:
            while b'\n' in buffer:
                raw,buffer=buffer.split(b'\n',1)
                try:value=json.loads(raw)
                except ValueError:continue
                if isinstance(value,dict) and value.get('id')==ident:
                    if 'error' in value:
                        code=value['error'].get('code') if isinstance(value['error'],dict) else None
                        raise QueryFailure('method_not_supported' if code==-32601 else 'account_limits_request_failed')
                    if not isinstance(value.get('result'),dict):raise QueryFailure('account_limits_response_invalid')
                    return value['result']
            events=selector.select(max(0,deadline-time.monotonic()))
            if not events:break
            chunk=os.read(process.stdout.fileno(),65536)
            if not chunk:raise QueryFailure('account_limits_process_closed')
            total+=len(chunk)
            if total>1024*1024:raise QueryFailure('account_limits_response_too_large')
            buffer+=chunk
        raise QueryFailure('account_limits_timeout')
    try:
        send(dict(id=1,method='initialize',params=dict(clientInfo=dict(name='video-agent-quota-read',version='1.0'))))
        response(1)
        send(dict(method='initialized'))
        # Empty capability object uses no automatic Luna Reserve fallback.
        send(dict(id=2,method='account/rateLimits/read',params={}))
        return response(2)
    finally:
        selector.close()
        if process.poll() is None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=3)
        if process.stdin:process.stdin.close()
        if process.stdout:process.stdout.close()

def stamp(value,zone):
    if type(value) is not int or not 0<value<4102444800:return None
    try:return datetime.fromtimestamp(value,timezone.utc).astimezone(ZoneInfo(zone)).isoformat()
    except (ValueError,OverflowError,KeyError):return None

def summarize(value):
    if not isinstance(value,dict) or not isinstance(value.get('rateLimits'),dict):
        raise QueryFailure('account_limits_response_invalid')
    rows=[]
    def row(label,raw):
        if not isinstance(raw,dict):return
        ident=raw.get('limitId')
        if not isinstance(ident,str):ident=label
        if not re.fullmatch(r'[A-Za-z0-9_. -]{1,100}',ident or ''):ident='account'
        item=dict(limit_id=ident)
        for key in ('primary','secondary'):
            window=raw.get(key)
            if not isinstance(window,dict):continue
            percent=window.get('usedPercent');minutes=window.get('windowDurationMins')
            if type(percent) is not int:continue
            item[key]=dict(used_percent=percent,window_minutes=minutes if type(minutes) is int else None,
                resets_at_utc=stamp(window.get('resetsAt'),'UTC'),
                resets_at_santiago=stamp(window.get('resetsAt'),'America/Santiago'))
        if type(raw.get('spendControlReached')) is bool:item['spend_control_reached']=raw['spendControlReached']
        if item not in rows:rows.append(item)
    row('account',value['rateLimits'])
    by_id=value.get('rateLimitsByLimitId')
    if isinstance(by_id,dict):
        for label,raw in by_id.items():row(label,raw)
    result=dict(state='live_account_limits_read',ordinary_usage_allowed=value.get('ordinaryUsageAllowed')
        if type(value.get('ordinaryUsageAllowed')) is bool else None,limits=rows)
    # A missing backend permission is unknown, not proof of quota recovery.
    if result['ordinary_usage_allowed'] is None:result['quota_recovery_confirmed']=False
    return result

def saved_hint(folder=BASE):
    path=folder/'review-events.jsonl'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>1024*1024:return None
    for line in path.read_text(errors='replace').splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        if not isinstance(value,dict) or value.get('type') not in ('error','turn.failed'):continue
        error=value.get('error')
        raw=value.get('message') if value.get('type')=='error' else error.get('message') if isinstance(error,dict) else None
        if not isinstance(raw,str):continue
        raw=re.sub(r'https?://[^\s)]+','[URL]',raw)
        raw=re.sub(r'(?i)Bearer\s+\S+','[oculto]',raw)
        raw=re.sub(r'\bsk-[A-Za-z0-9_-]+','[oculto]',raw)
        match=re.search(r'(?:try again|resets?|reset|retry)\b[^\n]{0,180}',raw,re.I)
        if match:return match.group(0)
    return None

def main():
    result=dict(job_id=JOB,checked_at=datetime.now(timezone.utc).isoformat(),ai_requests=0,
        model_requests=0,review_retries=0,job_files_modified=False)
    try:result.update(summarize(fetch_limits()))
    except Exception as exc:
        code=str(exc) if isinstance(exc,QueryFailure) else type(exc).__name__
        result.update(state='live_limits_unavailable',reason=code,quota_recovery_confirmed=False)
    hint=saved_hint()
    if hint:result['previous_failure_reset_hint']=hint
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
