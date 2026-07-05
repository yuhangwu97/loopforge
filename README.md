# LoopForge

一个后台服务。给目标文件和检查命令，自动循环改进代码，直到通过。

## 功能

### 自动修 Bug

告诉它测试命令。它跑测试、看报错、定位代码、修改、再跑测试。循环直到全绿，或者达到最大轮数。

改坏了会自动回滚到上一轮。

### 性能优化

告诉它 benchmark 命令。它跑分、找瓶颈、改代码、再跑分。对比 baseline 判断是否有提升，没有提升就回滚换方向。

### 代码重构

告诉它质量检查命令。它分析复杂度、重构、跑测试确保行为不变。复杂度下降且测试不挂才算分。

### 任务管理

每个任务有完整的执行记录：每轮做了什么、改了什么文件、得分多少、为什么继续或停止。任务存在 SQLite 里，服务重启不丢。

### 多个 AI 模型

支持 Claude、OpenAI、DeepSeek。设环境变量即可切换，不需要改代码。

### Dashboard

Web 界面管理任务。创建、查看进度、展开每轮详情、看实时状态。运行中的任务通过 SSE 实时推送状态变更。

### 水平扩展

单机模式直接跑。需要多 worker 时接 Redis 用 Celery 分发任务。

## 使用场景

- CI 里自动修 lint 报错
- 本地重构后跑测试确保没引入 bug
- 后台挂着持续优化某个模块的性能
- 给开源项目做自动化的 easy fix

## 快速开始

建 `.env`：

```
DEEPSEEK_API_KEY=sk-...
LOOPFORGE_MODEL=deepseek-chat
```

命令行：

```bash
pip install -e .
loopforge run --strategy fix --target ./src --eval "pytest"
```

服务模式：

```bash
loopforge serve --port 8848
# 打开 http://localhost:8848
```

## 架构

```
请求 → CLI / REST API / Dashboard
              │
       ┌──────┴──────┐
       │  Loop Engine │  状态机：Plan → Act → Evaluate → Decide
       └──────┬──────┘
              │
    ┌─────────┼─────────┐
    │         │         │
 Strategy  LLM Client  SQLite
 (插件)    (多模型)    (持久化)
```

- **Loop Engine** — 驱动循环，管理快照和回滚，发射 SSE 事件
- **Strategy** — 决定"怎么改"和"好不好"。内置 fix/optimize/refactor，可插拔
- **LLM Client** — 统一接口，自动路由 Claude/OpenAI/DeepSeek
- **SQLite** — 任务和每轮结果持久化
- **Dashboard** — 纯 HTML/JS，无框架依赖

## API

```
GET    /                          Dashboard
POST   /api/v1/loops              创建任务
GET    /api/v1/loops              任务列表
GET    /api/v1/loops/{id}         任务详情
POST   /api/v1/loops/{id}/pause   暂停
POST   /api/v1/loops/{id}/resume  继续
POST   /api/v1/loops/{id}/stop    停止
DELETE /api/v1/loops/{id}         删除
GET    /api/v1/loops/{id}/events  实时事件 (SSE)
GET    /api/v1/strategies         策略列表
```

## 策略

内置三个：

| 策略 | 做什么 | 评估方式 |
|------|--------|---------|
| `fix` | 修 bug / lint / 类型错误 | 检查输出中 error/fail 数量 |
| `optimize` | 性能优化 | benchmark 数值对比 baseline |
| `refactor` | 降低复杂度 | 复杂度 + 测试通过率 |

第三方策略通过 pip 包安装，在 `pyproject.toml` 里声明入口点。

## 项目结构

```
src/loopforge/
├── main.py              CLI
├── server.py            FastAPI + Dashboard
├── engine.py            核心循环 + 回滚
├── worker.py            后台任务（内存 / Celery）
├── celery_app.py        Celery 定义
├── models.py            数据模型
├── db.py                SQLite
├── dashboard/index.html Web 界面
├── strategy/            策略系统
│   ├── base.py
│   ├── registry.py
│   └── builtin/         fix / optimize / refactor
└── llm/                 LLM 抽象层
    ├── client.py
    └── providers/       claude / openai / deepseek
```

## 还没做的

- Docker 沙箱
- GitHub Bot
- generate / review 策略

## License

MIT
