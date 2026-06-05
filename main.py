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
        log("🛡️ 检测 Cloudflare 状态...")
        for i in range(5):
            try:
                resp = self.page.ele('css:[name="cf-turnstile-response"]', timeout=1)
                if resp and resp.value:
                    log(f"⚡ Token 已存在，无需点击")
                    return True
            except:
                pass
            time.sleep(1)

        iframe = None
        for selector in [
            'css:iframe[src^="https://challenges.cloudflare.com"]',
            'css:iframe[id^="cf-chl-widget-"]',
        ]:
            try:
                iframe = self.page.get_frame(selector, timeout=3)
                if iframe:
                    break
            except:
                pass

        if not iframe:
            return True

        try:
            body = iframe.ele('tag:body')
            sr = body.shadow_root if body else None
            if sr:
                target = sr.ele('css:input[type="checkbox"]') or sr.ele('css:#challenge-stage')
                if target:
                    target.click.at(offset_x=10, offset_y=10)
                    time.sleep(2)
                    return True
        except:
            pass

        return True


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
        co.set_argument('--window-size=1280,1024')
        
        co.headless(False)
        
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
        time.sleep(3)
        
        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✨ [{self.email}] 缓存有效，已直达后台！")
            return True

        solver.solve() 
        time.sleep(3)  # 给充足的表单渲染时间

        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✨ [{self.email}] 自动重定向进入后台！")
            return True

        # ═════════════════════════════════════════════
        #  🎯【针对性大修】：完全独立的单步级联查找机制
        # ═════════════════════════════════════════════
        try:
            log(f"当前页面标题: [{page.title}]，开始单步探测输入框...")
            
            # 1. 寻找账号输入框
            email_ele = None
            email_selectors = [
                '#email',                 # 方案 A: 极简 ID 寻找
                'tag:input@id=email',      # 方案 B: 精确属性寻找
                'css:input[id="email"]',   # 方案 C: 标准 CSS
                '@placeholder*邮箱',       # 方案 D: 模糊提示词
                'tag:input'                # 方案 E: 兜底页面第一个输入框
            ]
            
            for sel in email_selectors:
                try:
                    el = page.ele(sel, timeout=1)
                    if el and el.is_displayed:
                        email_ele = el
                        log(f"🎯 账号框精确定位成功，匹配选择器: [{sel}]")
                        break
                except:
                    pass

            if not email_ele:
                raise Exception("页面上所有已知的账号输入框定位方法均告失败")
                
            email_ele.click()
            page.actions.key_down('control').send_key('a').key_up('control').send_key('backspace')
            time.sleep(0.2)
            
            for char in self.email:
                email_ele.input(char, clear=False)
                time.sleep(random.uniform(0.01, 0.04))
            
            # 2. 寻找密码输入框
            pwd_ele = None
            pwd_selectors = [
                '#password',
                'tag:input@id=password',
                'css:input[id="password"]',
                'css:input[type="password"]'
            ]
            
            for sel in pwd_selectors:
                try:
                    el = page.ele(sel, timeout=1)
                    if el and el.is_displayed:
                        pwd_ele = el
                        log(f"🎯 密码框精确定位成功，匹配选择器: [{sel}]")
                        break
                except:
                    pass

            if not pwd_ele:
                raise Exception("页面上所有已知的密码输入框定位方法均告失败")
                
            pwd_ele.click()
            page.actions.key_down('control').send_key('a').key_up('control').send_key('backspace')
            time.sleep(0.2)
            
            for char in self.password:
                pwd_ele.input(char, clear=False)
                time.sleep(random.uniform(0.01, 0.04))
                
            log("✍️ 账号与密码表单字段已全部填入完成")
            
        except Exception as e:
            log(f"❌ 填写表单失败: {e}，当前页 URL: {page.url}")
            pic_path = f"err_form_{self.safe_email}.png"
            page.get_screenshot(path=pic_path)
            send_tg_photo(self.tg_token, self.tg_chat_id, pic_path, f"❌ <b>{self.email}</b> 填写表单失败: {e}\nURL: {page.url}")
            return False

        # 3. 寻找并点击登录按钮
        btn_ele = None
        btn_selectors = [
            'css:button[type="submit"]',
            'text:登录',
            'xpath://button[contains(text(),"登录")]',
            'css:.btn-primary'
        ]
        for sel in btn_selectors:
            try:
                el = page.ele(sel, timeout=1)
                if el:
                    btn_ele = el
                    break
            except:
                pass

        if btn_ele:
            try:
                btn_ele.click()
                log(" Northrop 🖱️ 已成功点击登录提交按钮")
            except Exception as click_e:
                log(f"⚠️ 点击登录按钮遭遇阻碍: {click_e}")
        else:
            log("⚠️ 未捕获到明显的登录按钮，尝试直接回车提交表单")
            page.actions.send_key('Enter')

        time.sleep(5)

        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✅ [{self.email}] 登录成功")
            return True

        log(f"❌ [{self.email}] 登录判定未通过，当前 URL: {page.url}")
        pic_path = f"err_login_{self.safe_email}.png"
        page.get_screenshot(path=pic_path)
        send_tg_photo(self.tg_token, self.tg_chat_id, pic_path, f"❌ <b>{self.email}</b> 登录判定失败\nURL: {page.url}")
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
                result['message'] = f'POST 异常: {str(post_err)}'

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
