from html.parser import HTMLParser
import urllib.request

class MyHTMLParser(HTMLParser):
    def handle_data(self, data):
        if data.strip():
            print(data.strip())

req = urllib.request.Request("https://openrouter.ai/models?output_modalities=video", headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode('utf-8')
        MyHTMLParser().feed(html)
except Exception as e:
    print(e)
