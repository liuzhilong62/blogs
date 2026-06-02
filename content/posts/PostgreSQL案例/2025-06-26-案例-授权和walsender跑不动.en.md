---
title: "Case: GRANT Authorization Causes Walsender to Hang"
date: 2025-06-26
categories: [PostgreSQL Cases]
description: "Analysis of GRANT authorization causing walsender to freeze: massive pg_class changes from bulk GRANT produce huge numbers of invalidation messages; logical decoding stalls due to pathman plugin's slow hash table traversal during invalidation processing"
---

## Symptoms

The walsender's LSN stopped advancing. The stack trace showed it was stuck in pathman's `invalidate_psin_entries_using_relid`, with the relid constantly changing and the walsender CPU pegged at 100%.

```c
pstack 121327
#0  hash_seq_search (status=status@entry=0x7fffaadf8330) at dynahash.c:1441
#1  0x00002ba3b40ec728 in invalidate_psin_entries_using_relid (relid=relid@entry=42319501) at src/relation_info.c:251
#2  0x00002ba3b40ecb3d in forget_status_of_relation (relid=relid@entry=42319501) at src/relation_info.c:232
#3  0x00002ba3b40fcc96 in pathman_relcache_hook (arg=<optimized out>, relid=42319501) at src/hooks.c:934
#4  0x000000000087168a in LocalExecuteInvalidationMessage (msg=0x3a391c8) at inval.c:595
#5  0x000000000071d50e in ReorderBufferExecuteInvalidations (rb=0x1b63ff8, txn=0x1be5f58, txn=0x1be5f58) at reorderbuffer.c:2238
#6  ReorderBufferCommit (rb=0x1b63ff8, xid=xid@entry=4285897514, commit_lsn=405674661986920, end_lsn=<optimized out>, commit_time=commit_time@entry=799377897828299, origin_id=origin_id@entry=0, origin_lsn=origin_lsn@entry=0) at reorderbuffer.c:1819
#7  0x0000000000712d18 in DecodeCommit (xid=4285897514, parsed=0x7fffaadf8630, buf=0x7fffaadf87f0, ctx=0x1a359e8) at decode.c:637
#8  DecodeXactOp (ctx=0x1a359e8, buf=buf@entry=0x7fffaadf87f0) at decode.c:245
#9  0x00000000007130b2 in LogicalDecodingProcessRecord (ctx=0x1a359e8, record=0x1a35c80) at decode.c:114
#10 0x0000000000733662 in XLogSendLogical () at walsender.c:2885
#11 0x0000000000735942 in WalSndLoop (send_data=send_data@entry=0x733620 <XLogSendLogical>) at walsender.c:2287
#12 0x0000000000736692 in StartLogicalReplication (cmd=0x1846c68) at walsender.c:1213
#13 exec_replication_command (cmd_string=cmd_string@entry=0x181a288 "START_REPLICATION SLOT \"lzl_logical_rep\" LOGICAL 170F5/7C3EAE78 (\"proto_version\" '1', \"publication_names\" 'lzl_logical_rep')") at walsender.c:1640
#14 0x0000000000774e91 in PostgresMain (argc=<optimized out>, argv=argv@entry=0x1866478, dbname=0x18662b8 "lzldb", username=<optimized out>) at postgres.c:4325
#15 0x0000000000485989 in BackendRun (port=<optimized out>, port=<optimized out>) at postmaster.c:4526
#16 BackendStartup (port=0x18635b0) at postmaster.c:4210
#17 ServerLoop () at postmaster.c:1739
#18 0x0000000000702f08 in PostmasterMain (argc=argc@entry=3, argv=argv@entry=0x1814da0) at postmaster.c:1412
#19 0x000000000048660a in main (argc=3, argv=0x1814da0) at main.c:210

## Second execution, same stack, different relid
pstack 121327
#0  hash_seq_search (status=status@entry=0x7fffaadf8330) at dynahash.c:1441
#1  0x00002ba3b40ec728 in invalidate_psin_entries_using_relid (relid=relid@entry=26560221) at src/relation_info.c:251
#2  0x00002ba3b40ecb3d in forget_status_of_relation (relid=relid@entry=26560221) at src/relation_info.c:232
#3  0x00002ba3b40fcc96 in pathman_relcache_hook (arg=<optimized out>, relid=26560221) at src/hooks.c:934
#4  0x000000000087168a in LocalExecuteInvalidationMessage (msg=0x39f1f68) at inval.c:595
...
```

## Analysis

The changing relid showed that the walsender was still running, not dead. The LSN was not advancing, so we analyzed the LSN position to see what the transaction was doing.

If the slot information was still available, we could look up the restart LSN via the slot view to find the WAL position. If not, we could use the LSN from the stack trace to identify the WAL log.

Using `pg_waldump` to inspect WAL log entries, filtering by xid:

```shell
rmgr: Heap        len (rec/tot):    961/   961, tx: 4285897514, lsn: 170F5/7DFE3470, prev 170F5/7DFE3430, desc: UPDATE+INIT off 2 xmax 4285897514 flags 0x00 ; new off 1 xmax 0, blkref #0: rel 1663/17662/1259 blk 8443, blkref #1: rel 1663/17662/1259 blk 7327

...
rmgr: Transaction len (rec/tot): 1778325/1778325, tx: 4285897514, lsn: 170F5/7E1F4268, prev 170F5/7E1F4220, desc: COMMIT 2025-05-01 09:24:57.828299 CST; inval msgs: catcache 22 catcache 22 catcache 22 catcache 22 catcache 50 catcache 49 catcache 50 catcache 49 catcache 50 catcache 49 catcache 50 catcache 49 catcache 50 catcache 49 catcache 50 
...
 relcache 48813261 relcache 48813255 relcache 51030741 relcache 48813252 relcache 50737247 relcache 48813246 relcache 48813243 relcache 48813237 relcache 50737241 relcache 48813234 relcache 48813224 relcache 49379811 relcache 48813216 relcache 48813210 relcache 45452775
```

The transaction for `rel 1663/17662/1259` had 180,000 records. The last record was inval msgs: ~70,000 catcache entries and ~30,000 relcache entries.

`rel 1663/17662/1259` is `pg_class`. Querying by xmin reveals the affected tables and commit time:

```sql
select xmin,xmax,pg_xact_commit_timestamp(xmin),relname from pg_class where xmin='4285897514'::xid order by relname desc ;
    xmin    | xmax |   pg_xact_commit_timestamp    |                   relname                   
------------+------+-------------------------------+---------------------------------------------
 4285897514 |    0 | 2025-05-01 09:24:57.828299+08 | v$session
 4285897514 |    0 | 2025-05-01 09:24:57.828299+08 | tmp_20230801_id_seq
 4285897514 |    0 | 2025-05-01 09:24:57.828299+08 | tmp_20230801
 4285897514 |    0 | 2025-05-01 09:24:57.828299+08 | test_param
 4285897514 |    0 | 2025-05-01 09:24:57.828299+08 | test_20240105
 ...
 
 select count(*) from pg_class where xmin='4285897514'::xid ;
 count 
-------
 18523

 select count(*) from pg_class ;
 count  
--------
 139138
```

Checking the pglog by timestamp:

```shell
2025-05-01 09:24:59.837 CST,"postgres","lzldb",61418,"[local]",6812cd65.efea,3,"DO",2025-05-01 09:24:53 CST,549/0,0,LOG,00000,"duration: 6036.275 ms  statement:     
...
                    EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO r_lzldbdata_qry';
...
                END;
                $$",,,,,,,,,"psql","client backend"
```

We can basically confirm that the GRANT operation was the culprit. GRANT updates `relacl` in `pg_class`, and at least 18,000 relations had their permissions updated. Updates to `pg_class` trigger invalidation messages, and the massive number of invalidation messages were being processed slowly in the walsender process.

## Reproduction

```sql
-- Create a logical replication slot, any kind will do
select pg_create_logical_replication_slot('logical_test','test_decoding');
pg_recvlogical -h 127.0.0.1 -p 7997 -d lzldb -U repuser --slot=logical_test --start -f recv.sql &

-- Create many tables
DO $$
BEGIN
    FOR i IN 1..20000 LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS table_%s ( 
                col1 varchar(10)
            )', 
            lpad(i::text, 5, '0')  -- Generate 5-digit numbered table names
        );
    END LOOP;
END $$;

-- Single GRANT
grant select on all tables in schema public to r_lzldb_qry;
```

```sql
-- Perfectly reproduced
postgres@lzlhost:~/lzl/grant]$ pstack 172862
#0  hash_seq_search (status=status@entry=0x7ffd664be280) at dynahash.c:1444
#1  0x00002ad31235e728 in invalidate_psin_entries_using_relid (relid=relid@entry=1002857) at src/relation_info.c:251
#2  0x00002ad31235eb3d in forget_status_of_relation (relid=relid@entry=1002857) at src/relation_info.c:232
#3  0x00002ad31236ec96 in pathman_relcache_hook (arg=<optimized out>, relid=1002857) at src/hooks.c:934
#4  0x000000000087168a in LocalExecuteInvalidationMessage (msg=0x2ad3c3f61a88) at inval.c:595
#5  0x000000000071d50e in ReorderBufferExecuteInvalidations (rb=0x17e5698, txn=0x180d698, txn=0x180d698) at reorderbuffer.c:2238


[postgres@lzlhost:~/lzl/grant]$ pstack 172862
#0  0x0000000000891d0c in hash_seq_search (status=status@entry=0x7ffd664be280) at dynahash.c:1441
#1  0x00002ad31235e728 in invalidate_psin_entries_using_relid (relid=relid@entry=1011110) at src/relation_info.c:251
#2  0x00002ad31235eb3d in forget_status_of_relation (relid=relid@entry=1011110) at src/relation_info.c:232
#3  0x00002ad31236ec96 in pathman_relcache_hook (arg=<optimized out>, relid=1011110) at src/hooks.c:934


-- relid keeps changing
-- CPU pegged at 100%:
ps -eo pid,%cpu,%mem|grep 172862
172862 99.3  0.0

-- Takes about 2 hours to catch up
```

## Accelerating Walsender by Removing Pathman

Since the database wasn't actually using pathman partitioned tables but had the extension installed, we tried bypassing the pathman hook to speed up walsender processing.

```sql
drop extension pg_pathman;
grant update on all tables in schema public to r_lzldb_upd;

[postgres@lzlhost~/lzl/grant]$  pstack 133460
#0  hash_seq_search (status=status@entry=0x7ffe292d5c90) at dynahash.c:1418
#1  0x000000000087f228 in RelfilenodeMapInvalidateCallback (arg=<optimized out>, relid=1034036) at relfilenodemap.c:64
#2  0x000000000087168a in LocalExecuteInvalidationMessage (msg=0x2b9699795768) at inval.c:595
#3  0x000000000071d50e in ReorderBufferExecuteInvalidations (rb=0x195a358, txn=0x1a6ff38, txn=0x1a6ff38) at reorderbuffer.c:2238
#4  ReorderBufferCommit (rb=0x195a358, xid=xid@entry=328684387, commit_lsn=8016890875224, end_lsn=<optimized out>, commit_time=commit_time@entry=799851538975691, origin_id=origin_id@entry=0, origin_lsn=origin_lsn@entry=0) at reorderbuffer.c:1819

## Completed within 20 seconds
```

Even without commenting out `pg_pathman` from `shared_preload_libraries`, there was a dramatic improvement — walsender went from 2 hours to 20 seconds.

This seemed odd at first — without commenting `shared_preload_libraries`, the hook should still run. Source analysis revealed the reason: the very first step of the hook checks for the pathman config table; if it doesn't exist, it skips pathman's invalidation logic entirely, so execution completes quickly:

```c
/*
 * Invalidate PartRelationInfo cache entry if needed.
 */
void
pathman_relcache_hook(Datum arg, Oid relid)
{
	Oid pathman_config_relid;

	/* See cook_partitioning_expression() */
	if (!pathman_hooks_enabled)
		return;

	if (!IsPathmanReady())
		return;

...

	/*
	 * Invalidation event for PATHMAN_CONFIG table (probably DROP EXTENSION).
	 * Digging catalogs here is expensive and probably illegal, so we take
	 * cached relid. It is possible that we don't know it atm (e.g. pathman
	 * was disabled). However, in this case caches must have been cleaned
	 * on disable, and there is no DROP-specific additional actions.
	 */
	pathman_config_relid = get_pathman_config_relid(true);
	if (relid == pathman_config_relid)
	{
		delay_pathman_shutdown();
	}

	/* Invalidation event for some user table */
	else if (relid >= FirstNormalObjectId)
	{
		/* Invalidate PartBoundInfo entry if needed */
		forget_bounds_of_rel(relid);

		/* Invalidate PartStatusInfo entry if needed */
		forget_status_of_relation(relid);

		/* Invalidate PartParentInfo entry if needed */
		forget_parent_of_partition(relid);
	}
}
```

`get_pathman_config_relid` fetches the pathman_config table. `drop extension pg_pathman` removes the pathman_config table from the database, so the source code never enters the `forget_*` logic.

There are other ways to accelerate walsender processing: setting `pg_pathman.enable=off` causes `IsPathmanReady()` to return false and bail out immediately. Or, most directly, comment out `pg_pathman` from `shared_preload_libraries` and restart the instance (this is instance-level, not database-level).

## Improvements in PG14

PG14.0 release notes:

> Allow logical decoding to more efficiently process cache invalidation messages (Dilip Kumar)
> This allows logical decoding to work efficiently in presence of a large amount of DDL.

https://www.postgresql.org/docs/release/14.0/

Patch:

<https://git.postgresql.org/gitweb/?p=postgresql.git;a=commitdiff;h=d7eb52d71>

Comment from PG14's `ReorderBufferAddInvalidations`:

> We require to record it in form of the change so that we can execute only the required invalidations instead of executing all the invalidations on each CommandId increment.

Comparing PG14 vs PG13, `ReorderBufferCommit` underwent a major rewrite.

In PG13, transaction processing logic was directly in the `ReorderBufferCommit` function:

```c
				case REORDER_BUFFER_CHANGE_INTERNAL_COMMAND_ID:
					Assert(change->data.command_id != InvalidCommandId);

					if (command_id < change->data.command_id)
					{
						command_id = change->data.command_id;

						if (!snapshot_now->copied)
						{
							/* we don't use the global one anymore */
							snapshot_now = ReorderBufferCopySnap(rb, snapshot_now,
																txn, command_id);
						}

						snapshot_now->curcid = command_id;

						TeardownHistoricSnapshot(false);
						SetupHistoricSnapshot(snapshot_now, txn->tuplecid_hash);

						/*
						 * Every time the CommandId is incremented, we could
						 * see new catalog contents, so execute all
						 * invalidations.
						 */
						ReorderBufferExecuteInvalidations(rb, txn);
					}
```

In PG14, the main logic moved to `ReorderBufferReplay` -> `ReorderBufferProcessTXN`.

`ReorderBufferProcessTXN` introduced a new `case REORDER_BUFFER_CHANGE_INVALIDATION` branch to execute invalidations from the reorder buffer:

```c
				case REORDER_BUFFER_CHANGE_INVALIDATION:
					/* Execute the invalidation messages locally */
					ReorderBufferExecuteInvalidations(
												  change->data.inval.ninvalidations,
												  change->data.inval.invalidations);
					break;
```

The logic after `ReorderBufferExecuteInvalidations` is largely the same. The main differences between PG13 and PG14's `ReorderBufferCommit`:

- `ReorderBufferCommit` is no longer the primary transaction processing function; the call stack is deeper
- A new `case REORDER_BUFFER_CHANGE_INVALIDATION` branch was added, separated from `REORDER_BUFFER_CHANGE_INTERNAL_COMMAND_ID`, to handle invalidations independently
- The per-command_id invalidation processing logic was removed

## Root Cause and Solutions

The root cause of the walsender hang was a bulk GRANT operation that updated many rows in `pg_class`, triggering a massive number of invalidation messages. A statement like `GRANT privs ON ALL TABLES IN SCHEMA public TO role1` executes as multiple commands within a single transaction in PostgreSQL. In PG13, logical replication processes invalidation messages per-command, invoking each hook's inval hash table processing. In this scenario, pathman's hook was particularly slow at processing the inval hash table, causing replication lag.

Conditions for pathman-induced slowness (all must apply):

- PG13 or earlier
- Bulk GRANT
- pathman extension installed (whether used or not)
- Logical replication slot active

Even after removing pathman, significant CPU time was still spent in functions like `RelfilenodeMapInvalidateCallback`. In PG13 testing, the processing time difference between with and without pathman was hours vs. minutes.

Other untested but community-mentioned scenarios (all must apply):

- PG13 or earlier
- Bulk DDL / TRUNCATE / DCL / DROP PUBLICATION
- Logical replication slot active

Short-term fix: If pathman tables are not in use, drop the extension or unload the pathman shared library; restart the replication slot.

Long-term fix: Upgrade to PG14+ (tested — extremely fast with no lag).

### 

## References

<https://www.postgresql.org/message-id/flat/17716-1fe42e7b44fc2f25%40postgresql.org>

<https://git.postgresql.org/gitweb/?p=postgresql.git;a=commitdiff;h=d7eb52d71>
