# -*- coding: utf-8 -*-
"""
pusher.py —— 微信推送通道。

支持两条通道，按环境变量自动选择（二选一即可，都配则优先 Server酱）：
  - Server酱  ：环境变量 SERVERCHAN_SENDKEY
                 接口 https://sctapi.ftqq.com/<SENDKEY>.send  （新版，推荐）
                 兼容 https://sct.ftqq.com/<SENDKEY>.send      （旧版）
  - WxPusher  ：环境变量 WXPUSHER_TOKEN（应用 Token）+ WXPUSHER_UIDS（接收者 UID，逗号分隔）

密钥绝不写死在代码里，全部走 Secret / 环境变量。
"""

import os
import json
import urllib.request
import urllib.parse


def _post_form(url, data, timeout=10):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        return resp
    except Exception as e:
        return '{"errmsg":"%s"}' % e


def _post_json(url, payload, timeout=10):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json;charset=utf-8"})
    try:
        return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except Exception as e:
        return '{"success":false,"msg":"%s"}' % e


def push_serverchan(sendkey, title, desp):
    """Server酱推送。返回 (ok:bool, msg)。"""
    if not sendkey:
        return False, "未配置 SERVERCHAN_SENDKEY"
    for base in ("https://sctapi.ftqq.com", "https://sct.ftqq.com"):
        url = "%s/%s.send" % (base, sendkey)
        resp = _post_form(url, {"title": title, "desp": desp})
        try:
            j = json.loads(resp)
            # Server酱：code==0 成功；若无 code 字段（旧版）看 errmsg
            if j.get("code") == 0 or j.get("errmsg") in (None, "", "ok"):
                return True, resp
        except ValueError:
            if "ok" in resp.lower():
                return True, resp
    return False, resp


def push_wxpusher(token, uids, title, content):
    """WxPusher 推送。content 支持 Markdown。返回 (ok:bool, msg)。"""
    if not token or not uids:
        return False, "未配置 WXPUSHER_TOKEN / WXPUSHER_UIDS"
    uid_list = [u.strip() for u in uids.split(",") if u.strip()]
    payload = {
        "appToken": token,
        "content": content,
        "summary": title,
        "contentType": 3,          # 3 = Markdown
        "topicIds": [],
        "uids": uid_list,
    }
    resp = _post_json("https://wxpusher.zjiecode.com/api/send/message", payload)
    try:
        j = json.loads(resp)
        if j.get("success"):
            return True, resp
        return False, resp
    except ValueError:
        return False, resp


def push(title, desp):
    """统一入口：根据环境变量选择通道并推送。返回 (ok, msg)。"""
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if sendkey:
        return push_serverchan(sendkey, title, desp)
    token = os.environ.get("WXPUSHER_TOKEN", "").strip()
    uids = os.environ.get("WXPUSHER_UIDS", "").strip()
    if token and uids:
        return push_wxpusher(token, uids, title, desp)
    return False, "未配置任何推送通道（SERVERCHAN_SENDKEY 或 WXPUSHER_TOKEN+WXPUSHER_UIDS）"


if __name__ == "__main__":
    # 自测：无密钥时优雅返回，不抛异常
    ok, msg = push("测试", "内容")
    print("push self-test:", ok, msg)
