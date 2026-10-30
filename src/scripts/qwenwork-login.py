#!/usr/bin/env python3
"""千问办公设备码登录（路线 B）：生成授权 URL → 打开浏览器 → 轮询拿 token。

成功后把凭据写入 cred/qwenwork/session.json（git 已过滤）：
{token, refresh_token, expires_at, refresh_token_expires_at, login_device_id, machine_id, obtained_at}
只回显指纹级信息。
"""
import base64, hashlib, json, os, secrets, sys, time, urllib.parse, urllib.request, urllib.error, uuid
from pathlib import Path

CRED_DIR = Path(__file__).resolve().parents[2] / "cred" / "qwenwork"
SESSION_FILE = CRED_DIR / "session.json"
MACHINE_ID_FILE = Path.home() / ".qwenworkcn" / ".auth" / "machine_id"
CLIENT_ID = "e883ade2-e6e3-4d6d-adf7-f92ceff5fdcb"
AUTH_BASE = "https://gateway.qwenwork.cn"
OPENAPI_BASE = "https://gateway.qwenwork.cn"
APP_VERSION = "1.4.0"
RELEASE_VERSION = "1.4.0-26102705"
BUILD = "26102705"

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def client_headers():
    return {
        "X-QwenWork-Version": APP_VERSION,
        "X-QwenWork-Release-Version": RELEASE_VERSION,
        "X-QwenWork-Build": BUILD,
        "X-QwenWork-Platform": "win32",
        "X-QwenWork-Arch": "x64",
        "X-QwenWork-Channel": "stable",
        "X-QwenWork-App-Mode": "standard",
    }


def pkce():
    length = 43 + secrets.randbelow(86)
    verifier = "".join(ALPHABET[secrets.randbelow(len(ALPHABET))] for _ in range(length))
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def machine_id():
    try:
        return MACHINE_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def fp(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12] if text else "(空)"


def poll(nonce, verifier, challenge, timeout_s=300):
    url = (f"{OPENAPI_BASE}/api/v1/deviceToken/poll?nonce={urllib.parse.quote(nonce)}"
           f"&verifier={urllib.parse.quote(verifier)}&challenge_method=S256")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rid = str(uuid.uuid4())
        req = urllib.request.Request(url, method="GET", headers={
            "Accept": "application/json", "X-Request-Id": rid, **client_headers()})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                state = r.headers.get("x-device-flow-state", "")
                body = json.loads(r.read().decode("utf-8"))
                token = body.get("token") or ""
                if token:
                    return body
                print(f"  状态={state or '200-无token'}，继续轮…")
        except urllib.error.HTTPError as e:
            state = e.headers.get("x-device-flow-state", "")
            reason = e.headers.get("x-device-flow-failure-reason", "")
            if e.code == 404:
                print(f"  等待授权（{state or 'pending'}）…")
            elif e.code in (502, 503, 504):
                print(f"  上游暂时 {e.code}，继续轮…")
            else:
                print(f"  轮询被拒：{e.code} state={state} reason={reason}")
                if reason or (state and state == "failed"):
                    raise SystemExit(f"授权失败：state={state} reason={reason}")
        time.sleep(2)
    raise SystemExit("5 分钟内未完成授权")


def main():
    urllib.parse  # noqa
    verifier, challenge = pkce()
    nonce = str(uuid.uuid4())
    mid = machine_id()
    query = (f"challenge={urllib.parse.quote(challenge)}&challenge_method=S256"
             f"&nonce={urllib.parse.quote(nonce)}&machine_id={urllib.parse.quote(mid)}"
             f"&client_id={CLIENT_ID}&redirect_uri=qwenwork-cn%3A%2F%2F")
    auth_url = f"{AUTH_BASE}/device/selectAccounts?{query}"
    print("== 授权链接（已尝试自动打开浏览器）==")
    print(auth_url)
    try:
        os.startfile(auth_url)  # Windows 默认浏览器
    except Exception:
        pass
    print("== 开始轮询（请在浏览器里完成账号授权）==")
    body = poll(nonce, verifier, challenge)
    token = body.get("token") or ""
    record = {
        "token": token,
        "refresh_token": body.get("refresh_token") or "",
        "expires_at": body.get("expires_at") or body.get("expiresAt") or "",
        "refresh_token_expires_at": body.get("refresh_token_expires_at") or "",
        "nonce": nonce,
        "challenge": challenge,
        "client_id": CLIENT_ID,
        "login_device_id": mid,
        "machine_id": mid,
        "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "device-flow",
    }
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"token  len={len(token)} sha256={fp(token)}")
    print(f"refresh len={len(record['refresh_token'])} sha256={fp(record['refresh_token'])}")
    print(f"expires_at={record['expires_at']}")
    print(f"已写入 {SESSION_FILE}（git 已过滤）")


if __name__ == "__main__":
    main()
