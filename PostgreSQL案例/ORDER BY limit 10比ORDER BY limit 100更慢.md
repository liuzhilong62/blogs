# 问题分析
pg数据库中执行sql时，ORDER BY limit 10比ORDER BY limit 100更慢
## 执行计划分析
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
主表没有走到column2索引，而是走column3排序字段索引的Index Scan Backward，scan index的cost非常高，而最终的cost比较低，实际执行需要9s
如果把limit 10改成limit 100，执行计划正常：
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
子查询执行计划不变，主表走到column2单列索引，回表后排序再limit，执行非常快。
不仅是limit，如果原sql仅更换column2的值，执行计划也正常。也就是说这个生产的sql只有极个别的column2的值时执行计划是异常的。

执行计划分析：
子查询前后没变可以不用分析，主要是索引选择上的不同。column2是过滤字段，column3是排序字段，两个执行计划分别选择了这2个字段的索引。
 * 异常的limit 10执行计划：*反向扫描排序字段索引->回表 ->limit*。因为不需要额外排序，反向扫描索引时找到limit个数据就可以不用继续扫描了；扫描排序字段索引的预估代价非常高，最上层的limit最终代价预估很低。
 * 正常的limit 100执行计划：*访问过滤字段索引->回表 ->以排序字段排序 ->limit*。因为要排序，需要把符合条件的所有索引条目全部找出来；本身访问过滤字段的索引代价预估低。

所以问题的关键在于*部分*反向扫描排序索引时，代价预估的过低

## 真实的执行情况
`explain (analyze,buffers) `看下真实的执行情况
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
limit 10的执行计划，执行8s，内存读shared hit=861100 磁盘读read=42985 ，丢弃了1521796行
limit 100的执行计划执行0.1s shared hit=694 read=274，丢弃了1218行
limit 10的执行计划明显是不正常，**读了太多的数据才找到符合条件的行**，这是sql执行过慢的原因

## 统计信息分析
本身预估的代价不高，但是实际上需要扫描非常多的索引行，首先想到是否是统计信息是否准确
表的统计信息：
```
[postgres@cnsz381785:7169/(rasesql)phmamp][10-30.15:01:26]M=#  select relpages,reltuples::bigint from pg_class where relname='tablelzl1';
 relpages | reltuples 
----------+-----------
    91172 |   2280874 --count出来差不多
```
字段的统计信息：
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
这个column2 applyno20231112刚好就是排第一的most_common_vals，出现预估概率是0.0005，用预估的行2280874*0.0005=1140，与实际的行数1232差不多
```
[postgres@cnsz381785:7169/(rasesql)phmamp][10-30.15:05:28]M=# select count(*) from tablelzl1 where column2 = 'applyno20231112';
 count 
-------
  1232
```
说明统计信息是准确的，实际上运行`analze`收集统计信息也不会解决这个问题


# 数据分布不均的计算
用当前统计信息计算出来的符合条件的行有1140个，那么预计从排序字段的索引上找到第一条数据平均要扫描2280874/1140=2000个索引行。如果找10条便是20000个索引行，100条便是200000个索引行。

把sort禁用，让limit 100语句强行走排序字段的索引
```sql
M=# set enable_sort=off;
SET
```
```
--limit 100的执行计划
 Limit  (cost=0.43..15222.69 rows=100 width=990)
   ->  Index Scan Backward using idx_tablelzl1_column3 on tablelzl1 ri  (cost=0.43..158007.45 rows=1038 width=990)
         Filter: (((column1)::text = 'AAAA'::text) AND ((column2)::text = 'applyno20231112'::text))
         SubPlan 1
           ->  Index Scan using uk_tablelzl2_ii on tablelzl2 cl  (cost=0.27..5.29 rows=1 width=18)
                 Index Cond: (((item_no)::text = 'manualSign'::text) AND ((item_name)::text = (ri.manual_sign)::text))
```
limit 10改成limit 100后的执行计划，代价从1522.66升到了15222.69，基本上只是简单的*10。limit 100的代价15222.69大于了走过滤字段索引的执行计划cost 3162.78，所以limit 10和limit 100执行计划不同，选择了不同的索引。

**以上的估算都是以数据零散的放在排序列的索引上 为前提的，实际情况有可能数据在最后一条（反向扫描索引），很快就能找到；也有可能数据全部在索引叶节点前面的几个pages，此时几乎是扫描全部索引并回表，代价便非常高。**
那么两个字段的关联度，数据在索引上的分布情况，决定了使用排序字段的索引 的效率。

再看下真实的执行扫描了多少行数据：
```
   ->  Index Scan Backward using idx_tablelzl1_column3 on tablelzl1 ri  (cost=0.43..157932.45 rows=1038 width=990) (actual time=23.309..8122.505 rows=10 loops=1)
         Filter: (((column1)::text = 'AAAA'::text) AND ((column2)::text = 'applyno20231112'::text))
         Rows Removed by Filter: 1521796
```
实际上差不多扫描了1521796行才找到这10条数据，本来预估的是20000，整整相差了76倍！



# 触发场景
 - 必须有where +order by+limit语句
 - 排序字段和过滤字段都必须有索引
 - 一般limit不会特别大
 - 数据分布不均
# 解决办法
改写sql语句：添加表达式，不让order by字段走索引即可
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

# oracle是怎么做的

## 执行计划cost的预估差异
从上面的执行计划分析，pg的执行计划cost看起来不太适应，上层的cost小于内层的cost，不像oracle这样阶梯式的累加计算
这里做一个oracle和pg的实验，一张表仅存储colname='x'的数据，看下pg和oracle的对cost计算的区别：
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
col1='x'立马就能找到，limit的算法没有推入到全表扫描的成本中，total cost是17747.20，跟扫描完表的成本是一样的。limit的成本cost虽然没有下推到内层的cost做计算，但是rows计算了！

来看下oracle是执行计划是怎么做的：
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
对于oracle的计划，a='x'的数据可以立即找到的话，STOPKEY的代价算进了内层的cost中，cost只有2，实际上扫描全表的代价比较高302。

这一点是oracle与pg关于cost计算的一个重要区别：
 - oracle的外层cost必然>=内层cost；pg则不一定
 - oracle的内层cost计算包含了外层的算子（比如stopkey）；但是pg不会包含，直接给子路径的全部成本

## oracle的数据分布不均问题
知道了数据分布不均的原理，造一条数据把他放在排序索引的开头即可
```sql
create table tlzl(a char(100) not null,b char(100) not null);
--插入批量数据
begin
for i in 1..100000 loop
insert into tlzl values('test','test');
end loop;
end;
/
--插入特殊数据
insert into tlzl values('aaaa','aaaa');
insert into tlzl values('zzzz','zzzz');
--创建索引
create index idx_a on tlzl(a);
create index idx_b on tlzl(b);
--收集统计信息
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
oracle的优化器也是一样的，优化器并不知道数据到底放在索引的哪个地方，没有办法，放在索引的第一条和最后一条都是估算的同一代价。
不过oracle有很多方法可以解决这个问题，如extended statistic、Automatic Column Group Detection、固化执行计划等。


# 参考
http://www.postgres.cn/v2/news/viewone/1/717
https://oracle-base.com/articles/12c/automatic-column-group-detection-extended-statistics-12cr1
