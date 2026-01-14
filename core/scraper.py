import re
import json
import time
import logging
import requests
from typing import Optional, Tuple, Any
from bs4 import BeautifulSoup
from config import HEADERS, NETWORK_TIMEOUT

def clean_price(price_text: Any) -> int:
    """Removes 'Rp', dots, and converts to an integer."""
    if not price_text:
        return 0
    nums = re.findall(r'\d+', str(price_text))
    return int("".join(nums)) if nums else 0

def scrape_tokopedia(url: str, session: Optional[requests.Session] = None) -> Tuple[Optional[int], Optional[str]]:
    """
    Scrapes a Tokopedia product page for price and image URL.
    Returns: (price_int, image_url_str) or (None, None) on failure.
    """
    if "tokopedia.com" not in url:
        logging.error(f"Invalid Tokopedia URL: {url}")
        return None, None

    requester = session if session else requests
    max_retries = 3
    retry_delay = 2
    response = None

    for attempt in range(max_retries):
        try:
            response = requester.get(url, headers=HEADERS, timeout=NETWORK_TIMEOUT)
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            logging.warning(f"Attempt {attempt + 1}/{max_retries} failed for {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                return None, None

    if not response:
        return None, None

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        price: Optional[int] = None
        image_url: Optional[str] = None

        # --- Method 1: JSON-LD ---
        script_tag = soup.find('script', type='application/ld+json')
        if script_tag and script_tag.string:
            try:
                # Fix concatenated JSON objects
                json_content = script_tag.string
                json_data_list = json.loads(f'[{json_content.replace("}{", "},{")}]')
                
                product_data = next((item for item in json_data_list if item.get('@type') == 'Product'), None)
                if product_data:
                    offers = product_data.get('offers', [])
                    if isinstance(offers, list) and offers:
                        price = clean_price(offers[0].get('price'))
                    elif isinstance(offers, dict):
                        price = clean_price(offers.get('price'))

                    images = product_data.get('image', [])
                    if isinstance(images, list) and images:
                        image_url = images[0]
            except Exception as e:
                logging.warning(f"JSON-LD parsing failed for {url}: {e}")

        # --- Method 2: HTML Fallback ---
        if price is None:
            el = soup.find('div', {'data-testid': 'lblPDPDetailProductPrice'})
            if el: 
                price = clean_price(el.text)
        
        if image_url is None:
            el = soup.find('img', {'data-testid': 'PDPMainImage'})
            if el:
                # Type safe extraction: Attributes can be str, list, or None
                src_val = el.get('src')
                if isinstance(src_val, str):
                    image_url = src_val
            
            if not image_url:
                # Secondary fallback
                container = soup.find('div', class_='css-1nchjne')
                if container:
                    img_sub = container.find('img')
                    if img_sub:
                        src_sub_val = img_sub.get('src')
                        if isinstance(src_sub_val, str):
                            image_url = src_sub_val

        return price, image_url

    except Exception as e:
        logging.error(f"Unexpected error parsing {url}: {e}", exc_info=True)
        return None, None