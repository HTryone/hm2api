# 平台清单

| 平台 | key | 公开模型 id | 上游 | 凭据 | 计费 |
|---|---|---|---|---|---|
| 讯飞 Loomy | `loomy` | `auto`、`spark-x*`、`DeepSeek-V4.1-Flash` 等（原样） | `https://loomyad.xunfei.cn/api/v1` | **`cred/loomy/auth-session.json`（唯一读源）**；桌面端 `C:\Users\Public\Loomy\<hash>\userData\auth-session.json` 仅作同步源，比仓库副本新时自动覆盖进来 | `usage.credit`（积分） |
| 千问办公 | `qwenwork` | `qwenwork/flash`、`qwenwork/pro`、`qwenwork/qwen3.8-max-preview` | `POST /api/desktop-sessions` 下发的 `base_url`（如 `https://api9.qwenwork.cn`） | `cred/qwenwork/session.json`（设备码登录，7 天；缺失时解密桌面端 `auth-v2.dat`） | 无积分字段（token usage） |

## 千问办公鉴权细节
1. 登录 JWT（7 天）：`cred/qwenwork/session.json` → 否则解密桌面端 `auth-v2.dat`
2. 换取推理密钥（2h）：`POST https://gateway.qwenwork.cn/api/desktop-sessions {"session_id":<uuid>}` → `{access_token:"sk-mm-v1.*", base_url, expires_at_ms}`，到期前 5 分钟自动重换
3. 推理：`{base_url}/v1/chat/completions`，标准 OpenAI，**无需签名**
4. 目录：`GET https://gateway.qwenwork.cn/api/desktop/chat-modes`（明文）
