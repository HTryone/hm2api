# credentials —— 本机凭据（一个平台一个文件夹）

整个目录被 git 过滤（只保留 README 说明），**永远不入库**。

```
cred/
├── qwenwork/         千问办公
│   ├── session.json   ← 凭据（7 天 JWT + refresh_token）
│   └── README.md
└── loomy/            讯飞 Loomy
    ├── auth-session.json  ← 凭据（网关每次读取时从桌面端同步过来的镜像）
    └── README.md
```

规则：**新增平台 = 新建一个平台文件夹，里面放「凭据文件 + README」**，
README 写清：谁写入、谁读取、过期怎么续。
