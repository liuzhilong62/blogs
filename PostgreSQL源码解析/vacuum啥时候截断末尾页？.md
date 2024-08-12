
# vacuum truncate
>TRUNCATE---Specifies that `VACUUM` should attempt to truncate off any empty pages at the end of the table and allow the disk space for the truncated pages to be returned to the operating system. This is normally the desired behavior and is the default unless the `vacuum_truncate` option has been set to false for the table to be vacuumed. Setting this option to false may be useful to avoid `ACCESS EXCLUSIVE` lock on the table that the truncation requires. This option is ignored if the `FULL` option is used.

AKA，vacuum操作中的truncate选项是默认打开的，它会把表末尾的pages移除，移除的时候会获得一个表上的8级锁。
今天发现某个环境上delete from删除完所有数据后，autovacuum自动触发或者手动跑vacuum，都不会回收空间。
重现问题:
```sql
create table lzl1(a int);
insert into lzl1 select generate_series(1,1000) a;
analyze lzl1;
```
```
lzldb=#  select relname,relpages,reltuples from   pg_class where relname='lzl1';
 relname | relpages | reltuples 
---------+----------+-----------
 lzl1    |        5 |      1000
```
在relpage是5，最后一个页的页号是4
```
lzldb=> select t_ctid,lp,case lp_flags when 0 then '0:LP_UNUSED' when 1 then 'LP_NORMAL' when 2 then 'LP_REDIRECT'  when 3 then 'LP_DEAD' end as lp_flags,t_xmin,t_xmax,t_field3 as t_cid, raw_flags, info.combined_flags,substring(t_data,0,40) from heap_page_items(get_raw_page('lzl1',4)) item,LATERAL heap_tuple_infomask_flags(t_infomask, t_infomask2) info order by lp;
 t_ctid | lp | lp_flags  | t_xmin | t_xmax | t_cid |                raw_flags                | combined_flags | substring  
--------+----+-----------+--------+--------+-------+-----------------------------------------+----------------+------------
 (4,1)  |  1 | LP_NORMAL |    772 |      0 |     0 | {HEAP_XMIN_COMMITTED,HEAP_XMAX_INVALID} | {}             | \x89030000
 (4,2)  |  2 | LP_NORMAL |    772 |      0 |     0 | {HEAP_XMIN_COMMITTED,HEAP_XMAX_INVALID} | {}             | \x8a030000
 ...
```

```sql
delete from lzl1;
vacuum lzl1;
```

```sql
lzldb=> select t_ctid,lp,case lp_flags when 0 then '0:LP_UNUSED' when 1 then 'LP_NORMAL' when 2 then 'LP_REDIRECT'  when 3 then 'LP_DEAD' end as lp_flags,t_xmin,t_xmax,t_field3 as t_cid, raw_flags, info.combined_flags,substring(t_data,0,40) from heap_page_items(get_raw_page('lzl1',4)) item,LATERAL heap_tuple_infomask_flags(t_infomask, t_infomask2) info order by lp;
 t_ctid | lp |  lp_flags   | t_xmin | t_xmax | t_cid | raw_flags | combined_flags | substring 
--------+----+-------------+--------+--------+-------+-----------+----------------+-----------
        |  1 | 0:LP_UNUSED |        |        |       |           |                | 
        lzldb=# select relname,relpages,reltuples from   pg_class where relname='lzl1';
 relname | relpages | reltuples 
---------+----------+-----------
 lzl2    |        5 |         0
```
看上去死元组都回收了，不过空间还是占用着的，page并没有回收
为什么表里面都没有数据了还不做截断操作？带着这个问题来一探究竟。

# should_attempt_truncation函数源码分析
（未声明版本的都是PG11）
在vacuumlazy.c中有一个言简意赅的函数`should_attempt_truncation`，这个就是判断是否需要做truncation的函数：
```c
static bool
should_attempt_truncation(LVRelStats *vacrelstats)
{
	BlockNumber possibly_freeable;

	possibly_freeable = vacrelstats->rel_pages - vacrelstats->nonempty_pages;
	if (possibly_freeable > 0 &&
		(possibly_freeable >= REL_TRUNCATE_MINIMUM ||
		 possibly_freeable >= vacrelstats->rel_pages / REL_TRUNCATE_FRACTION) &&
		old_snapshot_threshold < 0)
		return true;
	else
		return false;
}
```
其中
```c
#define REL_TRUNCATE_MINIMUM 1000
#define REL_TRUNCATE_FRACTION 16
```
所以是否truncation的判断逻辑必须满足以下条件：
 - 末尾空page数大于1000 或 末尾空page数大于总page数的1/16
 - old_snapshot_threshold<0

第一个规则是为了不用老是去截断那先零零碎碎的末尾空page，这回收不了多少空间，不仅浪费时间还浪费8级锁，没有必要。
第二个规则是这样解释的：
```c
 * Also don't attempt it if we are doing early pruning/vacuuming, because a
 * scan which cannot find a truncated heap page cannot determine that the
 * snapshot is too old to read that page.  We might be able to get away with
 * truncating all except one of the pages, setting its LSN to (at least) the
 * maximum of the truncated range if we also treated an index leaf tuple
 * pointing to a missing heap page as something to trigger the "snapshot too
 * old" error, but that seems fragile and seems like it deserves its own patch
 * if we consider it.
```
“因为vacuum扫描还不能确认page上的数据是否有快照过久问题，里面还有些LSN、索引页问题，代码逻辑看起来很琐碎，如果需要这个功能的话，需要一个patch来解决这个问题”
OK，看起来就是没有去判断page是否真的有快照过久问题，那么简单粗暴地以old_snapshot_threshold<0来判断，数据库本身关闭了快照过久问题，才会去truncation。

回到之前的vacuum没有回收的问题，因为是delete删除了所有数据，所以肯定满足“末尾空page数大于总page数的1/16”，然而环境中的old_snapshot_threshold确是打开的：
```sql
lzldb=> show  old_snapshot_threshold ;
 old_snapshot_threshold 
------------------------
 1h
```
关闭old_snapshot_threshold再去做这个delete全表+vacuum就会回收了。关闭old_snapshot_threshold需要重启数据库。
```sql
--重启后
lzldb=> show  old_snapshot_threshold ;
 old_snapshot_threshold 
------------------------
 -1
lzldb=> select pg_relation_filepath('lzl1');
 pg_relation_filepath 
----------------------
 base/16384/16446

lzldb=> vacuum lzl1; 
--pages成功回收
lzldb=#  select relname,relpages,reltuples from   pg_class where relname='lzl1';
 relname | relpages | reltuples 
---------+----------+-----------
 lzl1    |        0 |         0
--没有重建表 
lzldb=>  select pg_relation_filepath('lzl1');
 pg_relation_filepath 
----------------------
 base/16384/16446
```
pages全部成功回收，表没有重建。问题就算定位完了。
不过为了更进一步了解vacuum truncation机制，还可以继续看看下面的章节。

# lazy_truncate_heap函数源码分析
仅仅通过`should_attempt_truncation`函数来判断是否truncation还不严谨，还要看一眼真正执行truncation的函数`lazy_truncate_heap`，里面还有一些判断
```c
/*
 * lazy_truncate_heap - try to truncate off any empty pages at the end
 */
static void
lazy_truncate_heap(Relation onerel, LVRelStats *vacrelstats)
{
	BlockNumber old_rel_pages = vacrelstats->rel_pages;
	BlockNumber new_rel_pages;
	int			lock_retry;

	/* Report that we are now truncating */
	pgstat_progress_update_param(PROGRESS_VACUUM_PHASE,
								 PROGRESS_VACUUM_PHASE_TRUNCATE);

	/*
	 * Loop until no more truncating can be done.
	 */
	do
	{
		PGRUsage	ru0;

		pg_rusage_init(&ru0);

		/*
		 * We need full exclusive lock on the relation in order to do
		 * truncation. If we can't get it, give up rather than waiting --- we
		 * don't want to block other backends, and we don't want to deadlock
		 * (which is quite possible considering we already hold a lower-grade
		 * lock).
		 */
		vacrelstats->lock_waiter_detected = false;
		lock_retry = 0;
		while (true)
		{	
			//如果可以获得锁，break while
			if (ConditionalLockRelation(onerel, AccessExclusiveLock))
				break;

			/*
			 * Check for interrupts while trying to (re-)acquire the exclusive
			 * lock.
			 */
			CHECK_FOR_INTERRUPTS();
			
			//如果没有立即获得锁，最初(++lock_retry)=1，不大于100；当大于100时，不做truncation直接返回
			if (++lock_retry > (VACUUM_TRUNCATE_LOCK_TIMEOUT /
								VACUUM_TRUNCATE_LOCK_WAIT_INTERVAL))
			{
				/*
				 * We failed to establish the lock in the specified number of
				 * retries. This means we give up truncating.
				 */
				vacrelstats->lock_waiter_detected = true;
				ereport(elevel,
						(errmsg("\"%s\": stopping truncate due to conflicting lock request",
								RelationGetRelationName(onerel))));
				return;
			}
			
			//sleep 50ms，看起来有点笨。理论上最长可以等50*100=5s
			pg_usleep(VACUUM_TRUNCATE_LOCK_WAIT_INTERVAL * 1000L);
		}

		//当我们拿到排他锁后，查看vacuum过程中是否有新元组，如有则不做truncation
		new_rel_pages = RelationGetNumberOfBlocks(onerel);
		if (new_rel_pages != old_rel_pages)
		{
			UnlockRelation(onerel, AccessExclusiveLock);
			return;
		}

		new_rel_pages = count_nondeletable_pages(onerel, vacrelstats);
		//如果vacuum过程中有新元组写入，不做truncation
		if (new_rel_pages >= old_rel_pages)
		{
			/* can't do anything after all */
			UnlockRelation(onerel, AccessExclusiveLock);
			return;
		}

		/*
		 * Okay to truncate.
		 */
		RelationTruncate(onerel, new_rel_pages);

		//truncation后立即释放锁
		UnlockRelation(onerel, AccessExclusiveLock);

...
	} while (new_rel_pages > vacrelstats->nonempty_pages &&
			 vacrelstats->lock_waiter_detected);
}
```
其中
```c
#define VACUUM_TRUNCATE_LOCK_WAIT_INTERVAL 50 /* 微秒！！ */
#define VACUUM_TRUNCATE_LOCK_TIMEOUT 5000 /* 微秒！！ */
```
真正调用的主题函数是RelationTruncate，前面一大截都是在尝试获取AccessExclusiveLock。除了之前说的2个条件外，还有以下两种情况不会做truncation
 - 没有获得AccessExclusiveLock
 - vacuum过程中有新数据写入


# vacuum truncate可能会等待5秒
上面翻`lazy_truncate_heap`源码的时候，发现循环获取锁那里的等待时间是有点笨：
```
pg_usleep(VACUUM_TRUNCATE_LOCK_WAIT_INTERVAL * 1000L);
```
这里每次循环会等待50ms，理论上最长可以等50*100=5s！
测试一把这个等待时间：
| 窗口1 | 窗口2 |
|--|--|
| create table lzl2; |  |
| alter table lzl2 set (autovacuum_enabled=off);; |  |
| insert into lzl2 select generate_series(1,1000) a; |  |
| delete from lzl2; |  |
|begin;||
|select * from lzl2;||
||\timing|
||vacuum lzl2; --Time: 5022.122 ms (00:05.022)|
可以看到等待时间约5s。
手速快的话还可以再开个窗口抓下会话2的pstack
```c
[postgres@cncq081298 lzl]$ pstack 4113
#0  0x00002b92a978c013 in __select_nocancel () from /lib64/libc.so.6
#1  0x000000000086225a in pg_usleep (microsec=microsec@entry=50000) at pgsleep.c:56
#2  0x00000000005e8212 in lazy_truncate_heap (vacrelstats=0xfc4490, onerel=0x2b92a8bc88d8) at vacuumlazy.c:1861
#3  lazy_vacuum_rel (onerel=onerel@entry=0x2b92a8bc88d8, options=options@entry=5, params=params@entry=0x7ffc96bb31d0, bstrategy=<optimized out>) at vacuumlazy.c:290
#4  0x00000000005e4551 in vacuum_rel (relid=32778, relation=<optimized out>, options=options@entry=5, params=params@entry=0x7ffc96bb31d0) at vacuum.c:1572
#5  0x00000000005e55ac in vacuum (options=5, relations=0xfc6540, params=params@entry=0x7ffc96bb31d0, bstrategy=<optimized out>, bstrategy@entry=0x0, isTopLevel=isTopLevel@entry=true) at vacuum.c:340
...
```
它走到了`lazy_truncate_heap`上的`pg_usleep `，传入`entry=50000 microsec`，实际上`pg_usleep`循环了100次，总等待时间是50000*100 microsec=5s。

后来PG15这段代码更优化了，把pg_usleep改成WaitLatch
```c
(void) WaitLatch(MyLatch,
WL_LATCH_SET | WL_TIMEOUT | WL_EXIT_ON_PM_DEATH,
VACUUM_TRUNCATE_LOCK_WAIT_INTERVAL,
WAIT_EVENT_VACUUM_TRUNCATE);
ResetLatch(MyLatch);
```

# vacuum truncate小结
vacuum触发truncation的条件（且）：
 - 末尾空page数大于1000 或 末尾空page数大于总page数的1/16
 - old_snapshot_threshold<0
 - PG15（不含）以前需要在5s内获得8级锁AccessExclusiveLock
 - vacuum过程中没有新数据写入


