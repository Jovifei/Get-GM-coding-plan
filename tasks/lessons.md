# Lessons Learned

## 2026-05-14: no_refresh_window 窗口期封锁关键刷新

**问题**: `no_refresh_window` 在 10:00 前后各 20 秒的窗口内禁止一切页面刷新，包括按钮明确提示"请刷新再试"时也拒绝刷新，导致错过库存放出的最关键时机。

**规则**:
1. 任何"禁止刷新"窗口都不应阻止页面自身要求的刷新动作（如按钮显示"请刷新再试"）
2. 配置读取路径必须与 config.yaml 结构一致 —— 用 `config.get('section', {}).get('key', default)` 而非硬编码假定 key 在某 section 下
3. 修改 Python 文件时优先使用文本模式（UTF-8）读写，避免二进制替换破坏编码

## 2026-05-14: click-verify dead loop (12 minutes of wasted clicks)

**Problem**: After clicking the button, `_verify_click_success()` always failed with 1s timeout, causing infinite retry loop for 12 minutes until the purchase window expired.

**Root causes**:
1. `_verify_click_success()` timeout was only 1000ms — too short for page navigation
2. No retry limit on click-verify cycle — reset and retry forever without refreshing
3. No new-tab/popup detection — if click opens a new tab, verification never sees it

**Fixes applied**:
1. Increased verification timeouts to 2000ms (fast) + 3000ms (retry after page load)
2. Added URL-based detection as most reliable signal (check if URL changed from glm-coding)
3. Added new-page/popup detection and auto-switch logic
4. Added max retry limit (3) with forced page refresh between retry batches
5. Expanded indicator list to cover more confirmation page elements

**Rules**:
1. Always include URL change detection in page-transition verification — it's the most reliable signal
2. Never allow infinite retry loops — cap at a reasonable number and escalate (refresh/restart)
3. Always check `page.context.pages` for new tabs/windows when click actions might open popups
4. Use 2-tier timeout strategy: fast scan first, then longer timeout after waiting for page load
