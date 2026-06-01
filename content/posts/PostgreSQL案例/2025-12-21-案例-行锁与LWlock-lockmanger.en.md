---
title: "Case Study: Row Locks and LWLock LockManager"
date: 2025-12-21
categories: [PostgreSQL案例]
description: "Analyzing how high-concurrency updates on the same row cause massive row locks and LWLock LockManager waits, verifying through benchmarks that row locks bypassing the fastpath mechanism is the root cause of increased LWLock contention"
---

## Symptoms

The database showed a large number of row locks and a smaller number of LWLock LockManager waits. CPU was maxed out and active sessions spiked. The blocking PID associated with the locks kept changing, with no obvious long-transaction blocker.
(Imagine high CPU and active sessions.)

The SQL corresponding to the large number of locks was as follows:

```sql
UPDATE lzl_record  SET rc_lzl1= rc_lzl1 + $1, pc_lzl2 = pc_lzl2 + $2, rc_lzl3 = rc_lzl3 + $3 where lzl_id = $4
```



## Analysis

### No Increase in SQL Concurrency Observed

From the correlation between hits and CPU, we can analyze from the SQL hit perspective. That UPDATE SQL accounted for about 80% of activity. The SQL's execution count had not changed, but `blks hit` was clearly abnormal.

We also analyzed metadata access — within snapshots, no metadata tables showed unusually high access.

From the symptom analysis, neither SQL concurrency increase nor metadata anomalies were apparent. The reason for the SQL hit increase wasn't obvious at this point.



### LWLock LockManager Analysis

Since the SQL itself is simple — the `lzl_id` field in the `lzl_record` table is a unique field, meaning the update is done by unique key.

In addition to the large number of explicit locks, the wait events at the scene also included LWLock LockManager.

However, the table is a regular table (not partitioned), with only 4 or 5 indexes on it.

LWLock LockManager is related to not using the fast path. Simple queries and DML can use the fast path:

> Weak relation locks.  SELECT, INSERT, UPDATE, and DELETE must acquire a
> lock on every relation they operate on, as well as various system catalogs
> that can be used internally.  Many DML operations can proceed in parallel
> against the same table at the same time; only DDL operations such as
> CLUSTER, ALTER TABLE, or DROP -- or explicit user action such as LOCK TABLE
> -- will create lock conflicts with the "weak" locks (AccessShareLock,
> RowShareLock, RowExclusiveLock) acquired by DML operations.



So a SELECT/DML accessing no more than 16 relations (including indexes) should be able to use the fast path, and there shouldn't be much LWLock LockManager.

However, DML certainly can't simply use the fast path — fast path handles lock operations entirely locally, but DML must check whether other sessions hold locks on the row and needs to access shared memory. Combined with the fact that this SQL updates by unique field yet still encounters row locks, it must be updating the same row.

From the logs, we could see instances of updating the same row — one row had tens of thousands of lock-waiting updates.

## Benchmark Testing

### Benchmarking Same-Row Updates to Reproduce LWLock LockManager

Given that row locks definitely can't rely solely on the fast path, and knowing that LWLock LockManager degrades database performance, we benchmarked different scenarios.

```
#prompt
Give me a pgbench benchmark script
Table structure: primary key, unique field + unique index, other fields
Update: update by unique field

Benchmark repeated updates on the same row (repeated row-lock updates)
Benchmark random updates on different rows (no row-lock updates)
```

Script omitted. Environment: 20 cores, 96GB RAM.

pgbench commands:

```shell
pgbench -h localhost -p $PGPORT -d lzldb -U dbmgr -f update_same_unique_key.sql  -c 200 -j 32 -T 600 -r -S
pgbench -h localhost -p $PGPORT -d lzldb -U dbmgr -f update_random_unique_key.sql  -c 200 -j 32 -T 600 -r -S
```

Wait events during the benchmark:

```sql
 -- Update same row, 2 typical samples
 usename  | state  |     wait_event      | wait_event_type | cnt 
----------+--------+---------------------+-----------------+-----
 dbmgr    | active | LockManager         | LWLock          | 105
 dbmgr    | active | transactionid       | Lock            |  61
 dbmgr    | active | tuple               | Lock            |  25
 dbmgr    | active | [null]              | [null]          |   8
 dbmgr    | active | WALSync             | IO              |   1
 
  usename  | state  |     wait_event      | wait_event_type | cnt 
----------+--------+---------------------+-----------------+-----
 dbmgr    | active | transactionid       | Lock            | 180
 dbmgr    | active | LockManager         | LWLock          |  18
 dbmgr    | active | tuple               | Lock            |   1
 dbmgr    | active | WALSync             | IO              |   1
```

```sql
-- Update different rows, 2 typical samples
usename  |        state        |     wait_event      | wait_event_type | cnt 
----------+---------------------+---------------------+-----------------+-----
 dbmgr    | active              | [null]              | [null]          | 106
 dbmgr    | idle                | ClientRead          | Client          |  34
 dbmgr    | idle in transaction | ClientRead          | Client          |  25
 dbmgr    | active              | WALWrite            | LWLock          |  21
 dbmgr    | active              | BufferMapping       | LWLock          |   7
 dbmgr    | idle in transaction | [null]              | [null]          |   4
 dbmgr    | idle in transaction | WALWrite            | LWLock          |   2
 
  usename  |        state        |     wait_event      | wait_event_type | cnt 
----------+---------------------+---------------------+-----------------+-----
 dbmgr    | active              | [null]              | [null]          | 117
 dbmgr    | idle                | ClientRead          | Client          |  42
 dbmgr    | idle in transaction | ClientRead          | Client          |  24
 dbmgr    | active              | WALWrite            | LWLock          |  12
 dbmgr    | active              | XactGroupUpdate     | IPC             |   1
 dbmgr    | active              | WALSync             | IO              |   1
 dbmgr    | active              | XactSLRU            | LWLock          |   1
 dbmgr    | active              | BufferContent       | LWLock          |   1
 dbmgr    | active              | ClientRead          | Client          |   1
```

From the wait events, the difference is clear: updating the same row produces LWLock LockManager, sometimes at a high proportion. Updating different rows mostly just waits on CPU. Scenario 1 matches the production situation.

## A Brief Analysis of Row Locks and Fast Path

The lmgr README's explanation of the fast path:

```
Fast Path Locking
-----------------

Fast path locking is a special purpose mechanism designed to reduce the
overhead of taking and releasing certain types of locks which are taken
and released very frequently but rarely conflict.  Currently, this includes
two categories of locks:

(1) Weak relation locks.  SELECT, INSERT, UPDATE, and DELETE must acquire a
lock on every relation they operate on, as well as various system catalogs
that can be used internally.  Many DML operations can proceed in parallel
against the same table at the same time; only DDL operations such as
CLUSTER, ALTER TABLE, or DROP -- or explicit user action such as LOCK TABLE
-- will create lock conflicts with the "weak" locks (AccessShareLock,
RowShareLock, RowExclusiveLock) acquired by DML operations.
```

Conditions for locks that can use the fast path, from `lmgr/lock.c`:

```c
/*
 * The fast-path lock mechanism is concerned only with relation locks on
 * unshared relations by backends bound to a database.  The fast-path
 * mechanism exists mostly to accelerate acquisition and release of locks
 * that rarely conflict.  Because ShareUpdateExclusiveLock is
 * self-conflicting, it can't use the fast-path mechanism; but it also does
 * not conflict with any of the locks that do, so we can ignore it completely.
 */
#define EligibleForRelationFastPath(locktag, mode) \
	((locktag)->locktag_lockmethodid == DEFAULT_LOCKMETHOD && \
	(locktag)->locktag_type == LOCKTAG_RELATION && \
	(locktag)->locktag_field1 == MyDatabaseId && \
	MyDatabaseId != InvalidOid && \
	(mode) < ShareUpdateExclusiveLock)
```

SELECT/DML can use the fast path, but only for `locktype=relation`.

Let's look at the actual lock situation when there's a row lock:

```sql
-- Session 1
begin;
update lzl1 set b='zzz' where a=1;

-- Session 2
begin;
update lzl1 set b='zzz' where a=1;
-- waiting


-- Session 3
 select *  from pg_locks where pid<>(select pg_backend_pid()) order by pid,locktype;
   locktype    | database | relation |  page  | tuple  | virtualxid | transactionid | classid | objid  | objsubid | virtualtransaction |  pid   |       mode       | granted | fastpath 
---------------+----------+----------+--------+--------+------------+---------------+---------+--------+----------+--------------------+--------+------------------+---------+----------
 relation      |  4267681 |  5290151 | [null] | [null] | [null]     |        [null] |  [null] | [null] |   [null] | 5/4791             | 220559 | RowExclusiveLock | t       | t
 transactionid |   [null] |   [null] | [null] | [null] | [null]     |     170706189 |  [null] | [null] |   [null] | 5/4791             | 220559 | ExclusiveLock    | t       | f
 transactionid |   [null] |   [null] | [null] | [null] | [null]     |     170706190 |  [null] | [null] |   [null] | 5/4791             | 220559 | ExclusiveLock    | t       | f
 transactionid |   [null] |   [null] | [null] | [null] | [null]     |     170706187 |  [null] | [null] |   [null] | 5/4791             | 220559 | ShareLock        | f       | f
 tuple         |  4267681 |  5290151 |      0 |      1 | [null]     |        [null] |  [null] | [null] |   [null] | 5/4791             | 220559 | ExclusiveLock    | t       | f
 virtualxid    |   [null] |   [null] | [null] | [null] | 5/4791     |        [null] |  [null] | [null] |   [null] | 5/4791             | 220559 | ExclusiveLock    | t       | t
 relation      |  4267681 |  5290151 | [null] | [null] | [null]     |        [null] |  [null] | [null] |   [null] | 7/562              | 253641 | RowExclusiveLock | t       | t
 transactionid |   [null] |   [null] | [null] | [null] | [null]     |     170706187 |  [null] | [null] |   [null] | 7/562              | 253641 | ExclusiveLock    | t       | f
 virtualxid    |   [null] |   [null] | [null] | [null] | 7/562      |        [null] |  [null] | [null] |   [null] | 7/562              | 253641 | ExclusiveLock    | t       | t

```

PG's row lock implementation is quite complex — it involves not only tuple locks, but also transactionid and relation locks. Among these, only `locktype=relation` and `virtualxid` can use the fast path; all others cannot.

Compare with the no-row-lock case:

```sql
-- Session 1
begin;
update lzl1 set b='zzz' where a=1;

-- Session 2
begin;
update lzl1 set b='zzz' where a=2;
-- waiting

select *  from pg_locks where pid<>(select pg_backend_pid()) order by pid,locktype;
   locktype    | database | relation |  page  | tuple  | virtualxid | transactionid | classid | objid  | objsubid | virtualtransaction |  pid   |       mode       | granted | fastpath 
---------------+----------+----------+--------+--------+------------+---------------+---------+--------+----------+--------------------+--------+------------------+---------+----------
 relation      |  4267681 |  5290151 | [null] | [null] | [null]     |        [null] |  [null] | [null] |   [null] | 5/4792             | 220559 | RowExclusiveLock | t       | t
 relation      |  4267681 |  5290151 | [null] | [null] | [null]     |        [null] |  [null] | [null] |   [null] | 5/4792             | 220559 | AccessShareLock  | t       | t
 transactionid |   [null] |   [null] | [null] | [null] | [null]     |     170706214 |  [null] | [null] |   [null] | 5/4792             | 220559 | ExclusiveLock    | t       | f
 virtualxid    |   [null] |   [null] | [null] | [null] | 5/4792     |        [null] |  [null] | [null] |   [null] | 5/4792             | 220559 | ExclusiveLock    | t       | t
 relation      |  4267681 |  5290151 | [null] | [null] | [null]     |        [null] |  [null] | [null] |   [null] | 7/563              | 253641 | AccessShareLock  | t       | t
 relation      |  4267681 |  5290151 | [null] | [null] | [null]     |        [null] |  [null] | [null] |   [null] | 7/563              | 253641 | RowExclusiveLock | t       | t
 transactionid |   [null] |   [null] | [null] | [null] | [null]     |     170706212 |  [null] | [null] |   [null] | 7/563              | 253641 | ExclusiveLock    | t       | f
 virtualxid    |   [null] |   [null] | [null] | [null] | 7/563      |        [null] |  [null] | [null] |   [null] | 7/563              | 253641 | ExclusiveLock    | t       | t

```

There are only 2-3 fewer `fastpath=f` entries. The transactionid locks held by both sessions definitely can't use the fast path.

Summary of conditions for using the fast-path lock mechanism (all must be met):

- Lock level <= 3, i.e., SELECT/DML statements
- `locktype=relation`. PG's row locks also require at least transactionid and tuple locks, so these two can't use the fast path
- Fewer than 16 relations accessed (typically exceeded only with full partition access on partitioned tables)



## Conclusion

1. Is the row lock the cause or the effect? Is it a row lock problem, or did database performance degrade causing SQL to run slower and produce row locks?

Row lock is the cause. The SQL execution count didn't change, but the SQL parameters shifted from scattered to concentrated — i.e., updates to the same row noticeably increased. From the benchmark data, updating the same row produces row lock and LWLock LockManager waits.

2. SQL execution count didn't increase — did SQL performance degrade?

SQL performance did degrade, but the index was definitely not chosen incorrectly — it was simply because the same row was being updated repeatedly.



Solution:

From the business side, the SQL was tied to a certain API endpoint: after being called, it updates the call count into the table. If the same endpoint is called repeatedly, it's possible to repeatedly update the same row. Therefore, reducing repeated calls to the same endpoint, or batching the database updates into fewer, larger batches, is expected to mitigate this problem.

