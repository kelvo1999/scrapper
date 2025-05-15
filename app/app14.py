import requests
from bs4 import BeautifulSoup
import pandas as pd
import pytesseract
from PIL import Image, ImageEnhance
from io import BytesIO
import re
from datetime import datetime, date
from urllib.parse import urljoin
import time
import cv2
import numpy as np
from rapidfuzz import process
import logging
from typing import List, Dict, Tuple, Optional, Set
import os

# === CONFIGURATION ===
CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'min_delay': 1,
    'max_delay': 3,
    'max_retries': 3,
    'tesseract_path': r'C:\Users\kelvin.shisanya\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    'image_selectors': {
        'coupon': ['img[src*="coupon"]', 'div.entry-content img'],
        'hot_buy': ['img[src*="hotbuy"]', 'img[src*="deal"]', 'div.hot-deals img']
    },
    'default_brands': {
        'SunVilla', 'Charmin', 'Yardistry', 'Dyson Cyclone', 'Pistachios', 'Primavera Mistura',
        'Apples', 'Palmiers', 'Waterloo', 'Woozoo', 'Mower', 'Trimmer', 'Jet Blower',
        'Scotts', 'Huggies', 'Powder', 'Cookie', 'Kerrygold', 'Prawn Hacao'
    }
}

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('costco_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_current_month_year() -> Tuple[str, str]:
    """Get current month and year as strings."""
    today = date.today()
    return today.strftime("%B"), today.strftime("%Y")

def load_known_brands(filepath: str) -> Set[str]:
    """Load known brands from a file or use defaults."""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                brands = {line.strip() for line in f if line.strip()}
                if brands:
                    logger.info(f"Loaded {len(brands)} brands from {filepath}")
                    return brands
                
        logger.warning(f"Brand file {filepath} not found or empty. Using default brands.")
        return CONFIG['default_brands']
    except Exception as e:
        logger.error(f"Error loading brand file: {e}")
        return CONFIG['default_brands']

def initialize() -> bool:
    """Initialize Tesseract OCR."""
    try:
        pytesseract.pytesseract.tesseract_cmd = CONFIG['tesseract_path']
        version = pytesseract.get_tesseract_version()
        logger.info(f"Tesseract initialized (v{version})")
        return True
    except Exception as e:
        logger.error(f"Tesseract init error: {e}")
        return False

def get_page(url: str, retry_count: int = 0) -> Optional[str]:
    """Fetch a web page with retries and random delays."""
    try:
        delay = np.random.uniform(CONFIG['min_delay'], CONFIG['max_delay'])
        time.sleep(delay)
        
        headers = {
            'User-Agent': CONFIG['user_agent'],
            'Accept-Language': 'en-US,en;q=0.9'
        }
        
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        
        # Check if content is HTML
        if 'text/html' not in res.headers.get('Content-Type', ''):
            logger.warning(f"Non-HTML content received from {url}")
            return None
            
        return res.text
    except requests.exceptions.RequestException as e:
        if retry_count < CONFIG['max_retries']:
            logger.warning(f"Retry {retry_count + 1} for {url}: {e}")
            return get_page(url, retry_count + 1)
        logger.error(f"Failed to fetch {url} after {CONFIG['max_retries']} retries: {e}")
        return None

def download_image(img_url: str, referer: str) -> Optional[Image.Image]:
    """Download and preprocess an image."""
    try:
        headers = {
            'User-Agent': CONFIG['user_agent'],
            'Referer': referer,
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
        }
        
        res = requests.get(img_url, headers=headers, timeout=10)
        res.raise_for_status()
        
        if not res.headers.get("Content-Type", "").startswith("image"):
            logger.warning(f"Skipping non-image: {img_url}")
            return None
            
        img = Image.open(BytesIO(res.content))
        
        # Convert to OpenCV format for processing
        img_np = np.array(img)
        if img_np.ndim == 2:
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
        elif img_np.shape[2] == 4:
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        else:
            img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        
        # Image processing pipeline
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        denoised = cv2.fastNlMeansDenoising(thresh, None, 30, 7, 21)
        
        # Convert back to PIL Image
        img = Image.fromarray(denoised)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        
        return img
    except Exception as e:
        logger.error(f"Error processing image {img_url}: {e}")
        return None

def split_grid_image_dynamic(img: Image.Image) -> List[Image.Image]:
    """Split grid image into sub-images based on content analysis."""
    width, height = img.size
    
    # Use edge detection to determine optimal splits
    img_np = np.array(img)
    edges = cv2.Canny(img_np, 50, 150)
    
    # Detect vertical lines
    vertical_projection = np.sum(edges, axis=0)
    vertical_peaks = np.where(vertical_projection > np.mean(vertical_projection) * 1.5)[0]
    
    # Detect horizontal lines
    horizontal_projection = np.sum(edges, axis=1)
    horizontal_peaks = np.where(horizontal_projection > np.mean(horizontal_projection) * 1.5)[0]
    
    # Determine columns and rows
    columns = len(vertical_peaks) + 1 if len(vertical_peaks) > 0 else (4 if width > 900 else 3)
    rows = len(horizontal_peaks) + 1 if len(horizontal_peaks) > 0 else 2
    
    # Split image
    cell_width = width // columns
    cell_height = height // rows
    
    sub_images = []
    for row in range(rows):
        for col in range(columns):
            left = col * cell_width
            upper = row * cell_height
            right = (col + 1) * cell_width
            lower = (row + 1) * cell_height
            sub_images.append(img.crop((left, upper, right, lower)))
    
    return sub_images

def extract_text_from_image(img: Image.Image) -> str:
    """Extract text from image using OCR with error correction."""
    config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
    try:
        text = pytesseract.image_to_string(img, config=config).strip()
        
        # Common OCR corrections
        corrections = {
            '|': 'I', 
            '1': 'I', 
            '0': 'O', 
            'vv': 'W',
            '$': 'S',
            '©': 'C',
            '®': '',
            '™': ''
        }
        
        for wrong, right in corrections.items():
            text = text.replace(wrong, right)
            
        # Remove multiple spaces and newlines
        text = ' '.join(text.split())
        
        return text
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return ""

def fuzzy_find_brand(ocr_text: str, known_brands: Set[str]) -> Optional[str]:
    """Find the best brand match using fuzzy matching."""
    if not ocr_text or not known_brands:
        return None
        
    # Try to extract potential brand candidates from the first few words
    first_words = ' '.join(ocr_text.split()[:3])
    match = process.extractOne(first_words, known_brands, score_cutoff=80)
    
    if match:
        logger.debug(f"Fuzzy matched brand: {match[0]} (score: {match[1]})")
        return match[0]
    return None

def parse_coupon_data(text: str, source_url: str, is_hot_buy: bool, known_brands: Set[str]) -> List[Dict[str, str]]:
    """Parse coupon data from OCR text."""
    if not text:
        return []
    
    current_month, current_year = get_current_month_year()
    data = []
    blocks = re.split(r'(?=\$\d+(?:\.\d{2})?\s*OFF)', text)
    
    for block in blocks:
        full_text = ' '.join(block.split())
        if len(full_text) < 10:
            continue
            
        # Brand detection
        item_brand = next((b for b in known_brands if re.search(rf'\b{re.escape(b)}\b', full_text, re.IGNORECASE)), '')
        if not item_brand:
            fuzzy = fuzzy_find_brand(' '.join(full_text.split()[:3]), known_brands)
            item_brand = fuzzy if fuzzy else ''
            
        # Clean up description
        item_description = re.sub(rf'^\s*{re.escape(item_brand)}[\s:,-]*', '', full_text, flags=re.IGNORECASE)
        item_description = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', item_description).strip()
        item_description = re.sub(r'\s+', ' ', item_description)
        
        # Extract deal information
        discount_match = re.search(r'\$[0-9]+(?:\.\d{2})?\s*OFF', block, re.IGNORECASE)
        discount = discount_match.group(0) if discount_match else ""
        discount_cleaned = re.sub(r'[^\d.]', '', discount)
        
        limit = re.search(r'(Limit\s+\d+|While\s+supplies\s+last)', block, re.IGNORECASE)
        price = re.search(r'\$[0-9]+\.\d{2}', block)
        
        # Determine channel
        channel = ""
        if is_hot_buy:
            block_lower = block.lower()
            if 'warehouse' in block_lower and 'online' in block_lower:
                channel = "In-Warehouse + Online"
            elif 'warehouse' in block_lower:
                channel = "In-Warehouse"
            elif 'online' in block_lower:
                channel = "Online"
        
        # Dynamic date handling
        today = date.today()
        if is_hot_buy:
            # Hot buys typically run for 1 week starting near the end of the month
            start_date = date(today.year, today.month, 28)  # 28th of current month
            end_date = start_date + timedelta(days=7)
        else:
            # Coupon books typically run for 4 weeks starting near the beginning of the month
            start_date = date(today.year, today.month, 9)  # 9th of current month
            end_date = start_date + timedelta(days=25)
        
        discount_period = f"{start_date.strftime('%B %d')} through {end_date.strftime('%B %d')}"
        
        data.append({
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'article_name': f"Costco {current_month} {current_year} Hot Buys Coupons" if is_hot_buy else f"Costco {current_month} {current_year} Coupon Book",
            'publish_date': f"{current_year}-{today.month:02d}-28 00:00:00" if is_hot_buy else f"{current_year}-{today.month:02d}-01 00:00:00",
            'item_brand': item_brand,
            'item_description': item_description,
            'discount': discount,
            'discount_cleaned': discount_cleaned,
            'count_limit': limit.group(0) if limit else "",
            'channel': channel,
            'discount_period': discount_period,
            'item_original_price': price.group(0) if price else "",
            'source_url': source_url
        })
    
    return data

def scrape_images_from_page(url: str, is_hot_buy: bool = False) -> List[Dict[str, str]]:
    """Scrape and process images from a webpage."""
    html = get_page(url)
    if not html:
        return []
    
    brand_file = 'hot_buy_brands.txt' if is_hot_buy else 'coupon_book_brands.txt'
    known_brands = load_known_brands(brand_file)
    soup = BeautifulSoup(html, 'html.parser')
    
    # Try all selectors until we find images
    selectors = CONFIG['image_selectors']['hot_buy'] if is_hot_buy else CONFIG['image_selectors']['coupon']
    images = []
    for selector in selectors:
        images = soup.select(selector)
        if images:
            logger.info(f"Found {len(images)} images using selector: {selector}")
            break
    
    # Fallback to all images if no matches
    if not images:
        images = soup.select('img')
        logger.warning(f"Using fallback selector - found {len(images)} images")
    
    items = []
    for img_tag in images:
        img_url = img_tag.get('src')
        if not img_url:
            continue
            
        if not img_url.startswith('http'):
            img_url = urljoin(url, img_url)
        
        logger.info(f"Processing image: {img_url}")
        img = download_image(img_url, url)
        if not img:
            continue
            
        # Split and process sub-images
        sub_imgs = split_grid_image_dynamic(img)
        for idx, sub_img in enumerate(sub_imgs):
            text = extract_text_from_image(sub_img)
            if not text:
                logger.debug(f"No text found in sub-image {idx + 1}")
                continue
                
            parsed = parse_coupon_data(text, img_url, is_hot_buy, known_brands)
            if isinstance(parsed, list):
                items.extend(parsed)
                logger.info(f"Found {len(parsed)} items in sub-image {idx + 1}")
    
    # Handle pagination for hot buys
    if is_hot_buy and items:
        next_page = soup.find('a', string=re.compile(r'next|›|>', re.IGNORECASE))
        if next_page and next_page.get('href'):
            next_url = urljoin(url, next_page['href'])
            logger.info(f"Found next page: {next_url}")
            items.extend(scrape_images_from_page(next_url, is_hot_buy))
    
    return items

def save_to_excel(data: List[Dict[str, str]], filename: str) -> None:
    """Save data to Excel file with validation."""
    if not data:
        logger.warning(f"No data to save for {filename}")
        return
        
    try:
        df = pd.DataFrame(data)
        
        # Ensure required columns exist
        required_columns = [
            'scrape_datetime', 'article_name', 'publish_date', 'item_brand',
            'item_description', 'discount', 'discount_cleaned', 'count_limit',
            'channel', 'discount_period', 'item_original_price', 'source_url'
        ]
        
        # Add missing columns if necessary
        for col in required_columns:
            if col not in df.columns:
                df[col] = ""
        
        df = df[required_columns]
        df.to_excel(filename, index=False)
        logger.info(f"Saved {len(df)} records to {filename}")
    except Exception as e:
        logger.error(f"Failed to save Excel file {filename}: {e}")

# def find_all_coupon_links() -> List[Tuple[str, str]]:
#     """Find all coupon and hot buy links from the main page."""
#     url = "https://www.costcoinsider.com/category/coupons/"
#     html = get_page(url)
#     if not html:
#         return []
        
#     soup = BeautifulSoup(html, 'html.parser')
#     links = []
    
#     for article in soup.select('article'):
#         a_tag = article.select_one('h2.entry-title a')
#         if not a_tag:
#             continue
            
#         title = a_tag.text.strip()
#         href = a_tag.get('href')
        
#         if href and ('hot buys' in title.lower() or 'coupon book' in title.lower()):
#             links.append((title, href))
#             logger.debug(f"Found coupon link: {title} - {href}")
    
#     return links

def find_all_coupon_links() -> List[Tuple[str, str]]:
    """Find all coupon and hot buy links from the main page."""
    url = "https://www.costcoinsider.com/category/coupons/"
    html = get_page(url)
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    links = []

    for article in soup.select('article'):
        a_tag = article.select_one('h2 a')  # <- FIXED LINE
        if not a_tag:
            continue

        title = a_tag.text.strip()
        href = a_tag.get('href')

        if href and ('hot buys' in title.lower() or 'coupon book' in title.lower()):
            links.append((title, href))
            logger.debug(f"Found coupon link: {title} - {href}")

    return links


def main():
    """Main execution function."""
    logger.info("Starting Costco coupon scraper")
    
    if not initialize():
        logger.error("Failed to initialize Tesseract OCR. Exiting.")
        return
        
    logger.info("Finding coupon post links...")
    post_links = find_all_coupon_links()
    
    if not post_links:
        logger.error("No valid post links found. Exiting.")
        return
        
    current_month, current_year = get_current_month_year()
    
    for title, link in post_links:
        is_hot_buy = 'hot buys' in title.lower()
        coupon_type = 'Hot Buys' if is_hot_buy else 'Coupon Book'
        
        logger.info(f"\nScraping {coupon_type}: {title}")
        items = scrape_images_from_page(link, is_hot_buy)
        
        if not items:
            logger.warning(f"No items found for {title}")
            continue
            
        # Extract year from title or use current year
        year_match = re.search(r'\b(20\d{2})\b', title)
        year = year_match.group(1) if year_match else current_year
        
        label = 'Hot_Buys' if is_hot_buy else 'Coupon_Books'
        filename = f"{year}_{current_month}_{label}.xlsx"
        
        save_to_excel(items, filename)
    
    logger.info("\nScraping complete!")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)