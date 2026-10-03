# -*- coding: utf-8 -*-
import os
import sys
import time
from io import BytesIO

from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_URL = "http://localhost:8000"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "portfolio")
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
    time.sleep(1)
    try:
        driver.execute_script("localStorage.removeItem('scm_token');")
        driver.get(f"{BASE_URL}/login")
        time.sleep(1)
        driver.find_element(By.ID, "login-id").send_keys("admin")
        driver.find_element(By.ID, "login-pw").send_keys("admin")
        driver.find_element(By.ID, "login-btn").click()
        time.sleep(2)
        token = driver.execute_script("return localStorage.getItem('scm_token')")
        if token:
            print("[OK] Form Login successful.")
            return True
    except Exception as e:
        print(f"[WARN] Form Login failed: {e}")

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
                if(d.access_token) {
                    localStorage.setItem('scm_token', d.access_token);
                    return true;
                }
                return false;
            });
        """)
        if result:
            print("[OK] API Login successful.")
            return True
    except Exception as e:
        print(f"[ERROR] API Login failed: {e}")
    return False

def capture_gif_order_plan(driver):
    print("Capturing Order Plan Simulation GIF...")
    driver.get(f"{BASE_URL}/order-plan")
    time.sleep(3)
    
    # Hide loader
    driver.execute_script("""
        var l = document.getElementById('global-loader');
        if (l) l.classList.remove('active');
    """)
    time.sleep(0.5)
    
    frames = []
    
    # Capture initial state a few times to pause
    for _ in range(5):
        png = driver.get_screenshot_as_png()
        frames.append(Image.open(BytesIO(png)))
        
    try:
        slider = driver.find_element(By.ID, "weight-slider")
        action = ActionChains(driver)
        
        # Simulate moving slider to the right step by step
        for offset in range(10, 150, 20):
            action.click_and_hold(slider).move_by_offset(offset, 0).release().perform()
            time.sleep(0.3)
            png = driver.get_screenshot_as_png()
            frames.append(Image.open(BytesIO(png)))
            
        # Hold at end
        for _ in range(5):
            frames.append(frames[-1])
            
        # Move back
        for offset in range(-20, -100, -20):
            action.click_and_hold(slider).move_by_offset(offset, 0).release().perform()
            time.sleep(0.3)
            png = driver.get_screenshot_as_png()
            frames.append(Image.open(BytesIO(png)))
            
    except Exception as e:
        print(f"Failed to interact with slider: {e}")
        
    # Save GIF
    if frames:
        gif_path = os.path.join(OUTPUT_DIR, "order_plan_simulation.gif")
        frames[0].save(
            gif_path, 
            save_all=True, 
            append_images=frames[1:], 
            optimize=True, 
            duration=300, 
            loop=0
        )
        print(f"[SAVED] {gif_path}")

def capture_gif_inventory_filters(driver):
    print("Capturing Inventory Filters GIF...")
    driver.get(f"{BASE_URL}/inventory")
    time.sleep(3)
    
    # Hide loader
    driver.execute_script("""
        var l = document.getElementById('global-loader');
        if (l) l.classList.remove('active');
    """)
    time.sleep(0.5)
    
    frames = []
    for _ in range(3):
        png = driver.get_screenshot_as_png()
        frames.append(Image.open(BytesIO(png)))
        
    try:
        # Click the first warehouse filter to toggle it
        checkboxes = driver.find_elements(By.CSS_SELECTOR, ".filter-checkbox input[type='checkbox']")
        if len(checkboxes) > 1:
            # Uncheck second checkbox
            checkboxes[1].click()
            time.sleep(0.5)
            frames.append(Image.open(BytesIO(driver.get_screenshot_as_png())))
            
            # Uncheck third checkbox
            if len(checkboxes) > 2:
                checkboxes[2].click()
                time.sleep(0.5)
                frames.append(Image.open(BytesIO(driver.get_screenshot_as_png())))
                
            # Wait
            for _ in range(3):
                frames.append(frames[-1])
                
            # Recheck second checkbox
            checkboxes[1].click()
            time.sleep(0.5)
            frames.append(Image.open(BytesIO(driver.get_screenshot_as_png())))
            
    except Exception as e:
        print(f"Failed to interact with filters: {e}")
        
    if frames:
        gif_path = os.path.join(OUTPUT_DIR, "inventory_filters.gif")
        frames[0].save(
            gif_path, 
            save_all=True, 
            append_images=frames[1:], 
            optimize=True, 
            duration=400, 
            loop=0
        )
        print(f"[SAVED] {gif_path}")


def main():
    print("Starting Media Capture...")
    driver = get_driver()
    try:
        if login(driver):
            capture_gif_order_plan(driver)
            capture_gif_inventory_filters(driver)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
