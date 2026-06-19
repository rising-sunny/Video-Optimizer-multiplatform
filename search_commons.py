import urllib.request
import json
import urllib.parse

def search_commons(query):
    query_enc = urllib.parse.quote(query)
    url = f"https://commons.wikimedia.org/w/api.php?action=query&list=search&srsearch={query_enc}&utf8=&format=json&srnamespace=6"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())
        return [item['title'] for item in data['query']['search']]

def get_image_url(image_title):
    title_enc = urllib.parse.quote(image_title)
    url = f"https://commons.wikimedia.org/w/api.php?action=query&titles={title_enc}&prop=imageinfo&iiprop=url&format=json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            pages = data['query']['pages']
            for page_id in pages:
                if 'imageinfo' in pages[page_id]:
                    return pages[page_id]['imageinfo'][0]['url']
    except Exception as e:
        pass
    return None

results = search_commons("Tunguska trees")
for r in results[:5]:
    url = get_image_url(r)
    print(f"URL: {url}")
