---
title: "Case Study: Analyzing Occasional Slow INSERT VALUES"
date: 2024-08-12
categories: [PostgreSQL案例]
description: "Analyzing why INSERT VALUES occasionally became slow. Through wait event analysis, the root cause was identified as WALWrite lock contention, where WAL flushing became the bottleneck under heavy concurrent writes."
---


The business team reported that INSERT VALUES occasionally became slow. By the time I checked the active sessions, the slow write problem had already subsided.

Later, I discovered that the slow write problem lasted less than half a minute, with INSERT VALUES taking 1-2 seconds. I wrote a script to capture active session information and managed to get the session data:

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

The most abnormal wait event was WALWrite with 40 sessions.

Two of the WALWrite-waiting sessions looked like this:

```sql
  pid  | usename  |          xact_start           |         state_change          |  wait_event   | wait_event_type | state  |                                                                                  partofquery
-------+----------+-------------------------------+-------------------------------+---------------+-----------------+--------+--------------------------------------------------------------
 144955 | lzluser11 | 2024-05-23 07:58:27.516574+08 | 2024-05-23 07:58:27.516588+08 | WALWrite       | LWLock          | active | insert into table1( 
 179869 | lzluser11 | 2024-05-23 07:58:28.116371+08 | 2024-05-23 07:58:28.116386+08 | WALWrite       | IO              | active | insert into table1( 
```

Let's search the source code for WALWrite-related content:

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

When WAL is written from WAL buffers to disk, the WALWriteLock must be held.

When a backend flushes WAL while holding WALWriteLock, it can also flush the commit records of other backends. Those other backends need to wait for this flush to finish, but they don't need to acquire the lock afterward. If their WAL has been flushed, they can return directly (rather than flushing WAL again).

`XLogFlush` is extremely important. The key code in `XLogFlush` is in the for loop:

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

The `XLogFlush` function is the main function for flushing dirty WAL:

1. Check if the dirty WAL that needs to be flushed has already been flushed by someone else. If so, return directly.
2. Try to acquire the lock `WALWriteLock` in exclusive mode, retrying continuously until the lock is acquired.
3. Once the lock is acquired, check again if the dirty WAL that needs to be flushed has already been flushed by someone else. If so, release `WALWriteLock` and return (during the lock acquisition wait, someone else might have flushed the dirty WAL — if so, there's nothing to do).
4. Wait for `commit_delay` milliseconds, and if the number of concurrent committing transactions exceeds `commit_siblings`, update the WAL write position to form a group commit. This step currently doesn't apply because `CommitDelay` defaults to 0, effectively meaning group commit is not enabled.
5. Call `XLogWrite` to write the log, release `WALWriteLock` after completion.

`XLogFlush` for flushing dirty WAL needs to check whether the currently requested dirty WAL has already been written. If not, it will hold `WALWriteLock` until the `XLogWrite` function completes writing the log. `XLogWrite` is the specific function for writing WAL, such as writing to which position on which page.

Returning to the wait events from active sessions, the `IO:WALWrite` wait is relatively easy to understand, but how do we confirm whether `LWLock:WALWrite` is a problem?

From the `XLogFlush` function logic, we know that `WALWriteLock` is an exclusive LWLock that PostgreSQL acquires when writing dirty WAL (this makes sense — WAL commit information is written sequentially and can only be written in exclusive mode; you can't let whoever writes fastest write first, as that could easily corrupt data). It's a serialized write of WAL commit information.

Understanding this part of the logic, looking back at `pg_stat_activity`, we can see that there was **only 1** `IO:WALWrite`, while there were dozens of `LWLock:WALWrite` waits.

Although we can't directly see the LWLock blocking chain, we can infer from the source code that **LWLock:WALWrite is waiting on IO:WALWrite**.

The [official documentation](https://www.postgresql.org/docs/16/wal-configuration.html) has a section about `XLogFlush` and adjusting WAL buffers:

> Normally, WAL buffers should be written and flushed by an XLogFlush request, which is made, for the most part, at transaction commit time to ensure that transaction records are flushed to permanent storage. On systems with high WAL output, XLogFlush requests might not occur often enough to prevent XLogInsertRecord from having to do writes. On such systems one should increase the number of WAL buffers by modifying the wal_buffers parameter. When full_page_writes is set and the system is very busy, setting wal_buffers higher will help smooth response times during the period immediately following each checkpoint.

Under normal circumstances, WAL buffers are flushed by `XLogFlush`, for example during transaction commit to write WAL logs to disk. If the WAL log volume is large but `XLogFlush` is not triggered frequently enough (meaning mostly large transactions), `XLogInsertRecord` needs to write uncommitted WAL records — meaning the WAL buffer is insufficient. In this case, increasing `wal_buffers` may slightly help with system response time.

> There are two commonly used internal WAL functions: XLogInsertRecord and XLogFlush. XLogInsertRecord is used to place a new record into the WAL buffers in shared memory. If there is no space for the new record, XLogInsertRecord will have to write (move to kernel cache) a few filled WAL buffers

Combined with a description from the `XLogInsertRecord` function:

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

The `XLogInsertRecord` function is used to place new WAL records into the WAL buffer:

1. Writing requires reserving a certain amount of space.
2. Copy the WAL record to the reserved WAL space (presumably the reserved space in the WAL buffer). **Multiple processes can execute this in parallel.**

Copying WAL records to the WAL buffer can be done in parallel. This is unlikely to be a bottleneck since it's an in-memory copy with parallelism.

But `XLogFlush` is different — it holds an exclusive LWLock throughout the write. So, in scenarios with high concurrency and small transactions, increasing WAL buffers theoretically won't be very effective.

At this point, we can rule out `wal_buffers` memory tuning and focus our attention on I/O. Looking at the I/O-related wait counts in `pg_stat_activity`:

```sql
DataFileRead	4
DataFileExtend	1
WALWrite		1
WALRead			1
```

The INSERT VALUES slowness lasted less than a minute and was not normally present. However, looking at the normal session information, I/O class WALWrite waits were almost always there:

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

However, checking the I/O performance at that time, writing 15 MB/s was not high — in fact, it was relatively low compared to other time periods, and `w_await` was also very low:

```c
Device:         rrqm/s   wrqm/s     r/s     w/s    rkB/s    wkB/s avgrq-sz avgqu-sz   await r_await w_await  svctm  %util
dm-322            0.00     0.00  187.00 1515.00  3572.00 15344.00    22.23     2.05    1.20    9.39    0.18   0.15  25.70
```

There was no strong evidence pointing to a storage performance issue.

At present, it appears to be transient lock contention during concurrent INSERT VALUES small transactions when flushing WAL. We can rule out the following options:

1. Concurrent small transactions — no need to [adjust WAL buffers](https://www.postgresql.org/docs/16/wal-configuration.html)
2. WAL log volume is not large — no need to enable [log compression](https://dba.stackexchange.com/questions/338319/postgres-walwrite-waits-whats-the-bottleneck)
3. Not many FPIs (Full Page Images) — no need to adjust checkpoint
4. I/O pressure is not high — no need to [improve I/O performance](https://docs.dbmarlin.com/docs/kb/wait-events/postgresql/walwritelock/)

At minimum, the following optimizations can be made:

1. Enable database group commit (can be deferred if concerned about risk; testing required)
2. Batch multiple INSERT VALUES statements at the application level to reduce WALWriteLock contention

