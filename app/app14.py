import requests
from bs4 import BeautifulSoup
import pandas as pd
import pytesseract
from PIL import Image, ImageEnhance
from io import BytesIO
import re
from datetime import datetime
from urllib.parse import urljoin
import time
import cv2
import numpy as np
from rapidfuzz import process

# === CONFIGURATION ===
CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'delay': 2,
    'tesseract_path': r'C:\Users\kelvin.shisanya\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    'image_selectors': {
        'coupon': ['img[src*="coupon"]', 'div.entry-content img'],
        'hot_buy': ['img[src*="hotbuy"]', 'img[src*="deal"]', 'div.hot-deals img']
    },
    'default_brands': {'Kirkland', 'Samsung', 'Sony', 'Dyson', 'Apple', 'LG', 'Bose', 'Panasonic'}
}

def load_known_brands(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            brands = set(line.strip() for line in f if line.strip())
            return brands if brands else CONFIG['default_brands']
    except FileNotFoundError:
        print(f"⚠️ Brand file {filepath} not found. Using default brands.")
        return CONFIG['default_brands']

def initialize():
    try:
        pytesseract.pytesseract.tesseract_cmd = CONFIG['tesseract_path']
        pytesseract.get_tesseract_version()
        return True
    except Exception as e:
        print(f"❌ Tesseract init error: {e}")
        return False

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

def split_grid_image_dynamic(img):
    width, height = img.size
    columns = 4 if width > 900 else 3
    rows = 2
    cell_width = width // columns
    cell_height = height // rows
    return [img.crop((col*cell_width, row*cell_height, (col+1)*cell_width, (row+1)*cell_height))
            for row in range(rows) for col in range(columns)]

def extract_text_from_image(img):
    config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
    try:
        text = pytesseract.image_to_string(img, config=config).strip()
        for wrong, right in {'|': 'I', '1': 'I', '0': 'O', 'vv': 'W'}.items():
            text = text.replace(wrong, right)
        return text
    except Exception as e:
        print(f"❌ OCR failed: {e}")
        return ""

def fuzzy_find_brand(ocr_text, known_brands):
    match_tuple = process.extractOne(ocr_text, known_brands, score_cutoff=80)
    return match_tuple[0] if match_tuple else None

def parse_coupon_data(text, source_url, is_hot_buy, known_brands):
    data = []
    blocks = re.split(r'(?=\$\d+(?:\.\d{2})?\s*OFF)', text)
    for block in blocks:
        full_text = ' '.join(block.split())
        if len(full_text) < 10:
            continue
        item_brand = next((b for b in known_brands if re.search(rf'\\b{re.escape(b)}\\b', full_text, re.IGNORECASE)), '')
        if not item_brand:
            fuzzy = fuzzy_find_brand(' '.join(full_text.split()[:3]), known_brands)
            item_brand = fuzzy if fuzzy else re.match(r'^([A-Z][a-zA-Z0-9&\-\']+)', full_text).group(1) if re.match(r'^([A-Z][a-zA-Z0-9&\-\']+)', full_text) else ''
        item_description = re.sub(rf'^\s*{re.escape(item_brand)}[\s:,-]*', '', full_text, flags=re.IGNORECASE)
        item_description = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', item_description).strip()
        item_description = re.sub(r'\s+', ' ', item_description)
        discount_match = re.search(r'\$[0-9]+(?:\.\d{2})?\s*OFF', block, re.IGNORECASE)
        discount = discount_match.group(0) if discount_match else ""
        discount_cleaned = re.sub(r'[^\d.]', '', discount)
        limit = re.search(r'(Limit\s+\d+|While\s+supplies\s+last)', block, re.IGNORECASE)
        price = re.search(r'\$[0-9]+\.\d{2}', block)
        channel = ""
        if is_hot_buy:
            if 'warehouse' in block.lower() and 'online' in block.lower():
                channel = "In-Warehouse + Online"
            elif 'warehouse' in block.lower():
                channel = "In-Warehouse"
            elif 'online' in block.lower():
                channel = "Online"
        data.append({
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'article_name': "Costco April 2025 Hot Buys Coupons" if is_hot_buy else "Costco April 2025 Coupon Book",
            'publish_date': "2025-03-28 00:00:00" if is_hot_buy else "2025-04-01 00:00:00",
            'item_brand': item_brand,
            'item_description': item_description,
            'discount': discount,
            'discount_cleaned': discount_cleaned,
            'count_limit': limit.group(0) if limit else "",
            'channel': channel,
            'discount_period': "March 29th through April 6th" if is_hot_buy else "April 9th through May 4th",
            'item_original_price': price.group(0) if price else "",
            'source_url': source_url
        })
    return data

def scrape_images_from_page(url, is_hot_buy=False):
    html = get_page(url)
    if not html:
        return []
    brand_file = 'hot_buy_brands.txt' if is_hot_buy else 'coupon_book_brands.txt'
    known_brands = load_known_brands(brand_file)
    soup = BeautifulSoup(html, 'html.parser')
    selectors = CONFIG['image_selectors']['hot_buy'] if is_hot_buy else CONFIG['image_selectors']['coupon']
    images = []
    for selector in selectors:
        images = soup.select(selector)
        if images:
            break
    if not images:
        images = soup.select('img')
    items = []
    for img_tag in images:
        img_url = img_tag.get('src')
        if not img_url.startswith('http'):
            img_url = urljoin(url, img_url)
        print(f"📥 Downloading image: {img_url}")
        img = download_image(img_url, url)
        if not img:
            continue
        sub_imgs = split_grid_image_dynamic(img)
        for sub_img in sub_imgs:
            text = extract_text_from_image(sub_img)
            if not text:
                continue
            parsed = parse_coupon_data(text, img_url, is_hot_buy, known_brands)
            if isinstance(parsed, list):
                items.extend(parsed)
    if is_hot_buy:
        next_page = soup.find('a', string=re.compile(r'next|›|>', re.IGNORECASE))
        if next_page and next_page.get('href'):
            items.extend(scrape_images_from_page(urljoin(url, next_page['href']), is_hot_buy))
    return items

def save_to_excel(data, filename):
    if not data:
        print(f"⚠️ No data to save for {filename}")
        return
    df = pd.DataFrame(data)
    df = df[[
        'scrape_datetime', 'article_name', 'publish_date', 'item_brand',
        'item_description', 'discount', 'discount_cleaned', 'count_limit',
        'channel', 'discount_period', 'item_original_price', 'source_url']]
    df.to_excel(filename, index=False)
    print(f"💾 Saved {len(df)} records to {filename}")

def main():
    if not initialize():
        return
    print("📘 Scraping Coupon Book...")
    coupons = scrape_images_from_page("https://www.costcoinsider.com/costco-april-2025-coupon-book/", False)
    save_to_excel(coupons, "2025-04-28_Coupon_Books.xlsx")
    print("🔥 Scraping Hot Buys...")
    hotbuys = scrape_images_from_page("https://www.costcoinsider.com/costco-april-2025-hot-buys-coupons/", True)
    save_to_excel(hotbuys, "2025-04-28_Hot_Buys_Coupons.xlsx")
    print("🎉 Done! Check the Excel files.")

if __name__ == "__main__":
    main()
