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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('coupon_scraper.log'),
        logging.StreamHandler()
    ]
)

# === CONFIGURATION ===
CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'delay': 2,
    'max_retries': 3,
    'request_timeout': 15,
    'tesseract_path': r'C:\Users\kelvin.shisanya\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    'coupon_base_url': 'https://www.costcoinsider.com/costco-{month}-{year}-coupon-book/',
    'hot_buys_base_url': 'https://www.costcoinsider.com/costco-{month}-{year}-hot-buys-coupons/',
    'image_selectors': {
        'coupon': ['img[src*="coupon"]', 'div.entry-content img', '.coupon-book img'],
        'hot_buy': ['img[src*="hotbuy"]', 'img[src*="deal"]', 'div.hot-deals img']
    },
    'default_brands': {
        'Kirkland', 'Nike', 'Samsung', 'Apple', 'Adidas', 'Sony', 'LG', 'Kerrygold', 
        'Orgain', 'Michelin', 'Greenworks', 'Huggies', 'Woozoo', 'Wonderful',
        'Yardistry', 'Waterloo', 'Tide', 'Bounty', 'Dyson', 'Cuisinart'
    }
}

# === SETUP ===
def initialize():
    try:
        pytesseract.pytesseract.tesseract_cmd = CONFIG['tesseract_path']
        version = pytesseract.get_tesseract_version()
        logging.info(f"Tesseract OCR {version} initialized successfully")
        return True
    except Exception as e:
        logging.error(f"Tesseract initialization failed: {e}")
        return False

# === BRAND HANDLING ===
def load_known_brands(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            brands = {line.strip() for line in f if line.strip()}
            return brands.union(CONFIG['default_brands'])
    except FileNotFoundError:
        logging.warning(f"Brand file {filepath} not found. Using default brands only.")
        return CONFIG['default_brands']

# === NETWORK UTILITIES ===
def get_page(url, retries=None):
    retries = retries or CONFIG['max_retries']
    for attempt in range(retries):
        try:
            delay = CONFIG['delay'] + random.uniform(0, 1)
            time.sleep(delay)
            
            headers = {'User-Agent': CONFIG['user_agent']}
            response = requests.get(
                url, 
                headers=headers, 
                timeout=CONFIG['request_timeout']
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1}/{retries} failed for {url}: {str(e)}")
            if attempt == retries - 1:
                logging.error(f"Failed to fetch {url} after {retries} attempts")
                return None

# === IMAGE PROCESSING ===
def preprocess_image(image_np):
    # Convert to grayscale if needed
    if image_np.ndim == 2:
        image_cv = cv2.cvtColor(image_np, cv2.COLOR_GRAY2BGR)
    elif image_np.shape[2] == 4:
        image_cv = cv2.cvtColor(image_np, cv2.COLOR_RGBA2BGR)
    else:
        image_cv = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
    
    # Enhanced preprocessing pipeline
    gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 3)
    thresh = cv2.adaptiveThreshold(
        gray, 255, 
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    denoised = cv2.fastNlMeansDenoising(
        thresh, None, 
        h=30, 
        templateWindowSize=7,
        searchWindowSize=21
    )
    return denoised

def download_image(img_url, referer):
    for attempt in range(CONFIG['max_retries']):
        try:
            headers = {
                'User-Agent': CONFIG['user_agent'],
                'Referer': referer
            }
            response = requests.get(
                img_url,
                headers=headers,
                timeout=CONFIG['request_timeout']
            )
            response.raise_for_status()

            if not response.headers.get('Content-Type', '').startswith('image'):
                logging.warning(f"Skipping non-image content at {img_url}")
                return None

            img = Image.open(BytesIO(response.content))
            img_np = np.array(img)
            processed = preprocess_image(img_np)
            
            # Enhance image for OCR
            img = Image.fromarray(processed)
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = ImageEnhance.Sharpness(img).enhance(1.5)
            
            return img
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1} failed for image {img_url}: {e}")
            if attempt == CONFIG['max_retries'] - 1:
                logging.error(f"Failed to download image after {CONFIG['max_retries']} attempts")
                return None

# === OCR PROCESSING ===
def correct_ocr_text(text):
    corrections = {
        '|': 'I', '1': 'I', '0': 'O', 'vv': 'W', 'l': '1',
        'S': '$', 'B': '8', 'O': '0', 'Z': '2', '5': 'S',
        'D': 'O', 'Q': 'O', 'T': 'I', 'E': '8', 'G': '6'
    }
    for wrong, right in corrections.items():
        text = text.replace(wrong, right)
    return text

def extract_text_from_image(img):
    try:
        config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
        text = pytesseract.image_to_string(img, config=config).strip()
        return correct_ocr_text(text)
    except Exception as e:
        logging.error(f"OCR processing failed: {e}")
        return ""

# === DATA EXTRACTION ===
def extract_discount_period(soup, is_hot_buy):
    pattern = (r'(?:valid|offer)\s*(.*?)\s*through\s*(.*?)(?:\s*while supplies last|$)'
               if is_hot_buy else 
               r'(?:valid|offer)\s*(.*?)\s*through\s*(.*?)(?:\s*\.|\s*$)')
    text = ' '.join(soup.stripped_strings)
    match = re.search(pattern, text, re.IGNORECASE)
    return f"{match.group(1)} through {match.group(2)}" if match else "Not specified"

def parse_coupon_data(text, source_url, is_hot_buy, known_brands, article_name, publish_date, discount_period):
    # Save raw OCR for debugging
    with open('ocr_debug.log', 'a', encoding='utf-8') as f:
        f.write(f"\n=== Source: {source_url} ===\n{text}\n{'='*50}\n")

    # Enhanced block splitting
    blocks = re.split(r'(?=\$\d+(?:\.\d{2})?\s*(?:OFF|SAVE|off|save))', text)
    data = []
    
    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if not lines or len(lines) < 2:
            continue
            
        full_text = ' '.join(lines)
        if len(full_text) < 15 or re.search(r'BOOK WITH|TRAVEL|PACKAGE|^\W+$', full_text, re.IGNORECASE):
            continue

        # Brand extraction with improved logic
        item_brand = ""
        full_text_lower = full_text.lower()
        
        # Check against known brands first
        for brand in known_brands:
            brand_lower = brand.lower()
            if (re.search(rf'\b{brand_lower}\b', full_text_lower) or
                brand_lower in full_text_lower):
                item_brand = brand
                break
        
        # Fallback brand detection
        if not item_brand:
            # Try to find brand-like patterns
            brand_match = re.search(
                r'(?:^|\s)([A-Z][A-Z0-9&\-]{2,}(?:\s+[A-Z][A-Z0-9&\-]+)*)\b',
                full_text
            )
            item_brand = brand_match.group(1).strip() if brand_match else ""
            
            # Final fallback - first words
            if not item_brand or len(item_brand.split()) > 3:
                item_brand = ' '.join(full_text.split()[:2]).strip()

        # Clean description
        item_description = full_text.strip()
        
        # Remove brand if found at beginning
        if item_brand:
            brand_pattern = re.escape(item_brand)
            item_description = re.sub(
                rf'^{brand_pattern}[,\s\-]*', 
                '', 
                item_description, 
                flags=re.IGNORECASE
            ).strip()
        
        # Remove common patterns
        patterns_to_remove = [
            r'\$\d+(?:\.\d{2})?\s*(?:OFF|SAVE|off|save)',
            r'Limit\s+\d+|While\s+supplies\s+last',
            r'\$[\d,]+\.\d{2}(?!\s*(?:OFF|SAVE))',
            r'[\*•\-]+',
            r'\b(?:online|warehouse|in-warehouse|only|offer|valid)\b'
        ]
        
        for pattern in patterns_to_remove:
            item_description = re.sub(
                pattern, 
                ' ', 
                item_description, 
                flags=re.IGNORECASE
            )
        
        # Final cleaning
        item_description = re.sub(r'\s{2,}', ' ', item_description).strip()
        item_description = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', item_description)
        
        # If description is too short, use alternative approach
        if len(item_description) < 10:
            item_description = ' '.join(
                word for word in full_text.split() 
                if not any(
                    word.lower() in brand_word.lower() 
                    for brand_word in item_brand.split()
                )
            )[:100].strip()

        # Extract other fields
        discount_match = re.search(
            r'\$[\d,]+(?:\.[\d]{2})?\s*(?:OFF|SAVE|off|save)', 
            block, 
            re.IGNORECASE
        )
        discount = discount_match.group(0) if discount_match else ""
        discount_cleaned = re.sub(r'[^\d.]', '', discount) if discount else ""

        limit = re.search(
            r'(Limit\s+\d+|While\s+supplies\s+last)', 
            block, 
            re.IGNORECASE
        )
        price = re.search(
            r'\$[\d,]+\.\d{2}(?!\s*(?:OFF|SAVE|off|save))', 
            block
        )

        # Determine channel
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

        data.append({
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'article_name': article_name,
            'publish_date': publish_date,
            'item_brand': item_brand[:50],
            'item_description': item_description[:200],
            'discount': discount,
            'discount_cleaned': discount_cleaned,
            'count_limit': limit.group(0) if limit else "",
            'channel': channel,
            'discount_period': discount_period,
            'item_original_price': price.group(0) if price else "",
            'source_url': source_url
        })

    return data

# === CORE SCRAPING ===
def scrape_images_from_page(url, is_hot_buy=False, article_name="", publish_date=""):
    html = get_page(url)
    if not html:
        return []

    brand_file = 'hot_buy_brands.txt' if is_hot_buy else 'coupon_book_brands.txt'
    known_brands = load_known_brands(brand_file)

    soup = BeautifulSoup(html, 'html.parser')
    discount_period = extract_discount_period(soup, is_hot_buy)
    items = []

    # Determine image selectors
    selectors = CONFIG['image_selectors']['hot_buy' if is_hot_buy else 'coupon']
    images = []
    
    for selector in selectors:
        images = soup.select(selector)
        if images:
            break
    
    if not images:
        images = soup.select('img')
    
    logging.info(f"Found {len(images)} images on {url}")

    for img_tag in images:
        img_url = img_tag.get('src', '').strip()
        if not img_url:
            continue
            
        if not img_url.startswith(('http://', 'https://')):
            img_url = urljoin(url, img_url)

        logging.info(f"Processing image: {img_url}")
        img = download_image(img_url, url)
        if not img:
            continue

        text = extract_text_from_image(img)
        if not text or len(text) < 20:
            logging.warning(f"Skipping image with insufficient text: {img_url}")
            continue

        parsed_data = parse_coupon_data(
            text, img_url, is_hot_buy, 
            known_brands, article_name, 
            publish_date, discount_period
        )
        items.extend(parsed_data)

    # Handle pagination for hot buys
    if is_hot_buy and items:
        next_page = soup.find('a', string=re.compile(r'next|›|>', re.IGNORECASE))
        if next_page and next_page.get('href'):
            next_url = urljoin(url, next_page['href'])
            logging.info(f"Found next page: {next_url}")
            items.extend(scrape_images_from_page(
                next_url, is_hot_buy, 
                article_name, publish_date
            ))

    return items

# === DATA SAVING ===
def save_data(data, filename, format='excel'):
    if not data:
        logging.warning(f"No data to save for {filename}")
        return

    df = pd.DataFrame(data)
    columns = [
        'scrape_datetime', 'article_name', 'publish_date', 
        'item_brand', 'item_description', 'discount',
        'discount_cleaned', 'count_limit', 'channel',
        'discount_period', 'item_original_price', 'source_url'
    ]
    df = df[columns]

    try:
        if format.lower() == 'excel':
            df.to_excel(filename, index=False)
        else:
            df.to_csv(filename, index=False)
        logging.info(f"Successfully saved {len(df)} records to {filename}")
    except Exception as e:
        logging.error(f"Failed to save data: {e}")

# === MAIN EXECUTION ===
def main(historical=False, months_back=24):
    if not initialize():
        return

    coupon_data = []
    hot_buys_data = []
    current_date = datetime.now()
    
    if historical:
        logging.info(f"Starting historical scrape for {months_back} months back")
        start_date = current_date - timedelta(days=30*months_back)
        
        while start_date <= current_date:
            month = start_date.strftime('%B').lower()
            year = start_date.year
            
            # Coupon Book
            coupon_url = CONFIG['coupon_base_url'].format(month=month, year=year)
            article_name = f"Costco {month.capitalize()} {year} Coupon Book"
            publish_date = start_date.replace(day=1).strftime('%Y-%m-%d')
            
            logging.info(f"Scraping coupon book: {article_name}")
            coupons = scrape_images_from_page(
                coupon_url, False, article_name, publish_date
            )
            coupon_data.extend(coupons)
            
            # Hot Buys
            hot_buys_url = CONFIG['hot_buys_base_url'].format(month=month, year=year)
            article_name = f"Costco {month.capitalize()} {year} Hot Buys"
            
            logging.info(f"Scraping hot buys: {article_name}")
            hot_buys = scrape_images_from_page(
                hot_buys_url, True, article_name, publish_date
            )
            hot_buys_data.extend(hot_buys)
            
            # Move to next month
            start_date = (start_date.replace(day=1) + timedelta(days=32))
    else:
        # Current month only
        month = current_date.strftime('%B').lower()
        year = current_date.year
        
        # Coupon Book
        coupon_url = CONFIG['coupon_base_url'].format(month=month, year=year)
        article_name = f"Costco {month.capitalize()} {year} Coupon Book"
        publish_date = current_date.replace(day=1).strftime('%Y-%m-%d')
        
        logging.info(f"Scraping current coupon book: {article_name}")
        coupon_data = scrape_images_from_page(
            coupon_url, False, article_name, publish_date
        )
        
        # Hot Buys
        hot_buys_url = CONFIG['hot_buys_base_url'].format(month=month, year=year)
        article_name = f"Costco {month.capitalize()} {year} Hot Buys"
        
        logging.info(f"Scraping current hot buys: {article_name}")
        hot_buys_data = scrape_images_from_page(
            hot_buys_url, True, article_name, publish_date
        )

    # Save results
    date_str = current_date.strftime('%Y-%m-%d')
    if historical:
        save_data(coupon_data, f"costco_historical_coupons_{date_str}.xlsx")
        save_data(hot_buys_data, f"costco_historical_hot_buys_{date_str}.xlsx")
    else:
        save_data(coupon_data, f"costco_current_coupons_{date_str}.xlsx")
        save_data(hot_buys_data, f"costco_current_hot_buys_{date_str}.xlsx")

    logging.info("Scraping completed successfully")

if __name__ == "__main__":
    # For current month only
    main(historical=False)
    
    # For historical data (past 24 months)
    # main(historical=True, months_back=24)