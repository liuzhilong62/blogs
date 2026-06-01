---
title: "A DBA's Perspective on the 0526 Approved Database List"
date: 2026-05-29
draft: false
categories: ["杂项"]
tags: ["Xinchuang", "Domestic Databases", "Approved List"]
description: "The 2026 No.2 Xinchuang database list released: 23 products pass, Ping An, UnionPay, China Mobile, and China Telecom self-developed databases debut. A DBA's interpretation and reflections."
---

> AI rate 5%

## TL;DR

On May 26, the Xinchuang Database List 2026 No. 2 was released, with 23 products passing (8 centralized + 15 distributed) — the most ever. Most notably: Ping An, UnionPay, China Mobile, and China Telecom — four major buyers — had their self-incubated databases debut on the list. The Xinchuang logic has changed — buyers are no longer just buyers.

## The Latest List

Historical batch statistics for the Xinchuang database list. Data source: China Information Security Evaluation Center (itsec.gov.cn), 8 batches total, 4 containing databases.

**By Batch**

| Batch | Date | Database Products | Achieved Level II |
|-------|------|-------------------|-------------------|
| 2023#1 | 2023-12-26 | 11 (centralized) | None |
| 2024#2 | 2024-09-30 | 17 (6 centralized + 11 distributed) | GaussDB |
| 2025#2 | 2025-08-22 | 3 (centralized) | None |
| 2026#2 | 2026-05-26 | 23 (8 centralized + 15 distributed) | Dameng/Yashan/GaussDB/GoldenDB |

**By Appearances (≥2 times)**

| Vendor | Count |
|--------|-------|
| Dameng | 3 |
| GBASE | 3 |
| Alibaba Cloud | 3 |
| HighGo | 2 |
| Tencent Cloud | 2 |
| East Golden | 2 |
| Vastdata | 2 |
| Huawei Cloud | 2 |
| ZTE (GoldenDB) | 2 |
| OceanBase | 2 |
| Kingbase | 2 |
| Shentong | 2 |
| Xugu | 2 |
| Yashan | 2 |
| Only 1 time | PingCAP/Wanli/Uxin/Ping An/China Mobile/UnionPay/Telecom Cloud/Timecho/Transwarp/DolphinDB/Z-Range/CM Suzhou |

**By Category: Big Tech / Unicorn / Major Buyer**

| Category | Vendors |
|----------|---------|
| Big Tech | Huawei Cloud (GaussDB/TaurusDB/DWS), Alibaba Cloud (PolarDB/AnalyticDB), Tencent Cloud (TDSQL), ZTE (GoldenDB), OceanBase (Ant Group) |
| Unicorns | PingCAP (TiDB), Yashan (SICS), Transwarp (ArgoDB), Timecho (TimechoDB), DolphinDB |
| Major Buyers | Ping An Tech (RASESQL), China UnionPay (UPDRDB), China Mobile (Panwei + He3DB), China Telecom Cloud (TeleDB) |
| Traditional Xinchuang | Dameng, Kingbase, GBASE, Shentong, HighGo, Xugu, Vastdata, East Golden, Wanli, Uxin |

## The Floodgates Open

When this list came out, my reaction was four words: **the floodgates opened**. 23 products — the most ever. A few highlights:

**Ping An RASESQL.** The most unexpected. Ping An Group's fintech capabilities have always been strong, but there was almost no public information about them building a database. Seeing "RASESQL" on the list stunned me for several seconds. A financial buyer of Ping An's scale — once their self-developed database passes national testing, their internal Xinchuang replacement roadmap gains one more path.

**UnionPay UPDRDB.** Equally mysterious. I had no idea UnionPay was building a distributed database before this. UnionPay's transaction volume speaks for itself — a distributed database that can handle their own business won't be technically weak.

**Alibaba Cloud PolarDB for MySQL.** The MySQL-compatible edition of PolarDB not passing had been something many people remembered. Now, all three of PolarDB's main lines — PG edition, distributed edition, MySQL edition — have passed. Add AnalyticDB, and Alibaba Cloud's database family is basically complete.

**China Mobile Panwei + China Telecom TeleDB.** China Mobile already had He3DB (CM Suzhou) pass national testing last year; this year Panwei is their second product. China Telecom TeleDB debuts. Both telecom operators now have their own incubated Xinchuang databases, which should significantly reduce their respective Xinchuang replacement pressure. Interestingly, China Unicom has been silent — their Xinchuang strategy is clearly different from Mobile and Telecom.

**Transwarp ArgoDB.** Transwarp started in the big data/Hadoop ecosystem and now their distributed database has passed national testing. Once crowned "China's First Domestic Big Data Infrastructure Software Stock" with a market cap exceeding 30 billion, their path from data lake to Xinchuang database has been validated.

## Impact

The most important signal from this floodgate opening: **buyers can self-develop databases**.

What are the implications?

- Major buyers who succeed at self-development don't have to be lambs to the slaughter.
- Those major buyers who haven't built one yet may restart their self-development efforts.
- The market share that big tech and unicorns could compete for in the domestic database market just shrank.

Financial industry players UnionPay and Ping An, telecom players China Mobile and China Telecom — all passed national testing, effectively earning a "R&D Success" gold badge. Internally, each organization must be celebrating. For external vendors, what they've lost isn't just major clients — more precisely, **they've lost absolute bargaining power**.

"I know you're in a tough spot, and I know you can't afford not to buy, so I'll swap the butcher's knife for a dragon-slaying blade and slaughter you to death" — for buyers who successfully incubated their own databases, this kind of predicament has been substantially eased. That's significant.

As for where Xinchuang policy goes next, nobody can say. Based on previous lists, things should be getting stricter (last time only 3 databases passed), but this time they unexpectedly opened the floodgates. A sharp contraction next round isn't impossible. Not just China Unicom — insurance industry players like CPIC and PICC, and even capable financial institutions, could consider jumping in to hand-roll their own database.

## Bittersweet Reflections

Since our kernel team sits right behind me, I have some understanding of the Xinchuang R&D process. After consecutive failed submissions, the entire team's morale was extremely low. I believe we weren't the only ones — many teams whose submissions failed felt the same. For industries like finance and telecom, there's a Xinchuang mandate, but if your self-developed product doesn't pass approval, there's no choice at the corporate strategy level, and at the team level, there's no reason for existence. That's why "passing national testing" carries such weight and influence. Thankfully they passed — heartfelt congratulations to them! RaseSQL No.1!

At the same time, it's clear that Xinchuang results and direction are unstable, volatile, and impactful. It determines some companies' strategies and many people's fates. I myself am even a piece on this wheel of fortune.

Beyond those on the list, many organizations poured enormous effort but remain off the list. Their products might be terrible, or they might be excellent. But national testing is that stark watershed — a mysterious ticket of admission. **Pass or fail — in the domestic market, those are two entirely different concepts.**

OK, just some thoughts — might delete later.

## Reference

https://www.itsec.gov.cn/aqkkcp/cpgg/

> Original link: https://lastdba.com/2026/05/29/xinchuang-db-2026-review/
