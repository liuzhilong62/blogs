---
title: "Case Study: Performance Degradation After Adding an Index and the Generic Plan"
date: 2025-09-13
categories: [PostgreSQL案例]
description: "Analyzing a case where performance dropped after adding an index: the new index caused the optimizer to choose a different execution path, and the cached generic plan prevented ANALYZE from updating the erroneous cached plan"
---

## Problem Description

An index was added the night before, and the next morning the CPU was maxed out. The problematic SQL was easy to locate — just one query. The SQL was running for over 30 seconds, but the day before it only took about 3 seconds, so we needed to examine the before-and-after execution plan changes.

Only the key parts of the execution plan are shown below.

Execution plan before adding the index:

```sql
            ->  Nested Loop  (cost=19.92..2259694.20 rows=265822 width=33)
                  ->  Index Scan using uk_lzl_task on lzl_task t  (cost=0.29..20007.99 rows=195 width=24)
                        Filter: ((created_by)::text = 'LIUZHILONG62'::text)
                  ->  Append  (cost=19.63..11337.15 rows=14842 width=57)
                        ->  Bitmap Heap Scan on lzl_202501 cc_1  (cost=19.63..3053.69 rows=1467 width=66)
                              Recheck Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))
                              ->  Bitmap Index Scan on lzl_202501_task_no_idx  (cost=0.00..19.27 rows=1594 width=0)
                                    Index Cond: ((task_no)::text = (t.task_no)::text)
                        ->  Bitmap Heap Scan on lzl_202502 cc_2  (cost=21.67..3066.85 rows=1604 width=66)
                              Recheck Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))
                              ->  Bitmap Index Scan on lzl_202502_task_no_idx  (cost=0.00..21.27 rows=1605 width=0)
                                    Index Cond: ((task_no)::text = (t.task_no)::text)
                        ->  Index Scan using lzl_202503_task_no_idx on lzl_202503 cc_3  (cost=0.43..1362.61 rows=1637 width=57)
                              Index Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))
                        ->  Index Scan using lzl_202504_task_no_idx on lzl_202504 cc_4  (cost=0.43..604.64 rows=1795 width=56)
                              Index Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))
                        ->  Index Scan using lzl_202505_task_no_idx on lzl_202505 cc_5  (cost=0.43..445.30 rows=1450 width=56)
                              Index Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))
                        ->  Index Scan using lzl_202506_task_no_idx on lzl_202506 cc_6  (cost=0.43..583.94 rows=1675 width=56)
                              Index Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))
                        ->  Index Scan using lzl_202507_task_no_idx on lzl_202507 cc_7  (cost=0.43..633.45 rows=1973 width=56)
                              Index Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))
                        ->  Index Scan using lzl_202508_task_no_idx on lzl_202508 cc_8  (cost=0.43..619.43 rows=1720 width=56)
                              Index Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))
                        ->  Index Scan using lzl_202509_task_no_idx on lzl_202509 cc_9  (cost=0.42..893.03 rows=1521 width=56)
                              Index Cond: ((task_no)::text = (t.task_no)::text)
                              Filter: ((created_date > '2025-01-07 09:00:00'::timestamp without time zone) AND (created_date < '2025-09-03 12:56:44.973'::timestamp without time zone))

```

The created_date time range searches for data within 1 year. The index added the night before was on created_date.

Execution plan after adding the index:

```sql
             ->  Hash Join  (cost=63.37..23740.82 rows=191 width=33)
                    Hash Cond: ((cc.task_no)::text = (t.task_no)::text)
                    ->  Append  (cost=0.00..23376.98 rows=114435 width=58)
                          Subplans Removed: 28
                          ->  Index Scan using idx_lzltab_202501_created_date on lzltab_202501 cc_1  (cost=0.43..1450.59 rows=8958 width=66)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                          ->  Index Scan using idx_lzltab_202502_created_date on lzltab_202502 cc_2  (cost=0.43..1822.73 rows=7405 width=66)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                          ->  Index Scan using idx_lzltab_202503_created_date on lzltab_202503 cc_3  (cost=0.43..1430.03 rows=7917 width=57)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                          ->  Index Scan using idx_lzltab_202504_created_date on lzltab_202504 cc_4  (cost=0.43..2412.44 rows=11041 width=56)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                          ->  Index Scan using idx_lzltab_202505_created_date on lzltab_202505 cc_5  (cost=0.43..2260.73 rows=13381 width=56)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                          ->  Index Scan using idx_lzltab_202506_created_date on lzltab_202506 cc_6  (cost=0.43..3930.10 rows=17832 width=56)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                          ->  Index Scan using idx_lzltab_202507_created_date on lzltab_202507 cc_7  (cost=0.43..3878.77 rows=21786 width=56)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                          ->  Index Scan using idx_lzltab_202508_created_date on lzltab_202508 cc_8  (cost=0.43..4736.72 rows=22033 width=56)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                          ->  Index Scan using idx_lzltab_202509_created_date on lzltab_202509 cc_9  (cost=0.42..627.09 rows=1893 width=56)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
                    ->  Hash  (cost=63.03..63.03 rows=27 width=24)
                          ->  Bitmap Heap Scan on ai_outbound_call_task t  (cost=2.99..63.03 rows=27 width=24)
                                Recheck Cond: ((created_by)::text = ($3)::text)
                                ->  Bitmap Index Scan on idx_ai_call_task_c  (cost=0.00..2.99 rows=27 width=0)
                                      Index Cond: ((created_by)::text = ($3)::text)
```

The new execution plan switched from using the task_no index to using the created_date index, and changed from a Nested Loop to a Hash Join. The cost dropped from 2,259,694 to 23,740 — a 100x reduction. However, the actual execution time increased by roughly 10x.

## Problem Diagnosis

Let's work through three questions to analyze and diagnose the issue:

1. Why did the optimizer suggest the created_date index?
2. Why did it end up using the new index?
3. Why is the estimated row count very small even though the actual execution time is very long?

### Why Did the Optimizer Suggest the created_date Index?

If we directly substitute the parameters from the PostgreSQL log into the SQL text, the execution plan is actually the good one — the one that runs in 3 seconds using the task_no index. The optimization engineer also ran it this way and found it to be fine. But in production, this wasn't the execution plan that was used.

Even when we force PostgreSQL *not* to use the task_no index, the optimizer chooses a sequential scan rather than the created_date index:

```sql
                     Hash Cond: (((cc.task_no)::text || ''::text) = (t.task_no)::text)
                     ->  Append  (cost=0.00..2794425.58 rows=22238757 width=57)
                           ->  Seq Scan on lzltab_202501 cc_1  (cost=0.00..193060.05 rows=1585238 width=66)
                                 Filter: ((created_date > '2025-01-08 11:00:00'::timestamp without time zone) AND (created_date < '2025-09-04 08:31:43'::timestamp without time zone))
                           ->  Seq Scan on lzltab_202502 cc_2  (cost=0.00..178567.54 rows=1480969 width=66)
                                 Filter: ((created_date > '2025-01-08 11:00:00'::timestamp without time zone) AND (created_date < '2025-09-04 08:31:43'::timestamp without time zone))
                           ->  Seq Scan on lzltab_202503 cc_3  (cost=0.00..191073.34 rows=1583356 width=57)
```

This is very strange: no matter how we ran it ourselves, we couldn't get it to use the bad created_date index. So how did production end up using it?

The answer lies in bind variables — it was likely a **generic plan**.

Characteristics of the generic plan:

1. When `plan_cache_mode = auto`, PostgreSQL compares the generic plan cost against the average cost of the first five hard parses (custom plans). If the generic plan has a lower cost, it is used and subsequent executions skip hard parsing; otherwise, every execution undergoes hard parsing (see the source function `choose_custom_plan`).
2. What the generic plan looks like has nothing to do with the actual bind variable values.

This is easy to reproduce using bind variables via PREPARE/EXECUTE:

```sql
PREPARE sql1(timestamp without time zone,timestamp without time zone,text) AS
SELECT COUNT(*)
xxxxxxx...;

=# EXECUTE sql1('2025-01-08 11:00:00','2025-09-04 08:31:43','LIUZHILONG62'); 
 count 
-------
 12016
(1 row)

Time: 367.220 ms
=# EXECUTE sql1('2025-01-08 11:00:00','2025-09-04 08:31:43','LIUZHILONG62'); 
 count 
-------
 12016
(1 row)

Time: 254.386 ms
=# EXECUTE sql1('2025-01-08 11:00:00','2025-09-04 08:31:43','LIUZHILONG62'); 
 count 
-------
 12016
(1 row)

Time: 235.343 ms
=# EXECUTE sql1('2025-01-08 11:00:00','2025-09-04 08:31:43','LIUZHILONG62'); 
 count 
-------
 12016
(1 row)

Time: 234.110 ms
=# EXECUTE sql1('2025-01-08 11:00:00','2025-09-04 08:31:43','LIUZHILONG62'); 
 count 
-------
 12016
(1 row)

Time: 233.570 ms
=# EXECUTE sql1('2025-01-08 11:00:00','2025-09-04 08:31:43','LIUZHILONG62'); 
 count 
-------
 12016
(1 row)

Time: 70678.344 ms (01:10.678)  -- 6th execution is significantly slower


=# select * from pg_prepared_statements\gx  -- pg14 supports pg_prepared_statements
generic_plans   | 1
custom_plans    | 5
```

The first 5 hard parses (custom plans) all executed quickly. The 6th execution used the generic plan, which used the created_date index — this was the exact production failure plan, which was extremely slow.

So while the optimization suggestion to use the created_date index was somewhat problematic, when you substituted bind variables with actual values and ran EXPLAIN, the execution plan was correct. In production, however, the application used bind variables, and the generic plan kicked in — causing the failure.

### Why Is the Estimated Row Count Small But the Actual Execution Time Very Long?

The failing execution plan has a problem: the estimated cost is too small, and the estimated rows are too few.

```sql
                          ->  Index Scan using idx_lzltab_202501_created_date on lzltab_202501 cc_1  (cost=0.43..1450.59 rows=8958 width=66)
                                Index Cond: ((created_date > $1) AND (created_date < $2))
```

From a business logic perspective, this looks abnormal. The created_date condition spans multiple partitions, and since created_date is the partition key, `WHERE created_date >= xx AND <= yy` must be contiguous. The selectivity on a sub-partition should always be 1, meaning rows should equal the sub-partition row count — several million, not several thousand.

At first I thought it was a statistics issue, but the statistics were fairly accurate — the historical partition data for 202501 hadn't changed.

Since this is a generic plan issue, we need to examine the generic plan cost estimation by reading the source code. Cost estimation is more complex, but rows estimation is relatively easier to understand and locate.

```c
static double
calc_rangesel(TypeCacheEntry *typcache, VariableStatData *vardata,
			  const RangeType *constval, Oid operator)
{
...
		else
		{
			/* with any other operator, empty Op non-empty matches nothing */
			selec = (1.0 - empty_frac) * hist_selec;
		}
	}

	/* all range operators are strict */
	selec *= (1.0 - null_frac);
```

`range_select = (1 - null_frac) * histogram_selectivity`. The range histogram selectivity looks at the histogram buckets hit by the range plus any matching MCV entries. However, we don't need to compute all this for this case.

Because the generic plan does not look at the histogram:

```c
/*
 * rangesel -- restriction selectivity for range operators
 */
Datum
rangesel(PG_FUNCTION_ARGS)
{
...
	/*
	 * If we got a valid constant on one side of the operator, proceed to
	 * estimate using statistics. Otherwise punt and return a default constant
	 * estimate.  Note that calc_rangesel need not handle
	 * OID_RANGE_ELEM_CONTAINED_OP.
	 */
	if (constrange)
		selec = calc_rangesel(typcache, &vardata, constrange, operator);
	else
		selec = default_range_selectivity(operator);
...
}
```

`calc_rangesel` is the selectivity calculation function that takes constant values (used above). The `else` branch calls `default_range_selectivity`, which does not pass any constants.

```c
/*
 * Returns a default selectivity estimate for given operator, when we don't
 * have statistics or cannot use them for some reason.
 */
static double
default_range_selectivity(Oid operator)
{
	switch (operator)
	{
        ...
		case OID_RANGE_CONTAINS_ELEM_OP:
		case OID_RANGE_ELEM_CONTAINED_OP:

			/*
			 * "range @> elem" is more or less identical to a scalar
			 * inequality "A >= b AND A <= c".
			 */
			return DEFAULT_RANGE_INEQ_SEL;
	}
}
```

The default range selectivity define:

```c
/* default selectivity estimate for range inequalities "A > b AND A < c" */
#define DEFAULT_RANGE_INEQ_SEL	0.005
```

Let's verify this against the production row estimate:

```sql
 select reltuples::bigint*0.005 from pg_class where relname='lzltab_202501'\gx
-[ RECORD 1 ]------
?column? | 8958.350
```

This matches the actual estimated rows of 8958:

```sql
idx_lzltab_202501_created_date on lzltab_202501 cc_1  (cost=0.43..1450.59 rows=8958 width=66)
```

So the new execution plan's inaccurate estimate is because the generic plan uses a default selectivity of 0.005.

## Summary

### Why Does the Generic Plan Exist, and the Problem with Soft Parsing

It's easier to think of the generic plan as a "DEFAULT estimate plan."

Why does the generic plan always seem to have problems?

Let's trace the reasoning chain:

- The generic plan exists to reduce hard parsing, i.e., to enable soft parsing.
- If we don't hard-parse every execution, we can reuse an execution plan without passing specific parameter values.
- If we don't pass parameters and directly use an execution plan, that plan must be generated in advance.

Ways to generate an execution plan in advance:

- A parameter-less execution plan (the generic plan)
- Reuse an execution plan generated from the first few executions with parameters (PostgreSQL doesn't have this)

If we use a generic plan, it can be inaccurate, for example:

- 1. Data skew (e.g., a particular MCV has a very high frequency, like `WHERE a = 1` but `a = 1` appears extremely often). This heavily depends on what the parameter value actually is, but the generic plan receives no parameters, so the plan cannot be accurate.
- 2. Evenly distributed data where selectivity still cannot be accurately calculated (e.g., `WHERE a > $1 AND a < $2`). Without knowing the range, no one can compute the selectivity. The generic plan receives no parameters, so the plan cannot be accurate.

If we reused plans from the first few parameterized executions (which PostgreSQL doesn't do), they could also be inaccurate:

- Data skew: the first few parameter values may not be representative, and they would heavily influence what the subsequent fixed plan looks like.

### Categories of Generic Plan Estimation Problems

Because the comparison requires 5 custom plans first, generic plan problems can be divided into two categories:

1. The first 5 SQL executions are not representative. This is closely tied to the first 5 execution plans and depends on data skew and whether the first 5 parameter values are representative.
2. The generic plan itself is problematic. Due to data skew or the inability to accurately compute selectivity for evenly distributed data, the generic plan itself is inefficient.

### Optimization Recommendations

Based on this case, generic plan issues can appear on partitioned tables. The partition key is contiguous, and selectivity when scanning all partitions should be 1, but the generic plan uses 0.005, which can easily lead to a "full index scan" scenario.

So during optimization, we need to consider more:

- Avoid creating too many indexes that confuse the optimizer.
- Eliminate generic plan interference. Use `EXECUTE` to truly run the query 6 times.
- At the session level, set `plan_cache_mode = 'force_generic_plan'` or `set plan_cache_mode = 'force_custom_plan'` to compare execution plans. Or, on pg16+, use `EXPLAIN (GENERIC_PLAN)` to compare.

Syntax reference:

```sql
--prepare/excute
PREPARE sql1(text) AS
SELECT COUNT(*) FROM LZL where a=$1;

EXECUTE sql1('zzz');  -- run 6 times first
EXPLAIN EXECUTE sql1('zzz');

select * from pg_prepared_statements -- view prepared statement info, current session only

-- Compare execution plans by setting session parameters before EXPLAIN EXECUTE
set plan_cache_mode='force_generic_plan'
set plan_cache_mode='force_custom_plan'
-- Directly view generic plan, pg16+
explain (GENERIC_PLAN) xx  
```

> Original article: https://lastdba.com/2025/09/13/案例-添加索引性能下降和generic-plan/
*Originally published in Chinese on [lastdba.com](https://lastdba.com).*
