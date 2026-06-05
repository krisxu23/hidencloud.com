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
    """
    解析多账号字符串，格式：
      账号1---密码1
      账号2---密码2
    支持换行或逗号分隔
    """
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
            log(f"⚠️ 无法解析行（格式应为 账号---密码）: {line}")
    return accounts


# ─────────────────────────────────────────────
#  Turnstile 破解
# ─────────────────────────────────────────────

class TurnstileSolver:
    def __init__(self, page: ChromiumPage):
        self.page = page

    def solve(self, timeout: int = 20) -> bool:
        log("🛡️ 开始处理 Cloudflare Turnstile...")

        # 先检查是否已自动通过
        try:
            resp = self.page.ele('css:[name="cf-turnstile-response"]', timeout=2)
            if resp and resp.value:
                log("⚡ Token 已存在，Turnstile 自动通过")
                return True
        except Exception:
            pass

        # 定位 iframe
        iframe = None
        for selector in [
            'css:iframe[src^="https://challenges.cloudflare.com"]',
            'css:iframe[id^="cf-chl-widget-"]',
        ]:
            try:
                iframe = self.page.get_frame(selector, timeout=8)
                if iframe:
                    break
            except Exception:
                pass

        if not iframe:
            log("❌ 找不到 Turnstile iframe")
            return False

        log("✅ 锁定 iframe，穿透 Shadow Root...")
        time.sleep(random.uniform(1.5, 2.5))

        clicked = False

        # 方案1：穿透 Shadow Root
        try:
            body = iframe.ele('tag:body')
            sr = body.shadow_root if body else None
            if sr:
                target = (
                    sr.ele('css:input[type="checkbox"]') or
                    sr.ele('css:div.main-wrapper') or
                    sr.ele('css:#content')
                )
                if target:
                    target.click.at(offset_x=10, offset_y=10)
                    clicked = True
                    log("🖱️ Shadow Root 内点击成功")
        except Exception as e:
            log(f"⚠️ Shadow Root 穿透失败: {e}")

        # 方案2：坐标盲点
        if not clicked:
            try:
                iframe.frame_ele.click.at(offset_x=25, offset_y=30)
                clicked = True
                log("🏹 坐标盲点点击")
            except Exception as e:
                log(f"❌ 盲点失败: {e}")

        if not clicked:
            return False

        # 等待 token 注入
        for i in range(timeout):
            time.sleep(1)
            try:
                resp = self.page.ele('css:[name="cf-turnstile-response"]', timeout=1)
                if resp and resp.value:
                    log(f"🎉 Turnstile 通过！(耗时 {i+1}s)")
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
        self.results: list[dict] = []

    # ── 浏览器初始化 ──────────────────────────

    def _make_page(self) -> ChromiumPage:
        co = ChromiumOptions()
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--window-size=1280,900')
        co.set_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        if self.proxy:
            co.set_proxy(self.proxy)
        return ChromiumPage(co)

    # ── 登录 ─────────────────────────────────

    def login(self) -> bool:
        log(f"🔐 [{self.email}] 开始登录...")
        self.page = self._make_page()
        page = self.page
        solver = TurnstileSolver(page)

        page.get(self.LOGIN_URL)
        
        # 1. 前置 Cloudflare 检查：如果遇到 5 秒盾全局拦截，先过盾
        log(f"🛡️ [{self.email}] 检查前置 Cloudflare 防护...")
        solver.solve(timeout=8) 
        
        # 等待页面渲染
        time.sleep(random.uniform(2, 4))

        # 2. 填写表单（使用更鲁棒的定位方式）
        try:
            # 账号框：支持 type=email，或名字包含 email/username，或利用文字标签定位
            email_ele = (
                page.ele('css:input[type="email"]', timeout=10) or 
                page.ele('css:input[name*="email"]') or 
                page.ele('css:input[name*="username"]') or 
                page.ele('xpath://*[contains(text(), "Email")]/following::input[1]')
            )
            
            if not email_ele:
                raise Exception("等待 10 秒后仍未找到账号输入框")
                
            email_ele.clear()
            email_ele.input(self.email)
            time.sleep(random.uniform(0.3, 0.7))
            
            # 密码框
            pwd_ele = (
                page.ele('css:input[type="password"]') or 
                page.ele('css:input[name*="password"]') or 
                page.ele('xpath://*[contains(text(), "Password")]/following::input[1]')
            )
            if pwd_ele:
                pwd_ele.clear()
                pwd_ele.input(self.password)
            time.sleep(random.uniform(0.3, 0.7))
            
        except Exception as e:
            log(f"❌ [{self.email}] 填写表单失败: {e}")
            # 截图留证
            debug_pic = f"error_login_{self.email.replace('@','_')}.png"
            try:
                page.get_screenshot(path=debug_pic)
                log(f"📸 已保存错误现场截图至: {debug_pic}")
            except Exception:
                pass
            return False

        # 3. 破解表单层 Turnstile（如果之前的前置检查没用到）
        ok = solver.solve()
        if not ok:
            log(f"⚠️ [{self.email}] Turnstile 未通过，尝试直接提交...")

        # 4. 提交登录
        try:
            btn = (
                page.ele('xpath://button[contains(text(),"Sign in")]') or
                page.ele('xpath://button[contains(text(),"Login")]') or
                page.ele('xpath://button[contains(text(),"登录")]') or
                page.ele('css:button[type="submit"]')
            )
            if btn:
                btn.click()
            else:
                log(f"❌ [{self.email}] 找不到登录按钮")
                return False
        except Exception as e:
            log(f"❌ [{self.email}] 点击登录按钮失败: {e}")
            return False

        time.sleep(random.uniform(3, 5))

        # 5. 验证是否登录成功
        if 'dashboard' in page.url or 'service' in page.url:
            log(f"✅ [{self.email}] 登录成功")
            return True

        # 检查错误提示
        try:
            err = page.ele('css:.alert-danger, css:[class*="error"], css:[class*="alert"]', timeout=2)
            if err:
                log(f"❌ [{self.email}] 登录失败: {err.text[:80]}")
        except Exception:
            pass

        log(f"❌ [{self.email}] 登录失败，当前 URL: {page.url}")
        return False

    # ── 获取所有服务 ──────────────────────────

    def get_services(self) -> list[dict]:
        """从 dashboard 抓取所有服务 ID 和到期信息"""
        page = self.page
        log(f"📋 [{self.email}] 获取服务列表...")

        page.get(self.DASHBOARD_URL)
        time.sleep(random.uniform(2, 3))

        services = []

        # 抓取服务卡片（找所有 /service/{id}/manage 链接）
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
            log(f"⚠️ [{self.email}] 抓取服务链接失败: {e}")

        # 补充：如果 dashboard 没有直接链接，尝试 /services 页
        if not services:
            try:
                page.get(f"{self.BASE}/services")
                time.sleep(2)
                links = page.eles('css:a[href*="/service/"][href*="/manage"]')
                for link in links:
                    href = link.attr('href') or ''
                    m = re.search(r'/service/(\d+)/manage', href)
                    if m:
                        sid = m.group(1)
                        if not any(s['id'] == sid for s in services):
                            services.append({'id': sid})
            except Exception as e:
                log(f"⚠️ [{self.email}] 抓取 /services 失败: {e}")

        log(f"📦 [{self.email}] 找到 {len(services)} 个服务: {[s['id'] for s in services]}")
        return services

    # ── 续期单个服务 ──────────────────────────

    def renew_service(self, service_id: str) -> dict:
        page = self.page
        result = {
            'service_id': service_id,
            'success': False,
            'message': '',
            'invoice_id': '',
        }

        log(f"🔄 [{self.email}] 续期服务 #{service_id}...")
        manage_url = f"{self.BASE}/service/{service_id}/manage"
        page.get(manage_url)
        time.sleep(random.uniform(2, 3))

        # 提取 CSRF _token
        token = ''
        try:
            token_ele = page.ele('css:input[name="_token"]', timeout=3)
            if token_ele:
                token = token_ele.value
        except Exception:
            pass

        # 也从 meta 标签尝试
        if not token:
            try:
                meta = page.ele('css:meta[name="csrf-token"]', timeout=2)
                if meta:
                    token = meta.attr('content') or ''
            except Exception:
                pass

        if not token:
            # 从页面 HTML 提取
            html = page.html
            m = re.search(r'<input[^>]+name="_token"[^>]+value="([^"]+)"', html)
            if m:
                token = m.group(1)

        if not token:
            result['message'] = 'CSRF token 提取失败'
            log(f"❌ [{self.email}] #{service_id}: {result['message']}")
            return result

        log(f"🔑 [{self.email}] #{service_id} token: {token[:20]}...")

        # 点击 Renew 按钮（打开弹窗）
        try:
            renew_btn = (
                page.ele('xpath://button[contains(text(),"Renew")]') or
                page.ele('xpath://a[contains(text(),"Renew")]') or
                page.ele('css:[data-action*="renew"], css:[onclick*="renew"]')
            )
            if renew_btn:
                renew_btn.click()
                time.sleep(random.uniform(1.5, 2.5))
                log(f"🖱️ [{self.email}] #{service_id} 点击了 Renew 按钮")
        except Exception as e:
            log(f"⚠️ [{self.email}] #{service_id} 点击 Renew 按钮失败（将直接 POST）: {e}")

        # 在弹窗中点击 "Create Invoice"
        try:
            confirm_btn = (
                page.ele('xpath://button[contains(text(),"Create Invoice")]') or
                page.ele('xpath://button[contains(text(),"Renew")]') or
                page.ele('css:.modal button[type="submit"]')
            )
            if confirm_btn:
                confirm_btn.click()
                time.sleep(random.uniform(2, 3))
                log(f"🖱️ [{self.email}] #{service_id} 点击了 Create Invoice")
                # 检查是否跳转到 invoice 页
                if 'invoice' in page.url:
                    m = re.search(r'/invoice/([a-f0-9\-]+)', page.url)
                    invoice_id = m.group(1)[:8] if m else ''
                    result['success'] = True
                    result['message'] = '续期成功（UI点击）'
                    result['invoice_id'] = invoice_id
                    log(f"✅ [{self.email}] #{service_id} 续期成功，发票: {invoice_id}")
                    return result
        except Exception as e:
            log(f"⚠️ [{self.email}] #{service_id} 弹窗点击失败（尝试直接 POST）: {e}")

        # 保底：直接 POST API
        log(f"📡 [{self.email}] #{service_id} 使用直接 POST 续期...")
        try:
            # 从 DrissionPage 拿 cookies 构造 requests session
            cookies_list = page.cookies()
            s = requests.Session()
            for ck in cookies_list:
                s.cookies.set(ck.get('name', ''), ck.get('value', ''), domain=ck.get('domain', ''))

            renew_url = f"{self.BASE}/service/{service_id}/renew"
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': self.BASE,
                'Referer': manage_url,
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
            }
            data = {'_token': token, 'days': '7'}

            if self.proxy:
                proxies = {'http': f'socks5://{self.proxy}', 'https': f'socks5://{self.proxy}'}
            else:
                proxies = None

            resp = s.post(renew_url, data=data, headers=headers,
                          allow_redirects=True, timeout=20, proxies=proxies)

            if 'invoice' in resp.url or resp.status_code in (200, 302):
                m = re.search(r'/invoice/([a-f0-9\-]+)', resp.url)
                invoice_id = m.group(1)[:8] if m else ''
                # 进一步验证：检查响应内容
                if '发票' in resp.text or 'invoice' in resp.text.lower() or invoice_id:
                    result['success'] = True
                    result['message'] = '续期成功（POST）'
                    result['invoice_id'] = invoice_id
                    log(f"✅ [{self.email}] #{service_id} POST 续期成功，发票: {invoice_id}")
                else:
                    result['message'] = f'POST 返回异常，状态: {resp.status_code}'
                    log(f"❌ [{self.email}] #{service_id}: {result['message']}")
            else:
                result['message'] = f'续期响应异常: {resp.status_code}'
                log(f"❌ [{self.email}] #{service_id}: {result['message']}")

        except Exception as e:
            result['message'] = f'POST 异常: {e}'
            log(f"❌ [{self.email}] #{service_id}: {result['message']}")

        return result

    # ── 主流程 ────────────────────────────────

    def run(self) -> list[dict]:
        try:
            if not self.login():
                return [{'service_id': 'N/A', 'success': False,
                         'message': '登录失败', 'invoice_id': ''}]

            services = self.get_services()
            if not services:
                return [{'service_id': 'N/A', 'success': False,
                         'message': '未找到任何服务', 'invoice_id': ''}]

            results = []
            for svc in services:
                r = self.renew_service(svc['id'])
                results.append(r)
                time.sleep(random.uniform(2, 4))

            return results

        except Exception as e:
            log(f"💥 [{self.email}] 运行异常: {e}")
            import traceback
            traceback.print_exc()
            return [{'service_id': 'N/A', 'success': False,
                     'message': f'运行异常: {e}', 'invoice_id': ''}]
        finally:
            if self.page:
                try:
                    self.page.quit()
                except Exception:
                    pass


# ─────────────────────────────────────────────
#  主入口
# ─────────────────────────────────────────────

def main():
    # 读取环境变量
    accounts_raw = os.getenv('ACCOUNTS', '').strip()
    tg_token     = os.getenv('TG_BOT_TOKEN', '').strip()
    tg_chat_id   = os.getenv('TG_CHAT_ID', '').strip()
    proxy        = os.getenv('PROXY', '').strip()   # 格式: 127.0.0.1:10808

    if not accounts_raw:
        log("❌ 环境变量 ACCOUNTS 为空，退出")
        sys.exit(1)

    accounts = parse_accounts(accounts_raw)
    if not accounts:
        log("❌ 未解析到任何账号，退出")
        sys.exit(1)

    log(f"📋 共解析到 {len(accounts)} 个账号")

    all_results: list[dict] = []
    account_summaries: list[str] = []

    for email, password in accounts:
        log(f"\n{'='*50}")
        log(f"🚀 处理账号: {email}")
        log(f"{'='*50}")

        renewer = HidenCloudRenewer(email, password, proxy)
        results = renewer.run()
        all_results.extend(results)

        # 构建此账号的汇总
        success_count = sum(1 for r in results if r['success'])
        fail_count    = len(results) - success_count

        lines = [f"📧 <b>{email}</b>"]
        for r in results:
            icon = "✅" if r['success'] else "❌"
            inv  = f" | 发票: <code>{r['invoice_id']}</code>" if r['invoice_id'] else ""
            lines.append(f"  {icon} 服务 #{r['service_id']}: {r['message']}{inv}")
        lines.append(f"  成功 {success_count} / 共 {len(results)} 个")
        account_summaries.append('\n'.join(lines))

        time.sleep(random.uniform(3, 6))

    # ── 发送 Telegram 汇总通知 ──
    total_ok   = sum(1 for r in all_results if r['success'])
    total_fail = len(all_results) - total_ok

    tg_msg = (
        f"🔔 <b>HidenCloud 自动续期报告</b>\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📊 总计: ✅ {total_ok} 成功 / ❌ {total_fail} 失败\n\n"
        + '\n\n'.join(account_summaries)
    )
    send_tg(tg_token, tg_chat_id, tg_msg)

    log(f"\n🏁 全部完成：{total_ok} 成功，{total_fail} 失败")
    if total_fail > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
