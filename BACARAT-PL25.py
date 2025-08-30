import concurrent.futures
import os
import sys
import traceback
import psutil
import requests
import random
from io import BytesIO
import re
import base64
from PIL import Image
import pytesseract
from PyQt5.QtGui import QTextCursor
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QTextEdit, QPushButton, QLineEdit, QComboBox, QMessageBox, QCheckBox,
                             QDialog, QTableWidget, QTableWidgetItem)  # Thêm QTableWidgetItem vào đây)
from PyQt5.QtCore import Qt, QThread, QTimer
from pathlib import Path
import pyautogui
import json
import logging
import threading
import csv
import time
from PyQt5.QtCore import QThread, pyqtSignal
import urllib3
import subprocess
import webbrowser

# KHAI BÁO PHIÊN BẢN HIỆN TẠI CỦA ỨNG DỤNG
CURRENT_VERSION = "1.0.0"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # Tắt cảnh báo InsecureRequestWarning
# Cấu hình logging
import logging.handlers

# Cấu hình logging với mã hóa UTF-8
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Tạo handler cho file với mã hóa UTF-8
file_handler = logging.handlers.RotatingFileHandler(
    filename="roulette.log",
    encoding="utf-8",  # Đảm bảo sử dụng UTF-8
    maxBytes=10*1024*1024,  # Giới hạn kích thước file log (10MB)
    backupCount=5  # Giữ tối đa 5 file backup
)
file_handler.setLevel(logging.INFO)

# Định dạng log
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)

# Thêm handler vào logger
logger.addHandler(file_handler)

# Thiết lập môi trường Playwright
if getattr(sys, 'frozen', False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.path.dirname(sys.executable), ".playwright")
else:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = ".playwright"

# Đường dẫn cấu hình
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

# Biến toàn cục
CONFIG_FILE = Path('config.json')
csv_lock = threading.Lock()
file_lock = threading.Lock()
active_browsers = []
total_browsers = 0
countdown_status = {}
countdown_lock = threading.Lock()
all_countdowns_ready_event = threading.Event()
account_status = {}
account_lock = threading.Lock()
autorou_status = {}
autorou_lock = threading.Lock()
all_autorou_clicked_event = threading.Event()
total_accounts = 0
completed_accounts = 0
all_chips_selected_event = threading.Event()
stop_event = threading.Event()
bet_status = {}
bet_status_lock = threading.Lock()
table_status = "Bàn cược ẩn"
table_status_lock = threading.Lock()
current_round = 0
round_lock = threading.Lock()
credentials = []

# Hàm chung: Tạo User-Agent ngẫu nhiên
def generate_random_user_agent():
    operating_systems = ['Windows NT 10.0; Win64; x64', 'Windows NT 11.0; Win64; x64']
    browsers = {
        'Chrome': [f"{random.randint(133, 136)}.{random.randint(0, 9)}.{random.randint(0, 9)}.{random.randint(0, 9)}" for _ in range(10)],
        'Safari': [f"{random.randint(14, 15)}.{random.randint(0, 2)}.{random.randint(0, 2)}/605.1.{random.randint(1, 9)}" for _ in range(10)],
    }
    os_ = random.choice(operating_systems)
    browser_name = random.choice(['Safari', 'Chrome'])
    browser_version = random.choice(browsers[browser_name])
    if browser_name == 'Chrome':
        return f'Mozilla/5.0 ({os_}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser_version} Safari/537.36'
    else:
        version, safari = browser_version.split('/')
        return f'Mozilla/5.0 ({os_}) AppleWebKit/{safari} (KHTML, like Gecko) Version/{version} Safari/{safari}'

# Hàm chung: Kiểm tra proxy
def set_total_accounts(count, credentials):
    global total_accounts
    total_accounts = count
    logging.info(f"Set total_accounts: {total_accounts}")
    with countdown_lock:
        countdown_status.clear()
        for username, _ in credentials:
            countdown_status[username] = False
        logging.info(f"Initialized countdown_status: {countdown_status}")
    with autorou_lock:
        autorou_status.clear()
        for username, _ in credentials:
            autorou_status[username] = False
        logging.info(f"Initialized autorou_status: {autorou_status}")
    with account_lock:
        account_status.clear()
        for username, _ in credentials:
            account_status[username] = False
        logging.info(f"Initialized account_status: {account_status}")
    with bet_status_lock:
        bet_status.clear()
        for username, _ in credentials:
            bet_status[username] = False
        logging.info(f"Initialized bet_status: {bet_status}")

# Hàm chung: Giải mã và xử lý captcha
def decode_base64_to_image(base64_str):
    image_data = base64.b64decode(base64_str)
    image_buffer = BytesIO(image_data)
    return Image.open(image_buffer)

def demo_imagetotext(image):
    text = pytesseract.image_to_string(image)
    text = text.replace('/', '').replace("\n", '')
    return text[:4]

def handle_captcha(page):
    try:
        captcha_input = page.locator('input[ng-model="$ctrl.code"]')
        if captcha_input.is_visible():
            captcha_input.click()
            time.sleep(1)
            captcha_image = page.locator('img[src^="data:image/png;base64,"]')
            if captcha_image.is_visible():
                captcha_src = captcha_image.get_attribute("src")
                if captcha_src and captcha_src.startswith("data:image/png;base64,"):
                    base64_str = captcha_src.split(",")[1]
                    image = decode_base64_to_image(base64_str)
                    captcha_code = demo_imagetotext(image)
                    if not captcha_code:
                        captcha_code = '1'
                    captcha_input.fill(captcha_code)
                    time.sleep(0.5)
                    return captcha_code
    except Exception:
        return None

# Hàm chung: Xử lý modal
def handle_modal(page, username, max_attempts=3):
    image_selector = 'img[src*="centerMask1_vn.jpg"], img[src*="centerMask2_vn.jpg"]'
    modal_found = False
    modal_iframe_index = None
    attempt = 0

    logging.info(f"Bắt đầu tìm modal cho {username}...")
    while attempt < max_attempts and not modal_found and not stop_event.is_set():
        attempt += 1
        logging.info(f"Thử {attempt} kiểm tra iframe cho modal cho {username}...")
        iframes = page.locator('iframe').all()
        logging.info(f"Số iframe tìm thấy cho {username}: {len(iframes)}")

        if iframes:
            for idx, _ in enumerate(iframes):
                frame = page.frame_locator('iframe').nth(idx)
                try:
                    frame.locator(image_selector).wait_for(state='visible', timeout=500)
                    logging.info(f"Đã tìm thấy modal trong iframe {idx} cho {username} ở lần thử {attempt}")
                    modal_found = True
                    modal_iframe_index = idx
                    break
                except PlaywrightTimeoutError:
                    logging.info(f"Không tìm thấy modal trong iframe {idx} cho {username}.")

        if not modal_found and attempt < max_attempts:
            logging.warning(f"Không tìm thấy modal trong bất kỳ iframe nào cho {username}. Thử lại sau 0.5 giây...")
            time.sleep(0.5)
        elif not modal_found:
            logging.warning(f"Không tìm thấy modal sau {max_attempts} lần thử cho {username}. Tiếp tục tìm Roulette.")
            return False, None

    if modal_found:
        close_attempt = 0
        close_success = False
        frame = page.frame_locator('iframe').nth(modal_iframe_index)
        while close_attempt < max_attempts and not close_success:
            close_attempt += 1
            logging.info(f"Thử {close_attempt} đóng modal cho {username}...")
            try:
                close_button = frame.locator('button:has(svg[width="31"][height="32"])')
                close_button.click()
                page.wait_for_selector(image_selector, state='hidden', timeout=2000)
                logging.info(f"Đã đóng modal thành công trong iframe {modal_iframe_index} cho {username}")
                close_success = True
            except Exception as e:
                logging.error(f"Lỗi khi đóng modal trong iframe {modal_iframe_index} cho {username} ở lần thử {close_attempt}: {e}")
                if close_attempt < max_attempts:
                    time.sleep(0.5)
                else:
                    logging.warning(f"Không thể đóng modal sau {max_attempts} lần thử cho {username}.")
                    return False, None
        return True, modal_iframe_index
    return False, None

# Hàm chung: Tìm và nhấp vào Roulette hoặc AutoRou
def click_game_element(page, username, selector, element_name, max_attempts=3):
    attempt = 0
    found = False
    while attempt < max_attempts and not found and not stop_event.is_set():
        attempt += 1
        logging.info(f"Thử {attempt}/{max_attempts} tìm {element_name} cho {username}...")
        iframes = page.locator('iframe').all()
        logging.info(f"Số iframe tìm thấy khi tìm {element_name} cho {username}: {len(iframes)}")

        if iframes:
            frame = page.frame_locator('iframe').nth(0)
            try:
                element = frame.locator(selector).first
                element.wait_for(state='visible', timeout=5000)
                element.click()
                logging.info(f"Đã tìm thấy và nhấp {element_name} trong iframe 0 cho {username} ở lần thử {attempt}")
                found = True
            except PlaywrightTimeoutError:
                logging.warning(f"Không tìm thấy {element_name} trong iframe 0 cho {username} ở lần thử {attempt}.")

        if not found and attempt < max_attempts:
            logging.info(f"Không tìm thấy {element_name}. Tải lại trang cho {username}...")
            page.reload()
            try:
                page.wait_for_selector('body', timeout=30000)
                logging.info(f"Tải lại trang thành công cho {username}.")
                time.sleep(1)
            except PlaywrightTimeoutError as e:
                logging.error(f"Lỗi khi tải lại trang cho {username}: {e}")
                return False
        elif not found:
            logging.error(f"Không tìm thấy {element_name} sau {max_attempts} lần thử cho {username}.")
            with open(f"log_{element_name.lower()}_{username}.txt", "w", encoding='utf-8') as f:
                f.write(page.content())
            # page.screenshot(path=f"error_{username}_{element_name.lower()}.png")
            return False
    return found

# Hàm chung: Đợi giai đoạn đặt cược
def wait_for_betting_phase(page, username, max_attempts=100, target_countdown=8):
    global table_status
    countdown_selector = 'dt#countdown p'
    betting_start_selector = 'div#gameInfo'
    attempt = 0
    countdown_ready = False

    logging.info(f"Bắt đầu kiểm tra đồng hồ đếm ngược trong iframe 1 cho {username}...")
    while attempt < max_attempts and not countdown_ready and not stop_event.is_set():
        attempt += 1
        start_time = time.time()
        try:
            iframes = page.locator('iframe').all()
            logging.info(f"Số iframe tìm thấy khi kiểm tra countdown cho {username} (lần {attempt}): {len(iframes)}")

            if len(iframes) > 1:
                frame = page.frame_locator('iframe').nth(1)
                frame_handle = page.frames[2] if len(page.frames) > 2 else None
                if not frame_handle:
                    logging.info(f"Không thể lấy frame handle cho iframe 1 của {username}.")
                    time.sleep(0.5)
                    continue

                try:
                    game_info = frame.locator(betting_start_selector)
                    game_info.wait_for(state='visible', timeout=2000)
                    betting_text = game_info.locator('p').text_content(timeout=1000).strip()
                    with table_status_lock:
                        table_status = "Bàn cược đang hoạt động" if betting_text == "Bắt đầu đặt cược" else "Bàn cược ẩn"
                        logging.info(f"Updated table_status: {table_status}")

                    if betting_text != "Bắt đầu đặt cược":
                        logging.info(f"Chưa ở giai đoạn đặt cược ({betting_text}) cho {username}. Thử lại...")
                        time.sleep(1)
                        continue

                    countdown_element = frame.locator(countdown_selector)
                    countdown_element.wait_for(state='visible', timeout=2000)
                    countdown_text = countdown_element.text_content(timeout=1000).strip()
                    logging.info(f"Đồng hồ đếm ngược cho {username}: {countdown_text} (lần thử {attempt})")

                    try:
                        countdown_value = int(countdown_text)
                        if countdown_value >= target_countdown:
                            countdown_ready = True
                            logging.info(f"Đồng hồ đếm ngược đạt yêu cầu ({countdown_value} giây) cho {username}.")
                        else:
                            logging.info(f"Đồng hồ đếm ngược < {target_countdown} giây ({countdown_value} giây). Thử lại.")
                    except ValueError:
                        logging.info(f"Giá trị đồng hồ không phải số: '{countdown_text}'. Thử lại.")
                except PlaywrightTimeoutError as e:
                    logging.info(f"Lỗi khi kiểm tra countdown trong iframe 1 cho {username}: {e} (lần thử {attempt})")
            else:
                logging.info(f"Không đủ iframe (chỉ có {len(iframes)} iframe) cho {username} (lần thử {attempt}).")

            elapsed_time = time.time() - start_time
            sleep_time = max(0, 2 - elapsed_time)
            time.sleep(sleep_time)
        except Exception as e:
            logging.info(f"Lỗi tổng quát khi kiểm tra đồng hồ đếm ngược cho {username}: {e} (lần thử {attempt}).")
            time.sleep(0.5)

    if not countdown_ready:
        logging.error(f"Không thể tìm thấy đồng hồ đếm ngược >= {target_countdown} giây sau {max_attempts} lần thử cho {username}.")
        with countdown_lock:
            countdown_status[username] = False
        with table_status_lock:
            table_status = "Bàn cược ẩn"
            logging.info(f"Updated table_status: {table_status}")
        try:
            with open(f"error_{username}_wait.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            page.screenshot(path=f"error_{username}_wait.png")
            logging.info(f"Đã lưu screenshot vào error_{username}_wait.png")
        except Exception as log_e:
            logging.error(f"Lỗi khi lưu nội dung cho {username}: {log_e}")
        return False

    with countdown_lock:
        countdown_status[username] = True
        logging.info(f"Đã đặt countdown_status[{username}] = True")
        ready_countdowns = sum(1 for status in countdown_status.values() if status)
        logging.info(f"Số countdown sẵn sàng: {ready_countdowns}/{total_accounts}")
        if ready_countdowns == total_accounts:
            if all(countdown_status.values()):
                logging.info("Tất cả tài khoản đã xác nhận countdown. Ra hiệu all_countdowns_ready_event.")
                all_countdowns_ready_event.set()
            else:
                logging.info("Không phải tất cả tài khoản đều xác nhận countdown. Đặt lại để thử lại.")
                for acc in countdown_status:
                    countdown_status[acc] = False
                all_countdowns_ready_event.clear()
                return False
    return True

# Hàm chung: Nhấp vào số cược
def click_by_coordinates(page, username, x, y, bet_number, frame_index=1):
    global table_status
    start_time = time.time()
    try:
        iframes = page.locator('iframe').all()
        logging.info(f"Số iframe tìm thấy cho {username}: {len(iframes)}")
        if len(iframes) < frame_index + 1:
            logging.error(f"Không đủ iframe để đặt cược cho {username} (cần iframe {frame_index}).")
            return False

        frame = page.frame_locator('iframe').nth(frame_index)
        frame_handle = page.frames[frame_index + 1] if len(page.frames) > frame_index + 1 else None
        if not frame_handle:
            logging.error(f"Không thể lấy frame handle cho iframe {frame_index} của {username}.")
            return False
        logging.info(f"Đã chuyển vào iframe {frame_index} cho {username}.")

        try:
            game_info = frame.locator('#gameInfo').text_content(timeout=2000).strip()
            if "Tạm ngừng đặt cược" in game_info:
                logging.info(f"Betting is paused for {username}.")
                return False
        except PlaywrightTimeoutError:
            logging.error(f"Không tìm thấy #gameInfo trong iframe {frame_index} cho {username}.")
            return False

        french_mode_style = frame_handle.evaluate("document.querySelector('#frenchMode')?.style.display || 'none'")
        mode = "french" if french_mode_style != "none" else "classic"
        logging.info(f"Detected mode for {username}: {mode}")

        display_id = f"CS{bet_number}" if mode == "french" else f"S{bet_number}"
        chip_id = f"CS{bet_number}Chip" if mode == "french" else f"S{bet_number}Chip"
        logging.info(f"Targeting display element ID: {display_id} and chip element ID: {chip_id} for number {bet_number} for {username}")

        try:
            display_element = frame.locator(f'#{display_id}')
            display_element.wait_for(state='visible', timeout=10000)
            if not display_element.is_visible():
                logging.error(f"Display element {display_id} is not visible for {username}.")
                return False
        except PlaywrightTimeoutError:
            logging.error(f"Display element {display_id} is not found or not visible for {username}.")
            return False

        frame_handle.evaluate(f"""
            const element = document.querySelector('#{display_id}');
            if (element) {{
                const rect = element.getBoundingClientRect();
                const moveEvent = new MouseEvent('mousemove', {{
                    bubbles: true,
                    clientX: rect.left + 10,
                    clientY: rect.top + 10
                }});
                const downEvent = new MouseEvent('mousedown', {{
                    bubbles: true,
                    clientX: rect.left + 10,
                    clientY: rect.top + 10
                }});
                const upEvent = new MouseEvent('mouseup', {{
                    bubbles: true,
                    clientX: rect.left + 10,
                    clientY: rect.top + 10
                }});
                const clickEvent = new MouseEvent('click', {{
                    bubbles: true,
                    clientX: rect.left + 10,
                    clientY: rect.top + 10
                }});
                element.dispatchEvent(moveEvent);
                setTimeout(() => {{
                    element.dispatchEvent(downEvent);
                    setTimeout(() => {{
                        element.dispatchEvent(upEvent);
                        element.dispatchEvent(clickEvent);
                    }}, 100);
                }}, 200);
            }} else {{
                throw new Error("Không tìm thấy phần tử {display_id} trong iframe!");
            }}
        """)
        logging.info(f"Simulated mousemove, mousedown, mouseup, and click on {display_id} with delays for {username}.")

        time.sleep(1)

        chip_placed = frame.locator(f'#{chip_id}.chips3dTable-in:not(:empty)').count() > 0
        if chip_placed:
            logging.info(f"Chip successfully placed on number {bet_number} for {username}.")
        else:
            logging.error(f"No chip detected on number {bet_number} for {username}.")
            # page.screenshot(path=f"error_{username}_no_chip.png")
            logging.info(f"Đã lưu screenshot vào error_{username}_no_chip.png")
            return False

        try:
            confirm_button = frame.locator('#btnBetConfirm')
            confirm_button.wait_for(state='visible', timeout=5000)
            class_attr = confirm_button.evaluate("el => el.className") or ""
            if "noWork" in class_attr:
                logging.error(f"Confirm button is not clickable (noWork) for {username}.")
                return False
            frame_handle.evaluate("document.querySelector('#btnBetConfirm').click()")
            logging.info(f"Clicked confirm button for {username}.")
        except PlaywrightTimeoutError:
            logging.error(f"No confirm button found or not clickable for {username}.")
            return False

        logging.info(f"Thời gian xử lý click_by_coordinates cho {username}: {time.time() - start_time:.2f}s")
        with bet_status_lock:
            bet_status[username] = True  # Đánh dấu đặt cược thành công
        return True

    except Exception as e:
        logging.error(f"Lỗi khi nhấp phần tử cho {username}: {e}")
        try:
            if frame_handle:
                with open(f"error_{username}_iframe.html", "w", encoding="utf-8") as f:
                    iframe_content = frame_handle.evaluate("document.documentElement.outerHTML")
                    f.write(iframe_content)
                logging.info(f"Đã lưu nội dung iframe vào error_{username}_iframe.html")
            with open(f"error_{username}_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            page.screenshot(path=f"error_{username}_click.png")
            logging.info(f"Đã lưu screenshot vào error_{username}_click.png")
        except Exception as log_e:
            logging.error(f"Lỗi khi lưu nội dung cho {username}: {log_e}")
        with bet_status_lock:
            bet_status[username] = False
        return False

def set_total_accounts(count, credentials):
    global total_accounts
    total_accounts = count
    logging.info(f"Set total_accounts: {total_accounts}")
    with countdown_lock:
        countdown_status.clear()
        for username, _ in credentials:
            countdown_status[username] = False
        logging.info(f"Initialized countdown_status: {countdown_status}")
    with autorou_lock:
        autorou_status.clear()
        for username, _ in credentials:
            autorou_status[username] = False
        logging.info(f"Initialized autorou_status: {autorou_status}")
    with account_lock:
        account_status.clear()
        for username, _ in credentials:
            account_status[username] = False
        logging.info(f"Initialized account_status: {account_status}")
    with bet_status_lock:
        bet_status.clear()
        for username, _ in credentials:
            bet_status[username] = False
        logging.info(f"Initialized bet_status: {bet_status}")
    all_autorou_clicked_event.clear()
    all_chips_selected_event.clear()
    all_countdowns_ready_event.clear()
    logging.info("Cleared all synchronization events.")

def check_all_accounts_ready(username):
    global completed_accounts
    logging.info(f"Kiểm tra trạng thái tài khoản: {account_status}")
    logging.info(f"Tổng số tài khoản: {total_accounts}")

    with account_lock:
        completed_accounts += 1
        logging.info(f"Tài khoản đã hoàn thành: {completed_accounts}/{total_accounts}")

        if completed_accounts == total_accounts:
            ready_accounts = sum(1 for status in account_status.values() if status)
            autorou_accounts = sum(1 for status in autorou_status.values() if status)
            bet_accounts = sum(1 for status in bet_status.values() if status)
            logging.info(f"Số tài khoản sẵn sàng: {ready_accounts}/{total_accounts}")
            logging.info(f"Số tài khoản nhấp AutoRou: {autorou_accounts}/{total_accounts}")
            logging.info(f"Số tài khoản đặt cược: {bet_accounts}/{total_accounts}")
            for acc, status in account_status.items():
                logging.info(f"Trạng thái {acc}: {'Sẵn sàng' if status else 'Chưa sẵn sàng'}")
            for acc, status in autorou_status.items():
                logging.info(f"Trạng thái AutoRou {acc}: {'Đã nhấp' if status else 'Chưa nhấp'}")
            for acc, status in bet_status.items():
                logging.info(f"Trạng thái cược {acc}: {'Đã đặt cược' if status else 'Chưa đặt cược'}")

            if ready_accounts == total_accounts and all(account_status.values()) and all(autorou_status.values()) and all(bet_status.values()):
                logging.info("Tất cả tài khoản đã hoàn thành hành động thành công. Ra hiệu all_chips_selected_event.")
                all_chips_selected_event.set()
                all_autorou_clicked_event.set()
                all_countdowns_ready_event.set()
            else:
                logging.info(f"Không phải tất cả tài khoản đều hoàn thành thành công ({ready_accounts}/{total_accounts} sẵn sàng). Đặt lại trạng thái.")
                with account_lock:
                    for acc in account_status:
                        account_status[acc] = False
                with autorou_lock:
                    for acc in autorou_status:
                        autorou_status[acc] = False
                with countdown_lock:
                    for acc in countdown_status:
                        countdown_status[acc] = False
                with bet_status_lock:
                    for acc in bet_status:
                        bet_status[acc] = False
                completed_accounts = 0
                all_chips_selected_event.clear()
                all_countdowns_ready_event.clear()
                all_autorou_clicked_event.clear()
                logging.info(f"Đã đặt lại trạng thái cho tất cả tài khoản để thử lại.")

# Hàm chung: Lấy số dư với tối đa 3 lần thử
def get_balance(page, username, max_retries=3):
    balance = None
    for attempt in range(max_retries):
        try:
            page.wait_for_selector('span[ng-bind="$ctrl.userInfo.balance | currencyDefault"]', timeout=15000)
            balance_text = page.query_selector('span[ng-bind="$ctrl.userInfo.balance | currencyDefault"]').inner_text().replace(',', '')
            balance = float(balance_text)
            logging.info(f"Lấy số dư thành công cho {username}: {balance}")
            return balance
        except Exception as e:
            logging.warning(f"Thử {attempt + 1}/{max_retries} lấy số dư thất bại cho {username}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)  # Chờ 2 giây trước khi thử lại
    logging.error(f"Không thể lấy số dư cho {username} sau {max_retries} lần thử.")
    return None

# Hàm chung: Ghi vào file CSV
def log_to_csv(username, bet_number=None, balance=None, round_number=None):
    csv_file = Path('taikhoancuoc.csv')
    with csv_lock:
        try:
            # Đọc dữ liệu hiện có từ file CSV
            existing_data = []
            row_index = None
            if csv_file.exists():
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    existing_data = list(reader)
                    # Tìm dòng tương ứng với username
                    for idx, row in enumerate(existing_data[1:]):  # Bỏ qua header
                        if row[0] == username:
                            row_index = idx + 1  # +1 vì header chiếm dòng đầu
                            break

            if bet_number is not None and balance is not None and round_number is not None:
                # Cập nhật thông tin cược vào dòng tương ứng
                if row_index is not None:
                    existing_data[row_index] = [
                        username,
                        str(bet_number),
                        str(balance) if balance is not None else 'N/A',
                        str(round_number),
                        time.strftime('%Y-%m-%d %H:%M:%S')
                    ]
                    # Ghi lại toàn bộ dữ liệu vào file CSV
                    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerows(existing_data)
                    logging.info(
                        f"Đã cập nhật dữ liệu vào CSV cho {username}: Số cược {bet_number}, Số dư {balance}, Vòng {round_number}")
                else:
                    logging.error(f"Không tìm thấy dòng tương ứng cho {username} trong file CSV để cập nhật.")
            else:
                logging.info(f"Không có thông tin cược để cập nhật cho {username}.")
        except Exception as e:
            logging.error(f"Lỗi khi xử lý CSV cho {username}: {e}")

# Hàm Bacarat: Thêm logic rút tiền và ghi CSV
def Bacarat(page, link, username, password, mode, chip, account_index):
    max_rounds = 5
    current_round = 0

    while current_round < max_rounds and not stop_event.is_set():
        current_round += 1
        logging.info(f"Bắt đầu vòng cược {current_round}/{max_rounds} cho {username}")

        try:
            # Reset states for this account at the start of each betting round
            with account_lock:
                account_status[username] = False
                logging.info(f"Reset account_status[{username}] = False. Trạng thái: {account_status}")
            with autorou_lock:
                autorou_status[username] = False
                logging.info(f"Reset autorou_status[{username}] = False. Trạng thái: {autorou_status}")
            with countdown_lock:
                countdown_status[username] = False
                logging.info(f"Reset countdown_status[{username}] = False. Trạng thái: {countdown_status}")
            with bet_status_lock:
                bet_status[username] = False
                logging.info(f"Reset bet_status[{username}] = False. Trạng thái: {bet_status}")

            page.wait_for_selector('body', timeout=30000)
            logging.info(f"Trang đã tải cho {username}.")

            # Handle modal
            modal_closed, _ = handle_modal(page, username)
            if not modal_closed:
                logging.info(f"Không thể đóng modal cho {username}. Tiếp tục tìm Roulette.")

            # Click Roulette
            roulette_selector = '//button[contains(@class, "relative w-full") and .//img[contains(@src, "group07.png")] and .//div[contains(text(), "Roulette")]] | //div[contains(@class, "flex") and contains(@class, "items-center") and .//img[contains(@src, "group07.png")] and .//div[contains(text(), "Roulette")]]'
            if not click_game_element(page, username, roulette_selector, "Roulette"):
                logging.error(f"Không thể tìm thấy Roulette sau các lần thử cho {username}. Thoát.")
                check_all_accounts_ready(username)
                return

            logging.info(f"Tải lại trang sau khi nhấp Roulette cho {username}...")
            page.reload()
            page.wait_for_selector('body', timeout=30000)
            logging.info(f"Tải lại trang thành công cho {username}.")

            time.sleep(1)
            page.reload()
            iframes = page.locator('iframe').all()
            logging.info(f"Số iframe sau khi nhấp Roulette cho {username}: {len(iframes)}")

            # Click AutoRou if not already clicked
            all_autorou_clicked_event.clear()
            with autorou_lock:
                if not autorou_status.get(username, False):
                    autorou_selector = '//div[@data-v-d51c9253 and contains(@class, "flex items-center") and .//span[contains(text(), "AutoRou")]]'
                    if not click_game_element(page, username, autorou_selector, "AutoRou"):
                        logging.error(f"Không thể nhấp AutoRou cho {username}. Thoát.")
                        autorou_status[username] = False
                        check_all_accounts_ready(username)
                        return

                    autorou_status[username] = True
                    logging.info(f"Đã nhấp AutoRou thành công. Cập nhật autorou_status[{username}] = True")
                    autorou_ready = sum(1 for status in autorou_status.values() if status)
                    logging.info(f"Số tài khoản nhấp AutoRou: {autorou_ready}/{total_accounts}")
                    if autorou_ready == total_accounts and all(autorou_status.values()):
                        logging.info("Tất cả tài khoản đã nhấp AutoRou. Ra hiệu all_autorou_clicked_event.")
                        all_autorou_clicked_event.set()
                    else:
                        logging.info(f"Chưa đủ tài khoản nhấp AutoRou ({autorou_ready}/{total_accounts}). Đợi...")
                else:
                    logging.info(f"Tài khoản {username} đã nhấp AutoRou trước đó, bỏ qua nhấp lại.")

            logging.info(f"Đợi tất cả tài khoản nhấp AutoRou cho {username}...")
            all_autorou_clicked_event.wait(timeout=300)
            if not all_autorou_clicked_event.is_set():
                logging.warning(f"Không phải tất cả tài khoản đều nhấp AutoRou. Đợi vòng cược tiếp theo cho {username}.")
                with account_lock:
                    account_status[username] = False
                with autorou_lock:
                    autorou_status[username] = False
                with countdown_lock:
                    countdown_status[username] = False
                all_autorou_clicked_event.clear()
                all_chips_selected_event.clear()
                all_countdowns_ready_event.clear()
                check_all_accounts_ready(username)
                return

            # Select bet range and chip
            all_chips_selected_event.clear()
            with account_lock:
                if not account_status.get(username, False):
                    max_attempts = 5
                    attempt = 0
                    chip_found = False

                    logging.info(f"Bắt đầu chọn mức cược và chip {chip} trong iframe 1 cho {username}...")
                    while attempt < max_attempts and not chip_found and not stop_event.is_set():
                        attempt += 1
                        logging.info(f"Thử {attempt} chọn mức cược và chip {chip} cho {username}...")
                        try:
                            iframes = page.locator('iframe').all()
                            logging.info(f"Số iframe tìm thấy khi chọn mức cược và chip {chip} cho {username}: {len(iframes)}")

                            if len(iframes) > 1:
                                frame = page.frame_locator('iframe').nth(1)
                                frame_handle = page.frames[2] if len(page.frames) > 2 else None
                                if not frame_handle:
                                    logging.error(f"Không thể lấy frame handle cho iframe 1 của {username}.")
                                    time.sleep(0.5)
                                    continue

                                # Click betRange
                                try:
                                    frame.locator('#betRange').wait_for(state='visible', timeout=5000)
                                    class_attr = frame.locator('#betRange').evaluate("el => el.className") or ""
                                    if "noWork" in class_attr:
                                        logging.error(f"Nút betRange không thể nhấp (noWork) cho {username}.")
                                        time.sleep(0.5)
                                        continue
                                    frame_handle.evaluate("""
                                        const element = document.querySelector('#betRange');
                                        if (element) {
                                            const clickEvent = new MouseEvent('click', {
                                                bubbles: true,
                                                cancelable: true
                                            });
                                            element.dispatchEvent(clickEvent);
                                        } else {
                                            throw new Error('Không tìm thấy betRange trong iframe.');
                                        }
                                    """)
                                    logging.info(f"Đã nhấp vào nút betRange (10 - 500) cho {username}.")
                                except Exception as e:
                                    logging.error(f"Không thể nhấp betRange cho {username}: {e}")
                                    time.sleep(0.5)
                                    continue

                                # Click limitRange_131105
                                try:
                                    frame.locator('#limitRange_131105').wait_for(state='visible', timeout=5000)
                                    frame_handle.evaluate("""
                                        const element = document.querySelector('#limitRange_131105');
                                        if (element) {
                                            const clickEvent = new MouseEvent('click', {
                                                bubbles: true,
                                                cancelable: true
                                            });
                                            element.dispatchEvent(clickEvent);
                                        } else {
                                            throw new Error('Không tìm thấy limitRange_131105 trong iframe.');
                                        }
                                    """)
                                    logging.info(f"Đã nhấp vào mức cược 20-1K (limitRange_131105) cho {username}.")
                                except Exception as e:
                                    logging.error(f"Không thể nhấp limitRange_131105 cho {username}: {e}")
                                    time.sleep(0.5)
                                    continue

                                # Wait and click limitSubmit
                                time.sleep(0.5)
                                try:
                                    frame.locator('#limitSubmit').wait_for(state='visible', timeout=5000)
                                    frame_handle.evaluate("""
                                        const element = document.querySelector('#limitSubmit');
                                        if (element) {
                                            const clickEvent = new MouseEvent('click', {
                                                bubbles: true,
                                                cancelable: true
                                            });
                                            element.dispatchEvent(clickEvent);
                                        } else {
                                            throw new Error('Không tìm thấy limitSubmit trong iframe.');
                                        }
                                    """)
                                    logging.info(f"Đã nhấp vào nút xác nhận (limitSubmit) cho {username}.")
                                except Exception as e:
                                    logging.error(f"Không thể nhấp limitSubmit cho {username}: {e}")
                                    time.sleep(0.5)
                                    continue

                                # Click chip
                                chip_value = {"1": "10", "2": "20", "5": "50"}.get(chip, "10")
                                chip_class = f"chips3d-{chip_value}"
                                chip_selector = f'//li[contains(@class, "{chip_class}") and .//p[text()="{chip_value}"]]'
                                try:
                                    frame.locator('#chips').wait_for(timeout=30000)
                                    chip_element = frame.locator(chip_selector)
                                    chip_element.click()
                                    frame.locator(f'//li[contains(@class, "{chip_class}") and contains(@class, "now")]').wait_for(timeout=5000)
                                    logging.info(f"Đã nhấp và chọn chip {chip_value} trong iframe 1 cho {username}")
                                    chip_found = True
                                except Exception as e:
                                    logging.error(f"Lỗi khi tìm hoặc nhấp chip {chip_value} trong iframe 1 (thử {attempt}) cho {username}: {e}")

                            else:
                                logging.warning(f"Không đủ iframe (chỉ có {len(iframes)} iframe) cho {username}.")

                            if not chip_found and attempt < max_attempts:
                                logging.info(f"Không thể chọn mức cược hoặc chip {chip_value}. Tải lại trang cho {username}...")
                                page.reload()
                                page.wait_for_selector('body', timeout=30000)
                                logging.info(f"Tải lại trang thành công cho {username}.")
                                autorou_selector = '//div[@data-v-d51c9253 and contains(@class, "flex items-center") and .//span[contains(text(), "AutoRou")]]'
                                if not click_game_element(page, username, autorou_selector, "AutoRou"):
                                    logging.error(f"Không thể nhấp AutoRou sau khi tải lại cho {username}. Thoát.")
                                    break
                                with autorou_lock:
                                    autorou_status[username] = True
                                    autorou_ready = sum(1 for status in autorou_status.values() if status)
                                    if autorou_ready == total_accounts and all(autorou_status.values()):
                                        logging.info("Tất cả tài khoản đã nhấp AutoRou sau khi tải lại. Ra hiệu all_autorou_clicked_event.")
                                        all_autorou_clicked_event.set()
                                all_autorou_clicked_event.wait(timeout=300)
                                time.sleep(1)
                            elif not chip_found:
                                logging.error(f"Không thể chọn mức cược hoặc chip {chip_value} sau {max_attempts} lần thử cho {username}.")
                                break

                        except Exception as e:
                            logging.error(f"Lỗi tổng quát trong lần thử {attempt} cho {username}: {e}")
                            if attempt < max_attempts:
                                page.reload()
                                page.wait_for_selector('body', timeout=30000)
                                logging.info(f"Tải lại trang thành công cho {username}.")
                                autorou_selector = '//div[@data-v-d51c9253 and contains(@class, "flex items-center") and .//span[contains(text(), "AutoRou")]]'
                                if not click_game_element(page, username, autorou_selector, "AutoRou"):
                                    logging.error(f"Không thể nhấp AutoRou sau khi tải lại cho {username}. Thoát.")
                                    break
                                with autorou_lock:
                                    autorou_status[username] = True
                                    autorou_ready = sum(1 for status in autorou_status.values() if status)
                                    if autorou_ready == total_accounts and all(autorou_status.values()):
                                        logging.info("Tất cả tài khoản đã nhấp AutoRou sau khi tải lại. Ra hiệu all_autorou_clicked_event.")
                                        all_autorou_clicked_event.set()
                                all_autorou_clicked_event.wait(timeout=300)
                                time.sleep(1)
                            else:
                                logging.error(f"Không thể chọn mức cược hoặc chip {chip_value} sau {max_attempts} lần thử cho {username}.")
                                break

                    if chip_found:
                        account_status[username] = True
                        logging.info(f"Trạng thái tài khoản {username}: Đã chọn mức cược và chip {chip_value}. Trạng thái: {account_status}")
                        chip_ready = sum(1 for status in account_status.values() if status)
                        if chip_ready == total_accounts and all(account_status.values()):
                            logging.info("Tất cả tài khoản đã chọn mức cược và chip. Ra hiệu all_chips_selected_event.")
                            all_chips_selected_event.set()
                    else:
                        logging.error(f"Không thể tìm hoặc nhấp mức cược hoặc chip {chip_value} trong iframe 1 cho {username} sau tất cả các lần thử.")
                        account_status[username] = False
                        with autorou_lock:
                            autorou_status[username] = False
                        check_all_accounts_ready(username)
                        return
                else:
                    logging.info(f"Tài khoản {username} đã chọn mức cược và chip trước đó, bỏ qua chọn lại.")

            logging.info(f"Đợi tất cả tài khoản chọn mức cược và chip cho {username}...")
            all_chips_selected_event.wait(timeout=300)
            if not all_chips_selected_event.is_set():
                logging.warning(f"Không phải tất cả tài khoản đều chọn mức cược và chip. Đợi vòng cược tiếp theo cho {username}.")
                with account_lock:
                    account_status[username] = False
                with autorou_lock:
                    autorou_status[username] = False
                with countdown_lock:
                    countdown_status[username] = False
                all_autorou_clicked_event.clear()
                all_chips_selected_event.clear()
                all_countdowns_ready_event.clear()
                check_all_accounts_ready(username)
                return

            logging.info(f"Hoàn thành đợi mức cược và chip cho {username}. Tiếp tục kiểm tra countdown...")
            if not wait_for_betting_phase(page, username):
                logging.error(f"Không thể vào giai đoạn đặt cược cho {username}.")
                with account_lock:
                    account_status[username] = False
                with autorou_lock:
                    autorou_status[username] = False
                with countdown_lock:
                    countdown_status[username] = False
                all_autorou_clicked_event.clear()
                all_chips_selected_event.clear()
                all_countdowns_ready_event.clear()
                check_all_accounts_ready(username)
                return

            logging.info(f"Đợi tất cả tài khoản xác nhận countdown cho {username}...")
            all_countdowns_ready_event.wait(timeout=300)
            if not all_countdowns_ready_event.is_set():
                logging.warning(f"Không phải tất cả tài khoản đều xác nhận countdown. Đợi vòng cược tiếp theo cho {username}.")
                with account_lock:
                    account_status[username] = False
                with autorou_lock:
                    autorou_status[username] = False
                with countdown_lock:
                    countdown_status[username] = False
                all_autorou_clicked_event.clear()
                all_chips_selected_event.clear()
                all_countdowns_ready_event.clear()
                check_all_accounts_ready(username)
                return

            if not account_status.get(username, False):
                logging.warning(f"Tài khoản {username} không sẵn sàng (mức cược hoặc chip không được chọn). Bỏ qua đặt cược.")
                check_all_accounts_ready(username)
                return
            if not countdown_status.get(username, False):
                logging.warning(f"Tài khoản {username} không sẵn sàng (countdown không được xác nhận). Bỏ qua đặt cược.")
                check_all_accounts_ready(username)
                return

            iframes = page.locator('iframe').all()
            if len(iframes) > 1:
                logging.info(f"Chuyển sang iframe 1 để đặt cược cho {username}.")
            else:
                logging.error(f"Không tìm thấy iframe hợp lệ để đặt cược cho {username}.")
                with account_lock:
                    account_status[username] = False
                with autorou_lock:
                    autorou_status[username] = False
                with bet_status_lock:
                    bet_status[username] = False
                check_all_accounts_ready(username)
                return

            bet_number = (account_index - 1) % 37
            logging.info(f"Đặt cược vào số {bet_number} cho {username} (account_index {account_index}).")

            if click_by_coordinates(page, username, 0, 0, bet_number):
                logging.info(f"Đặt cược thành công vào số {bet_number} cho {username}.")
                with bet_status_lock:
                    bet_status[username] = True
                with account_lock:
                    account_status[username] = True
                    logging.info(f"Trạng thái tài khoản {username}: Đã đặt cược. Trạng thái: {account_status}")


                time.sleep(60)
                # Navigate to WithdrawApplication
                base_link = link.split('/Account/LoginToSupplier')[0]
                withdraw_url = f"{base_link}/WithdrawApplication"
                try:
                    logging.info(f"Điều hướng đến {withdraw_url} cho {username}")
                    page.goto(withdraw_url, timeout=60000)
                    page.wait_for_load_state('networkidle', timeout=60000)
                    logging.info(f"Đã tải thành công {withdraw_url} cho {username}")
                except Exception as e:
                    logging.error(f"Lỗi khi điều hướng đến {withdraw_url} cho {username}: {e}")
                    check_all_accounts_ready(username)
                    return

                # Nhấn Esc nếu thấy "Tin tức mới nhất"
                try:
                    page.wait_for_selector('h2[translate="Shared_NewsInfo_Title"].ng-scope', timeout=50000)
                    page.keyboard.press("Escape")
                    time.sleep(1)
                    page.keyboard.press("Escape")
                    time.sleep(1)
                    page.keyboard.press("Escape")
                    logging.info(f"Đã nhấn Esc để đóng popup 'Tin tức mới nhất' cho {username}")
                    time.sleep(1)
                except PlaywrightTimeoutError:
                    logging.info(f"Không tìm thấy popup 'Tin tức mới nhất' cho {username}")

                # Nhấp nút "Cập nhật" 4-5 lần
                try:
                    page.wait_for_selector('button.btn.btn-link[title="Cập nhật"]', timeout=30000)
                    click_count = random.randint(4, 5)
                    logging.info(f"Nhấp nút 'Cập nhật' {click_count} lần cho {username}")
                    for i in range(click_count):
                        page.click('button.btn.btn-link[title="Cập nhật"]')
                        logging.info(f"Nhấp 'Cập nhật' lần {i+1}/{click_count} cho {username}")
                        time.sleep(3)
                except PlaywrightTimeoutError:
                    logging.info(f"Không tìm thấy nút 'Cập nhật' cho {username}")

                # Lấy số dư
                balance = get_balance(page, username)
                # Ghi vào CSV
                with round_lock:
                    log_to_csv(username, bet_number, balance, current_round)
                check_all_accounts_ready(username)
                break
            else:
                logging.error(f"Không thể đặt cược vào số {bet_number} cho {username}.")
                with account_lock:
                    account_status[username] = False
                with autorou_lock:
                    autorou_status[username] = False
                with bet_status_lock:
                    bet_status[username] = False
                check_all_accounts_ready(username)
                return

        except Exception as e:
            logging.error(f"Lỗi nghiêm trọng trong Bacarat cho {username}: {traceback.format_exc()}")
            with account_lock:
                account_status[username] = False
            with autorou_lock:
                autorou_status[username] = False
            with countdown_lock:
                countdown_status[username] = False
            with bet_status_lock:
                bet_status[username] = False
            check_all_accounts_ready(username)
            return

    if current_round >= max_rounds:
        logging.info(f"Đã đạt số vòng cược tối đa ({max_rounds}) cho {username}. Dừng lại.")
        check_all_accounts_ready(username)

def login_with_playwright(link, username, password, proxy, user_agent, proxy_handler, mode, chip,
                          browser_width, browser_height, x_pos, y_pos, account_index, headless):
    max_retries = 5
    retry_count = 0
    bet_success = False

    while retry_count < max_retries and not stop_event.is_set():
        context = None
        browser = None
        try:
            logging.info(f"Thử lần {retry_count + 1}/{max_retries} mở trình duyệt cho {username}...")
            print(f"Thử lần {retry_count + 1}/{max_retries} mở trình duyệt cho {username}")
            with sync_playwright() as p:
                # Sử dụng headless từ tham số
                browser = p.chromium.launch(headless=headless, args=['--disable-gpu', '--no-sandbox'])
                proxy_dict = {"server": proxy}
                context = browser.new_context(
                    user_agent=user_agent,
                    proxy=proxy_dict,
                    viewport={"width": browser_width, "height": browser_height},
                    no_viewport=False
                )
                context.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
                page = context.new_page()

                with file_lock:
                    if context not in active_browsers:
                        active_browsers.append(context)

                page.evaluate(f"document.title = 'Chrome_{username}'")

                logging.info(f"Tải trang {link} cho {username}...")
                print(f"Tải trang: {username}")
                try:
                    response = page.goto(link, timeout=60000)
                    if stop_event.is_set():
                        logging.info(f"Dừng login_with_playwright cho {username} do sự kiện dừng.")
                        print(f"Dừng login_with_playwright: {username}")
                        return None
                    if response and response.status == 200:
                        logging.info(f"Đã tải thành công trang {link} cho {username} (mã trạng thái: {response.status})")
                        print(f"Đã tải trang thành công: {username}")
                    else:
                        logging.error(f"Lỗi khi tải trang {link} cho {username}: Mã trạng thái {response.status if response else 'không có phản hồi'}")
                        print(f"Lỗi tải trang: {username}")
                        raise Exception("Không thể tải trang")
                except Exception as e:
                    logging.error(f"Lỗi khi gọi page.goto cho {username}: {traceback.format_exc()}")
                    print(f"Lỗi page.goto: {username}")
                    raise

                try:
                    page.wait_for_selector('input[ng-model="$ctrl.user.account.value"]', timeout=60000)
                    logging.info(f"Đã tìm thấy form đăng nhập cho {username}")
                    print(f"Tìm thấy form đăng nhập: {username}")
                except PlaywrightTimeoutError as e:
                    logging.info(f"Không tìm thấy trường tài khoản cho {username}. Coi như đăng nhập thành công.")
                    print(f"Không tìm thấy trường tài khoản: {username}. Đăng nhập thành công.")
                    if mode == "BACARAT":
                        logging.info(f"Gọi Bacarat cho {username} với account_index={account_index}")
                        print(f"Gọi Bacarat: {username}")
                        time.sleep(3)
                        Bacarat(page, link, username, password, mode, chip, account_index)
                        with bet_status_lock:
                            bet_success = bet_status.get(username, False)
                        return None

                try:
                    page.wait_for_selector('input[ng-model="$ctrl.user.password.value"]', timeout=10000)
                    logging.info(f"Đã tìm thấy trường mật khẩu cho {username}")
                    print(f"Tìm thấy trường mật khẩu: {username}")
                except PlaywrightTimeoutError as e:
                    logging.info(f"Không tìm thấy trường mật khẩu cho {username}. Coi như đăng nhập thành công.")
                    print(f"Không tìm thấy trường mật khẩu: {username}. Đăng nhập thành công.")
                    if mode == "BACARAT":
                        logging.info(f"Gọi Bacarat cho {username} với account_index={account_index}")
                        print(f"Gọi Bacarat: {username}")
                        time.sleep(3)
                        Bacarat(page, link, username, password, mode, chip, account_index)
                        with bet_status_lock:
                            bet_success = bet_success or bet_status.get(username, False)
                        return None

                logging.info(f"Bắt đầu đăng nhập cho {username}...")
                time.sleep(5)
                print(f"Bắt đầu đăng nhập: {username}")
                page.locator('input[ng-model="$ctrl.user.account.value"]').fill(username)
                page.locator('input[ng-model="$ctrl.user.password.value"]').fill(password)

                max_attempts = 20
                attempt = 0
                login_success = False

                while attempt < max_attempts and not login_success and not stop_event.is_set():
                    attempt += 1
                    captcha_code = handle_captcha(page)
                    logging.info(f"Mã captcha cho {username}: {captcha_code}")
                    print(f"Mã captcha: {captcha_code} cho {username}")
                    if not captcha_code:
                        continue

                    page.locator('button:has-text("ĐĂNG NHẬP")').click()
                    logging.info(f"Đã nhấp nút ĐĂNG NHẬP cho {username}")
                    print(f"Nhấp nút ĐĂNG NHẬP: {username}")

                    try:
                        page.wait_for_selector('div[bind-html-compile="$ctrl.content"]', timeout=10000)
                        confirm_button = page.locator('button.btn.btn-primary.ng-scope')
                        confirm_button.click()
                        time.sleep(0.5)
                        continue
                    except:
                        login_success = True

                if login_success:
                    logging.info(f"Đăng nhập thành công cho {username}.")
                    print(f"Đăng nhập thành công: {username}")
                    if mode == "BACARAT":
                        logging.info(f"Gọi Bacarat cho {username} với account_index={account_index}")
                        print(f"Gọi Bacarat: {username}")
                        time.sleep(3)
                        Bacarat(page, link, username, password, mode, chip, account_index)
                        with bet_status_lock:
                            if bet_status.get(username, False):  # Kiểm tra nếu đặt cược thành công
                                logging.info(
                                    f"Đặt cược thành công cho {username}. ")
                                print(f"Đặt cược thành công: {username}. ")
                                time.sleep(0.5)  # Thêm timeout 3 giây
                                bet_success = True
                        return None
                else:
                    logging.error(f"Đăng nhập thất bại cho {username} sau {max_attempts} lần thử.")
                    print(f"Đăng nhập thất bại: {username}")
                    with account_lock:
                        account_status[username] = False
                    with autorou_lock:
                        autorou_status[username] = False
                    with countdown_lock:
                        countdown_status[username] = False
                    with bet_status_lock:
                        bet_status[username] = False
                    return None

        except Exception as e:
            logging.error(f"Lỗi trong login_with_playwright cho {username}: {traceback.format_exc()}")
            print(f"Lỗi login_with_playwright: {username}")
            if bet_success:
                logging.info(f"Đặt cược đã thành công cho {username}. Bỏ qua thử lại do lỗi context/browser.")
                print(f"Đặt cược thành công, không thử lại: {username}")
                with account_lock:
                    account_status[username] = True
                return None
            else:
                retry_count += 1
                if retry_count < max_retries:
                    logging.info(f"Thử lại đăng nhập cho {username} sau 10 giây (lần thử {retry_count + 1}/{max_retries})...")
                    print(f"Thử lại đăng nhập cho {username} (lần thử {retry_count + 1}/{max_retries})")
                    time.sleep(10)
                    try:
                        for proc in psutil.process_iter(['name', 'cmdline']):
                            if proc.info['name'] in ['chrome.exe', 'chromium', 'msedge']:
                                cmdline = ' '.join(proc.info.get('cmdline', [])).lower()
                                if 'playwright' in cmdline and f'chrome_{username.lower()}' in cmdline:
                                    proc.terminate()
                                    proc.wait(timeout=3)
                                    logging.info(f"Đã dừng tiến trình Playwright: {proc.info['name']} (PID: {proc.pid}) cho {username}")
                    except Exception as proc_e:
                        logging.error(f"Lỗi khi dừng tiến trình Playwright cho {username}: {proc_e}")
                    with file_lock:
                        if context in active_browsers:
                            active_browsers.remove(context)
                            logging.info(f"Đã xóa context khỏi active_browsers trước khi thử lại cho {username}")
                    with account_lock:
                        account_status[username] = False
                    with autorou_lock:
                        autorou_status[username] = False
                    with countdown_lock:
                        countdown_status[username] = False
                    with bet_status_lock:
                        bet_status[username] = False
                    continue
                else:
                    logging.error(f"Đã vượt quá số lần thử tối đa ({max_retries}) cho {username}. Bỏ qua.")
                    print(f"Đã vượt quá số lần thử tối đa cho {username}")
                    with account_lock:
                        account_status[username] = False
                    with autorou_lock:
                        autorou_status[username] = False
                    with countdown_lock:
                        countdown_status[username] = False
                    with bet_status_lock:
                        bet_status[username] = False
                    with file_lock:
                        if context in active_browsers:
                            active_browsers.remove(context)
                            logging.info(f"Đã xóa context khỏi active_browsers do vượt quá số lần thử cho {username}")
                    return None

        finally:
            try:
                if context:
                    try:
                        if hasattr(context, '_impl_obj') and context._impl_obj.is_connected():
                            context.close()
                            logging.info(f"Đã đóng browser context thành công cho {username}.")
                            print(f"Đã đóng context: {username}")
                        else:
                            logging.warning(
                                f"Context đã bị đóng hoặc không hợp lệ cho {username}. Bỏ qua đóng context.")
                            print(f"Context đã đóng: {username}")
                        with file_lock:
                            if context in active_browsers:
                                active_browsers.remove(context)
                                logging.info(f"Đã xóa context khỏi active_browsers cho {username}")
                    except Exception as e:
                        logging.error(f"Lỗi đóng context: {username}: {traceback.format_exc()}")
                        print(f"Lỗi đóng context: {username}")
                        with file_lock:
                            if context in active_browsers:
                                active_browsers.remove(context)
                                logging.info(f"Đã xóa context khỏi active_browsers do lỗi đóng context cho {username}")
                        if bet_success:
                            logging.info(f"Đặt cược đã thành công, bỏ qua lỗi đóng context cho {username}.")
                            print(f"Bỏ qua lỗi đóng context vì đặt cược thành công: {username}")
                            with account_lock:
                                account_status[username] = True
                            return None
                        elif retry_count < max_retries:
                            logging.info(f"Lỗi đóng context nhưng đặt cược chưa thành công cho {username}. Thử lại lần {retry_count + 1}/{max_retries}...")
                            print(f"Lỗi đóng context, thử lại lần {retry_count + 1}/{max_retries} cho {username}")
                            retry_count += 1
                            time.sleep(10)
                            try:
                                for proc in psutil.process_iter(['name', 'cmdline']):
                                    if proc.info['name'] in ['chrome.exe', 'chromium', 'msedge']:
                                        cmdline = ' '.join(proc.info.get('cmdline', [])).lower()
                                        if 'playwright' in cmdline and f'chrome_{username.lower()}' in cmdline:
                                            proc.terminate()
                                            proc.wait(timeout=3)
                                            logging.info(f"Đã dừng tiến trình Playwright: {proc.info['name']} (PID: {proc.pid}) cho {username}")
                            except Exception as proc_e:
                                logging.error(f"Lỗi khi dừng tiến trình Playwright cho {username}: {proc_e}")
                            with account_lock:
                                account_status[username] = False
                            with autorou_lock:
                                autorou_status[username] = False
                            with countdown_lock:
                                countdown_status[username] = False
                            with bet_status_lock:
                                bet_status[username] = False
                            continue
                        else:
                            logging.error(f"Lỗi đóng context và đã vượt quá số lần thử tối đa ({max_retries}) cho {username}.")
                            print(f"Lỗi đóng context và vượt quá số lần thử tối đa cho {username}")
                            with account_lock:
                                account_status[username] = False
                            with autorou_lock:
                                autorou_status[username] = False
                            with countdown_lock:
                                countdown_status[username] = False
                            with bet_status_lock:
                                bet_status[username] = False
                            return None
                if browser:
                    try:
                        browser.close()
                        logging.info(f"Đã đóng browser trong finally cho {username}.")
                        print(f"Đã đóng browser: {username}")
                    except Exception as e:
                        logging.error(f"Lỗi đóng browser: {username}: {traceback.format_exc()}")
                        print(f"Lỗi đóng browser: {username}")
                        if bet_success:
                            logging.info(f"Đặt cược đã thành công, bỏ qua lỗi đóng browser cho {username}.")
                            print(f"Bỏ qua lỗi đóng browser vì đặt cược thành công: {username}")
                            with account_lock:
                                account_status[username] = True
                            return None
            except Exception as e:
                logging.error(f"Lỗi tổng quát trong khối finally cho {username}: {traceback.format_exc()}")
                print(f"Lỗi tổng quát trong finally cho {username}")
                with file_lock:
                    if context in active_browsers:
                        active_browsers.remove(context)
                        logging.info(f"Đã xóa context khỏi active_browsers do lỗi tổng quát trong finally cho {username}")
                if not bet_success and retry_count < max_retries:
                    logging.info(f"Lỗi trong finally nhưng đặt cược chưa thành công cho {username}. Thử lại lần {retry_count + 1}/{max_retries}...")
                    print(f"Lỗi trong finally, thử lại lần {retry_count + 1}/{max_retries} cho {username}")
                    retry_count += 1
                    time.sleep(10)
                    with account_lock:
                        account_status[username] = False
                    with autorou_lock:
                        autorou_status[username] = False
                    with countdown_lock:
                        countdown_status[username] = False
                    with bet_status_lock:
                        bet_status[username] = False
                    continue
                elif bet_success:
                    logging.info(f"Đặt cược đã thành công, bỏ qua lỗi trong finally cho {username}.")
                    print(f"Bỏ qua lỗi trong finally vì đặt cược thành công: {username}")
                    with account_lock:
                        account_status[username] = True
                    return None
                else:
                    logging.error(f"Lỗi trong finally và đã vượt quá số lần thử tối đa ({max_retries}) cho {username}.")
                    print(f"Lỗi trong finally và vượt quá số lần thử tối đa cho {username}")
                    with account_lock:
                        account_status[username] = False
                    with autorou_lock:
                        autorou_status[username] = False
                    with countdown_lock:
                        countdown_status[username] = False
                    with bet_status_lock:
                        bet_status[username] = False
                    return None

# Lớp Worker
class Worker(QThread):
    def __init__(self, link, username, password, proxy, api_key, mode, chip,
                 browser_width, browser_height, x_pos, y_pos, account_index,headless):
        super().__init__()
        self.link = link
        self.username = username
        self.password = password
        self.proxy = proxy
        self.api_key = api_key
        self.mode = mode
        self.chip = chip  # Changed from amount to chip
        self.browser_width = browser_width
        self.browser_height = browser_height
        self.x_pos = x_pos
        self.y_pos = y_pos
        self.account_index = account_index
        self.headless = headless  # Thêm headless
        self.context = None

    def run(self):
        user_agent = generate_random_user_agent()
        proxy_handler = ProxyHandler(self.api_key)
        logging.info(f"Khởi động trình duyệt cho tài khoản {self.username} với proxy {self.proxy}...")
        login_with_playwright(
            self.link, self.username, self.password, self.proxy, user_agent,
            proxy_handler, self.mode, self.chip,
            self.browser_width, self.browser_height, self.x_pos, self.y_pos,
            self.account_index, self.headless  # Truyền headless
        )
        logging.info(f"Luồng cho tài khoản {self.username} đã hoàn thành.")

class ProxyHandler:
    def __init__(self, api_key):
        self.api_key = api_key

    def change_ip_using_api(self, retry_limit=3):
        try:
            url = f"https://app.proxyno1.com/api/change-key-ip/{self.api_key}"  # URL từ mã cũ
            headers = {"Accept": "application/json", "Content-Type": "application/json"}  # Headers từ mã cũ
            retry_count = 0
            while retry_count < retry_limit:
                response = requests.get(url, headers=headers, timeout=10, verify=False)  # Thêm verify=False
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status', 1) == 0:  # Kiểm tra status == 0
                        logging.info(f"Thay đổi IP thành công với API key {self.api_key}")
                        time.sleep(10)  # Chờ 10 giây như mã cũ
                        return True
                    else:
                        if retry_count < retry_limit - 1:
                            match = re.search(r'Đợi (\d+) giây', data.get('message', ''))
                            wait_time = int(match.group(1)) if match else 10
                            logging.info(f"API yêu cầu đợi {wait_time} giây trước khi thử lại")
                            time.sleep(wait_time)
                            retry_count += 1
                        else:
                            logging.warning(f"Thay đổi IP thất bại sau {retry_limit} lần thử: {data.get('message', 'No message')}")
                            return False
                else:
                    logging.warning(f"Yêu cầu API thất bại, mã trạng thái: {response.status_code}")
                    time.sleep(10)  # Chờ 10 giây như mã cũ
                    retry_count += 1
            logging.error(f"Không thể thay đổi IP sau {retry_limit} lần thử với API key {self.api_key}")
            return False
        except Exception as e:
            logging.error(f"Lỗi khi thay đổi IP với API key {self.api_key}: {traceback.format_exc()}")
            return False


def check_proxy(proxy, proxy_handler, max_retries=3):
    """
    Kiểm tra xem proxy có hoạt động bằng cách gửi yêu cầu đến Google.
    Nếu thất bại, thử đổi IP và kiểm tra lại tối đa max_retries lần.
    """
    proxy_url = f"http://{proxy}"
    proxies = {"http": proxy_url, "https": proxy_url}
    test_url = "https://www.google.com"  # URL kiểm tra proxy
    retry_count = 0

    while retry_count < max_retries:
        try:
            response = requests.get(test_url, proxies=proxies, timeout=10, verify=False)
            if response.status_code == 200:
                logging.info(f"Proxy {proxy} hoạt động với mã trạng thái: {response.status_code}")
                return True
            else:
                logging.warning(f"Proxy {proxy} trả về mã trạng thái: {response.status_code}")
        except Exception as e:
            logging.warning(f"Không thể kết nối với proxy {proxy}: {str(e)}")

        retry_count += 1
        if retry_count < max_retries:
            logging.info(f"Proxy {proxy}. Thử đổi IP (lần {retry_count + 1}/{max_retries})...")
            success = proxy_handler.change_ip_using_api()
            if success:
                time.sleep(10)  # Chờ 10 giây sau khi đổi IP
            else:
                logging.warning(f"Không thể đổi IP cho {proxy}. Thử lại...")
                time.sleep(1)

    logging.error(f"Proxy không hoạt động sau {proxy} max_retries lần thử {max_retries}.")
    return False


from PyQt5.QtCore import pyqtSignal

class AutomationWorker(QThread):
    log_signal = pyqtSignal(str)
    enable_run_button_signal = pyqtSignal()
    update_round_signal = pyqtSignal(int, int)
    all_rounds_completed_signal = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

    def cleanup_resources(self):
        try:
            for proc in psutil.process_iter(['name', 'cmdline']):
                if proc.info['name'] in ['chrome.exe', 'chromium', 'msedge']:
                    cmdline = ' '.join(proc.info.get('cmdline', [])).lower()
                    if 'playwright' in cmdline:
                        proc.terminate()
                        proc.wait(timeout=3)
                        logging.info(f"Đã dừng tiến trình Playwright: {proc.info['name']} (PID: {proc.pid})")
            with file_lock:
                active_browsers.clear()
                logging.info("Đã xóa danh sách active_browsers sau vòng.")
        except Exception as e:
            logging.error(f"Lỗi khi dọn dẹp tài nguyên: {traceback.format_exc()}")

    def run(self):
        try:
            global credentials, total_browsers, completed_accounts, current_round
            logging.info("Bước 1: Dừng tất cả hoạt động trước đó...")
            stop_event.set()
            for worker in self.main_window.workers:
                try:
                    worker.terminate()
                    logging.info(f"Đã dừng worker cho {worker.username}")
                except Exception as e:
                    logging.error(f"Lỗi khi dừng worker cho {worker.username}: {traceback.format_exc()}")
                    self.log_signal.emit(f"Lỗi khi dừng worker cho {worker.username}: {e}")
            self.main_window.workers.clear()
            time.sleep(1)
            stop_event.clear()

            logging.info("Bước 2: Đóng tất cả trình duyệt đồng thời...")
            self.main_window.close_all_browsers()

            logging.info("Bước 3: Đặt lại trạng thái chương trình...")
            self.main_window.reset_program_state()

            logging.info("Bước 4: Lưu cấu hình...")
            self.main_window.save_config()

            logging.info("Bước 5: Xử lý thông tin tài khoản...")
            credentials = []
            completed_accounts_set = self.main_window.load_completed_accounts()
            for line in self.main_window.account_input.toPlainText().strip().split('\n'):
                parts = line.split('|')
                if len(parts) >= 2:
                    username, password = parts[0].strip(), parts[1].strip()
                    if (username, password) not in completed_accounts_set:
                        credentials.append((username, password))
                else:
                    parts = line.split()
                    if len(parts) >= 2:
                        username, password = parts[0].strip(), parts[1].strip()
                        if (username, password) not in completed_accounts_set:
                            credentials.append((username, password))

            if not credentials:
                logging.error("Lỗi: Không có thông tin tài khoản hợp lệ hoặc tất cả tài khoản đã hoàn thành.")
                self.log_signal.emit("Lỗi: Không có thông tin tài khoản hợp lệ hoặc tất cả tài khoản đã hoàn thành.")
                self.enable_run_button_signal.emit()
                return

            # Ghi danh sách tài khoản vào file CSV ngay khi nhấn "Chạy"
            csv_file = Path('taikhoancuoc.csv')
            with csv_lock:
                try:
                    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(['TK', 'SO CUOC', 'SO TIEN', 'MUC CUOC', 'Timestamp'])
                        for username, _ in credentials:
                            writer.writerow([username, '', 'N/A', '', time.strftime('%Y-%m-%d %H:%M:%S')])
                    logging.info("Đã tạo hoặc làm mới file taikhoancuoc.csv với danh sách tài khoản")
                except Exception as e:
                    logging.error(f"Lỗi khi tạo/làm mới file CSV: {e}")
                    self.log_signal.emit(f"Lỗi khi tạo/làm mới file CSV: {e}")

            max_accounts_per_group = 37
            credential_groups = [
                credentials[i:i + max_accounts_per_group]
                for i in range(0, len(credentials), max_accounts_per_group)
            ]
            max_rounds = len(credential_groups)
            logging.info(f"Tổng số nhóm tài khoản: {max_rounds} nhóm")

            base_link = self.main_window.link_input.text().strip()
            mode = self.main_window.mode_combo.currentText()
            chip = self.main_window.chip_combo.currentText()
            headless = self.main_window.headless_checkbox.isChecked()

            if not base_link:
                logging.error("Lỗi: Không có liên kết cơ bản được cung cấp.")
                self.log_signal.emit("Lỗi: Không có liên kết cơ bản được cung cấp.")
                self.enable_run_button_signal.emit()
                return

            if not base_link.startswith(('http://', 'https://')):
                base_link = f"https://{base_link}"
                logging.info(f"Đã thêm giao thức HTTPS vào liên kết: {base_link}")

            link = f"{base_link}/Account/LoginToSupplier?supplierType=SE&gId=4020"
            logging.info(f"Liên kết được sử dụng: {link}")

            proxies = {}
            proxy_input_text = self.main_window.proxy_input.toPlainText().strip()
            for line in proxy_input_text.split('\n'):
                parts = line.split('|')
                if len(parts) == 2:
                    proxies[parts[0].strip()] = parts[1].strip()

            if not proxies:
                logging.error("Lỗi: Không có proxy hợp lệ được cung cấp.")
                self.log_signal.emit("Lỗi: Không có proxy hợp lệ được cung cấp.")
                self.enable_run_button_signal.emit()
                return

            num_proxies = len(proxies)
            proxy_list = list(proxies.items())
            logging.info(f"Số lượng proxy: {num_proxies}")

            screen_width, screen_height = pyautogui.size()
            browser_width = 700
            browser_height = 700
            max_browsers_per_row = min(10, screen_width // browser_width)
            offset = 50
            vertical_offset = 50

            # Xử lý chạy lại hoặc bỏ qua vòng hiện tại
            start_round = self.main_window.current_round - 1 if self.main_window.retry_current_round_flag else max(0, self.main_window.current_round)
            if self.main_window.skip_current_round_flag:
                start_round = min(self.main_window.current_round, max_rounds - 1)
                self.main_window.skip_current_round_flag = False
            if self.main_window.retry_current_round_flag:
                self.main_window.retry_current_round_flag = False

            for group_idx in range(start_round, max_rounds):
                if stop_event.is_set():
                    logging.info(f"Dừng xử lý nhóm {group_idx + 1} do sự kiện dừng.")
                    self.log_signal.emit(f"Dừng xử lý nhóm {group_idx + 1} do sự kiện dừng.")
                    break

                with round_lock:
                    current_round = group_idx + 1
                self.update_round_signal.emit(current_round, max_rounds)
                logging.info(f"Bắt đầu nhóm {group_idx + 1}/{max_rounds} với {len(credential_groups[group_idx])} tài khoản")
                self.log_signal.emit(f"Bắt đầu vòng {current_round}/{max_rounds}")

                self.main_window.reset_program_state()
                total_browsers = len(credential_groups[group_idx])
                completed_accounts = 0
                set_total_accounts(len(credential_groups[group_idx]), credential_groups[group_idx])

                self.main_window.proxy_threads = []
                self.main_window.proxy_status.clear()
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [
                        executor.submit(self.main_window.process_proxy, api_key, proxy)
                        for api_key, proxy in proxy_list
                    ]
                    concurrent.futures.wait(futures)

                active_proxies = [(api_key, proxy) for api_key, proxy in proxy_list if self.main_window.proxy_status.get(proxy, False)]
                if not active_proxies:
                    logging.error(f"Không có proxy nào hoạt động cho nhóm {group_idx + 1}.")
                    self.log_signal.emit(f"Lỗi: Không có proxy hoạt động cho nhóm {group_idx + 1}.")
                    self.enable_run_button_signal.emit()
                    return

                num_active_proxies = len(active_proxies)
                accounts_per_proxy = max(1, (len(credential_groups[group_idx]) + num_active_proxies - 1) // num_active_proxies)

                self.main_window.workers = []
                # self.main_window.retry_button.setEnabled(True)
                # self.main_window.skip_button.setEnabled(True)
                credential_idx = 0
                for proxy_idx, (api_key, proxy) in enumerate(active_proxies):
                    if stop_event.is_set():
                        break

                    start_idx = credential_idx
                    end_idx = min(start_idx + accounts_per_proxy, len(credential_groups[group_idx]))
                    assigned_credentials = credential_groups[group_idx][start_idx:end_idx]
                    credential_idx = end_idx

                    for idx, (username, password) in enumerate(assigned_credentials):
                        if stop_event.is_set():
                            break

                        total_idx = start_idx + idx
                        row = total_idx // max_browsers_per_row
                        col = total_idx % max_browsers_per_row
                        x_pos = col * (browser_width + offset)
                        y_pos = row * (browser_height + vertical_offset)
                        x_pos = max(0, min(x_pos, screen_width - browser_width))
                        y_pos = max(0, min(y_pos, screen_height - browser_height))
                        account_index = total_idx + 1

                        worker = Worker(
                            link, username, password, proxy, api_key, mode, chip,
                            browser_width, browser_height, x_pos, y_pos, account_index, headless
                        )
                        with file_lock:
                            self.main_window.workers.append(worker)
                        worker.start()
                        time.sleep(1)

                for worker in self.main_window.workers:
                    worker.wait()

                # Lưu tài khoản đã hoàn thành
                self.main_window.save_completed_accounts(credential_groups[group_idx])

                self.main_window.close_all_browsers()
                self.cleanup_resources()
                logging.info(f"Hoàn tất vòng {group_idx + 1}. Đã dọn dẹp tài nguyên.")
                if group_idx < max_rounds - 1:
                    time.sleep(5)

            logging.info("Đã hoàn tất xử lý tất cả các nhóm tài khoản.")
            with round_lock:
                current_round = 0
            self.update_round_signal.emit(0, max_rounds)
            # self.main_window.retry_button.setEnabled(False)
            # self.main_window.skip_button.setEnabled(False)
            self.all_rounds_completed_signal.emit()
            self.enable_run_button_signal.emit()

        except Exception as e:
            logging.error(f"Lỗi trong AutomationWorker: {traceback.format_exc()}")
            self.log_signal.emit(f"Lỗi trong AutomationWorker: {e}")
            with round_lock:
                current_round = 0
            self.update_round_signal.emit(0, max_rounds)
            # self.main_window.retry_button.setEnabled(False)
            # self.main_window.skip_button.setEnabled(False)
            self.all_rounds_completed_signal.emit()
            self.enable_run_button_signal.emit()
# Lớp MainWindow
class FilterBalanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bảng Ngoại Tệ")
        self.setGeometry(200, 200, 400, 300)

        layout = QVBoxLayout()

        # Tạo bảng để hiển thị dữ liệu
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(['Tài khoản', 'Số tiền'])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        # Nút đóng
        close_button = QPushButton("Đóng")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        self.setLayout(layout)

    def populate_table(self, data):
        self.table.setRowCount(len(data))
        for row, (username, balance) in enumerate(data):
            self.table.setItem(row, 0, QTableWidgetItem(username))
            self.table.setItem(row, 1, QTableWidgetItem(str(balance)))


class DownloadThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path

    def run(self):
        try:
            response = requests.get(self.url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            bytes_downloaded = 0

            with open(self.save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if total_size > 0:
                        percentage = int((bytes_downloaded / total_size) * 100)
                        self.progress.emit(percentage)

            self.finished.emit(self.save_path)
        except Exception as e:
            self.error.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CƯỢC ROULETTE")
        self.setGeometry(100, 100, 300, 400)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        self.statusBar().showMessage("Sẵn sàng")
        self.statusBar().setStyleSheet("font-size: 14px;")

        link_layout = QHBoxLayout()
        link_label = QLabel("Link:")
        self.link_input = QLineEdit()
        link_layout.addWidget(link_label)
        link_layout.addWidget(self.link_input)
        layout.addLayout(link_layout)

        mode_amount_layout = QHBoxLayout()
        mode_label = QLabel("Chế độ:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["BACARAT"])
        mode_amount_layout.addWidget(mode_label)
        mode_amount_layout.addWidget(self.mode_combo)

        chip_label = QLabel("Tiền Cược:")
        self.chip_combo = QComboBox()
        self.chip_combo.addItems(["1", "2", "5"])
        mode_amount_layout.addWidget(chip_label)
        mode_amount_layout.addWidget(self.chip_combo)
        layout.addLayout(mode_amount_layout)

        self.headless_checkbox = QCheckBox("Chạy ẩn trình duyệt")
        self.headless_checkbox.setChecked(False)
        layout.addWidget(self.headless_checkbox)

        proxy_label = QLabel("Proxy (api_key|proxy, mỗi dòng một proxy):")
        self.proxy_input = QTextEdit()
        layout.addWidget(proxy_label)
        layout.addWidget(self.proxy_input)

        account_label = QLabel("Tài khoản (username|password, mỗi dòng một tài khoản):")
        self.account_input = QTextEdit()
        self.account_input.textChanged.connect(self.check_account_change)
        layout.addWidget(account_label)
        layout.addWidget(self.account_input)

        status_label = QLabel("Trạng thái:")
        self.status_display = QTextEdit()
        self.status_display.setReadOnly(True)
        self.status_display.setFixedHeight(100)
        self.status_display.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.status_display.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(status_label)
        layout.addWidget(self.status_display)

        button_layout = QHBoxLayout()
        self.run_button = QPushButton("Chạy")
        self.run_button.clicked.connect(self.start_automation)
        button_layout.addWidget(self.run_button)

        self.close_button = QPushButton("Đóng")
        self.close_button.clicked.connect(self.close_all_browsers)
        button_layout.addWidget(self.close_button)

        self.open_folder_button = QPushButton("Mở thư mục")
        self.open_folder_button.clicked.connect(self.open_current_folder)
        button_layout.addWidget(self.open_folder_button)

        layout.addLayout(button_layout)

        # Thêm nút Lọc Tiền
        self.filter_balance_button = QPushButton("Lọc Tiền")
        self.filter_balance_button.clicked.connect(self.filter_balance)
        layout.addWidget(self.filter_balance_button)

        # Thêm nút Xóa tài khoản đã xong
        self.clear_completed_button = QPushButton("Xóa tài khoản đã xong")
        self.clear_completed_button.clicked.connect(self.clear_completed_accounts)
        layout.addWidget(self.clear_completed_button)

        self.workers = []
        self.proxy_threads = []
        self.proxy_status = {}
        self.current_round = 0
        self.max_rounds = 0
        self.previous_account_input = self.account_input.toPlainText()
        self.retry_current_round_flag = False
        self.skip_current_round_flag = False
        self.load_config()

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status_display)
        self.status_timer.start(1000)

        if getattr(sys, 'frozen', False):
            current_dir = os.path.dirname(sys.executable)
            flag_file_path = os.path.join(current_dir, "update_success.flag")
            if os.path.exists(flag_file_path):
                QMessageBox.information(self, "Thành công",
                                        f"Ứng dụng đã được cập nhật thành công lên phiên bản {CURRENT_VERSION}!")
                os.remove(flag_file_path)

        # Gọi hàm kiểm tra cập nhật
        self.check_for_updates()

    def check_for_updates(self):
        # !!! THAY THẾ CÁC GIÁ TRỊ SAU !!!
        repo_owner = "blackshark9992"
        repo_name = "BACARAT"  # Tên kho chứa của tool Baccarat

        api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"

        try:
            response = requests.get(api_url, timeout=5)
            response.raise_for_status()
            latest_release = response.json()
            latest_version = latest_release["tag_name"].replace('v', '')

            if latest_version > CURRENT_VERSION:
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Information)
                msg_box.setText(
                    f"Đã có phiên bản mới ({latest_version})!\nBạn có muốn tự động cập nhật và khởi động lại không?")
                msg_box.setWindowTitle("Thông báo cập nhật")
                msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

                if msg_box.exec() == QMessageBox.Yes:
                    download_url = latest_release["assets"][0]["browser_download_url"]
                    self.start_update_process(download_url)

        except Exception as e:
            print(f"Không thể kiểm tra cập nhật: {e}")

    def start_update_process(self, download_url):
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.run_button.setEnabled(False)

        if getattr(sys, 'frozen', False):
            current_dir = os.path.dirname(sys.executable)
        else:
            current_dir = os.path.dirname(__file__)
        self.update_file_path_temp = os.path.join(current_dir, "update.tmp")

        self.download_thread = DownloadThread(download_url, self.update_file_path_temp)
        self.download_thread.progress.connect(self.update_progress)
        self.download_thread.finished.connect(self.on_download_finished)
        self.download_thread.error.connect(self.on_download_error)
        self.download_thread.start()

    def update_progress(self, percentage):
        self.progress_bar.setValue(percentage)

    def on_download_error(self, error_message):
        QMessageBox.critical(self, "Lỗi", f"Tải bản cập nhật thất bại: {error_message}")
        self.progress_bar.hide()
        self.run_button.setEnabled(True)

    def on_download_finished(self, downloaded_file_path):
        self.progress_bar.setFormat("Hoàn thành! Khởi động lại trong 3 giây...")
        QTimer.singleShot(3000, self.launch_updater_and_exit)

    def launch_updater_and_exit(self):
        current_file_path = sys.executable
        file_name = os.path.basename(current_file_path)
        current_dir = os.path.dirname(current_file_path)
        updater_script_path = os.path.join(current_dir, "updater.bat")
        flag_file_path = os.path.join(current_dir, "update_success.flag")

        script_content = f"""
@echo off
echo Vui long cho trong giay lat de hoan tat cap nhat...
TIMEOUT /T 2 /NOBREAK > NUL
DEL "{current_file_path}"
REN "{self.update_file_path_temp}" "{file_name}"
echo. > "{flag_file_path}"
START "" "{current_file_path}"
(DEL "%~f0" & exit)
"""
        with open(updater_script_path, "w") as f:
            f.write(script_content)

        subprocess.Popen([updater_script_path])
        sys.exit(0)

    def filter_balance(self):
        """Lọc và hiển thị tài khoản có số tiền lớn hơn 10 từ file taikhoancuoc.csv"""
        csv_file = Path('taikhoancuoc.csv')
        filtered_accounts = []

        try:
            if csv_file.exists():
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader)  # Bỏ qua header
                    for row in reader:
                        if len(row) >= 3:
                            try:
                                balance = float(row[2]) if row[2] != 'N/A' else 0
                                if balance > 10:
                                    filtered_accounts.append((row[0], balance))
                            except ValueError:
                                logging.warning(f"Số tiền không hợp lệ cho tài khoản {row[0]}: {row[2]}")
                                continue
                logging.info(f"Tìm thấy {len(filtered_accounts)} tài khoản có số tiền > 10")
            else:
                logging.error("File taikhoancuoc.csv không tồn tại")
                QMessageBox.warning(self, "Lỗi", "File taikhoancuoc.csv không tồn tại!", QMessageBox.Ok)
                return

            # Hiển thị bảng tạm
            dialog = FilterBalanceDialog(self)
            dialog.populate_table(filtered_accounts)
            dialog.exec_()
            self.statusBar().showMessage(f"Đã hiển thị {len(filtered_accounts)} tài khoản có số tiền > 10")
            logging.info(f"Đã hiển thị dialog với {len(filtered_accounts)} tài khoản")
        except Exception as e:
            logging.error(f"Lỗi khi lọc tài khoản: {e}")
            QMessageBox.critical(self, "Lỗi", f"Lỗi khi lọc tài khoản: {e}", QMessageBox.Ok)
            self.statusBar().showMessage("Lỗi khi lọc tài khoản")


    def open_current_folder(self):
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            if sys.platform == "win32":
                os.startfile(current_dir)
            elif sys.platform == "darwin":
                subprocess.run(["open", current_dir])
            else:
                subprocess.run(["xdg-open", current_dir])
            logging.info(f"Đã mở thư mục hiện tại: {current_dir}")
            self.statusBar().showMessage("Đã mở thư mục hiện tại")
        except Exception as e:
            logging.error(f"Lỗi khi mở thư mục hiện tại: {e}")
            self.statusBar().showMessage(f"Lỗi khi mở thư mục: {e}")

    def check_account_change(self):
        current_account_input = self.account_input.toPlainText().strip()
        if current_account_input != self.previous_account_input:
            logging.info("Phát hiện thay đổi trong danh sách tài khoản. Đặt lại file CSV khi chạy.")
            self.previous_account_input = current_account_input

    def retry_current_round(self):
        logging.info(f"Yêu cầu chạy lại vòng {self.current_round}")
        self.statusBar().showMessage(f"Chạy lại vòng {self.current_round}")
        self.retry_current_round_flag = True
        self.close_all_browsers()  # Đóng tất cả trình duyệt
        self.start_automation()  # Bắt đầu lại automation

    def skip_current_round(self):
        logging.info(f"Yêu cầu bỏ qua vòng {self.current_round}")
        self.statusBar().showMessage(f"Bỏ qua vòng {self.current_round}")
        self.skip_current_round_flag = True
        self.close_all_browsers()  # Đóng tất cả trình duyệt
        self.start_automation()  # Bắt đầu automation để chuyển sang vòng tiếp theo

    def load_config(self):
        try:
            if not CONFIG_FILE.exists():
                default_config = {
                    'link': '',
                    'proxy': '',
                    'account': '',
                    'mode': 'BACARAT',
                    'chip': '1',
                    'headless': False  # Thêm giá trị mặc định cho headless
                }
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=4, ensure_ascii=False)
                logging.info("Đã tạo config.json mới với giá trị mặc định.")
            else:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.link_input.setText(config.get('link', ''))
                    self.proxy_input.setPlainText(config.get('proxy', ''))
                    self.account_input.setPlainText(config.get('account', ''))
                    mode = config.get('mode', 'BACARAT')
                    if mode == "BACARAT":
                        self.mode_combo.setCurrentText(mode)
                    self.chip_combo.setCurrentText(config.get('chip', '1'))
                    self.headless_checkbox.setChecked(config.get('headless', False))  # Tải trạng thái headless
                    self.previous_account_input = config.get('account', '')
        except Exception as e:
            logging.error(f"Lỗi khi tải hoặc tạo config: {e}")

    def save_config(self):
        try:
            config = {
                'link': self.link_input.text().strip(),
                'proxy': self.proxy_input.toPlainText().strip(),
                'account': self.account_input.toPlainText().strip(),
                'mode': self.mode_combo.currentText(),
                'chip': self.chip_combo.currentText(),
                'headless': self.headless_checkbox.isChecked()  # Lưu trạng thái headless
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            self.previous_account_input = self.account_input.toPlainText().strip()
        except Exception as e:
            logging.error(f"Lỗi khi lưu config: {e}")

    def update_status_display(self):
        with file_lock:
            opened_webs = len(active_browsers)
        with account_lock:
            chip_selected = sum(1 for status in account_status.values() if status)
        with autorou_lock:
            autorou_clicked = sum(1 for status in autorou_status.values() if status)
        with bet_status_lock:
            bets_placed = sum(1 for status in bet_status.values() if status)
        with table_status_lock:
            current_table_status = table_status

        round_text = f"{self.current_round}/{self.max_rounds}" if self.current_round > 0 else "0"

        status_text = (
            f"Web mở: {opened_webs}/{total_browsers}\n"
            f"Tài khoản nhấp AutoRou: {autorou_clicked}/{total_accounts}\n"
            f"Tài khoản chọn chip: {chip_selected}/{total_accounts}\n"
            f"Tài khoản tìm thấy số cược: {bets_placed}/{total_accounts}\n"
            f"Trạng thái bàn: {current_table_status}\n"
            f"Vòng: {round_text}\n"
        )
        self.status_display.setPlainText(status_text)
        self.status_display.verticalScrollBar().setValue(
            self.status_display.verticalScrollBar().maximum()
        )

    def append_log_to_display(self, message):
        cursor = self.status_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(message + "\n")
        self.status_display.setTextCursor(cursor)
        self.status_display.ensureCursorVisible()

    def start_automation(self):
        self.run_button.setEnabled(False)
        self.worker = AutomationWorker(self)
        self.worker.log_signal.connect(self.append_log_to_display)
        self.worker.enable_run_button_signal.connect(self.enable_run_button)
        self.worker.update_round_signal.connect(self.update_round_display)
        self.worker.all_rounds_completed_signal.connect(self.show_completion_message)
        self.worker.start()

    def update_round_display(self, round_number, max_rounds):
        self.current_round = round_number
        self.max_rounds = max_rounds
        logging.info(f"Cập nhật vòng cược: Vòng hiện tại: {round_number}/{max_rounds}")
        self.update_status_display()

    def show_completion_message(self):
        logging.info("Hoàn tất tất cả các vòng cược.")
        QMessageBox.information(
            self,
            "Hoàn tất",
            "Tất cả các vòng cược đã hoàn thành thành công!",
            QMessageBox.Ok
        )

    def enable_run_button(self):
        self.run_button.setEnabled(True)
        self.statusBar().showMessage("Sẵn sàng")

    def close_all_browsers(self):
        global active_browsers, table_status
        logging.info("Bắt đầu đóng đồng loạt các trình duyệt và dừng tất cả luồng...")
        stop_event.set()

        for worker in self.workers:
            try:
                worker.quit()
                logging.info(f"Đã dừng worker cho {worker.username}")
            except Exception as e:
                logging.error(f"Lỗi khi dừng worker cho {worker.username}: {traceback.format_exc()}")
        self.workers.clear()

        with file_lock:
            for context in active_browsers[:]:
                try:
                    if hasattr(context, '_impl_obj') and context._impl_obj.is_connected():
                        context.close()
                        logging.info("Đã đóng một context trình duyệt.")
                    else:
                        logging.warning("Context đã bị đóng hoặc không hợp lệ. Bỏ qua.")
                except Exception as e:
                    logging.error(f"Lỗi khi đóng context trình duyệt: {traceback.format_exc()}")
                finally:
                    if context in active_browsers:
                        active_browsers.remove(context)

        try:
            for proc in psutil.process_iter(['name', 'cmdline']):
                if proc.info['name'] in ['chrome.exe', 'chromium', 'msedge']:
                    cmdline = ' '.join(proc.info.get('cmdline', [])).lower()
                    if 'playwright' in cmdline:
                        proc.terminate()
                        proc.wait(timeout=3)
                        logging.info(f"Đã dừng tiến trình Playwright: {proc.info['name']} (PID: {proc.pid})")
        except Exception as e:
            logging.error(f"Lỗi khi dừng tiến trình Playwright: {e}")

        with table_status_lock:
            table_status = "Bàn cược ẩn"
        with account_lock:
            account_status.clear()
        with autorou_lock:
            autorou_status.clear()
        with countdown_lock:
            countdown_status.clear()
        with bet_status_lock:
            bet_status.clear()
        all_autorou_clicked_event.clear()
        all_chips_selected_event.clear()
        all_countdowns_ready_event.clear()
        stop_event.clear()
        logging.info("Đã đóng tất cả trình duyệt và đặt lại trạng thái.")

    def reset_program_state(self):
        global active_browsers, total_browsers, completed_accounts, table_status, current_round
        with file_lock:
            active_browsers.clear()
        total_browsers = 0
        completed_accounts = 0
        with table_status_lock:
            table_status = "Bàn cược ẩn"
        with round_lock:
            current_round = 0
        with account_lock:
            account_status.clear()
        with countdown_lock:
            countdown_status.clear()
        with autorou_lock:
            autorou_status.clear()
        with bet_status_lock:
            bet_status.clear()
        all_countdowns_ready_event.clear()
        all_autorou_clicked_event.clear()
        all_chips_selected_event.clear()
        logging.info("Đã đặt lại trạng thái chương trình.")

    def process_proxy(self, api_key, proxy):
        if stop_event.is_set():
            logging.info(f"Dừng xử lý proxy cho {proxy} do sự kiện dừng.")
            return
        try:
            proxy_handler = ProxyHandler(api_key)
            max_ip_retries = 3
            retry_count = 0
            proxy_works = False

            while retry_count < max_ip_retries and not proxy_works and not stop_event.is_set():
                success = proxy_handler.change_ip_using_api()
                if not success:
                    retry_count += 1
                    time.sleep(5)
                    continue

                time.sleep(10)
                proxy_works = check_proxy(proxy, proxy_handler, max_retries=3)
                retry_count += 1

            with file_lock:
                self.proxy_status[proxy] = proxy_works
        except Exception as e:
            logging.error(f"Lỗi khi xử lý proxy {proxy}: {traceback.format_exc()}")
            with file_lock:
                self.proxy_status[proxy] = False
    def load_completed_accounts(self):
        """Tải danh sách tài khoản đã hoàn thành từ file completed_accounts.txt."""
        completed_accounts = set()
        completed_file = Path('TK_XONG.txt')
        if completed_file.exists():
            try:
                with open(completed_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        parts = line.strip().split('|')
                        if len(parts) == 3 and parts[2] == 'Xong':
                            completed_accounts.add((parts[0], parts[1]))
                logging.info(f"Đã tải {len(completed_accounts)} tài khoản đã hoàn thành từ completed_accounts.txt")
            except Exception as e:
                logging.error(f"Lỗi khi tải completed_accounts.txt: {e}")
        return completed_accounts

    def save_completed_accounts(self, credentials):
        """Lưu các tài khoản đã hoàn thành vào file completed_accounts.txt."""
        completed_file = Path('TK_XONG.txt')
        with file_lock:
            try:
                with open(completed_file, 'a', encoding='utf-8') as f:
                    for username, password in credentials:
                        if bet_status.get(username, False):  # Chỉ lưu nếu tài khoản đã đặt cược thành công
                            f.write(f"{username}|{password}|Xong\n")
                            logging.info(f"Đã lưu tài khoản {username} vào TK_XONG.txt")
            except Exception as e:
                logging.error(f"Lỗi khi lưu vào TK_XONG.txt: {e}")

    def clear_completed_accounts(self):
        try:
            tk_xong_file = Path('TK_XONG.txt')
            log_file = Path('roulette.log')

            # Xóa file TK_XONG.txt nếu tồn tại
            if tk_xong_file.exists():
                tk_xong_file.unlink()
                logging.info("Đã xóa file TK_XONG.txt")
                self.statusBar().showMessage("Đã xóa danh sách tài khoản đã hoàn thành")
            else:
                logging.info("File TK_XONG.txt không tồn tại, không cần xóa")
                self.statusBar().showMessage("Không tìm thấy file TK_XONG.txt")

            # Đóng file handler của logger trước khi xóa file roulette.log
            global logger
            for handler in logger.handlers[:]:  # Sao chép danh sách để tránh lỗi khi xóa
                if isinstance(handler, logging.handlers.RotatingFileHandler) and handler.baseFilename == str(
                        log_file.resolve()):
                    handler.close()
                    logger.removeHandler(handler)
                    logging.info("Đã đóng file handler cho roulette.log")

            # Xóa file roulette.log nếu tồn tại
            if log_file.exists():
                log_file.unlink()
                logging.info("Đã xóa file roulette.log")
                self.statusBar().showMessage("Đã xóa file log roulette.log")
            else:
                logging.info("File roulette.log không tồn tại, không cần xóa")
                self.statusBar().showMessage("Không tìm thấy file roulette.log")

            # Tái cấu hình logger với file handler mới
            file_handler = logging.handlers.RotatingFileHandler(
                filename="roulette.log",
                encoding="utf-8",
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5
            )
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logging.info("Đã tái cấu hình logger với file handler mới cho roulette.log")

        except Exception as e:
            logging.error(f"Lỗi khi xóa tài khoản đã hoàn thành hoặc file log: {e}")
            self.statusBar().showMessage(f"Lỗi khi xóa: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

def main():
    try:
        app = QApplication(sys.argv) if not QApplication.instance() else QApplication.instance()
        window = MainWindow()
        window.show()
        return window
    except Exception as e:
        logging.error(f"Lỗi khi chạy BACARAT: {e}")
        return None