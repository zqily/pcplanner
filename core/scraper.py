import re
import json
import time
import logging
import requests
from typing import Optional, Tuple, Any
from bs4 import BeautifulSoup
from config import HEADERS, NETWORK_TIMEOUT

logger = logging.getLogger(__name__)

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
        logger.error(f"Invalid Tokopedia URL provided: {url}")
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
            logger.warning(f"Connection attempt {attempt + 1}/{max_retries} failed for {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error(f"All connection retries failed for {url}")
                return None, None

    if not response:
        return None, None

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        price: Optional[int] = None
        image_url: Optional[str] = None

        # --- Method 1: JSON-LD (Preferred) ---
        script_tag = soup.find('script', type='application/ld+json')
        if script_tag and script_tag.string:
            try:
                # Fix concatenated JSON objects often found in Tokopedia source
                json_content = script_tag.string
                # Wrap in list if multiple objects exist in one script block
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
                    elif isinstance(images, str):
                        image_url = images
            except Exception as e:
                logger.warning(f"JSON-LD parsing failed for {url}: {e}. Falling back to HTML.")

        # --- Method 2: HTML Fallback ---
        if price is None:
            el = soup.find('div', {'data-testid': 'lblPDPDetailProductPrice'})
            if el: 
                price = clean_price(el.text)
        
        if image_url is None:
            el = soup.find('img', {'data-testid': 'PDPMainImage'})
            if el:
                src_val = el.get('src')
                if isinstance(src_val, str):
                    image_url = src_val
            
            if not image_url:
                # Secondary fallback container
                container = soup.find('div', class_='css-1nchjne')
                if container:
                    img_sub = container.find('img')
                    if img_sub:
                        src_sub_val = img_sub.get('src')
                        if isinstance(src_sub_val, str):
                            image_url = src_sub_val
        
        if price is None and image_url is None:
            logger.warning(f"Scraper returned no data for {url}. Page structure might have changed.")

        return price, image_url

    except Exception as e:
        # Critical: Log the traceback so we know exactly what broke in the parsing logic
        logger.error(f"Unexpected exception during parsing of {url}", exc_info=True)
        return None, None