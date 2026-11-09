#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日积分签到 — GitHub Actions 定时任务（无头浏览器执行）
流程：
  1) 从仓库 Secret（WB_STATE_B64，base64 编码的 Playwright storageState）还原登录态
  2) 无头 Chromium 加载登录态 → 打开 workbuddy.cn/app
  3) 页面上下文内调用官方签到接口（幂等：已签过直接返回，不会多领）
环境变量：
  WB_STATE_B64  必填，登录态 base64
退出码：
  0 = 签到成功或今日已签；2 = 登录态失效（Actions 会发邮件提醒你更新 Secret）
"""
import base64
import json
import os
import sys
import time

STATE_PATH = "/tmp/storage_state.json"
APP_URL = "https://www.workbuddy.cn/app"
UID = "ab08f04e-dd95-46aa-94de-62772aee2399"


def log(msg):
    print("[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def main():
    raw = os.environ.get("WB_STATE_B64", "").strip()
    if not raw:
        log("✗ 未设置 Secret WB_STATE_B64")
        sys.exit(2)
    try:
        state = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception as e:
        log("✗ WB_STATE_B64 解码失败：{}".format(str(e)[:150]))
        sys.exit(2)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    log("登录态已还原（{} cookies）".format(len(state.get("cookies", []))))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(storage_state=STATE_PATH, locale="zh-CN")
        page = ctx.new_page()
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)

        if "login" in page.url:
            log("✗ 登录态已失效（跳转到登录页）。请在本机重新导出登录态并更新 Secret WB_STATE_B64")
            browser.close()
            sys.exit(2)

        res = page.evaluate(
            """async () => {
                const st = await fetch('/v2/billing/meter/checkin-activity-status',
                    {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
                if (!st.ok) return {action:'http_error', status: st.status, body: (await st.text()).slice(0,200)};
                const stj = await st.json();
                if (stj.data && stj.data.today_checked_in) return {action:'already', data: stj.data};
                const r = await fetch('/v2/billing/meter/daily-checkin',
                    {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
                const rj = await r.json();
                if (rj.code === 10001) return {action:'already', data: stj.data};
                return {action:'checkin', data: rj.data || stj.data};
            }"""
        )
        if res.get("action") == "http_error":
            log("✗ 接口异常 HTTP {}：{}".format(res.get("status"), res.get("body")))
            browser.close()
            sys.exit(1)

        data = res.get("data") or {}
        result = {
            "ok": True,
            "action": res.get("action"),
            "today_credit": data.get("today_credit"),
            "streak_days": data.get("streak_days"),
            "total_credits": data.get("total_credits"),
        }
        log("✓ 签到结果：{}".format(json.dumps(result, ensure_ascii=False)))
        browser.close()

    print("RESULT:" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
