
业务insert value偶发变慢，当我去查看活动会话的时候写入慢问题已经缓解了。
后来发现写入慢问题持续不到半分钟，insert value写入时间1-2s，写个抓活动会话的脚本还是能拿到会话信息：
```sql
     wait_event      | count
---------------------+-------
 [null]              |    11
 WALRead             |     1
 DataFileRead        |     2
 BgWriterMain        |     1
 WALWrite            |    40
 AutoVacuumMain      |     1
 ClientRead          |   385
 LogicalLauncherMain |     1
```
等待事件最异常的就是WALWrite 40个会话。
其中2个WALWrite等待的会话如下：
```sql
  pid  | usename  |          xact_start           |         state_change          |  wait_event   | wait_event_type | state  |                                                                                  partofquery
-------+----------+-------------------------------+-------------------------------+---------------+-----------------+--------+--------------------------------------------------------------
 144955 | lzluser11 | 2024-05-23 07:58:27.516574+08 | 2024-05-23 07:58:27.516588+08 | WALWrite       | LWLock          | active | insert into table1( 
 179869 | lzluser11 | 2024-05-23 07:58:28.116371+08 | 2024-05-23 07:58:28.116386+08 | WALWrite       | IO              | active | insert into table1( 
```
直接搜源码关于WALWrite的相关内容
```c
 * WALWriteLock: must be held to write WAL buffers to disk (XLogWrite or
 * XLogFlush).
```
 ```c
 /*
 * LWLockAcquireOrWait - Acquire lock, or wait until it's free
 *
 * The semantics of this function are a bit funky.  If the lock is currently
 * free, it is acquired in the given mode, and the function returns true.  If
 * the lock isn't immediately free, the function waits until it is released
 * and returns false, but does not acquire the lock.
 *
 * This is currently used for WALWriteLock: when a backend flushes the WAL,
 * holding WALWriteLock, it can flush the commit records of many other
 * backends as a side-effect.  Those other backends need to wait until the
 * flush finishes, but don't need to acquire the lock anymore.  They can just
 * wake up, observe that their records have already been flushed, and return.
 */ 
 ```
 wal从wal buffer写入磁盘时，必须持有WALWriteLock。
 当backend刷wal时，持有WALWriteLock，它也能刷其他backends提交记录。其他backends需要等这个flush完成，但不需要再去持有锁了。如果他们的wal被刷了，他们能直接返回（而不是再去刷一次wal）。
 
XLogFlush极其重要， XLogFlush的关键代码在for循环里：
```c
/*
 * Ensure that all XLOG data through the given position is flushed to disk.
 *
 * NOTE: this differs from XLogWrite mainly in that the WALWriteLock is not
 * already held, and we try to avoid acquiring it if possible.
 */
void
XLogFlush(XLogRecPtr record)
{
...

	/*
	 * Now wait until we get the write lock, or someone else does the flush
	 * for us.
	 */
	for (;;)
	{
		XLogRecPtr	insertpos;

		/* read LogwrtResult and update local state */
		SpinLockAcquire(&XLogCtl->info_lck);
		if (WriteRqstPtr < XLogCtl->LogwrtRqst.Write)
			WriteRqstPtr = XLogCtl->LogwrtRqst.Write;
		LogwrtResult = XLogCtl->LogwrtResult;
		SpinLockRelease(&XLogCtl->info_lck);

		/* done already? */
		if (record <= LogwrtResult.Flush)
			break;

		/*
		 * Before actually performing the write, wait for all in-flight
		 * insertions to the pages we're about to write to finish.
		 */
		insertpos = WaitXLogInsertionsToFinish(WriteRqstPtr);

		/*
		 * Try to get the write lock. If we can't get it immediately, wait
		 * until it's released, and recheck if we still need to do the flush
		 * or if the backend that held the lock did it for us already. This
		 * helps to maintain a good rate of group committing when the system
		 * is bottlenecked by the speed of fsyncing.
		 */
		if (!LWLockAcquireOrWait(WALWriteLock, LW_EXCLUSIVE))
		{
			/*
			 * The lock is now free, but we didn't acquire it yet. Before we
			 * do, loop back to check if someone else flushed the record for
			 * us already.
			 */
			continue;
		}

		/* Got the lock; recheck whether request is satisfied */
		LogwrtResult = XLogCtl->LogwrtResult;
		if (record <= LogwrtResult.Flush)
		{
			LWLockRelease(WALWriteLock);
			break;
		}

		/*
		 * Sleep before flush! By adding a delay here, we may give further
		 * backends the opportunity to join the backlog of group commit
		 * followers; this can significantly improve transaction throughput,
		 * at the risk of increasing transaction latency.
		 *
		 * We do not sleep if enableFsync is not turned on, nor if there are
		 * fewer than CommitSiblings other backends with active transactions.
		 */
		if (CommitDelay > 0 && enableFsync &&
			MinimumActiveBackends(CommitSiblings))
		{
			pg_usleep(CommitDelay);

			/*
			 * Re-check how far we can now flush the WAL. It's generally not
			 * safe to call WaitXLogInsertionsToFinish while holding
			 * WALWriteLock, because an in-progress insertion might need to
			 * also grab WALWriteLock to make progress. But we know that all
			 * the insertions up to insertpos have already finished, because
			 * that's what the earlier WaitXLogInsertionsToFinish() returned.
			 * We're only calling it again to allow insertpos to be moved
			 * further forward, not to actually wait for anyone.
			 */
			insertpos = WaitXLogInsertionsToFinish(insertpos);
		}

		/* try to write/flush later additions to XLOG as well */
		WriteRqst.Write = insertpos;
		WriteRqst.Flush = insertpos;

		XLogWrite(WriteRqst, false);

		LWLockRelease(WALWriteLock);
		/* done */
		break;
	}
...
} 
```
XLogFlush函数是刷脏WAL的主要函数：
1. 判断需要flush的脏WAL是否已经被其他人flush了，如是，则直接返回
2. 尝试以排他模式获得锁WALWriteLock，不断尝试，直到获得锁为止
3. 拿到锁了，再次检查需要flush的脏WAL是否已经被其他人flush了，如是，则释放WALWriteLock，然后返回（申请锁期间也有可能脏WAL被其他人flush，如果是当然什么也不用做）
4. 等待commit_delay毫秒且并发提交事务数大于commit_siblings，更新wal的写入点，形成组提交  。这一步目前走不到，因为CommitDelay默认为0，相当于没有打开组提交
5. 调用XLogWrite写日志，写完释放WALWriteLock

XLogFlush刷脏wal需要判断当前请求的脏wal是不是已经写了，如果没写，会持有WALWriteLock直到XLogWrite函数日志写入完成。XLogWrite是写wal的具体函数，如写如到哪个page的哪个位置。

回到之前活动会话的等待事件上。IO:WALWrite等待IO比较好理解，LWLOCK:WALWrite怎么去确认是不是问题呢？
从XLogFlush函数逻辑可知，WALWriteLock是pg在写脏wal时申请的排他LWlock（这很好理解，wal的提交信息是顺序写的，只能给排他模式写，不能谁写的快就谁写，不然数据容易出错），是串行的写wal提交信息。
了解这部分逻辑再回去看pg_stat_activity，会发现IO:WALWrite**只有1个**，而LWLOCK:WALWrite有几十个。
虽然不能直接看到LWLOCK的blocking chain，但是我们可以从源码中得知，**LWLOCK:WALWrite在等待IO:WALWrite**。

[官方文档](https://www.postgresql.org/docs/16/wal-configuration.html)有一段关于XLogFlush和调整wal buffer的描述：
>Normally, WAL buffers should be written and flushed by an XLogFlush request, which is made, for the most part, at transaction commit time to ensure that transaction records are flushed to permanent storage. On systems with high WAL output, XLogFlush requests might not occur often enough to prevent XLogInsertRecord from having to do writes. On such systems one should increase the number of WAL buffers by modifying the wal_buffers parameter. When full_page_writes is set and the system is very busy, setting wal_buffers higher will help smooth response times during the period immediately following each checkpoint.

正常情况下，wal buffer会被XLogFlush flush，例如事务提交写wal日志到磁盘上。如果wal日志量很大，但是XLogFlush触发不频繁（也就是全是大事务），就需要XLogInsertRecord写没有提交的wal record，也就是说wal_buffer不够用了，此时增大wal_buffer会稍微对系统的响应时间有帮助。

>There are two commonly used internal WAL functions: XLogInsertRecord and XLogFlush. XLogInsertRecord is used to place a new record into the WAL buffers in shared memory. If there is no space for the new record, XLogInsertRecord will have to write (move to kernel cache) a few filled WAL buffers

结合XLogInsertRecord函数的一段描述:
```c
	 * We have now done all the preparatory work we can without holding a
	 * lock or modifying shared state. From here on, inserting the new WAL
	 * record to the shared WAL buffer cache is a two-step process:
	 *
	 * 1. Reserve the right amount of space from the WAL. The current head of
	 *	  reserved space is kept in Insert->CurrBytePos, and is protected by
	 *	  insertpos_lck.
	 *
	 * 2. Copy the record to the reserved WAL space. This involves finding the
	 *	  correct WAL buffer containing the reserved space, and copying the
	 *	  record in place. This can be done concurrently in multiple processes.
```
XLogInsertRecord函数是用来将新的wal record到WAL buffer中的。
1. 写入需要保留一定量的空间
2. 拷贝wal record到保留的wal空间（应指的是wal buffer中的保留空间）。**多个进程可并行执行**

wal record拷贝到wal buffer是可以并行执行的。这很难称为瓶颈，因为是内存拷贝还有并行。
而XLogFlush函数就不是了，XLogFlush写入的时候会一直持有一个排他LWlock。所以，在这种并发高的小事务场景中，提高wal buffer理论上效果不会太理想。

至此，可以排除wal_buffers内存调整，把关注点放在IO上。再看pg_stat_activity的IO类相关等待个数：
```sql
DataFileRead	4
DataFileExtend	1
WALWrite		1
WALRead			1
```
insert value慢只持续了不到1分钟时间，平时没有异常。但是从平时的会话信息上看IO类的WALWrite等待基本都在
```sql
  pid  | usename  |          xact_start           |         state_change          |  wait_event   | wait_event_type | state  |                                                                                  partofquery
-------+----------+-------------------------------+-------------------------------+---------------+-----------------+--------+--------------------------------------------------------------
  72668 | lzluser11 | 2024-05-23 09:32:20.828394+08 | 2024-05-23 09:32:20.82841+08  | WALWrite      | IO              | active | insert into table1(                                                                                                                                            +
  77215 | lzluser11 | 2024-05-23 09:33:01.342541+08 | 2024-05-23 09:33:01.342552+08 | WALWrite      | IO              | active | insert into table1                                                                                                                                          +
  94904 | lzluser11 | 2024-05-23 09:34:32.442309+08 | 2024-05-23 09:34:32.442323+08 | WALWrite      | IO              | active | insert into table1                                                                                                                                          +
  88024 | lzluser11 | 2024-05-23 09:36:28.779086+08 | 2024-05-23 09:36:28.779311+08 | WALWrite      | IO              | active | UPDATE table2 SET                                                                                                                                              +
 103236 | lzluser11 | 2024-05-23 09:37:04.144283+08 | 2024-05-23 09:37:04.144302+08 | WALWrite      | IO              | active | insert into table1                                                                                                                                          +
  47342 | lzluser11 | 2024-05-23 09:37:09.192683+08 | 2024-05-23 09:37:09.192699+08 | WALWrite      | IO              | active | insert into table1                                                                                                                                          +
  75399 | lzluser11 | 2024-05-23 09:45:30.743023+08 | 2024-05-23 09:45:30.743024+08 | WALWrite      | IO              | active | update table1                                                                                                                                               +
 221993 | lzluser11 | 2024-05-23 09:46:16.184532+08 | 2024-05-23 09:46:16.184541+08 | WALWrite      | IO              | active | insert into table1   
```
然而检查当时IO性能，写入15M/s并不高，与其他时间段相比甚至比较低，w_await同样很低
```c
Device:         rrqm/s   wrqm/s     r/s     w/s    rkB/s    wkB/s avgrq-sz avgqu-sz   await r_await w_await  svctm  %util
dm-322            0.00     0.00  187.00 1515.00  3572.00 15344.00    22.23     2.05    1.20    9.39    0.18   0.15  25.70
```
没有强有力的证据显示是存储性能问题。

目前来看应是瞬时并发insert value小事务，对flush wal时的锁争用。可以排除以下选项:
1. 并发小事务，不需要[调整wal buffer](https://www.postgresql.org/docs/16/wal-configuration.html)
2. wal日志量不大，不需要开启[日志压缩](https://dba.stackexchange.com/questions/338319/postgres-walwrite-waits-whats-the-bottleneck)
3. FPI不多，不需要调整checkpoint
4. IO压力不大，不需要[提升IO性能](https://docs.dbmarlin.com/docs/kb/wait-events/postgresql/walwritelock/)

至少可以有如下优化:
1. 开启数据库组提交（怕背锅可不调整，需要再测试）
2. 业务单个语句insert value语句合并提交，减少WALWriteLock锁争用

