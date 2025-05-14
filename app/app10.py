import requests  # HTTP requests
from bs4 import BeautifulSoup  # HTML parser
import pandas as pd  # Data handling
import pytesseract  # OCR engine
from PIL import Image, ImageEnhance  # Image handling
from io import BytesIO  # In-memory file
import re  # Regex for pattern matching
from datetime import datetime  # Date/time formatting
from urllib.parse import urljoin  # Join base and relative URLs
import time  # Delay for rate limiting
import cv2  # OpenCV for image preprocessing
import numpy as np  # Array handling


def load_known_brands(filepath):
    """Load known brands from a file into a set"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        print(f"⚠️ Brand file {filepath} not found. Proceeding without brand matching.")
        return set()


# === CONFIGURATION ===
CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'delay': 2,
    'tesseract_path': r'C:\Users\kelvin.shisanya\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    'image_selectors': {
        'coupon': ['img[src*="coupon"]', 'div.entry-content img'],
        'hot_buy': ['img[src*="hotbuy"]', 'img[src*="deal"]', 'div.hot-deals img']
    }
}


# === SETUP ===
def initialize():
    try:
        pytesseract.pytesseract.tesseract_cmd = CONFIG['tesseract_path']
        pytesseract.get_tesseract_version()
        return True
    except Exception as e:
        print(f"❌ Tesseract init error: {e}")
        return False


# === PAGE FETCHING ===
def get_page(url):
    try:
        time.sleep(CONFIG['delay'])
        headers = {'User-Agent': CONFIG['user_agent']}
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        return res.text
    except Exception as e:
        print(f"❌ Failed to fetch {url}: {e}")
        return None


# === IMAGE HANDLER ===
def download_image(img_url, referer):
    try:
        headers = {'User-Agent': CONFIG['user_agent'], 'Referer': referer}
        res = requests.get(img_url, headers=headers)
        res.raise_for_status()

        if not res.headers.get("Content-Type", "").startswith("image"):
            print(f"⛔ Skipping non-image: {img_url}")
            return None

        img = Image.open(BytesIO(res.content))
        img_np = np.array(img)

        if img_np.ndim == 2:
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
        elif img_np.shape[2] == 4:
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        else:
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        denoised = cv2.fastNlMeansDenoising(thresh, None, 30, 7, 21)

        img = Image.fromarray(denoised)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)

        return img

    except Exception as e:
        print(f"❌ Error processing image {img_url}: {e}")
        return None


# === OCR HANDLER ===
def extract_text_from_image(img):
    config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
    try:
        text = pytesseract.image_to_string(img, config=config).strip()
        ocr_corrections = {
            '|': 'I',
            '1': 'I',
            '0': 'O',
            'vv': 'W',
        }
        for wrong, right in ocr_corrections.items():
            text = text.replace(wrong, right)
        return text
    except Exception as e:
        print(f"❌ OCR failed: {e}")
        return ""


# === DATA PARSER ===
def parse_coupon_data(text, source_url, is_hot_buy, known_brands):
    blocks = re.split(r'(?=\$\d+(?:\.\d{2})?\s*OFF)', text)
    data = []

    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if not lines:
            continue

        full_text = ' '.join(lines)

        if len(full_text) < 10 or re.search(r'BOOK WITH|TRAVEL|PACKAGE|^\W+$', full_text, re.IGNORECASE):
            continue

        item_brand = ""
        for brand in known_brands:
            if re.search(rf'(?<!\w){re.escape(brand.lower())}(?!\w)', full_text.lower()):
                item_brand = brand
                break

        if not item_brand:
            brand_match = re.search(r'^([A-Z][A-Z&\-\s]+[A-Z])(?=\s|$)|^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', full_text)
            if brand_match:
                item_brand = (brand_match.group(1) or brand_match.group(2)).strip()
            else:
                item_brand = ' '.join(full_text.split()[:2]).strip()

        item_description = full_text.strip()

        if item_brand:
            brand_tokens = item_brand.lower().split()
            desc_tokens = item_description.split()
            filtered = [token for token in desc_tokens if token.lower() not in brand_tokens]
            item_description = ' '.join(filtered).strip()

        item_description = re.sub(r'\s+', ' ', item_description)
        item_description = re.sub(r'^[^a-zA-Z0-9]+', '', item_description)
        item_description = re.sub(r'[\*•\-]+$', '', item_description)

        discount_match = re.search(r'\$[0-9]+(?:\.\d{2})?\s*OFF', text, re.IGNORECASE)
        discount = discount_match.group(0) if discount_match else ""
        discount_cleaned = re.sub(r'[^\d.]', '', discount) if discount else ""

        limit = re.search(r'(Limit\s+\d+|While\s+supplies\s+last)', text, re.IGNORECASE)
        price = re.search(r'\$[0-9]+\.\d{2}', text)

        channel = ""
        if is_hot_buy:
            warehouse = 'warehouse' in text.lower()
            online = 'online' in text.lower()
            if warehouse and online:
                channel = "In-Warehouse + Online"
            elif warehouse:
                channel = "In-Warehouse"
            elif online:
                channel = "Online"

        discount_period = "March 29th through April 6th" if is_hot_buy else "April 9th through May 4th"

        row = {
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'article_name': "Costco April 2025 Hot Buys Coupons" if is_hot_buy else "Costco April 2025 Coupon Book",
            'publish_date': "2025-03-28 00:00:00" if is_hot_buy else "2025-04-01 00:00:00",
            'item_brand': item_brand,
            'item_description': item_description,
            'discount': discount,
            'discount_cleaned': discount_cleaned,
            'count_limit': limit.group(0) if limit else "",
            'channel': channel,
            'discount_period': discount_period,
            'item_original_price': price.group(0) if price else "",
            'source_url': source_url
        }

        data.append(row)

    return data


# === SCRAPER CORE ===
def scrape_images_from_page(url, is_hot_buy=False):
    html = get_page(url)
    if not html:
        return []

    brand_file = 'hot_buy_brands.txt' if is_hot_buy else 'coupon_book_brands.txt'
    known_brands = load_known_brands(brand_file)

    soup = BeautifulSoup(html, 'html.parser')
    items = []

    if not is_hot_buy:
        coupon_container = soup.select_one('#coupon-book')
        images = coupon_container.select('img') if coupon_container else []
        print(f"📦 Found {len(images)} coupon book images in #coupon-book")
    else:
        selectors = CONFIG['image_selectors']['hot_buy']
        images = []
        for selector in selectors:
            images = soup.select(selector)
            if images:
                break
        else:
            images = soup.select('img')
        print(f"📦 Found {len(images)} hot buy images")

    for img_tag in images:
        img_url = img_tag.get('src')
        if not img_url.startswith('http'):
            img_url = urljoin(url, img_url)

        print(f"📥 Downloading image: {img_url}")
        img = download_image(img_url, url)
        if not img:
            continue

        text = extract_text_from_image(img)
        if not text:
            continue

        parsed = parse_coupon_data(text, img_url, is_hot_buy, known_brands)
        if isinstance(parsed, list):
            items.extend(parsed)

    if is_hot_buy:
        next_page = soup.find('a', string=re.compile(r'next|›|>', re.IGNORECASE))
        if next_page and next_page.get('href'):
            next_url = urljoin(url, next_page['href'])
            print(f"➡️ Following next page: {next_url}")
            items.extend(scrape_images_from_page(next_url, is_hot_buy))

    return items


# === SAVE TO EXCEL ===
def save_to_excel(data, filename):
    if not data:
        print(f"⚠️ No data to save for {filename}")
        return

    df = pd.DataFrame(data)
    columns = [
        'scrape_datetime', 'article_name', 'publish_date', 'item_brand',
        'item_description', 'discount', 'discount_cleaned', 'count_limit',
        'channel', 'discount_period', 'item_original_price', 'source_url'
    ]

    df = df[columns]
    df.to_excel(filename, index=False)
    print(f"💾 Saved {len(df)} records to {filename}")


# === MAIN ===
def main():
    if not initialize():
        return

    print("📘 Scraping Coupon Book...")
    coupon_url = "https://www.costcoinsider.com/costco-april-2025-coupon-book/"
    coupons = scrape_images_from_page(coupon_url, is_hot_buy=False)
    save_to_excel(coupons, "2025-04-28_Coupon_Books.xlsx")

    print("🔥 Scraping Hot Buys...")
    hot_buys_url = "https://www.costcoinsider.com/costco-april-2025-hot-buys-coupons/"
    hotbuys = scrape_images_from_page(hot_buys_url, is_hot_buy=True)
    save_to_excel(hotbuys, "2025-04-28_Hot_Buys_Coupons.xlsx")

    print("🎉 Done! Check the Excel files.")


if __name__ == "__main__":
    main()
