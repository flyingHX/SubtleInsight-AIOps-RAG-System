# AIOps 运营控制台运维部署方案手册

> 适用范围：`/workspace/app`（React + Vite 前端 + FastAPI 后端 + Atoms Cloud 托管 PostgreSQL）。
> 注意：与 `/workspace/aiops-rag-system`（Python 流水线，含 Milvus/Kafka/Redis/ES docker-compose）相互独立。

## 1. 系统组成

| 组件 | 目录 | 技术 | 默认端口 |
|------|------|------|----------|
| 前端 | `app/frontend` | React 18 + Vite + shadcn/ui + Tailwind | 3000（自动避让） |
| 后端 | `app/backend` | FastAPI + SQLAlchemy async + pydantic-settings | 8000（自动避让） |
| 数据库 | Atoms Cloud 托管 | PostgreSQL（ORM 自动建表） | - |
| 认证 | Atoms 平台 | OIDC + JWT（演示环境另有 demo-login） | - |

## 2. 环境要求

- Node.js ≥ 18，包管理器 pnpm（缺失时脚本回退 npm）。
- Python 3.10+，依赖管理 uv（`uv venv` + `uv pip install`）。
- 后端依赖清单：`app/backend/requirements.txt` 与 `requirements.default`（两份都要安装，脚本已按序处理）。

## 3. 一键启动（开发/预览）

```bash
bash app/start_app_v2.sh
```

脚本行为：
1. 自动探测本机 IP 与可用端口对（后端从 8000、前端从 3000 起步，被占用自动 +1 重试，最多 3 次）。
2. 安装后端依赖（uv）与前端依赖（pnpm install + `@metagptx/web-sdk@latest`）。
3. 启动后端：`uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT --reload`（排除 *.log、*.pyc）。
4. 启动前端：`pnpm dev --host 0.0.0.0 --port $FRONTEND_PORT`（Vite 将 `/api` 代理到后端端口）。
5. 轮询 `GET http://$LOCAL_IP:$BACKEND_PORT/health` 直到就绪（最多 60 秒）。
6. Ctrl+C 一并停止前后端（trap 清理）。

常用参数：
- `--no-start`：只安装依赖不启动。
- `--local`：本地模式，将 `$$BACKEND_DOMAIN$$`/`$$FRONTEND_DOMAIN$$` 占位符替换为本机地址。
- `--env-filename FILE`：指定环境变量文件（默认 `.env`；未提供 S2S 参数时启用文件模式）。
- 环境变量方式：`S2S_JWT_TOKEN`、`S2S_JWT_BASE_URL`、`CHAT_ID` 提供时改从平台 API 拉取配置（固定 dev 环境，并支持 dirty 信号热刷新）。

## 4. 前后端独立启动

后端（在 `app/backend` 下）：

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -r requirements.default
export IS_LAMBDA=false
uvicorn main:app --host 0.0.0.0 --port 8000
```

前端（在 `app/frontend` 下）：

```bash
pnpm install
BACKEND_PORT=8000 pnpm dev        # 开发模式，/api 代理到后端
BACKEND_PORT=8000 pnpm build      # 生产构建，产物在 dist/
```

> 生产构建如需预渲染 `/` 与 `/blog/`，保持 `vite.config.ts` 中现有 prerender 插件配置即可；预渲染数据由 `prerender/` 脚本生成。

## 5. 数据库初始化与种子数据

1. **建表**：后端启动时通过 ORM 自动创建全部业务表（events、kb_cases、kb_change_sets、kb_versions、kb_merge_proposals、approval_requests、approval_steps、rule_versions、unknown_templates、audit_logs、console_configs），无需手工执行 SQL。
2. **演示种子**（预览/演示环境）：

```bash
cd app/backend
python scripts/seed_console_demo.py
```

3. **序列同步（重要）**：种子脚本使用显式 ID 插入，PostgreSQL 自增序列不会自动推进，会导致后续 INSERT 主键冲突（典型症状：审批/晋升接口 500）。执行：

```bash
python scripts/fix_sequences.py
```

该脚本将 11 张表的 id 序列重置为 `MAX(id)+1`。**任何使用显式 ID 导入数据之后都必须执行一次。**

## 6. 环境变量说明

后端通过 `core/config.py`（pydantic-settings）读取环境变量，未显式声明的键可用 `settings.<name>` 动态读取（snake_case → 大写环境变量）。

| 变量 | 说明 |
|------|------|
| `IS_LAMBDA` | 固定 `false`（本地/自部署）；true 时走 Lambda 入口 `lambda_handler.py` |
| `ENVIRONMENT` | 环境标识，本地为 `dev` |
| `BACKEND_PORT` / `FRONTEND_PORT` | 启动脚本自动分配并导出，覆盖 .env 同名值 |
| `S2S_JWT_TOKEN` / `S2S_JWT_BASE_URL` / `CHAT_ID` | 平台配置拉取凭证（可选，提供后从 API 拉环境变量） |
| `USERNAME` | 平台调试请求头（可选） |

认证相关密钥由 Atoms 平台注入（OIDC/JWKS），无需手工配置；AI 能力走内置 AIHub，无需自备 API Key。

## 7. 健康检查与验证

```bash
curl http://localhost:8000/health          # 200 即后端就绪
curl http://localhost:8000/docs            # OpenAPI 文档
# 控制台 API 抽样验证（需登录态）
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/console/permissions
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/console/dashboard
```

未携带 Token 访问控制台 API 应返回 401（RBAC 生效）。前端打开 `http://localhost:3000` 应出现登录页；演示账号见《使用手册》§1。

## 8. 日志

| 路径 | 内容 |
|------|------|
| `app/backend/logs/app_YYYYMMDD.log` | 后端启动与请求日志（按日滚动） |
| `app/backend/logs/restart.log` | 重启与异常堆栈记录 |

uvicorn `--reload` 热重载已排除 `*.log`，日志写入不会触发重启风暴。

## 9. 生产部署要点

1. **前端静态化**：`pnpm build` 产出 `dist/`，由 Nginx/网关直接托管静态文件。
2. **后端常驻**：生产去掉 `--reload`，用 systemd / supervisor / 容器守护：

```ini
# systemd 示例（/etc/systemd/system/aiops-console.service）
[Service]
WorkingDirectory=/opt/app/backend
Environment=IS_LAMBDA=false
ExecStart=/opt/app/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
```

3. **反向代理（Nginx 示例）**：

```nginx
server {
    listen 443 ssl;
    server_name console.example.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location / {
        root /opt/app/frontend/dist;
        try_files $uri /index.html;   # SPA 路由回退
    }
}
```

- 回调域名需与 Atoms OIDC 应用配置一致；统一走 HTTPS。

## 10. 备份与恢复

```bash
# 备份（业务库）
pg_dump "$DATABASE_URL" -Fc -f console_backup_$(date +%F).dump

# 恢复
pg_restore --clean --if-exists -d "$DATABASE_URL" console_backup_2026-09-11.dump
python scripts/fix_sequences.py   # 恢复后同步序列
```

- 审计日志（audit_logs）为合规数据，建议纳入每日备份且保留 ≥ 180 天。
- 知识案例历史版本（kb_versions）与规则版本（rule_versions）均只增不改，备份后可随时追溯。

## 11. 升级与回滚

1. **升级**：拉取新代码 → 安装依赖（后端 uv / 前端 pnpm）→ 重启后端（ORM 自动补齐新表/列）→ 前端重新 build 替换 dist。升级前执行 §10 备份。
2. **应用回滚**：切回上一版本代码并重启；数据库结构仅向后兼容新增时无需回滚数据库。
3. **数据回滚**：业务语义回滚优先使用控制台内置能力（知识案例版本回滚、规则版本回滚），比直接改库安全且自带审计。
4. **序列修复**：任何显式 ID 导入/恢复后执行 `scripts/fix_sequences.py`。

## 12. 故障排查

| 现象 | 排查与处置 |
|------|-----------|
| 后端起不来 | 查看 `logs/restart.log` 与 `logs/app_*.log`；确认依赖两份 requirements 均已安装、`.venv` 已激活 |
| 端口被占 | 脚本自动 +1 避让；手动启动时确认 `BACKEND_PORT`/`FRONTEND_PORT` |
| 审批/晋升 500 主键冲突 | 执行 `python scripts/fix_sequences.py`（显式 ID 种子导致序列未同步） |
| 前端 401 / 登录循环 | 确认走 SDK 登录（localStorage `token`）；检查回调路由 `/auth/callback` 与 OIDC 域名配置 |
| AI 诊断全部超时 | 配置中心调大 `llm_timeout_seconds`；确认平台 AIHub 可用 |
| RAG 全部无召回 | 知识库为空或案例均归档；执行种子脚本或补充活跃案例 |
| 规则发布后未生效 | 查看规则版本列表确认目标版本 status=active；审计有 `rule_reload` 记录即热加载成功 |
| 前端 /api 404 | 开发模式确认 Vite 代理目标端口 = 后端实际端口（`BACKEND_PORT`） |

## 13. 安全注意事项

- 生产环境禁用演示登录依赖的快捷通道前先评估（`/api/v1/auth/demo-login` 仅应存在于预览环境）。
- 默认角色 `viewer` 最低权限；`role_bindings_json` 中按邮箱精确绑定。
- 全部写操作（审批/发布/回滚/配置）强制审计，禁止绕过控制台直改数据库。
- 数据库连接串、平台密钥仅存于环境变量/平台密钥管理，禁止提交到仓库。
