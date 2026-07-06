import requests
import pandas as pd
import re
import time
import sys
import os
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser


# =====================================================
# FIND MY GADGET SCRAPER
# First Method Scraping + Image Scraping + Data Cleaning
#
# Output: CSV only
# For app.py: rename final CSV to gadgets.csv
#
# Fields:
# category, brand, model, price, image_url, image_file,
# source_name, source_url, detail_url,
# ram, storage, processor, display, gpu, battery, camera, os
# =====================================================

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def safe_print(text=""):
    try:
        print(text)
    except UnicodeEncodeError:
        print(str(text).encode("ascii", "replace").decode("ascii"))


HEADERS = {
    "User-Agent": "FindMyGadgetStudentProject/1.0 (+educational-public-data)"
}

# Paths are anchored to this file, so n8n can call it from automation_api.py safely.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# n8n-friendly environment options:
#   SCRAPER_DELAY_SECONDS=2
#   MAX_RECORDS_PER_SOURCE=0
#   DOWNLOAD_IMAGES=1
DELAY_SECONDS = float(os.getenv("SCRAPER_DELAY_SECONDS", "2"))

# 0 means no limit. For testing, set env MAX_RECORDS_PER_SOURCE=20.
MAX_RECORDS_PER_SOURCE = int(os.getenv("MAX_RECORDS_PER_SOURCE", "0"))

# Image scraping settings
DOWNLOAD_IMAGES = os.getenv("DOWNLOAD_IMAGES", "1").lower() not in ["0", "false", "no"]
IMAGE_FOLDER = os.path.join(BASE_DIR, "gadget_images")
MAX_IMAGE_SIZE_MB = 5

ROBOTS_CACHE = {}

SOURCES = [
    # =====================================================
    # EXISTING SOURCES
    # =====================================================

    # PINOY TECHNO GUIDE - SMARTPHONES
    {"category": "Smartphone", "source_name": "PTG Realme", "url": "https://www.pinoytechnoguide.com/pricelists/realme", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG Vivo", "url": "https://www.pinoytechnoguide.com/pricelists/vivo", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG OPPO", "url": "https://www.pinoytechnoguide.com/pricelists/oppo", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG Samsung", "url": "https://www.pinoytechnoguide.com/pricelists/samsung", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG Xiaomi", "url": "https://www.pinoytechnoguide.com/pricelists/xiaomi", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG Infinix", "url": "https://www.pinoytechnoguide.com/pricelists/infinix", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG TECNO", "url": "https://www.pinoytechnoguide.com/pricelists/tecno", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG HONOR", "url": "https://www.pinoytechnoguide.com/pricelists/honor", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG Huawei", "url": "https://www.pinoytechnoguide.com/pricelists/huawei", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG Apple", "url": "https://www.pinoytechnoguide.com/pricelists/apple", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG POCO", "url": "https://www.pinoytechnoguide.com/pricelists/poco", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG Nokia", "url": "https://www.pinoytechnoguide.com/pricelists/nokia", "pages": 1},
    {"category": "Smartphone", "source_name": "PTG OnePlus", "url": "https://www.pinoytechnoguide.com/pricelists/oneplus", "pages": 1},

    # PINOY TECHNO GUIDE - TABLETS
    {"category": "Tablet", "source_name": "PTG Tablets", "url": "https://www.pinoytechnoguide.com/tablets", "pages": 5},

    # OLD LAPTOP SOURCES
    {"category": "Laptop", "source_name": "Benstore Laptops", "url": "https://benstore.com.ph/327-laptops", "pages": 8},
    {"category": "Laptop", "source_name": "Silicon Valley PH Laptops", "url": "https://siliconvalley.com.ph/product-category/laptops/", "pages": 8},

    # =====================================================
    # NEW PHILIPPINE PESO SOURCES
    # =====================================================

    # KIMSTORE
    {"category": "Smartphone", "source_name": "Kimstore Smartphones", "url": "https://www.kimstore.com/collections/smartphones", "pages": 5},
    {"category": "Smartphone", "source_name": "Kimstore Budget Phones", "url": "https://www.kimstore.com/collections/budget-friendly-mobile-phones", "pages": 3},
    {"category": "Tablet", "source_name": "Kimstore Tablets iPads", "url": "https://www.kimstore.com/collections/tablets-ipads", "pages": 4},
    {"category": "Tablet", "source_name": "Kimstore Android Tablets", "url": "https://www.kimstore.com/collections/android-tablets", "pages": 3},
    {"category": "Tablet", "source_name": "Kimstore Affordable Tablets", "url": "https://www.kimstore.com/collections/affordable-tablets", "pages": 3},

    # PC EXPRESS
    {"category": "Laptop", "source_name": "PC Express Laptops", "url": "https://pcx.com.ph/collections/laptops", "pages": 8},
    {"category": "Laptop", "source_name": "PC Express All Laptop Tagged", "url": "https://pcx.com.ph/collections/all-products/laptop", "pages": 8},

    # EASYPC
    {"category": "Laptop", "source_name": "EasyPC Laptops", "url": "https://easypc.com.ph/collections/laptops", "pages": 5},

    # LAPTOP FACTORY
    {"category": "Laptop", "source_name": "Laptop Factory Home", "url": "https://laptopfactory.com.ph/", "pages": 1},
    {"category": "Laptop", "source_name": "Laptop Factory Gaming Laptops", "url": "https://laptopfactory.com.ph/product-category/gaming-laptops/", "pages": 5},
    {"category": "Laptop", "source_name": "Laptop Factory Premium Laptops", "url": "https://laptopfactory.com.ph/product-category/premium-laptops/", "pages": 5},
    {"category": "Laptop", "source_name": "Laptop Factory Mainstream Laptops", "url": "https://laptopfactory.com.ph/product-category/mainstream-laptops/", "pages": 5},
    {"category": "Laptop", "source_name": "Laptop Factory Acer", "url": "https://laptopfactory.com.ph/product-category/acer/", "pages": 5},
    {"category": "Laptop", "source_name": "Laptop Factory HP", "url": "https://laptopfactory.com.ph/product-category/hp/", "pages": 5},
    {"category": "Laptop", "source_name": "Laptop Factory Lenovo", "url": "https://laptopfactory.com.ph/product-category/lenovo/", "pages": 5},

    # GIGAHERTZ
    {"category": "Laptop", "source_name": "GigaHertz All Laptops", "url": "https://www.gigahertz.com.ph/collections/all-laptops", "pages": 8},

    # ABENSON
    {"category": "Smartphone", "source_name": "Abenson Smartphones", "url": "https://www.abenson.com/mobile/smartphone.html", "pages": 5},
    {"category": "Tablet", "source_name": "Abenson Mobile", "url": "https://www.abenson.com/mobile.html", "pages": 3},
    {"category": "Laptop", "source_name": "Abenson Laptops PC", "url": "https://www.abenson.com/computers-gadget/laptops-pc.html", "pages": 5},

    # ANSONS
    {"category": "Smartphone", "source_name": "Ansons Smartphones", "url": "https://ansons.ph/product-category/smartphones/", "pages": 5},
    {"category": "Laptop", "source_name": "Ansons Laptops", "url": "https://ansons.ph/product-category/laptops/", "pages": 5},

    # SAVE N EARN
    {"category": "Smartphone", "source_name": "Save N Earn Smartphones", "url": "https://savenearn.com.ph/collections/smartphone", "pages": 10},
    {"category": "Smartphone", "source_name": "Save N Earn Mobile Phones", "url": "https://savenearn.com.ph/collections/mobile-phones-smartphone-device", "pages": 10},
    {"category": "Tablet", "source_name": "Save N Earn Tablets", "url": "https://savenearn.com.ph/collections/tablets", "pages": 5},

    # YUGATECH
    {"category": "Smartphone", "source_name": "YugaTech Smartphone Price List", "url": "https://www.yugatech.com/smartphone-price-list-philippines-2025/", "pages": 1},

    # VILLMAN
    {"category": "Laptop", "source_name": "VillMan Shop New Models", "url": "https://shop.villman.com/collections/new-models", "pages": 8},
    {"category": "Laptop", "source_name": "VillMan Notebook PCs", "url": "https://villman.com/Category/Notebook-PCs", "pages": 5},
    {"category": "Laptop", "source_name": "VillMan Notebook PCs Page100", "url": "https://villman.com/Category/Notebook-PCs/100", "pages": 3},

    # OCTAGON
    {"category": "Laptop", "source_name": "Octagon Home Laptops", "url": "https://www.octagon.com.ph/", "pages": 1},

    # DYNAQUEST
    # If this page changes or blocks scraping, the scraper will simply skip it.
    {"category": "Laptop", "source_name": "DynaQuest Laptops", "url": "https://dynaquestpc.com/collections/laptops", "pages": 5},
]

OUTPUT_COLUMNS = [
    "category",
    "brand",
    "model",
    "price",
    "image_url",
    "image_file",
    "source_name",
    "source_url",
    "detail_url",
    "ram",
    "storage",
    "processor",
    "display",
    "gpu",
    "battery",
    "camera",
    "os"
]


# =====================================================
# BASIC HELPERS
# =====================================================

def get_base_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def allowed_by_robots(url):
    try:
        base = get_base_url(url)

        if base in ROBOTS_CACHE:
            rp = ROBOTS_CACHE[base]
        else:
            rp = RobotFileParser()
            rp.set_url(urljoin(base, "/robots.txt"))
            rp.read()
            ROBOTS_CACHE[base] = rp

        return rp.can_fetch(HEADERS["User-Agent"], url)

    except Exception:
        return True


def request_soup(url):
    if not allowed_by_robots(url):
        safe_print(f"Skipped by robots.txt: {url}")
        return None

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.encoding = response.apparent_encoding
    except requests.exceptions.RequestException as e:
        safe_print(f"Request error: {e}")
        return None

    if response.status_code != 200:
        safe_print(f"Skipped status {response.status_code}: {url}")
        return None

    return BeautifulSoup(response.text, "html.parser")


def build_page_url(base_url, page_number):
    if page_number == 1:
        return base_url

    base_url = base_url.rstrip("/")

    # WordPress / WooCommerce style
    if any(domain in base_url for domain in [
        "pinoytechnoguide.com",
        "siliconvalley.com.ph",
        "laptopfactory.com.ph",
        "ansons.ph",
        "abenson.com",
        "octagon.com.ph"
    ]):
        return base_url + f"/page/{page_number}/"

    # Shopify style
    if any(domain in base_url for domain in [
        "kimstore.com",
        "pcx.com.ph",
        "gigahertz.com.ph",
        "savenearn.com.ph",
        "shop.villman.com",
        "easypc.com.ph",
        "dynaquestpc.com"
    ]):
        if "?" in base_url:
            return base_url + f"&page={page_number}"
        return base_url + f"?page={page_number}"

    # Old VillMan style
    if "villman.com/Category" in base_url:
        return base_url + f"/{page_number * 100}"

    # Benstore style
    if "benstore.com.ph" in base_url:
        return base_url + f"?page={page_number}"

    return base_url


def clean_spaces(text):
    if text is None:
        return ""

    text = str(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# =====================================================
# PRICE FUNCTIONS
# =====================================================

def extract_prices(text):
    if not text:
        return []

    text = str(text)

    patterns = [
        r"₱\s*[\d,]+(?:\.\d+)?",
        r"PHP\s*[\d,]+(?:\.\d+)?",
        r"Php\s*[\d,]+(?:\.\d+)?",
        r"\bP\s*[\d]{1,3}(?:,\d{3})+(?:\.\d+)?"
    ]

    prices = []

    for pattern in patterns:
        prices.extend(re.findall(pattern, text))

    return prices


def price_text_to_numbers(text):
    prices = extract_prices(text)
    numbers = []

    for price in prices:
        match = re.search(r"[\d,]+(?:\.\d+)?", price)

        if match:
            value = float(match.group(0).replace(",", ""))

            if value.is_integer():
                value = int(value)

            numbers.append(value)

    return numbers


def extract_price_value(text, category):
    numbers = price_text_to_numbers(text)

    if not numbers:
        return None

    valid_numbers = []

    for value in numbers:
        if category == "Smartphone" and 1000 <= value <= 250000:
            valid_numbers.append(value)

        elif category == "Tablet" and 1000 <= value <= 250000:
            valid_numbers.append(value)

        elif category == "Laptop" and 5000 <= value <= 700000:
            valid_numbers.append(value)

    if not valid_numbers:
        return None

    # Lowest valid price is usually the sale/current price.
    return min(valid_numbers)


def price_is_valid(category, price):
    if price is None:
        return False

    try:
        price = float(price)
    except Exception:
        return False

    if category == "Smartphone":
        return 1000 <= price <= 250000

    if category == "Tablet":
        return 1000 <= price <= 250000

    if category == "Laptop":
        return 5000 <= price <= 700000

    return price >= 1000


def remove_price(text):
    text = re.sub(r"₱\s*[\d,]+(?:\.\d+)?", "", str(text))
    text = re.sub(r"PHP\s*[\d,]+(?:\.\d+)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bP\s*[\d]{1,3}(?:,\d{3})+(?:\.\d+)?", "", text)
    text = text.replace("Regular price", "")
    text = text.replace("Sale price", "")
    text = text.replace("Current price is:", "")
    text = text.replace("Original price was:", "")
    text = text.replace("Current price", "")
    text = text.replace("Original price", "")
    text = text.replace("Unit price", "")
    text = text.replace("Price", "")
    text = text.replace("From", "")
    return clean_spaces(text)


# =====================================================
# IMAGE SCRAPING
# =====================================================

def is_valid_image_url(url):
    if not url:
        return False

    lower = url.lower()

    if lower.startswith("data:"):
        return False

    bad_words = [
        "logo",
        "icon",
        "avatar",
        "spinner",
        "loading",
        "placeholder",
        "banner",
        "ads",
        "advertisement",
        "sprite"
    ]

    if any(word in lower for word in bad_words):
        return False

    good_ext = [".jpg", ".jpeg", ".png", ".webp"]

    if any(ext in lower for ext in good_ext):
        return True

    # Some Shopify CDN images have no normal extension after query.
    if "cdn.shopify.com" in lower or "cdn" in lower:
        return True

    return False


def get_best_srcset_url(srcset):
    if not srcset:
        return ""

    parts = srcset.split(",")
    candidates = []

    for part in parts:
        item = part.strip().split(" ")

        if item:
            candidates.append(item[0])

    if candidates:
        return candidates[-1]

    return ""


def extract_image_url_from_card(card, page_url):
    img = card.find("img")

    if not img:
        return ""

    possible_sources = [
        img.get("data-src"),
        img.get("data-lazy-src"),
        img.get("data-original"),
        img.get("data-srcset"),
        get_best_srcset_url(img.get("srcset")),
        img.get("src")
    ]

    for src in possible_sources:
        if not src:
            continue

        if "," in src:
            src = get_best_srcset_url(src)

        img_url = urljoin(page_url, src)

        if is_valid_image_url(img_url):
            return img_url

    return ""


def safe_filename(text):
    text = clean_spaces(text)
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    text = text.strip("_")
    return text[:80] if text else "image"


def download_image(image_url, category, brand, model):
    if not DOWNLOAD_IMAGES:
        return ""

    if not image_url:
        return ""

    try:
        os.makedirs(IMAGE_FOLDER, exist_ok=True)

        clean_url = image_url.split("?")[0]
        parsed = urlparse(clean_url)
        ext = os.path.splitext(parsed.path)[1].lower()

        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"

        unique_hash = hashlib.md5(image_url.encode("utf-8")).hexdigest()[:10]

        filename = f"{safe_filename(category)}_{safe_filename(brand)}_{safe_filename(model)}_{unique_hash}{ext}"
        filepath = os.path.join(IMAGE_FOLDER, filename)

        if os.path.exists(filepath):
            return filepath

        response = requests.get(image_url, headers=HEADERS, timeout=20, stream=True)

        if response.status_code != 200:
            return ""

        content_type = response.headers.get("Content-Type", "").lower()

        if "image" not in content_type:
            return ""

        max_bytes = MAX_IMAGE_SIZE_MB * 1024 * 1024
        downloaded = 0

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    downloaded += len(chunk)

                    if downloaded > max_bytes:
                        f.close()
                        os.remove(filepath)
                        return ""

                    f.write(chunk)

        return filepath

    except Exception:
        return ""


# =====================================================
# MODEL CLEANING AND VALIDATION
# =====================================================

def clean_model_name(model):
    model = clean_spaces(model)
    model = remove_price(model)

    remove_phrases = [
        "– Full Specs and Official Price in the Philippines",
        "- Full Specs and Official Price in the Philippines",
        "– Full Specs and Price in the Philippines",
        "- Full Specs and Price in the Philippines",
        "– Full Specs and Official in the Philippines",
        "- Full Specs and Official in the Philippines",
        "Full Specs and Official Price in the Philippines",
        "Full Specs and Price in the Philippines",
        "Full Specs",
        "Official Price in the Philippines",
        "Price in the Philippines",
        "Philippines",
        "Add to cart",
        "Add To Cart",
        "Quick view",
        "Quick View",
        "Choose options",
        "Choose your option",
        "Select options",
        "Select Options",
        "Read more",
        "Read More",
        "Compare",
        "Wishlist",
        "Image:",
        "Image",
        "No reviews",
        "View details",
        "View Details",
        "Sold out",
        "Only 1 left",
        "Only 2 left",
        "In stock",
        "Sale!",
        "Sale",
        "Save",
        "Regular price",
        "Sale price",
        "Unit price",
        "/per"
    ]

    for phrase in remove_phrases:
        model = model.replace(phrase, "")

    model = re.sub(r"\b\d+%\s*off\b", "", model, flags=re.IGNORECASE)
    model = re.sub(r"\s+[|–-]\s*$", "", model)
    model = re.sub(r"\s+", " ", model)
    model = model.strip(" -|•*~/")

    return model


def is_bad_model(model):
    if not model:
        return True

    text = clean_spaces(model)
    lower = text.lower()

    bad_exact = [
        "",
        "-",
        "home",
        "search",
        "menu",
        "login",
        "register",
        "cart",
        "wishlist",
        "compare",
        "quick view",
        "choose options",
        "choose your option",
        "add to cart",
        "add to wishlist",
        "add to compare",
        "read more",
        "select options",
        "default sorting",
        "show sidebar",
        "filter",
        "sort by",
        "price",
        "regular price",
        "sale price",
        "image",
        "official price",
        "latest phones and news",
        "latest mobile phones and news",
        "latest smartphones",
        "latest tablets",
        "laptops",
        "tablets",
        "smartphones",
        "all products",
        "products",
        "featured",
        "featured products"
    ]

    bad_contains = [
        "showing ",
        "filter by",
        "sort by",
        "stock status",
        "top rated products",
        "free shipping",
        "your cart",
        "days",
        "hours",
        "mins",
        "secs",
        "pinoy techno guide",
        "latest apple phones and news",
        "latest honor phones and news",
        "latest infinix mobile phones and news",
        "latest samsung phones and news",
        "latest oppo phones and news",
        "latest realme phones and news",
        "latest vivo phones and news",
        "all brands",
        "all networks",
        "advertisement",
        "related products",
        "customer service",
        "privacy policy",
        "terms and conditions",
        "copyright",
        "subscribe",
        "newsletter",
        "tech news",
        "buying guide",
        "how to",
        "have questions",
        "customer satisfaction",
        "track order",
        "delivery service",
        "pickup locations",
        "apply (",
        "availability",
        "product type",
        "sort by:",
        "from ₱",
        "to ₱"
    ]

    if lower in bad_exact:
        return True

    for bad in bad_contains:
        if bad in lower:
            return True

    if text.startswith("₱"):
        return True

    if len(text) < 3:
        return True

    return False


def is_valid_detail_url(url, category):
    if not url:
        return False

    lower = url.lower()

    bad_paths = [
        "/tech-news",
        "/news",
        "/guides",
        "/how-to",
        "/about",
        "/contact",
        "/privacy",
        "/terms",
        "/tag/",
        "/author/",
        "/search",
        "/advertise",
        "/apps",
        "/telco",
        "/promos",
        "/downloads",
        "/wp-content",
        "/feed",
        "/cart",
        "/wishlist",
        "/compare",
        "/account",
        "/login",
        "#"
    ]

    for bad in bad_paths:
        if bad in lower:
            return False

    if lower.endswith(".jpg") or lower.endswith(".png") or lower.endswith(".webp"):
        return False

    # E-commerce product URLs
    if "/products/" in lower or "/product/" in lower:
        return True

    if category == "Smartphone":
        words = [
            "realme", "vivo", "oppo", "samsung", "galaxy", "xiaomi", "redmi",
            "poco", "infinix", "tecno", "honor", "huawei", "iphone", "apple",
            "nokia", "oneplus", "nothing", "nubia", "itel", "smartphone",
            "phone", "pixel", "motorola", "moto"
        ]
        return any(w in lower for w in words)

    if category == "Tablet":
        words = [
            "tablet", "ipad", "pad", "tab", "matepad", "xpad", "megapad"
        ]
        return any(w in lower for w in words)

    if category == "Laptop":
        words = [
            "laptop", "notebook", "macbook", "aspire", "vivobook", "ideapad",
            "thinkpad", "legion", "rog", "tuf", "predator", "nitro", "swift",
            "zenbook", "yoga", "pavilion", "probook", "elitebook", "xps",
            "inspiron", "latitude", "razer", "surface", "chromebook", "loq",
            "aorus", "msi", "modern", "prestige", "stealth", "katana",
            "cyborg", "asus", "acer", "lenovo", "dell", "hp-", "victus",
            "omen", "expertbook", "zenbook", "matebook", "megabook"
        ]
        return any(w in lower for w in words)

    return True


def category_allowed(category, text):
    lower = text.lower()

    if category == "Smartphone":
        blocked = [
            "laptop", "macbook", "mouse", "keyboard", "monitor",
            "charger", "power bank", "case", "screen protector",
            "film", "tempered", "cable", "adapter", "earbuds",
            "headset", "printer", "gaming console", "smart tv"
        ]

        if any(word in lower for word in blocked):
            return False

        words = [
            "iphone", "samsung", "galaxy", "xiaomi", "redmi", "poco",
            "realme", "vivo", "oppo", "huawei", "honor", "infinix",
            "tecno", "itel", "nokia", "oneplus", "pixel", "nubia",
            "motorola", "moto", "nothing", "smartphone", "phone"
        ]

        return any(word in lower for word in words)

    if category == "Tablet":
        blocked = [
            "keyboard", "mouse", "case", "screen protector", "film",
            "tempered", "charger", "power bank", "pen only", "stylus only",
            "laptop"
        ]

        if any(word in lower for word in blocked):
            return False

        words = [
            "pad", "tab", "tablet", "matepad", "ipad", "xpad", "megapad"
        ]

        return any(word in lower for word in words)

    if category == "Laptop":
        blocked = [
            "gaming console", "rog ally", "msi claw", "steam deck",
            "mouse", "keyboard", "monitor", "bag", "backpack",
            "printer", "ink", "toner", "router", "desktop package",
            "mini desktop", "mini pc", "gaming desktop", "desktop pc",
            "smart tank", "tablet", "ipad", "smartphone", "phone"
        ]

        if any(word in lower for word in blocked):
            return False

        words = [
            "laptop", "notebook", "macbook", "aspire", "vivobook", "ideapad",
            "thinkpad", "legion", "rog", "tuf", "predator", "nitro", "swift",
            "zenbook", "yoga", "pavilion", "probook", "elitebook", "xps",
            "inspiron", "latitude", "razer blade", "surface laptop",
            "chromebook", "loq", "aorus", "msi", "modern", "prestige",
            "stealth", "katana", "cyborg", "asus", "acer", "lenovo",
            "dell", "hp ", "hp-", "victus", "omen", "expertbook",
            "matebook", "megabook", "envy", "spectre"
        ]

        return any(word in lower for word in words)

    return True


# =====================================================
# SPEC EXTRACTION
# =====================================================

def extract_first_match(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return clean_spaces(match.group(0))

    return ""


def extract_all_matches(text, patterns, limit=5):
    found = []

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)

        for item in matches:
            if isinstance(item, tuple):
                item = " ".join([x for x in item if x])

            item = clean_spaces(item)

            if item and item not in found:
                found.append(item)

    return " | ".join(found[:limit])


def extract_ram(text):
    patterns = [
        r"\b\d+\s*GB\s*(?:RAM|DDR3|DDR4|DDR5|LPDDR4|LPDDR4X|LPDDR5|LPDDR5X)?\b",
        r"\b\d+\s*\+\s*\d+\s*GB\s*(?:RAM)?\b",
        r"\b\d+GB\s*RAM\b"
    ]

    return extract_first_match(text, patterns)


def extract_storage(text):
    patterns = [
        r"\b\d+\s*TB\s*(?:SSD|NVMe|HDD|Storage)?\b",
        r"\b\d+\s*GB\s*(?:SSD|NVMe|HDD|ROM|Storage)\b",
        r"\b(?:32|64|128|256|512)\s*GB\b",
        r"\b1\s*TB\b",
        r"\b2\s*TB\b"
    ]

    return extract_first_match(text, patterns)


def extract_processor(text):
    patterns = [
        r"Intel Core Ultra\s*\d+[^\]\|\[]*",
        r"Intel Core\s*i\d+[^\]\|\[]*",
        r"Core Ultra\s*\d+[^\]\|\[]*",
        r"Core\s*i\d+[^\]\|\[]*",
        r"Intel Core\s*\d+[^\]\|\[]*",
        r"AMD Ryzen\s*\d+[^\]\|\[]*",
        r"Ryzen AI\s*\d+[^\]\|\[]*",
        r"Ryzen\s*\d+[^\]\|\[]*",
        r"Snapdragon X Elite[^\]\|\[]*",
        r"Snapdragon X Plus[^\]\|\[]*",
        r"Snapdragon\s*[^\]\|\[]*",
        r"Apple M\d[^\]\|\[]*",
        r"MediaTek\s*[^\]\|\[]*",
        r"Dimensity\s*[^\]\|\[]*",
        r"Helio\s*[^\]\|\[]*",
        r"Unisoc\s*[^\]\|\[]*",
        r"Exynos\s*[^\]\|\[]*",
        r"Kirin\s*[^\]\|\[]*",
        r"Celeron[^\]\|\[]*",
        r"Pentium[^\]\|\[]*"
    ]

    return extract_first_match(text, patterns)


def extract_gpu(text):
    patterns = [
        r"NVIDIA\s*GeForce\s*RTX\s*\d+[^\]\|\[]*",
        r"NVIDIA\s*RTX\s*\d+[^\]\|\[]*",
        r"NVIDIA\s*GTX\s*\d+[^\]\|\[]*",
        r"GeForce\s*RTX\s*\d+[^\]\|\[]*",
        r"RTX\s*\d+[^\]\|\[]*",
        r"GTX\s*\d+[^\]\|\[]*",
        r"Intel Arc[^\]\|\[]*",
        r"Intel Iris Xe[^\]\|\[]*",
        r"AMD Radeon[^\]\|\[]*",
        r"Radeon[^\]\|\[]*",
        r"Adreno[^\]\|\[]*",
        r"Mali-G\d+[^\]\|\[]*",
        r"UHD Graphics[^\]\|\[]*"
    ]

    return extract_first_match(text, patterns)


def extract_battery(text):
    patterns = [
        r"\b\d{3,5}\s*mAh\b",
        r"\b\d{2,3}\s*Wh\b"
    ]

    return extract_first_match(text, patterns)


def extract_camera(text):
    patterns = [
        r"\b\d+\s*MP\b",
        r"\b\d+\s*Megapixel\b"
    ]

    return extract_all_matches(text, patterns, limit=4)


def extract_display(text):
    patterns = [
        r"\b\d{1,2}(?:\.\d)?\s*(?:inch|inches|in|”|\")\b",
        r"\b\d{1,2}(?:\.\d)?-inch\b",
        r"\b\d{1,2}(?:\.\d)?in\b",
        r"\bAMOLED\b",
        r"\bOLED\b",
        r"\bIPS\b",
        r"\bLCD\b",
        r"\bFHD\+?\b",
        r"\bQHD\+?\b",
        r"\bWUXGA\b",
        r"\bWQXGA\b",
        r"\b\d+Hz\b"
    ]

    return extract_all_matches(text, patterns, limit=6)


def extract_os(text):
    patterns = [
        r"Windows\s*11\s*(?:Home|Pro)?",
        r"Windows\s*10\s*(?:Home|Pro)?",
        r"Win\s*11",
        r"Win\s*10",
        r"macOS\s*[A-Za-z0-9 ]*",
        r"Android\s*\d+(?:\.\d+)?",
        r"iOS\s*\d+(?:\.\d+)?",
        r"iPadOS\s*\d+(?:\.\d+)?",
        r"ChromeOS",
        r"DOS",
        r"Linux"
    ]

    return extract_first_match(text, patterns)


def guess_brand(model):
    lower = model.lower()

    brand_map = {
        "iphone": "Apple",
        "ipad": "Apple",
        "macbook": "Apple",
        "apple": "Apple",
        "samsung": "Samsung",
        "galaxy": "Samsung",
        "xiaomi": "Xiaomi",
        "redmi": "Xiaomi",
        "poco": "POCO",
        "realme": "Realme",
        "vivo": "Vivo",
        "oppo": "OPPO",
        "huawei": "Huawei",
        "honor": "HONOR",
        "infinix": "Infinix",
        "tecno": "TECNO",
        "itel": "itel",
        "nokia": "Nokia",
        "oneplus": "OnePlus",
        "lenovo": "Lenovo",
        "acer": "Acer",
        "asus": "ASUS",
        "hp ": "HP",
        "hp-": "HP",
        "dell": "Dell",
        "msi": "MSI",
        "razer": "Razer",
        "microsoft": "Microsoft",
        "surface": "Microsoft",
        "gigabyte": "Gigabyte",
        "aorus": "Gigabyte",
        "alienware": "Alienware",
        "cherry": "Cherry Mobile",
        "myphone": "MyPhone",
        "techlife": "TechLife",
        "nubia": "nubia",
        "nothing": "Nothing",
        "motorola": "Motorola",
        "moto": "Motorola",
        "pixel": "Google",
        "google": "Google",
        "tecno": "TECNO",
        "alldocube": "Alldocube",
        "bmax": "BMAX"
    }

    for key, brand in brand_map.items():
        if key in lower:
            return brand

    parts = model.split()
    return parts[0] if parts else "Unknown"


# =====================================================
# SCRAPING METHOD 1: LIST PAGE ONLY
# =====================================================

def find_link_inside_card(card, page_url, category):
    base = get_base_url(page_url)

    # Prefer product links
    for a in card.find_all("a", href=True):
        href = urljoin(page_url, a["href"])

        if not href.startswith(base):
            continue

        lower = href.lower()

        if "/products/" in lower or "/product/" in lower:
            return href

    # Fallback to valid detail link
    for a in card.find_all("a", href=True):
        href = urljoin(page_url, a["href"])

        if not href.startswith(base):
            continue

        if is_valid_detail_url(href, category):
            return href

    return page_url


def make_record(category, source_name, model, price, image_url, image_file, source_url, detail_url, text_for_specs):
    brand = guess_brand(model)

    return {
        "category": category,
        "brand": brand,
        "model": model,
        "price": price,
        "image_url": image_url,
        "image_file": image_file,
        "source_name": source_name,
        "source_url": source_url,
        "detail_url": detail_url,
        "ram": extract_ram(text_for_specs),
        "storage": extract_storage(text_for_specs),
        "processor": extract_processor(text_for_specs),
        "display": extract_display(text_for_specs),
        "gpu": extract_gpu(text_for_specs),
        "battery": extract_battery(text_for_specs),
        "camera": extract_camera(text_for_specs),
        "os": extract_os(text_for_specs)
    }


def get_title_from_card(card):
    title_selectors = [
        "h1",
        "h2",
        "h3",
        "h4",
        ".product-title",
        ".product__title",
        ".card__heading",
        ".product-card__title",
        ".woocommerce-loop-product__title",
        ".product-name",
        ".product-item-name",
        ".name",
        "a"
    ]

    for selector in title_selectors:
        tag = card.select_one(selector)

        if tag:
            title = clean_spaces(tag.get_text(" "))

            if not is_bad_model(title):
                return title

    return ""


def extract_records_from_cards(soup, page_url, category, source_name):
    records = []

    selectors = [
        "li.product",
        ".product",
        ".product-item",
        ".product-card",
        ".product-card-wrapper",
        ".product-grid-item",
        ".grid__item",
        ".card-wrapper",
        ".collection-product-card",
        ".item",
        ".card",
        ".post",
        ".entry",
        "article",
        "tr"
    ]

    seen_card_text = set()

    for selector in selectors:
        for card in soup.select(selector):
            card_text = clean_spaces(card.get_text(" "))

            if not card_text or card_text in seen_card_text:
                continue

            seen_card_text.add(card_text)

            price = extract_price_value(card_text, category)

            if not price_is_valid(category, price):
                continue

            title = get_title_from_card(card)

            if is_bad_model(title):
                title = remove_price(card_text)

            model = clean_model_name(title)

            if is_bad_model(model):
                continue

            combined_text = model + " " + card_text

            if not category_allowed(category, combined_text):
                continue

            detail_url = find_link_inside_card(card, page_url, category)

            image_url = extract_image_url_from_card(card, page_url)
            brand = guess_brand(model)
            image_file = download_image(image_url, category, brand, model)

            records.append(make_record(
                category=category,
                source_name=source_name,
                model=model,
                price=price,
                image_url=image_url,
                image_file=image_file,
                source_url=page_url,
                detail_url=detail_url,
                text_for_specs=combined_text
            ))

    return records


def extract_records_from_lines(soup, page_url, category, source_name):
    records = []

    lines = [
        clean_spaces(line)
        for line in soup.get_text("\n").split("\n")
        if clean_spaces(line)
    ]

    for i, line in enumerate(lines):
        price = extract_price_value(line, category)

        if not price_is_valid(category, price):
            continue

        possible_model = ""

        # Usually model is above the price.
        for back in range(1, 10):
            if i - back < 0:
                break

            candidate = clean_model_name(lines[i - back])

            if not is_bad_model(candidate):
                possible_model = candidate
                break

        if is_bad_model(possible_model):
            possible_model = clean_model_name(remove_price(line))

        if is_bad_model(possible_model):
            continue

        combined_text = possible_model + " " + line

        if not category_allowed(category, combined_text):
            continue

        records.append(make_record(
            category=category,
            source_name=source_name,
            model=possible_model,
            price=price,
            image_url="",
            image_file="",
            source_url=page_url,
            detail_url=page_url,
            text_for_specs=combined_text
        ))

    return records


def scrape_list_page(page_url, category, source_name):
    soup = request_soup(page_url)

    if soup is None:
        return []

    card_records = extract_records_from_cards(soup, page_url, category, source_name)
    line_records = extract_records_from_lines(soup, page_url, category, source_name)

    return card_records + line_records


# =====================================================
# FINAL CLEANING
# =====================================================

def clean_dataframe(raw_df):
    removed_rows = []

    if raw_df.empty:
        return raw_df, pd.DataFrame(), 0

    df = raw_df.copy()

    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[OUTPUT_COLUMNS]

    for col in OUTPUT_COLUMNS:
        if col != "price":
            df[col] = df[col].astype(str).map(clean_spaces)

    df["model"] = df["model"].map(clean_model_name)
    df["brand"] = df["model"].map(guess_brand)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    valid_indexes = []

    for idx, row in df.iterrows():
        reason = ""

        category = row["category"]
        model = row["model"]
        price = row["price"]

        combined_text = " ".join([
            str(row.get("category", "")),
            str(row.get("brand", "")),
            str(row.get("model", "")),
            str(row.get("source_name", "")),
            str(row.get("ram", "")),
            str(row.get("storage", "")),
            str(row.get("processor", "")),
            str(row.get("gpu", "")),
            str(row.get("display", "")),
        ])

        if is_bad_model(model):
            reason = "bad_model"

        elif not category_allowed(category, combined_text):
            reason = "wrong_category"

        elif not price_is_valid(category, price):
            reason = "invalid_price"

        elif "latest" in model.lower() and "news" in model.lower():
            reason = "non_product_page"

        if reason:
            bad_row = row.to_dict()
            bad_row["remove_reason"] = reason
            removed_rows.append(bad_row)
        else:
            valid_indexes.append(idx)

    clean_df = df.loc[valid_indexes].copy()

    before_dedup = len(clean_df)

    clean_df = clean_df.drop_duplicates(
        subset=["category", "brand", "model", "price"],
        keep="first"
    )

    after_dedup = len(clean_df)
    duplicate_removed = before_dedup - after_dedup

    clean_df = clean_df.sort_values(
        by=["category", "brand", "price"],
        ascending=[True, True, True]
    )

    removed_df = pd.DataFrame(removed_rows)

    return clean_df, removed_df, duplicate_removed


def save_outputs(clean_df, removed_df, duplicate_removed, raw_count):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Main file used by app.py
    app_csv = os.path.join(BASE_DIR, "gadgets.csv")

    # Backup/output files for checking n8n runs
    clean_csv = os.path.join(OUTPUT_DIR, f"find_my_gadget_CLEAN_WITH_IMAGES_{timestamp}.csv")
    latest_csv = os.path.join(OUTPUT_DIR, "find_my_gadget_latest.csv")
    latest_json = os.path.join(OUTPUT_DIR, "find_my_gadget_latest.json")
    removed_csv = os.path.join(OUTPUT_DIR, f"removed_invalid_rows_{timestamp}.csv")
    report_txt = os.path.join(OUTPUT_DIR, f"cleaning_report_{timestamp}.txt")
    latest_report = os.path.join(OUTPUT_DIR, "cleaning_report_latest.txt")

    # Make app.py-friendly columns if missing
    for col in [
        "id", "usage", "price_text", "category", "brand", "model", "price",
        "image_url", "image_file", "source_name", "source_url", "detail_url",
        "ram", "storage", "processor", "display", "gpu", "battery", "camera", "os"
    ]:
        if col not in clean_df.columns:
            clean_df[col] = ""

    if not clean_df.empty:
        clean_df["id"] = range(1, len(clean_df) + 1)

    # Save CSV used by the web system
    clean_df.to_csv(app_csv, index=False, encoding="utf-8-sig")

    # Save backups and latest outputs
    clean_df.to_csv(clean_csv, index=False, encoding="utf-8-sig")
    clean_df.to_csv(latest_csv, index=False, encoding="utf-8-sig")
    clean_df.to_json(latest_json, orient="records", indent=4, force_ascii=False)

    if removed_df is not None and not removed_df.empty:
        removed_df.to_csv(removed_csv, index=False, encoding="utf-8-sig")

    report_content = ""
    report_content += "FIND MY GADGET DATA CLEANING REPORT\n"
    report_content += "==================================\n\n"
    report_content += f"Run time: {datetime.now()}\n"
    report_content += f"Original raw rows: {raw_count}\n"
    report_content += f"Clean rows: {len(clean_df)}\n"
    report_content += f"Invalid rows removed: {len(removed_df) if removed_df is not None else 0}\n"
    report_content += f"Duplicate rows removed: {duplicate_removed}\n\n"

    report_content += "Count by category:\n"
    if not clean_df.empty:
        report_content += clean_df["category"].value_counts().to_string()
    else:
        report_content += "No clean data."

    report_content += "\n\nCount by source:\n"
    if not clean_df.empty and "source_name" in clean_df.columns:
        report_content += clean_df["source_name"].value_counts().to_string()
    else:
        report_content += "No source data."

    report_content += "\n\nOutput columns:\n"
    report_content += ", ".join(list(clean_df.columns))

    with open(report_txt, "w", encoding="utf-8") as f:
        f.write(report_content)

    with open(latest_report, "w", encoding="utf-8") as f:
        f.write(report_content)

    safe_print("\nFILES SAVED SUCCESSFULLY!")
    safe_print(f"App CSV updated: {app_csv}")
    safe_print(f"Latest CSV: {latest_csv}")
    safe_print(f"Latest JSON: {latest_json}")
    safe_print(f"Cleaning report: {latest_report}")

    if removed_df is not None and not removed_df.empty:
        safe_print(f"Removed rows CSV: {removed_csv}")

    if DOWNLOAD_IMAGES:
        safe_print(f"Images folder: {IMAGE_FOLDER}")


# =====================================================
# MAIN
# =====================================================

def main():
    safe_print("==================================================")
    safe_print("FIND MY GADGET SCRAPER")
    safe_print("First Method + More PH Sources + Image Scraping")
    safe_print("CSV only | price column | public pages only")
    safe_print("==================================================")

    all_records = []

    for source in SOURCES:
        category = source["category"]
        source_name = source["source_name"]
        base_url = source["url"]
        pages = source["pages"]

        safe_print(f"\nSOURCE: {source_name}")
        safe_print(f"Category: {category}")

        source_count = 0

        for page_number in range(1, pages + 1):
            page_url = build_page_url(base_url, page_number)

            safe_print(f"Scraping page {page_number}: {page_url}")

            records = scrape_list_page(page_url, category, source_name)

            safe_print(f"Raw records found: {len(records)}")

            for record in records:
                if MAX_RECORDS_PER_SOURCE > 0 and source_count >= MAX_RECORDS_PER_SOURCE:
                    break

                all_records.append(record)
                source_count += 1

            time.sleep(DELAY_SECONDS)

        safe_print(f"Total accepted raw records from {source_name}: {source_count}")

    raw_df = pd.DataFrame(all_records, columns=OUTPUT_COLUMNS)

    if raw_df.empty:
        safe_print("\nNo raw data scraped.")
        empty_df = pd.DataFrame(columns=OUTPUT_COLUMNS)
        save_outputs(empty_df, pd.DataFrame(), 0, 0)
        return

    clean_df, removed_df, duplicate_removed = clean_dataframe(raw_df)

    save_outputs(
        clean_df=clean_df,
        removed_df=removed_df,
        duplicate_removed=duplicate_removed,
        raw_count=len(raw_df)
    )

    safe_print("\nDONE!")
    safe_print(f"Raw rows scraped: {len(raw_df)}")
    safe_print(f"Clean rows: {len(clean_df)}")

    if not clean_df.empty:
        safe_print("\nCount by category:")
        safe_print(clean_df["category"].value_counts().to_string())

        safe_print("\nCount by source:")
        safe_print(clean_df["source_name"].value_counts().head(30).to_string())

        safe_print("\nSample clean data:")
        safe_print(clean_df.head(20).to_string(index=False))

    safe_print("\nNEXT STEP:")
    safe_print("n8n/app.py ready: gadgets.csv has been updated automatically.")


if __name__ == "__main__":
    main()