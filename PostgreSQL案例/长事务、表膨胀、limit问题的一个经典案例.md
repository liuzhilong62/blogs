

  # update主键慢，问题分析
  
  一个简单的主键更新，update执行了超过1s，由于并发比较高，cpu直接打满
  ```sql
  2024-04-01 10:19:36.084 CST,"lzlopr","lzl",158751,"10.33.78.149:51502",66055a6b.26c1f,172,"UPDATE",2024-03-28 19:54:19 CST,528/19816630,970251337,LOG,00000,"duration: 1218.688 ms  plan:
Query Text:             update table_a                 set (省略...）=$6           where column_id =$7
Update on table_a  (cost=0.40..5.49 rows=1 width=2774)
  ->  Index Scan using pk_id on table_a  (cost=0.40..5.49 rows=1 width=2774)
        Index Cond: ((column_id)::text = $7)",,,,,,,,,"PostgreSQL JDBC Driver","client backend"
```
sql本身也非常简单，就是条件为='主键'的更新。看update的执行计划，是走了pk主键索引的，所以从执行计划上看没有问题，问题不在执行计划突变。


改写下sql（因为是update），`explain (analyze,buffers)`对比看下SQL的执行消耗
```sql
=> explain (analyze,buffers) select * from table_a where column_id='d4f713370e584820a9b15e2218ea436a';
                                                           QUERY PLAN                                                            
---------------------------------------------------------------------------------------------------------------------------------
 Bitmap Heap Scan on table_a  (cost=2.91..5.42 rows=1 width=1156) (actual time=55.052..123.354 rows=1 loops=1)
   Recheck Cond: ((column_id)::text = 'd4f713370e584820a9b15e2218ea436a'::text)
   Heap Blocks: exact=1
   Buffers: shared hit=13870
   ->  Bitmap Index Scan on pk_id  (cost=0.00..2.91 rows=1 width=0) (actual time=3.464..3.465 rows=13866 loops=1)
         Index Cond: ((column_id)::text = 'd4f713370e584820a9b15e2218ea436a'::text)
         Buffers: shared hit=24
 Planning:
   Buffers: shared hit=4261
 Planning Time: 11.028 ms
 Execution Time: 123.567 ms
(11 rows)
```
这里的真实执行计划没问题，但是shared hit=13870明显太高了。正常来说走主键不应该扫描太多的page，这里比较容易联想到表膨胀

查看表膨胀：
```sql
--表大小 \dt
Size        | 525 MB
```
```sql
--表的实际行数
count | 827
```
```sql
--死元组 pg_stat_all_tables
n_live_tup          | 786
n_dead_tup          | 657604
```
有只有800条活元组，但是有65w条死元组！主键扫描了多个page的原因应该就是这个，但是为啥没有回收死元组呢？
表在默认修改20%数据的时候就会触发autovacuum执行vacuum回收，这个在日志中可以看到，autovacuum是有被触发的：
```shell
2024-04-01 14:13:46.649 CST,,,14081,,660a5099.3701,1,,2024-04-01 14:13:45 CST,259/17828993,0,LOG,00000,"automatic vacuum of table ""lzl.public.table_a"": index scans: 0
2024-04-01 14:13:47.801 CST,,,14081,,660a5099.3701,2,,2024-04-01 14:13:45 CST,259/17828994,971045014,LOG,00000,"automatic analyze of table ""lzl.public.table_a"" system usage: CPU: user: 0.08 s, system: 0.01 s, elapsed: 1.15 s",,,,,,,,,"","autovacuum worker"
2024-04-01 14:14:46.673 CST,,,26136,,660a50d5.6618,1,,2024-04-01 14:14:45 CST,259/17829090,0,LOG,00000,"automatic vacuum of table ""lzl.public.table_a"": index scans: 0
2024-04-01 14:14:47.833 CST,,,26136,,660a50d5.6618,2,,2024-04-01 14:14:45 CST,259/17829091,971049759,LOG,00000,"automatic analyze of table ""lzl.public.table_a"" system usage: CPU: user: 0.08 s, system: 0.03 s, elapsed: 1.15 s",,,,,,,,,"","autovacuum worker"
2024-04-01 14:15:46.680 CST,,,40743,,660a5111.9f27,1,,2024-04-01 14:15:45 CST,259/17829164,0,LOG,00000,"automatic vacuum of table ""lzl.public.table_a"": index scans: 0
2024-04-01 14:15:47.849 CST,,,40743,,660a5111.9f27,2,,2024-04-01 14:15:45 CST,259/17829165,971055464,LOG,00000,"automatic analyze of table ""lzl.public.table_a"" system usage: CPU: user: 0.08 s, system: 0.03 s, elapsed: 1.16 s",,,,,,,,,"","autovacuum worker"
2024-04-01 14:16:46.677 CST,,,52599,,660a514d.cd77,1,,2024-04-01 14:16:45 CST,259/17829263,0,LOG,00000,"automatic vacuum of table ""lzl.public.table_a"": index scans: 0
2024-04-01 14:16:47.844 CST,,,52599,,660a514d.cd77,2,,2024-04-01 14:16:45 CST,259/17829264,971061382,LOG,00000,"automatic analyze of table ""lzl.public.table_a"" system usage: CPU: user: 0.08 s, system: 0.03 s, elapsed: 1.16 s",,,,,,,,,"","autovacuum worker"
2024-04-01 14:17:46.699 CST,,,64858,,660a5189.fd5a,1,,2024-04-01 14:17:45 CST,234/16589539,0,LOG,00000,"automatic vacuum of table ""lzl.public.table_a"": index scans: 0
2024-04-01 14:17:47.851 CST,,,64858,,660a5189.fd5a,2,,2024-04-01 14:17:45 CST,234/16589540,971066091,LOG,00000,"automatic analyze of table ""lzl.public.table_a"" system usage: CPU: user: 0.09 s, system: 0.02 s, elapsed: 1.15 s",,,,,,,,,"","autovacuum worker"
2024-04-01 14:18:46.703 CST,,,78112,,660a51c5.13120,1,,2024-04-01 14:18:45 CST,259/17829409,0,LOG,00000,"automatic vacuum of table ""lzl.public.table_a"": index scans: 0
2024-04-01 14:18:47.854 CST,,,78112,,660a51c5.13120,2,,2024-04-01 14:18:45 CST,259/17829410,971070390,LOG,00000,"automatic analyze of table ""lzl.public.table_a"" system usage: CPU: user: 0.09 s, system: 0.02 s, elapsed: 1.15 s",,,,,,,,,"","autovacuum worker"		
```
不仅有触发，而且间隔刚好是一分钟。autovacuum_naptime间隔触发时间默认就是1分钟
```sql
>= show autovacuum_naptime ;
 autovacuum_naptime 
--------------------
 1min
(1 row)
```
可以判断：
 - autovacuum成功触发
 - 死元组可能回收不及，1分钟内产生的死元组大于20%（可能1分钟太长了）；或者根本没有回收，下次一定触发autovacuum

看下autovacuum的具体内容：
```shell
2024-04-01 10:22:44.648 CST,,,16827,,660a1a73.41bb,1,,2024-04-01 10:22:43 CST,170/16910186,0,LOG,00000,"automatic vacuum of table ""lzl.public.table_a"": index scans: 0
pages: 0 removed, 48745 remain, 6 skipped due to pins, 0 skipped frozen
tuples: 0 removed, 744488 remain, 743666 are dead but not yet removable, oldest xmin: 969118077
buffer usage: 97603 hits, 0 misses, 5 dirtied
avg read rate: 0.000 MB/s, avg write rate: 0.028 MB/s
system usage: CPU: user: 0.21 s, system: 0.22 s, elapsed: 1.41 s
WAL usage: 4 records, 3 full page images, 5129 bytes",,,,,,,,,"","autovacuum worker"
```
autovacuum触发了，但是完全没有回收死元组`tuples: 0 removed, 744488 remain, 743666 are dead but not yet removable, oldest xmin: 969118077`。`oldest xmin`代表库内的最旧事务，也就是有长事务，这个很好找到：
```sql
>=  select pid,usename,xact_start,state_change,wait_event,state,query from  pg_stat_activity where state<>'idle' order by xact_start ;
  pid   |  usename   |          xact_start           |         state_change          |     wait_event      |        state        |                                                                              
--------+------------+-------------------------------+-------------------------------+---------------------+---------------------+------------------------------------------------------------------------------
 164658 | phbdspsqp  | 2024-04-01 08:36:57.275408+08 | 2024-04-01 08:36:57.299609+08 | DataFileRead        | active              | SELECT "minval","maxval" FROM (select min(ID) as minval,max(TRACK
```
长事务就是这个早上8点多跑了几个小时sql。虽然不是一个表，但是因为是`oldest xmin`所以也会有影响。
至此原因已经定位：
 - 表A的update频繁，表膨胀风险较高
 - 表B长事务阻止表A死元组回收
 - 表A的update语句扫描了过多的page

解决办法：
 - 结束长事务。`select pg_terminate_backend(164658)`
 - 手动vacuum或者等待1分钟（以内）自动vacuum。 `vacuum table_a`

上面2个操作完成后，查看死元组
```sql
n_live_tup          | 707
n_dead_tup          | 298
```
65w的死元组已清理。
再次查看执行计划：

```sql
=>  explain (analyze,buffers) select * from table_a where column_id='d4f713370e584820a9b15e2218ea436a';
                                                                   QUERY PLAN                                                                    
-------------------------------------------------------------------------------------------------------------------------------------------------
 Index Scan using pk_id on table_a  (cost=0.40..5.44 rows=1 width=621) (actual time=0.026..0.029 rows=1 loops=1)
   Index Cond: ((column_id)::text = 'd4f713370e584820a9b15e2218ea436a'::text)
   Buffers: shared hit=6
 Planning Time: 0.057 ms
 Execution Time: 0.043 ms
```
shared hit只有6，故障恢复。

另外，vacuum只会回收死元组，但是不会清理空间，表还是那么大。这个只有等新数据复用空间或者repack等重建表的操作来回收
```sql
Size        | 525 MB
```

 
 # order by limit的番外sql优化：
刚才那个长事务sql，也有问题···
业务反馈前几天都快，今天跑了几个小时了
 ```sql
 explain select min(ID) as minval,max(ID) as maxval from table_b where time_at >= to_timestamp('2024-03-30 00:00:00','yyyy-MM-dd HH24:mi:ss');
                                                                             QUERY PLAN                                                                             
--------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Result  (cost=4298.54..4298.55 rows=1 width=64)
   InitPlan 1 (returns $0)
     ->  Limit  (cost=0.70..2149.27 rows=1 width=32)
           ->  Index Scan using pk_b on table_b  (cost=0.70..1181490202.27 rows=549896 width=32)
                 Index Cond: ((ID)::text IS NOT NULL)
                 Filter: (time_at >= to_timestamp('2024-03-30 00:00:00'::text, 'yyyy-MM-dd HH24:mi:ss'::text))
   InitPlan 2 (returns $1)
     ->  Limit  (cost=0.70..2149.27 rows=1 width=32)
           ->  Index Scan Backward using pk_b on table_b table_b_1  (cost=0.70..1181490202.27 rows=549896 width=32)
                 Index Cond: ((ID)::text IS NOT NULL)
                 Filter: (time_at >= to_timestamp('2024-03-30 00:00:00'::text, 'yyyy-MM-dd HH24:mi:ss'::text))
 ```
 sql也很简单，条件只有一个时间字段 ，过滤性还可以
 不过这个sql没有走 time_at 索引，而是走的 ID主键索引  。这个跟[limit问题](https://blog.csdn.net/qq_40687433/article/details/134387782?spm=1001.2014.3001.5501)是一样的。analyze是没有用的，最好是改写sql。
 改写后SQL结果秒出：
 ```sql
 explain select min(ID||'') as minval,max(ID||'') as maxval from table_b where time_at >= to_timestamp('2024-03-30 00:00:00','yyyy-MM-dd HH24:mi:ss')

                                                         QUERY PLAN                                                         
----------------------------------------------------------------------------------------------------------------------------
 Aggregate  (cost=1201418.86..1201418.87 rows=1 width=64)
   ->  Index Scan using idx_time_at on table_b  (cost=0.57..1195919.90 rows=549896 width=33)
         Index Cond: (time_at >= to_timestamp('2024-03-30 00:00:00'::text, 'yyyy-MM-dd HH24:mi:ss'::text))
```
这个还不是执行计划突变，因为没有变。前几天同样是这样的执行计划，但是跑的比较快，原因是还是因为数据分布和limit的机制，数据很快就找到自然就返回了，这也是优化器为什么会选择主键索引；“运气不好”数据半天找不到就要跑很久。

# 小结
一个经典的案例：
 - update频繁更新的小表
 - 长事务阻止死元组回收
 - 长事务是排序和limt操作（order by，max/min，group都有可能）导致的索引选择问题

一个故障，三个postgres的经典知识点，相当有代表性。
