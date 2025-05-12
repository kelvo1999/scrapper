import requests
from bs4 import BeautifulSoup
import pandas as pd
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from io import BytesIO
import re
from datetime import datetime
from urllib.parse import urljoin
import time
import cv2
import numpy as np

# Configuration
CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'delay': 3,
    'tesseract_path': r'C:\Users\kelvin.shisanya\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',  # Update this path
    'image_selectors': {
        'coupon': ['img[src*="coupon"]', 'div.coupon-container img', 'div.entry-content img'],
        'hot_buy': ['img[src*="hotbuy"]', 'img[src*="deal"]', 'div.hot-deals img']
    }
}

def initialize():
    """Set up Tesseract and verify dependencies"""
    try:
        pytesseract.pytesseract.tesseract_cmd = CONFIG['tesseract_path']
        # Verify Tesseract is working
        pytesseract.get_tesseract_version()
        return True
    except Exception as e:
        print(f"❌ Tesseract initialization failed: {str(e)}")
        print("Please install Tesseract OCR and set the correct path in CONFIG")
        return False

def get_page(url):
    """Fetch webpage with error handling"""
    try:
        time.sleep(CONFIG['delay'])
        headers = {'User-Agent': CONFIG['user_agent']}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching {url}: {str(e)}")
        return None

def download_image(img_url, referer):
    """Download and preprocess image for better OCR"""
    try:
        headers = {
            'User-Agent': CONFIG['user_agent'],
            'Referer': referer
        }
        response = requests.get(img_url, headers=headers)
        response.raise_for_status()
        
        img = Image.open(BytesIO(response.content))
        
        # Convert to OpenCV format for advanced processing
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        # Preprocessing pipeline
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        denoised = cv2.fastNlMeansDenoising(thresh, None, 30, 7, 21)
        
        # Convert back to PIL Image
        img = Image.fromarray(denoised)
        
        # Additional enhancements
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.0)
        
        return img
    except Exception as e:
        print(f"Error processing image {img_url}: {str(e)}")
        return None

def extract_text_from_image(img):
    """Extract text with optimized OCR settings"""
    custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789$.abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ -c preserve_interword_spaces=1'
    try:
        text = pytesseract.image_to_string(img, config=custom_config)
        return text.strip()
    except Exception as e:
        print(f"OCR Error: {str(e)}")
        return ""

def parse_coupon_data(text, source_url, is_hot_buy=False):
    """Parse extracted text into structured data matching Excel format"""
    # Common field extraction
    brand_match = re.search(r'^([A-Z][a-zA-Z0-9&]+)', text)
    description_match = re.search(r'(?:\n|^)(.+?)(?=\$|\n|$)', text)
    discount_match = re.search(r'(\$\d+(?:\.\d{2})?\s*off)', text, re.IGNORECASE)
    price_match = re.search(r'(\$\d+\.\d{2})(?=\D|$)', text)
    limit_match = re.search(r'(Limit\s+\d+|While\s+supplies\s+last)', text, re.IGNORECASE)
    
    # Hot buy specific fields
    channel = ""
    if is_hot_buy:
        if re.search(r'warehouse.*online|online.*warehouse', text, re.IGNORECASE):
            channel = "In-Warehouse + Online"
        elif re.search(r'warehouse', text, re.IGNORECASE):
            channel = "In-Warehouse"
        elif re.search(r'online', text, re.IGNORECASE):
            channel = "Online"
    
    # Date parsing
    if is_hot_buy:
        period_match = re.search(r'([A-Za-z]+\s\d{1,2}(?:st|nd|rd|th)?\s*through\s*[A-Za-z]+\s\d{1,2}(?:st|nd|rd|th)?)', text, re.IGNORECASE)
        discount_period = period_match.group(0) if period_match else "Saturday March 29th through Sunday April 6th"
    else:
        discount_period = "April 9th through May 4th"
    
    return {
        'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
        'article_name': "Costco April 2025 Hot Buys Coupons" if is_hot_buy else "Costco April 2025 Coupon Book",
        'publish_date': "2025-03-28 00:00:00" if is_hot_buy else "2025-04-01 00:00:00",
        'item_brand': brand_match.group(1) if brand_match else "",
        'item_description': description_match.group(1).strip() if description_match else "",
        'discount': discount_match.group(1) if discount_match else "",
        'discount_cleaned': re.sub(r'[^\d.]', '', discount_match.group(1)) if discount_match else "",
        'count_limit': limit_match.group(0) if limit_match else "",
        'channel': channel,
        'discount_period': discount_period,
        'item_original_price': price_match.group(1) if price_match else "",
        'source_url': source_url
    }

def scrape_images_from_page(url, is_hot_buy=False):
    """Scrape all relevant images from a page and extract data"""
    html = get_page(url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    
    # Try different selectors until we find images
    selectors = CONFIG['image_selectors']['hot_buy'] if is_hot_buy else CONFIG['image_selectors']['coupon']
    images = []
    
    for selector in selectors:
        images = soup.select(selector)
        if images:
            break
    
    if not images:
        print("⚠️ No images found with configured selectors, trying fallback...")
        images = soup.select('img')
    
    for img in images:
        img_url = img['src']
        if not img_url.startswith('http'):
            img_url = urljoin(url, img_url)
        
        print(f"🔍 Processing image: {img_url}")
        image = download_image(img_url, url)
        if not image:
            continue
            
        text = extract_text_from_image(image)
        if not text:
            continue
            
        item_data = parse_coupon_data(text, img_url, is_hot_buy)
        if item_data:
            items.append(item_data)
    
    # Handle pagination for hot buys
    if is_hot_buy:
        next_page = soup.find('a', string=re.compile(r'next|›|>', re.IGNORECASE))
        if next_page and next_page.get('href'):
            next_url = urljoin(url, next_page['href'])
            print(f"➡️ Found next page: {next_url}")
            items.extend(scrape_images_from_page(next_url, is_hot_buy))
    
    return items

def save_to_excel(data, filename):
    """Save data to Excel with proper formatting"""
    df = pd.DataFrame(data)
    
    # Reorder columns to match your template
    columns = [
        'scrape_datetime', 'article_name', 'publish_date', 'item_brand',
        'item_description', 'discount', 'discount_cleaned', 'count_limit',
        'channel', 'discount_period', 'item_original_price', 'source_url'
    ]
    df = df[columns]
    
    # Rename columns to match your Excel headers
    df.columns = [
        'scrape_datetime', 'article_name', 'publish_date', 'item_brand',
        'item_description', 'discount', 'discount_cleaned', 'count_limit',
        'channel', 'discount_period', 'item_original_price', 'source_url'
    ]
    
    df.to_excel(filename, index=False)
    print(f"💾 Saved {len(df)} items to {filename}")

def main():
    if not initialize():
        return
    
    # Scrape Coupon Book
    coupon_url = "https://www.costcoinsider.com/costco-april-2025-coupon-book/"
    print("\n📘 Starting Coupon Book scrape...")
    coupon_items = scrape_images_from_page(coupon_url)
    save_to_excel(coupon_items, "2025-04-28_Coupon_Books.xlsx")
    
    # Scrape Hot Buys
    hot_buys_url = "https://www.costcoinsider.com/costco-april-2025-hot-buys-coupons/"
    print("\n🔥 Starting Hot Buys scrape...")
    hot_buys_items = scrape_images_from_page(hot_buys_url, is_hot_buy=True)
    save_to_excel(hot_buys_items, "2025-04-28_Hot_Buys_Coupons.xlsx")
    
    print("\n🎉 All done! Check the generated Excel files.")

if __name__ == "__main__":
    main()