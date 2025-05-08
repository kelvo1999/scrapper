import scrapy
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor
from scrapy.utils.project import get_project_settings
import csv
import datetime
import re  # Import the regular expression module


class CostcoCouponsSpider(CrawlSpider):
    name = 'costco_coupons'
    allowed_domains = ['costcoinsider.com']
    start_urls = ['https://www.costcoinsider.com/category/coupons/']

    rules = (
        # Follow links to coupon book and hot buys pages
        Rule(LinkExtractor(allow=(r'/costco-[\w-]+-coupon-book/', r'/costco-[\w-]+-hot-buys-coupons/')), callback='parse_article'),
        # Follow pagination links for hot buys pages (e.g., /costco-april-2025-hot-buys-coupons-page-1/)
        Rule(LinkExtractor(allow=(r'/costco-[\w-]+-hot-buys-coupons/costco-[\w-]+-hot-buys-coupons-page-\d+/',)), callback='parse_article'),
    )

    def __init__(self, *args, **kwargs):
        super(CostcoCouponsSpider, self).__init__(*args, **kwargs)
        # Initialize the CSV writer.  This creates the file and writes the header row.
        self.csv_file = open('costco_coupons.csv', 'w', newline='', encoding='utf-8')
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(['scrape_datetime', 'article_name', 'publish_date', 'item_brand', 'item_description', 'discount', 'discount_cleaned', 'count_limit', 'channel', 'discount_period', 'item_original_price'])
        self.settings = get_project_settings()  #Get settings.

    def closed(self, reason):
        # This method is called when the spider finishes.  Close the CSV file.
        self.csv_file.close()

    def parse_article(self, response):
        """
        Parses the article (coupon book or hot buys) and extracts the relevant data.
        """
        article_name = response.xpath('//h1[@class="entry-title"]/text()').get()
        publish_date = response.xpath('//time[@class="entry-date published updated"]/@datetime').get()
        if publish_date:
            publish_date = publish_date.split('T')[0]  # Extract only the date part
        else:
            publish_date = None

        # Extract coupon items.  This logic handles both coupon books and hot buys.
        # The মূল selector targets the individual coupon items within the page.
        for item in response.xpath('//div[@class="wp-block-columns is-layout-flex wp-block-column"] | //div[@class="fusion-text fusion-text-flow"]//p'): # Added fusion-text for hotbuys and adjusted xpath
            item_brand = None # Initialize item_brand
            item_description = item.xpath('.//text()').getall()
            item_description = ' '.join(item_description).strip() # convert description to string
            # Extract brand from description if possible
            if "Brand:" in item_description:
                item_brand = item_description.split("Brand:")[1].split()[0].strip()

            discount = item.xpath('.//strong/text()').get()  # Changed to get()
            if not discount:
                discount = item.xpath('.//span/text()').get()
            if not discount:
                continue # Skip if no discount

            count_limit = item.xpath('.//em/text()').get()
            channel = None  # Initialize channel
            if "In-Warehouse" in item_description and "Online" in item_description:
                channel = "In-Warehouse + Online"
            elif "In-Warehouse" in item_description:
                channel = "In-Warehouse"
            elif "Online" in item_description:
                channel = "Online"
            discount_period = None # Initialize
            price_info = item.xpath('.//text()').getall()
            price_info = " ".join(price_info)

            # Extract discount period
            if "through" in price_info:
                discount_period = price_info.split("through")[-1].strip()
            elif "thru" in price_info:
                discount_period = price_info.split("thru")[-1].strip()

            item_original_price = None

            # Extract the numeric value from the discount string
            discount_cleaned = None
            if discount:
                discount_cleaned = re.findall(r'(\d+\.?\d*)', discount)  # Find all numbers
                if discount_cleaned:
                    discount_cleaned = float(discount_cleaned[0])  # Use the first number found

            # Extract original price
            if "Original Price:" in price_info:
                try:
                    item_original_price = float(price_info.split("Original Price:")[1].split()[0].replace("$",""))
                except:
                    item_original_price = None

            #write row
            self.csv_writer.writerow([
                datetime.datetime.now().isoformat(),
                article_name,
                publish_date,
                item_brand,
                item_description,
                discount,
                discount_cleaned,
                count_limit,
                channel,
                discount_period,
                item_original_price
            ])
        
    def handle_error(self, failure):
        # Log any errors that occur during the scraping process
        self.logger.error(f"Error processing URL: {failure.request.url}")
        self.logger.error(failure.getTraceback())

