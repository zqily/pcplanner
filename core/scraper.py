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
    try:
        # Extract all digits
        nums = re.findall(r'\d+', str(price_text))
        return int("".join(nums)) if nums else 0
    except ValueError:
        return 0

def scrape_tokopedia(url: str, session: Optional[requests.Session] = None) -> Tuple[Optional[int], Optional[str]]:
    """
    Scrapes a Tokopedia product page for price and image URL.
    Returns: (price_int, image_url_str) or (None, None) on failure.
    """
    if not url or "tokopedia.com" not in url:
        logger.error(f"Invalid Tokopedia URL provided: {url}")
        return None, None

    # Use provided session or create a one-off
    requester = session if session else requests
    
    max_retries = 3
    retry_delay = 2
    response = None

    for attempt in range(max_retries):
        try:
            response = requester.get(url, headers=HEADERS, timeout=NETWORK_TIMEOUT)
            response.raise_for_status()
            break
        except requests.exceptions.HTTPError as e:
            # If 404 or 403, retrying usually doesn't help unless it's temporary blocking
            logger.warning(f"HTTP error {e.response.status_code} for {url} on attempt {attempt + 1}")
            if e.response.status_code == 404:
                return None, None # Product gone
            time.sleep(retry_delay)
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

        # --- Method 1: JSON-LD (Preferred, usually most reliable) ---
        script_tag = soup.find('script', type='application/ld+json')
        if script_tag and script_tag.string:
            try:
                # Fix concatenated JSON objects often found in Tokopedia source
                json_content = script_tag.string
                # Wrap in list if multiple objects exist in one script block
                # Only if not already a valid json structure
                if not json_content.strip().startswith('['):
                     json_data_list = json.loads(f'[{json_content.replace("}{", "},{")}]')
                else:
                     json_data_list = json.loads(json_content)

                # Find the 'Product' type in the list
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
            except json.JSONDecodeError:
                logger.warning(f"JSON-LD parsing error for {url}. Falling back to HTML.")
            except Exception as e:
                logger.warning(f"JSON-LD extraction failed for {url}: {e}. Falling back to HTML.")

        # --- Method 2: HTML Fallback (Selectors change often) ---
        if price is None:
            el = soup.find('div', {'data-testid': 'lblPDPDetailProductPrice'})
            if el: 
                price = clean_price(el.text)
        
        if image_url is None:
            # Primary image container
            el = soup.find('img', {'data-testid': 'PDPMainImage'})
            if el:
                src_val = el.get('src')
                if isinstance(src_val, str):
                    image_url = src_val
            
            if not image_url:
                # Secondary fallback container often used in mobile view or gallery
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
        logger.error(f"Unexpected exception during parsing of {url}: {e}", exc_info=True)
        return None, None