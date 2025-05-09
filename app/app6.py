import requests
from bs4 import BeautifulSoup
import pandas as pd 
import re
from datetime import datetime

# Configuration
BASE_URL = "https://www.costcoinsider.com"
COUPON_URL = "https://www.costcoinsider.com/costco-april-2025-coupon-book/"  # Update this
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def get_page(url):
    """Fetch webpage with error handling"""
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching {url}: {str(e)}")
        return None

def extract_coupons(html):
    """Extract coupons from HTML using content patterns"""
    soup = BeautifulSoup(html, 'html.parser')
    
    # Save HTML for debugging
    with open("debug_page.html", "w", encoding="utf-8") as f:
        f.write(str(soup))
    
    # Find all text nodes that look like coupons
    coupons = []
    for element in soup.find_all(string=True):
        text = element.strip()
        if not text or len(text) < 20:
            continue
            
        # Look for price patterns in the text
        if re.search(r'\$\d+\.\d{2}\s*off|\$\d+\s*off', text):
            # Extract components
            brand = re.search(r'^([A-Z][a-zA-Z0-9&]+)', text)
            discount = re.search(r'(\$\d+(?:\.\d{2})?)\s*off', text)
            price = re.search(r'\$(\d+\.\d{2})(?=\D|$)', text)
            limit = re.search(r'(Limit\s+\d+|While\s+supplies\s+last)', text, re.IGNORECASE)
            
            coupons.append({
                'Item': text,
                'Brand': brand.group(1) if brand else '',
                'Discount': discount.group(1) if discount else '',
                'Price': f"${price.group(1)}" if price else '',
                'Limit': limit.group(0) if limit else ''
            })
    
    return coupons

def main():
    # Get the page
    html = get_page(COUPON_URL)
    if not html:
        print("Failed to fetch page")
        return
    
    # Extract coupons
    coupons = extract_coupons(html)
    
    if not coupons:
        print("No coupons found. Please check:")
        print("1. Open debug_page.html in browser")
        print("2. Find coupon text and identify its HTML structure")
        print("3. Let me know what you find to update the selector")
        return
    
    # Save to CSV
    df = pd.DataFrame(coupons)
    df.to_csv("costco_coupons.csv", index=False)
    print(f"Saved {len(df)} coupons to costco_coupons.csv")

if __name__ == "__main__":
    main()