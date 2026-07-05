# LoopForge — AI-Powered Engineering Loop Engine

> 一个开源的后台服务，持续运行 AI 驱动的工程迭代循环。
> 给定目标 → 自动规划 → 执行 → 评估 → 改进 → 再循环，直到满足条件。

## 一、核心理念

传统的 AI Agent 是**线性的**：提问 → 回答。  
LoopForge 是**螺旋上升的**：提问 → 尝试 → 评估 → 改进 → 再尝试 → ...

```
Round 1:  [Plan] → [Act] → [Evaluate] → score: 60
Round 2:  [Plan] → [Act] → [Evaluate] → score: 72  ↑
Round 3:  [Plan] → [Act] → [Evaluate] → score: 88  ↑
Round 4:  [Plan] → [Act] → [Evaluate] → score: 91  ↑ (threshold met, stop)
```

每次循环：
- **产出可见**：做了什么、结果怎样
- **方向可逆**：如果变差就回滚
- **决策可追溯**：为什么选择这个行动

---

## 二、架构总览

```
                        ┌──────────────┐
                        │   Webhook    │  (GitHub, Slack, cron...)
                        └──────┬───────┘
                               │
  ┌────────────────────────────┼──────────────────────────────┐
  │                     LoopForge Service                      │
  │                                                            │
  │  ┌──────────┐    ┌──────────────┐    ┌─────────────────┐  │
  │  │ REST API │ ←→ │ Loop Manager │ ←→ │ Strategy Registry│  │
  │  │ (FastAPI)│    │ (scheduler)  │    │ (plugin loader) │  │
  │  └──────────┘    └──────┬───────┘    └─────────────────┘  │
  │                         │                                  │
  │                  ┌──────┴───────┐                          │
  │                  │ Loop Workers │  (background tasks)      │
  │                  └──────┬───────┘                          │
  │                         │                                  │
  │     ┌───────────────────┼───────────────────┐              │
  │     │                   │                   │              │
  │  ┌──┴──┐   ┌────────┐  │   ┌────────┐  ┌──┴──────┐       │
  │  │ DB  │   │  LLM   │  │   │  Tool  │  │ Sandbox │       │
  │  │SQLite│  │ Client │  │   │ Exec   │  │ (docker)│       │
  │  │/PG  │   │(Claude)│  │   │ (bash) │  │         │       │
  │  └─────┘   └────────┘  │   └────────┘  └─────────┘       │
  │                         │                                  │
  └─────────────────────────┼──────────────────────────────────┘
                            │
                     ┌──────┴───────┐
                     │  Dashboard   │   (Web UI)
                     │  - 活跃循环   │
                     │  - 历史记录   │
                     │  - 指标图表   │
                     └──────────────┘
```

---

## 三、核心 Loop Engine

每个 Loop 是一个有限状态机：

```
                  ┌─────────────────────────┐
                  │        IDLE             │
                  └────────────┬────────────┘
                               │ start
                  ┌────────────▼────────────┐
                  │        PLAN             │  LLM 分析现状，生成行动计划
                  └────────────┬────────────┘
                               │
                  ┌────────────▼────────────┐
                  │         ACT             │  执行计划（改代码/跑命令/调API）
                  └────────────┬────────────┘
                               │
                  ┌────────────▼────────────┐
                  │      EVALUATE           │  度量结果（测试/benchmark/lint）
                  └────────────┬────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
               score >= threshold    score < threshold
                    │                     │
           ┌────────▼────────┐   ┌────────▼────────┐
           │     DONE        │   │    DECIDE        │
           └─────────────────┘   │  continue/       │
                                 │  backtrack/      │
                                 │  change strategy │
                                 └────────┬─────────┘
                                          │
                                 ┌────────▼────────┐
                                 │      PLAN        │  (next round)
                                 └─────────────────┘
```

关键设计决策：

1. **每轮有成本上限**：防止无限烧 token，默认每轮最多 5 次 LLM 调用
2. **回溯机制**：如果本轮 score < 上轮 score，自动回滚变更
3. **探索/利用平衡**：前几轮鼓励多方向探索，后期聚焦最优方向
4. **人类可中断**：任意时刻可以暂停、review、手动介入

---

## 四、API 设计

```
POST   /api/v1/loops             创建新循环
GET    /api/v1/loops             列出所有循环
GET    /api/v1/loops/{id}        查看循环详情
POST   /api/v1/loops/{id}/pause  暂停
POST   /api/v1/loops/{id}/resume 恢复
POST   /api/v1/loops/{id}/stop   停止
GET    /api/v1/loops/{id}/rounds 查看每轮记录
GET    /api/v1/loops/{id}/events SSE 实时事件流

GET    /api/v1/strategies        列出可用策略
POST   /api/v1/webhook/github    GitHub webhook 触发
```

创建循环的请求体示例：

```json
{
    "name": "optimize-auth-module",
    "strategy": "optimize",
    "target": {
        "type": "code",
        "path": "./src/auth",
        "language": "python"
    },
    "constraints": {
        "max_rounds": 10,
        "max_tokens_per_round": 50000,
        "evaluation": "pytest && python bench.py",
        "threshold": 0.9,
        "sandbox": true
    },
    "schedule": null
}
```

---

## 五、Strategy 插件系统

Strategy 是一个 Python 类，实现 `plan / act / evaluate / decide` 四个方法：

```python
from loopforge.strategy.base import BaseStrategy, RoundResult

class OptimizeStrategy(BaseStrategy):
    """代码性能优化循环"""

    async def plan(self, ctx: LoopContext) -> ActionPlan:
        """分析当前代码，找到性能瓶颈，生成优化方案"""
        # LLM: "这段代码的瓶颈在哪？怎么优化？"
        ...

    async def act(self, plan: ActionPlan, ctx: LoopContext) -> ActionResult:
        """在 sandbox 里执行代码修改"""
        # 写文件 → 如果有 sandbox 则在容器内执行
        ...

    async def evaluate(self, result: ActionResult, ctx: LoopContext) -> float:
        """跑 benchmark，返回 score (0-1)"""
        # 跑 pytest + benchmark，归一化分数
        ...

    async def decide(self, score: float, history: list[RoundResult]) -> Decision:
        """决定：继续 / 换方向 / 停止 / 回滚"""
        ...
```

内置策略：

| 策略 | 用途 | 评估指标 |
|------|------|---------|
| `optimize` | 性能优化 | benchmark 耗时、吞吐量 |
| `fix` | Bug 修复 | 测试通过率、lint 错误数 |
| `refactor` | 代码重构 | 圈复杂度、测试覆盖、可维护性评分 |
| `generate` | 代码生成 | 测试通过 + 需求匹配度 |
| `review` | 代码审查 | 问题密度、严重程度 |
| `custom` | 自由任务 | 用户自定义评估脚本 |

第三方策略通过 pip 安装：

```bash
pip install loopforge-strategy-sql-optimizer
```

---

## 六、三种运行模式

### 模式 1：一次性任务
```bash
loopforge run --strategy optimize --target ./src --eval "python bench.py"
# 跑完就退出，输出最终结果
```

### 模式 2：后台服务 (核心模式)
```bash
loopforge serve --port 8848
# 启动 API + Dashboard，通过 HTTP 提交任务、查看状态
```

### 模式 3：GitHub Bot
```bash
loopforge bot --repo owner/repo --on-pr
# 监听 PR，自动 review/optimize/fix
```

---

## 七、记忆系统

LoopForge 在循环之间保持记忆：

```
每轮记录:
  - round_number
  - plan (LLM 生成的计划)
  - actions (执行了什么)
  - score (评估分数)
  - diff (代码变更)
  - tokens_used
  - duration

跨循环知识:
  - 哪些策略在当前任务上有效
  - 哪些方向已经探索过（避免重复）
  - LLM 的 prompt 可以注入历史经验
```

---

## 八、安全设计

- **Sandbox 模式**：代码变更在 Docker 容器中执行，隔离于宿主机
- **Token 预算**：每轮/每任务有 token 上限，防止失控
- **审批门**：敏感操作（如 git push、删除文件）需要人工确认
- **只读模式**：可以先 dry-run 看计划，不实际执行

---

## 九、项目结构

```
loopforge/
├── README.md
├── LICENSE               (MIT)
├── pyproject.toml
├── docker-compose.yml
├── Makefile
│
├── docs/
│   ├── DESIGN.md         ← 这个文件
│   ├── quickstart.md
│   └── strategy-dev.md   # 如何开发自定义策略
│
├── config/
│   ├── default.yaml
│   └── strategies.yaml
│
├── src/loopforge/
│   ├── __init__.py
│   ├── main.py            # 入口：serve / run / bot
│   ├── server.py          # FastAPI app
│   ├── engine.py          # Loop 引擎核心
│   ├── worker.py          # 后台 Worker
│   ├── models.py          # Pydantic 模型
│   ├── db.py              # 持久化层（SQLite → PostgreSQL）
│   ├── sandbox.py         # Docker sandbox 管理
│   ├── hooks.py           # Webhook 处理
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py        # Abstract BaseStrategy
│   │   ├── registry.py    # 策略注册与发现
│   │   ├── loader.py      # 插件加载器
│   │   └── builtin/
│   │       ├── optimize.py
│   │       ├── fix.py
│   │       ├── refactor.py
│   │       ├── generate.py
│   │       └── review.py
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py      # LLM 抽象层
│   │   └── providers/
│   │       ├── claude.py
│   │       └── openai.py
│   │
│   ├── dashboard/
│   │   ├── index.html
│   │   ├── style.css
│   │   └── app.js
│   │
│   └── templates/
│       └── prompts/       # LLM prompt 模板
│           ├── plan.j2
│           └── decide.j2
│
├── tests/
│   ├── test_engine.py
│   ├── test_strategies.py
│   └── fixtures/
│
└── examples/
    ├── optimize_sql.py
    ├── fix_eslint.py
    └── github_bot.py
```

---

## 十、技术选型

| 关注点 | 选择 | 理由 |
|--------|------|------|
| Web 框架 | FastAPI | 异步、类型安全、生态好 |
| LLM 客户端 | Anthropic SDK + OpenAI SDK | 支持多 provider |
| 任务队列 | Celery + Redis | 可靠、可扩展 |
| 持久化 | SQLite (默认) / PostgreSQL (生产) | 渐进式复杂度 |
| Sandbox | Docker SDK for Python | 隔离执行环境 |
| Dashboard | 纯 HTML/JS（无框架） | 零依赖、轻量 |
| 配置 | YAML + Pydantic Settings | 类型校验 |
| 包管理 | Poetry / uv | 现代 Python 打包 |

---

## 十一、MVP 路线图

### Phase 1 — 单机可用 (2-3 周)
- [x] 核心 Loop 引擎（状态机）
- [ ] CLI: `loopforge run`
- [ ] 一个内置策略 `fix`
- [ ] SQLite 持久化
- [ ] Claude API 集成

### Phase 2 — 服务化 (1-2 周)
- [ ] `loopforge serve` + REST API
- [ ] SSE 事件流
- [ ] 基础 Dashboard
- [ ] Docker 部署

### Phase 3 — 生态 (2-3 周)
- [ ] 策略插件系统
- [ ] Sandbox 模式
- [ ] GitHub Bot 模式
- [ ] 更多内置策略

### Phase 4 — 开源
- [ ] 文档、示例、GIF
- [ ] pip 发布
- [ ] CI/CD
- [ ] 社区贡献指南

---

## 十二、竞品对比

| | LoopForge | Aider | Sweep | OpenHands |
|------|-----------|-------|-------|-----------|
| 运行模式 | **后台服务** | CLI | GitHub Bot | Web/CLI |
| 核心能力 | 通用迭代循环 | 代码编辑 | PR 自动化 | 全栈开发 |
| 策略可插拔 | ✅ | ❌ | ❌ | 有限 |
| Sandbox | ✅ | ❌ | ✅ | ✅ |
| 开源 | ✅ | ✅ | ✅ | ✅ |

---

## 十三、一个典型场景

用户提交一个 "优化 auth 模块性能" 的任务：

```
Round 1:
  Plan:  "分析 auth.py 的数据库查询，发现 N+1 问题"
  Act:   "添加 joinedload 预加载关联表"
  Eval:  "benchmark: 120ms → 85ms, score: 0.71"

Round 2:
  Plan:  "JWT decode 每次都在做，可以缓存验证结果"
  Act:   "添加 Redis 缓存层，TTL 5min"
  Eval:  "benchmark: 85ms → 45ms, score: 0.88"

Round 3:
  Plan:  "bcrypt 验证太慢，考虑降低 rounds 或用 argon2"
  Act:   "改用 argon2id"
  Eval:  "benchmark: 45ms → 38ms, score: 0.92"

Round 4:
  Plan:  "数据库索引缺失"
  Act:   "添加复合索引"
  Eval:  "benchmark: 38ms → 22ms, score: 0.95 ≥ threshold 0.9"

Done: "auth 模块性能从 120ms 优化到 22ms，提升 5.5x"
```

---

## 十四、设计原则

1. **Observable**：每步可观测，不黑盒
2. **Reversible**：变差了能回滚
3. **Bounded**：有时间和资源上限
4. **Pluggable**：策略、LLM、工具都可替换
5. **Simple First**：从 CLI + SQLite 开始，不引入不必要的复杂度
