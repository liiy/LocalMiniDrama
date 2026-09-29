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

系统拆分为三个独立运行端，分别负责 Web API、投递调度与异步任务执行：

```bash
# 1. API 服务端（日志自动路由至 logs/api.log）
python -m app.main

# 2. Redis 调度端（日志自动路由至 logs/dispatcher.log）
python -m app.tasks.dispatcher_entry

# 3. Dramatiq 异步工作节点（日志自动路由至 logs/worker.log）
dramatiq app.tasks.worker_entry --queues lmd_tasks --processes 2 --threads 4
```

也可以在仓库根目录执行 `docker compose up -d`。其中 `backend-worker` 可水平扩容，重复 Redis 消息会由 `queue_jobs` 的原子状态更新拦截。

## 多端日志隔离与规范

三个独立端运行期日志均通过工业级 `SafeRotatingFileHandler` 与北京时间（UTC+8）高精度格式化输出，实现全自动分流与并发锁保护：

| 进程 / 服务端 | 默认日志文件 | 环境变量覆盖 | 特性说明 |
|--------------|------------|-------------|---------|
| **API 服务端** (`app.main` / `uvicorn`) | `logs/api.log` | `LMD_LOG_FILE=api.log` | 拦截 Uvicorn 访问/错误日志并入 Root Logger |
| **调度端** (`app.tasks.dispatcher_entry`) | `logs/dispatcher.log` | `LMD_LOG_FILE=dispatcher.log` | 记录 MySQL Outbox 扫描、状态流转与投递动作 |
| **工作端** (`dramatiq app.tasks.worker_entry`) | `logs/worker.log` | `LMD_LOG_FILE=worker.log` | 捕获 Dramatiq 任务执行、Windows 多进程锁安全滚动 |

> **提示**：可通过环境变量 `LMD_LOG_DIR` 自定义日志目录（默认在项目根目录 `logs/`）；也可通过 `LMD_LOG_FILE=<name>` 显式指定任意输出文件名。

## 可靠性约束

- API 只在数据库事务提交后首次投递，Worker 不会读取未提交任务。
- Dispatcher 周期扫描未投递或长时间未认领任务，处理提交后进程崩溃造成的漏投。
- Redis 消息只包含 `job_id`，Worker 从 MySQL 读取最新载荷和取消状态。
- 失败重试会清空 Broker 投递标记，由 Dispatcher 再次投递。
