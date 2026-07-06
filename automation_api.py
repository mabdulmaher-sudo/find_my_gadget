from flask import Flask, jsonify
from pathlib import Path
from datetime import datetime
import subprocess
import threading
import sys
import json
import requests

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BASE_DIR / "scrape_gadgets.py"
LOG_DIR = BASE_DIR / "logs"
LOCK_FILE = BASE_DIR / "scraper.lock"
STATUS_FILE = BASE_DIR / "scraper_status.json"

LOG_DIR.mkdir(exist_ok=True)


def write_status(status, message, log_file="", started_at="", finished_at="", return_code=None):
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


def read_status():
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


def run_scraper_background():
    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"scraper_{timestamp}.log"

    try:
        LOCK_FILE.write_text("running", encoding="utf-8")

        write_status(
            status="running",
            message="Scraper is currently running in the background.",
            log_file=log_file,
            started_at=started_at
        )

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
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

        if result.returncode == 0:
            # Optional: refresh main app data if app.py is running
            try:
                requests.get("http://127.0.0.1:5000/refresh-data", timeout=10)
            except Exception:
                pass

            write_status(
                status="success",
                message="Scraping and data cleaning completed successfully.",
                log_file=log_file,
                started_at=started_at,
                finished_at=finished_at,
                return_code=result.returncode
            )
        else:
            write_status(
                status="failed",
                message="Scraper finished with error. Check log file.",
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

        write_status(
            status="error",
            message=str(e),
            log_file=log_file,
            started_at=started_at,
            finished_at=finished_at
        )

    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "running",
        "message": "Find My Gadget Automation API is running.",
        "run_scraper_endpoint": "/run-scraper",
        "status_endpoint": "/status"
    })


@app.route("/status", methods=["GET"])
def status():
    return jsonify(read_status())


@app.route("/run-scraper", methods=["GET", "POST"])
def run_scraper():
    if LOCK_FILE.exists():
        return jsonify({
            "status": "busy",
            "message": "Scraper is already running. Please wait.",
            "status_endpoint": "/status"
        }), 409

    if not SCRIPT_PATH.exists():
        return jsonify({
            "status": "error",
            "message": "scrape_gadgets.py not found.",
            "expected_path": str(SCRIPT_PATH)
        }), 404

    thread = threading.Thread(target=run_scraper_background)
    thread.daemon = True
    thread.start()

    return jsonify({
        "status": "started",
        "message": "Scraper started in the background. n8n does not need to wait until scraping is finished.",
        "status_endpoint": "/status",
        "script": str(SCRIPT_PATH)
    }), 202


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)