---
title: "Case Study: Logical Replication Deadlocks Checkpoint, Walsender, and Backup"
date: 2024-08-12
categories: [PostgreSQL案例]
description: "Troubleshooting a cascading hang where logical replication walsender exhausts memory, triggers replication_slot_io waits, and blocks both checkpoint and backup processes"
---

## Problem Symptoms

The backup process (`pg_start_backup()`) was blocked by the checkpointer, and the checkpointer was blocked by the logical replication walsender. The database was still serving queries, but backup, checkpoint, and logical replication were all completely hung.

Two processes in `pg_stat_activity` showed an unusual wait event: `replication_slot_io`.

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

One walsender and one checkpointer. Both were started on April 2. Let's check the walsender 173038 logs:

```shell
--repuser log
2024-04-02 11:40:07.750 CST,,,173038,"30.88.75.58:37623",660b7e17.2a3ee,1,"",2024-04-02 11:40:07 CST,,0,LOG,00000,"connection received: host=30.88.75.58 port=37623",,,,,,,,,""
2024-04-02 11:40:07.756 CST,"repuser","lzldb",173038,"30.88.75.58:37623",660b7e17.2a3ee,2,"authentication",2024-04-02 11:40:07 CST,32/30,0,LOG,00000,"replication connection authorized: user=repuser",,,,,,,,,""
2024-04-02 11:40:07.765 CST,"repuser","lzldb",173038,"30.88.75.58:37623",660b7e17.2a3ee,3,"idle",2024-04-02 11:40:07 CST,32/0,0,LOG,00000,"starting logical decoding for slot ""pg_lzldb_lzldb_ora_pgdb_pgdb""","Streaming transactions committing after 4263/42E6EF88, reading WAL from 4263/41DAEBD0.",,,,,,,,"PostgreSQL JDBC Driver"
2024-04-02 11:40:07.765 CST,"repuser","lzldb",173038,"30.88.75.58:37623",660b7e17.2a3ee,4,"idle",2024-04-02 11:40:07 CST,32/0,0,LOG,00000,"logical decoding found consistent point at 4263/41DAEBD0","There are no running transactions.",,,,,,,,"PostgreSQL JDBC Driver"
```

Walsender 173038 only shows startup information. After that, no more log output — it likely hung from the very start.

Scrolling back a bit, we can find an earlier walsender for the same replication slot (different PID, same slot name):

```shell
--84918 earlier startup logs
2024-04-02 11:30:07.498 CST,,,84918,"30.88.75.58:54898",660b7bbf.14bb6,1,"",2024-04-02 11:30:07 CST,,0,LOG,00000,"connection received: host=30.88.75.58 port=54898",,,,,,,,,""
2024-04-02 11:30:07.504 CST,"repuser","lzldb",84918,"30.88.75.58:54898",660b7bbf.14bb6,2,"authentication",2024-04-02 11:30:07 CST,30/3,0,LOG,00000,"replication connection authorized: user=repuser",,,,,,,,,""
2024-04-02 11:30:07.514 CST,"repuser","lzldb",84918,"30.88.75.58:54898",660b7bbf.14bb6,3,"idle",2024-04-02 11:30:07 CST,30/0,0,LOG,00000,"starting logical decoding for slot ""pg_lzldb_lzldb_ora_pgdb_pgdb""","Streaming transactions committing after 4263/41DADE38, reading WAL from 4263/358F1340.",,,,,,,,"PostgreSQL JDBC Driver"
2024-04-02 11:30:07.516 CST,"repuser","lzldb",84918,"30.88.75.58:54898",660b7bbf.14bb6,4,"idle",2024-04-02 11:30:07 CST,30/0,0,LOG,00000,"logical decoding found consistent point at 4263/358F1340","There are no running transactions.",,,,,,,,"PostgreSQL JDBC Driver"

2024-04-02 11:36:07.061 CST,"repuser","lzldb",86630,"30.88.75.58:45227",660b7bca.15266,5,"idle",2024-04-02 11:30:18 CST,30/0,0,ERROR,XX000,"could not write to file ""pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"": Cannot allocate memory",,,,,,,,,"PostgreSQL JDBC Driver"
2024-04-02 11:36:40.151 CST,"repuser","lzldb",86630,"30.88.75.58:45227",660b7bca.15266,6,"idle",2024-04-02 11:30:18 CST,,0,LOG,00000,"disconnection: session time: 0:06:21.760 user=repuser database=lzldb host=30.88.75.58 port=45227",,,,,,,,,"PostgreSQL JDBC Driver"
```

This replication slot was also started at 11:30:07. Six minutes later, it failed to write `state.tmp` due to memory exhaustion.

The checkpointer process 12729 also reported the same `state.tmp` error — `"pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"": File exists"`. This error appeared ~30 seconds after the replication slot error:

```shell
--checkpoint log
2024-04-02 11:36:39.925 CST,,,12729,,660b7a17.31b9,4,,2024-04-02 11:23:03 CST,,0,LOG,58P02,"could not create file ""pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"": File exists",,,,,,,,,""
2024-04-02 11:36:40.151 CST,,,12729,,660b7a17.31b9,5,,2024-04-02 11:23:03 CST,,0,LOG,00000,"checkpoint complete: wrote 334 buffers (0.0%); 0 WAL file(s) added, 0 removed, 0 recycled; write=0.108 s, sync=0.082 s, total=217.083 s; sync files=139, longest=0.004 s, average=0.000 s; distance=2295 kB, estimate=2295 kB",,,,,,,,,""
2024-04-02 11:48:03.414 CST,,,12729,,660b7a17.31b9,6,,2024-04-02 11:23:03 CST,,0,LOG,00000,"checkpoint starting: time",,,,,,,,,""
```

After this, the checkpointer produced no more log output — it hung, just like the walsender.

Searching for `pg_replslot/pg_lzldb_lzldb_ora_pgdb_pgdb/state.tmp"": File exists"` quickly leads to a community thread: <https://www.postgresql.org/message-id/14b3454f-2d68-c637-68e4-2b42ff976168%40postgrespro.ru>

The actual fix landed in [PG 12.3](https://www.postgresql.org/docs/release/12.3/):
> Ensure that a replication slot's io_in_progress_lock is released in failure code paths (Pavan Deolasee)
> This could result in a walsender later becoming stuck waiting for the lock.

## Deep Dive

We found the bug, but several questions remain:

- Why did the walsender and checkpointer hang?
- Who is blocking whom — the walsender or the checkpointer?
- How was this triggered?
- What are the solutions?

### Source Code Analysis

Current version: 11.5.

Pstack of both processes:

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
#17 0x000000000047e481 in BackendRun (port=0x20eda0) at postmaster.c:4358
#18 BackendStartup (port=0x20eda0) at postmaster.c:4030
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

The key observation is the `LWLockAcquire` frame. Both the walsender and the checkpointer are trying to acquire the **same LWLOCK address in exclusive mode**: `lock=lock@entry=0x2babd8cee5b8, mode=mode@entry=LW_EXCLUSIVE` — waiting indefinitely.

The function right above `LWLockAcquire` is `SaveSlotToPath`.

Looking at the source in `src/backend/replication/slot.c`, the critical function `SaveSlotToPath`:

```c
//SaveSlotToPath stores slot state
static void
SaveSlotToPath(ReplicationSlot *slot, const char *dir, int elevel)
{	//11.5 code
	char		tmppath[MAXPGPATH];
	char		path[MAXPGPATH];
	int			fd;
	ReplicationSlotOnDisk cp;
	bool		was_dirty;
...
	/* and don't do anything if there's nothing to write */
	if (!was_dirty)
		return;
	//Acquire LWLock in exclusive mode at function entry
	LWLockAcquire(&slot->io_in_progress_lock, LW_EXCLUSIVE);

...
	//Note the fd logic — the error matches the second walsender error
	fd = OpenTransientFile(tmppath, O_CREAT | O_EXCL | O_WRONLY | PG_BINARY);
	if (fd < 0)
	{
		ereport(elevel,
				(errcode_for_file_access(),
				 errmsg("could not create file \"%s\": %m",
						tmppath)));
		return;
...
	//The logic for writing to fd — the error matches the first walsender error
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
	LWLockRelease(&slot->io_in_progress_lock);	//Release LWLock at end of function
	}
```

`SaveSlotToPath` acquires `LWLockAcquire` on the slot's `io_in_progress_lock` in `LW_EXCLUSIVE` mode — very similar to the wait event name: `io_in_progress_lock` ↔ `replication_slot_io`.

At the end of the function, `LWLockRelease` releases the lock.

**But in both `if` branches, there is no `LWLockRelease` — the function just returns directly!**

The PostgreSQL log shows "could not create file" for `tmppath`, meaning the code hit one of those two `if` branches — either the **write to state.tmp failed** branch or the **create state.tmp failed** branch.

Let's reconstruct the timeline from the logs:

1. **11:36:07**: Logical replication first error — "could not write to file ... state.tmp". Replication link dies.
2. **11:36:39**: Checkpointer error — "could not create file ... state.tmp". One second later, checkpoint "completes" with 0 dirty buffers, 0 WAL.
3. **11:40:07**: Logical replication starts again. No more output.
4. **11:48:03**: Checkpointer triggers `start` again. No more output.

Important: the first and second logical replication connections belong to **different** walsender PIDs; the first and second checkpoint entries belong to the **same** checkpointer PID.

**Fault mechanism reconstructed:**

1. Logical replication walsender, due to memory pressure, fails to write `state.tmp`, leaving a residual `state.tmp` file behind.
2. The checkpointer, encountering the residual `state.tmp`, enters the `if (fd < 0)` branch in `SaveSlotToPath` after acquiring the LWLock in exclusive mode — and returns **without releasing the LWLock**.
3. A new walsender starts for logical replication and tries to acquire the LWLock at the top of `SaveSlotToPath` — waits indefinitely.
4. The checkpointer triggers a new checkpoint and also tries to acquire the LWLock at the top of `SaveSlotToPath` — waits indefinitely.

With the mechanism clear, the answers follow:

- **Why did the walsender and checkpointer hang?** Residual `state.tmp`. The checkpointer held the LWLock without releasing it. Both walsender and checkpointer wait indefinitely.
- **Who blocks whom?** The checkpointer blocks the walsender.
- **How was it triggered?** The previous walsender exhausted memory, leaving an uncleaned `state.tmp`.
- **Solutions?** Force restart the database.

### Reproduction

For background on PostgreSQL logical replication, refer to: [PG inner workings: Logical Replication](https://blog.csdn.net/qq_40687433/article/details/129291207). Key commands:

```sql
select pg_create_logical_replication_slot('logical_test','test_decoding');
pg_recvlogical -h 127.0.0.1 -p 5558 -d lzldb -U lzl --slot=logical_test --start -f recv.sql &
```

The slot and replication link are ready:

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

Since the problem is caused by `state.tmp`, just `touch` it under `pg_replslot`:

```sql
[postgres@testhost logical_test]$ pwd
/pgdata/lzl/data11/pg_replslot/logical_test
```

`pg_recvlogical` immediately errors:

```sql
 pg_recvlogical: unexpected termination of replication stream: ERROR:  could not create file "pg_replslot/logical_test/state.tmp": File exists
```

Manual `CHECKPOINT` hangs:

```sql
lzldb=# checkpoint;

--hang
```

Now check the walsender and session states:

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

Perfectly reproduced — two `replication_slot_io` wait events.

### PG 12.3 Code Fix

```c
//Here showing 15.3, which has an extra save_errno vs 12.3
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

In **every `if` branch**, `LWLockRelease` is called before returning. This eliminates the logical vulnerability where the LWLock is not released in certain code paths. The code is clearly more robust.

### Solution Analysis

- Deleting `state.tmp` won't help — the LWLock is already held; the file was just the trigger.
- Restarting the replication link or killing the downstream won't help — the checkpointer is the one holding the LWLock.
- The checkpointer cannot be killed directly. The only solution in this state is a **force restart** to perform instance recovery. A normal shutdown is impossible because `CHECKPOINT` is blocked.
- The ultimate fix: upgrade to PG 12.3 or later.

*(I also tried using gdb to call `LWLockRelease` with the LWLock address from pstack — it crashed the test instance immediately. Not recommended.)*

## Summary

Logical replication is one of the most significant feature enhancements in recent PostgreSQL releases. Early versions did have many issues and pitfalls. PostgreSQL's [ambitious logical replication approach](https://blog.csdn.net/qq_40687433/article/details/136405862?spm=1001.2014.3001.5501) shows genuine innovation, and the community continuously refines and strengthens it — nearly every minor release includes many logical replication updates. This case is a real-world example: the logical replication code is clearly becoming more robust.

Logical replication has a lot of depth. Recommended reading: [PG Inner Workings: Logical Replication](https://blog.csdn.net/qq_40687433/article/details/129291207)

