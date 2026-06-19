import urllib.request
import re
import os
from urllib.parse import unquote

url = 'https://html.duckduckgo.com/html/?q=baltic+sea+anomaly+sonar+scan+image'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    links = re.findall(r'//external-content\.duckduckgo\.com/iu/\?u=([^&\"\']+)', html)
    urls = list(set([unquote(l) for l in links if '.jpg' in l.lower() or '.png' in l.lower()]))
    if not urls:
        print("No image URLs found.")
    for i, u in enumerate(urls[:3]):
        try:
            req_img = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req_img, timeout=10) as response, open(f'scratch_baltic_{i}.jpg', 'wb') as out_file:
                out_file.write(response.read())
            print(f"Saved: scratch_baltic_{i}.jpg from {u}")
        except Exception as e:
            print(f"Failed {u}: {e}")
except Exception as e:
    print(e)
