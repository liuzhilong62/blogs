# 问题现象
备份进程命令pg_start_backup()被checkpoint进程阻塞，checkpoint被逻辑复制walsender进程阻塞。业务虽然还在继续运行，但是备份、checkpoint、逻辑复制全部hang死。


pg_stat_activity 中有两个明显异常的等待事件：`replication_slot_io` 。
```sql

[postgres@hostlzl:6666/postgres][04-08.16:50:28]=>  select * from  pg_stat_activity where pid=173038 \gx
-[ RECORD 1 ]----+------------------------------
datid            | 17630
datname          | lzldb
pid              | 173038
usesysid         | 35157
usename          | repuser
application_name | PostgreSQL JDBC Driver
client_addr      | 30.88.75.58
client_hostname  | [null]
client_port      | 37623
backend_start    | 2024-04-02 11:40:07.75022+08
xact_start       | [null]
query_start      | [null]
state_change     | 2024-04-02 11:40:07.764475+08
wait_event_type  | LWLock
wait_event       | replication_slot_io
state            | active
backend_xid      | [null]
backend_xmin     | [null]
query            | 
backend_type     | walsender

Time: 6.658 ms
[postgres@hostlzl:6666/postgres][04-08.16:50:34]=>  select * from  pg_stat_activity where pid=12729\gx
-[ RECORD 1 ]----+------------------------------
datid            | [null]
datname          | [null]
pid              | 12729
usesysid         | [null]
usename          | [null]
application_name | 
client_addr      | [null]
client_hostname  | [null]
client_port      | [null]
backend_start    | 2024-04-02 11:23:03.343116+08
xact_start       | [null]
query_start      | [null]
state_change     | [null]
wait_event_type  | LWLock
wait_event       | replication_slot_io
state            | [null]
backend_xid      | [null]
backend_xmin     | [null]
query            | 
backend_type     | checkpointer
```
一个是walsender进程，一个是checkpointer进程。都是4月2日启动的进程，直接查看4月2日walsender 173038的日志：
```shell
--repuser log
2024-04-02 11:40:07.750 CST,,,173038,"30.88.75.58:37623",660b7e17.2a3ee,1,"",2024-04-02 11:40:07 CST,,0,LOG,00000,"connection received: host=30.88.75.58 port=37623",,,,,,,,,""
2024-04-02 11:40:07.756 CST,"repuser","lzldb",173038,"30.88.75.58:37623",660b7e17.2a3ee,2,"authentication",2024-04-02 11:40:07 CST,32/30,0,LOG,00000,"replication connection authorized: user=repuser",,,,,,,,,""
2024-04-02 11:40:07.765 CST,"repuser","lzldb",173038,"30.88.75.58:37623",660b7e17.2a3ee,3,"idle",2024-04-02 11:40:07 CST,32/0,0,LOG,00000,"starting logical decoding for slot ""pg_lzldb_lzldb_ora_pgdb_pgdb""","Streaming transactions committing after 4263/42E6EF88, reading WAL from 4263/41DAEBD0.",,,,,,,,"PostgreSQL JDBC Driver"
2024-04-02 11:40:07.765 CST,"repuser","lzldb",173038,"30.88.75.58:37623",660b7e17.2a3ee,4,"idle",2024-04-02 11:40:07 CST,32/0,0,LOG,00000,"logical decoding found consistent point at 4263/41DAEBD0","There are no running transactions.",,,,,,,,"PostgreSQL JDBC Driver"
```
173038这个walsender进程只能看到start启动链路信息，后面这个walsender再也没有输出过日志，很有可能从那个时候起开始hang了。
不过再往前翻一点，还可以看到相同复制链路的walsender信息（walsender进程号不同，slot name相同）：
```shell
--84918 之前的启动日志
2024-04-02 11:30:07.498 CST,,,84918,"30.88.75.58:54898",660b7bbf.14bb6,1,"",2024-04-02 11:30:07 CST,,0,LOG,00000,"connection received: host=30.88.75.58 port=54898",,,,,,,,,""
2024-04-02 11:30:07.504 CST,"repuser","lzldb",84918,"30.88.75.58:54898",660b7bbf.14bb6,2,"authentication",2024-04-02 11:30:07 CST,30/3,0,LOG,00000,"replication connection authorized: user=repuser",,,,,,,,,""
2024-04-02 11:30:07.514 CST,"repuser","lzldb",84918,"30.88.75.58:54898",660b7bbf.14bb6,3,"idle",2024-04-02 11:30:07 CST,30/0,0,LOG,00000,"starting logical decoding for slot ""pg_lzldb_lzldb_ora_pgdb_pgdb""","Streaming transactions committing after 4263/41DADE38, reading WAL from 4263/358F1340.",,,,,,,,"PostgreSQL JDBC Driver"
2024-04-02 11:30:07.516 CST,"repuser","lzldb",84918,"30.88.75.58:54898",660b7bbf.14bb6,4,"idle",2024-04-02 11:30:07 CST,30/0,0,LOG,00000,"logical decoding found consistent point at 4263/358F1340","There are no running transactions.",,,,,,,,"PostgreSQL JDBC Driver"

2024-04-02 11:36:07.061 CST,"repuser","lzldb",86630,"30.88.75.58:45227",660b7bca.15266,5,"idle",2024-04-02 11:30:18 CST,30/0,0,ERROR,XX000,"could not write to file ""pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"": Cannot allocate memory",,,,,,,,,"PostgreSQL JDBC Driver"
2024-04-02 11:36:40.151 CST,"repuser","lzldb",86630,"30.88.75.58:45227",660b7bca.15266,6,"idle",2024-04-02 11:30:18 CST,,0,LOG,00000,"disconnection: session time: 0:06:21.760 user=repuser database=lzldb host=30.88.75.58 port=45227",,,,,,,,,"PostgreSQL JDBC Driver"
```
这个复制槽在11:30:07也启动过一次，并且过了6分钟后，因为内存打满导致写入`state.tmp`失败。
同样的，上面查出来的checkpoint进程12729，也报了相同的state.tmp文件错误`pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"": File exists"`，该报错在复制槽报错后的半分钟出现：
```shell
--checkpoint log
2024-04-02 11:36:39.925 CST,,,12729,,660b7a17.31b9,4,,2024-04-02 11:23:03 CST,,0,LOG,58P02,"could not create file ""pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"": File exists",,,,,,,,,""
2024-04-02 11:36:40.151 CST,,,12729,,660b7a17.31b9,5,,2024-04-02 11:23:03 CST,,0,LOG,00000,"checkpoint complete: wrote 334 buffers (0.0%); 0 WAL file(s) added, 0 removed, 0 recycled; write=0.108 s, sync=0.082 s, total=217.083 s; sync files=139, longest=0.004 s, average=0.000 s; distance=2295 kB, estimate=2295 kB",,,,,,,,,""
2024-04-02 11:48:03.414 CST,,,12729,,660b7a17.31b9,6,,2024-04-02 11:23:03 CST,,0,LOG,00000,"checkpoint starting: time",,,,,,,,,""
```
checkpoint此后再也没有出现过日志输出，看起来跟walsender一样，hang住了。

通过搜索`pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"": File exists"`可以快速又简单的找到社区邮件：<https://www.postgresql.org/message-id/14b3454f-2d68-c637-68e4-2b42ff976168%40postgrespro.ru>
它真正的修复版本是[PG12.3](https://www.postgresql.org/docs/release/12.3/)：
>Ensure that a replication slot's io_in_progress_lock is released in failure code paths (Pavan Deolasee)
This could result in a walsender later becoming stuck waiting for the lock.


# 深入分析

虽然找到了bug，但其实很多问题没有搞清楚：
 - walsender和checkpoints为什么hang住了？
 - walsender和checkpoints是谁阻塞了谁？
 - 怎么触发的？
 - 有什么解决方案？

## 源码分析
当前版本为11.5。

walsender和checkpointer两个进程的的pstack：

```shell
[postgres@hostlzl:lzldb:6666: /pg/pg6666/data/pg_log]$ pstack 173038  ##walsender
#0  0x00002b9eec171a0b in do_futex_wait.constprop.1 () from /lib64/libpthread.so.0
#1  0x00002b9eec171a9f in __new_sem_wait_slow.constprop.0 () from /lib64/libpthread.so.0
#2  0x00002b9eec171b3b in sem_wait@@GLIBC_2.2.5 () from /lib64/libpthread.so.0
#3  0x00000000006b2512 in PGSemaphoreLock (sema=0x2b9ef5fdb0b8) at pg_sema.c:316
#4  0x000000000071e94c in LWLockAcquire (lock=lock@entry=0x2babd8cee5b8, mode=mode@entry=LW_EXCLUSIVE) at lwlock.c:1243
#5  0x00000000006ef7cb in SaveSlotToPath (slot=0x2babd8cee500, dir=dir@entry=0x7ffcaffd79f0 "pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb", elevel=elevel@entry=20) at slot.c:1249
#6  0x00000000006f0515 in ReplicationSlotSave () at slot.c:653
#7  0x00000000006d75d8 in LogicalConfirmReceivedLocation (lsn=<optimized out>) at logical.c:1049
#8  0x00000000006d774d in LogicalIncreaseXminForSlot (current_lsn=current_lsn@entry=72994075200640, xmin=xmin@entry=1241611955) at logical.c:914
#9  0x00000000006e0fb3 in SnapBuildProcessRunningXacts (builder=builder@entry=0x23146c0, lsn=72994075200640, running=running@entry=0x22e8978) at snapbuild.c:1146
#10 0x00000000006d484c in DecodeStandbyOp (buf=0x7ffcaffd7eb0, buf=0x7ffcaffd7eb0, ctx=0x2209820) at decode.c:318
#11 LogicalDecodingProcessRecord (ctx=0x2209820, record=<optimized out>) at decode.c:121
#12 0x00000000006e50e0 in XLogSendLogical () at walsender.c:2799
#13 0x00000000006e7122 in WalSndLoop (send_data=send_data@entry=0x6e5080 <XLogSendLogical>) at walsender.c:2162
#14 0x00000000006e7d91 in StartLogicalReplication (cmd=0x22eedd8) at walsender.c:1109
#15 exec_replication_command (cmd_string=cmd_string@entry=0x2210c48 "START_REPLICATION SLOT pg_lzldb_lzldb_ora_pgdb_pgdb LOGICAL 4263/42E6EF88 (\"add-tables\" 'public.acr_finance_coa_partition_17_01,public.acr_finance_coa_partition_17_02,public.acr_finance_coa_part"...) at walsender.c:1541
#16 0x000000000072c899 in PostgresMain (argc=<optimized out>, argv=argv@entry=0x2216f78, dbname=0x2216c98 "lzldb", username=<optimized out>) at postgres.c:4178
#17 0x000000000047e481 in BackendRun (port=0x220eda0) at postmaster.c:4358
#18 BackendStartup (port=0x220eda0) at postmaster.c:4030
#19 ServerLoop () at postmaster.c:1707
#20 0x00000000006c4359 in PostmasterMain (argc=argc@entry=3, argv=argv@entry=0x21dbe90) at postmaster.c:1380
#21 0x000000000047eefb in main (argc=3, argv=0x21dbe90) at main.c:228


[postgres@hostlzl:lzldb:6666: /pg/pg6666/data/pg_wal]$ pstack 12729  ##checkpointer
#0  0x00002b9eec171a0b in do_futex_wait.constprop.1 () from /lib64/libpthread.so.0
#1  0x00002b9eec171a9f in __new_sem_wait_slow.constprop.0 () from /lib64/libpthread.so.0
#2  0x00002b9eec171b3b in sem_wait@@GLIBC_2.2.5 () from /lib64/libpthread.so.0
#3  0x00000000006b2512 in PGSemaphoreLock (sema=0x2b9ef5fdcd38) at pg_sema.c:316
#4  0x000000000071e94c in LWLockAcquire (lock=lock@entry=0x2babd8cee5b8, mode=mode@entry=LW_EXCLUSIVE) at lwlock.c:1243
#5  0x00000000006ef7cb in SaveSlotToPath (slot=slot@entry=0x2babd8cee500, dir=dir@entry=0x7ffcaffd6ee0 "pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb", elevel=elevel@entry=15) at slot.c:1249
#6  0x00000000006f11a7 in CheckPointReplicationSlots () at slot.c:1100
#7  0x00000000004f674f in CheckPointGuts (checkPointRedo=72994093982360, flags=flags@entry=128) at xlog.c:9146
#8  0x00000000004fcc77 in CreateCheckPoint (flags=flags@entry=128) at xlog.c:8937
#9  0x00000000006b8312 in CheckpointerMain () at checkpointer.c:491
#10 0x000000000050ba15 in AuxiliaryProcessMain (argc=argc@entry=2, argv=argv@entry=0x7ffcaffd7540) at bootstrap.c:451
#11 0x00000000006c1cb9 in StartChildProcess (type=CheckpointerProcess) at postmaster.c:5337
#12 0x00000000006c2f5a in reaper (postgres_signal_arg=<optimized out>) at postmaster.c:2867
#13 <signal handler called>
#14 0x00002b9eed5ba783 in __select_nocancel () from /lib64/libc.so.6
#15 0x000000000047db38 in ServerLoop () at postmaster.c:1671
#16 0x00000000006c4359 in PostmasterMain (argc=argc@entry=3, argv=argv@entry=0x21dbe90) at postmaster.c:1380
#17 0x000000000047eefb in main (argc=3, argv=0x21dbe90) at main.c:228
```
最值得注意的是`LWLockAcquire`这行的堆栈，walsender和checkpointer都有这样的进栈，并且他们俩都以排他模式申请了同一个LWLOCK地址：`lock=lock@entry=0x2babd8cee5b8, mode=mode@entry=LW_EXCLUSIVE`，进入无限期的等待···
`LWLockAcquire`的上一个堆栈函数便是`SaveSlotToPath`。

在`src/backend/replication/slot.c`中找到关键问题函数源码`SaveSlotToPath`：

```c
//SaveSlotToPath用于存储slot的状态
static void
SaveSlotToPath(ReplicationSlot *slot, const char *dir, int elevel)
{	//11.5代码
	char		tmppath[MAXPGPATH];
	char		path[MAXPGPATH];
	int			fd;
	ReplicationSlotOnDisk cp;
	bool		was_dirty;
...
	/* and don't do anything if there's nothing to write */
	if (!was_dirty)
		return;
	//函数开头获得LWLock，排他模式
	LWLockAcquire(&slot->io_in_progress_lock, LW_EXCLUSIVE);

...
	//注意fd的逻辑，报错与第二次walsender报错一致
	fd = OpenTransientFile(tmppath, O_CREAT | O_EXCL | O_WRONLY | PG_BINARY);
	if (fd < 0)
	{
		ereport(elevel,
				(errcode_for_file_access(),
				 errmsg("could not create file \"%s\": %m",
						tmppath)));
		return;
...
	//写入fd文件的逻辑，报错与首次walsender报错一致
	if ((write(fd, &cp, sizeof(cp))) != sizeof(cp))
	{
		int			save_errno = errno;

		pgstat_report_wait_end();
		CloseTransientFile(fd);

		/* if write didn't set errno, assume problem is no disk space */
		errno = save_errno ? save_errno : ENOSPC;
		ereport(elevel,
				(errcode_for_file_access(),
				 errmsg("could not write to file \"%s\": %m",
						tmppath)));
		return;
	}
...
	LWLockRelease(&slot->io_in_progress_lock);	//函数最后释放LWLock
	}
```	
`SaveSlotToPath`函数上来就获取`LWLockAcquire`，传入slot地址，命名跟等待事件非常类似：`io_in_progress_lock`<->` replication_slot_io`，以`LW_EXCLUSIVE`模式申请LWLOCK。
在`SaveSlotToPath`函数最后有`LWLockRelease`释放LWLOCK。
**但是，在所有if判断中，没有任何LWLockRelease，直接return**！！！

而pg日志中的输出就是“could not create file” tmppath，说明代码就是走到了以上两个if逻辑里，也就是**写入state.tmp失败**和**创建state.tmp失败**的if逻辑中。

联系pglog中的报错顺序：
 1. 11:36:07：逻辑复制首次报错"could not write to file ""pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"，复制链路挂掉
 2. 11:36:39：checkpointer进程报错"could not create file ""pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"，并于1秒后“complete”，写入0个脏块，0条wal
 3. 11:40:07：逻辑复制再次启动，启动后再无输出
 4. 11:48:03：checkpointer进程再次触发start，后续再无输出，后续再无输出

上面有两个逻辑复制和两个checkpointer的日志输出，这里要注意一个很重要的信息：第一次逻辑复制和第二次逻辑复制归属于*不同的*walsender进程；第一次checkpoint和第二次checkpoint信息归属于*相同的*checkpointer进程。

从以上信息总结出故障原理：
 1. 逻辑复制因内存问题，写入state.tmp失败，留下一个残存的state.tmp文件
 2. checkpointer进程因残存的state.tmp文件，在`SaveSlotToPath`函数中，以排他模式获得LWLock后进入`if (fd < 0)`判断，不释放LWLock直接return
 3. 逻辑复制再次启动，walsender进程在`SaveSlotToPath`函数开头申请LWLock，开始无限期等待
 4. checkpointer进程触发start checkpoint，checkpointer进程在`SaveSlotToPath`函数开头申请LWLock，开始无限期等待

故障原理理清后答案自然就很清楚：
 - walsender和checkpointer为什么hang住了？如上故障原理分析。残存的state.tmp，checkpointer持有LWLock未释放，walsender和checkpointer无限等待。
 - walsender和checkpointer是谁阻塞了谁？checkpointer阻塞walsender
 - 怎么触发的？前一个walsender进程因为内存打满写了state.tmp未清理
 - 有什么解决方案？强制重启数据库

## 复现
pg逻辑复制知识可参考[pg内功修炼：逻辑复制](https://blog.csdn.net/qq_40687433/article/details/129291207?ops_request_misc=%257B%2522request%255Fid%2522%253A%2522171267312516800182785061%2522%252C%2522scm%2522%253A%252220140713.130102334.pc%255Fblog.%2522%257D&request_id=171267312516800182785061&biz_id=0&utm_medium=distribute.pc_search_result.none-task-blog-2~blog~first_rank_ecpm_v1~rank_v31_ecpm-1-129291207-null-null.nonecase&utm_term=%E9%80%BB%E8%BE%91%E5%A4%8D%E5%88%B6&spm=1018.2226.3001.4450)，主要使用以下命令：
```sql
select pg_create_logical_replication_slot('logical_test','test_decoding');
pg_recvlogical -h 127.0.0.1 -p 5558 -d lzldb -U lzl --slot=logical_test --start -f recv.sql &
```
复制槽和逻辑复制链路就OK了：
```sql
postgres=#  select pid,usename,xact_start,state_change,wait_event,state,query from  pg_stat_activity where state<>'idle' order by xact_start ;
  pid  | usename  |          xact_start           |         state_change          |     wait_event      | state  |                                                               query                          
                                      
-------+----------+-------------------------------+-------------------------------+---------------------+--------+----------------------------------------------------------------------------------------------
--------------------------------------
 59916 | postgres | 2024-04-08 21:14:32.015534+08 | 2024-04-08 21:14:32.015545+08 |                     | active | select pid,usename,xact_start,state_change,wait_event,state,query from  pg_stat_activity wher
e state<>'idle' order by xact_start ;
 59791 | lzl      |                               | 2024-04-08 21:14:19.566112+08 | WalSenderWaitForWAL | active | SELECT pg_catalog.set_config('search_path', '', false)

postgres=# select pid,usename,application_name,backend_start,state,pg_walfile_name_offset(sent_lsn) sentoffset,pg_walfile_name_offset(write_lsn) writeoffset,pg_walfile_name_offset(flush_lsn) flushoffset from pg_stat_replication;
  pid  | usename | application_name |        backend_start         |   state   |             sentoffset             |            writeoffset             |            flushoffset             
-------+---------+------------------+------------------------------+-----------+------------------------------------+------------------------------------+------------------------------------
 59791 | lzl     | pg_recvlogical   | 2024-04-08 21:14:19.56364+08 | streaming | (000000010000000000000001,6612032) | (000000010000000000000001,6612032) | (000000010000000000000001,6612032)
```
因为是state.tmp文件引起的，直接在pg_replslot下面touch
```sql
[postgres@testhost logical_test]$ pwd
/pgdata/lzl/data11/pg_replslot/logical_test
```
pg_recvlogical立马报错：
```sql
 pg_recvlogical: unexpected termination of replication stream: ERROR:  could not create file "pg_replslot/logical_test/state.tmp": File exists
```
手动执行checkpoint也会hang住
```sql
lzldb=# checkpoint;

--hang
```
在看下walsender和会话的状态：
```sql
postgres=> select * from pg_stat_activity ;
 datid | datname  |  pid  | usesysid | usename  | application_name | client_addr | client_hostname | client_port |         backend_start         |          xact_start           |          query_start         
 |         state_change          | wait_event_type |     wait_event      | state  | backend_xid | backend_xmin |                         query                          |         backend_type         
-------+----------+-------+----------+----------+------------------+-------------+-----------------+-------------+-------------------------------+-------------------------------+------------------------------
-+-------------------------------+-----------------+---------------------+--------+-------------+--------------+--------------------------------------------------------+------------------------------
...                         
 |                               | Activity        | LogicalLauncherMain |        |             |              |                                                        | logical replication launcher
 | 2024-04-08 21:25:55.058523+08 |                 |                     | active |             |              | checkpoint;                                            | client backend
 16384 | lzldb    | 77638 |    16385 | lzl      | pg_recvlogical   | 127.0.0.1   |                 |       56928 | 2024-04-08 21:25:17.495833+08 |                               | 2024-04-08 21:25:17.497754+08
 | 2024-04-08 21:25:17.498329+08 | LWLock          | replication_slot_io | active |             |              | SELECT pg_catalog.set_config('search_path', '', false) | walsender
 |                               | LWLock          | replication_slot_io |        |             |              |                                                        | checkpointer
```
完美复现2个replication_slot_io 等待事件


## PG12.3的代码已优化
```c
//这里贴的是15.3，比12.3多一段save_errno
static void
SaveSlotToPath(ReplicationSlot *slot, const char *dir, int elevel)
{	
	fd = OpenTransientFile(tmppath, O_CREAT | O_EXCL | O_WRONLY | PG_BINARY);
	if (fd < 0)
	{
		/*
		 * If not an ERROR, then release the lock before returning.  In case
		 * of an ERROR, the error recovery path automatically releases the
		 * lock, but no harm in explicitly releasing even in that case.  Note
		 * that LWLockRelease() could affect errno.
		 */
		int			save_errno = errno;

		LWLockRelease(&slot->io_in_progress_lock);
		errno = save_errno;
		ereport(elevel,
				(errcode_for_file_access(),
				 errmsg("could not create file \"%s\": %m",
						tmppath)));
		return;
	}
...
LWLockRelease(&slot->io_in_progress_lock);

}	
```	
在**每一个 if中**，在都会先运行LWLockRelease，然后再return。这样就不会某些场景下LWLock不释放的逻辑漏洞了，代码明显更为健壮。

## 解决办法分析
因为state.tmp文件只是诱因，LWLOCK已经持有了，删除state.tmp不会解决这个问题。
因为真正持有LW_LOCK的人是checkpointer，所以重启复制链路或者kill下游都是也是没有用的。
因为是checkpointer进程不能直接kill，目前这个状态除了重启没有好的解决办法，而且只有**强制重启**进行实例恢复，正常关库因为checkpoint阻塞是关不了的···
最后，终极解决办法当然是升级到PG12.3以上。

*（另外，我也试了下gdb调用LWLockRelease（LWLock的地址pstack已经输出了），直接把测试环境库搞挂了，所以就不推荐gdb了）*

# 总结
PG在近期的版本中最为重要的特性提升之一就是逻辑复制，早期的PG的逻辑复制确实是存在很多问题，坑多。PG这种[大包大揽的逻辑复制思路](https://blog.csdn.net/qq_40687433/article/details/136405862?spm=1001.2014.3001.5501)很有技术创新的精神，而且也能看到社区孜孜不倦地对逻辑复制的完善和加强，几乎每个小版本都能搜到逻辑复制的许多更新。这个案例就是一个现实的例子，逻辑复制的代码明显越来越健壮。
逻辑复制的知识点其实挺多的，最后推荐一波之前的文章：[pg内功修炼：逻辑复制](https://blog.csdn.net/qq_40687433/article/details/129291207?ops_request_misc=%257B%2522request%255Fid%2522%253A%2522171267312516800182785061%2522%252C%2522scm%2522%253A%252220140713.130102334.pc%255Fblog.%2522%257D&request_id=171267312516800182785061&biz_id=0&utm_medium=distribute.pc_search_result.none-task-blog-2~blog~first_rank_ecpm_v1~rank_v31_ecpm-1-129291207-null-null.nonecase&utm_term=%E9%80%BB%E8%BE%91%E5%A4%8D%E5%88%B6&spm=1018.2226.3001.4450)
