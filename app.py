import os
import re
import math
import time
import json
import shutil
import subprocess
import threading
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

import pandas as pd
from flask import Flask, request, render_template_string, send_from_directory, url_for, jsonify

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "gadgets.csv")
IMAGE_FOLDER = os.path.join(APP_DIR, "gadget_images")

BASE_DIR = Path(APP_DIR)
SCRAPER_PATH = BASE_DIR / "scrape_gadgets.py"
LOG_DIR = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "outputs"
LOCK_FILE = BASE_DIR / "scraper.lock"
STATUS_FILE = BASE_DIR / "scraper_status.json"

LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)

USAGES = [
    "All",
    "Student / School",
    "Office / Business",
    "Gaming",
    "Content Creation"
]


# =====================================================
# BASIC HELPERS
# =====================================================

def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, float) and math.isnan(value):
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none", "null", "n/a"]:
        return ""

    return re.sub(r"\s+", " ", text)


def money(value):
    try:
        if value is None or pd.isna(value):
            return "No price"

        return "₱{:,.0f}".format(float(value))

    except Exception:
        return "No price"


def parse_budget_input(value):
    text = clean_text(value).lower()
    text = text.replace("₱", "").replace(",", "").replace("php", "").strip()

    if not text:
        return 10000.0

    try:
        if text.endswith("k"):
            number = float(text.replace("k", "").strip())
            return number * 1000

        return float(text)

    except Exception:
        return 10000.0


def get_budget_range(budget):
    lower_limit = budget * 0.999
    upper_limit = budget * 1.05

    return lower_limit, upper_limit


def parse_price(value):
    text = clean_text(value)

    if not text:
        return None

    try:
        number = float(
            text.replace(",", "")
                .replace("₱", "")
                .replace("PHP", "")
                .replace("php", "")
                .strip()
        )

        if number > 0:
            return number

    except Exception:
        pass

    matches = re.findall(r"₱\s*([\d,]+(?:\.\d+)?)", text)
    numbers = []

    for match in matches:
        try:
            numbers.append(float(match.replace(",", "")))
        except Exception:
            pass

    if numbers:
        return min(numbers)

    matches = re.findall(r"(?<![A-Za-z])([\d]{1,3}(?:,\d{3})+(?:\.\d+)?)", text)

    for match in matches:
        try:
            numbers.append(float(match.replace(",", "")))
        except Exception:
            pass

    if numbers:
        return min(numbers)

    return None


def normalize_category(value):
    value = clean_text(value).lower()

    if "phone" in value or "smart" in value:
        return "Smartphone"

    if "laptop" in value or "notebook" in value:
        return "Laptop"

    if "tablet" in value or "ipad" in value:
        return "Tablet"

    return value.title() if value else "Gadget"


def ram_gb(*parts):
    text = " ".join(clean_text(x).lower() for x in parts)
    values = []

    for match in re.findall(r"(\d+)\s*gb", text):
        try:
            values.append(int(match))
        except Exception:
            pass

    return max(values) if values else 0


def storage_gb(*parts):
    text = " ".join(clean_text(x).lower() for x in parts)
    values = []

    for match in re.findall(r"(\d+)\s*tb", text):
        try:
            values.append(int(match) * 1024)
        except Exception:
            pass

    for match in re.findall(r"(\d+)\s*gb", text):
        try:
            values.append(int(match))
        except Exception:
            pass

    return max(values) if values else 0


def make_blob(row):
    cols = [
        "category",
        "brand",
        "model",
        "usage",
        "ram",
        "storage",
        "processor",
        "display",
        "gpu",
        "battery",
        "camera",
        "os"
    ]

    return " ".join(clean_text(row.get(col, "")) for col in cols).lower()


def safe_feature(value, fallback="Not specified"):
    value = clean_text(value)

    return value if value else fallback


def make_link(row):
    detail = clean_text(row.get("detail_url", ""))
    source = clean_text(row.get("source_url", ""))

    if detail.startswith("http"):
        return detail

    if source.startswith("http"):
        return source

    brand = clean_text(row.get("brand", ""))
    model = clean_text(row.get("model", ""))
    category = clean_text(row.get("category", ""))
    query = f"{brand} {model} {category} price Philippines".replace(" ", "+")

    return f"https://www.google.com/search?q={query}"


def default_category_image(category):
    """
    Returns a local default image based on the gadget category.
    The files must be stored inside the gadget_images folder:
      - default_phone.jpg
      - default_laptop.jpg
      - default_tablet.jpg
    """
    category = normalize_category(category)

    default_files = {
        "Smartphone": "default_phone.jpg",
        "Laptop": "default_laptop.jpg",
        "Tablet": "default_tablet.jpg",
    }

    filename = default_files.get(category, "default_phone.jpg")
    return url_for("serve_gadget_image", filename=filename)


def get_image(row):
    """
    Image priority:
    1. Real online image_url
    2. Local image_file from gadget_images
    3. Default category image supplied by the user
    """
    image_url = clean_text(row.get("image_url", ""))

    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url

    image_file = clean_text(row.get("image_file", ""))

    if image_file:
        normalized = image_file.replace("\\", "/")

        if "gadget_images/" in normalized:
            filename = normalized.split("gadget_images/", 1)[1]
        else:
            filename = os.path.basename(normalized)

        if filename:
            local_path = os.path.join(IMAGE_FOLDER, filename)

            if os.path.exists(local_path):
                return url_for("serve_gadget_image", filename=filename)

    return default_category_image(row.get("category", "Gadget"))


# =====================================================
# DATASET PRICE GUIDE
# =====================================================

def build_category_guides(df):
    guides = {}

    if df.empty:
        return {
            "All": {
                "label": "All Gadgets",
                "min_price": 500,
                "max_price": 419900,
                "count": 0,
                "instruction": "No dataset loaded."
            }
        }

    valid_df = df.dropna(subset=["price"]).copy()
    valid_df = valid_df[valid_df["price"] > 0]

    def make_guide(label, sub_df):
        display_label = "Phones" if label == "Smartphone" else label

        if sub_df.empty:
            return {
                "label": display_label,
                "min_price": 0,
                "max_price": 0,
                "count": 0,
                "instruction": f"No available {display_label} data in the dataset."
            }

        min_price = float(sub_df["price"].min())
        max_price = float(sub_df["price"].max())
        count = int(len(sub_df))

        return {
            "label": display_label,
            "min_price": min_price,
            "max_price": max_price,
            "count": count,
            "instruction": f"For {display_label}, enter a budget between {money(min_price)} and {money(max_price)} based on the current dataset. Available records: {count}."
        }

    guides["All"] = make_guide("All Gadgets", valid_df)

    for category in sorted(valid_df["category"].dropna().unique().tolist()):
        cat_df = valid_df[valid_df["category"] == category].copy()
        guides[category] = make_guide(category, cat_df)

    return guides


# =====================================================
# USAGE CLASSIFICATION
# =====================================================

def classify_primary_usage(row):
    text = make_blob(row)
    price = row.get("price", 0)
    ram = ram_gb(row.get("ram", ""), row.get("model", ""))
    storage = storage_gb(row.get("storage", ""), row.get("model", ""))

    gaming_keywords = [
        "gaming", "rog", "tuf", "legion", "predator", "nitro",
        "alienware", "omen", "loq", "victus", "katana", "cyborg",
        "poco", "gt ", "gt-", "snapdragon 8", "snapdragon 7",
        "dimensity 8", "dimensity 9", "helio g99", "rtx", "gtx",
        "radeon rx", "120hz", "144hz", "165hz", "180hz", "240hz"
    ]

    creator_keywords = [
        "creator", "proart", "studio", "macbook pro", "oled", "amoled",
        "4k", "3k", "qhd", "uhd", "rtx 4070", "rtx 4080", "rtx 4090",
        "rtx 5070", "rtx 5080", "rtx 5090", "ultra", "pro max",
        "108mp", "200mp", "512gb", "1tb", "2tb"
    ]

    business_keywords = [
        "thinkpad", "latitude", "elitebook", "probook", "zenbook",
        "swift", "vivobook", "surface", "macbook air", "business",
        "office", "xps", "spectre", "core i5", "core i7",
        "ryzen 5", "ryzen 7", "windows 11", "macos"
    ]

    school_keywords = [
        "chromebook", "celeron", "pentium", "ipad", "tab a",
        "student", "education", "aspire", "ideapad", "pavilion",
        "redmi", "realme", "galaxy a", "pad", "tab"
    ]

    if any(k in text for k in gaming_keywords):
        return "Gaming"

    if any(k in text for k in creator_keywords) or ram >= 16 or storage >= 512:
        return "Content Creation"

    if any(k in text for k in business_keywords) or ram >= 8:
        return "Office / Business"

    try:
        if any(k in text for k in school_keywords) or float(price) <= 25000:
            return "Student / School"
    except Exception:
        pass

    return "Student / School"


def keyword_score(text, keywords):
    if not keywords:
        return 0.0

    hits = sum(1 for key in keywords if key in text)

    return min(1.0, hits / 4)


def spec_power_score(row):
    text = make_blob(row)
    ram = ram_gb(row.get("ram", ""), row.get("model", ""))
    storage = storage_gb(row.get("storage", ""), row.get("model", ""))

    score = 0.30

    if ram >= 4:
        score += 0.08

    if ram >= 8:
        score += 0.12

    if ram >= 16:
        score += 0.12

    if storage >= 64:
        score += 0.05

    if storage >= 256:
        score += 0.10

    if storage >= 512:
        score += 0.10

    if any(k in text for k in ["ssd", "ufs", "nvme"]):
        score += 0.08

    if any(k in text for k in ["oled", "amoled", "retina", "qhd", "3k", "4k", "120hz", "144hz", "165hz", "240hz"]):
        score += 0.10

    if any(k in text for k in ["rtx", "gtx", "snapdragon 8", "snapdragon 7", "dimensity 8", "dimensity 9", "ryzen 7", "ryzen 9", "core i7", "core i9", "ultra 7", "ultra 9"]):
        score += 0.15

    return max(0.0, min(1.0, score))


# =====================================================
# USAGE SCORING RULES
# =====================================================

def usage_match_score(row, usage):
    usage = clean_text(usage).lower()

    if usage == "all":
        return 1.0

    text = make_blob(row)
    category = clean_text(row.get("category", "")).lower()
    price = float(row.get("price", 0) or 0)
    ram = ram_gb(row.get("ram", ""), row.get("model", ""))
    storage = storage_gb(row.get("storage", ""), row.get("model", ""))

    if usage == "student / school":
        keywords = [
            "student", "school", "education", "chromebook", "celeron",
            "pentium", "aspire", "vivobook", "ideapad", "pavilion",
            "redmi", "realme", "galaxy a", "ipad", "tab", "pad",
            "helio", "dimensity", "core i3", "ryzen 3"
        ]

        score = 0.35
        score += keyword_score(text, keywords) * 0.30

        if price <= 25000:
            score += 0.20
        elif price <= 45000:
            score += 0.10

        if ram >= 4:
            score += 0.08

        if storage >= 64:
            score += 0.07

        if category in ["laptop", "tablet"]:
            score += 0.05

        return max(0.0, min(1.0, score))

    if usage == "office / business":
        keywords = [
            "office", "business", "thinkpad", "latitude", "elitebook",
            "probook", "zenbook", "swift", "vivobook", "surface",
            "macbook", "xps", "spectre", "core i5", "core i7",
            "ryzen 5", "ryzen 7", "windows", "macos", "ssd"
        ]

        score = 0.35
        score += keyword_score(text, keywords) * 0.35

        if ram >= 8:
            score += 0.15

        if storage >= 256:
            score += 0.10

        if price >= 15000:
            score += 0.05

        return max(0.0, min(1.0, score))

    if usage == "gaming":
        keywords = [
            "gaming", "rog", "tuf", "legion", "predator", "nitro",
            "alienware", "omen", "loq", "victus", "katana", "cyborg",
            "poco", "gt ", "gt-", "snapdragon 8", "snapdragon 7",
            "dimensity 8", "dimensity 9", "helio g99", "rtx", "gtx",
            "radeon", "adreno", "mali", "120hz", "144hz", "165hz",
            "180hz", "240hz"
        ]

        score = 0.25
        score += keyword_score(text, keywords) * 0.45

        if any(k in text for k in ["rtx", "gtx", "radeon", "adreno", "mali"]):
            score += 0.15

        if ram >= 8:
            score += 0.10

        if any(k in text for k in ["120hz", "144hz", "165hz", "180hz", "240hz"]):
            score += 0.05

        return max(0.0, min(1.0, score))

    if usage == "content creation":
        keywords = [
            "creator", "proart", "studio", "macbook pro", "oled",
            "amoled", "4k", "3k", "qhd", "uhd", "rtx", "pro max",
            "ultra", "108mp", "200mp", "50mp", "512gb", "1tb", "2tb",
            "core i7", "core i9", "ryzen 7", "ryzen 9", "apple m"
        ]

        score = 0.25
        score += keyword_score(text, keywords) * 0.40

        if ram >= 16:
            score += 0.15

        if storage >= 512:
            score += 0.10

        if any(k in text for k in ["oled", "amoled", "qhd", "3k", "4k"]):
            score += 0.05

        if any(k in text for k in ["rtx", "radeon", "core i7", "core i9", "ryzen 7", "ryzen 9", "apple m"]):
            score += 0.05

        return max(0.0, min(1.0, score))

    return 0.50


def price_match_score(price, budget):
    if not budget or budget <= 0:
        return 0.0

    try:
        price = float(price)
        budget = float(budget)
    except Exception:
        return 0.0

    lower_limit, upper_limit = get_budget_range(budget)

    if price < lower_limit or price > upper_limit:
        return 0.0

    distance = abs(price - budget)
    max_distance = max(abs(upper_limit - budget), abs(budget - lower_limit))

    if max_distance <= 0:
        return 1.0

    score = 1.0 - (distance / max_distance)
    score = 0.80 + (score * 0.20)

    return max(0.0, min(1.0, score))


# =====================================================
# LOAD DATASET
# =====================================================

def load_data():
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(
            "Hindi makita ang gadgets.csv. Ilagay ang gadgets.csv sa same folder ng app.py."
        )

    df = pd.read_csv(DATA_FILE)

    required = [
        "id",
        "category",
        "usage",
        "brand",
        "model",
        "price",
        "price_text",
        "image_url",
        "image_file",
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

    for col in required:
        if col not in df.columns:
            df[col] = ""

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].fillna("").astype(str).str.strip()

    df["id"] = range(1, len(df) + 1)

    df["category"] = df["category"].apply(normalize_category)

    def fixed_price(row):
        current_price = parse_price(row.get("price", ""))

        if current_price is not None:
            return current_price

        return parse_price(row.get("price_text", ""))

    df["price"] = df.apply(fixed_price, axis=1)

    df = df.dropna(subset=["price"])
    df = df[df["price"] > 0]

    df = df[~((df["category"].str.lower() == "laptop") & (df["price"] < 5000))]
    df = df[df["model"].astype(str).str.strip() != ""]

    df["usage"] = df.apply(
        lambda row: classify_primary_usage(row),
        axis=1
    )

    df["search_blob"] = df.apply(make_blob, axis=1)

    df = df.drop_duplicates(
        subset=["category", "brand", "model", "price"],
        keep="first"
    )

    df["id"] = range(1, len(df) + 1)

    return df.reset_index(drop=True)


# =====================================================
# AUTO-RELOAD DATASET FOR N8N UPDATES
# =====================================================

DATA_CACHE = None
DATA_MTIME = None
CATEGORY_GUIDES_CACHE = None


def get_data(force_reload=False):
    global DATA_CACHE, DATA_MTIME, CATEGORY_GUIDES_CACHE

    if not os.path.exists(DATA_FILE):
        empty_df = pd.DataFrame(columns=[
            "id", "category", "usage", "brand", "model", "price",
            "price_text", "image_url", "image_file", "source_url",
            "detail_url", "ram", "storage", "processor", "display",
            "gpu", "battery", "camera", "os", "search_blob"
        ])
        DATA_CACHE = empty_df
        CATEGORY_GUIDES_CACHE = build_category_guides(empty_df)
        return empty_df.copy()

    current_mtime = os.path.getmtime(DATA_FILE)

    if force_reload or DATA_CACHE is None or DATA_MTIME != current_mtime:
        DATA_CACHE = load_data()
        DATA_MTIME = current_mtime
        CATEGORY_GUIDES_CACHE = build_category_guides(DATA_CACHE)
        print(f"Dataset loaded/reloaded: {len(DATA_CACHE)} records from {DATA_FILE}")

    return DATA_CACHE.copy()


def get_category_guides():
    global CATEGORY_GUIDES_CACHE

    if CATEGORY_GUIDES_CACHE is None:
        get_data(force_reload=True)

    return CATEGORY_GUIDES_CACHE or build_category_guides(pd.DataFrame())


# =====================================================
# ONLINE N8N PUBLIC API ROUTES
# =====================================================

def write_scraper_status(status, message, log_file="", started_at="", finished_at="", return_code=None):
    data = {
        "status": status,
        "message": message,
        "log_file": str(log_file) if log_file else "",
        "started_at": str(started_at) if started_at else "",
        "finished_at": str(finished_at) if finished_at else "",
        "return_code": return_code,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    STATUS_FILE.write_text(
        json.dumps(data, indent=4, ensure_ascii=False),
        encoding="utf-8"
    )


def read_scraper_status():
    if not STATUS_FILE.exists():
        return {
            "status": "idle",
            "message": "No scraper run yet.",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "status": "unknown",
            "message": "Could not read scraper status."
        }


def copy_latest_clean_csv_to_gadgets():
    latest_files = []
    latest_files += list(BASE_DIR.glob("find_my_gadget_CLEAN_*.csv"))
    latest_files += list(OUTPUT_DIR.glob("find_my_gadget_CLEAN_*.csv"))
    latest_files += list(OUTPUT_DIR.glob("find_my_gadget_latest.csv"))

    if not latest_files:
        return False

    latest_file = max(latest_files, key=lambda file: file.stat().st_mtime)
    shutil.copyfile(latest_file, DATA_FILE)
    return True


def run_scraper_background():
    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"online_scraper_{timestamp}.log"

    try:
        LOCK_FILE.write_text("running", encoding="utf-8")

        write_scraper_status(
            status="running",
            message="Scraper is running in the background.",
            log_file=log_file,
            started_at=started_at
        )

        result = subprocess.run(
            [sys.executable, str(SCRAPER_PATH)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        finished_at = datetime.now()

        log_text = ""
        log_text += f"Started: {started_at}\n"
        log_text += f"Finished: {finished_at}\n"
        log_text += f"Return code: {result.returncode}\n\n"
        log_text += "===== STDOUT =====\n"
        log_text += result.stdout
        log_text += "\n\n===== STDERR =====\n"
        log_text += result.stderr

        log_file.write_text(log_text, encoding="utf-8")

        copied = copy_latest_clean_csv_to_gadgets()
        data = get_data(force_reload=True)

        if result.returncode == 0:
            write_scraper_status(
                status="success",
                message=f"Scraping completed. gadgets.csv updated: {copied}. Dataset refreshed. Rows: {len(data)}.",
                log_file=log_file,
                started_at=started_at,
                finished_at=finished_at,
                return_code=result.returncode
            )
        else:
            write_scraper_status(
                status="failed",
                message="Scraper finished with error. Check logs.",
                log_file=log_file,
                started_at=started_at,
                finished_at=finished_at,
                return_code=result.returncode
            )

    except Exception as e:
        finished_at = datetime.now()

        try:
            log_file.write_text(str(e), encoding="utf-8")
        except Exception:
            pass

        write_scraper_status(
            status="error",
            message=str(e),
            log_file=log_file,
            started_at=started_at,
            finished_at=finished_at
        )

    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()


# =====================================================
# RECOMMENDATION SYSTEM
# =====================================================

def to_card(row, match_score=None):
    price = row.get("price", None)

    features = []

    if safe_feature(row.get("processor", ""), ""):
        features.append(("Processor", safe_feature(row.get("processor"))))

    if safe_feature(row.get("ram", ""), ""):
        features.append(("RAM", safe_feature(row.get("ram"))))

    if safe_feature(row.get("storage", ""), ""):
        features.append(("Storage", safe_feature(row.get("storage"))))

    if safe_feature(row.get("display", ""), ""):
        features.append(("Display", safe_feature(row.get("display"))))

    if safe_feature(row.get("gpu", ""), ""):
        features.append(("GPU", safe_feature(row.get("gpu"))))

    if safe_feature(row.get("battery", ""), ""):
        features.append(("Battery", safe_feature(row.get("battery"))))

    if safe_feature(row.get("camera", ""), ""):
        features.append(("Camera", safe_feature(row.get("camera"))))

    if safe_feature(row.get("os", ""), ""):
        features.append(("OS", safe_feature(row.get("os"))))

    if not features:
        features = [("Info", "Open View Details for complete specs")]

    return {
        "id": int(row.get("id")),
        "brand": safe_feature(row.get("brand"), "Unknown Brand"),
        "model": safe_feature(row.get("model"), "Unknown Gadget"),
        "category": safe_feature(row.get("category"), "Gadget"),
        "usage": safe_feature(row.get("usage"), "Student / School"),
        "price": float(price) if price is not None and not pd.isna(price) else None,
        "price_display": money(price),
        "image": get_image(row),
        "fallback_image": default_category_image(row.get("category", "Gadget")),
        "link": make_link(row),
        "features": features[:6],
        "match_score": round(float(match_score), 1) if match_score is not None else None,
    }


def recommend(budget, category, usage):
    df = get_data()

    category = clean_text(category)
    usage = clean_text(usage) or "All"

    if category and category.lower() != "all":
        df = df[df["category"].str.lower() == category.lower()].copy()

    if df.empty:
        return []

    lower_limit, upper_limit = get_budget_range(budget)

    df = df[
        (df["price"] >= lower_limit) &
        (df["price"] <= upper_limit)
    ].copy()

    if df.empty:
        return []

    scores = []

    for _, row in df.iterrows():
        p_score = price_match_score(float(row["price"]), budget)

        if usage.lower() == "all":
            final = p_score * 100
        else:
            u_score = usage_match_score(row, usage)
            s_score = spec_power_score(row)

            exact_usage_bonus = 0.05 if clean_text(row.get("usage", "")).lower() == usage.lower() else 0.0

            final = (0.45 * p_score) + (0.40 * u_score) + (0.15 * s_score) + exact_usage_bonus
            final = max(0.0, min(1.0, final)) * 100

        scores.append(final)

    df["match_score"] = scores

    # Sorting rule for Suggestions:
    # 1. First result = exact budget match; if none, closest price to the user's budget.
    # 2. Remaining results = ascending percentage above the user's budget.
    #    Example: +0.5% appears before +2%, and +2% appears before +5%.
    df["price_distance"] = (df["price"] - budget).abs()
    df["above_budget_percent"] = ((df["price"] - budget) / budget * 100).clip(lower=0)
    df["distance_percent"] = (df["price_distance"] / budget * 100)

    df["is_budget_best_match"] = False
    closest_index = df["price_distance"].idxmin()
    df.loc[closest_index, "is_budget_best_match"] = True

    df = df.sort_values(
        [
            "is_budget_best_match",
            "above_budget_percent",
            "distance_percent",
            "match_score"
        ],
        ascending=[False, True, True, False]
    )

    return [to_card(row, row["match_score"]) for _, row in df.iterrows()]


# =====================================================
# HTML TEMPLATE
# =====================================================

HOME_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Find My Gadget</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<style>
*{
    margin:0;
    padding:0;
    box-sizing:border-box;
    font-family:"Times New Roman", Times, serif;
}

body{
    min-height:100vh;
    color:#ffffff;
    background:
        repeating-linear-gradient(0deg, rgba(255,255,255,.08) 0 1px, transparent 1px 75px),
        repeating-linear-gradient(90deg, rgba(255,255,255,.08) 0 1px, transparent 1px 75px),
        linear-gradient(135deg, #008b64 0%, #12c1b8 35%, #001d5c 72%, #020617 100%);
    background-attachment:fixed;
}

.header{
    background:rgba(1,10,28,.94);
    padding:22px 46px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:20px;
    position:sticky;
    top:0;
    z-index:10;
    border-bottom:2px solid rgba(255,255,255,.18);
    box-shadow:0 10px 30px rgba(0,0,0,.35);
}

.brand h1{
    letter-spacing:8px;
    font-size:30px;
    font-weight:900;
    color:white;
    text-shadow:3px 3px 0 #008ab0, 0 0 15px rgba(0, 255, 85, 0.7);
}

.brand p{
    margin-top:5px;
    color:#eaf2ff;
}

.page{
    display:grid;
    grid-template-columns:350px 1fr;
    gap:20px;
    padding:20px 24px;
    max-width:1450px;
    margin:auto;
}

.sidebar{
    background:linear-gradient(160deg, rgba(18, 155, 193, 0.88), rgba(0,29,92,.90));
    border:1px solid rgba(255,255,255,.25);
    border-radius:16px;
    padding:26px 24px;
    height:max-content;
    position:sticky;
    top:105px;
    box-shadow:0 15px 35px rgba(0,0,0,.35);
}

.sidebar h2{
    letter-spacing:5px;
    font-size:24px;
}

.sidebar p{
    margin-top:6px;
    color:#e5e7eb;
}

.form-group{
    margin-top:24px;
}

.form-group label{
    display:block;
    font-size:18px;
    font-weight:800;
    margin-bottom:10px;
}

input,
select{
    width:100%;
    padding:14px 16px;
    border:1px solid rgba(255,255,255,.25);
    border-radius:8px;
    font-size:17px;
    background:rgba(255,255,255,.12);
    color:white;
    outline:none;
}

select option{
    color:#111827;
}

.hint{
    margin-top:8px;
    font-size:14px;
    color:#fef3c7;
    line-height:1.4;
}

.category-guide{
    margin-top:12px;
    padding:14px;
    border-radius:10px;
    background:rgba(255,255,255,.14);
    border:1px solid rgba(255,255,255,.25);
    color:#ffffff;
    line-height:1.45;
}

.category-guide b{
    color:#ffe066;
}

.category-guide .small{
    color:#dbeafe;
    font-size:13px;
    margin-top:6px;
}

.range-row{
    display:flex;
    justify-content:space-between;
    margin-top:8px;
    color:#e5e7eb;
    font-size:14px;
}

input[type="range"]{
    margin-top:14px;
    accent-color:white;
}

.btn{
    width:100%;
    border:none;
    background:linear-gradient(135deg, #ffffff, #dbeafe);
    color:#001d5c;
    padding:14px 18px;
    border-radius:8px;
    font-size:17px;
    font-weight:900;
    cursor:pointer;
}

.content{
    background:linear-gradient(145deg, rgba(10,14,25,.92), rgba(30,10,18,.92), rgba(0,29,92,.88));
    border:1px solid rgba(255,255,255,.18);
    border-radius:16px;
    padding:28px;
    min-width:0;
    box-shadow:0 20px 45px rgba(0,0,0,.45);
}

.content-head{
    background:linear-gradient(135deg, rgba(94, 193, 18, 0.95), rgba(0,29,92,.95));
    border-left:8px solid #ffffff;
    border-radius:14px;
    padding:20px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:15px;
    margin-bottom:20px;
}

.content-head h2{
    letter-spacing:5px;
    font-size:26px;
}

.result-count{
    background:#eaf8ef;
    border:2px solid #63c67a;
    color:#006b2e;
    padding:13px 20px;
    border-radius:10px;
    font-size:17px;
    font-weight:900;
    white-space:nowrap;
}

.cards{
    display:grid;
    grid-template-columns:repeat(auto-fill, minmax(270px, 1fr));
    gap:18px;
}

.card{
    background:rgba(255,255,255,.10);
    border:1px solid rgba(255,255,255,.18);
    border-radius:14px;
    padding:16px;
    box-shadow:0 12px 28px rgba(0,0,0,.30);
    overflow:hidden;
}

.img-box{
    height:190px;
    background:rgba(255,255,255,.10);
    border-radius:10px;
    display:flex;
    justify-content:center;
    align-items:center;
    overflow:hidden;
    margin-bottom:14px;
}

.img-box img{
    width:100%;
    height:100%;
    object-fit:cover;
    background:white;
}

.no-img{
    color:#dbeafe;
    font-weight:900;
    text-align:center;
    padding:15px;
}

.card h3{
    font-size:20px;
    line-height:1.2;
    margin-bottom:10px;
}

.badges{
    display:flex;
    flex-wrap:wrap;
    gap:8px;
    margin-bottom:10px;
}

.badge{
    background:#1298c1;
    border:1px solid rgba(255,255,255,.25);
    padding:6px 9px;
    border-radius:999px;
    font-size:13px;
    font-weight:800;
}

.price{
    font-size:24px;
    font-weight:900;
    color:#ffe066;
    margin:10px 0;
}

.score{
    background:rgba(0,255,136,.14);
    border:1px solid rgba(0,255,136,.35);
    color:#a7f3d0;
    padding:8px 10px;
    border-radius:8px;
    font-weight:900;
    margin-bottom:10px;
}

.features{
    margin:12px 0;
    list-style:none;
}

.features li{
    padding:7px 0;
    border-bottom:1px solid rgba(255,255,255,.12);
    font-size:15px;
}

.view-btn{
    display:block;
    text-align:center;
    text-decoration:none;
    background:linear-gradient(135deg, #f7d54a, #caa600);
    color:#111827;
    padding:11px 14px;
    border-radius:8px;
    font-weight:900;
    margin-top:12px;
}

.empty{
    padding:40px;
    text-align:center;
    border:1px dashed rgba(255,255,255,.35);
    border-radius:10px;
    background:rgba(255,255,255,.08);
}

@media(max-width:900px){
    .header{
        flex-direction:column;
        align-items:flex-start;
        padding:20px;
    }

    .page{
        grid-template-columns:1fr;
        padding:14px;
    }

    .sidebar{
        position:static;
    }

    .content-head{
        flex-direction:column;
        align-items:flex-start;
    }

    .result-count{
        width:100%;
        text-align:center;
    }
}
</style>
</head>

<body>

<header class="header">
    <div class="brand">
        <h1>FIND MY GADGET</h1>
        <p>Personalized Gadget Selector Using Budget and Usage Criteria</p>
    </div>
</header>

<main class="page">

    <aside class="sidebar">
        <h2>FIND YOUR GADGET</h2>
        <p>Select your preferences below</p>

        <form method="GET" action="/">
            <div class="form-group">
                <label>1. Enter Budget</label>
                <input type="text" id="budgetInput" name="budget" value="{{ budget_input }}" placeholder="Example: 10000 or 10k">
            

                <input type="range" id="budgetRange" min="500" max="500000" value="{{ budget_value }}">
                <div class="range-row">
                    <span id="guideMin">Min: ₱0</span>
                    <span id="guideMax">Max: ₱0</span>
                </div>
            </div>

            <div class="form-group">
                <label>2. Select Gadget Type</label>
                <select name="category" id="categorySelect">
                    <option value="All" {% if category == "All" %}selected{% endif %}>All Gadgets</option>
                    {% for cat in categories %}
                        <option value="{{ cat }}" {% if cat == category %}selected{% endif %}>
                            {% if cat == "Smartphone" %}Phone{% else %}{{ cat }}{% endif %}
                        </option>
                    {% endfor %}
                </select>

                <div class="category-guide" id="categoryGuide">
                    Loading category instruction...
                </div>
            </div>

            <div class="form-group">
                <label>3. Select Intended Usage</label>
                <select name="usage">
                    {% for use in usages %}
                        <option value="{{ use }}" {% if use == usage %}selected{% endif %}>{{ use }}</option>
                    {% endfor %}
                </select>
                <div class="hint">
                    Choose <b>All</b> if you want budget-only recommendation.
                </div>
            </div>

            <div class="form-group">
                <button type="submit" class="btn">Find Gadget</button>
            </div>
        </form>
    </aside>

    <section class="content">
        <div class="content-head">
            <div>
                <h2>RECOMMENDED GADGETS</h2>
                <p>
                    Budget: <b>{{ budget_display }}</b><br>
                    Accepted price range: <b>{{ lower_display }}</b> to <b>{{ upper_display }}</b><br>
                    Type: <b>{{ category }}</b> |
                    Usage: <b>{{ usage }}</b>
                </p>
            </div>

            <div class="result-count">✔ {{ results|length }} Results Found</div>
        </div>

        {% if results %}
        <div class="cards">
            {% for item in results %}
            <article class="card">
                <div class="img-box">
                    <img
                        src="{{ item.image }}"
                        alt="{{ item.brand }} {{ item.model }}"
                        onerror="this.onerror=null; this.src='{{ item.fallback_image }}';"
                    >
                </div>

                <h3>{{ item.brand }} {{ item.model }}</h3>

                <div class="badges">
                    <span class="badge">{{ item.category }}</span>
                    <span class="badge">{{ item.usage }}</span>
                </div>

                <div class="price">{{ item.price_display }}</div>

                {% if item.match_score is not none %}
                    <div class="score">Match Score: {{ item.match_score }}%</div>
                {% endif %}

                <ul class="features">
                    {% for label, value in item.features %}
                        <li><strong>{{ label }}:</strong> {{ value }}</li>
                    {% endfor %}
                </ul>

                <a href="{{ item.link }}" target="_blank" class="view-btn">View Details</a>
            </article>
            {% endfor %}
        </div>
        {% else %}
            <div class="empty">
                No matching gadgets found within the allowed price range.<br><br>
                Try another budget.   </div>
        {% endif %}
    </section>
</main>

<script>
const budgetInput = document.getElementById("budgetInput");
const budgetRange = document.getElementById("budgetRange");
const categorySelect = document.getElementById("categorySelect");
const categoryGuide = document.getElementById("categoryGuide");
const guideMin = document.getElementById("guideMin");
const guideMax = document.getElementById("guideMax");

const CATEGORY_GUIDES = {{ category_guides|tojson }};

function parseBudgetText(value){
    value = String(value).toLowerCase().replace("₱", "").replaceAll(",", "").replace("php", "").trim();

    if(value.endsWith("k")){
        let n = parseFloat(value.replace("k", ""));
        if(!isNaN(n)){
            return n * 1000;
        }
    }

    let n = parseFloat(value);

    if(!isNaN(n)){
        return n;
    }

    return 10000;
}

function peso(value){
    value = Number(value);

    if(isNaN(value)){
        return "₱0";
    }

    return "₱" + value.toLocaleString("en-PH", {
        maximumFractionDigits: 0
    });
}

function updateCategoryInstruction(){
    let selected = categorySelect.value;
    let guide = CATEGORY_GUIDES[selected] || CATEGORY_GUIDES["All"];

    if(!guide){
        categoryGuide.innerHTML = "No price guide available.";
        guideMin.textContent = "Min: ₱0";
        guideMax.textContent = "Max: ₱0";
        return;
    }

    if(Number(guide.count) <= 0){
        categoryGuide.innerHTML = `
            <b>${guide.label}</b><br>
            No available price data for this category.
        `;
        guideMin.textContent = "Min: ₱0";
        guideMax.textContent = "Max: ₱0";
        return;
    }

    let minPrice = Number(guide.min_price);
    let maxPrice = Number(guide.max_price);

    guideMin.textContent = "Min: " + peso(minPrice);
    guideMax.textContent = "Max: " + peso(maxPrice);

    budgetRange.min = Math.floor(minPrice);
    budgetRange.max = Math.ceil(maxPrice);

    let currentBudget = parseBudgetText(budgetInput.value);

    if(!isNaN(currentBudget)){
        if(currentBudget < minPrice){
            budgetRange.value = Math.floor(minPrice);
        }else if(currentBudget > maxPrice){
            budgetRange.value = Math.ceil(maxPrice);
        }else{
            budgetRange.value = Math.round(currentBudget);
        }
    }

    categoryGuide.innerHTML = `
        <b>${guide.label} Price Guide</b><br>
        Suggested budget input: <b>${peso(minPrice)}</b> to <b>${peso(maxPrice)}</b><br>
        Available data records: <b>${guide.count}</b>
        <div class="small">
            This guide is based on your current gadgets.csv dataset.
            The result will still follow the strict range: 0.1% below and 5% above your entered budget.
        </div>
    `;
}

budgetInput.addEventListener("input", function(){
    let value = parseBudgetText(budgetInput.value);
    let minValue = Number(budgetRange.min);
    let maxValue = Number(budgetRange.max);

    if(value >= minValue && value <= maxValue){
        budgetRange.value = value;
    }
});

budgetRange.addEventListener("input", function(){
    budgetInput.value = budgetRange.value;
});

categorySelect.addEventListener("change", function(){
    updateCategoryInstruction();
});

updateCategoryInstruction();
</script>

</body>
</html>
"""


# =====================================================
# ROUTES
# =====================================================

@app.route("/gadget_images/<path:filename>")
def serve_gadget_image(filename):
    return send_from_directory(IMAGE_FOLDER, filename)


@app.route("/status", methods=["GET"])
def scraper_status():
    return jsonify(read_scraper_status())


@app.route("/run-scraper", methods=["GET", "POST"])
def run_scraper():
    if LOCK_FILE.exists():
        return jsonify({
            "status": "busy",
            "message": "Scraper is already running. Please wait.",
            "status_endpoint": "/status"
        }), 409

    if not SCRAPER_PATH.exists():
        return jsonify({
            "status": "error",
            "message": "scrape_gadgets.py not found.",
            "expected_path": str(SCRAPER_PATH)
        }), 404

    thread = threading.Thread(target=run_scraper_background)
    thread.daemon = True
    thread.start()

    return jsonify({
        "status": "started",
        "message": "Scraper started in the background.",
        "status_endpoint": "/status"
    }), 202


@app.route("/refresh-data", methods=["GET", "POST"])
def refresh_data():
    data = get_data(force_reload=True)

    return jsonify({
        "status": "success",
        "message": "Dataset refreshed successfully.",
        "rows": int(len(data)),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/")
def index():
    budget_input = request.args.get("budget", "10000")
    category = request.args.get("category", "Smartphone")
    usage = request.args.get("usage", "All")

    if clean_text(category).lower() in ["phone", "phones", "smartphone", "smartphones"]:
        category = "Smartphone"

    budget_value = parse_budget_input(budget_input)

    if budget_value < 500:
        budget_value = 500

    if budget_value > 500000:
        budget_value = 500000

    lower_limit, upper_limit = get_budget_range(budget_value)

    data = get_data()
    categories = sorted(data["category"].dropna().unique().tolist())

    if category not in categories and category != "All":
        category = "Smartphone" if "Smartphone" in categories else "All"

    if usage not in USAGES:
        usage = "All"

    results = recommend(budget_value, category, usage)

    return render_template_string(
        HOME_HTML,
        results=results,
        budget_input=budget_input,
        budget_value=int(budget_value),
        budget_display=money(budget_value),
        lower_display=money(lower_limit),
        upper_display=money(upper_limit),
        category=category,
        usage=usage,
        categories=categories,
        usages=USAGES,
        category_guides=get_category_guides()
    )


if __name__ == "__main__":
    data = get_data(force_reload=True)
    print(f"Loaded {len(data)} gadget records from {DATA_FILE}")
    print("Open: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
