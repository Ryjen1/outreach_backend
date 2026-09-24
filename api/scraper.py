import requests

class WebScraper:
    def __init__(self, url="https://example.com"):
        self.url = url

    def fetch(self):
        response = requests.get(self.url)
        if response.status_code == 200:
            return response.text
        else:
            return None
