import os
import re
import sys
import time
import random
import json
import requests
from datetime import datetime
from DrissionPage import ChromiumPage, ChromiumOptions


# ─────────────────────────────────────────────
#  工具函数
# ─────────────────────────────────────────────

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def send_tg(token: str, chat_id: str, text: str):
    """发送 Telegram 通知"""
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=15)
        if resp.status_code == 200:
            log("📤 Telegram 通知已发送")
        else:
            log(f"⚠️ Telegram 发送失败: {resp.text[:100]}")
    except Exception as e:
        log(f"❌ Telegram 异常: {e}")


def parse_accounts(raw: str) -> list[tuple[str, str]]:
    """解析多账号"""
    accounts = []
    lines = re.split(r'[\n,]+', raw.strip())
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if '---' in line:
            parts = line.split('---', 1)
            email = parts[0].strip()
            password = parts[1].strip()
            if email and password:
                accounts.append((email, password))
        else:
            log(f"⚠️ 无法解析行: {line}")
    return accounts


# ─────────────────────────────────────────────
#  Turnstile 破解器（融合 Weirdhost 优秀算法）
# ─────────────────────────────────────────────

class TurnstileSolver:
    def __init__(self, page: ChromiumPage):
        self.page = page

    def solve(self, timeout: int = 25) -> bool:
        log("🛡️ 开始处理 Cloudflare Turnstile...")

        # 1. 检查是否自动通过
        for i in range(4):
            try:
                resp = self.page.ele('css:[name="cf-turnstile-response"]', timeout=1)
                if resp and resp.value:
                    log(f"⚡ [自动通过] Token 已存在，无需点击 (耗时 {i}s)")
                    return True
            except Exception:
                pass
            time.sleep(1)

        # 2. 锁定 iframe
        iframe = None
        for selector in [
            'css:iframe[src^="https://challenges.cloudflare.com"]',
            'css:iframe[id^="cf-chl-widget-"]',
        ]:
            try:
                iframe = self.page.get_frame(selector, timeout=5)
                if iframe:
                    break
            except Exception:
                pass

        if not iframe:
            log("❌ 找不到 Turnstile iframe")
            resp = self.page.ele('css:[name="cf-turnstile-response"]', timeout=1)
            return True if (resp and resp.value) else False

        time.sleep(random.uniform(1.5, 2.5))

        click_success = False
        # 3. 穿透 Closed Shadow Root 并使用【带坐标偏移的物理点击】
        try:
            body = iframe.ele('tag:body')
            sr = body.shadow_root if body else None
            if sr:
                target = (
                    sr.ele('css:input[type="checkbox"]') or
                    sr.ele('css:#challenge-stage') or
                    sr.ele('css:div.main-wrapper') or
                    sr.ele('css:#content')
                )
                if target:
                    log("鼠标在 ShadowRoot 内部找到目标，执行带偏移量的物理点击...")
                    target.click.at(offset_x=10, offset_y=10)
                    click_success = True
        except Exception as e:
            log(f"⚠️ Shadow Root 穿透点击失败: {e}")

        # 4. 保底方案：Iframe 坐标盲点
        if not click_success:
            log("🏹 [保底方案] 执行 Iframe 坐标偏移盲点...")
            try:
                iframe.frame_ele.click.at(offset_x=25, offset_y=30)
                click_success = True
            except Exception as e:
                log(f"❌ 盲点失败: {e}")

        if not click_success:
            return False

        # 5. 等待验证结果
        log("⏳ 点击已执行，等待验证通过...")
        for i in range(timeout):
            time.sleep(1)
            try:
                resp = self.page.ele('css:[name="cf-turnstile-response"]', timeout=1)
                if resp and resp.value:
                    log(f"🎉 过盾成功！Token 已注入 (总耗时 {i+1}s)")
                    return True
            except Exception:
                pass

        log("⚠️ Turnstile 等待超时")
        return False


# ─────────────────────────────────────────────
#  HidenCloud 续期核心
# ─────────────────────────────────────────────

class HidenCloudRenewer:
    BASE = "https://dash.hidencloud.com"
    LOGIN_URL = f"{BASE}/auth/login"
    DASHBOARD_URL = f"{BASE}/dashboard"

    def __init__(self, email: str, password: str, proxy: str = ""):
        self.email = email
        self.password = password
        self.proxy = proxy
        self.page: ChromiumPage | None = None

    def _make_page(self) -> ChromiumPage:
        co = ChromiumOptions()
        
        # 针对 Linux 环境可指定 Chrome 路径（如本地运行可注释此行）
        if os.path.exists('/usr/bin/google-chrome'):
            co.set_browser_path('/usr/bin/google-chrome')
            
        # 融合 Weirdhost 规避高强度风控的核心参数
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-setuid-sandbox') 
        co.set_argument('--disable-software-rasterizer')
        co.set_argument('--disable-extensions')
        co.set_argument('--disable-popup-blocking')
        co.set_argument('--ignore-certificate-errors')
        co.set_argument('--no-first-run')
        co.set_argument('--no-default-browser-check')
        co.set_argument('--window-size=1280,1024')
        
        # 【核心技巧】关闭无头模式，伪装成真实有头浏览器
        co.headless(False)
        
        # 保持持久化缓存目录
        profile_path = os.path.join(os.getcwd(), 'hiden_browser_profile')
        co.set_user_data_path(profile_path)
        co.auto_port()

        if self.proxy:
            proxy_url = self.proxy if "://" in self.proxy else f"socks5://{self.proxy}"
            co.set_argument(f'--proxy-server={proxy_url}')
            log(f"🌐 代理已配置: {proxy_url}")
            
        return ChromiumPage(co)

    def login(self) -> bool:
        log(f"🔐 [{self.email}] 开始登录...")
        self.page = self._make_page()
        page = self.page
        solver = TurnstileSolver(page)

        page.get(self.LOGIN_URL)
        
        # 前置检查
        solver.solve(timeout=8) 
        time.sleep(random.uniform(2, 4))

        try:
            email_ele = page.ele('css:input[type="email"]', timeout=10) or page.ele('css:input[name*="email"]')
            if not email_ele:
                raise Exception("找不到账号输入框")
                
            # 模拟人类慢速输入
            email_ele.click()
            email_ele.clear()
            for char in self.email:
                email_ele.input(char, clear=False)
                time.sleep(random.uniform(0.05, 0.15))
            
            pwd_ele = page.ele('css:input[type="password"]')
            if pwd_ele:
                pwd_ele.click()
                pwd_ele.clear()
                for char in self.password:
                    pwd_ele.input(char, clear=False)
                    time.sleep(random.uniform(0.05, 0.15))
            
        except Exception as e:
            log(f"❌ 填写表单失败: {e}")
            return False

        # 破译登录表单 Turnstile
        solver.solve()

        # 提交
        try:
            btn = page.ele('css:button[type="submit"]') or page.ele('xpath://button[contains(text(),"Sign in")]')
            if btn:
                btn.click()
            else:
                return False
        except Exception as e:
            log(f"❌ 点击登录按钮失败: {e}")
            return False

        time.sleep(5)

        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✅ [{self.email}] 登录成功")
            return True

        log(f"❌ [{self.email}] 登录失败，当前 URL: {page.url}")
        return False

    def get_services(self) -> list[dict]:
        page = self.page
        log(f"📋 [{self.email}] 获取服务列表...")
        page.get(self.DASHBOARD_URL)
        time.sleep(3)

        services = []
        try:
            links = page.eles('css:a[href*="/service/"][href*="/manage"]')
            for link in links:
                href = link.attr('href') or ''
                m = re.search(r'/service/(\d+)/manage', href)
                if m:
                    sid = m.group(1)
                    if not any(s['id'] == sid for s in services):
                        services.append({'id': sid})
        except Exception as e:
            log(f"⚠️ 抓取服务链接失败: {e}")
        return services

    def renew_service(self, service_id: str) -> dict:
        page = self.page
        result = {'service_id': service_id, 'success': False, 'message': '', 'invoice_id': ''}

        log(f"🔄 续期服务 #{service_id}...")
        manage_url = f"{self.BASE}/service/{service_id}/manage"
        page.get(manage_url)
        time.sleep(3)

        # 提取 Token
        token = ''
        token_ele = page.ele('css:input[name="_token"]')
        if token_ele:
            token = token_ele.value

        # 点击 Renew 弹出模态框
        try:
            renew_btn = page.ele('xpath://button[contains(text(),"Renew")]') or page.ele('css:[data-action*="renew"]')
            if renew_btn:
                renew_btn.click()
                time.sleep(2)
        except Exception:
            pass

        # 点击 Create Invoice
        try:
            confirm_btn = page.ele('xpath://button[contains(text(),"Create Invoice")]')
            if confirm_btn:
                confirm_btn.click()
                time.sleep(4)
                if 'invoice' in page.url:
                    m = re.search(r'/invoice/([a-f0-9\-]+)', page.url)
                    invoice_id = m.group(1)[:8] if m else ''
                    result['success'] = True
                    result['message'] = '续期成功（UI）'
                    result['invoice_id'] = invoice_id
                    return result
        except Exception:
            pass

        # API 保底
        log(f"📡 #{service_id} 启动 API POST 保底方案...")
        try:
            s = requests.Session()
            for ck in page.cookies():
                s.cookies.set(ck.get('name', ''), ck.get('value', ''), domain=ck.get('domain', ''))

            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': self.BASE,
                'Referer': manage_url,
                'User-Agent': page.user_agent
            }
            proxies = {'http': f'socks5://{self.proxy}', 'https': f'socks5://{self.proxy}'} if self.proxy else None
            resp = s.post(f"{self.BASE}/service/{service_id}/renew", data={'_token': token, 'days': '7'}, headers=headers, proxies=proxies, timeout=20)

            if 'invoice' in resp.url or resp.status_code in (200, 302):
                m = re.search(r'/invoice/([a-f0-9\-]+)', resp.url)
                invoice_id = m.group(1)[:8] if m else ''
                result['success'] = True
                result['message'] = '续期成功（POST）'
                result['invoice_id'] = invoice_id
            else:
                result['message'] = f'POST 状态码异常: {resp.status_code}'
        except Exception as e:
            result['message'] = f'POST 异常: {e}'

        return result

    def run(self):
        try:
            if not self.login():
                return [{'service_id': 'N/A', 'success': False, 'message': '登录失败'}]
            services = self.get_services()
            if not services:
                return [{'service_id': 'N/A', 'success': False, 'message': '未找到服务'}]
            
            results = []
            for svc in services:
                results.append(self.renew_service(svc['id']))
                time.sleep(3)
            return results
        finally:
            if self.page:
                try: self.page.quit()
                except: pass


# ─────────────────────────────────────────────
#  主入口
# ─────────────────────────────────────────────

def main():
    accounts_raw = os.getenv('ACCOUNTS', '').strip()
    tg_token     = os.getenv('TG_BOT_TOKEN', '').strip()
    tg_chat_id   = os.getenv('TG_CHAT_ID', '').strip()
    proxy        = os.getenv('PROXY', '').strip()

    if not accounts_raw:
        log("❌ ACCOUNTS 环境变量为空")
        sys.exit(1)

    accounts = parse_accounts(accounts_raw)
    all_results = []
    account_summaries = []

    for email, password in accounts:
        log(f"\n🚀 开始处理: {email}")
        renewer = HidenCloudRenewer(email, password, proxy)
        results = renewer.run()
        all_results.extend(results)

        lines = [f"📧 <b>{email}</b>"]
        for r in results:
            icon = "✅" if r.get('success') else "❌"
            inv = f" | 发票: <code>{r['invoice_id']}</code>" if r.get('invoice_id') else ""
            lines.append(f"  {icon} 服务 #{r['service_id']}: {r['message']}{inv}")
        account_summaries.append('\n'.join(lines))

    # 发送通知
    total_ok = sum(1 for r in all_results if r.get('success'))
    tg_msg = f"🔔 <b>HidenCloud 续期报告</b>\n📊 成功 {total_ok} / 失败 {len(all_results)-total_ok}\n\n" + '\n\n'.join(account_summaries)
    send_tg(tg_token, tg_chat_id, tg_msg)


if __name__ == '__main__':
    main()
