from bs4 import BeautifulSoup
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def fetch_soup(url):
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")

def shgcdn_url(img):
    src = img.get("src", "")
    if "shgcdn.com" not in src:
        return src
    uuid = src.split("shgcdn.com/")[1].split("/")[0]
    return f"https://i.shgcdn.com/{uuid}/-/format/auto/-/quality/normal/-/resize/1200x/"

def get_analog_menu_image():
    soup = fetch_soup("https://www.carabellocoffee.com/pages/analog")
    container = soup.find("div", class_="shg-image-overflow")
    img = container.find("img") if container else None
    return shgcdn_url(img) if img else None

def get_coffee_classes():
    soup = fetch_soup("https://www.carabellocoffee.com/collections/coffee-classes")
    events = []
    for link in soup.find_all("a", class_="shogun-image-link"):
        img = link.find("img")
        date_div = link.find_next("div", class_="shg-rich-text")
        if img:
            events.append({
                "date": date_div.get_text(strip=True) if date_div else "Date TBD",
                "image_url": shgcdn_url(img),
                "ticket_url": link.get("href", "")
            })
    return events