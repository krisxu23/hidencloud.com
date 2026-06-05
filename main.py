import os
import re
import sys
import time
import random
import requests
from datetime import datetime
from DrissionPage import ChromiumPage, ChromiumOptions


# ─────────────────────────────────────────────
#  工具函数（支持文字与图片发送）
# ─────────────────────────────────────────────

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def send_tg(token: str, chat_id: str, text: str):
    """发送 Telegram 纯文字通知"""
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
            log("📤 Telegram 文字通知已发送")
        else:
            log(f"⚠️ Telegram 文字发送失败: {resp.text[:100]}")
    except Exception as e:
        log(f"❌ Telegram 文字异常: {e}")


def send_tg_photo(token: str, chat_id: str, photo_path: str, caption: str = ""):
    """发送 Telegram 图片通知（带文字介绍）"""
    if not token or not chat_id:
        return
    if not os.path.exists(photo_path):
        log(f"⚠️ 未找到待发送的截图文件: {photo_path}")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        with open(photo_path, 'rb') as f:
            files = {'photo': f}
            data = {
                'chat_id': chat_id,
                'caption': caption,
                'parse_mode': 'HTML'
            }
            resp = requests.post(url, data=data, files=files, timeout=25)
        if resp.status_code == 200:
            log(f"📤 Telegram 截图已成功发送: {os.path.basename(photo_path)}")
            os.remove(photo_path)  # 发送成功后删除本地临时文件
        else:
            log(f"⚠️ Telegram 图片发送失败: {resp.text[:100]}")
    except Exception as e:
        log(f"❌ Telegram 图片异常: {e}")


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
#  Turnstile 破盾器
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
        # 3. 穿透 Shadow Root 执行带偏移量物理点击
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
#  HidenCloud 专属续期核心
# ─────────────────────────────────────────────

class HidenCloudRenewer:
    BASE = "https://dash.hidencloud.com"
    LOGIN_URL = f"{BASE}/auth/login"
    DASHBOARD_URL = f"{BASE}/dashboard"

    def __init__(self, email: str, password: str, proxy: str = "", tg_token: str = "", tg_chat_id: str = ""):
        self.email = email
        self.password = password
        self.proxy = proxy
        self.tg_token = tg_token
        self.tg_chat_id = tg_chat_id
        self.page: ChromiumPage | None = None
        self.safe_email = email.replace('@', '_').replace('.', '_')

    def _make_page(self) -> ChromiumPage:
        co = ChromiumOptions()
        if os.path.exists('/usr/bin/google-chrome'):
            co.set_browser_path('/usr/bin/google-chrome')
            
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
        
        co.headless(False)  # 有头配合 xvfb 运行更稳定
        
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
        time.sleep(2)
        
        # 缓存检查 1
        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✨ [{self.email}] 缓存有效，已处于后台！")
            return True

        solver.solve(timeout=8) 
        time.sleep(random.uniform(2, 4))

        # 缓存检查 2
        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✨ [{self.email}] 过盾后自动进入后台！")
            return True

        # ═════════════════════════════════════════════
        #  🎯【针对性修复】：根据 F12 结构精确定位输入框
        # ═════════════════════════════════════════════
        try:
            # 1. 寻找账号输入框：优先使用截图中的 id="email"，并用中文 placeholder 做保底
            email_ele = page.ele(
                'css:input#email, '
                'input[id="email"], '
                'input[placeholder*="邮箱"], '
                'input[placeholder*="邮"]', 
                timeout=12
            )
            if not email_ele:
                raise Exception("无法定位到账号/用户名输入框")
                
            email_ele.click()
            # 组合物理键全选清空
            page.actions.key_down('control').send_key('a').key_up('control').send_key('backspace')
            time.sleep(0.3)
            
            # 仿真打字输入用户名
            for char in self.email:
                email_ele.input(char, clear=False)
                time.sleep(random.uniform(0.02, 0.06))
            log("✍️ 用户名/邮箱字段已顺利填入")
            
            # 2. 寻找密码输入框：优先使用截图中的 id="password"
            pwd_ele = page.ele(
                'css:input#password, '
                'input[id="password"], '
                'input[type="password"]', 
                timeout=6
            )
            if not pwd_ele:
                raise Exception("无法定位到密码输入框")
                
            pwd_ele.click()
            page.actions.key_down('control').send_key('a').key_up('control').send_key('backspace')
            time.sleep(0.3)
            
            # 仿真打字输入密码
            for char in self.password:
                pwd_ele.input(char, clear=False)
                time.sleep(random.uniform(0.02, 0.06))
            log("✍️ 密码字段已顺利填入")
            
        except Exception as e:
            log(f"❌ 填写表单失败: {e}，当前页 URL: {page.url}")
            pic_path = f"err_form_{self.safe_email}.png"
            page.get_screenshot(path=pic_path)
            send_tg_photo(self.tg_token, self.tg_chat_id, pic_path, f"❌ <b>{self.email}</b> 填写表单失败: {e}\nURL: {page.url}")
            return False

        # 再次确认过盾情况
        solver.solve()

        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✅ [{self.email}] 成功进入主页")
            return True

        # 点击登录提交按钮
        try:
            btn = (
                page.ele('css:button[type="submit"]') or 
                page.ele('text:登录') or
                page.ele('xpath://button[contains(text(),"登录")]') or
                page.ele('css:.btn-primary')
            )
            if btn:
                btn.click()
                log("🖱️ 已点击登录提交按钮")
        except Exception as e:
            log(f"❌ 点击登录按钮失败: {e}")
            return False

        time.sleep(5)

        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✅ [{self.email}] 登录成功")
            return True

        log(f"❌ [{self.email}] 登录终审失败，当前 URL: {page.url}")
        pic_path = f"err_login_{self.safe_email}.png"
        page.get_screenshot(path=pic_path)
        send_tg_photo(self.tg_token, self.tg_chat_id, pic_path, f"❌ <b>{self.email}</b> 登录失败\nURL: {page.url}")
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

        log(f"🔄 正在处理服务 #{service_id}...")
        manage_url = f"{self.BASE}/service/{service_id}/manage"
        page.get(manage_url)
        time.sleep(4)

        token = ''
        token_ele = page.ele('css:input[name="_token"]')
        if token_ele:
            token = token_ele.value

        ui_success = False
        try:
            renew_btn = (
                page.ele('text:Renew', timeout=5) or 
                page.ele('xpath://*[contains(text(),"Renew")]') or
                page.ele('css:.btn-success') or
                page.ele('css:[href*="renew"]')
            )
            if not renew_btn:
                raise Exception("无法定位页面的 'Renew' 按钮")
            
            renew_btn.click()
            log("🖱️ 已成功点击外部 'Renew' 按钮，等待模态框弹出...")
            time.sleep(3)

            invoice_btn = (
                page.ele('text:Create Invoice', timeout=5) or
                page.ele('xpath://*[contains(text(),"Create Invoice")]') or
                page.ele('css:.btn-warning') or 
                page.ele('css:[type="submit"]')
            )
            if not invoice_btn:
                raise Exception("无法定位模态框中的 'Create Invoice' 按钮")

            invoice_btn.click()
            log("🖱️ 已成功点击模态框中的 'Create Invoice' 按钮，正在开票...")
            time.sleep(5)

            if 'invoice' in page.url or page.ele('text:Invoice') or page.ele('text:success'):
                m = re.search(r'/invoice/([a-f0-9\-]+)', page.url)
                invoice_id = m.group(1)[:8] if m else 'SUCCESS'
                
                result['success'] = True
                result['message'] = '续期成功（UI全自动点击）'
                result['invoice_id'] = invoice_id
                ui_success = True
                
                log(f"🎉 [{self.email}] 服务 #{service_id} UI 续期成功！发票ID: {invoice_id}")
                
                pic_path = f"success_ui_{service_id}_{self.safe_email}.png"
                page.get_screenshot(path=pic_path)
                send_tg_photo(self.tg_token, self.tg_chat_id, pic_path, 
                              f"✅ <b>{self.email}</b>\n服务 #{service_id} 续期成功（网页端自动点击）！\n发票ID: <code>{invoice_id}</code>")
                return result

        except Exception as ui_err:
            log(f"⚠️ UI 点击流遇到阻碍: {ui_err}")

        # API POST 保底方案
        if not ui_success:
            log(f"📡 #{service_id} 启动底层 API POST 保底续期策略...")
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
                
                proxies = None
                if self.proxy:
                    p_str = self.proxy if "://" in self.proxy else f"socks5://{self.proxy}"
                    proxies = {'http': p_str, 'https': p_str}

                post_data = {'_token': token, 'days': '7'}
                resp = s.post(f"{self.BASE}/service/{service_id}/renew", data=post_data, headers=headers, proxies=proxies, timeout=20)

                if 'invoice' in resp.url or resp.status_code in (200, 302):
                    m = re.search(r'/invoice/([a-f0-9\-]+)', resp.url)
                    invoice_id = m.group(1)[:8] if m else 'POST_OK'
                    result['success'] = True
                    result['message'] = '续期成功（POST保底）'
                    result['invoice_id'] = invoice_id
                    
                    page.get(manage_url)
                    time.sleep(2)
                    pic_path = f"success_post_{service_id}_{self.safe_email}.png"
                    page.get_screenshot(path=pic_path)
                    send_tg_photo(self.tg_token, self.tg_chat_id, pic_path, 
                                  f"✅ <b>{self.email}</b>\n服务 #{service_id} 续期成功（POST保底）！\n发票ID: <code>{invoice_id}</code>")
                else:
                    result['message'] = f'POST 反馈异常，状态码: {resp.status_code}'
            except Exception as post_err:
                err_msg = str(post_err)
                if "Missing dependencies for SOCKS support" in err_msg:
                    result['message'] = 'Python缺失pysocks依赖库，请运行 pip install pysocks'
                else:
                    result['message'] = f'POST 异常: {err_msg}'

        if not result['success']:
            log(f"❌ #{service_id} 续期最终判定失败: {result['message']}")
            pic_path = f"fail_renew_{service_id}_{self.safe_email}.png"
            page.get_screenshot(path=pic_path)
            send_tg_photo(self.tg_token, self.tg_chat_id, pic_path, 
                          f"❌ <b>{self.email}</b>\n服务 #{service_id} 续期失败！\n关键原因: {result['message']}")

        return result

    def run(self):
        try:
            if not self.login():
                return [{'service_id': 'N/A', 'success': False, 'message': '登录未通过'}]
            services = self.get_services()
            if not services:
                return [{'service_id': 'N/A', 'success': False, 'message': '未提取到可用服务'}]
            
            results = []
            for svc in services:
                results.append(self.renew_service(svc['id']))
                time.sleep(4)
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
        log("❌ 未检测到 ACCOUNTS 环境变量")
        sys.exit(1)

    accounts = parse_accounts(accounts_raw)
    all_results = []
    account_summaries = []

    for email, password in accounts:
        log(f"\n🚀 开始调配账号: {email}")
        renewer = HidenCloudRenewer(email, password, proxy, tg_token, tg_chat_id)
        results = renewer.run()
        all_results.extend(results)

        lines = [f"📧 <b>{email}</b>"]
        for r in results:
            icon = "✅" if r.get('success') else "❌"
            inv = f" | 发票: <code>{r['invoice_id']}</code>" if r.get('invoice_id') else ""
            lines.append(f"  {icon} 服务 #{r['service_id']}: {r['message']}{inv}")
        account_summaries.append('\n'.join(lines))

    total_ok = sum(1 for r in all_results if r.get('success'))
    tg_msg = f"🔔 <b>HidenCloud 续期总核验报告</b>\n📊 成功 {total_ok} / 失败 {len(all_results)-total_ok}\n\n" + '\n\n'.join(account_summaries)
    send_tg(tg_token, tg_chat_id, tg_msg)


if __name__ == '__main__':
    main()
