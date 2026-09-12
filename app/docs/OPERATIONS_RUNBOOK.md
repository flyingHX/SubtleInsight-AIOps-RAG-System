# AIOps 运营控制台运维手册（Runbook）

> 面向值班与 SRE 的应急处置手册。部署细节见《OPERATIONS_DEPLOYMENT_GUIDE.md》。

## 1. 服务巡检（每日）

| 检查项 | 命令/入口 | 期望 |
|--------|-----------|------|
| 后端健康 | `curl http://localhost:8000/health` | 200 |
| 前端可达 | 浏览器打开控制台首页 | 登录页/总览正常渲染 |
| 待办积压 | 总览「待办」卡片 或 `GET /api/v1/console/dashboard` | pending_approvals / pending_unknowns 无持续增长 |
| LLM 健康 | 总览「依赖健康」llm 项 | healthy；degraded 时查诊断降级原因 |
| 审计连续性 | 审计日志页按时间倒序 | 当日关键操作均有对应审计记录 |

## 2. 常见告警场景与处置

### 2.1 审批/晋升接口 500（主键冲突）
- **根因**：显式 ID 种子/导入后 PostgreSQL 序列未同步。
- **处置**：
  ```bash
  cd app/backend && python scripts/fix_sequences.py
  ```
- **验证**：重新发起晋升或审批，返回 200；审计出现对应记录。

### 2.2 AI 诊断批量超时（llm_timeout）
- **处置**：sys_admin → 配置中心 → `llm_timeout_seconds` 调大（如 45 → 90，上限 300）→ 重试一次诊断。
- **仍失败**：检查平台 AIHub 状态；期间告警查看不受影响，可先用 RAG 召回案例处置。

### 2.3 紧急变更需要免审
- **处置**：sys_admin → 配置中心 → `approval_mode=OFF` → 提交变更直接发布。
- **恢复**：事件处置完成后切回 `SINGLE_REVIEW`，并核查 OFF 期间的 `kb_publish` 审计记录。

### 2.4 误发布知识/规则
- **知识案例**：知识库 → 案例详情 → 版本历史 → 回滚到上一版本（生成新版本，秒级生效）。
- **规则**：规则管理 → 版本列表 → 回滚到上一个版本（重新激活并热加载）。
- 两类回滚均写审计，无需数据库操作。

### 2.5 RAG 无召回 / 未知率升高
- 查看「规则管理 → 未知模板」队列：样本量大的模板及时晋升（填写目标 error_type → 审批）。
- 知识库确认目标错误类型存在 `active` 案例；被合并归档的案例不再召回，可在案例列表切「已归档」核实。

### 2.6 前端访问 401/白屏
- 401：登录态过期，重新登录；确认浏览器 localStorage `token` 存在。
- /api 404：Vite 代理目标端口与后端实际端口不一致（`BACKEND_PORT` 环境变量）。
- 白屏：确认后端 `/health` 正常、前端构建产物完整。

## 3. 数据维护

### 3.1 演示数据重置
```bash
cd app/backend
python scripts/seed_console_demo.py   # 追加演示数据
python scripts/fix_sequences.py       # 必须执行
```

### 3.2 备份（建议每日）
```bash
pg_dump "$DATABASE_URL" -Fc -f console_backup_$(date +%F).dump
```
审计日志保留 ≥ 180 天。

### 3.3 恢复
```bash
pg_restore --clean --if-exists -d "$DATABASE_URL" <dump 文件>
python scripts/fix_sequences.py
```

## 4. 升级窗口流程

1. 通知用户 + 冻结审批操作。
2. 执行数据库备份（§3.2）。
3. 拉取新版本代码，安装依赖（后端 uv / 前端 pnpm）。
4. 重启后端（生产去 `--reload`），前端重新 build。
5. 巡检（§1）全部通过后解除冻结。
6. 回滚预案：切回上一版本代码重启；数据层面优先用控制台内置版本回滚。

## 5. 升级/值班联系矩阵

| 事项 | 责任角色 | 操作入口 |
|------|----------|----------|
| 审批积压催办 | 审批人（approver+） | 审批中心 |
| 审批模式/阈值调整 | sys_admin | 配置中心 |
| 规则发布/回滚 | sys_admin | 规则管理 |
| 案例回滚/合并 | kb_admin+ | 知识库 |
| 数据库/序列/部署 | 运维 | 服务器 + scripts/ |
| 平台登录/AIHub 异常 | 平台方 | Atoms 平台支持 |

## 6. 应急速查卡

```
序列冲突   -> python scripts/fix_sequences.py
紧急免审   -> 配置中心 approval_mode=OFF（事后切回）
误发布     -> 控制台内版本回滚（知识/规则均支持）
诊断超时   -> 配置中心 llm_timeout_seconds 调大
后端起不来 -> 看 logs/restart.log + logs/app_YYYYMMDD.log
前端 /api 404 -> 核对 BACKEND_PORT 与 Vite 代理端口
```
