---
title: "A Brief Analysis of PostgreSQL TRUNCATE"
date: 2024-08-12
categories: [PostgreSQL源码解析]
description: "Comprehensive analysis of PostgreSQL TRUNCATE command options, including ONLY inheritance behavior, RESTART/CONTINUE IDENTITY sequence reset, and CASCADE behavior"
---

## Command Options

```sql
TRUNCATE [ TABLE ] [ ONLY ] name [ * ] [, ... ]
    [ RESTART IDENTITY | CONTINUE IDENTITY ] [ CASCADE | RESTRICT ]
```

**1**. `ONLY`: truncate only the specified table. When a table has inheritance children or child partitions, by default they are truncated together; ONLY can truncate just the inheritance parent table. Partitioned parent tables cannot specify ONLY.

```sql
-- Cannot truncate only a partitioned parent table
=> truncate only parttable;
ERROR:  42809: cannot truncate only a partitioned table
HINT:  Do not specify the ONLY keyword, or use TRUNCATE ONLY on the partitions directly.
LOCATION:  ExecuteTruncate, tablecmds.c:1655
```

```sql
-- truncate only the inheritance parent table, only the parent is cleaned
=> truncate table only parenttable;
TRUNCATE TABLE
=> select tableoid::regclass,count(*) from parenttable group by tableoid::regclass ;
  tableoid  | count
------------+-------
 childtable |     1

-- Directly truncate the inheritance parent table, child tables are also cleaned
=>  truncate table parenttable;
TRUNCATE TABLE
=> select tableoid::regclass,count(*) from parenttable group by tableoid::regclass ;
 tableoid | count
----------+-------
(0 rows)
```

**2**. `RESTART IDENTITY` `CONTINUE IDENTITY`: whether to reset sequences on columns. Default is CONTINUE.

```sql
-- bigserial creates a column sequence by default
=> create table tableserial (a  bigserial not null,b name);
CREATE TABLE
=> \d+ tableserial;
                                               Table "public.tableserial"
 Column |  Type  | Collation | Nullable |                Default                 | Storage | Stats target | Description
--------+--------+-----------+----------+----------------------------------------+---------+--------------+-------------
 a      | bigint |           | not null | nextval('tableserial_a_seq'::regclass) | plain   |              |
 b      | name   |           |          |                                        | plain   |              |

=> insert into tableserial(b) select md5(random()::text) from generate_series(1,1000);
INSERT 0 1000
-- seq current value is 1000
=> select currval('tableserial_a_seq'::regclass);
 currval
---------
    1000

-- Direct truncate does not reset sequences by default
=>  truncate table tableserial;
TRUNCATE TABLE
=> select currval('tableserial_a_seq'::regclass) cur,nextval('tableserial_a_seq'::regclass);
 cur  | nextval
------+---------
 1000 |    1001

-- Explicitly specify RESTART IDENTITY to reset sequences
=>  truncate table tableserial RESTART IDENTITY;
TRUNCATE TABLE
-- Note: seq is reset on nextval
=>  select currval('tableserial_a_seq'::regclass) cur,nextval('tableserial_a_seq'::regclass);
 cur  | nextval
------+---------
 1001 |       1
```

**3**. `CASCADE`: truncate the table and all foreign key referencing tables.

```sql
-- Create primary table, foreign key table, and data
=>  create table pri_tab(id bigint primary key,name varchar(10));
CREATE TABLE

=> insert into pri_tab values (1,'abc'),(2,'abc'),(3,'abc');
INSERT 0 3

=>  create table frn_tab(id bigint,FOREIGN KEY (id) REFERENCES pri_tab(id));
CREATE TABLE

=> insert into frn_tab values (1),(2);
INSERT 0 2

=> select * from pri_tab;
 id | name
----+------
  1 | abc
  2 | abc
  3 | abc
(3 rows)

-- Foreign key table frn_tab depends on pri_tab's data
=> select * from frn_tab;
 id
----
  1
  2
(2 rows)

-- With foreign key references on the primary table, CASCADE is required on the foreign key table, otherwise truncate fails
=> truncate table pri_tab ;
ERROR:  0A000: cannot truncate a table referenced in a foreign key constraint
DETAIL:  Table "frn_tab" references "pri_tab".
HINT:  Truncate table "frn_tab" at the same time, or use TRUNCATE ... CASCADE.
LOCATION:  heap_truncate_check_FKs, heap.c:3427

-- Clear foreign key constrained tables together
=> truncate table pri_tab cascade;
NOTICE:  00000: truncate cascades to table "frn_tab"
LOCATION:  ExecuteTruncateGuts, tablecmds.c:1725
TRUNCATE TABLE
=> select * from pri_tab;
 id | name
----+------
(0 rows)

=>  select * from frn_tab;
 id
----
(0 rows)

```

Since the foreign key table depends on the primary table's data, you cannot directly truncate the primary table — you must add CASCADE, at which point the foreign key table is also cleared along with the primary table.

**4**. `RESTRICT`
Whether to clear foreign key tables. Not very useful — it's the default option, and behavior is the same whether specified or not. Use CASCADE to clear associated foreign key tables.

## MVCC / Transaction

The PG official documentation has this passage:

>`TRUNCATE` is not MVCC-safe. After truncation, the table will appear empty to concurrent transactions, if they are using a snapshot taken before the truncation occurred.
>`TRUNCATE` is transaction-safe with respect to the data in the tables: the truncation will be safely rolled back if the surrounding transaction does not commit.

transaction-safe means it can be placed inside a transaction block and can be rolled back.
Rolling back truncate:

```sql
=> begin;
BEGIN
=> truncate t1;
TRUNCATE TABLE
=> rollback;
ROLLBACK
=> select count(*) from t1;
 count
-------
   100
```

not MVCC-safe means: if a session takes a snapshot before truncate, and a truncate occurs during the snapshot period, that snapshot can read the result after truncate. This does not conform to MVCC.
However, this isn't a big issue in session scenarios, because truncate takes an 8-level lock (AccessExclusiveLock). If the snapshot hasn't ended, at minimum there's a read shared lock on the table, so truncate won't execute.

>This will only be an issue for a transaction that did not access the table in question before the DDL command started — any transaction that has done so would hold at least an `ACCESS SHARE` table lock, which would block the DDL command until that transaction completes.

## Feature Updates

![在这里插入图片描述](/img/csdn/c1c4036557be.png)

There aren't many truncate feature updates. Just note that PG14 added support for truncating foreign tables. The prerequisite for truncating foreign tables is that the FDW must support the TRUNCATE API.

>Also it extends postgres_fdw so that it can issue TRUNCATE command to foreign servers, by adding new routine for that TRUNCATE API.

## Functional Differences Between pg TRUNCATE and Other Databases

![在这里插入图片描述](/img/csdn/8b204baa363f.png)
![在这里插入图片描述](/img/csdn/b7ebb636b6b2.png)

TRUNCATE being fast and an 8-level lock are already well-known traits. Compared to other databases, PG can also: **choose whether to reset sequences** (`RESTART IDENTITY` `CONTINUE IDENTITY`), **rollback**, and has **simple authorization**.

## What TRUNCATE Does

```sql
create table lzl(a int);
create index lzl_idx on lzl(a);
create sequence lzl_seq start with 1;
alter table lzl alter column a set default nextval('lzl_seq');
--select pg_relation_filepath('lzl');
```

```sql
-- db path
=> select oid from  pg_database where datname='lzldb';
  oid
--------
 418679

-- When first created, each rel's oid = relfilenode
=> select relname,oid,relfilenode,relkind from pg_class where  relname like 'lzl%';
 relname |  oid   | relfilenode | relkind
---------+--------+-------------+---------
 lzl     | 428363 |      428363 | r
 lzl_idx | 428366 |      428366 | i
 lzl_seq | 428367 |      428367 | S
(3 rows)

=> truncate table lzl;
TRUNCATE TABLE
=> select relname,oid,relfilenode,relkind from pg_class where  relname like 'lzl%';
 relname |  oid   | relfilenode | relkind
---------+--------+-------------+---------
 lzl     | 428363 |      428370 | r
 lzl_idx | 428366 |      428371 | i
 lzl_seq | 428367 |      428367 | S
-- After truncate, table and index were rebuilt, but sequence was not

M=> truncate table lzl RESTART IDENTITY;
TRUNCATE TABLE
=> select relname,oid,relfilenode,relkind from pg_class where  relname like 'lzl%';
 relname |  oid   | relfilenode | relkind
---------+--------+-------------+---------
 lzl     | 428363 |      428372 | r
 lzl_idx | 428366 |      428373 | i
 lzl_seq | 428367 |      428367 | S
-- Even with explicit RESTART, sequence was still not rebuilt

M=> alter sequence lzl_seq restart;
ALTER SEQUENCE
M=> select relname,oid,relfilenode,relkind from pg_class where  relname like 'lzl%';
 relname |  oid   | relfilenode | relkind
---------+--------+-------------+---------
 lzl     | 428363 |      428372 | r
 lzl_idx | 428366 |      428373 | i
 lzl_seq | 428367 |      428374 | S
-- Explicitly restarting the sequence DOES rebuild it
```

`truncate ... RESTART IDENTITY` did not rebuild our sequence, while `alter sequence lzl_seq restart` did rebuild the sequence. It seems the understanding of `RESTART IDENTITY` was wrong. Let's look at the official documentation for `RESTART IDENTITY`:

>Automatically restart sequences owned by columns of the truncated table(s).

The sequence must be `owned by` a column on the table — note: not `owner to`. Although `\d` shows sequences on the table, they may not belong to the table.

```sql
 \d+ lzl;
                                              Table "public.lzl"
 Column |  Type   | Collation | Nullable |           Default            | Storage | Stats target | Description
--------+---------+-----------+----------+------------------------------+---------+--------------+-------------
 a      | integer |           |          | nextval('lzl_seq'::regclass) | plain   |              |
```

Use `owned by` to modify the sequence's owning table:

```sql
=> ALTER SEQUENCE lzl_seq OWNED BY lzl.a;
ALTER SEQUENCE

-- Check sequence owner information
SELECT s.relname AS seq, n.nspname AS sch, t.relname AS tab, a.attname AS col
FROM pg_class s
JOIN pg_depend d ON d.objid=s.oid AND d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass
JOIN pg_class t ON t.oid=d.refobjid
JOIN pg_namespace n ON n.oid=t.relnamespace
JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
WHERE s.relkind='S' AND d.deptype='a';
        seq        |  sch   |     tab     | col
-------------------+--------+-------------+-----
 tableserial_a_seq | public | tableserial | a
 lzl_seq           | public | lzl         | a

=> truncate table lzl RESTART IDENTITY;
TRUNCATE TABLE
M=> select relname,oid,relfilenode,relkind from pg_class where  relname like 'lzl%';
 relname |  oid   | relfilenode | relkind
---------+--------+-------------+---------
 lzl     | 428363 |      428375 | r
 lzl_idx | 428366 |      428376 | i
 lzl_seq | 428367 |      428377 | S
```

When a sequence is `owned by` a column on the table, explicitly specifying `RESTART IDENTITY` with truncate will restart that sequence, which also rebuilds the sequence. **Sequences created via serial/bigserial are owned by the table and are dropped when the table is dropped; sequences not owned by a table are not dropped when the table is dropped**.

Summary of truncate rebuild characteristics:
 - Direct `truncate table` rebuilds the table and indexes.
 - **`truncate table` + `RESTART IDENTITY` rebuilds (i.e., restarts) sequences that belong to this table. If a sequence doesn't belong to this table, even if the column's default is associated with the sequence, the sequence won't be rebuilt**.

## Source Code Analysis

TRUNCATE is also a utility command, and the entry function can be found quickly.

`ExecuteTruncate` in `src/backend/commands/tablecmds.c` is the entry function. The comments already explain that truncate must acquire an exclusive lock, check permissions and relation validity, and recursively check all tables that need to be truncated.

```c
void
ExecuteTruncate(TruncateStmt *stmt)
{
...

/*
* Open, exclusive-lock, and check all the explicitly-specified relations
*/
foreach(cell, stmt->relations)
{
...
LOCKMODE lockmode = AccessExclusiveLock;  // Level 8 lock
...

rel = table_open(myrelid, NoLock); // Open table

void
ExecuteTruncate(TruncateStmt *stmt)
{
...
	foreach(cell, stmt->relations)
	{
...
		LOCKMODE	lockmode = AccessExclusiveLock; // Level 8 lock
...
		/* open the relation, we already hold a lock on it */
		rel = table_open(myrelid, NoLock); // Open table
...
		truncate_check_activity(rel);  // Even with the lock, verify it's not in use
...
		if (recurse) // Recursive execution
		{
...
			children = find_all_inheritors(myrelid, lockmode, NULL); // Find all inheritance children

			foreach(child, children)
			{
...
				 // Above only checked the parent table, recursion checks children
				truncate_check_rel(RelationGetRelid(rel), rel->rd_rel);
				truncate_check_activity(rel);

				rels = lappend(rels, rel);  // Add to the list of rels to truncate
				relids = lappend_oid(relids, childrelid);
...
			}
		}
		// Recursion ends
		// truncate only on partitioned parent table? error directly
		else if (rel->rd_rel->relkind == RELKIND_PARTITIONED_TABLE)
			ereport(ERROR,
					(errcode(ERRCODE_WRONG_OBJECT_TYPE),
					 errmsg("cannot truncate only a partitioned table"),
					 errhint("Do not specify the ONLY keyword, or use TRUNCATE ONLY on the partitions directly.")));
	}

	// Main function
	ExecuteTruncateGuts(rels, relids, relids_logged,
						stmt->behavior, stmt->restart_seqs);

	/* And close the rels */
	foreach(cell, rels)
	{
		Relation	rel = (Relation) lfirst(cell);

		table_close(rel, NoLock);
	}
}
```

`ExecuteTruncateGuts` is called not only by the TRUNCATE command but also by the subscription side (publication/subscription can synchronize TRUNCATE).

```c
void
ExecuteTruncateGuts(List *explicit_rels,
					List *relids,
					List *relids_logged,
					DropBehavior behavior, bool restart_seqs)
{
...
	rels = list_copy(explicit_rels);
	if (behavior == DROP_CASCADE)  // If CASCADE option specified, extract all referencing relations
	{
		for (;;)
		{
...
			newrelids = heap_truncate_find_FKs(relids); // Find FKs
			if (newrelids == NIL)
				break;			/* nothing else to add */ // No rels, exit directly

			foreach(cell, newrelids)
			{
...
				rel = table_open(relid, AccessExclusiveLock); // All rels acquire AccessExclusiveLock
				ereport(NOTICE,
						(errmsg("truncate cascades to table \"%s\"",
								RelationGetRelationName(rel))));
				truncate_check_rel(relid, rel->rd_rel);  // Check if it's a truncatable object — must be a data-storing table
				truncate_check_perms(relid, rel->rd_rel);  // Check permissions
				truncate_check_activity(rel);  // Check if in use
...
			}
		}
	}

...
	if (restart_seqs) // Handle restart seq
	{
		foreach(cell, rels)
		{
			Relation	rel = (Relation) lfirst(cell);
			List	   *seqlist = getOwnedSequences(RelationGetRelid(rel));
...
			// Only check sequence permissions
				if (!pg_class_ownercheck(seq_relid, GetUserId()))
					aclcheck_error(ACLCHECK_NOT_OWNER, OBJECT_SEQUENCE,
								   RelationGetRelationName(seq_rel));
...
		}
	}

...

	// Execute all BEFORE TRUNCATE triggers
	foreach(cell, rels)
	{
		ExecBSTruncateTriggers(estate, resultRelInfo);
		resultRelInfo++;
	}

// Begin the actual truncate
	foreach(cell, rels)
	{
...
		// If it's a partitioned parent table, do nothing
		if (rel->rd_rel->relkind == RELKIND_PARTITIONED_TABLE)
			continue;

		// Handle foreign tables
		if (rel->rd_rel->relkind == RELKIND_FOREIGN_TABLE)
		{
		...
		}

...
		 // If same transaction (may rollback), directly execute heap_truncate_one_rel without creating new relfilenode
		if (rel->rd_createSubid == mySubid ||
			rel->rd_newRelfilenodeSubid == mySubid)
		{
			/* Immediate, non-rollbackable truncation is OK */
			heap_truncate_one_rel(rel);
		}
		else
		{
...
			// Set NewRelfilenode
			RelationSetNewRelfilenode(rel, rel->rd_rel->relpersistence);

			heap_relid = RelationGetRelid(rel);

			 // Same for toast
			toast_relid = rel->rd_rel->reltoastrelid;
			if (OidIsValid(toast_relid))
			{
				Relation	toastrel = relation_open(toast_relid,
													 AccessExclusiveLock);

				RelationSetNewRelfilenode(toastrel,
										  toastrel->rd_rel->relpersistence);
				table_close(toastrel, NoLock);
			}

...
			 // Rebuild indexes
			reindex_relation(heap_relid, REINDEX_REL_PROCESS_TOAST,
							 &reindex_params);
		}

		pgstat_count_truncate(rel); // Update pgstat truncate count
	}

...
	// Reset sequences
	foreach(cell, seq_relids)
	{
		Oid			seq_relid = lfirst_oid(cell);

		ResetSequence(seq_relid);
	}

	// Write WAL
	if (list_length(relids_logged) > 0)
	{
	...
	}

	// Fire AFTER TRUNCATE triggers
	resultRelInfo = resultRelInfos;
	foreach(cell, rels)
	{
		ExecASTruncateTriggers(estate, resultRelInfo);
		resultRelInfo++;
	}
...
}
```

The `ExecuteTruncateGuts` function processes according to truncate options, with the following flow:
1. Find all referencing foreign key tables based on CASCADE option
2. Fire BEFORE TRUNCATE triggers
3. Execute truncate
 - If same transaction, don't immediately create `NewRelfilenode`, directly call `heap_truncate_one_rel` for truncation
 - If not same transaction, call `RelationSetNewRelfilenode` to create new `NewRelfilenode`
4. `reindex_relation` function rebuilds indexes
5. Reset sequences based on RESTART IDENTITY
6. Write WAL log
7. Fire AFTER TRUNCATE triggers

Tracing further, there's quite a bit of function nesting:
`RelationSetNewRelfilenode`
`table_relation_set_new_filenode`
`relation_set_new_filenode`
`heapam_relation_set_new_filenode`
`RelationCreateStorage`
Then to `smgrcreate` and `smgr_create` in `src/backend/storage/smgr/smgr.c`. The comment for `smgr.c`:

> public interface routines to storage manager switch
> All file system operations in POSTGRES dispatch through these routines.

Any file system operation goes through smgr (storage manager); at this point it becomes file system operations.

## Reference

https://www.postgresql.org/docs/15/sql-truncate.html
https://www.postgresql.org/docs/current/mvcc-caveats.html
https://pgpedia.info/t/truncate.html
https://www.orafaq.com/wiki/SQL_FAQ
https://learnsql.com/blog/difference-between-truncate-delete-and-drop-table-in-sql/

*Originally published in Chinese on [lastdba.com](https://lastdba.com).*
