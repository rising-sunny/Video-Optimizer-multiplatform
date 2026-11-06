#!/usr/bin/env python3
"""Submit one explicit single-channel Catarsis request to the existing broker."""
import argparse
import json
from pathlib import Path
import re
import socket
import sys

ROOT = Path('/opt/video-agent-mcp')
sys.path.insert(0, str(ROOT))


def unique(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise RuntimeError('single_request_duplicate_json_key')
        result[key] = value
    return result


def load_request(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 16384:
        raise RuntimeError('single_request_file_invalid')
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if set(value) != {'operation', 'request_id', 'channel', 'topic'}:
        raise RuntimeError('single_request_fields_invalid')
    if value['operation'] != 'generation_start_single' or value['channel'] not in (
            'stunning-facts-of-history', 'stunning-revelations'):
        raise RuntimeError('single_request_scope_invalid')
    if not isinstance(value['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', value['request_id']):
        raise RuntimeError('single_request_id_invalid')
    topic = value['topic']
    if not isinstance(topic, str) or not 8 <= len(topic.strip()) <= 900 or any(ord(c) < 32 for c in topic):
        raise RuntimeError('single_request_topic_invalid')
    return value


def call(value):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(40)
        connection.connect('/run/video-agent-prepare/control.sock')
        connection.sendall(json.dumps(value, ensure_ascii=True).encode() + b'\n')
        with connection.makefile('rb') as stream:
            raw = stream.readline(1048577)
    if len(raw) > 1048576 or not raw.endswith(b'\n'):
        raise RuntimeError('single_broker_response_invalid')
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-file', required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--start', action='store_true')
    args = parser.parse_args()
    request = load_request(args.request_file)
    if args.check:
        import generation_worker
        import deepseek_runtime
        from catarsis_style import VERSION
        generation_worker.preflight()
        if deepseek_runtime.MAX_ESTIMATE != .20 or deepseek_runtime.LIMITS.get('chat') != 10:
            raise RuntimeError('single_existing_budget_configuration_changed')
        print(json.dumps(dict(state='checked', channel=request['channel'], request_id=request['request_id'],
            style_profile=VERSION, new_videos=0, ai_requests=0, estimated_usd_ceiling=.20,
            generation='not_requested', publication='not_requested')), flush=True)
        return
    result = call(request)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result.get('state') not in ('accepted', 'running', 'ready'):
        raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        value = str(exc)
        code = value if re.fullmatch(r'[a-z][a-z0-9_]{0,100}', value) else 'single_request_' + type(exc).__name__
        print(json.dumps(dict(state='blocked', error_code=code, publication_allowed=False)), flush=True)
        raise SystemExit(2)
