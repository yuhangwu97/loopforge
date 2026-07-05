<p align="center">
  <h1 align="center">LoopForge</h1>
  <p align="center"><strong>AI-powered Loop Engineering Tool</strong></p>
  <p align="center">
    <img src="https://img.shields.io/badge/version-0.1.0-blue" alt="Version">
    <img src="https://img.shields.io/badge/python-3.10+-green" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License">
  </p>
</p>

---

LoopForge 是一个循环工程工具。它的核心思想很简单：**把代码改进变成一个自动化的闭环**。

给定一个目标和一条检查命令，它自动进入 Plan → Act → Evaluate → Decide 的循环——每轮分析现状、修改代码、评估结果、决定继续还是停止。改坏了就回滚，达标了就停，不行就再来一轮。

和一次性问答式的 AI 编程助手不同，LoopForge 关注的是**迭代收敛**：让代码在一个可控的闭环里逐步变好，直到满足预设标准。

## 它能做什么

### 自动修复

给定一个测试命令，LoopForge 反复运行测试、分析报错、定位并修改代码、再运行测试，直到全部通过。

适用场景：
- 修 bug：`pytest` 红了，让它自己改到绿
- 修 lint：`ruff check` 报了一堆，让它逐条清掉
- 修类型：`mypy` 报了类型错误，让它一个个改

### 性能优化

给定一个 benchmark 命令，LoopForge 先跑一次建立 baseline，然后每轮找瓶颈、改代码、再跑分。分数对比 baseline 计算提升幅度，提升不够就换方向。

适用场景：
- 某个函数慢了，写个 benchmark 脚本让它自己优化
- 数据库查询 N+1 问题，给个性能测试让它改

### 代码重构

给定质量检查命令（如复杂度分析 + 测试），LoopForge 分析代码结构、重构、跑测试确保行为不变。复杂度下降且测试全过才算有效。

适用场景：
- 老代码逻辑纠缠，让它拆成小函数
- 重复代码太多，让它提取公共逻辑

### 任务管理与可观测性

每个任务从创建到完成，每一轮的计划、动作、得分、决策都有完整记录。任务持久化在 SQLite 中，服务重启不丢失。

### 多种运行模式

| 模式 | 命令 | 说明 |
|------|------|------|
| 一次性 | `loopforge run` | 本地跑完出结果 |
| 后台服务 | `loopforge serve` | API + Dashboard，长期运行 |
| 分布式 | `loopforge serve` + `loopforge worker` | Redis + Celery，多 worker 并行 |

### Web Dashboard

内置 Web 管理界面：创建任务、查看进度、展开每轮详情、实时状态更新。运行中的任务通过 SSE 推送状态变更。

### 多模型支持

Claude、OpenAI、DeepSeek 均已接入。设置环境变量即可切换，调用方无需关心底层 provider 差异。

## 快速开始

### 环境准备

```bash
git clone https://github.com/yuhangwu97/loopforge.git
cd loopforge
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 配置 API Key

创建 `.env` 文件：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
LOOPFORGE_MODEL=deepseek-chat
```

Claude 用户设 `ANTHROPIC_API_KEY`，OpenAI 用户设 `OPENAI_API_KEY`。可以同时配置多个，通过 model 名自动路由。

### 跑一个修复任务

```bash
loopforge run --strategy fix --target ./src --eval "pytest"
```

### 启动服务

```bash
loopforge serve --port 8848
```

浏览器打开 `http://localhost:8848`，通过 Dashboard 管理任务。

## 工作原理

LoopForge 的核心是一个四阶段状态机，每轮走一遍：

```
                  ┌──────────┐
                  │   IDLE   │
                  └────┬─────┘
                       │
            ┌──────────▼──────────┐
            │       PLAN          │
            │  运行检查命令        │
            │  LLM 分析输出        │
            │  生成 SEARCH/REPLACE │
            └──────────┬──────────┘
                       │
            ┌──────────▼──────────┐
            │        ACT          │
            │  快照文件（用于回滚） │
            │  执行代码修改        │
            └──────────┬──────────┘
                       │
            ┌──────────▼──────────┐
            │     EVALUATE        │
            │  重新运行检查命令     │
            │  计算得分（0-1）     │
            └──────────┬──────────┘
                       │
            ┌──────────▼──────────┐
            │      DECIDE         │
            │                      │
            │  score ≥ threshold → DONE
            │  改坏了 → BACKTRACK   │
            │  没达标 → CONTINUE    │
            └──────────────────────┘
```

关键设计：

- **快照回滚**：每轮 Act 前自动保存目标文件的内容。如果本轮分数比上一轮低，Decide 阶段返回 BACKTRACK，Engine 自动恢复文件
- **一轮一次 LLM 调用**：Plan 阶段 LLM 直接在回复里带上 SEARCH/REPLACE 块，Act 阶段直接改文件，不需要二次调用
- **可暂停/恢复/取消**：运行中的任务支持运行时控制

## 架构

```
请求入口: CLI / REST API / Dashboard
                │
     ┌──────────┴──────────┐
     │    Loop Engine       │
     │  - 四阶段状态机       │
     │  - 快照与回滚         │
     │  - SSE 事件发射       │
     └──────────┬──────────┘
                │
   ┌────────────┼────────────┐
   │            │            │
   ▼            ▼            ▼
Strategy    LLM Client     Database
- fix       - Claude       - SQLite
- optimize  - OpenAI       - loops 表
- refactor  - DeepSeek     - rounds 表
(可插拔)    (统一接口)      (WAL 模式)
```

- **Strategy 插件系统**：每个策略实现 `plan()`、`act()`、`evaluate()`、`decide()` 四个方法。通过 `pyproject.toml` 的 entry point 注册，pip 安装即可用
- **LLM Client**：统一接口，根据 model 名自动路由。OpenAI 和 DeepSeek 共用基类，消除重复代码
- **Worker**：双模式后台执行。默认 asyncio 进程内任务，检测到 Redis 后自动切换到 Celery

## API

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/` | Dashboard |
| `POST` | `/api/v1/loops` | 创建任务 |
| `GET` | `/api/v1/loops` | 任务列表 |
| `GET` | `/api/v1/loops/{id}` | 任务详情（含每轮记录） |
| `POST` | `/api/v1/loops/{id}/pause` | 暂停 |
| `POST` | `/api/v1/loops/{id}/resume` | 恢复 |
| `POST` | `/api/v1/loops/{id}/stop` | 停止 |
| `DELETE` | `/api/v1/loops/{id}` | 删除 |
| `GET` | `/api/v1/loops/{id}/events` | SSE 实时事件流 |
| `GET` | `/api/v1/strategies` | 可用策略列表 |

创建任务示例：

```json
{
    "config": {
        "name": "fix-auth-bug",
        "strategy": "fix",
        "target": { "path": "./src/auth", "language": "python" },
        "constraints": {
            "max_rounds": 10,
            "max_tokens_per_round": 50000,
            "evaluation": "pytest tests/ -v",
            "threshold": 0.9,
            "timeout_per_round": 300,
            "sandbox": false
        },
        "llm_model": "deepseek-chat"
    }
}
```

## 策略开发

自定义策略只需继承 `BaseStrategy`：

```python
from loopforge.strategy.base import BaseStrategy, ActionPlan, ActionResult, EvaluateResult
from loopforge.models import Decision, Constraints, RoundResult

class MyStrategy(BaseStrategy):
    name = "my-strategy"
    description = "一句话描述"

    async def plan(self, state):
        # 分析现状，返回 ActionPlan（含 filepath/search/replace）
        ...

    async def act(self, plan, state):
        # 执行修改，返回 ActionResult
        ...

    async def evaluate(self, result, state):
        # 跑检查，返回 EvaluateResult（含 score 0-1）
        ...

    async def decide(self, score, history, constraints):
        # 返回 Decision.CONTINUE / STOP / BACKTRACK / CHANGE_STRATEGY
        ...
```

在 `pyproject.toml` 中注册：

```toml
[project.entry-points."loopforge.strategies"]
my-strategy = "my_package.strategies:MyStrategy"
```

## 项目结构

```
src/loopforge/
├── main.py              CLI 入口
├── server.py            FastAPI 服务 + Dashboard 路由
├── engine.py            核心循环引擎 + 快照/回滚
├── worker.py            后台任务管理（asyncio / Celery 双模式）
├── celery_app.py        Celery 应用定义
├── models.py            Pydantic 数据模型
├── db.py                SQLite 持久化层
├── dashboard/
│   └── index.html       Web 管理界面
├── strategy/
│   ├── base.py          策略抽象基类
│   ├── registry.py      策略注册与发现
│   └── builtin/         内置策略
│       ├── fix.py
│       ├── optimize.py
│       └── refactor.py
└── llm/
    ├── client.py         多 provider 统一接口
    ├── types.py          共享类型定义
    └── providers/
        ├── claude.py
        ├── openai.py
        ├── deepseek.py
        └── _openai_compatible.py  OpenAI 兼容基类
```

## 下一步

- [ ] Docker 沙箱隔离
- [ ] GitHub Bot（PR 触发自动修）
- [ ] `generate` 和 `review` 策略
- [ ] 每轮 token 用量追踪

## License

MIT
