之前已经写过一篇比较详细的[关于逻辑复制的文章](https://blog.csdn.net/qq_40687433/article/details/129291207?ops_request_misc=%257B%2522request%255Fid%2522%253A%2522170082845616800211565759%2522%252C%2522scm%2522%253A%252220140713.130102334.pc%255Fblog.%2522%257D&request_id=170082845616800211565759&biz_id=0&utm_medium=distribute.pc_search_result.none-task-blog-2~blog~first_rank_ecpm_v1~rank_v31_ecpm-1-129291207-null-null.nonecase&utm_term=%E9%80%BB%E8%BE%91%E5%A4%8D%E5%88%B6&spm=1018.2226.3001.4450)了，这里不会再重复描述一些基础知识。不过难免有些知识点有遗漏，最近发一些有意思的逻辑复制特性。

# replica identity与old/new值

replica identity是用来在逻辑复制期间标识一行数据的。
上面这句话当然没有问题，但是没有解释old和new数据的变化。

>`DEFAULT`
>Records the old values of the columns of the primary key, if any. This is the default for non-system tables.
>`USING INDEX` index_name
>Records the old values of the columns covered by the named index, that must be unique, not partial, not deferrable, and include only columns marked `NOT NULL`. If this index is dropped, the behavior is the same as `NOTHING`.
>`FULL`
>Records the old values of all columns in the row.
>`NOTHING`
>Records no information about the old row. This is the default for system tables.

pg官方文档对于replica identity甚至只解释了old值的情况，例如nothing不复制update/delete都没解释，足见old值的重要性。


创建一个复制链路：

```sql
select pg_create_logical_replication_slot('pubtestlzl2','test_decoding');
pg_recvlogical -d lzldb --slot=pubtestlzl2 --start -f recv.sql &
```

test_decoding的复制链路正常模拟

```sql
--replica identity默认是d：有主键时用主键；没有主键时为nothing，无法复制update和delete
M=>  create table lzltest(a bigint primary key,b varchar(100),c varchar(100));
CREATE TABLE
M=> insert into lzltest values(1,'bbbbbb','ccccccccc');
INSERT 0 1
M=> update lzltest set b='b';
UPDATE 1
```

recvlogical输出

```sql
table public.lzltest: INSERT: a[bigint]:1 b[character varying]:'bbbbbb' c[character varying]:'ccccccccc'
table public.lzltest: UPDATE: a[bigint]:1 b[character varying]:'b' c[character varying]:'ccccccccc'
```

replica identity为default，更新非主键字段，所有字段只有new值

```sql
M=> update lzltest set a='111';
UPDATE 1
table public.lzltest: UPDATE: old-key: a[bigint]:1 new-tuple: a[bigint]:111 b[character varying]:'bb' c[character varying]:'ccccccccc'
```

replica identity为default，更新主键时，解析出了主键标识的old和new值，其他字段只有new值

```sql
M=> alter table lzltest replica identity full;
ALTER TABLE

M=>  update lzltest set b='b';
UPDATE 1
table public.lzltest: UPDATE: old-key: a[bigint]:2 b[character varying]:'b' c[character varying]:'ccccccccc' new-tuple: a[bigint]:2 b[character varying]:'b' c[character varying]:'ccccccccc'
```

replica identity设置为full，保留整行数据的old和new值

无论是default（主键）还是full模式，都会记录所有字段的信息，区别在于是否有old数据。default时：

 - insert：本身是new数据，当然没有old值，会记录new值的所有字段
 - update：记录所有字段的new值，**只有标识字段才有old值（如果有更新标识字段）**
 - delete：本身是old数据，不一定记录所有字段。同样适用*只有标识字段才有old值*，只记录标识位。

**总结：当replica identity为default时，无论什么操作（INSERT,UPDATE,DELTE)，只要是old数据，只记录标识字段；只要是new数据，记录所有字段**。
把default修改为full时，解析出来的日志量差别不会特别大，因为new数据永远是所有字段，（不考虑*全是*delete的场景下）full解析出的日志量小于default时的两倍。


# pgoutput不能peek

用pgoutput去创建一个复制槽

```sql
select pg_create_logical_replication_slot('pubtestlzl','pgoutput');
```

然后去peek或者接收，都失败

```sql
select * from pg_logical_slot_peek_changes('pubtestlzl',null,null);
pg_recvlogical -d lzldb --slot=pubtestlzl --start -f recv.sql &
```

```c
pg_recvlogical: error: could not send replication command "START_REPLICATION SLOT "pubtestlzl" LOGICAL 0/0": ERROR:  client sent proto_version=0 but we only support protocol 1 or higher
CONTEXT:  slot "pubtestlzl", output plugin "pgoutput", in the startup callback
pg_recvlogical: disconnected; waiting 5 seconds to try again
```

不能peek或pg_recvlogical去接收pgoutput的复制槽。由于pgoutput是发布订阅的output plugin，这个plugin不能人工去peek或接收···

# 发布订阅可以不在pg-pg之间

`create publication`、`create subscription`都是pg内部的命令，也可以用他们来创建pg库之间的链路。
三方软件同样可以使用创建发布，并模拟订阅并创建复制槽。这样比直接创建复制槽要更好，因为可以通过发布管理复制表。

# toast和逻辑解析

发送toast的字段不会被解析！也就是说整行数据可能只有一部分会传递出来（toast字段本身没有更新的情况下）
正常解析会解析所有字段：

```sql
--创建一个test-coding的复制槽
=>  select pg_create_logical_replication_slot('logical_dest','test_decoding');
 pg_create_logical_replication_slot 
------------------------------------
 (logical_dest,349/A80040E0)
(1 row)

--创建一个小字段的表
=> create table test1(a int primary key,b varchar(100),c varchar(100));
CREATE TABLE

=> select* from pg_replication_slots;
  slot_name   |    plugin     | slot_type | datoid | database | temporary | active | active_pid |  xmin  | catalog_xmin | restart_lsn  | confirmed_flush_lsn | wal_status | safe_wal_size 
--------------+---------------+-----------+--------+----------+-----------+--------+------------+--------+--------------+--------------+---------------------+------------+---------------
 logical_dest | test_decoding | logical   | 418679 | lzldb    | f         | f      |     [null] | [null] |    872483335 | 349/A80040A8 | 349/A80040E0        | reserved   |        [null]
(1 row)


=>  insert into test1 values (1,'qwer','qwer');
INSERT 0 1
Time: 0.915 ms
=> select * from pg_logical_slot_peek_changes('logical_dest',null,null);
     lsn      |    xid    |                                               data                                               
--------------+-----------+--------------------------------------------------------------------------------------------------
 349/A8004C78 | 872483335 | BEGIN 872483335
 349/A80103E8 | 872483335 | COMMIT 872483335
 349/A8018B30 | 872483369 | BEGIN 872483369
 349/A8018B30 | 872483369 | table public.test1: INSERT: a[integer]:1 b[character varying]:'qwer' c[character varying]:'qwer'
 349/A8018C50 | 872483369 | COMMIT 872483369
(5 rows)
--insert被解析，包含所有字段

=> update test1 set b='zxcv' where c='qwer';
UPDATE 1
Time: 4.005 ms
=>  select * from pg_logical_slot_peek_changes('logical_dest',null,null);
     lsn      |    xid    |                                               data                                               
--------------+-----------+--------------------------------------------------------------------------------------------------
 349/A8004C78 | 872483335 | BEGIN 872483335
 349/A80103E8 | 872483335 | COMMIT 872483335
 349/A8018B30 | 872483369 | BEGIN 872483369
 349/A8018B30 | 872483369 | table public.test1: INSERT: a[integer]:1 b[character varying]:'qwer' c[character varying]:'qwer'
 349/A8018C50 | 872483369 | COMMIT 872483369
 349/A801D018 | 872483378 | BEGIN 872483378
 349/A801D018 | 872483378 | table public.test1: UPDATE: a[integer]:1 b[character varying]:'zxcv' c[character varying]:'qwer'
 349/A801D098 | 872483378 | COMMIT 872483378
(8 rows)
--update被解析，包含所有字段
```

正常来说，没有toast时，解析出来的数据是包含该行所有字段的数据的。


toast解析测试：

```sql
--将字段改大
=>  alter table test1 alter column b type varchar(3000);
ALTER TABLE
Time: 8.091 ms
=>   alter table test1 alter column c type varchar(3000);
ALTER TABLE
Time: 0.937 ms

--一个批量random的function
=> create or replace function f_random_str(length INTEGER) returns character varying
-> LANGUAGE plpgsql
-> AS $$
-> DECLARE
-> result varchar(3000);
-> BEGIN
-> SELECT array_to_string(ARRAY(SELECT chr((65 + round(random() * 25)) :: integer)
-> FROM generate_series(1,length)), '') INTO result;
-> return result;
-> END
-> $$;
CREATE FUNCTION

--插入数据
=>  insert into test1 values (2,f_random_str(2000),f_random_str(2000));
INSERT 0 1

--查看是否有toast
=> SELECT                                              
->   n.nspname as schema,                              
-> s.oid::regclass as relname,                     
-> s.reltoastrelid::regclass as toast_name,        
-> pg_relation_size(s.reltoastrelid) AS toast_size 
->   FROM                                              
-> pg_class s join pg_namespace n                  
-> on s.relnamespace = n.oid                       
->   WHERE                                             
-> relkind = 'r'                                   
-> AND reltoastrelid <> 0                          
-> AND n.nspname = 'public'                        
->   ORDER BY                                          
-> 3 DESC;
 schema | relname |        toast_name        | toast_size 
--------+---------+--------------------------+------------
 public | test1   | pg_toast.pg_toast_418714 |       8192
(1 row)

--通过主键进行更新，更新toast字段
=> update test1 set b='zxcv' where a=2;
UPDATE 1

=>  select * from pg_logical_slot_peek_changes('logical_dest',null,null);
     lsn      |    xid    |                                                                                                                                                                                      
--------------+-----------+--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
...
 349/A851FD90 | 872483420 | BEGIN 872483420
 349/A85216E0 | 872483420 | table public.test1: INSERT: a[integer]:2 b[character varying]:'GIORCXQQWDBGTUNDZXAWMPYOUEGTECWTVQGDQGSPMEPJNPUQIFMESLRASBZWGONETRENDCHLDWVTDWJLTGRYUMFDOWHLEYLUTECPOVCYXFIATLKVEQTHSC'
 349/A85218A0 | 872483420 | COMMIT 872483420
 349/A8525CA8 | 872483429 | BEGIN 872483429
 349/A8525D50 | 872483429 | table public.test1: UPDATE: a[integer]:2 b[character varying]:'zxcv' c[character varying]:unchanged-toast-datum
 349/A8525DE0 | 872483429 | COMMIT 872483429
```

 有toast的字段c，不涉及更新，没有解析的数据，直接抛出toast数据未变`unchanged-toast-datum`

 用wal2json测试：

 ```sql
=>  select pg_create_logical_replication_slot('logical_json','wal2json');
 pg_create_logical_replication_slot 
------------------------------------
 (logical_json,349/A87CAB58)
(1 row)

=>  update test1 set b='zxcv' where a=2;
UPDATE 1
=>  \pset format wrapped
Output format is wrapped.
=>  \pset columns 200
Target width is 200.
=>  select * from pg_logical_slot_peek_changes('logical_json',null,null);
-[ RECORD 1 ]------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
lsn  | 349/A87CACF8
xid  | 872483495
data | {"change":[{"kind":"update","schema":"public","table":"test1","columnnames":["a","b"],"columntypes":["integer","character varying(3000)"],"columnvalues":[2,"zxcv"],"oldkeys":{"keynames":["a"],.
     |."keytypes":["integer"],"keyvalues":[2]}}]}

=> update test1 set b='zxcv' where a=1;
UPDATE 1
Time: 1.391 ms
=>  select * from pg_logical_slot_peek_changes('logical_json',null,null);
-[ RECORD 1 ]------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
lsn  | 349/A87CACF8
xid  | 872483495
data | {"change":[{"kind":"update","schema":"public","table":"test1","columnnames":["a","b"],"columntypes":["integer","character varying(3000)"],"columnvalues":[2,"zxcv"],"oldkeys":{"keynames":["a"],.
     |."keytypes":["integer"],"keyvalues":[2]}}]}
-[ RECORD 2 ]------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
lsn  | 349/A8CCA0D8
xid  | 872483509
data | {"change":[{"kind":"update","schema":"public","table":"test1","columnnames":["a","b","c"],"columntypes":["integer","character varying(3000)","character varying(3000)"],"columnvalues":[1,"zxcv".
     |.,"qwer"],"oldkeys":{"keynames":["a"],"keytypes":["integer"],"keyvalues":[1]}}]}
 --更新时，解析出来没有c列的数据   
 ```

wal2json也是一样的效果。

mysql的参数[`binlog_row_image`](https://dev.mysql.com/doc/refman/8.0/en/replication-options-binary-log.html#sysvar_binlog_row_image)可以调整binlog是否记录大字段：

 - `full` (Log all columns)
 - `minimal` (Log only changed columns, and columns needed to identify rows)
 - `noblob` (Log all columns, except for unneeded BLOB and TEXT columns)

pg库完全没有这种控制，默认就是toast字段不解析，无其他选项可以设置~
