---
title: "From collation mismatch Exception to Its Principles"
date: 2025-12-13
categories: [PostgreSQL内功修炼]
description: "Starting from the collation mismatch exception, this article dives deep into PostgreSQL collation version management and the principles of operating system libc dependencies."
---

## Problem Phenomenon

After physical migration to Xinchuang, occasional errors appear in the pg log, version pg15:

```shell
WARNING:  01000: collation "zh_CN.utf8" has version mismatch
DETAIL:  The collation in the database was created using version 2.17, but the operating system provides version 2.28.
HINT:  Rebuild all objects affected by this collation and run ALTER COLLATION pg_catalog."zh_CN.utf8" REFRESH VERSION, or build RaseSQL with the right library version.
LOCATION:  pg_newlocale_from_collation, pg_locale.c:1660
```

Context: During the physical switch, invalid index rebuilding and refresh database collation version were performed.

Although the libc version was upgraded after physical migration, indexes were rebuilt and are now valid, and the collation version in the database is already consistent with the OS libc.

So,

Why is the error reported?

Where is the error triggered?

What is the impact of the error?

How to resolve it?

## Problem Analysis

### Why is the error reported?

The collation inside the database mainly involves 3 aspects: database, columns, and indexes. The first two use default collation, and the index collation is the real collation.

First, check the database collation. All databases use en_US.UTF8, and refresh database collation has already been done, so the "collation \"zh_CN.utf8\" has version mismatch" error should not be thrown at the database layer.

Then check columns without specially specified default collation:

```sql
select attrelid,attname,attcollation from pg_attribute where attcollation not in (0,100,950,951);
 attrelid | attname | attcollation 
----------+---------+--------------
(0 rows)
```

0 means no collation, default oid=100, C oid=950, POSIX oid=951; "zh_CN.utf8" definitely won't be any of these four.

Finally, check indexes without specially specified collation:

```sql
select * from (select indexrelid ,unnest(indcollation) coll from pg_index) i where coll not in (0,100,950,951);
 indexrelid | coll 
------------+------
(0 rows)
```

Having ruled out database, columns, and indexes, only one situation remains: the application layer specifies a sort rule:

```sql
select col1 from (values ('a'), ('A'), ('啊'), ('阿')) AS l(col1) order by col1 collate "zh_CN.utf8";
WARNING:  01000: collation "zh_CN.utf8" has version mismatch
DETAIL:  The collation in the database was created using version 2.17, but the operating system provides version 2.28.
HINT:  Rebuild all objects affected by this collation and run ALTER COLLATION pg_catalog."zh_CN.utf8" REFRESH VERSION, or build RaseSQL with the right library version.
LOCATION:  pg_newlocale_from_collation, pg_locale.c:1660
 col1 
------
 阿
 啊
 a
 A
```

This zh_CN.utf8 version is inconsistent with the actual one:

```sql
  select collname,collversion,pg_collation_actual_version(oid) from pg_collation where collname ='zh_CN.utf8';
  collname  | collversion | pg_collation_actual_version 
------------+-------------+-----------------------------
 zh_CN.utf8 | 2.17        | 2.28
```

Not only zh_CN.utf8 is different, all are different (except a few collations without version concept).

So it's very likely that the application itself specified a sort rule "zh_CN.utf8", but the coll version in the database is inconsistent with the OS, which triggered the error.

### Source Code Understanding

The error message makes it easy to locate the source code position. Two main functions are of interest: `pg_newlocale_from_collation` and `CheckMyDatabase`.

#### `pg_newlocale_from_collation` Caching and Checking `pg_collation`

`pg_newlocale_from_collation` was introduced in pg10.

```c
/*
 * Create a locale_t from a collation OID.  Results are cached for the
 * lifetime of the backend.  Thus, do not free the result with freelocale().
 *
 * As a special optimization, the default/database collation returns 0.
 * Callers should then revert to the non-locale_t-enabled code path.
 * In fact, they shouldn't call this function at all when they are dealing
 * with the default locale.  That can save quite a bit in hotspots.
 * Also, callers should avoid calling this before going down a C/POSIX
 * fastpath, because such a fastpath should work even on platforms without
 * locale_t support in the C library.
 *
 * For simplicity, we always generate COLLATE + CTYPE even though we
 * might only need one of them.  Since this is called only once per session,
 * it shouldn't cost much.
 */
/* locale_t means non-ICU. This function caches a locale_t type collation OID for the backend
* the default/database collation returns 0. "default" means using the database's collation
*/
pg_locale_t
pg_newlocale_from_collation(Oid collid)  // Note: passes in collation oid, not fetching all pg_collation
{
...
	/* Return 0 for "default" collation, just in case caller forgets */
	if (collid == DEFAULT_COLLATION_OID)  // Three special collations:
		return (pg_locale_t) 0;       // default oid=100, C oid=950, POSIX oid=951

...
	if (cache_entry->locale == 0)
	{
...
		collversion = SysCacheGetAttr(COLLOID, tp, Anum_pg_collation_collversion,
									  &isnull);  // Get version from pg_collation data dictionary
		if (!isnull)
		{
...
			actual_versionstr = get_collation_actual_version(collform->collprovider, collcollate); // Get actual version via get_collation_actual_version
...
			collversionstr = TextDatumGetCString(collversion);

			if (strcmp(actual_versionstr, collversionstr) != 0)  // Compare data dictionary version and actual version, throw error if different
				ereport(WARNING,
						(errmsg("collation \"%s\" has version mismatch",
								NameStr(collform->collname)),
						 errdetail("The collation in the database was created using version %s, "
								   "but the operating system provides version %s.",
								   collversionstr, actual_versionstr),
						 errhint("Rebuild all objects affected by this collation and run "
								 "ALTER COLLATION %s REFRESH VERSION, "
								 "or build PostgreSQL with the right library version.",
								 quote_qualified_identifier(get_namespace_name(collform->collnamespace),
															NameStr(collform->collname)))));
		}
...
	return cache_entry->locale;
}
```

The main check is: through the coll oid, check whether the version in the pg_collation data dictionary is consistent with the actual version; if inconsistent, throw an error.

#### `CheckMyDatabase` Caching and Checking `pg_database`

`CheckMyDatabase` has existed for a long time, performing many database-side checks. However, pg15 added logic for checking the database version.

```c
/*
 * CheckMyDatabase -- fetch information from the pg_database entry for our DB
 */
static void
CheckMyDatabase(const char *name, bool am_superuser, bool override_allow_connections)
{
...
	/* Fetch our pg_database row normally, via syscache */
	tup = SearchSysCache1(DATABASEOID, ObjectIdGetDatum(MyDatabaseId));
...
	default_locale.provider = dbform->datlocprovider; // default is the db's

	/*
	 * Default locale is currently always deterministic.  Nondeterministic
	 * locales currently don't support pattern matching, which would break a
	 * lot of things if applied globally.
	 */
	default_locale.deterministic = true; // byte-order sensitive

	/*
	 * Check collation version.  See similar code in
	 * pg_newlocale_from_collation().  Note that here we warn instead of error
	 * in any case, so that we don't prevent connecting.
	 */
	datum = SysCacheGetAttr(DATABASEOID, tup, Anum_pg_database_datcollversion,
							&isnull); // Get datcollversion from pg_database
	if (!isnull)
	{
		char	   *actual_versionstr;
		char	   *collversionstr;

		collversionstr = TextDatumGetCString(datum);

		actual_versionstr = get_collation_actual_version(dbform->datlocprovider, dbform->datlocprovider == COLLPROVIDER_ICU ? iculocale : collate);  // Get actual version via get_collation_actual_version
...
		else if (strcmp(actual_versionstr, collversionstr) != 0) // Compare db datcollversion and actual version, throw warning if not equal
			ereport(WARNING,
					(errmsg("database \"%s\" has a collation version mismatch",
							name),
					 errdetail("The database was created using collation version %s, "
							   "but the operating system provides version %s.",
							   collversionstr, actual_versionstr),
					 errhint("Rebuild all objects in this database that use the default collation and run "
							 "ALTER DATABASE %s REFRESH COLLATION VERSION, "
							 "or build PostgreSQL with the right library version.",
							 quote_identifier(name))));
	}
...
}
```

The `CheckMyDatabase` function compares the datcollversion in the pg_database data dictionary with the actual version.

#### Function Differences

- In pg14 and before, there was only 1 collation comparison logic: when a session first caches the corresponding collation, it calls `pg_newlocale_from_collation` to access **the version of the corresponding collation in the pg_collation data dictionary** and compare it with the real version.
- In PG15 and later, because the datcollversion field was added to the pg_database table, a new logic for checking db collation version was added: when a session first accesses the db in pg_database, it calls `CheckMyDatabase` to check **the datcollversion of the corresponding database in pg_database** and compare it with the real version.

### Why Are There Fewer Errors After Only Refreshing the Database?

After refreshing the database collation version, the warning about inconsistent pg_database coll version won't be triggered, but it still cannot rule out the situation where pg_collation's coll version is inconsistent. Why are there so many fewer errors after only refreshing the database? Could it be that pg_collation's coll version simply won't be loaded?

```sql
select c.coll,count(*) from (select  unnest(indcollation) coll from pg_index ) c group by c.coll;
 coll | count 
------+-------
  950 |    37  --C
    0 |  2841  --No collation
  100 |   723  --default
```

In real environments, default is the most used. Generally, no one specifies a collation; if not specified it's default, and default is the database's default collation.

Here we need to revisit the `pg_newlocale_from_collation` function. The function starts like this:

```c
pg_locale_t
pg_newlocale_from_collation(Oid collid)
{
	collation_cache_entry *cache_entry;

	/* Callers must pass a valid OID */
	Assert(OidIsValid(collid));

	/* Return 0 for "default" collation, just in case caller forgets */
	if (collid == DEFAULT_COLLATION_OID)
		return (pg_locale_t) 0;
...
```

When `collid==DEFAULT_COLLATION_OID`==100, it directly `return`s without executing the real version check below, so it won't throw a warning. This logic is reasonable because the db coll version has already been verified when logging into the database; if there's a problem, a warning must have already been thrown at the session layer.

Furthermore, even if a possible value like collid=37 is passed in, the corresponding C also has no version concept.

Therefore, after refreshing the database, in the vast majority of scenarios, as long as the database's internal sorting is used (not expression sorting or specified index sorting), no error will be thrown.

### Testing

Here we only test whether there is a refresh warning, not testing index corruption or database crashes.

```shell
# Check libc version
getconf GNU_LIBC_VERSION

Source host version glibc 2.17
Target host   glibc 2.28
pg version    pg15+
```

#### Test: Refresh db without refreshing pg_collation, only db coll version changes

```sql
select datname,datlocprovider,datcollate,datctype,datcollversion from pg_database 
  datname   | datlocprovider | datcollate  |  datctype   | datcollversion 
------------+----------------+-------------+-------------+----------------
 lzldb      | c              | en_US.UTF-8 | en_US.UTF-8 | 2.17
 
select collname,collprovider,collversion,pg_collation_actual_version(oid) from pg_collation where collname ~ 'en_US.utf8';
  collname  | collprovider | collversion | pg_collation_actual_version 
------------+--------------+-------------+-----------------------------
 en_US.utf8 | c            | 2.17        | 2.28

alter database lzldb refresh collation version;
NOTICE:  00000: changing version from 2.17 to 2.28
LOCATION:  AlterDatabaseRefreshColl, dbcommands.c:2399
ALTER DATABASE
```

Check pg_collation and pg_database again:

```sql
  collname  | collprovider | collversion | pg_collation_actual_version 
------------+--------------+-------------+-----------------------------
 en_US.utf8 | c            | 2.17        | 2.28

  datname   | datlocprovider | datcollate  |  datctype   | datcollversion 
------------+----------------+-------------+-------------+----------------
 lzldb      | c              | en_US.UTF-8 | en_US.UTF-8 | 2.28
```

Consistent with the official documentation description: refresh database collation version only refreshes the db's default collation; pg_collation itself won't change.

#### Test: Refresh db without refreshing pg_collation, specifying expression sort reports warning

As analyzed at the beginning, expression sorting will report a warning, omitted.

#### Test: Refresh db without refreshing pg_collation, creating a new index with specified collation reports warning

Test 1: Specify collation when creating index

```sql
   collname  | collversion | pg_collation_actual_version 
------------+-------------+-----------------------------
 zh_CN.utf8 | 2.17        | 2.28
 
 > create index idx11 on tt(a collate "zh_CN.utf8");
WARNING:  01000: collation "zh_CN.utf8" has version mismatch
DETAIL:  The collation in the database was created using version 2.17, but the operating system provides version 2.28.
HINT:  Rebuild all objects affected by this collation and run ALTER COLLATION pg_catalog."zh_CN.utf8" REFRESH VERSION, or build PostgreSQL with the right library version.
LOCATION:  pg_newlocale_from_collation, pg_locale.c:1664
CREATE INDEX
```

Test 2: Specify column default collation when creating table, don't specify when creating index

```sql
\c lzldb   -- Reconnect a session
You are now connected to database "lzldb" as user "postgres".
create table ttt(a varchar(10) collate "zh_CN.utf8");
CREATE TABLE

> create index idxttt on ttt(a);
WARNING:  01000: collation "zh_CN.utf8" has version mismatch
DETAIL:  The collation in the database was created using version 2.17, but the operating system provides version 2.28.
HINT:  Rebuild all objects affected by this collation and run ALTER COLLATION pg_catalog."zh_CN.utf8" REFRESH VERSION, or build PostgreSQL with the right library version.
LOCATION:  pg_newlocale_from_collation, pg_locale.c:1664
CREATE INDEX
Time: 7.904 ms
```

Column default collation and index specification of collation are essentially the same thing, both for specifying the index's collation. Both can report warnings.

#### Test: Refresh db without refreshing pg_collation, existing index with specified collation does not report warning

Scenario: The original database already has an index specifying collation zh_CN.utf8, different from the db. Refreshing the db won't catch it. But after migrating to a new database, the vendor's coll version definitely changed.

```sql
select collname,collprovider,collversion,pg_collation_actual_version(oid) from pg_collation where collname ~ 'zh_CN.utf8';
  collname  | collprovider | collversion | pg_collation_actual_version 
------------+--------------+-------------+-----------------------------
 zh_CN.utf8 | c            | 2.17        | 2.28
```

Without using expression sorting, the index can be used, but index sorting cannot be used:

```sql
> set enable_seqscan =off;
SET
> EXPLAIN ANALYZE SELECT a  FROM tt  ORDER BY a LIMIT 1000;
                                                               QUERY PLAN                                                               
----------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=6667.80..6670.30 rows=1000 width=33) (actual time=44.928..45.145 rows=1000 loops=1)
   ->  Sort  (cost=6667.80..6892.81 rows=90004 width=33) (actual time=44.926..45.021 rows=1000 loops=1)
         Sort Key: a
         Sort Method: top-N heapsort  Memory: 127kB
         ->  Index Only Scan using idxtt on tt  (cost=0.42..1732.98 rows=90004 width=33) (actual time=0.029..15.434 rows=90004 loops=1)
               Heap Fetches: 4
```

Existing indexes with specified collation do not report warnings when used.

## Summary of This Problem

The refresh database and refresh collation warnings are session-level. In each session, for each database or each collation, it only reports once.

Only refreshing the database very likely won't report warnings again, but there are situations where creating an index with a specified collation or running SQL with specified expression collation may still report warnings.

The coll version in the data dictionary is only for tracking whether the collation provider version has changed at the database layer. Imagine if there were no coll version in the data dictionary - the database might not even be able to return a warning saying "your sort rule provider has upgraded its version, your data sorting might have problems, you need to check it" (and of course it's not just about sorting).

## Solutions for This Problem

Corrupt indexes have already been rebuilt, the database has been refreshed, only collation hasn't been refreshed. The inconsistency of coll version in the data dictionary is not a big problem, it's just a warning. As for other hidden and strange pitfalls, refer to the more section.

Solution for this problem:

Step 1: Check if there are still dependencies

```sql
SELECT pg_describe_object(refclassid, refobjid, refobjsubid) AS "Collation",
       pg_describe_object(classid, objid, objsubid) AS "Object"
  FROM pg_depend d JOIN pg_collation c
       ON refclassid = 'pg_collation'::regclass AND refobjid = c.oid
  WHERE c.collversion <> pg_collation_actual_version(c.oid)
  ORDER BY 1, 2;

```

If there are returns, it's best to rebuild the dependent objects; if not, follow step 2:

- Solution 1: Do nothing. If there aren't many warnings, leaving them alone is fine.
- Solution 2: Only refresh collation zh_CN.UTF8. Fix one as it comes.
- Solution 3: Refresh all collations. Even if the application incrementally uses expressions or index-specified collation, no warnings will be reported.

## More

### Key Summary of glibc Upgrade Related Issues

Locale is a very tricky area, and glibc upgrades cause many collation-related problems. Referencing reference materials, here's a summary of some important points:

pg_collation is obtained from the OS command `locale -a`; the provider is basically glibc, so you need to look at the glibc version.

In pg_collation, "C" and "posix" have collprovider `c`, which looks the same as "C.UTF8" etc., but they're not. "C.UTF8"'s provider is glibc, **has a version, generally Unicode codepoint sorting or Unicode semantic sorting**; "C" and "POSIX" are equivalent, the most basic locale defined by the POSIX standard, implemented by libc, not in `locale -a`, **has no version, sorts directly by byte order**.

Root cause of collation problems: The database requires that locale definitions never change during the database lifecycle, but OS vendors, especially the GNU C library, make changes to locale in every minor version, and this is legitimate.

GNU C library makes changes to locale in every minor version. The version most prone to problems in reality is **glibc 2.28**, because 2.28 upgraded the major version **unicode 9.0.0** ([has been updated to a new upstream version from ISO which is in sync with Unicode 9.0.0](https://sourceware.org/glibc/wiki/Release/2.28)).

**pg has no way to detect compatibility issues caused by glibc upgrades**. Index corruption checking is not an all-check, and indexes are only one aspect. After physical replication or upgrade, even if indexes are rebuilt, you cannot rule out the possibility that the database crashes one day due to collation version issues.

Data anomalies include: duplicate primary keys, sort-dependent constraints, range partition table data written to wrong partitions, mergejoin and other sort operations, etc.

Character types depend on collation. Data types that don't depend on collation:

- bytea
- tsvector gin indexes
- pg_trgm indexes
- numeric data types: int, bigint, numeric, float, ...
- custom data types like geometry (PostGIS)
- timestamp

ASCII sorting is relatively common but doesn't conform to human understanding, i.e., not semantic. Semantically conforming international sorting standards are generally Unicode standards.

Unicode-based sorting rules are divided into 2 types: codepoint sorting, UCA (Unicode Collation Algorithm).

UCA is based on DUCET (Default Unicode Collation Element Table). The DUCET table itself may have sorting changes between different versions. For example, en_US.UTF8 is UCA sorting, equivalent to semantic sorting; version upgrades will change sorting rules. C.UTF8 is codepoint sorting; once codepoints are confirmed they won't change, and sorting rules won't change.

PG 17+ provides a very safe locale provider method: builtin, no longer depending on OS-provided glibc, ICU and other providers. Example enable command:

```sql
initdb --locale-provider=builtin --bultin-locale=C.UTF-8 dbname1

```

17 only supports C, C.UTF-8. C is byte-order sorting (approximately ASCII sorting), C.UTF-8 is Unicode codepoint sorting; 18 adds one more PG_UNICODE_FAST, also Unicode codepoint sorting, with [slight differences](https://www.postgresql.org/docs/18/locale.html#LOCALE-PROVIDERS) from C.UTF-8.

Because the database must maintain stable sorting, custom application sorting can only be pushed to the application layer. For example, expression sorting is semantically clear and doesn't affect the database's own choice of collation. If one day pg also supports built-in en_US.utf8, then we can consider built-in semantic sorting.

During Xinchuang migration, the glibc version of Xinchuang hosts is generally higher than old Intel server glibc versions, likely crossing the 2.28 version. Combined with tight deadlines, KPI pressure, insufficient manpower, and large databases, physical migration is unavoidable. So Xinchuang physical migration needs to pay attention to glibc versions and many anomalies caused by collation.

### What to Do After Physical Migration

Assuming the database is en_US.utf8, provider c, and physical migration across libc versions has already been done, the following operations should be performed:

**I. Official Required Solution**

1. At minimum, rebuild problematic indexes. Install the amcheck extension and use the bt_index_check function:

```sql
SELECT bt_index_check('idx1'::regclass, true);

```

2. Refresh database version (pg15+):

```sql
ALTER DATABASE name REFRESH COLLATION VERSION

```

3. Check if there are other [dependent objects](https://www.postgresql.org/docs/18/sql-altercollation.html#SQL-ALTERCOLLATION-NOTES). If there are, handle them accordingly:

```sql
SELECT pg_describe_object(refclassid, refobjid, refobjsubid) AS "Collation",
       pg_describe_object(classid, objid, objsubid) AS "Object"
  FROM pg_depend d JOIN pg_collation c
       ON refclassid = 'pg_collation'::regclass AND refobjid = c.oid
  WHERE c.collversion <> pg_collation_actual_version(c.oid)
  ORDER BY 1, 2;

```

After handling, then:

4. Refresh collation version (pg10+):

```sql
ALTER COLLATION name REFRESH VERSION

```

**II. Unofficial Workaround Solutions**

I haven't made a complete solution here, just some thoughts.

1. Handling partition table data written to wrong partition:

Partition key is int/bigint/float, no relation to collation, can be ignored.

Partition key is time partition, if timestamp, can be ignored. If varchar or other character types, depends on the situation.

Partition key is character type, refer to "a" and "-" sorting (pgconf Collation Challenges Sorting It Out). But note the following points:

- If querying data, don't query from the parent table; it might crash or fail to return results.
- There's no simple detection solution.

2. Handling primary key/unique key conflicts.

3. Handling fdw sort range anomaly issues.

4. Unknown problems.

## ref

https://wiki.postgresql.org/wiki/Locale_data_changes

https://wiki.postgresql.org/wiki/Collations

pgconf Collation Challenges Sorting It Out

PFCONF Collations from A to Z

http://www.unicode.org/reports/tr10/tr10-34.html

https://sourceware.org/glibc/wiki/Release/2.28

https://www.postgresql.org/docs/18/sql-altercollation.html

https://www.postgresql.org/docs/18/sql-alterdatabase.html

https://www.postgresql.org/docs/17/locale.html#LOCALE-PROVIDERS


---

> Original article: [https://lastdba.com/2025/12/13/从collation-mismatch异常到其原理/](https://lastdba.com/2025/12/13/从collation-mismatch异常到其原理/)
