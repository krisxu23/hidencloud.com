import os
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from seleniumbase import Driver

# ====================== 配置区域 ======================
HIDENCLOUD = os.getenv("HIDENCLOUD", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
PROXY_SERVER = os.getenv("PROXY_SERVER", "")

if "-----" in HIDENCLOUD:
    HIDEN_EMAIL, HIDEN_PWD = HIDENCLOUD.split("-----", 1)
else:
    raise ValueError("❌ HIDENCLOUD 格式错误，应为 email-----password")

BASE_URL = "https://dash.hidencloud.com"
STATE_DIR = "browser_state"
SCREENSHOT_DIR = "screenshots"

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

USER_DATA_DIR = os.path.abspath(os.path.join(STATE_DIR, "selenium_profile"))


# ====================== 工具函数 ======================
def get_bj_time():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')


def send_tg_notification(message, photo_path=None):
    """发送 TG 通知。有截图时发图片+说明，否则发纯文字。"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] 未配置 TG 信息，跳过发送")
        return
    # Markdown caption 限制 1024 字符，文字消息限制 4096 字符
    try:
        if photo_path and os.path.exists(photo_path):
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            caption = message[:1020] + "…" if len(message) > 1024 else message
            with open(photo_path, 'rb') as f:
                resp = requests.post(
                    url,
                    files={'photo': f},
                    data={'chat_id': TG_CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'},
                    timeout=30,
                )
            # 若图片发送失败（如文件损坏），降级为纯文字
            if not resp.ok:
                print(f"[WARN] 图片发送失败({resp.status_code})，降级为文字")
                raise ValueError("photo failed")
        else:
            raise ValueError("no photo")
    except Exception:
        try:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            text = message[:4000] + "…" if len(message) > 4096 else message
            requests.post(
                url,
                json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=15,
            )
        except Exception as e:
            print(f"[ERROR] TG 发送失败: {e}")
            return
    print("[INFO] 📡 TG 通知已发送")


def take_screenshot(driver, name):
    timestamp = datetime.now().strftime('%H%M%S')
    filename = f"{SCREENSHOT_DIR}/{timestamp}-{name}.png"
    try:
        driver.save_screenshot(filename)
        print(f"[INFO] 📸 截图 → {filename}")
    except Exception as e:
        print(f"[WARN] 截图失败: {e}")
    return filename


def wait_for_turnstile_token(driver, timeout=90):
    print("[INFO] ⏳ 等待 Turnstile 验证通过...")
    start = time.time()
    while time.time() - start < timeout:
        token = driver.execute_script(
            'return document.querySelector("[name=cf-turnstile-response]")?.value'
        )
        if token and len(token) > 20:
            print("[INFO] ✅ Turnstile token 已生成")
            return True
        time.sleep(1)
    return False


def wait_for_url_contains(driver, keyword, timeout=45):
    start = time.time()
    while time.time() - start < timeout:
        if keyword in driver.current_url:
            return True
        time.sleep(0.5)
    return False


def check_login_error(driver):
    try:
        error_selectors = [
            ".text-red-500", ".alert-danger", "[role='alert']", ".error", ".invalid-feedback"
        ]
        for sel in error_selectors:
            try:
                elem = driver.find_element(sel, by="css selector")
                if elem and elem.is_displayed() and elem.text.strip():
                    return elem.text.strip()
            except:
                pass
    except:
        pass
    return None


def mask_email(email):
    if '@' in email:
        local, domain = email.split('@', 1)
        return f"{local[:3]}***@{domain}"
    return f"{email[:3]}***"


def parse_due_date(text):
    """将页面显示的日期字符串转换为 YYYY-MM-DD 格式"""
    if not text:
        return None
    match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', text)
    if match:
        day, month_str, year = match.groups()
        try:
            dt = datetime.strptime(f"{day} {month_str} {year}", "%d %b %Y")
            return dt.strftime("%Y-%m-%d")
        except:
            pass
    if re.match(r'\d{4}-\d{2}-\d{2}', text):
        return text
    return None


def get_current_due_date(driver):
    """获取当前管理页面的到期时间，兼容多种页面结构"""
    selectors = [
        ("xpath", "//h6[contains(text(),'Due date')]/following-sibling::div"),
        ("xpath", "//p[contains(text(),'Due date')]/following-sibling::*"),
        ("xpath", "//*[contains(text(),'Due date')]/..//*[contains(@class,'text')]"),
        ("xpath", "//span[contains(text(),'Next Invoice')]/../..//span[last()]"),
        ("css selector", ".next-invoice-date"),
    ]
    for by, sel in selectors:
        try:
            elem = driver.find_element(by, sel)
            raw = elem.text.strip()
            if raw:
                std = parse_due_date(raw)
                return raw, std
        except:
            continue
    return "N/A", None


def get_all_service_ids(driver):
    """从 dashboard 页面提取所有服务 ID"""
    sids = []
    try:
        # 优先从 manage 链接抓取
        links = driver.find_elements("css selector", "a[href*='/service/'][href*='/manage']")
        for link in links:
            href = link.get_attribute("href") or ""
            m = re.search(r'/service/(\d+)/manage', href)
            if m and m.group(1) not in sids:
                sids.append(m.group(1))
    except:
        pass

    if not sids:
        # 从文字 "Free Server #XXXX" 提取
        try:
            elems = driver.find_elements("xpath", "//*[contains(text(),'Free Server #')]")
            for elem in elems:
                m = re.search(r'Free Server #(\d+)', elem.text)
                if m and m.group(1) not in sids:
                    sids.append(m.group(1))
        except:
            pass

    return sids


def close_any_modal(driver):
    """尝试关闭所有可见弹窗（点击 OK / Cancel / ×）"""
    for sel in [
        "//button[contains(text(),'OK')]",
        "//button[contains(text(),'Cancel')]",
        "//button[@aria-label='Close']",
        "//button[contains(@class,'close')]",
    ]:
        try:
            btn = driver.find_element("xpath", sel)
            if btn.is_displayed():
                btn.click()
                time.sleep(0.5)
                return True
        except:
            pass
    return False


def wait_for_modal_visible(driver, timeout=10):
    """等待续期模态框出现，返回模态框元素或 None"""
    modal_selectors = [
        "css selector", ".fixed.inset-0:not([style*='display: none'])",
    ]
    start = time.time()
    while time.time() - start < timeout:
        try:
            el = driver.find_element(*modal_selectors)
            if el.is_displayed():
                return el
        except:
            pass
        time.sleep(0.5)
    return None


def detect_restricted_popup(driver):
    """
    检测是否弹出了 Renewal Restricted 弹窗。
    返回 (is_restricted: bool, alert_text: str, days_left: int|None, threshold: int|None)
    """
    try:
        h3_text = driver.execute_script(
            "var el = document.querySelector('.fixed.inset-0 h3');"
            "return el ? el.textContent.trim() : '';"
        )
        if 'Renewal Restricted' in h3_text:
            alert_text = driver.execute_script(
                "var el = document.querySelector('.fixed.inset-0 p');"
                "return el ? el.textContent.trim() : '';"
            )
            # 从弹窗文字中提取天数，如 "expires in 6 days"
            days_left = None
            m = re.search(r'expires in (\d+) day', alert_text or "", re.IGNORECASE)
            if m:
                days_left = int(m.group(1))
            return True, alert_text or "", days_left, None
    except:
        pass
    return False, "", None, None


def notify_service_result(sid, res):
    """续期完成后立即发一条带截图的 TG 通知（每个服务单独一条）。"""
    if res["success"]:
        icon = "✅ 续期成功"
    elif res["skipped"]:
        icon = "⏰ 未到窗口期"
    else:
        icon = "❌ 续期失败"

    due_change = res["due_before"]
    if res["due_after"] != "N/A" and res["due_after"] != res["due_before"]:
        due_change = f"{res['due_before']} → {res['due_after']}"
    elif res["due_after"] != "N/A":
        due_change = res["due_after"]

    extra = ""
    if res["skipped"] and res.get("days_left") is not None:
        thr = res.get("threshold")
        extra = f"\n剩余: {res['days_left']} 天（需 ≤{thr} 天可续）" if thr else f"\n剩余: {res['days_left']} 天"

    msg = (
        f"{icon}\n\n"
        f"账号: `{HIDEN_EMAIL}`\n"
        f"服务: `Free Server #{sid}`\n"
        f"到期: {due_change}{extra}\n"
        f"详情: {res['message']}\n"
        f"时间: {get_bj_time()}"
    )
    send_tg_notification(msg, photo_path=res.get("screenshot"))


def renew_one_service(driver, sid):
    """
    对单个服务执行续期。
    返回 dict:
        success   bool
        skipped   bool   (限制弹窗，未到窗口期)
        message   str
        days_left int|None
        threshold int|None
        due_before str
        due_after  str
        screenshot str
    """
    result = {
        "success": False,
        "skipped": False,
        "message": "",
        "days_left": None,
        "threshold": None,
        "due_before": "N/A",
        "due_after": "N/A",
        "screenshot": None,
    }

    manage_url = f"{BASE_URL}/service/{sid}/manage"
    print(f"[INFO] 🚀 [{sid}] 访问管理页面...")
    driver.get(manage_url)
    time.sleep(3)
    take_screenshot(driver, f"s{sid}-01-manage")

    # 续期前到期时间
    result["due_before"], _ = get_current_due_date(driver)
    print(f"[INFO] [{sid}] 续期前到期: {result['due_before']}")

    # ── 定位 Renew 按钮 ──
    renew_btn = None
    btn_selectors = [
        ("css selector", "button[onclick*='showRenewAlert']"),
        ("xpath", "//button[.//i[contains(@class,'bx-recycle')]]"),
        ("xpath", "//button[normalize-space()='Renew']"),
        ("xpath", "//button[contains(text(),'Renew')]"),
    ]
    for by, val in btn_selectors:
        try:
            el = driver.find_element(by, val)
            if el.is_displayed():
                renew_btn = el
                break
        except:
            continue

    if not renew_btn:
        result["message"] = "未找到 Renew 按钮"
        result["screenshot"] = take_screenshot(driver, f"s{sid}-ERROR-no-renew-btn")
        return result

    # 从 onclick 提取参数（剩余天数/阈值）
    onclick_val = renew_btn.get_attribute("onclick") or ""
    param_match = re.search(
        r'showRenewAlert\((\d+),\s*(\d+),\s*(true|false)\)', onclick_val
    )
    if param_match:
        result["days_left"] = int(param_match.group(1))
        result["threshold"] = int(param_match.group(2))
        is_free = param_match.group(3) == "true"
        print(
            f"[INFO] [{sid}] 到期剩余: {result['days_left']} 天, "
            f"续期阈值: ≤{result['threshold']} 天, 免费服务: {is_free}"
        )

    # ── 点击 Renew ──
    print(f"[INFO] [{sid}] 🔄 点击 Renew 按钮...")
    renew_btn.click()
    time.sleep(2)
    take_screenshot(driver, f"s{sid}-02-renew-clicked")

    # ── 检测限制弹窗 ──
    is_restricted, alert_text, popup_days, _ = detect_restricted_popup(driver)
    if is_restricted:
        days_info = popup_days or result["days_left"]
        print(f"[INFO] [{sid}] ⚠️ Renewal Restricted: {alert_text}")
        take_screenshot(driver, f"s{sid}-03-restricted")
        close_any_modal(driver)
        result["skipped"] = True
        result["days_left"] = days_info
        result["message"] = (
            f"未到续期窗口期，距到期还有 {days_info} 天（需 ≤{result['threshold']} 天）"
            if days_info and result["threshold"]
            else "未到续期窗口期（Renewal Restricted）"
        )
        # 截图仍刷新管理页
        driver.get(manage_url)
        time.sleep(2)
        result["due_after"], _ = get_current_due_date(driver)
        result["screenshot"] = take_screenshot(driver, f"s{sid}-04-skipped-final")
        return result

    # ── 正常续期：等待模态框 ──
    print(f"[INFO] [{sid}] 📦 等待续期模态框...")

    # 尝试多种模态框选择器
    modal_found = False
    modal_selectors = [
        f"div#renewService-{sid}",
        "div[id^='renewService-']",
        ".modal:not([style*='display: none'])",
        "div[role='dialog']",
    ]
    for sel in modal_selectors:
        try:
            driver.wait_for_element_visible(sel, timeout=8)
            modal_found = True
            print(f"[INFO] [{sid}] 模态框已打开 (selector: {sel})")
            break
        except:
            continue

    if not modal_found:
        # 可能页面直接跳转（某些情况下无模态框）
        if "invoice" in driver.current_url:
            print(f"[INFO] [{sid}] ✅ 直接跳转到发票页，无需点击 Create Invoice")
            result["success"] = True
            result["message"] = "续期成功（直接跳转发票）"
        else:
            result["message"] = "未找到续期模态框"
            result["screenshot"] = take_screenshot(driver, f"s{sid}-ERROR-no-modal")
            return result

    if not result["success"]:
        take_screenshot(driver, f"s{sid}-03-modal-opened")

        # ── 点击 Create Invoice ──
        print(f"[INFO] [{sid}] 📦 点击 Create Invoice...")
        invoice_btn = None
        invoice_selectors = [
            ("xpath", "//button[contains(text(),'Create Invoice')]"),
            ("xpath", "//button[contains(text(),'Confirm')]"),
            ("xpath", f"//div[@id='renewService-{sid}']//button[@type='submit']"),
            ("css selector", "div[id^='renewService-'] button[type='submit']"),
            ("xpath", "//div[contains(@class,'modal')]//button[@type='submit']"),
            ("xpath", "//div[@role='dialog']//button[@type='submit']"),
        ]
        for by, val in invoice_selectors:
            try:
                el = driver.find_element(by, val)
                if el.is_displayed():
                    invoice_btn = el
                    break
            except:
                continue

        if not invoice_btn:
            result["message"] = "未找到 Create Invoice 按钮"
            result["screenshot"] = take_screenshot(driver, f"s{sid}-ERROR-no-invoice-btn")
            return result

        invoice_btn.click()
        print(f"[INFO] [{sid}] ✅ Create Invoice 已点击，等待跳转...")
        time.sleep(4)
        take_screenshot(driver, f"s{sid}-04-invoice-submitted")

    # ── 判断是否跳转到发票页 ──
    if "invoice" in driver.current_url:
        m = re.search(r'/invoice/([a-f0-9\-]+)', driver.current_url)
        invoice_id = m.group(1)[:8] if m else "unknown"
        print(f"[INFO] [{sid}] 💳 发票页: {invoice_id}")
        take_screenshot(driver, f"s{sid}-05-invoice-page")

        # 免费服务：发票页自动处理，无需支付，稍等后刷新确认
        # 如果存在 Pay / Apply Credit 按钮，也尝试点击
        pay_selectors = [
            ("xpath", "//button[contains(text(),'Apply Credit')]"),
            ("xpath", "//button[contains(text(),'Pay Now')]"),
            ("xpath", "//button[contains(text(),'Pay')]"),
            ("xpath", "//a[contains(text(),'Pay')]"),
            ("xpath", "//button[contains(text(),'Confirm')]"),
        ]
        for by, val in pay_selectors:
            try:
                el = driver.find_element(by, val)
                if el.is_displayed():
                    print(f"[INFO] [{sid}] 💰 点击支付按钮: {el.text.strip()}")
                    el.click()
                    time.sleep(5)
                    take_screenshot(driver, f"s{sid}-06-pay-clicked")
                    break
            except:
                continue

        result["success"] = True
        result["message"] = f"续期成功（发票 {invoice_id}）"
    else:
        # 未跳转发票页，可能已在当前页完成
        time.sleep(3)
        if "invoice" in driver.current_url:
            result["success"] = True
            result["message"] = "续期成功"
        else:
            print(f"[WARN] [{sid}] 未跳转发票页，当前 URL: {driver.current_url}")
            take_screenshot(driver, f"s{sid}-WARN-no-redirect")
            result["message"] = f"续期已执行，但未跳转发票页（请确认）"
            result["success"] = False  # 保守处理

    # ── 刷新管理页获取续期后到期时间 ──
    driver.get(manage_url)
    time.sleep(3)
    result["due_after"], due_after_std = get_current_due_date(driver)
    print(f"[INFO] [{sid}] 续期后到期: {result['due_after']}")

    # 输出标准格式供 Cron 解析
    if due_after_std:
        print(f"到期时间(标准): {due_after_std}")

    result["screenshot"] = take_screenshot(driver, f"s{sid}-99-final")
    return result


# ====================== 主逻辑 ======================
def main():
    print("[INFO] " + "=" * 50)
    print("[INFO] HidenCloud 自动续期脚本 (SeleniumBase)")
    print("[INFO] " + "=" * 50)
    print(f"[INFO] 📂 状态目录: {USER_DATA_DIR}")
    print(f"[INFO] 📸 截图目录: {SCREENSHOT_DIR}")

    driver_kwargs = {
        "headless": True,
        "uc": True,
        "user_data_dir": USER_DATA_DIR,
        "window_size": "1280,753",
    }
    if PROXY_SERVER:
        driver_kwargs["proxy"] = PROXY_SERVER
        print(f"[INFO] 🌐 使用代理: {PROXY_SERVER}")

    driver = Driver(**driver_kwargs)

    try:
        # ---------- 1. 访问主页 ----------
        print(f"[INFO] 🌐 访问主页: {BASE_URL}/dashboard")
        driver.get(f"{BASE_URL}/dashboard")
        time.sleep(3)
        take_screenshot(driver, "01-initial")

        # ---------- 2. 登录判断 ----------
        if "/auth/login" in driver.current_url or driver.is_element_visible("input#username"):
            print("[INFO] 🔒 检测到未登录，开始登录流程")
            take_screenshot(driver, "02-login-page")

            masked_email = mask_email(HIDEN_EMAIL)
            print(f"[INFO] ✍️ 填写邮箱: {masked_email}")
            driver.type("input#username", HIDEN_EMAIL)
            driver.type("input#password", HIDEN_PWD)
            take_screenshot(driver, "03-credentials-filled")

            print("[INFO] ⏳ 等待 Turnstile 加载...")
            time.sleep(5)

            if driver.is_element_present(".cf-turnstile"):
                print("[INFO] 🖱️ 尝试点击 Turnstile...")
                try:
                    driver.uc_gui_click_cf(".cf-turnstile")
                except:
                    driver.click(".cf-turnstile")
                take_screenshot(driver, "04-turnstile-clicked")

                if not wait_for_turnstile_token(driver, timeout=90):
                    take_screenshot(driver, "ERROR-turnstile-timeout")
                    raise Exception("Turnstile 验证超时")
                take_screenshot(driver, "05-token-ready")
            else:
                print("[WARN] 未找到 Turnstile 元素，继续提交...")

            print("[INFO] 🚀 提交登录表单")
            driver.click("button[type='submit']")
            take_screenshot(driver, "06-login-submitted")

            print("[INFO] ⏳ 等待登录跳转...")
            if not wait_for_url_contains(driver, "/dashboard", timeout=45):
                error_text = check_login_error(driver)
                if error_text:
                    take_screenshot(driver, "ERROR-login-failed-message")
                    raise Exception(f"登录失败: {error_text}")
                else:
                    time.sleep(5)
                    if "/dashboard" not in driver.current_url:
                        take_screenshot(driver, "ERROR-login-stuck")
                        raise Exception("登录后卡住，未跳转")

            print("[INFO] ✅ 登录成功")
            take_screenshot(driver, "07-login-success")
        else:
            print("[INFO] ✅ 已登录，跳过登录流程")
            take_screenshot(driver, "02-already-logged-in")

        # ---------- 3. 提取所有服务 ID ----------
        print("[INFO] 🔍 提取服务器 ID 列表...")
        time.sleep(3)
        take_screenshot(driver, "08-dashboard")

        sids = get_all_service_ids(driver)
        if not sids:
            take_screenshot(driver, "ERROR-no-service-ids")
            raise Exception("无法提取任何服务 ID")

        print(f"[INFO] ✅ 共找到 {len(sids)} 个服务")

        # ---------- 4. 逐一续期 ----------
        all_results = []
        for sid in sids:
            print(f"\n[INFO] {'─'*40}")
            print(f"[INFO] 开始处理服务 #{sid}")
            res = renew_one_service(driver, sid)
            res["sid"] = sid
            all_results.append(res)
            # 每个服务完成后立即发 TG 通知（含截图）
            notify_service_result(sid, res)
            time.sleep(2)

        # ---------- 5. 汇总并发送 TG 通知 ----------
        bj_time = get_bj_time()
        total_ok = sum(1 for r in all_results if r["success"])
        total_skip = sum(1 for r in all_results if r["skipped"])
        total_fail = len(all_results) - total_ok - total_skip

        lines = [
            f"🔔 *HidenCloud 续期报告*",
            f"账号: `{HIDEN_EMAIL}`",
            f"✅ 成功 {total_ok} | ⏰ 跳过 {total_skip} | ❌ 失败 {total_fail}",
            "",
        ]
        for r in all_results:
            if r["success"]:
                icon = "✅"
            elif r["skipped"]:
                icon = "⏰"
            else:
                icon = "❌"

            due_change = r["due_before"]
            if r["due_after"] != "N/A" and r["due_after"] != r["due_before"]:
                due_change = f"{r['due_before']} → {r['due_after']}"
            elif r["due_after"] != "N/A":
                due_change = r["due_after"]

            extra = ""
            if r["skipped"] and r["days_left"] is not None:
                extra = f"（剩余 {r['days_left']} 天，需 ≤{r['threshold']} 天可续）"

            lines.append(
                f"{icon} 服务 `#{r['sid']}`: {r['message']}{extra}\n"
                f"   到期: {due_change}"
            )

        lines.append(f"\n时间: {bj_time}")
        lines.append("HidenCloud Auto Renew")
        tg_msg = "\n".join(lines)

        # 汇总只发文字，各服务已单独发过截图
        send_tg_notification(tg_msg)

        print(f"\n[INFO] 🎉 所有任务完成 — ✅{total_ok} ⏰{total_skip} ❌{total_fail}")

    except Exception as e:
        print(f"[ERROR] ❌ 脚本执行失败: {e}")
        err_pic = take_screenshot(driver, "CRITICAL-ERROR")
        send_tg_notification(
            f"❌ *HidenCloud 脚本异常崩溃*\n\n"
            f"账号: `{HIDEN_EMAIL}`\n"
            f"错误: `{str(e)[:300]}`\n"
            f"时间: {get_bj_time()}",
            photo_path=err_pic,
        )
        raise
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
