import os
import requests
import json

token = os.environ.get("EPIDEMIC_TOKEN")
if not token:
    raise SystemExit("Falta EPIDEMIC_TOKEN en el entorno.")

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "text/event-stream"
}

try:
    resp = requests.get("https://www.epidemicsound.com/a/mcp-service/mcp/sse", headers=headers, stream=True)
    print("Status:", resp.status_code)
    for line in resp.iter_lines():
        if line:
            print(line.decode('utf-8'))
            if b'endpoint' in line:
                break
except Exception as e:
    print("Error:", e)
