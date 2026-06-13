import os
import requests
import json

# Carga el token desde la variable de entorno EPIDEMIC_TOKEN (export antes de correr).
token = os.environ.get("EPIDEMIC_TOKEN")
if not token:
    raise SystemExit("Falta EPIDEMIC_TOKEN en el entorno.")

headers = {
    "Authorization": f"Bearer {token}",
    "accept": "application/json"
}

try:
    resp = requests.get("https://partner-content-api.epidemicsound.com/v0/search?q=epic+history", headers=headers)
    print("Status:", resp.status_code)
    print("Response:", json.dumps(resp.json(), indent=2)[:1000])
except Exception as e:
    print("Error:", e)
