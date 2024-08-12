
# 命令选项
```sql
TRUNCATE [ TABLE ] [ ONLY ] name [ * ] [, ... ]
    [ RESTART IDENTITY | CONTINUE IDENTITY ] [ CASCADE | RESTRICT ]
```

**1**.`ONLY`:只truncate指定的表。当表有继承子表或有子分区时，默认会一起truncate;only可只truncate继承父表。分区父表不能指定only
```sql
--不能truncate only分区父表
=> truncate only parttable;
ERROR:  42809: cannot truncate only a partitioned table
HINT:  Do not specify the ONLY keyword, or use TRUNCATE ONLY on the partitions directly.
LOCATION:  ExecuteTruncate, tablecmds.c:1655
```
```sql
--truncate only继承父表，只清理父表
=> truncate table only parenttable;
TRUNCATE TABLE
=> select tableoid::regclass,count(*) from parenttable group by tableoid::regclass ;
  tableoid  | count 
------------+-------
 childtable |     1
 
--直接truncate继承父表，子表也会被清理
=>  truncate table parenttable;
TRUNCATE TABLE
=> select tableoid::regclass,count(*) from parenttable group by tableoid::regclass ;
 tableoid | count 
----------+-------
(0 rows)
```

**2**.`RESTART IDENTITY` `CONTINUE IDENTITY`:**列上**的序列是否要重置，默认CONTINUE。
```sql
--bigserial 默认会创建列上的序列
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
--seq当前值为1000
=> select currval('tableserial_a_seq'::regclass);
 currval 
---------
    1000

--直接truncate默认不会重置序列
=>  truncate table tableserial;
TRUNCATE TABLE
=> select currval('tableserial_a_seq'::regclass) cur,nextval('tableserial_a_seq'::regclass);
 cur  | nextval 
------+---------
 1000 |    1001

--显示指定RESTART IDENTITY，重置序列
=>  truncate table tableserial RESTART IDENTITY;
TRUNCATE TABLE
--注意seq在nextval时重置了
=>  select currval('tableserial_a_seq'::regclass) cur,nextval('tableserial_a_seq'::regclass);
 cur  | nextval 
------+---------
 1001 |       1
```

**3**.`CASCADE`：清理表及其所有外键表的数据
```sql
--创建主表和外键表和数据
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

--外键表frn_tab依赖主表pri_tab的数据
=> select * from frn_tab;
 id 
----
  1
  2
(2 rows)

--有主表外键reference时，外键表必须跟cascade，否则无法清理
=> truncate table pri_tab ;
ERROR:  0A000: cannot truncate a table referenced in a foreign key constraint
DETAIL:  Table "frn_tab" references "pri_tab".
HINT:  Truncate table "frn_tab" at the same time, or use TRUNCATE ... CASCADE.
LOCATION:  heap_truncate_check_FKs, heap.c:3427

--外键约束的表一起清空
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
由于外键表依赖主表的数据，不能直接truncate主表，必须加cascade，此时外键表也跟随主表一起清空

**4**.`RESTRICT`
是否清理foreign key表。没什么用，default选项，加不加都是这样。清理附带的外键表应加CASCADE。

# MVCC/transaction
pg官方文档有这么一段化
>`TRUNCATE` is not MVCC-safe. After truncation, the table will appear empty to concurrent transactions, if they are using a snapshot taken before the truncation occurred.
>`TRUNCATE` is transaction-safe with respect to the data in the tables: the truncation will be safely rolled back if the surrounding transaction does not commit.

transaction-safe意思是可以放在事务块里，可以回退
回滚truncate：
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
 not MVCC-safe意思是一个会话在truncate前打了一个快照，快照期间如果发生truncate，这个快照是可以读到truncate清理后的结果的。这不符合MVCC。
不过这个问题不算太大，在会话场景下，因为truncate是8级锁，快照没有结束的话最低在表上有一个读共享锁，所以truncate不会执行。
>This will only be an issue for a transaction that did not access the table in question before the DDL command started —any transaction that has done so would hold at least an `ACCESS SHARE` table lock, which would block the DDL command until that transaction completes
 

# 功能更新
![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/2c5bd7a69f4faab197b5190b8084a820.png)
truncate更新功能不多，只需要注意14的时候支持truncate foreign tables即可。truncate foreign tables前提是fdw得支持TRUNCATE API
>Also it extends postgres_fdw  so that it can issue TRUNCATE command to foreign servers, by adding  new routine for that TRUNCATE API.




# pg truncate和其他库的功能差异
![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/bbce89813b77e66e4a1a8f335ab7ec34.png)
![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/4d7ca906e1e45ee6ddf8b8e6e2b2a9ec.png)
truncate很快、8级锁等特性已经是人尽皆知的事情了，相对于其他数据库，pg还可以：**选择是否重置序列**（`RESTART IDENTITY` `CONTINUE IDENTITY`）、**回滚**、**简单的授权**。


# truncate做了什么
```sql
create table lzl(a int);
create index lzl_idx on lzl(a);
create sequence lzl_seq start with 1;
alter table lzl alter column a set default nextval('lzl_seq');
--select pg_relation_filepath('lzl');
```
```sql
--db路径
=> select oid from  pg_database where datname='lzldb';
  oid   
--------
 418679

--刚创建时候各个rel的oid=relfilenode
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
--truncate后，表和索引重建了，sequence却没有


M=> truncate table lzl RESTART IDENTITY;
TRUNCATE TABLE
=> select relname,oid,relfilenode,relkind from pg_class where  relname like 'lzl%';
 relname |  oid   | relfilenode | relkind 
---------+--------+-------------+---------
 lzl     | 428363 |      428372 | r
 lzl_idx | 428366 |      428373 | i
 lzl_seq | 428367 |      428367 | S
--显示restart，sequence还是没有重建


M=> alter sequence lzl_seq restart;
ALTER SEQUENCE
M=> select relname,oid,relfilenode,relkind from pg_class where  relname like 'lzl%';
 relname |  oid   | relfilenode | relkind 
---------+--------+-------------+---------
 lzl     | 428363 |      428372 | r
 lzl_idx | 428366 |      428373 | i
 lzl_seq | 428367 |      428374 | S
--显示restart sequence是会重建sequence的
```
`truncate ···RESTART IDENTITY`没有重建我们sequence，`alter sequence lzl_seq restart`重建了sequence。应该是`RESTART IDENTITY`没有理解对。在看下官方文档对`RESTART IDENTITY`的解释
>Automatically restart sequences owned by columns of the truncated table(s).

sequence必须`owned by`表上的列，注意不是`owner to`。虽然`\d`可以看到表上的sequence，但是它可能不属于表
```sql
 \d+ lzl;
                                              Table "public.lzl"
 Column |  Type   | Collation | Nullable |           Default            | Storage | Stats target | Description 
--------+---------+-----------+----------+------------------------------+---------+--------------+-------------
 a      | integer |           |          | nextval('lzl_seq'::regclass) | plain   |              | 
```


用`owned by`修改sequence的所属表
```sql
=> ALTER SEQUENCE lzl_seq OWNED BY lzl.a;
ALTER SEQUENCE

--查看序列的所有者信息
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
sequence owned by表上的列时，truncate显示带RESTART IDENTITY就会restart这个sequence，也就重建了sequence。**默认以serial/bigserial方式创建的序列是被表拥有的，随表drop而删除；那些不被表拥有的序列，drop不会删除**。
truncate重建特性汇总：
 - 直接truncate table会重建表和索引
 - **truncate table+RESTART IDENTITY，会重建（也就是retart）属于这个表的sequence。只要不属于这个表的sequence，哪怕列上关联了seq的默认值，也不会重建这个seq**。



# 源码分析
truncate也是utility命令，很快就可以找到入口函数
`src/backend/commands/tablecmds.c`中的`ExecuteTruncate`为入口函数，注释其实已经说明truncate要获得exclusive lock，并检查权限和relation是否ok，递归检查所有需要truncate的表
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
LOCKMODE lockmode = AccessExclusiveLock;  //8级锁
...

rel = table_open(myrelid, NoLock); //打开表


void
ExecuteTruncate(TruncateStmt *stmt)
{
...
	foreach(cell, stmt->relations)
	{
...
		LOCKMODE	lockmode = AccessExclusiveLock; //8级锁
...
		/* open the relation, we already hold a lock on it */
		rel = table_open(myrelid, NoLock); //打开表
...
		truncate_check_activity(rel);  //虽然已经有锁了，但是还是要验证是否在使用
...
		if (recurse) //递归执行
		{
...
			children = find_all_inheritors(myrelid, lockmode, NULL); //找到所有继承子表

			foreach(child, children)
			{
...
				 //上面只检查了父表，递归要检查子表
				truncate_check_rel(RelationGetRelid(rel), rel->rd_rel);
				truncate_check_activity(rel);

				rels = lappend(rels, rel);  //加入到待truncate的rel队列中
				relids = lappend_oid(relids, childrelid);
...
			}
		}
		//递归结束
		//发现truncate only分区父表，直接报错
		else if (rel->rd_rel->relkind == RELKIND_PARTITIONED_TABLE)
			ereport(ERROR,
					(errcode(ERRCODE_WRONG_OBJECT_TYPE),
					 errmsg("cannot truncate only a partitioned table"),
					 errhint("Do not specify the ONLY keyword, or use TRUNCATE ONLY on the partitions directly.")));
	}
		
	//主体函数	
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

`ExecuteTruncateGuts`函数不仅被truncate命令调用，还被订阅端调用（发布订阅可以同步truncate）。
```c
void
ExecuteTruncateGuts(List *explicit_rels,
					List *relids,
					List *relids_logged,
					DropBehavior behavior, bool restart_seqs)
{
...
	rels = list_copy(explicit_rels);
	if (behavior == DROP_CASCADE)  //如果指定了cascade选项,提取所有reference的relation
	{
		for (;;)
		{
...
			newrelids = heap_truncate_find_FKs(relids); //找到fk
			if (newrelids == NIL)
				break;			/* nothing else to add */ //没有rel直接退出

			foreach(cell, newrelids)
			{
...
				rel = table_open(relid, AccessExclusiveLock); //所有rel获得AccessExclusiveLock
				ereport(NOTICE,
						(errmsg("truncate cascades to table \"%s\"",
								RelationGetRelationName(rel))));
				truncate_check_rel(relid, rel->rd_rel);  //检查是否是可以truncate的对象，得是存储数据的表
				truncate_check_perms(relid, rel->rd_rel);  //检查是否有权限
				truncate_check_activity(rel);  //检查是否在使用
...
			}
		}
	}

...
	if (restart_seqs) //restart seq的处理
	{
		foreach(cell, rels)
		{
			Relation	rel = (Relation) lfirst(cell);
			List	   *seqlist = getOwnedSequences(RelationGetRelid(rel));
...
			//只是做sequence的权限检查
				if (!pg_class_ownercheck(seq_relid, GetUserId()))
					aclcheck_error(ACLCHECK_NOT_OWNER, OBJECT_SEQUENCE,
								   RelationGetRelationName(seq_rel));
...
		}
	}

...

	//执行所有before truncate触发器
	foreach(cell, rels)
	{
		ExecBSTruncateTriggers(estate, resultRelInfo);
		resultRelInfo++;
	}

//正式开始truncate
	foreach(cell, rels)
	{
...
		//如果是分区父表，啥都不做
		if (rel->rd_rel->relkind == RELKIND_PARTITIONED_TABLE)
			continue;

		//如果是foreign table的处理
		if (rel->rd_rel->relkind == RELKIND_FOREIGN_TABLE)
		{
		...
		}

...
		 //如果是同一事务，因为可能会回退，直接执行heap_truncate_one_rel函数，不创建新的relfilenode
		if (rel->rd_createSubid == mySubid ||
			rel->rd_newRelfilenodeSubid == mySubid)
		{
			/* Immediate, non-rollbackable truncation is OK */
			heap_truncate_one_rel(rel);
		}
		else
		{
...
			//设置NewRelfilenode
			RelationSetNewRelfilenode(rel, rel->rd_rel->relpersistence);

			heap_relid = RelationGetRelid(rel);

			 //toast同理
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
			 //重建索引
			reindex_relation(heap_relid, REINDEX_REL_PROCESS_TOAST,
							 &reindex_params);
		}

		pgstat_count_truncate(rel); //更新pgstat的truncate计算
	}

...
	//重置sequence 
	foreach(cell, seq_relids)
	{
		Oid			seq_relid = lfirst_oid(cell);

		ResetSequence(seq_relid);
	}

	//写wal
	if (list_length(relids_logged) > 0)
	{
	...
	}


	//触发AFTER TRUNCATE triggers
	resultRelInfo = resultRelInfos;
	foreach(cell, rels)
	{
		ExecASTruncateTriggers(estate, resultRelInfo);
		resultRelInfo++;
	}
...
}	
```
`ExecuteTruncateGuts`函数根据truncate选项进行处理，处理过程如下：
1. 根据cascade选项找到所有reference的外键表
2. 触发before truncate触发器
3. 执行truncate
 - 如果是同一事务，不立即生成`NewRelfilenode`，直接调用函数`heap_truncate_one_rel`进行truncate
 - 如果不是同一事务，调用`RelationSetNewRelfilenode`新建`NewRelfilenode`
4. `reindex_relation`函数重建索引
5. 根据restart identity重置sequence
6. 写wal日志
7. 触发after truncate触发器

后面大概追了下函数，套娃比较多
`RelationSetNewRelfilenode`
`table_relation_set_new_filenode`
`relation_set_new_filenode`在这里插入代码片
`heapam_relation_set_new_filenode`
`RelationCreateStorage`
然后到`src/backend/storage/smgr/smgr.c`中的`smgrcreate`和`smgr_create`。后面就没看太懂了（一到函数指针就有点追不到的感觉，先这样吧~）···
对于`smgr.c`有这样的注释：
> public interface routines to storage manager switch
> All file system operations in POSTGRES dispatch through these routines.

任何文件系统操作都会经过smgr（storage manager）；到这里就是文件系统操作了。

# reference
https://www.postgresql.org/docs/15/sql-truncate.html	
https://www.postgresql.org/docs/current/mvcc-caveats.html
https://pgpedia.info/t/truncate.html
https://www.orafaq.com/wiki/SQL_FAQ
https://learnsql.com/blog/difference-between-truncate-delete-and-drop-table-in-sql/



