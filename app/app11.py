import requests
from bs4 import BeautifulSoup
import pandas as pd
import pytesseract
from PIL import Image, ImageEnhance
from io import BytesIO
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
import time
import cv2
import numpy as np
import random
import logging
from dateutil.parser import parse

# === LOGGING SETUP ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === CONFIGURATION ===
CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'delay': 2,
    'tesseract_path': r'C:\Users\kelvin.shisanya\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    'coupon_base_url': 'https://www.costcoinsider.com/costco-{month}-{year}-coupon-book/',
    'hot_buys_base_url': 'https://www.costcoinsider.com/costco-{month}-{year}-hot-buys-coupons/',
    'image_selectors': {
        'coupon': ['img[src*="coupon"]', 'div.entry-content img', '.coupon-book img', 'img'],
        'hot_buy': ['img[src*="hotbuy"]', 'img[src*="deal"]', 'div.hot-deals img', '.entry-content img', 'img']
    }
}

# === SETUP ===
def initialize():
    try:
        pytesseract.pytesseract.tesseract_cmd = CONFIG['tesseract_path']
        version = pytesseract.get_tesseract_version()
        logging.info(f"Tesseract initialized: {version}")
        return True
    except FileNotFoundError:
        logging.error(f"Tesseract not found at {CONFIG['tesseract_path']}. Please install Tesseract or update the path.")
        return False
    except Exception as e:
        logging.error(f"Tesseract init error: {e}")
        return False

# === LOAD KNOWN BRANDS ===
def load_known_brands(filepath):
    default_brands = {
        'Kirkland', 'Nike', 'Samsung', 'Apple', 'Adidas', 'Sony', 'LG', 'Kerrygold', 'Orgain',
        'Michelin', 'Greenworks', 'Huggies', 'Woozoo', 'Wonderful', 'Yardistry', 'Waterloo',
        'Tide', 'Bounty', 'Dyson', 'Cuisinart'
    }
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            brands = set(line.strip() for line in f if line.strip())  # Fixed syntax
            return brands | default_brands
    except FileNotFoundError:
        logging.warning(f"Brand file {filepath} not found. Using default brands.")
        return default_brands

# === PAGE FETCHING ===
def get_page(url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(CONFIG['delay'] + random.uniform(0, 1))
            headers = {'User-Agent': CONFIG['user_agent']}
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            return res.text
        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed to fetch {url}: {e}")
            if attempt < retries - 1:
                time.sleep(CONFIG['delay'])
            continue
    logging.error(f"Failed to fetch {url} after {retries} attempts")
    return None

# === IMAGE HANDLER ===
def download_image(img_url, referer, retries=3):
    for attempt in range(retries):
        try:
            headers = {'User-Agent': CONFIG['user_agent'], 'Referer': referer}
            res = requests.get(img_url, headers=headers, timeout=10)
            res.raise_for_status()

            if not res.headers.get("Content-Type", "").startswith("image"):
                logging.warning(f"Skipping non-image: {img_url}")
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
            thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                         cv2.THRESH_BINARY, 11, 2)
            denoised = cv2.fastNlMeansDenoising(thresh, None, 30, 7, 21)

            img = Image.fromarray(denoised)
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = ImageEnhance.Sharpness(img).enhance(2.0)

            return img

        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed for {img_url}: {e}")
            if attempt < retries - 1:
                time.sleep(CONFIG['delay'])
            continue
    logging.error(f"Failed to download {img_url} after {retries} attempts")
    return None

# === OCR HANDLER ===
def extract_text_from_image(img):
    config = r'--oem 3 --psm 3 -c preserve_interword_spaces=1'
    try:
        text = pytesseract.image_to_string(img, config=config).strip()
        ocr_corrections = {
            '|': 'I', '1': 'I', '0': 'O', 'vv': 'W', 'l': '1', 'S': '$', 'B': '8', 'O': '0', 
            'Z': '2', '5': 'S', 'D': 'O', 'Q': 'O', 'T': 'I', 'E': '8', 'G': '6'
        }
        for wrong, right in ocr_corrections.items():
            text = text.replace(wrong, right)
        return text
    except Exception as e:
        logging.error(f"OCR failed: {e}")
        return ""

# === DATA PARSER ===
def parse_coupon_data(text, source_url, is_hot_buy, known_brands, article_name, publish_date, discount_period):
    logging.info(f"\n=== RAW OCR TEXT ===\n{text}\n===================")
    with open('ocr_debug.txt', 'a', encoding='utf-8') as f:
        f.write(f"\n=== URL: {source_url} ===\n{text}\n===================\n")

    blocks = re.split(r'(?=\$\d+(?:\.\d{2})?\s*(?:OFF|off|Save|SAVE))', text)
    data = []

    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if not lines:
            continue

        full_text = ' '.join(lines)
        if len(full_text) < 10 or re.search(r'BOOK WITH|TRAVEL|PACKAGE|^\W+$', full_text, re.IGNORECASE):
            continue

        # Brand Detection
        item_brand = ""
        full_text_lower = full_text.lower()
        for brand in known_brands:
            if re.search(rf'\b{re.escape(brand.lower())}\b', full_text_lower):
                item_brand = brand.title()
                break

        if not item_brand:
            brand_match = re.search(
                r'^([A-Z][A-Z&\-\s]{2,}[A-Z])(?=\s|$)|([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})',
                full_text, re.IGNORECASE
            )
            if brand_match:
                item_brand = (brand_match.group(1) or brand_match.group(2) or '').strip().title()
            if not item_brand or len(item_brand) > 30:
                item_brand = ' '.join(full_text.split()[:2]).strip().title()[:30]

        # Description Extraction
        item_description = full_text.strip()
        patterns_to_remove = [
            re.escape(item_brand),
            r'\$\d+(?:\.\d{2})?\s*(?:OFF|off|Save|SAVE)',
            r'Limit\s+\d+|While\s+supplies\s+last',
            r'\$[0-9]+\.\d{2}(?!\s*(?:OFF|off|Save|SAVE))',
            r'[\*•\-\+]+',
            r'warehouse|online|in-warehouse',
            r'\s+'
        ]
        for pattern in patterns_to_remove:
            item_description = re.sub(pattern, ' ', item_description, flags=re.IGNORECASE).strip()
        
        item_description = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', item_description)
        item_description = item_description[:50]
        if not item_description or len(item_description) < 5:
            item_description = ' '.join(full_text.split()[1:])[:50].strip()

        # Other Fields
        discount_match = re.search(r'\$[\d]+(?:\.[\d]{2})?\s*(?:OFF|off|Save|SAVE)', block, re.IGNORECASE)
        discount = discount_match.group(0) if discount_match else ""
        discount_cleaned = re.sub(r'[^\d.]', '', discount) if discount else ""

        limit = re.search(r'(Limit\s+\d+|While\s+supplies\s+last)', block, re.IGNORECASE)
        price = re.search(r'\$[0-9]+\.\d{2}(?!\s*(?:OFF|off|Save|SAVE))', block)

        channel = ""
        if is_hot_buy:
            warehouse = 'warehouse' in full_text_lower
            online = 'online' in full_text_lower
            if warehouse and online:
                channel = "In-Warehouse + Online"
            elif warehouse:
                channel = "In-Warehouse"
            elif online:
                channel = "Online"

        row = {
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'article_name': article_name,
            'publish_date': publish_date,
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

# === GENERATE URLS FOR HISTORICAL SCRAPING ===
def generate_historical_urls(start_date, end_date):
    coupon_urls = []
    hot_buys_urls = []
    current_date = start_date
    while current_date <= end_date:
        month = current_date.strftime('%B').lower()
        year = current_date.year
        coupon_url = CONFIG['coupon_base_url'].format(month=month, year=year)
        hot_buys_url = CONFIG['hot_buys_base_url'].format(month=month, year=year)
        coupon_urls.append((coupon_url, f"Costco {month.capitalize()} {year} Coupon Book", f"{year}-{current_date.month:02d}-01"))
        hot_buys_urls.append((hot_buys_url, f"Costco {month.capitalize()} {year} Hot Buys Coupons", f"{year}-{current_date.month:02d}-01"))
        # Move to next month
        current_date = (current_date.replace(day=1) + timedelta(days=32)).replace(day=1)
    return coupon_urls, hot_buys_urls

# === SCRAPER CORE ===
def scrape_images_from_page(url, is_hot_buy=False, article_name="", publish_date=""):
    html = get_page(url)
    if not html:
        return []

    brand_file = 'hot_buy_brands.txt' if is_hot_buy else 'coupon_book_brands.txt'
    known_brands = load_known_brands(brand_file)

    soup = BeautifulSoup(html, 'html.parser')
    items = []

    # Extract discount period
    discount_period = ""
    date_match = re.search(r'(\w+\s+\d{1,2}(?:st|nd|rd|th)?\s+through\s+\w+\s+\d{1,2}(?:st|nd|rd|th)?)', html, re.IGNORECASE)
    if date_match:
        discount_period = date_match.group(0)
    else:
        discount_period = "Unknown"

    if not is_hot_buy:
        coupon_container = soup.select_one('#coupon-book, .coupon-book, .entry-content')
        images = coupon_container.select('img') if coupon_container else soup.select('.entry-content img, img')
        logging.info(f"Found {len(images)} coupon book images")
    else:
        selectors = CONFIG['image_selectors']['hot_buy']
        images = []
        for selector in selectors:
            images = soup.select(selector)
            if images:
                break
        else:
            images = soup.select('img')
        logging.info(f"Found {len(images)} hot buy images")

    for img_tag in images:
        img_url = img_tag.get('src')
        if not img_url:
            continue
        if not img_url.startswith('http'):
            img_url = urljoin(url, img_url)

        logging.info(f"Downloading image: {img_url}")
        img = download_image(img_url, url)
        if not img:
            continue

        text = extract_text_from_image(img)
        if not text:
            continue

        parsed = parse_coupon_data(text, img_url, is_hot_buy, known_brands, article_name, publish_date, discount_period)
        if isinstance(parsed, list):
            items.extend(parsed)

    if is_hot_buy:
        next_page = soup.find('a', string=re.compile(r'next|›|>', re.IGNORECASE))
        if next_page and next_page.get('href'):
            next_url = urljoin(url, next_page['href'])
            logging.info(f"Following next page: {next_url}")
            items.extend(scrape_images_from_page(next_url, is_hot_buy, article_name, publish_date))

    logging.info(f"Extracted {len(items)} items from {url}")
    return items

# === SAVE TO CSV ===
def save_to_csv(data, filename):
    if not data:
        logging.warning(f"No data to save for {filename}")
        return

    df = pd.DataFrame(data)
    columns = [
        'scrape_datetime', 'article_name', 'publish_date', 'item_brand',
        'item_description', 'discount', 'discount_cleaned', 'count_limit',
        'channel', 'discount_period', 'item_original_price', 'source_url'
    ]
    df = df[columns]
    df.to_csv(filename, index=False)
    logging.info(f"Saved {len(df)} records to {filename}")

# === MAIN ===
def main(historical=False):
    if not initialize():
        return

    coupon_book_data = []
    hot_buys_data = []

    if historical:
        start_date = datetime.now() - timedelta(days=730)  # May 2023
        end_date = datetime.now()
        coupon_urls, hot_buys_urls = generate_historical_urls(start_date, end_date)
        
        # Scrape Coupon Book URLs
        for url, article_name, publish_date in coupon_urls:
            logging.info(f"Scraping Coupon Book: {article_name} ({url})")
            items = scrape_images_from_page(url, is_hot_buy=False, article_name=article_name, publish_date=publish_date)
            coupon_book_data.extend(items)

        # Scrape Hot Buys URLs
        for url, article_name, publish_date in hot_buys_urls:
            logging.info(f"Scraping Hot Buys: {article_name} ({url})")
            items = scrape_images_from_page(url, is_hot_buy=True, article_name=article_name, publish_date=publish_date)
            hot_buys_data.extend(items)
    else:
        # Current month (May 2025)
        month = datetime.now().strftime('%B').lower()
        year = datetime.now().year
        coupon_url = CONFIG['coupon_base_url'].format(month=month, year=year)
        hot_buys_url = CONFIG['hot_buys_base_url'].format(month=month, year=year)

        # Scrape Coupon Book
        logging.info(f"Scraping Coupon Book: {coupon_url}")
        coupon_book_data = scrape_images_from_page(
            coupon_url, 
            is_hot_buy=False, 
            article_name=f"Costco {month.capitalize()} {year} Coupon Book",
            publish_date=datetime.now().strftime('%Y-%m-%d')
        )

        # Scrape Hot Buys
        logging.info(f"Scraping Hot Buys: {hot_buys_url}")
        hot_buys_data = scrape_images_from_page(
            hot_buys_url, 
            is_hot_buy=True, 
            article_name=f"Costco {month.capitalize()} {year} Hot Buys Coupons",
            publish_date=datetime.now().strftime('%Y-%m-%d')
        )

    # Save to separate CSV files
    date_str = datetime.now().strftime('%Y-%m-%d')
    if historical:
        save_to_csv(coupon_book_data, f"costco_historical_coupon_book_2023_2025.csv")
        save_to_csv(hot_buys_data, f"costco_historical_hot_buys_2023_2025.csv")
    else:
        save_to_csv(coupon_book_data, f"costco_coupon_book_{date_str}.csv")
        save_to_csv(hot_buys_data, f"costco_hot_buys_coupons_{date_str}.csv")

    logging.info(f"Done! Check CSV files.")

if __name__ == "__main__":
    main(historical=False)  # Current month
    main(historical=True)   # Historical data