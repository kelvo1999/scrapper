import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import urljoin
import time
from datetime import datetime, timedelta
import re

# Constants
BASE_URL = "https://www.costcoinsider.com/category/coupons/"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}
MAX_RETRIES = 3
DELAY = 2  # seconds between requests

def get_soup(url):
    """Fetch and parse a webpage with retries and delay."""
    for _ in range(MAX_RETRIES):
        try:
            time.sleep(DELAY)
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            time.sleep(DELAY * 2)
    return None

def clean_discount(text):
    """Extract numeric discount value."""
    match = re.search(r'\$?(\d+(?:\.\d{1,2})?)', text)
    return match.group(1) if match else ''

def extract_coupon_book_data(book_url):
    soup = get_soup(book_url)
    if not soup:
        return []

    # Extract month and year
    match = re.search(r'/(costco-)?(\w+)-(\d{4})', book_url.lower())
    month = match.group(2).capitalize() if match else 'Unknown'
    year = match.group(3) if match else 'Unknown'

    coupons = []
    items = soup.find_all(['li', 'p'])
    print(f"🔍 Found {len(items)} items on {book_url}")

    for item in items:
        text = item.get_text(strip=True)
        if not text or len(text) < 10:
            continue

        discount = ''
        match = re.search(r'\$\d+(\.\d{1,2})?', text)
        if match:
            discount = match.group(0)

        count_limit = ''
        limit_match = re.search(r'Limit\s\d+', text, re.IGNORECASE)
        if limit_match:
            count_limit = limit_match.group(0)

        coupons.append({
            'Item Name': text,
            'Channel': 'Coupon Book',
            'Discount': discount,
            'Discount Period': f"{month} {year}",
            'Item Count Limit': count_limit,
            'Original Price': '',
            'Discounted Price': clean_discount(discount),
            'Item Code': '',
            'Source URL': book_url,
            'Type': 'Regular Coupon',
            'Scrape Date': datetime.now().strftime('%Y-%m-%d')
        })

    return coupons

def extract_hot_buys_data(hot_buys_url):
    soup = get_soup(hot_buys_url)
    if not soup:
        return []

    match = re.search(r'/(costco-)?(\w+)-(\d{4})', hot_buys_url.lower())
    month = match.group(2).capitalize() if match else 'Unknown'
    year = match.group(3) if match else 'Unknown'

    hot_buys = []
    items = soup.find_all(['li', 'p'])
    print(f"🔍 Found {len(items)} items on {hot_buys_url}")

    for item in items:
        text = item.get_text(strip=True)
        if not text or len(text) < 10:
            continue

        discount = ''
        match = re.search(r'\$\d+(\.\d{1,2})?', text)
        if match:
            discount = match.group(0)

        count_limit = ''
        limit_match = re.search(r'Limit\s\d+', text, re.IGNORECASE)
        if limit_match:
            count_limit = limit_match.group(0)

        hot_buys.append({
            'Item Name': text,
            'Channel': 'Hot Buys',
            'Discount': discount,
            'Discount Period': f"{month} {year}",
            'Item Count Limit': count_limit,
            'Original Price': '',
            'Discounted Price': clean_discount(discount),
            'Item Code': '',
            'Source URL': hot_buys_url,
            'Type': 'Hot Buy',
            'Scrape Date': datetime.now().strftime('%Y-%m-%d')
        })

    # Check for pagination
    next_page = soup.find('a', string=re.compile(r'Next|›', re.IGNORECASE))
    if next_page and next_page.get('href'):
        next_page_url = urljoin(hot_buys_url, next_page['href'])
        hot_buys.extend(extract_hot_buys_data(next_page_url))

    return hot_buys

def get_historical_links(main_url, years_back=2):
    soup = get_soup(main_url)
    if not soup:
        return [], []

    cutoff_date = datetime.now() - timedelta(days=365 * years_back)
    coupon_links = []
    hot_buy_links = []

    articles = soup.select('article')
    for article in articles:
        try:
            date_str = article.select_one('.entry-date')['datetime']
            article_date = datetime.strptime(date_str, '%Y-%m-%d')
            if article_date < cutoff_date:
                continue

            link = article.select_one('a')['href']
            title = article.select_one('a').text.lower()

            if 'coupon book' in title:
                coupon_links.append(link)
            elif 'hot buys' in title:
                hot_buy_links.append(link)
        except:
            continue

    return coupon_links, hot_buy_links

def main():
    columns = [
        'Item Name', 'Channel', 'Discount', 'Discount Period',
        'Item Count Limit', 'Original Price', 'Discounted Price',
        'Item Code', 'Source URL', 'Type', 'Scrape Date'
    ]
    all_data = pd.DataFrame(columns=columns)

    # Current month links
    current_coupon_url = "https://www.costcoinsider.com/costco-april-2025-coupon-book/"
    current_hot_buys_url = "https://www.costcoinsider.com/costco-april-2025-hot-buys-coupons/"

    print("📦 Processing current coupon book...")
    all_data = pd.concat([all_data, pd.DataFrame(extract_coupon_book_data(current_coupon_url))], ignore_index=True)

    print("🔥 Processing current hot buys...")
    all_data = pd.concat([all_data, pd.DataFrame(extract_hot_buys_data(current_hot_buys_url))], ignore_index=True)

    print("⏳ Fetching historical links...")
    coupon_links, hot_buy_links = get_historical_links(BASE_URL, years_back=2)
    print(f"✅ Found {len(coupon_links)} coupon books and {len(hot_buy_links)} hot buys")

    print("📚 Processing historical coupon books...")
    for link in coupon_links:
        all_data = pd.concat([all_data, pd.DataFrame(extract_coupon_book_data(link))], ignore_index=True)

    print("🛒 Processing historical hot buys...")
    for link in hot_buy_links:
        all_data = pd.concat([all_data, pd.DataFrame(extract_hot_buys_data(link))], ignore_index=True)

    # Save
    output_file = f"costco_coupons_{datetime.now().strftime('%Y%m%d')}.csv"
    all_data.to_csv(output_file, index=False)
    print(f"✅ Data saved to {output_file}")
    print(f"📊 Total records collected: {len(all_data)}")

if __name__ == "__main__":
    main()
