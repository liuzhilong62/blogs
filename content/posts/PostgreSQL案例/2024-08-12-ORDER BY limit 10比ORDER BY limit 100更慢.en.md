---
title: "ORDER BY LIMIT 10 Slower Than ORDER BY LIMIT 100"
date: 2024-08-12
categories: [PostgreSQL案例]
description: "Analyzing the counterintuitive phenomenon where a smaller ORDER BY LIMIT value runs slower, caused by the optimizer underestimating the cost of a backward index scan and choosing the wrong index"
---

## Problem Analysis

When executing SQL in a PostgreSQL database, `ORDER BY LIMIT 10` runs slower than `ORDER BY LIMIT 100`.

### Execution Plan Analysis

```sql
 SELECT
			*,
        (select cl.ITEM_DESC from tablelzl2 cl where item_name='name' and cl.ITEM_NO='abcdefg') AS "item"
        FROM
        tablelzl1 RI
        WHERE  RI.column1='AAAA'
		AND  RI.column2 = 'applyno20231112'
        ORDER BY
        RI.column3 DESC    limit 10
```

```
 Limit  (cost=0.43..1522.66 rows=10 width=990)
   ->  Index Scan Backward using idx_tablelzl1_column3 on tablelzl1 ri  (cost=0.43..158007.45 rows=1038 width=990)
         Filter: (((column1)::text = 'AAAA'::text) AND ((column2)::text = 'applyno20231112'::text))
         SubPlan 1
           ->  Index Scan using uk_tablelzl2_ii on tablelzl2 cl  (cost=0.27..5.29 rows=1 width=18)
                 Index Cond: (((item_no)::text = 'manualSign'::text) AND ((item_name)::text = (ri.manual_sign)::text))
```

The main table does not use the `column2` index. Instead it uses an **Index Scan Backward** on the `column3` sort index. The scan cost for the index is very high, yet the final cost looks low. Actual execution takes 9 seconds.

Changing `LIMIT 10` to `LIMIT 100` yields a normal execution plan:

```sql
 SELECT
			*,
        (select cl.ITEM_DESC from tablelzl2 cl where cl.ITEM_NAME = RI.MANUAL_SIGN AND   cl.ITEM_NO='manualSign') AS "manualSign"
        FROM
        tablelzl1 RI
        WHERE  RI.column1='AAAA'
		AND  RI.column2 = 'applyno20231112'
        ORDER BY
        RI.column3 DESC limit 100 
 ```

 ```
                                                      QUERY PLAN                                                       
-----------------------------------------------------------------------------------------------------------------------
 Limit  (cost=2632.28..3162.78 rows=100 width=990)
   ->  Result  (cost=2632.28..8138.87 rows=1038 width=990)
         ->  Sort  (cost=2632.28..2634.87 rows=1038 width=474)
               Sort Key: ri.column3 DESC
               ->  Index Scan using idx_cri_column2 on tablelzl1 ri  (cost=0.43..2592.61 rows=1038 width=474)
                     Index Cond: ((column2)::text = 'applyno20231112'::text)
                     Filter: ((column1)::text = 'AAAA'::text)
         SubPlan 1
           ->  Index Scan using uk_tablelzl2_ii on tablelzl2 cl  (cost=0.27..5.29 rows=1 width=18)
                 Index Cond: (((item_no)::text = 'manualSign'::text) AND ((item_name)::text = (ri.manual_sign)::text))
(10 rows)
 ```

The subquery plan remains unchanged. The main table now uses the `column2` single-column index, fetches rows, sorts, then applies LIMIT — execution is extremely fast.

This is not just about LIMIT values — changing only the `column2` value in the original SQL can also produce a normal plan. In practice, only a few specific `column2` values trigger the abnormal plan.

**Execution plan comparison:**

*column2* is a filter column, *column3* is a sort column. The two plans choose different indexes:

- **Abnormal `LIMIT 10` plan:** *Backward scan sort-column index → fetch rows → limit*. No extra sort needed; scanning backward, it can stop as soon as it finds enough rows matching the LIMIT. The estimated cost of scanning the sort-column index is very high, but the top-level LIMIT cost estimate is very low.
- **Normal `LIMIT 100` plan:** *Access filter-column index → fetch rows → sort by sort column → limit*. Because sorting is required, all matching index entries must be retrieved. The filter-column index scan itself has a low cost estimate.

So the key issue is: the optimizer **underestimates the cost of a partial backward scan on the sort index**.

### Actual Execution

Let's look at `explain (analyze,buffers)`:

```
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=0.43..1521.93 rows=10 width=990) (actual time=23.311..8122.516 rows=10 loops=1)
   Buffers: shared hit=861100 read=42985 dirtied=7
   I/O Timings: read=6741.003
   ->  Index Scan Backward using idx_tablelzl1_column3 on tablelzl1 ri  (cost=0.43..157932.45 rows=1038 width=990) (actual time=23.309..8122.505 rows=10 loops=1)
         Filter: (((column1)::text = 'AAAA'::text) AND ((column2)::text = 'applyno20231112'::text))
         Rows Removed by Filter: 1521796
         Buffers: shared hit=861100 read=42985 dirtied=7
         I/O Timings: read=6741.003
         SubPlan 1
           ->  Index Scan using uk_tablelzl2_ii on tablelzl2 cl  (cost=0.27..5.29 rows=1 width=18) (actual time=0.005..0.005 rows=0 loops=10)
                 Index Cond: (((item_no)::text = 'manualSign'::text) AND ((item_name)::text = (ri.manual_sign)::text))
                 Buffers: shared hit=6
 Planning:
   Buffers: shared hit=121 read=28
   I/O Timings: read=1.476
 Planning Time: 2.314 ms
 Execution Time: 8122.658 ms
```

```
 Limit  (cost=2632.28..3162.78 rows=100 width=990) (actual time=150.101..150.122 rows=14 loops=1)
   Buffers: shared hit=700 read=274
   I/O Timings: read=146.903
   ->  Result  (cost=2632.28..8138.87 rows=1038 width=990) (actual time=150.100..150.119 rows=14 loops=1)
         Buffers: shared hit=700 read=274
         I/O Timings: read=146.903
         ->  Sort  (cost=2632.28..2634.87 rows=1038 width=474) (actual time=150.072..150.073 rows=14 loops=1)
               Sort Key: ri.column3 DESC
               Sort Method: quicksort  Memory: 30kB
               Buffers: shared hit=694 read=274
               I/O Timings: read=146.903
               ->  Index Scan using idx_cri_column2 on tablelzl1 ri  (cost=0.43..2592.61 rows=1038 width=474) (actual time=0.418..149.973 rows=14 loops=1)
                     Index Cond: ((column2)::text = 'applyno20231112'::text)
                     Filter: ((column1)::text = 'AAAA'::text)
                     Rows Removed by Filter: 1218
                     Buffers: shared hit=691 read=274
                     I/O Timings: read=146.903
         SubPlan 1
           ->  Index Scan using uk_tablelzl2_ii on tablelzl2 cl  (cost=0.27..5.29 rows=1 width=18) (actual time=0.002..0.002 rows=0 loops=14)
                 Index Cond: (((item_no)::text = 'manualSign'::text) AND ((item_name)::text = (ri.manual_sign)::text))
                 Buffers: shared hit=6
 Planning Time: 0.334 ms
 Execution Time: 150.257 ms
```

The `LIMIT 10` plan executes in 8 seconds: shared hit=861,100, disk read=42,985, **1,521,796 rows removed by filter**.

The `LIMIT 100` plan executes in 0.15 seconds: shared hit=694, read=274, 1,218 rows removed.

The `LIMIT 10` plan is clearly abnormal — it **reads far too many rows before finding qualifying ones**, which is why the query is slow.

### Statistics Analysis

The estimated cost is low, but the actual scan touches many index rows. First, check whether the statistics are accurate.

Table statistics:

```
[postgres@cnsz381785:7169/(rasesql)phmamp][10-30.15:01:26]M=#  select relpages,reltuples::bigint from pg_class where relname='tablelzl1';
 relpages | reltuples 
----------+-----------
    91172 |   2280874 -- roughly matches actual count
```

Column statistics:

```
[phmampopr@cnsz381785:7169/(rasesql)phmamp][10-27.17:08:48]M=>  select * from pg_stats where tablename='tablelzl1' and attname='column2';
-[ RECORD 1 ]----------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
schemaname             | public
tablename              | tablelzl1
attname                | column2
inherited              | f
null_frac              | 0
avg_width              | 18
n_distinct             | -0.11990886
most_common_vals       | {applyno20231112,DY20190723006650,DY20200102012899,DY20180827000557,DY20190524001304,DY20190529001885,DY20190728002359}
most_common_freqs      | {0.0005,0.00026666667,0.00023333334,0.0002,0.0002,0.0002,0.0002}
histogram_bounds       | {CULZF0000121605605,DSNEW0000126854232,DSNEW0000137652871,DY20160516001057,DY20161104005509,DY20170306002677,DY20170703010428,DY20170928013517,DY20180410007383,DY20180615002936,DY20180
correlation            | 0.3131596
most_common_elems      | [null]
most_common_elem_freqs | [null]
elem_count_histogram   | [null]
```

The value `applyno20231112` happens to be the top `most_common_vals`, with an estimated frequency of 0.0005. Multiplying: 2,280,874 × 0.0005 = 1,140, which is close to the real count of 1,232.

```
[postgres@cnsz381785:7169/(rasesql)phmamp][10-30.15:05:28]M=# select count(*) from tablelzl1 where column2 = 'applyno20231112';
 count 
-------
  1232
```

Statistics are accurate. Running `ANALYZE` to recollect statistics would not fix this.

## The Effect of Uneven Data Distribution

Using the current statistics, the estimated number of matching rows is ~1,140. On average, finding the first matching row through the sort-column index would require scanning 2,280,874 / 1,140 ≈ 2,000 index entries. For 10 rows, about 20,000 entries; for 100 rows, about 200,000 entries.

Let's disable sort and force the `LIMIT 100` statement to use the sort-column index:

```sql
M=# set enable_sort=off;
SET
```

```
--limit 100 execution plan
 Limit  (cost=0.43..15222.69 rows=100 width=990)
   ->  Index Scan Backward using idx_tablelzl1_column3 on tablelzl1 ri  (cost=0.43..158007.45 rows=1038 width=990)
         Filter: (((column1)::text = 'AAAA'::text) AND ((column2)::text = 'applyno20231112'::text))
         SubPlan 1
           ->  Index Scan using uk_tablelzl2_ii on tablelzl2 cl  (cost=0.27..5.29 rows=1 width=18)
                 Index Cond: (((item_no)::text = 'manualSign'::text) AND ((item_name)::text = (ri.manual_sign)::text))
```

When `LIMIT 10` becomes `LIMIT 100`, the cost jumps from 1522.66 to 15222.69 — roughly a ×10 multiplication. The `LIMIT 100` cost of 15222.69 now exceeds the filter-column index plan's cost of 3162.78, so the optimizer switches indexes.

**The above estimates all assume data is evenly scattered across the sort-column index. In reality, the data could be at the very end (backward scan finds it quickly), or all concentrated in the first few leaf pages (requiring nearly a full index scan + fetch), making the cost extremely high.**

The correlation between the two columns — how the data is distributed across the index — determines whether using the sort-column index is efficient.

Let's look at how many rows were actually scanned:

```
   ->  Index Scan Backward using idx_tablelzl1_column3 on tablelzl1 ri  (cost=0.43..157932.45 rows=1038 width=990) (actual time=23.309..8122.505 rows=10 loops=1)
         Filter: (((column1)::text = 'AAAA'::text) AND ((column2)::text = 'applyno20231112'::text))
         Rows Removed by Filter: 1521796
```

In reality, about **1,521,796 rows** were scanned to find just 10 matching rows. The estimate was 20,000 — a **76× discrepancy**!

## Trigger Conditions

- Must involve `WHERE` + `ORDER BY` + `LIMIT` clauses
- Both the sort column and filter column must have indexes
- The LIMIT value is typically not very large
- Uneven data distribution

## Solution

Rewrite the SQL: add an expression to prevent the `ORDER BY` column from using its index.

```sql
 SELECT
			*,
        (select cl.ITEM_DESC from tablelzl2 cl where cl.ITEM_NAME = RI.MANUAL_SIGN AND   cl.ITEM_NO='manualSign') AS "manualSign"
        FROM
        tablelzl1 RI
        WHERE  RI.column1='AAAA'
		AND  RI.column2 = 'applyno20231112'
        ORDER BY
        RI.column3 +'0' DESC    limit 10
```

## How Oracle Handles This

### Cost Estimation Differences in Execution Plans

From the analysis above, the PostgreSQL execution plan's cost looks unbalanced — the upper-level cost is lower than the inner-level cost, unlike Oracle's hierarchical accumulation.

Let's run an experiment: a table containing only rows where `colname='x'`, comparing how PostgreSQL and Oracle calculate costs:

```
[postgres@cnsz381785:7169/(rasesql)dbmgr][10-31.14:32:19]M=# explain select * from testlzl where col1='x' limit 1;
                              QUERY PLAN                               
-----------------------------------------------------------------------
 Limit  (cost=0.00..0.02 rows=1 width=2)
   ->  Seq Scan on testlzl  (cost=0.00..17747.20 rows=1048576 width=2)
         Filter: ((col1)::text = 'x'::text)
```

```
[postgres@cnsz381785:7169/(rasesql)dbmgr][10-31.14:32:30]M=# explain select * from testlzl where col1='xx' limit 1;
                           QUERY PLAN                            
-----------------------------------------------------------------
 Limit  (cost=0.00..17747.20 rows=1 width=2)
   ->  Seq Scan on testlzl  (cost=0.00..17747.20 rows=1 width=2)
         Filter: ((col1)::text = 'xx'::text)
```

When `col1='x'`, the row is found immediately, but the LIMIT cost is not pushed down into the seq scan cost — the total cost is 17747.20, the same as scanning the whole table. The LIMIT cost is not pushed into the inner node's cost, but the **rows estimate is**.

Now let's see how Oracle handles the same case:

```
SYS@t8icss1> select * from dbmgr.testlzl where a='x' and rownum<=1;

1 row selected.


Execution Plan
----------------------------------------------------------
Plan hash value: 2045386539

------------------------------------------------------------------------------
| Id  | Operation          | Name    | Rows  | Bytes | Cost (%CPU)| Time     |
------------------------------------------------------------------------------
|   0 | SELECT STATEMENT   |         |     1 |     2 |     2   (0)| 00:00:01 |
|*  1 |  COUNT STOPKEY     |         |       |       |            |          |
|*  2 |   TABLE ACCESS FULL| TESTLZL |     1 |     2 |     2   (0)| 00:00:01 |
------------------------------------------------------------------------------

Predicate Information (identified by operation id):
---------------------------------------------------

   1 - filter(ROWNUM<=1)
   2 - filter("A"='x')
```

```
SYS@t8icss1> select * from dbmgr.testlzl where a='xx' and rownum<=1;

no rows selected


Execution Plan
----------------------------------------------------------
Plan hash value: 2045386539

------------------------------------------------------------------------------
| Id  | Operation          | Name    | Rows  | Bytes | Cost (%CPU)| Time     |
------------------------------------------------------------------------------
|   0 | SELECT STATEMENT   |         |     1 |     2 |   302   (2)| 00:00:01 |
|*  1 |  COUNT STOPKEY     |         |       |       |            |          |
|*  2 |   TABLE ACCESS FULL| TESTLZL |     1 |     2 |   302   (2)| 00:00:01 |
------------------------------------------------------------------------------

Predicate Information (identified by operation id):
---------------------------------------------------

   1 - filter(ROWNUM<=1)
   2 - filter("A"='xx')
```

In Oracle, when `a='x'` is found immediately, the STOPKEY cost is pushed into the inner node — cost is only 2. When the data doesn't exist (`a='xx'`), the full scan cost is 302.

This is an important difference between Oracle and PostgreSQL cost calculation:

- In Oracle, the outer node cost is always ≥ the inner node cost; in PostgreSQL, this is not guaranteed.
- Oracle's inner node cost incorporates outer operators (e.g., STOPKEY); PostgreSQL does not — it gives the full cost of the child path.

### Oracle and Uneven Data Distribution

Knowing the principle, we can reproduce the issue by placing data at the beginning of the sort index:

```sql
create table tlzl(a char(100) not null,b char(100) not null);
--Insert bulk data
begin
for i in 1..100000 loop
insert into tlzl values('test','test');
end loop;
end;
/
--Insert special data
insert into tlzl values('aaaa','aaaa');
insert into tlzl values('zzzz','zzzz');

--Create indexes
create index idx_a on tlzl(a);
create index idx_b on tlzl(b);
--Collect statistics
EXEC DBMS_STATS.GATHER_TABLE_STATS(OWNNAME=>'SYS',TABNAME=>'TLZL',estimate_percent => 10, degree=>1,METHOD_OPT=>'FOR ALL COLUMNS SIZE AUTO',cascade=>true);
```

```sql
select * from (select /*+ index(tlzl idx_a)*/* from tlzl where b='aaaa' order by a) where rownum<=1; 
select * from (select /*+ index(tlzl idx_a)*/* from tlzl where b='zzzz' order by a) where rownum<=1; 
```

```
SYS@t8icss1> select * from (select /*+ index(tlzl idx_a)*/* from tlzl where b='aaaa' order by a) where rownum<=1; 

Execution Plan
----------------------------------------------------------
Plan hash value: 3674066029

---------------------------------------------------------------------------------------
| Id  | Operation                     | Name  | Rows  | Bytes | Cost (%CPU)| Time     |
---------------------------------------------------------------------------------------
|   0 | SELECT STATEMENT              |       |     1 |   204 |  2210   (1)| 00:00:01 |
|*  1 |  COUNT STOPKEY                |       |       |       |            |          |
|   2 |   VIEW                        |       |     1 |   204 |  2210   (1)| 00:00:01 |
|*  3 |    TABLE ACCESS BY INDEX ROWID| TLZL  |     1 |   202 |  2210   (1)| 00:00:01 |
|   4 |     INDEX FULL SCAN           | IDX_A | 98830 |       |   779   (1)| 00:00:01 |
---------------------------------------------------------------------------------------
```

```
SYS@t8icss1> select * from (select /*+ index(tlzl idx_a)*/* from tlzl where b='zzzz' order by a) where rownum<=1; 

Execution Plan
----------------------------------------------------------
Plan hash value: 3674066029

---------------------------------------------------------------------------------------
| Id  | Operation                     | Name  | Rows  | Bytes | Cost (%CPU)| Time     |
---------------------------------------------------------------------------------------
|   0 | SELECT STATEMENT              |       |     1 |   204 |  2210   (1)| 00:00:01 |
|*  1 |  COUNT STOPKEY                |       |       |       |            |          |
|   2 |   VIEW                        |       |     1 |   204 |  2210   (1)| 00:00:01 |
|*  3 |    TABLE ACCESS BY INDEX ROWID| TLZL  |     1 |   202 |  2210   (1)| 00:00:01 |
|   4 |     INDEX FULL SCAN           | IDX_A | 98830 |       |   779   (1)| 00:00:01 |
---------------------------------------------------------------------------------------
```

Oracle's optimizer has the same limitation — it doesn't know where the data actually sits within the index. Whether the data is at the first or last position in the index, the estimated cost is the same.

However, Oracle provides more tools to address this: extended statistics, Automatic Column Group Detection, plan baselines, etc.

## References

http://www.postgres.cn/v2/news/viewone/1/717
https://oracle-base.com/articles/12c/automatic-column-group-detection-extended-statistics-12cr1

*Originally published in Chinese on [lastdba.com](https://lastdba.com).*
