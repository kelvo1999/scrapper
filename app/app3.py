import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
from datetime import datetime
import time
from urllib.parse import urljoin

# Configuration
BASE_URL = "https://www.costcoinsider.com/category/coupons/"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
DELAY = 3  # seconds between requests

def get_soup(url):
    """Fetch webpage with retries and delay"""
    try:
        time.sleep(DELAY)
        print(f"📡 Fetching: {url}")
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"❌ Error fetching {url}: {str(e)}")
        return None

def clean_text(text):
    """Clean and normalize text"""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def extract_discount(text):
    """Extract discount amount from text"""
    matches = re.findall(r'\$(\d+(?:\.\d{1,2})?)\s*off', text, re.IGNORECASE)
    return matches[0] if matches else ""

def extract_limit(text):
    """Extract purchase limit from text"""
    match = re.search(r'(Limit\s*\d+|Limited\s*time)', text, re.IGNORECASE)
    return match.group(0) if match else ""

def extract_original_price(text):
    """Extract original price when shown before discount"""
    match = re.search(r'\$(\d+\.\d{2})(?:\s*[\-–]\s*\$?\d+\.\d{2})?', text)
    return f"${match.group(1)}" if match else ""

def extract_coupon_book_data(book_url):
    """Extract data from coupon book pages"""
    print(f"📦 Processing coupon book: {book_url}")
    soup = get_soup(book_url)
    if not soup:
        return []
    
    # Save HTML for debugging
    with open("debug_coupon.html", "w", encoding="utf-8") as f:
        f.write(str(soup))
    
    # Extract metadata
    title = clean_text(soup.title.text) if soup.title else ""
    publish_date = re.search(r'\b[A-Za-z]+\s\d{4}\b', title)
    discount_period = re.search(r'[A-Za-z]+\s\d{1,2}(?:st|nd|rd|th)?\s*through\s*[A-Za-z]+\s\d{1,2}(?:st|nd|rd|th)?', title, re.IGNORECASE)
    
    coupons = []
    # Improved selector targeting coupon items
    items = soup.select('.entry-content ul li, .coupon-item, .product-item')
    
    for item in items:
        text = clean_text(item.get_text())
        if len(text.split()) < 3:  # Skip short text blocks
            continue
        
        # Improved brand/description extraction
        brand = ""
        description = text
        brand_match = re.match(r'^([A-Z][a-z]+)(?=\s)', text)
        if brand_match:
            brand = brand_match.group(1)
            description = text[len(brand):].strip()
        
        discount_text = re.search(r'\$\d+(?:\.\d{1,2})?\s*off', text, re.IGNORECASE)
        
        coupons.append({
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'article_name': title,
            'publish_date': publish_date.group(0) if publish_date else "",
            'item_brand': brand,
            'item_description': description,
            'discount': discount_text.group(0) if discount_text else "",
            'discount_cleaned': extract_discount(text),
            'count_limit': extract_limit(text),
            'channel': "",
            'discount_period': discount_period.group(0) if discount_period else "",
            'item_original_price': extract_original_price(text)
        })
    
    print(f"✅ Found {len(coupons)} coupons")
    return coupons

def extract_hot_buys_data(hot_buys_url):
    """Extract data from hot buys pages"""
    print(f"🔥 Processing hot buys: {hot_buys_url}")
    soup = get_soup(hot_buys_url)
    if not soup:
        return []
    
    # Save HTML for debugging
    with open("debug_hotbuys.html", "w", encoding="utf-8") as f:
        f.write(str(soup))
    
    # Extract metadata
    title = clean_text(soup.title.text) if soup.title else ""
    publish_date = re.search(r'\b[A-Za-z]+\s\d{4}\b', title)
    discount_period = re.search(r'[A-Za-z]+\s\d{1,2}(?:st|nd|rd|th)?\s*through\s*[A-Za-z]+\s\d{1,2}(?:st|nd|rd|th)?', title, re.IGNORECASE)
    
    hot_buys = []
    # Improved selector targeting hot buy items
    items = soup.select('.entry-content ul li, .hot-buy-item, .deal-item')
    
    for item in items:
        text = clean_text(item.get_text())
        if len(text.split()) < 3:  # Skip short text blocks
            continue
        
        # Extract channel information
        channel = ""
        if "warehouse" in text.lower() and "online" in text.lower():
            channel = "In-Warehouse + Online"
        elif "warehouse" in text.lower():
            channel = "In-Warehouse"
        elif "online" in text.lower():
            channel = "Online"
        
        # Improved brand/description extraction
        brand = ""
        description = text
        brand_match = re.match(r'^([A-Z][a-z]+)(?=\s)', text)
        if brand_match:
            brand = brand_match.group(1)
            description = text[len(brand):].strip()
        
        discount_text = re.search(r'\$\d+(?:\.\d{1,2})?\s*off', text, re.IGNORECASE)
        
        hot_buys.append({
            'scrape_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'article_name': title,
            'publish_date': publish_date.group(0) if publish_date else "",
            'item_brand': brand,
            'item_description': description,
            'discount': discount_text.group(0) if discount_text else "",
            'discount_cleaned': extract_discount(text),
            'count_limit': extract_limit(text),
            'channel': channel,
            'discount_period': discount_period.group(0) if discount_period else "",
            'item_original_price': extract_original_price(text)
        })
    
    # Pagination handling for hot buys
    next_page = soup.find('a', string=re.compile(r'next|›|>', re.IGNORECASE))
    if next_page and next_page.get('href'):
        next_url = urljoin(hot_buys_url, next_page['href'])
        print(f"➡️ Found next page: {next_url}")
        hot_buys.extend(extract_hot_buys_data(next_url))
    
    print(f"✅ Found {len(hot_buys)} hot buys")
    return hot_buys

def main():
    # Update these URLs with current coupon pages
    current_coupon_url = "https://www.costcoinsider.com/costco-april-2025-coupon-book/"
    current_hot_buys_url = "https://www.costcoinsider.com/costco-april-2025-hot-buys-coupons/"
    
    # Scrape coupon book data
    coupon_data = extract_coupon_book_data(current_coupon_url)
    coupon_df = pd.DataFrame(coupon_data)
    
    # Scrape hot buys data
    hot_buys_data = extract_hot_buys_data(current_hot_buys_url)
    hot_buys_df = pd.DataFrame(hot_buys_data)
    
    # Save to CSV files
    today = datetime.now().strftime('%Y-%m-%d')
    coupon_csv = f"Coupon_Books_{today}.csv"
    hot_buys_csv = f"Hot_Buys_{today}.csv"
    
    coupon_df.to_csv(coupon_csv, index=False)
    hot_buys_df.to_csv(hot_buys_csv, index=False)
    
    print("\n🎉 Scraping complete!")
    print(f"📋 Coupon book data saved to: {coupon_csv}")
    print(f"📋 Hot buys data saved to: {hot_buys_csv}")
    print(f"📊 Total coupons: {len(coupon_df)}")
    print(f"📊 Total hot buys: {len(hot_buys_df)}")

if __name__ == "__main__":
    main()