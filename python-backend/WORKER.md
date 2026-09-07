# 独立队列部署

生产队列由三个角色组成：FastAPI 负责写入 MySQL `queue_jobs`，Dispatcher 负责可靠投递 Redis，Dramatiq Worker 负责原子认领与执行。MySQL 始终是任务状态与业务载荷的权威来源。

## 环境变量

在 `.env` 中至少配置：

```dotenv
LMD_DATABASE_URL=mysql+pymysql://user:password@mysql:3306/lmd?charset=utf8mb4
LMD_QUEUE_BACKEND=dramatiq
LMD_REDIS_URL=redis://redis:6379/0
LMD_QUEUE_WORKER_ENABLED=false
```

API 进程必须关闭内嵌 DB Worker。Dispatcher 与 Worker 可使用同一个镜像独立扩缩容。

## 启动命令

```bash
python -m app.tasks.dispatcher_entry
dramatiq app.tasks.worker_entry --queues lmd_tasks --processes 2 --threads 4
```

也可以在仓库根目录执行 `docker compose up -d`。其中 `backend-worker` 可水平扩容，重复 Redis 消息会由 `queue_jobs` 的原子状态更新拦截。

## 可靠性约束

- API 只在数据库事务提交后首次投递，Worker 不会读取未提交任务。
- Dispatcher 周期扫描未投递或长时间未认领任务，处理提交后进程崩溃造成的漏投。
- Redis 消息只包含 `job_id`，Worker 从 MySQL 读取最新载荷和取消状态。
- 失败重试会清空 Broker 投递标记，由 Dispatcher 再次投递。
