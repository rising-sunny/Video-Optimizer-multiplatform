import urllib.request
import json

def search_wikimedia_images(query, limit=3):
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={query}&prop=images&format=json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())
        pages = data['query']['pages']
        for page_id in pages:
            if 'images' in pages[page_id]:
                return [img['title'] for img in pages[page_id]['images']]
    return []

def get_image_url(image_title):
    import urllib.parse
    title_encoded = urllib.parse.quote(image_title)
    url = f"https://en.wikipedia.org/w/api.php?action=query&titles={title_encoded}&prop=imageinfo&iiprop=url&format=json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            pages = data['query']['pages']
            for page_id in pages:
                if 'imageinfo' in pages[page_id]:
                    return pages[page_id]['imageinfo'][0]['url']
    except Exception as e:
        print(f"Error for {image_title}: {e}")
    return None

images = search_wikimedia_images("Tunguska_event")
print(f"Found {len(images)} images.")
urls = []
for img in images:
    if img.endswith('.jpg') or img.endswith('.png') or img.endswith('.JPG'):
        url = get_image_url(img)
        if url:
            urls.append(url)
            print(f"URL: {url}")
