# -*- coding: utf-8 -*-
"""
EIBE SCM Dashboard - Portfolio Screenshot Capture Script
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

BASE_URL = "http://localhost:8000"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio")
os.makedirs(OUTPUT_DIR, exist_ok=True)

PAGES = [
    {"name": "02_dashboard", "path": "/", "desc": "Summary Dashboard"},
    {"name": "03_inventory", "path": "/inventory", "desc": "Inventory Management"},
    {"name": "04_expiry", "path": "/expiry", "desc": "Expiry Management"},
    {"name": "05_order_plan", "path": "/order-plan", "desc": "Order Planning"},
    {"name": "06_matching", "path": "/matching", "desc": "Inbound Management"},
    {"name": "07_settings", "path": "/users", "desc": "System Settings"},
]

DARK_PAGES = [
    {"name": "08_dashboard_dark", "path": "/", "desc": "Dashboard Dark Mode"},
    {"name": "09_inventory_dark", "path": "/inventory", "desc": "Inventory Dark Mode"},
]


def get_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--force-device-scale-factor=1")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--lang=ko-KR")
    return webdriver.Chrome(options=opts)


def login(driver):
    driver.get(f"{BASE_URL}/login")
    time.sleep(2)
    driver.execute_script("localStorage.removeItem('scm_token');")
    driver.get(f"{BASE_URL}/login")
    time.sleep(2)

    try:
        username_input = driver.find_element(By.ID, "login-id")
        password_input = driver.find_element(By.ID, "login-pw")
        username_input.clear()
        username_input.send_keys("admin")
        password_input.clear()
        password_input.send_keys("admin")
        submit_btn = driver.find_element(By.ID, "login-btn")
        submit_btn.click()
        time.sleep(3)
        token = driver.execute_script("return localStorage.getItem('scm_token')")
        if token:
            print("  [OK] Logged in successfully.")
            return True
    except Exception as e:
        print(f"  [WARN] Form login issue: {e}")

    try:
        result = driver.execute_script("""
            const formData = new URLSearchParams();
            formData.append('username', 'admin');
            formData.append('password', 'admin');
            return fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: formData
            }).then(r => r.json()).then(d => {
                if (d.access_token) {
                    localStorage.setItem('scm_token', d.access_token);
                    return true;
                }
                return false;
            });
        """)
        if result:
            print("  [OK] Logged in via JS fallback.")
            return True
    except Exception as e:
        print(f"  [ERROR] JS fallback failed: {e}")
    return False


def capture(driver, filepath):
    # Get total height
    total_height = driver.execute_script("return Math.max(document.body.scrollHeight, document.body.offsetHeight, document.documentElement.clientHeight, document.documentElement.scrollHeight, document.documentElement.offsetHeight);")
    # Add a little buffer
    driver.set_window_size(1920, total_height + 100)
    time.sleep(0.5)
    driver.find_element(By.TAG_NAME, 'body').screenshot(filepath)
    # reset to normal viewport just in case
    driver.set_window_size(1920, 1080)
    print(f"  [SAVED] {os.path.basename(filepath)}")


def main():
    print("=" * 50)
    print("  EIBE SCM - Portfolio Screenshot Capture")
    print("=" * 50)

    driver = get_driver()
    try:
        print("\n[1/3] Capturing login page...")
        driver.get(f"{BASE_URL}/login")
        time.sleep(2)
        driver.execute_script("localStorage.removeItem('scm_token');")
        driver.get(f"{BASE_URL}/login")
        time.sleep(2)
        capture(driver, os.path.join(OUTPUT_DIR, "01_login.png"))

        print("\n[2/3] Logging in...")
        if not login(driver):
            print("Exiting due to login failure.")
            return

        print("\n[3/3] Capturing Light Mode pages...")
        for page in PAGES:
            print(f"\n  -> {page['desc']} ({page['path']})")
            driver.get(f"{BASE_URL}{page['path']}")
            time.sleep(3)
            driver.execute_script("""
                var l = document.getElementById('global-loader');
                if (l) l.classList.remove('active');
            """)
            time.sleep(1)
            capture(driver, os.path.join(OUTPUT_DIR, f"{page['name']}.png"))

        print("\n[4/4] Capturing Dark Mode pages...")
        driver.execute_script("localStorage.setItem('theme', 'dark');")
        for page in DARK_PAGES:
            print(f"\n  -> {page['desc']} ({page['path']})")
            driver.get(f"{BASE_URL}{page['path']}")
            time.sleep(3)
            driver.execute_script("""
                var l = document.getElementById('global-loader');
                if (l) l.classList.remove('active');
            """)
            time.sleep(2)
            capture(driver, os.path.join(OUTPUT_DIR, f"{page['name']}.png"))

        print("\n" + "=" * 50)
        total = 1 + len(PAGES) + len(DARK_PAGES)
        print(f"  DONE! {total} screenshots saved to portfolio/")
        print("=" * 50)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
