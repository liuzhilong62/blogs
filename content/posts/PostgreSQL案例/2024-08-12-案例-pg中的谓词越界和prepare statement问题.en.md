---
title: "Case Study: Predicate Out-of-Bounds and Prepared Statement Issues in PostgreSQL"
date: 2024-08-12
categories: [PostgreSQL案例]
description: "Analyzing the root cause of wrong index selection in execution plans: stale statistics at month-end causing predicate out-of-bounds, combined with prepared statement caching preventing plan updates even after ANALYZE."
---

## The Phenomenon

Case: The execution plan changed and chose the wrong index, causing SQL performance to degrade from milliseconds to seconds. After collecting statistics, the business SQL was still slow. Ultimately, the problem was resolved by dropping the `DAILY_DATE` time index and creating a composite index on `(DAILY_DATE, A_ID)`.

Questions:

1. Why did the optimizer choose the `DAILY_DATE` index instead of the more selective `A_ID` index?
2. Why did collecting statistics have no effect?

## Stale Statistics

```sql
-- Simplified SQL
select
         *
        from tablzl
        where A_ID = $1
        AND IS_DELETE = 'N'
        AND DAILY_DATE = to_date($2, 'yyyyMMdd')
              and PARTITION_KEY >= $3  
              and PARTITION_KEY <= $4
```

The optimizer chose the `DAILY_DATE` index instead of the more selective `A_ID` index:

```sql
Append  (cost=0.44..8.83 rows=2 width=204)
  ->  Index Scan using tablzl_p202401_DAILY_DATE_idx on tablzl_p202401 tablzl_1  (cost=0.44..5.47 rows=1 width=203)
        Index Cond: (DAILY_DATE = to_date('20240223'::text, 'yyyyMMdd'::text))
        Filter: ((partition_key >= 202401) AND (partition_key <= 202402) AND ((A_ID)::text = 'ID1234567890987654321'::text) AND ((is_delete)::text = 'N'::text))
  ->  Index Scan using tablzl_p202402_DAILY_DATE_idx on tablzl_p202402 tablzl_2  (cost=0.44..3.35 rows=1 width=204)
        Index Cond: (DAILY_DATE = to_date('20240223'::text, 'yyyyMMdd'::text))
        Filter: ((partition_key >= 202401) AND (partition_key <= 202402) AND ((A_ID)::text = 'ID1234567890987654321'::text) AND ((is_delete)::text = 'N'::text))
```

- For the `p202401` partition, whether it uses the `DAILY_DATE` or `A_ID` index doesn't make much difference, because the January partition has no data for February 23.
- For the `p202402` partition, whether it uses the `DAILY_DATE` or `A_ID` index makes a huge difference. Using the `DAILY_DATE` index, its estimated cost is 3.35 with rows=1, but in reality there are millions of rows, causing it to run for 2 seconds.

The statistics for `p202402` contain MCV (Most Common Values):

```sql
=  select * from pg_stats where tablename='tablzl_p202402' and attname='DAILY_DATE' \gx
most_common_vals       | {2024-02-21,2024-02-20,2024-02-22,2024-02-10,2024-02-15,2024-02-19,2024-02-16,2024-02-18,2024-02-17,2024-02-14,2024-02-11,2024-02-07,2024-02-12,2024-02-06,2024-02-08,2024-.
                       |.02-09,2024-02-03,2024-02-05,2024-02-01,2024-02-02,2024-01-31,2024-02-13,2024-02-04}
most_common_freqs      | {0.0481,0.047766667,0.0466,0.0449,0.0441,0.043833334,0.043733332,0.043466665,0.043133333,0.043066666,0.042366665,0.041866668,0.041366667,0.041366667,0.039766666,0.0394,0.039333332,0..
                       |.038766667,0.03863333,0.0381,0.038066667,0.037966665,0.037566666,0.036733333}
```

Calculate the sum of MCV frequencies:

```sql
= select 0.0481+0.047766667+0.0466+0.0449+0.0441+0.043833334+0.043733332+0.043466665+0.043133333+0.043066666+0.042366665+0.041866668+0.041366667+0.041366667+0.039766666+0.0394+0.039333332+0.038766667+0.03863333+0.0381+0.038066667+0.037966665+0.037566666+0.036733333;
  ?column?   
-------------
 0.999999990
```

It's exactly 1, meaning the planner estimates that days 1-22 represent all the data in this partition, and day 23 should have 0 rows. So when estimating rows for day 23 data, the planner assumes rows=1, and thus chooses the `DAILY_DATE` index. In reality, day 23 had millions of rows.

Essentially, this is a problem caused by stale statistics. Why were the first 22 days fine, and why didn't day 23 trigger automatic collection?

```sql
= select relname,reloptions from pg_class where relname='tablzl';
          relname           | reloptions 
----------------------------+------------
 tablzl | [null]

= show autovacuum_analyze_scale_factor;
 autovacuum_analyze_scale_factor 
---------------------------------
 0.1
```

The trigger threshold defaults to 0.1 — auto-ANALYZE only triggers when data changes reach 1/10. This is a monthly partition, with data inserted and updated daily. Early in the month, writing 2 million rows per day would trigger multiple ANALYZEs (the threshold of 50 can be ignored), but at month end, for example on day 23, writing 2 million rows would not trigger ANALYZE because only 1/23 of the data changed. In this scenario, data was also updated after insertion — 2 million inserts and 2 million updates — so the data change on day 23 was about 1/11, just barely not triggering ANALYZE. **This also explains why the first 20 days ran stably.**

Additionally, since the data change threshold is a ratio, as long as the daily data change volume is relatively uniform, this month-end statistics inaccuracy problem will always occur!

## Execution Plan Caching

Since this was a stale statistics problem, manually collecting statistics should have resolved it. In practice, however, after collection, the business SQL was still slow.

After running ANALYZE, manual `EXPLAIN ANALYZE` showed the correct execution plan.

This indicated that ANALYZE should have helped, but it didn't affect the business sessions. Since the SQL execution used long-lived sessions, I suspected that the JDBC driver was using prepared statements to cache execution plans ([JDBC PreparedStatement](https://jenkov.com/tutorials/jdbc/preparedstatement.html#:~:text=JDBC%20PreparedStatement%201%20Creating%20a%20PreparedStatement%20Before%20you,Reusing%20a%20PreparedStatement%20...%205%20PreparedStatement%20Performance%20)).

In PostgreSQL 13 (RasesQL 1.3), collecting statistics does not invalidate prepared statements; re-parsing only happens by reconnecting the session.

Prepared statements generate a generic execution plan. Due to inaccurate statistics, the generic execution plan, like the parameter-specific execution plan, could choose the wrong index.


## Characteristics of Prepared Statements

`psql` supports prepared statements, controlled by the `plan_cache_mode` parameter:

- `auto`: default, uses the five-execution mechanism
- `force_custom_plan`: always performs hard parsing, generating a custom plan
- `force_generic_plan`: always uses the generic plan with bound variables

Syntax:

```sql
PREPARE plan1(text,integer) AS select * from tlzl1 where id=$1 and month=$2;
EXECUTE plan1('256ac66bb53d31bc6124294238d6410c','11');

deallocate plan1|all;  -- invalidates the prepared statement; disconnecting also works
```

View: (basically useless since it's local — you can't see anything in production)

```sql
select * from pg_prepared_statements;
```

### How Generic Plans Are Generated

Normally, a prepared statement can generate a generic plan after running 5 times. There are many demonstrations online, so I won't demonstrate the normal case here. Below are the "magical" phenomena I observed during testing:

```sql
-- Prepare data
create table tlzl1(id varchar(50),month int);
INSERT INTO tlzl1 SELECT md5(g::text),EXTRACT(month FROM g)
FROM generate_series('2023-01-01'::date, '2023-11-30'::date, '1 minute') as g;
create index idx_id on tlzl1(id);
create index idx_month on tlzl1(month);
analyze tlzl;

-- Execute prepared statement
PREPARE plan1(text,integer) AS        
select * from tlzl1 where id=$1 and month=$2;
EXECUTE plan1('256ac66bb53d31bc6124294238d6410c','11');
explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','11');
```

Note that only data before December was inserted — December has no data. At this point, querying December data can use the `month` index:

```sql
=# explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','12');
                                                    QUERY PLAN                                                    
------------------------------------------------------------------------------------------------------------------
 Index Scan using idx_month on tlzl1  (cost=0.42..2.94 rows=1 width=37) (actual time=0.035..0.036 rows=0 loops=1)
   Index Cond: (month = 12)
   Filter: ((id)::text = '256ac66bb53d31bc6124294238d6410c'::text)
 Planning Time: 0.170 ms
 Execution Time: 0.058 ms
(5 rows)

Time: 0.551 ms
=# explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','12');
                                                    QUERY PLAN                                                    
------------------------------------------------------------------------------------------------------------------
 Index Scan using idx_month on tlzl1  (cost=0.42..2.94 rows=1 width=37) (actual time=0.021..0.021 rows=0 loops=1)
   Index Cond: (month = 12)
   Filter: ((id)::text = '256ac66bb53d31bc6124294238d6410c'::text)
 Planning Time: 0.168 ms
 Execution Time: 0.046 ms
(5 rows)

Time: 0.488 ms
=# explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','12');
                                                    QUERY PLAN                                                    
------------------------------------------------------------------------------------------------------------------
 Index Scan using idx_month on tlzl1  (cost=0.42..2.94 rows=1 width=37) (actual time=0.017..0.018 rows=0 loops=1)
   Index Cond: (month = 12)
   Filter: ((id)::text = '256ac66bb53d31bc6124294238d6410c'::text)
 Planning Time: 0.157 ms
 Execution Time: 0.040 ms
(5 rows)

Time: 0.419 ms
=# explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','12');
                                                    QUERY PLAN                                                    
------------------------------------------------------------------------------------------------------------------
 Index Scan using idx_month on tlzl1  (cost=0.42..2.94 rows=1 width=37) (actual time=0.019..0.020 rows=0 loops=1)
   Index Cond: (month = 12)
   Filter: ((id)::text = '256ac66bb53d31bc6124294238d6410c'::text)
 Planning Time: 0.160 ms
 Execution Time: 0.044 ms
(5 rows)

Time: 0.479 ms
=# explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','12');
                                                    QUERY PLAN                                                    
------------------------------------------------------------------------------------------------------------------
 Index Scan using idx_month on tlzl1  (cost=0.42..2.94 rows=1 width=37) (actual time=0.018..0.018 rows=0 loops=1)
   Index Cond: (month = 12)
   Filter: ((id)::text = '256ac66bb53d31bc6124294238d6410c'::text)
 Planning Time: 0.155 ms
 Execution Time: 0.041 ms
(5 rows)

Time: 0.426 ms
-- Sixth execution
=# explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','12');
                                                  QUERY PLAN                                                   
---------------------------------------------------------------------------------------------------------------
 Index Scan using idx_id on tlzl1  (cost=0.42..5.44 rows=1 width=37) (actual time=0.044..0.045 rows=0 loops=1)
   Index Cond: ((id)::text = $1)
   Filter: (month = $2)
   Rows Removed by Filter: 1
 Planning Time: 0.023 ms
 Execution Time: 0.079 ms
(6 rows)
```

On the sixth execution, the generic plan was bound — but it wasn't the same plan as the first five executions; it used the `id` index. If `id` had even higher cardinality, you could also observe cases where the generic plan simply couldn't be bound (not shown here).

Let's look at the source code:

`choose_custom_plan`:

```c
static bool

choose_custom_plan(CachedPlanSource *plansource, ParamListInfo boundParams)

{
...
	/* Generate custom plans until we have done at least 5 (arbitrary) */
	if (plansource->num_custom_plans < 5)
		return true;

	avg_custom_cost = plansource->total_custom_cost / plansource->num_custom_plans;

	/*
	 * Prefer generic plan if it's less expensive than the average custom
	 * plan.  (Because we include a charge for cost of planning in the
	 * custom-plan costs, this means the generic plan only has to be less
	 * expensive than the execution cost plus replan cost of the custom
	 * plans.)
	 *
	 * Note that if generic_cost is -1 (indicating we've not yet determined
	 * the generic plan cost), we'll always prefer generic at this point.
	 */
	if (plansource->generic_cost < avg_custom_cost)
		return false;

	return true;
}		
```

As long as the generic plan's cost is less than the average cost of the first 5 custom plans, the generic plan is used.

While the 5-execution mechanism is well-known, it's important to note how the generic plan is generated. On the 5th execution, there is no generic plan yet (initially, `generic_cost=-1`), so it directly goes to the `!customplan` logic in `GetCachedPlan`:

```c
CachedPlan *
GetCachedPlan(CachedPlanSource *plansource, ParamListInfo boundParams,
			  bool useResOwner, QueryEnvironment *queryEnv)
{
...
	customplan = choose_custom_plan(plansource, boundParams);

	if (!customplan)
	{
		if (CheckCachedPlan(plansource))
		{
			/* We want a generic plan, and we already have a valid one */
			plan = plansource->gplan;
			Assert(plan->magic == CACHEDPLAN_MAGIC);
		}
		else
		{
			/* Build a new generic plan */
			plan = BuildCachedPlan(plansource, qlist, NULL, queryEnv);
			/* Just make real sure plansource->gplan is clear */
			ReleaseGenericPlan(plansource);
			/* Link the new generic plan into the plansource */
			plansource->gplan = plan;
			plan->refcount++;
			/* Immediately reparent into appropriate context */
			if (plansource->is_saved)
			{
				/* saved plans all live under CacheMemoryContext */
				MemoryContextSetParent(plan->context, CacheMemoryContext);
				plan->is_saved = true;
			}
			else
			{
				/* otherwise, it should be a sibling of the plansource */
				MemoryContextSetParent(plan->context,
									   MemoryContextGetParent(plansource->context));
			}
			/* Update generic_cost whenever we make a new generic plan */
			plansource->generic_cost = cached_plan_cost(plan, false);

			/*
			 * If, based on the now-known value of generic_cost, we'd not have
			 * chosen to use a generic plan, then forget it and make a custom
			 * plan.  This is a bit of a wart but is necessary to avoid a
			 * glitch in behavior when the custom plans are consistently big
			 * winners; at some point we'll experiment with a generic plan and
			 * find it's a loser, but we don't want to actually execute that
			 * plan.
			 */
			customplan = choose_custom_plan(plansource, boundParams);

			/*
			 * If we choose to plan again, we need to re-copy the query_list,
			 * since the planner probably scribbled on it.  We can force
			 * BuildCachedPlan to do that by passing NIL.
			 */
			qlist = NIL;
		}
	}
	...
	return plan;
}	
```

In the `!customplan` logic, if a generic plan already exists, use it directly. If not, generate one via `BuildCachedPlan`, which is the main logic for generating plans — converting a query tree into a plan tree.

What about parameters? As the comments explain, pass NULL when there are no parameters to enter the plan generation logic:

```c
To build a generic, parameter-value-independent plan, pass NULL for
 * boundParams.  To build a custom plan, pass the actual parameter values via
 * boundParams
```

What execution plan does the optimizer prefer when NULL is passed? This part of the code logic is somewhat complex. From the optimizer's perspective, there may be multiple plans to choose from, but one must be selected as the generic plan.

And that selected generic plan is what gets compared against the cost of the first 5 plans.

Why didn't repeatedly executing a lower-cost plan produce the desired generic plan?

**What the generic plan looks like has nothing to do with the first five execution plans — the first five only determine whether this generic plan gets bound.**

From an optimizer design perspective, generic plans are meant to reduce parsing time and improve SQL execution efficiency, suitable for many small queries. The problem is that generic plans themselves are crude, and PostgreSQL introduced the five-execution mechanism precisely to reduce the likelihood of a generic plan being terrible.

Even with the five-execution mechanism, the reasons a bad generic plan still gets bound are:

- Generic plans are plans too, and they can inherently be bad
- Statistics are inaccurate, so the generic plan's cost estimate is very low
- The first five executions had low selectivity (or other factors) causing high custom plan costs

### Prepared Statement Invalidation

Besides DDL, `DEALLOCATE`, and disconnecting sessions, collecting statistics can also invalidate prepared statements — but this is a PostgreSQL 14 feature.

PostgreSQL 13:

> PostgreSQL will force re-analysis and re-planning of the statement before using it whenever database objects used in the statement have undergone definitional (DDL) changes since the previous use of the prepared statement

PostgreSQL 14:

> PostgreSQL will force re-analysis and re-planning of the statement before using it whenever database objects used in the statement have undergone definitional (DDL) changes or their planner statistics have been updated since the previous use of the prepared statement

Test confirming that in PostgreSQL 13, collecting statistics does not invalidate prepared statements:

```sql
= explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','11');
                                                  QUERY PLAN                                                   
---------------------------------------------------------------------------------------------------------------
 Index Scan using idx_id on tlzl1  (cost=0.42..5.44 rows=1 width=37) (actual time=0.033..0.033 rows=0 loops=1)
   Index Cond: ((id)::text = $1)
   Filter: (month = $2)
   Rows Removed by Filter: 1
 Planning Time: 0.098 ms
 Execution Time: 0.050 ms
(6 rows)

= select * from pg_prepared_statements;
 name  |                   statement                   |         prepare_time          | parameter_types | from_sql 
-------+-----------------------------------------------+-------------------------------+-----------------+----------
 plan1 | PREPARE plan1(text,integer) AS               +| 2024-02-29 14:27:59.966733+08 | {text,integer}  | t
       | select * from tlzl1 where id=$1 and month=$2; |                               |                 | 
(1 row)

= analyze tlzl1;
ANALYZE
= select * from pg_prepared_statements;
 name  |                   statement                   |         prepare_time          | parameter_types | from_sql 
-------+-----------------------------------------------+-------------------------------+-----------------+----------
 plan1 | PREPARE plan1(text,integer) AS               +| 2024-02-29 14:27:59.966733+08 | {text,integer}  | t
       | select * from tlzl1 where id=$1 and month=$2; |                               |                 | 
(1 row)

=  explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','11');
                                                  QUERY PLAN                                                   
---------------------------------------------------------------------------------------------------------------
 Index Scan using idx_id on tlzl1  (cost=0.42..5.44 rows=1 width=37) (actual time=0.051..0.052 rows=0 loops=1)
   Index Cond: ((id)::text = $1)
   Filter: (month = $2)
   Rows Removed by Filter: 1
 Planning Time: 0.022 ms
 Execution Time: 0.098 ms
(6 rows)
```

### JDBC Prepared Statements

Prepared statements are not unique to PostgreSQL — other databases also have similar pre-parsing features. For example, Oracle can achieve similar functionality.

[JDBC](https://jenkov.com/tutorials/jdbc/preparedstatement.html#:~:text=JDBC%20PreparedStatement%201%20Creating%20a%20PreparedStatement%20Before%20you,Reusing%20a%20PreparedStatement%20...%205%20PreparedStatement%20Performance%20) itself can call the database's pre-parsing interface and directly use prepared statements.

Example JDBC configuration:

```sql
String sql = "select * from people where id=?";

PreparedStatement preparedStatement =
        connection.prepareStatement(sql);
```


## Recommendations

1. Reduce the table-level `autovacuum_analyze_scale_factor` to `0.02` (why 0.02? Because 0.02 < 1/31). Since data is written and queried simultaneously, manual collection timing is hard to get right; reducing `autovacuum_analyze_scale_factor` can only mitigate this problem.
2. Consider removing the PREPARE setting in JDBC, or set `force_custom_plan`.
3. Adjust the SQL logic.
4. Adjust indexes: 4.1 Remove unnecessary time indexes; 4.2 Rebuild the index that gets chosen after predicate out-of-bounds as a composite index that includes the `id` field (a good suggestion).
5. Emergency procedure: If business performance doesn't recover after statistics collection, and you've confirmed the execution plan has changed via manual EXPLAIN, consider killing sessions (for versions before 13).

Finally, predicate out-of-bounds problems exist in essentially all databases, especially on time-based fields. There is currently no simple yet perfectly effective solution. Oracle's SPM (SQL Plan Management) gains another point in my favorability...

