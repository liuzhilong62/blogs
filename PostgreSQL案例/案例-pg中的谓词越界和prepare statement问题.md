# 现象
案例：执行计划发生变化，plan选择了错误的索引，sql由毫秒级变成秒级。后面收集统计信息后，业务sql还是慢，最后通过删除DAILY_DATE时间索引建立(DAILY_DATE,A_ID)组合索引才解决。
疑问：
1. 优化器为什么选择DAILY_DATE索引，而不是选择率更好的A_ID索引？
2. 收集统计信息后为什么没有效果？

# 统计信息过旧
```sql
--简化后的sql
select
         *
        from tablzl
        where A_ID = $1
        AND IS_DELETE = 'N'
        AND DAILY_DATE = to_date($2, 'yyyyMMdd')
              and PARTITION_KEY >= $3  
              and PARTITION_KEY <= $4
```
优化器选择DAILY_DATE索引而不是过滤性比较好的A_ID
```sql
Append  (cost=0.44..8.83 rows=2 width=204)
  ->  Index Scan using tablzl_p202401_DAILY_DATE_idx on tablzl_p202401 tablzl_1  (cost=0.44..5.47 rows=1 width=203)
        Index Cond: (DAILY_DATE = to_date('20240223'::text, 'yyyyMMdd'::text))
        Filter: ((partition_key >= 202401) AND (partition_key <= 202402) AND ((A_ID)::text = 'ID1234567890987654321'::text) AND ((is_delete)::text = 'N'::text))
  ->  Index Scan using tablzl_p202402_DAILY_DATE_idx on tablzl_p202402 tablzl_2  (cost=0.44..3.35 rows=1 width=204)
        Index Cond: (DAILY_DATE = to_date('20240223'::text, 'yyyyMMdd'::text))
        Filter: ((partition_key >= 202401) AND (partition_key <= 202402) AND ((A_ID)::text = 'ID1234567890987654321'::text) AND ((is_delete)::text = 'N'::text))
```
 - 对于p202401分区，走DAILY_DATE还是A_ID索引，差别不大，因为1月分区没有2月23日的数据
 - 对于p202402分区，走DAILY_DATE还是A_ID索引，差别很大。走DAILY_DATE索引，它的预估cost=3.35，rows=1，实际上有上百万的数据，跑了2秒

p202402的统计信息中有MCV：
```sql
=  select * from pg_stats where tablename='tablzl_p202402' and attname='DAILY_DATE' \gx
most_common_vals       | {2024-02-21,2024-02-20,2024-02-22,2024-02-10,2024-02-15,2024-02-19,2024-02-16,2024-02-18,2024-02-17,2024-02-14,2024-02-11,2024-02-07,2024-02-12,2024-02-06,2024-02-08,2024-.
                       |.02-09,2024-02-03,2024-02-05,2024-02-01,2024-02-02,2024-01-31,2024-02-13,2024-02-04}
most_common_freqs      | {0.0481,0.047766667,0.0466,0.0449,0.0441,0.043833334,0.043733332,0.043466665,0.043133333,0.043066666,0.042366665,0.041866668,0.041366667,0.041366667,0.039766666,0.0394,0.039333332,0..
                       |.038766667,0.03863333,0.0381,0.038066667,0.037966665,0.037566666,0.036733333}
```
计算MCV的总频率sum(most_common_freqs)
```sql
= select 0.0481+0.047766667+0.0466+0.0449+0.0441+0.043833334+0.043733332+0.043466665+0.043133333+0.043066666+0.042366665+0.041866668+0.041366667+0.041366667+0.039766666+0.0394+0.039333332+0.038766667+0.03863333+0.0381+0.038066667+0.037966665+0.037566666+0.036733333;
  ?column?   
-------------
 0.999999990
```
刚好是1，代表1-22日就是这个分区的所有数据（预估），23日的数据应该是0条，所以planner在预估23日的数据时rows=1，所以选择了DAILY_DATE索引。实际上23日的数据有百万条。
本质上这是一个统计信息过久造成的问题。为什么前22天没有问题而且23日没有触发自动收集呢？
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
触发阈值默认是0.1，数据变化达到1/10的时候才会触发自动analyze。这是一个月分区，数据是每天插入和更新的，月初时1天写入200w数据，因为数据存量少，会触发多次analyze（threshold默认50可以忽略不记），而在月末时，比如23日，1天写入200w数据，不会触发analyze，因为只写了1/23。这个场景中插入后还会更新，插入200w更新200w，所以23日的数据变化是1/11左右，刚好不会触发analyze，**这也能解释前20天运行稳定**。
另外，因为数据量的变化阈值是一个比例，每天的数据量的变化只要是比较均匀的，都会有这个月末统计信息不准的问题！

# 执行计划缓存
因为是统计信息过旧问题，手动收集统计信息理应解决这个问题，实际上收集了以后业务sql还是慢。
analyze了以后，手动explain analyze 执行计划却是正确的。
说明analyze应该是有用的，但是没有影响到业务会话。由于sql执行用的是长会话，怀疑jdbc中使用prepare statement缓存执行计划（[jdbc prepare statement](https://jenkov.com/tutorials/jdbc/preparedstatement.html#:~:text=JDBC%20PreparedStatement%201%20Creating%20a%20PreparedStatement%20Before%20you,Reusing%20a%20PreparedStatement%20...%205%20PreparedStatement%20Performance%20)）。
而prepare statement在pg13（rasesql 1.3）中，收集统计信息不会失效，只能通过重连会话的方式重写解析。
prepare statement会生产一个通用执行计划（generic plan），由于统计信息不准确，通用执行计划跟传参执行计划一样，可以选择错误的索引





# prepare statement的特性
psql支持prepare statement，由`plan_cache_mode`参数控制
 - `auto`：默认，五次机制处理
 - `force_custom_plan`：永远进行硬解析，生成custom plan
 - `force_generic_plan`：永远使用generic plan，绑定变量

使用语法：
```sql
PREPARE plan1(text,integer) AS select * from tlzl1 where id=$1 and month=$2;
EXECUTE plan1('256ac66bb53d31bc6124294238d6410c','11');

deallocate plan1|all;  --使prepare失效，断开会话也可以
```

视图：（基本没用，因为是本地的，生产可看不到东西）
```sql
select * from pg_prepared_statements;
```

## generic plan是怎么生成的
正常来说prepare语句跑5次是可以生成generic plan的。网上很多演示，这里就不演示正常情况了，以下是我测试出的“神奇”现象
```sql
--准备数据
create table tlzl1(id varchar(50),month int);
INSERT INTO tlzl1 SELECT md5(g::text),EXTRACT(month FROM g)
FROM generate_series('2023-01-01'::date, '2023-11-30'::date, '1 minute') as g;
create index idx_id on tlzl1(id);
create index idx_month on tlzl1(month);
analyze tlzl;

--执行prepare语句
PREPARE plan1(text,integer) AS        
select * from tlzl1 where id=$1 and month=$2;
EXECUTE plan1('256ac66bb53d31bc6124294238d6410c','11');
explain analyze EXECUTE  plan1('256ac66bb53d31bc6124294238d6410c','11');
```
注意这里只插入11月前的数据，12月是没有数据的。此时查12月数据可以走到month索引
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
--第六次
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
第六次绑定了generic plan，但是并不是前五次的plan，走的是id索引。如果id的重复度再高点的话，也可以测出来绑不上generic plan的场景（未展示）。
这里就要看下源码了
`choose_custom_plan`
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
只要generic plan的cost 小于 前5次的custom_cost平均值，那么就使用generic plan。
虽然5次机制众所周知，但是需要注意generic plan是怎么生成的。第5次时还没有generic plan（刚开始的时候），generic_cost=-1，会直接返回`GetCachedPlan`中的`!customplan`逻辑
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
`!customplan`逻辑中，如果有generic plan直接使用，没有的话通过`BuildCachedPlan`生成一个plan，`BuildCachedPlan`就是生成plan的主体逻辑，通过query tree生成plan tree。
没有参数怎么办？注释已经说明，没有参数就传NULL进去，到生成plan的逻辑
```c
To build a generic, parameter-value-independent plan, pass NULL for
 * boundParams.  To build a custom plan, pass the actual parameter values via
 * boundParams
```
传NULL优化器更prefer什么执行计划？这部分代码逻辑有些复杂。从优化器的角度考虑，可能是有多个plan可以选择的，但总得选一个作为generic plan
而选出来那个generic plan，才可以对比前5次的plan cost。
为什么用更低cost的执行计划反复执行，没有生成想要的generic plan？
**generic plan长什么样跟前五次的执行计划没有关系，前五次只是决定了是否绑定这个generic plan**。

从优化器设计的角度来考虑，generic plan是为了减少解析时间提高sql执行效率，适合多而小的查询。问题在于generic plan本身很粗糙，postgres引进五次机制就是为了来减少generic plan本身是稀烂的可能性。
即使有五次机制，还是导致绑定的烂generic plan的原因：
 - generic plan也是plan，本身就可能烂
 - 统计信息不准确，generic plan的cost预估很低
 - 前五次的传参选择率低（或其他影响）导致custom plan cost高



## prepare statement的失效
除了DDL、deallocate、断开会话，收集统计信息也会让prepared statement，不过这是pg14的特性。
pg13:

>PostgreSQL will force re-analysis and re-planning of the statement before using it whenever database objects used in the statement have undergone definitional (DDL) changes since the previous use of the prepared statement

pg14:
>PostgreSQL will force re-analysis and re-planning of the statement before using it whenever database objects used in the statement have undergone definitional (DDL) changes or their planner statistics have been updated since the previous use of the prepared statement

pg13 收集统计信息不会让prepare statement失效的测试：
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

## jdbc的prepare statement
prepare statement不是PG的独有功能，一些数据库也有相关的预解析特性，比如oracle也可以实现类似的功能。
[jdbc](https://jenkov.com/tutorials/jdbc/preparedstatement.html#:~:text=JDBC%20PreparedStatement%201%20Creating%20a%20PreparedStatement%20Before%20you,Reusing%20a%20PreparedStatement%20...%205%20PreparedStatement%20Performance%20)自身也可以调用数据库的预解析接口，直接显示使用 prepare statement。
jdbc参考配置：
```sql
String sql = "select * from people where id=?";

PreparedStatement preparedStatement =
        connection.prepareStatement(sql);
```


# 建议
1. 调小表级的`autovacuum_analyze_scale_factor=0.02`（why 0.02？0.02<1/31)。因为是边写边查，手动收集不太好定时间，调小`autovacuum_analyze_scale_factor`只能减缓这个问题。
2. 考虑去掉jdbc中的prepare设置，或者设置`force_custom_plan`
3. 调整sql逻辑
4. 调整索引。4.1删除不必要的时间索引；4.2将越界后走的索引重建为包含id字段的组合索引（一个不错的建议）。
5. 应急流程：统计信息收集后业务未恢复的情况，确认手动explain执行计划改变的情况下，可以考虑杀会话(13以前)。

最后，谓词越界问题基本上在所有数据库中都有，特别是在时间字段上。现有手段其实没有一个比较简单又能完美解决的办法，oracle的SPM好感度又+1...
