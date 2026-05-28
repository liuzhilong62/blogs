---
title: "当 PostgreSQL 成为 AI 的双手——Bruce Momjian 的 MCP Server 实战"
date: 2026-05-27
categories: ["PostgreSQL案例"]
tags: ["PostgreSQL", "MCP", "AI", "Agent"]
description: "Bruce Momjian 在 PGDay Armenia 2026 演示了用 PostgreSQL 构建 MCP Server，从盖革计数器到椒盐卷饼库存，一文讲清 MCP 比 RAG 强在哪，以及生产落地还差多远。"
---

同事 Bruce Momjian（PG core team，写了 20 多年发行注记的那位）最近在 PGDay Armenia 2026 做了一个演讲，标题很直白：[Building an MCP Server Using Postgres](https://momjian.us/main/writings/pgsql/mcp.pdf)。70 页幻灯片，两个能跑的 demo，看完以后我对 MCP 的认知被刷新了不少。

---

# RAG 的尽头是什么

先厘清一个基本问题：RAG 和 MCP 到底差在哪。

RAG（检索增强生成）的流程大家都很熟了：程序员决定要检索什么数据源，把检索结果拼到 system prompt 里，LLM 读完之后生成回答。这是一种**预编排**——LLM 能看到什么数据，在用户提问之前就已经定好了。

MCP（模型上下文协议）不一样。工具的描述直接注册给 LLM，LLM 在生成过程中**自己判断**要不要调工具、调哪个、参数是什么。这是**动态决策**——程序员只管暴露工具，LLM 负责编排。

Bruce 用一句话总结：

> RAG 只能做 AI 程序员预设的事情。MCP 可以根据输出质量动态调整，可以迭代调用多个工具，还可以触发外部任务。

---

# Demo 1：把盖革计数器接进 ChatGPT

第一个 demo 非常硬核——Bruce 在自家院子里架了一台 GQ GMC-800 盖革计数器，USB 接树莓派，每 15 分钟测一次环境辐射。

MCP Server 的核心代码就几行：

```python
from fastmcp import FastMCP

mcp = FastMCP("Geiger counter MCP server")

@mcp.tool
def geiger() -> int:
    """Return the radiation level (CPM) at 13 Roberts Road, Newtown Square, PA, USA"""
    return subprocess.check_output(
        "/var/lib/postgresql/tmp/geiger", shell=True, text=True
    )
```

底层是一个 Perl 脚本往串口发 `<GETCPM>>` 指令，读回 4 字节的 CPM 值。MCP Server 通过 Apache 反代暴露到 443 端口（因为 OpenAI 只跟 443 通信），注册到 ChatGPT 之后：

```
User: 13 Roberts Road 的辐射水平是多少？
GPT:  我没有这个位置的公开实时辐射数据……

User: 用我的 custom app
GPT:  [调用 geiger tool] → 14 CPM
      正常环境背景辐射（5-25 CPM），安全。

User: 测五次，给我平均值
GPT:  [调用 ×5] 15 16 13 15 15
      平均值：14.8 CPM
```

两个值得关注的点：

**一是 LLM 可以迭代调工具做计算**。RAG 是一次性塞数据，MCP 是"调 → 拿结果 → 判断要不要再调 → 调 → 算"。这已经是 agentic AI 的雏形了。

**二是用户必须显式授权**。Bruce 第一次问的时候 ChatGPT 直接说"我没有这个数据"，直到他说"use my custom app"才触发 tool call。当前的安全模型很保守——工具不会自动执行，需要用户明确指令。

---

# Demo 2：PostgreSQL 当椒盐卷饼店的库存系统

第二个 demo 从硬件回到了软件——用 PG 做 MCP 后端，模拟一个椒盐卷饼（pretzel）店的库存管理。

建表：

```sql
CREATE TABLE pretzel (
    quantity INTEGER CHECK (quantity >= 0)
);
INSERT INTO pretzel VALUES (0);  -- 初始库存为 0
```

三个 MCP tool，全部直接用 `psql` 操作 PG：

```python
@mcp.tool
def get_pretzel_inventory() -> int:
    """Return the number of unsold pretzels"""
    return subprocess.check_output(
        "psql --tuples-only -c 'SELECT quantity FROM pretzel;' -d mcp",
        shell=True, text=True
    )

@mcp.tool
def sold_one_pretzel() -> str:
    """Call this when a pretzel is sold; reduces inventory by one"""
    return subprocess.check_output(
        "psql --tuples-only -c 'UPDATE pretzel SET quantity = quantity - 1;' -d mcp",
        shell=True, text=True
    )

@mcp.tool
def baked_6_pretzels() -> str:
    """Call this when a tray of 6 pretzels is baked; increases inventory"""
    return subprocess.check_output(
        "psql --tuples-only -c 'UPDATE pretzel SET quantity = quantity + 6;' -d mcp",
        shell=True, text=True
    )
```

然后就是一段流畅的自然语言交互：

```
User: How many pretzels available?
GPT:  → 0 pretzels. Time to bake!

User: I just baked a tray
GPT:  → 6 pretzels in inventory

User: I sold two
GPT:  → 4 remaining

User: I sold four
GPT:  → 0 remaining. Time to bake again!

User: I sold one pretzel
GPT:  → ERROR: CHECK constraint 阻止了 quantity 变负数
      → 库存不足，系统拒绝了这次操作
```

**这个 demo 的核心洞察**：LLM 不直接写 SQL，而是调用你预先定义好的受控接口。函数名和描述就足以让 LLM 理解"什么时候该调哪个"。

但也暴露了一个问题：LLM 忠实执行了 `sold_one_pretzel`，但它不会预判"库存已经是 0，调了会报错"。MCP 是执行层，不是推理层。

---

# 那张 Transformer 图的问题

Bruce 在 slides 18-33 画了一套详细的 Transformer 内部流程图来解释 MCP 的工作原理：tool 描述向量化之后塞进 attention 层，和词向量放在同一个空间里，每一步的 output vector 去"找最近似的是词还是 tool"。

这个模型作为教学直觉是好的，但作为实现描述是有问题的。

几个点：

**system 和 user 没有边界**。Token 序列就是 token 序列，attention block 对 system prompt 的 token 和 user prompt 的 token 一视同仁做 Q·K 点积。没有什么"system 区"和"user 区"。

**attention 产出的是加权混合向量，不是去查最近似的查找操作**。`output = Σ(softmax(Q·K) × V)`，没有"找 cosine 距离最近"这一步。那套流程更像 retrieval 的范式，不是 generation 的范式。

**LLM 选工具的实际机制**是 attention 产出的 hidden state → LM head → softmax over 词表 → 输出 token。`{"name": "get_weather", "arguments": {...}}` 就是 model 学会了在某些上下文中生成这个 JSON token 序列。从来没有"在词和 tool 之间二选一"，只有"在整个词表上做 softmax"。

MCP 真正厉害的地方不在向量化的 trick，而在**协议标准化**——一套统一的 tool 注册、发现、调用、返回格式，让任何 LLM 客户端都能对接任何 MCP Server。这才是它比 RAG 革命性的地方。

---

# 生产落地还差多远

Bruce 在最后一页坦承了当前实现的局限：

- **没有认证**——谁都可以调你的 MCP Server
- **没有参数化**——三个 tool 都是无参函数，现实中的 tool 需要传参数
- **动态 SQL 安全性**——工具描述里声明"减库存"，但 LLM 可能被注入恶意指令
- **只调了 psql 命令行**——频率、连接池、事务管理都没考虑

他引用了两篇值得读的文章：[pgedge.com 的 MCP Server 踩坑记](https://www.pgedge.com/blog/lessons-learned-writing-an-mcp-server-for-postgresql) 和 CardinalOps 的[安全分析](https://cardinalops.com/blog/mcp-defaults-hidden-dangers-of-remote-deployment/)，都是生产实践的一手经验。

---

# 总结

两个 demo 的价值不在于能不能直接上生产，而在于**展示了边界在哪**：

1. MCP 的本质是让 LLM 在生成过程中动态调用外部工具，比 RAG 的静态检索灵活得多
2. PG 作为 MCP 后端是天然的——它的 SQL 接口和 CHECK 约束构成了一个自带安全兜底的执行层
3. 但 MCP Server 的认证、注入、事务管理目前完全靠开发者自己，距离"开箱即用的 PG MCP Server"还很远

一个细节：Bruce 演讲里 MCP Server 的代码都是 `/var/lib/postgresql/` 路径，MCP 数据库的用户也叫 `mcp`。这暗示了一个可能的演进方向——PostgreSQL 官方未来会不会内置一个 MCP Server 能力？毕竟 PG 的 extension 框架天然适合这种扩展。

---

> 原文：[Building an MCP Server Using Postgres](https://momjian.us/main/writings/pgsql/mcp.pdf)，Bruce Momjian，PGDay Armenia 2026。
