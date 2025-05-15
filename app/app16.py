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
import os

# === CONFIGURATION ===
CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'delay': 2,
    'tesseract_path': r'C:\Users\kelvin.shisanya\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    'image_selectors': {
        'coupon': ['img[src*="coupon"]', 'div.entry-content img'],
        'hot_buy': ['img[src*="hotbuy"]', 'img[src*="deal"]', 'div.hot-deals img']
    },
    'default_brands': {
        'SunVilla', 'Charmin', 'Yardistry', 'Dyson Cyclone', 'Pistachios', 'Primavera Mistura',
        'Apples', 'Palmiers', 'Waterloo', 'Woozoo', 'Mower', 'Trimmer', 'Jet Blower',
        'Scotts', 'Huggies', 'Powder', 'Cookie', 'Kerrygold', 'Prawn Hacao'
    },
    'blacklist_keywords': ['warehouse', 'online', 'only', 'in-warehouse', 'in warehouse']
}

# === HELPERS ===
def clean_text(text):
    return re.sub(r'\s+', ' ', text.strip())

def remove_blacklisted_words(text):
    pattern = re.compile(r'\b(?:' + '|'.join(map(re.escape, CONFIG['blacklist_keywords'])) + r')\b', flags=re.IGNORECASE)
    return pattern.sub('', text)

def fuzzy_find_brand(ocr_text, known_brands):
    if known_brands:
        match = process.extractOne(ocr_text, known_brands, score_cutoff=80)
        if match:
            return match[0]
    return None

def load_known_brands(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            brands = set(line.strip() for line in f if line.strip())
            return brands if brands else CONFIG['default_brands']
    except FileNotFoundError:
        print(f"⚠️ Brand file {filepath} not found. Using default brands.")
        return CONFIG['default_brands']

# === IMAGE & TEXT PROCESSING ===
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

def extract_text_from_image(img):
    config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
    try:
        text = pytesseract.image_to_string(img, config=config).strip()
        for wrong, right in {'|': 'I', '1': 'I', '0': 'O', 'vv': 'W', '$': 'S'}.items():
            text = text.replace(wrong, right)
        return text
    except Exception as e:
        print(f"❌ OCR failed: {e}")
        return ""

# === DATA PARSING ===
def parse_coupon_data(text, source_url, is_hot_buy, known_brands):
    blocks = re.split(r'(?=\$\d+(?:\.\d{2})?\s*OFF)', text)
    data = []

    for block in blocks:
        if len(block.strip()) < 10:
            continue
        full_text = re.sub(r'\s+', ' ', block.strip())

        clean_block = remove_blacklisted_words(full_text)

        # === Brand Detection ===
        item_brand = ""
        for brand in known_brands:
            if re.search(rf'\b{re.escape(brand.lower())}\b', clean_block.lower()):
                item_brand = brand
                break
        if not item_brand:
            possible = ' '.join(full_text.split()[:3])
            fuzzy = fuzzy_find_brand(possible, known_brands)
            if fuzzy:
                item_brand = fuzzy

        # === Description ===
        item_description = full_text
        if item_brand:
            pattern = re.compile(rf'^{re.escape(item_brand)}[\s:,-]*', re.IGNORECASE)
            item_description = pattern.sub('', item_description)
        item_description = remove_blacklisted_words(item_description)
        item_description = re.sub(r'[^\w\s]', '', item_description).strip()

        # === Discount ===
        discount_match = re.search(r'\$\s*\d+(?:\.\d{2})?\s*OFF', block, re.IGNORECASE)
        discount = discount_match.group(0).strip() if discount_match else ""
        discount_cleaned = re.sub(r'[^\d.]', '', discount) if discount else ""

        # === Limit ===
        limit_match = re.search(r'(Limit\s+\d+|While\s+supplies\s+last)', block, re.IGNORECASE)
        count_limit = limit_match.group(0).strip() if limit_match else ""

        # === Price ===
        price_match = re.search(r'\$\s*\d+\.\d{2}', block)
        item_original_price = price_match.group(0).strip() if price_match else ""

        # === Channel ===
        channel = ""
        b = block.lower()
        if 'warehouse' in b and 'online' in b:
            channel = "In-Warehouse + Online"
        elif 'warehouse' in b:
            channel = "In-Warehouse"
        elif 'online' in b:
            channel = "Online"

        data.append({
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'article_name': "Costco April 2025 Hot Buys Coupons" if is_hot_buy else "Costco April 2025 Coupon Book",
            'publish_date': "2025-03-28 00:00:00" if is_hot_buy else "2025-04-01 00:00:00",
            'item_brand': item_brand,
            'item_description': item_description,
            'discount': discount,
            'discount_cleaned': discount_cleaned,
            'count_limit': count_limit,
            'channel': channel,
            'discount_period': "March 29th through April 6th" if is_hot_buy else "April 9th through May 4th",
            'item_original_price': item_original_price,
            'source_url': source_url
        })
    return data

# === SCRAPER LOGIC ===
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
        text = extract_text_from_image(img)
        if not text:
            continue
        parsed = parse_coupon_data(text, img_url, is_hot_buy, known_brands)
        if isinstance(parsed, list):
            items.extend(parsed)
    save_to_excel(items, f"{'Hot_Buys' if is_hot_buy else 'Coupon_Books'}_{datetime.now().strftime('%Y-%m-%d')}.xlsx")
    return items

def save_to_excel(data, filename):
    if not data:
        print(f"⚠️ No data to save for {filename}")
        return
    df = pd.DataFrame(data)
    df = df[[
        'scrape_datetime', 'article_name', 'publish_date', 'item_brand',
        'item_description', 'discount', 'discount_cleaned', 'count_limit',
        'channel', 'discount_period', 'item_original_price', 'source_url'
    ]]
    df.to_excel(filename, index=False)
    print(f"💾 Saved {len(df)} records to {filename}")

def initialize():
    try:
        pytesseract.pytesseract.tesseract_cmd = CONFIG['tesseract_path']
        pytesseract.get_tesseract_version()
        return True
    except Exception as e:
        print(f"❌ Tesseract init error: {e}")
        return False

def main():
    if not initialize():
        return
    print("📘 Scraping Coupon Book...")
    scrape_images_from_page("https://www.costcoinsider.com/costco-april-2025-coupon-book/", is_hot_buy=False)
    print("🔥 Scraping Hot Buys...")
    scrape_images_from_page("https://www.costcoinsider.com/costco-april-2025-hot-buys-coupons/", is_hot_buy=True)
    print("🎉 Done! Check the Excel files.")

if __name__ == "__main__":
    main()
