import urllib.request

url = "https://upload.wikimedia.org/wikipedia/commons/a/a4/Tunguska_Ereignis-1.jpg"
req = urllib.request.Request(
    url, 
    headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    }
)

with urllib.request.urlopen(req) as response, open(r"C:\Users\sunse\.gemini\antigravity\brain\34a88839-abc4-4a17-a938-b485d3058ead\tunguska_real_1.jpg", 'wb') as out_file:
    out_file.write(response.read())
print("Downloaded successfully.")
