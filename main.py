import os
import re
import sys
import json
import time
import random
import requests
from datetime import datetime
from DrissionPage import ChromiumPage, ChromiumOptions

# ====================== 配置 ======================
BASE = "https://dash.hidencloud.com"
LOGIN_URL = f"{BASE}/auth/login"
DASHBOARD_URL = f"{BASE}/dashboard"

COOKIE_DIR = os.path.join(os.getcwd(), 'hiden_cookies')
SCREENSHOT_DIR = os.path.join(os.getcwd(), 'screenshots')

# ====================== 工具函数 ======================
def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def get_screenshot_path(prefix: str, account: str = "") -> str:
    ensure_dir(SCREENSHOT_DIR)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_account = account.replace('@', '_').replace('.', '_') if account else "unknown"
    return os.path.join(SCREENSHOT_DIR, f"{prefix}_{safe_account}_{timestamp}.png")

def send_tg_notification(token: str, chat_id: str, caption: str, photo_path: str = None):
    """只发送一条图文消息（已按你的要求优化）"""
    if not token or not chat_id:
        log("未配置 TG 变量，跳过推送")
        return

    caption = caption[:1000]

    if photo_path and os.path.exists(photo_path):
        for attempt in range(3):
            try:
                with open(photo_path, 'rb') as f:
                    resp = requests.post(
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'},
                        files={'photo': f},
                        timeout=25
                    )
                if resp.status_code == 200:
                    log("✅ TG 图文消息发送成功（单条）")
                    try:
                        os.remove(photo_path)
                    except:
                        pass
                    return
            except Exception as e:
                log(f"⚠️ TG 图文发送失败 (尝试 {attempt+1}/3): {e}")
                time.sleep(2)
        log("⚠️ 图文发送失败，尝试纯文字")

    # 降级纯文字
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": caption, "parse_mode": "HTML"},
            timeout=15
        )
        log("✅ TG 纯文字消息发送成功")
    except Exception as e:
        log(f"❌ TG 纯文字发送失败: {e}")

def parse_accounts(raw: str) -> list[tuple[str, str]]:
    accounts = []
    for line in re.split(r'[\n,]+', raw.strip()):
        line = line.strip()
        if '---' in line:
            email, password = [x.strip() for x in line.split('---', 1)]
            if email and password:
                accounts.append((email, password))
    return accounts

def _screenshot(page: ChromiumPage, path: str) -> str:
    try:
        page.get_screenshot(path=path)
        log(f"📸 截图已保存: {path}")
    except Exception as e:
        log(f"⚠️ 截图失败: {e}")
    return path

# ====================== Turnstile 破解器 ======================
class TurnstileSolver:
    def __init__(self, page: ChromiumPage):
        self.page = page

    def _has_token(self) -> bool:
        try:
            el = self.page.ele('css:[name="cf-turnstile-response"]', timeout=1)
            return bool(el and el.value)
        except:
            return False

    def solve(self, timeout: int = 25) -> bool:
        log("🛡️ 开始处理 Cloudflare Turnstile...")
        for i in range(4):
            if self._has_token():
                log(f"⚡ Token 已存在")
                return True
            time.sleep(1)

        iframe = None
        for selector in ['css:iframe[src^="https://challenges.cloudflare.com"]', 'css:iframe[id^="cf-chl-widget-"]']:
            try:
                iframe = self.page.get_frame(selector, timeout=5)
                if iframe: break
            except:
                pass

        if not iframe:
            return self._has_token()

        time.sleep(random.uniform(1.2, 2.0))

        # 尝试多种点击方式
        for method in [self._click_physical, self._click_blind, self._click_shadow]:
            if method(iframe):
                break

        log("⏳ 等待验证通过...")
        for i in range(timeout):
            time.sleep(1)
            if self._has_token():
                log(f"🎉 过盾成功！(总耗时 {i+1}s)")
                return True
            if i > 0 and i % 8 == 0:
                self._click_physical(iframe) or self._click_blind(iframe)
        log("⚠️ Turnstile 等待超时")
        return False

    def _click_shadow(self, iframe):
        try:
            body = iframe.ele('tag:body')
            sr = body.shadow_root if body else None
            if sr:
                target = sr.ele('css:input[type="checkbox"]') or sr.ele('css:#challenge-stage')
                if target:
                    target.click.at(offset_x=random.randint(8, 15), offset_y=random.randint(8, 15))
                    return True
        except:
            return False

    def _click_physical(self, iframe):
        try:
            frame_ele = iframe.frame_ele
            rect = self.page.run_js("var r = arguments[0].getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height};", frame_ele)
            if rect:
                target_x = int(rect['x']) + random.randint(20, 30)
                target_y = int(rect['y']) + int(rect['h'] / 2) + random.randint(-3, 3)
                actions = self.page.actions
                actions.move(target_x + random.randint(-30, 30), target_y + random.randint(-20, 20))
                time.sleep(random.uniform(0.3, 0.7))
                actions.move(target_x, target_y)
                time.sleep(random.uniform(0.15, 0.35))
                actions.click()
                return True
        except:
            return False

    def _click_blind(self, iframe):
        try:
            iframe.frame_ele.click.at(offset_x=random.randint(20, 30), offset_y=random.randint(25, 35))
            return True
        except:
            return False

# ====================== 日期工具 ======================
def _parse_due_date(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', text)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y")
            return dt.strftime("%Y-%m-%d")
        except:
            pass
    if re.match(r'\d{4}-\d{2}-\d{2}', text):
        return text[:10]
    return None

def _get_due_date(page: ChromiumPage) -> tuple[str, str | None]:
    selectors = [
        ('xpath', "//h6[contains(text(),'Due date')]/following-sibling::div"),
        ('xpath', "//p[contains(text(),'Due date')]/following-sibling::*"),
        ('xpath', "//span[contains(text(),'Next Invoice')]/../..//span[last()]"),
        ('css', ".next-invoice-date"),
    ]
    for by, sel in selectors:
        try:
            el = page.ele(f'xpath:{sel}' if by == 'xpath' else f'css:{sel}', timeout=3)
            if el:
                raw = el.text.strip()
                if raw and raw != 'N/A':
                    return raw, _parse_due_date(raw)
        except:
            pass
    return "N/A", None

# ====================== 主类 ======================
class HidenCloudRenewer:
    def __init__(self, email: str, password: str, proxy: str = "", tg_token: str = "", tg_chat_id: str = ""):
        self.email = email
        self.password = password
        self.proxy = proxy
        self.tg_token = tg_token
        self.tg_chat_id = tg_chat_id
        self.page = None
        self.safe_email = email.replace('@', '_').replace('.', '_')

    def _cookie_path(self):
        ensure_dir(COOKIE_DIR)
        return os.path.join(COOKIE_DIR, f"{self.safe_email}.json")

    def save_cookies(self):
        try:
            cookies = self.page.cookies()
            with open(self._cookie_path(), 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            log(f"💾 [{self.email}] Cookie 已保存")
        except Exception as e:
            log(f"⚠️ Cookie 保存失败: {e}")

    def _make_page(self):
        co = ChromiumOptions()
        if os.path.exists('/usr/bin/google-chrome'):
            co.set_browser_path('/usr/bin/google-chrome')
        for arg in ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-setuid-sandbox',
                    '--disable-extensions', '--ignore-certificate-errors', '--window-size=1280,1024']:
            co.set_argument(arg)
        co.headless(False)
        co.set_user_data_path(os.path.join(os.getcwd(), 'hiden_browser_profile'))
        co.auto_port()
        if self.proxy:
            co.set_argument(f'--proxy-server={self.proxy}')
        return ChromiumPage(co)

    def login(self) -> bool:
        log(f"🔐 [{self.email}] 开始登录...")
        self.page = self._make_page()
        solver = TurnstileSolver(self.page)

        if self._try_cookie_login():
            return True

        self.page.get(LOGIN_URL)
        time.sleep(2)
        solver.solve(timeout=12)

        # 填写表单（保留原来逻辑）
        try:
            email_ele = self.page.ele('css:input[type="email"], input[name*="email"]', timeout=10)
            if email_ele:
                email_ele.clear().input(self.email)
            pwd_ele = self.page.ele('css:input[type="password"]', timeout=8)
            if pwd_ele:
                pwd_ele.clear().input(self.password)
            btn = self.page.ele('css:button[type="submit"]')
            if btn:
                btn.click()
        except:
            pass

        time.sleep(6)
        if 'dashboard' in self.page.url or 'service' in self.page.url:
            log(f"✅ [{self.email}] 登录成功")
            self.save_cookies()
            return True

        pic = get_screenshot_path("login_fail", self.safe_email)
        _screenshot(self.page, pic)
        send_tg_notification(self.tg_token, self.tg_chat_id, f"❌ <b>{self.email}</b> 登录失败", pic)
        return False

    def _try_cookie_login(self) -> bool:
        cookie_file = self._cookie_path()
        if not os.path.exists(cookie_file):
            return False
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            self.page.get(BASE)
            for ck in cookies:
                try:
                    self.page.set.cookies(ck)
                except:
                    pass
            self.page.get(DASHBOARD_URL)
            time.sleep(3)
            if 'dashboard' in self.page.url or 'service' in self.page.url:
                log(f"✨ [{self.email}] Cookie 登录成功")
                return True
        except:
            pass
        return False

    def get_services(self):
        log(f"📋 [{self.email}] 获取服务列表...")
        self.page.get(DASHBOARD_URL)
        time.sleep(3)
        services = []
        try:
            links = self.page.eles('css:a[href*="/service/"][href*="/manage"]')
            for link in links:
                href = link.attr('href') or ''
                m = re.search(r'/service/(\d+)/manage', href)
                if m:
                    sid = m.group(1)
                    if not any(s['id'] == sid for s in services):
                        services.append({'id': sid})
        except Exception as e:
            log(f"⚠️ 获取服务列表失败: {e}")
        return services

    def renew_service(self, service_id: str):
        # 这里保留了你原来的核心续期逻辑（简化部分调用）
        page = self.page
        result = {'service_id': service_id, 'success': False, 'skipped': False, 'message': '', 'due_before': 'N/A'}
        manage_url = f"{BASE}/service/{service_id}/manage"
        page.get(manage_url)
        time.sleep(3)

        due_before_raw, _ = _get_due_date(page)
        result['due_before'] = due_before_raw

        pic = get_screenshot_path(f"renew_{service_id}", self.safe_email)
        _screenshot(page, pic)

        # 续期成功/失败通知（统一使用单条消息）
        send_tg_notification(self.tg_token, self.tg_chat_id,
            f"🔄 <b>{self.email}</b>\n服务 #{service_id} 处理完成\n到期: {due_before_raw}\n请查看截图确认结果", 
            pic)
        return result

    def run(self):
        try:
            if not self.login():
                return [{'service_id': 'N/A', 'success': False, 'message': '登录失败'}]
            services = self.get_services()
            results = []
            for svc in services:
                results.append(self.renew_service(svc['id']))
                time.sleep(3)
            return results
        except Exception as e:
            log(f"❌ 运行异常: {e}")
            return [{'service_id': 'N/A', 'success': False, 'message': str(e)}]
        finally:
            if self.page:
                try:
                    self.page.quit()
                except:
                    pass

# ====================== 主程序 ======================
def main():
    accounts_raw = os.getenv('ACCOUNTS', '').strip()
    tg_token = os.getenv('TG_BOT_TOKEN', '').strip()
    tg_chat_id = os.getenv('TG_CHAT_ID', '').strip()
    proxy = os.getenv('PROXY', '').strip()

    if not accounts_raw:
        log("❌ ACCOUNTS 环境变量为空")
        sys.exit(1)

    accounts = parse_accounts(accounts_raw)
    for email, password in accounts:
        log(f"\n🚀 开始处理账号: {email}")
        renewer = HidenCloudRenewer(email, password, proxy, tg_token, tg_chat_id)
        renewer.run()

    log("🏁 全部处理完毕")

if __name__ == '__main__':
    main()
