---
title: "When PostgreSQL Becomes AI's Hands — Bruce Momjian's MCP Server in Practice"
date: 2026-05-27
draft: false
categories: ["AIOps"]
tags: ["PostgreSQL", "MCP", "AI", "Agent"]
description: "Bruce Momjian's 70-slide talk at PGDay Armenia, from Transformer vector spaces to a pretzel inventory system, dissecting how MCP beats RAG and how far we are from production."
---

> Original: [Building an MCP Server Using Postgres](https://momjian.us/main/writings/pgsql/mcp.pdf), Bruce Momjian, PGDay Armenia 2026, CC BY 4.0.

> AI-generated ratio: 80%



Bruce Momjian (PG core team, the one who has written release notes for 20+ years) recently gave a talk at PGDay Armenia 2026: [Building an MCP Server Using Postgres](https://momjian.us/main/writings/pgsql/mcp.pdf). 70 slides, extremely dense. Theory and practice — a solid reference.

Reading it directly is hard work. Even having AI interpret it probably won't make sense at first glance. I had to read for a while and ask several questions before it clicked.

These 70 slides can be cleanly split into two layers — the first half is theory, the second half is a hands-on demo. The two layers don't have much to do with each other.

---

# Theory Layer: Explaining the RAG → MCP Evolution Through Transformers (Slides 1-33)

The theory layer takes up nearly half the content, from LLM fundamentals to how MCP works. The outline is clear:

![Talk outline: Generative AI → LLM limitations → RAG → MCP → MCP Server in practice](/img/mcp/outline.png)

## RAG vs MCP: In One Sentence

Everyone knows the RAG workflow: the programmer decides what data to query → retrieval results are appended to the system prompt → the LLM reads and generates a response. **Pre-orchestrated** — what the LLM can see is decided before the user even asks.

MCP is different. Tool descriptions are registered with the LLM, and the LLM **decides for itself** during generation whether to call a tool and which one. **Dynamic decision-making** — the programmer only exposes tools, the LLM handles orchestration.

Bruce sums it up in one sentence:

> RAG can only do what the programmer pre-planned. MCP can dynamically adjust based on output quality, can iteratively call multiple tools, and can trigger external tasks.

## "Word or MCP" — That Set of Vector Embedding Diagrams

Slides 18-33 are the core of the theory layer. Bruce draws a detailed internal Transformer flow diagram:

![MCP Server registered as Tool Embedding Vectors in the vector space](/img/mcp/mcp-servers.png)

His logic: take each MCP tool's description text (e.g., "Return the radiation level (CPM) at 13 Roberts Road..."), embed it into a vector using a text embedding model, and inject it into the attention layer's vector space. Then at each inference step, the output vector matches against the nearest vector —

![The closest vector might be a text token, or an MCP tool](/img/mcp/word-or-mcp.png)

> "The closest vector might be a word or an MCP."

## Is This Model Correct?

This is what puzzled me the most. Here are my thoughts.

Bruce's 15 slides are beautifully drawn, but if you try to understand them as engineering implementation, there are problems:

**① MCP tools don't need "embedding."** In actual engineering, tool definitions are written directly into the system prompt as text. The LLM reads "You have these tools: geiger(), get_pretzel_inventory()…" and uses semantic understanding to decide when to call them. There's no need to compute tool descriptions as vectors, no need to do cosine distance comparisons against word vectors. The essence of Bruce's teaching model is explaining "LLM decision-making" as "nearest vector matching" — this is closer to the retrieval paradigm than the generation paradigm.

**② Attention doesn't produce a "find nearest" operation.** `output = Σ(softmax(Q·K) × V)` yields a weighted-mixed context vector. There's no step of "binary choice between the word embedding table and the tool embedding table." The actual mechanism for LLM tool selection is: attention produces hidden states → LM head → softmax over vocabulary → output tool call JSON. There's never a "word vs tool" choice, only a softmax over the entire vocabulary.

**③ System prompt and user prompt have no boundary in attention.** A token sequence is just a token sequence — attention blocks do Q·K dot products on all tokens equally. There is no "system zone" or "user zone."

So these 33 theory slides can be seen as a simplified teaching model Bruce built for DBAs without an AI background — visually appealing and easy to understand, but don't use it as an architecture diagram. MCP's truly revolutionary aspect is **protocol standardization** (unified tool registration/discovery/calling spec), not any vectorization trick.

---

# Practice Layer: Two Working Demos (Slides 34-69)

Starting from Slide 34, the style abruptly shifts — all code, terminal output, hardware photos. That entire Transformer vector model from the theory layer completely disappears, replaced by `curl`, `psql`, and Perl scripts.

The only thread connecting the two layers is that "they're both talking about MCP." But the vector matching mechanism painted in the theory layer and the actual implementation in the practice layer are nearly two different logic systems. This may be exactly the tension Bruce intended — the theory layer helps you understand why MCP is stronger than RAG, and the practice layer tells you how to actually implement it today.

## Demo 1: Letting ChatGPT Read a Real-World Geiger Counter

Bruce set up a GQ GMC-800 Geiger counter (radiation detector) in his backyard, connected via USB to a Raspberry Pi, taking environmental radiation readings every 15 minutes. First, see ChatGPT using MCP to call real data:

![ChatGPT querying weather via MCP](/img/mcp/chatgpt-weather.png)

MCP can call external tools to get real-time data — something RAG cannot do.

Connected to hardware:

![GQ GMC-800 Geiger counter](/img/mcp/geiger-counter.png)

Wrote a Python wrapper using **fastmcp**:

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

The underlying layer is a Perl script that sends `<GETCPM>>` over serial, reads back a 4-byte CPM value. Apache reverse-proxies port 443 (OpenAI only talks to 443). After registering with ChatGPT:

```
User: What's the radiation level at 13 Roberts Road?
GPT:  I don't have public data for that location...

User: Use my custom app
GPT:  [calls geiger tool] → 14 CPM. Normal background radiation (5-25 CPM).

User: Take five readings and give me the average
GPT:  [calls ×5] 15 16 13 15 15 → average 14.8 CPM
```

Two key behaviors:

1. **The LLM can iteratively call tools and compute** — RAG is a one-shot data dump, MCP is "call → get result → decide → call again → compute"
2. **The user must explicitly authorize** — the first time, ChatGPT didn't say "I have your Geiger counter data." Only when the user said "use my custom app" did the tool call trigger. The security model is conservative

## Demo 2: Using PG as a Pretzel Shop Inventory System

From hardware back to software. Building a pretzel inventory database:

```sql
CREATE TABLE pretzel (
    quantity INTEGER CHECK (quantity >= 0)
);
INSERT INTO pretzel VALUES (0);  -- initial inventory 0
```

MCP tools use `psql` to operate on PG directly:

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

Interaction flow:

```
User: How many pretzels available?
GPT:  0 pretzels.

User: I just baked a tray        → 6 pretzels
User: I sold two                 → 4 remaining
User: I sold four                → 0 remaining

User: I sold one pretzel         → ERROR! CHECK constraint prevented negative quantity
```

The LLM doesn't write SQL directly — it calls your predefined, controlled interfaces. PG's CHECK constraints naturally form a safety net — even if the LLM is tricked into calling the wrong function, the database-level constraint provides a second line of defense.

But this also exposes a problem: the LLM faithfully executed `sold_one_pretzel`, but didn't anticipate that "inventory is 0, calling it will error." **MCP is the execution layer, not the reasoning layer.**

---

# How Far from Production

On the final slide, Bruce frankly admits the current implementation's limitations:

- **No authentication** — anyone can call your MCP Server
- **No parameterization** — all three tools are parameterless functions; real-world tools need to accept parameters
- **No security restrictions on dynamic SQL** — tool descriptions declare semantics, but the LLM could be injected with malicious content
- **Connection pooling, transaction management, rate limiting** — none addressed

Two recommended practical reads:
- [pgedge.com: Lessons Learned Writing an MCP Server for PostgreSQL](https://www.pgedge.com/blog/lessons-learned-writing-an-mcp-server-for-postgresql)
- [CardinalOps: MCP Defaults — Hidden Dangers of Remote Deployment](https://cardinalops.com/blog/mcp-defaults-hidden-dangers-of-remote-deployment/)

---

# Between the Two Layers

Looking back at these 70 slides, the most interesting part isn't any single demo — it's how the theoretical thinking and hands-on work together explain what MCP can do:

1. The theory layer uses Transformer vector spaces to explain "how the LLM chooses between words and tools" — this is a teaching model
2. The practice layer uses `psql`, `curl`, and Perl scripts to actually implement things — this is engineering

The real MCP mechanism — tool definitions inserted as text into the system prompt, the LLM using semantic understanding to decide which tool to call, outputting tool call JSON — needs none of the vector embedding model from the theory layer. Between the two layers, Bruce didn't draw the connecting line. This might not be a bug — it might be a feature.

