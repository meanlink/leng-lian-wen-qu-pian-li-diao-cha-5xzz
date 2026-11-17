# 冷链温区偏离调查

分布比较与偏离定位的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
赔付核销：登记货批与核定损失 → 开单（申报金额＋所据调查，仅已批准分析可作依据）→ 财务确认（占用可赔余额，同批累计实付不超核定损失）→ 本地付款端付款（单号幂等，回执丢失先对账不盲目再付）→ 撤销（在途等对账，已付退款冲回，退款确认前不释放可赔金额）；资金流水可查资金去向，worker 定时清扫并恢复未结付款与退款。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；赔付域另有 CargoBatch 货批、PayoutOrder 赔付核销单、Payment/Refund 付款退款单、FundEvent 资金流水；辅助 User、Audit、Delivery。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18201；后端文档 http://localhost:19201/docs；数据库宿主端口 17701。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载；另可登记货批、确认/撤销核销单、对账与付款端演练|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；可开具赔付核销单，不能确认或撤销|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；MySQL 8.0；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=cold-excursion；FRONTEND_PORT=18201；BACKEND_PORT=19201；DB_PORT=17701；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 赔付核销与本地付款端
- 金额一律以分存储；货批余额只经带守卫条件的原子 UPDATE 变动，并发核销共用余额时超额占用在 SQL 层失败。
- 付款单号 `PAY-订单号-A尝试号` 幂等：同单重试复用原单不新增付款；付款端对同号改金额直接拒收（409）。
- 回执只推进 pending/sent 状态且序号必须更新，旧回执不改新状态；回执丢失时以对账（查付款端台账）推进，不盲目再付。
- 撤销：未发出直接关闭；付款在途转「撤销中·等对账」，对账确认未成则释放、已成则自动退款冲回；退款确认前不释放可赔金额。
- 本地付款端（`/paygate`，后端内嵌模拟外部通道，独立台账独立提交）支持演练开关：丢回执、退款失败，可在「赔付核销」页一键开关并查看付款端台账。
- worker 每 tick 清扫未结付款/退款（回执宽限 3 秒、退款退避 5 秒），启动时立即恢复（无宽限）。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1002/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
