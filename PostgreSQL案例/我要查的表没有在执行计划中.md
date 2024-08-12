# 问题：查的表没有在执行计划中
sql：
```sql
SELECT
  *
FROM
  (
    SELECT
      A.column1 as "column1",
      --中间省略很多A字段
      A.column99 as "column99"
    from
      table_a A
      left join (
        SELECT
          lzl_id
        from
          table_a AA
          inner join table_b BB ON AA.lzl_key = BB.lzl_id
        where
          AA.column_code = '1'
        GROUP BY
          lzl_id
      ) B ON B.lzl_id = A.lzl_key
    where
      A.flagflagflag = '1'
      AND A.typetypetype = '2'
  ) TEMP
limit
  100
offset
  1000
```

执行计划：
```sql
                                                            QUERY PLAN                                                            
----------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=2.84..5.68 rows=1 width=1105) (actual time=0.038..0.039 rows=0 loops=1)
   Buffers: shared hit=2
   ->  Seq Scan on table_a a  (cost=0.00..2.84 rows=1 width=1105) (actual time=0.036..0.037 rows=0 loops=1)
         Filter: (((flagflagflag)::text = '1'::text) AND ((typetypetype)::text = '2'::text))
         Rows Removed by Filter: 38
         Buffers: shared hit=2
 Planning Time: 0.184 ms
 Execution Time: 0.066 ms
```
可以看到，sql本身是比较复杂的，SQL的逻辑查了3次表，总共查了2张表。table_a 在执行计划中我可以理解，但是需要查的table_b根本没在执行计划里面！这个执行计划只不过是简单的全表扫描了table_a。

# 分析的心路历程
中间其实想过很多可能，不过最有可能的是逻辑优化了，也就是说pg优化器认为table_b不需要查。
观察sql发现sql最终只查询了table_a的字段，没有查table_b。此时任意增加一个中间表B的字段，sql执行计划看上去就“正常”了，访问了table_b
```sql
explain SELECT
  *
FROM
  (
    SELECT
      A.column1 as "column1",
      --中间省略很多A字段
      A.column99 as "column99",
      B.lzl_id --新增一个B中间表的字段
    from
      table_a A
      left join (
        SELECT
          lzl_id
        from
          table_a AA
          inner join table_b BB ON AA.lzl_key = BB.lzl_id
        where
          AA.column_code = '1'
        GROUP BY
          lzl_id
      ) B ON B.lzl_id = A.lzl_key
    where
      A.flagflagflag = '1'
      AND A.typetypetype = '2'
  ) TEMP
limit
  100
offset
  1000
 ```
```sql                                                                          QUERY PLAN                                                                           
---------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=14.69..17.67 rows=1 width=1113)
   ->  Nested Loop Left Join  (cost=11.72..14.69 rows=1 width=1113)
         Join Filter: (bb.lzl_id = a.lzl_key)
         ->  Seq Scan on table_a a  (cost=0.00..2.84 rows=1 width=1113)
               Filter: (((flagflagflag)::text = '1'::text) AND ((typetypetype)::text = '2'::text))
         ->  Group  (cost=11.72..11.74 rows=5 width=8)
               Group Key: bb.lzl_id
               ->  Sort  (cost=11.72..11.73 rows=5 width=8)
                     Sort Key: bb.lzl_id
                     ->  Nested Loop  (cost=0.15..11.66 rows=5 width=8)
                           ->  Seq Scan on table_a aa  (cost=0.00..2.70 rows=1 width=8)
                                 Filter: ((company_code)::text = '1'::text)
                           ->  Index Only Scan using idx_table_b_lzl_id on table_b bb  (cost=0.15..8.83 rows=13 width=8)
                                 Index Cond: (lzl_id = aa.lzl_key)
```
这看上去跟left join有关系，但是简单想想又不对，因为右表的结果是会影响查询的最终结果的，不应该不去查右表。随便来个简单的left join，右表会被扫描
```sql
explain select lzlleft.a from lzlleft left join lzlright on lzlleft.a=lzlright.a;
                             QUERY PLAN                             
--------------------------------------------------------------------
 Hash Left Join  (cost=1.04..15.47 rows=320 width=4)
   Hash Cond: (lzlleft.a = lzlright.a)
   ->  Seq Scan on lzlleft  (cost=0.00..13.20 rows=320 width=4)
   ->  Hash  (cost=1.02..1.02 rows=2 width=4)
         ->  Seq Scan on lzlright  (cost=0.00..1.02 rows=2 width=4)
```
但是，在中间表B中，有个关键字`GROUP BY`。如果把`GROUP BY`去掉，那么无论有没有查询B的字段，都会访问table_b。
我们再在测试表中加个group by看看结果
```sql
> select * from lzlleft;
 a |  b  
---+-----
 1 | zzz
(1 row)

Time: 0.259 ms
> select * from lzlright;
 a |   b   
---+-------
 1 | qwer
 1 | poiuy 
 
> select lzlright.b from lzlleft full join  lzlright on lzlleft.b=lzlright.b group by lzlright.b;
   b    
--------
 [null]
 poiuy
 qwer
(3 rows)
```
这里就意识到了group by出来的结果集一定有一个特性——**唯一性**。
我们再在测表里加group by

 ```sql
 explain select lzlleft.a from lzlleft left join  (select  a from  lzlright group by a) c on lzlleft.a=c.a;
                        QUERY PLAN                        
----------------------------------------------------------
 Seq Scan on lzlleft  (cost=0.00..13.20 rows=320 width=4)
 ```
 右表不查了！
 根据右表唯一性的原则，下面还可以有一些骚操作：
 ```sql
 --distinct确保右表唯一
> explain select lzlleft.a from lzlleft left join  (select distinct a from  lzlright) c on lzlleft.a=c.a;
                        QUERY PLAN                        
----------------------------------------------------------
 Seq Scan on lzlleft  (cost=0.00..13.20 rows=320 width=4) 
 ```
 
 ```
 --唯一索引确保右表唯一，哪怕是select  a from  lzlright
>  explain select lzlleft.a from lzlleft left join  (select  a from  lzlright) c on lzlleft.a=c.a;
                              QUERY PLAN                               
-----------------------------------------------------------------------
 Hash Left Join  (cost=17.20..49.12 rows=512 width=4)
   Hash Cond: (lzlleft.a = lzlright.a)
   ->  Seq Scan on lzlleft  (cost=0.00..13.20 rows=320 width=4)
   ->  Hash  (cost=13.20..13.20 rows=320 width=4)
         ->  Seq Scan on lzlright  (cost=0.00..13.20 rows=320 width=4)
(5 rows)

Time: 0.510 ms
> create unique index idx_right on lzlright(a);
CREATE INDEX
Time: 3.576 ms
> explain select lzlleft.a from lzlleft left join  (select  a from  lzlright) c on lzlleft.a=c.a;
                        QUERY PLAN                        
----------------------------------------------------------
 Seq Scan on lzlleft  (cost=0.00..13.20 rows=320 width=4)
(1 row)
 ```
到这里来个分析小结：只要右表的数据是唯一的且只查询左表数据时，不需要真的去访问右表 。所以这不是一个bug，而是PG优化器的特性，是符合逻辑的。
# 源码分析
本期没有源码分析~
优化器源码实在太难了，这里就找了下优化器源码的注释看了下。可以搜索关键字`unique-ify`，有这么一句话：
```c
 * Also, this routine and others in this module accept the special JoinTypes
 * JOIN_UNIQUE_OUTER and JOIN_UNIQUE_INNER to indicate that we should
 * unique-ify the outer or inner relation and then apply a regular inner
 * join.  These values are not allowed to propagate outside this module,
 * however.  Path cost estimation code may need to recognize that it's
 * dealing with such a case --- the combination of nominal jointype INNER
 * with sjinfo->jointype == JOIN_SEMI indicates that. 
```
特殊的JoinTypes：JOIN_UNIQUE_INNER 和JOIN_UNIQUE_OUTER ，尝试把外表和内表连接唯一化后，成为inner join。Path代价估算需要考虑这种场景。


# 与oracle、mysql优化器的对比
对比看下oracle、mysql优化器有没有类似的逻辑优化提升

```sql
--oracle
create table lzlleft(a number);
create table lzlright(a number);
 select lzlleft.a from lzlleft left join  (select  distinct a from  lzlright) c on lzlleft.a=c.a;
```
```sql
--group by 唯一性
SQL>  select lzlleft.a from lzlleft left join  (select  a from  lzlright group by a) c on lzlleft.a=c.a; 

no rows selected


Execution Plan
----------------------------------------------------------
Plan hash value: 3533354041

---------------------------------------------------------------------------------
| Id  | Operation            | Name     | Rows  | Bytes | Cost (%CPU)| Time     |
---------------------------------------------------------------------------------
|   0 | SELECT STATEMENT     |          |     1 |    26 |     5  (20)| 00:00:01 |
|*  1 |  HASH JOIN OUTER     |          |     1 |    26 |     5  (20)| 00:00:01 |
|   2 |   TABLE ACCESS FULL  | LZLLEFT  |     1 |    13 |     2   (0)| 00:00:01 |
|   3 |   VIEW               |          |     1 |    13 |     3  (34)| 00:00:01 |
|   4 |    HASH GROUP BY     |          |     1 |    13 |     3  (34)| 00:00:01 |
|   5 |     TABLE ACCESS FULL| LZLRIGHT |     1 |    13 |     2   (0)| 00:00:01 |
---------------------------------------------------------------------------------

Predicate Information (identified by operation id):
---------------------------------------------------

   1 - access("LZLLEFT"."A"="C"."A"(+))
```
```sql
--ditinct 唯一 
SQL>  select lzlleft.a from lzlleft left join  (select  distinct a from  lzlright) c on lzlleft.a=c.a;

no rows selected


Execution Plan
----------------------------------------------------------
Plan hash value: 3859658234

---------------------------------------------------------------------------------
| Id  | Operation            | Name     | Rows  | Bytes | Cost (%CPU)| Time     |
---------------------------------------------------------------------------------
|   0 | SELECT STATEMENT     |          |     1 |    26 |     5  (20)| 00:00:01 |
|*  1 |  HASH JOIN OUTER     |          |     1 |    26 |     5  (20)| 00:00:01 |
|   2 |   TABLE ACCESS FULL  | LZLLEFT  |     1 |    13 |     2   (0)| 00:00:01 |
|   3 |   VIEW               |          |     1 |    13 |     3  (34)| 00:00:01 |
|   4 |    HASH UNIQUE       |          |     1 |    13 |     3  (34)| 00:00:01 |
|   5 |     TABLE ACCESS FULL| LZLRIGHT |     1 |    13 |     2   (0)| 00:00:01 |
---------------------------------------------------------------------------------

Predicate Information (identified by operation id):
---------------------------------------------------

   1 - access("LZLLEFT"."A"="C"."A"(+))
```
```sql 
--mysql 
create table lzlleft(a int primary key);
create table lzlright(a int primary key);
```
```sql
--group by唯一
explain select lzlleft.a from lzlleft left join  (select  a from  lzlright group by a) c on lzlleft.a=c.a; 
+----+-------------+------------+------------+-------+---------------+-------------+---------+-----------------+------+----------+-------------+
| id | select_type | table      | partitions | type  | possible_keys | key         | key_len | ref             | rows | filtered | Extra       |
+----+-------------+------------+------------+-------+---------------+-------------+---------+-----------------+------+----------+-------------+
|  1 | PRIMARY     | lzlleft    | NULL       | index | NULL          | PRIMARY     | 4       | NULL            |    1 |   100.00 | Using index |
|  1 | PRIMARY     | <derived2> | NULL       | ref   | <auto_key0>   | <auto_key0> | 4       | lzldb.lzlleft.a |    2 |   100.00 | Using index |
|  2 | DERIVED     | lzlright   | NULL       | index | PRIMARY       | PRIMARY     | 4       | NULL            |    1 |   100.00 | Using index |
+----+-------------+------------+------------+-------+---------------+-------------+---------+-----------------+------+----------+-------------+
```
```sql
--distinct唯一
explain select lzlleft.a from lzlleft left join  (select  distinct a from  lzlright) c on lzlleft.a=c.a;
+----+-------------+------------+------------+-------+---------------+-------------+---------+-----------------+------+----------+-------------+
| id | select_type | table      | partitions | type  | possible_keys | key         | key_len | ref             | rows | filtered | Extra       |
+----+-------------+------------+------------+-------+---------------+-------------+---------+-----------------+------+----------+-------------+
|  1 | PRIMARY     | lzlleft    | NULL       | index | NULL          | PRIMARY     | 4       | NULL            |    1 |   100.00 | Using index |
|  1 | PRIMARY     | <derived2> | NULL       | ref   | <auto_key0>   | <auto_key0> | 4       | lzldb.lzlleft.a |    2 |   100.00 | Using index |
|  2 | DERIVED     | lzlright   | NULL       | index | PRIMARY       | PRIMARY     | 4       | NULL            |    1 |   100.00 | Using index |
+----+-------------+------------+------------+-------+---------------+-------------+---------+-----------------+------+----------+-------------+
```
综上，oracle、mysql均不会对left join只查左表且右表唯一做优化，他们会访问右表。
pg优化器确实是有些东西的。

 
 
 
 
 
  
