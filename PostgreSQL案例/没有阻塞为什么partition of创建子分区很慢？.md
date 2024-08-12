
### create table.. partition of语句慢分析
```sql
2024-05-16 22:02:59.063 CST,"user1","dblzl",125889,"30.88.79.3:37423",66461213.1ebc1,2,"authentication",2024-05-16 22:02:59 CST,34/41364668,0,LOG,00000,"connection authorized: user=user1 database=dblzl",,,,,,,,,"","client backend"
2024-05-16 22:02:59.079 CST,"user1","dblzl",125889,"30.88.79.3:37423",66461213.1ebc1,3,"idle",2024-05-16 22:02:59 CST,34/41364669,0,LOG,00000,"statement:  -- a86fae372f73414bbe1af18213a47beb
/*a86fae372f73414bbe1af18213a47beb */
create table if not exists table1_partition_p2406 partition of table1 for values from ('2024-06-01 00:00:00') to ('2024-07-01 00:00:00'); ",,,,,,,,,"","client backend"
...
2024-05-16 22:38:28.555 CST,"user1","dblzl",125889,"30.88.79.3:37423",66461213.1ebc1,4,"CREATE TABLE",2024-05-16 22:02:59 CST,34/0,0,LOG,00000,"duration: 2129483.549 ms",,,,,,,,,"","client backend"
```
user1这个用户在22:02:59连接进入数据库后，立即就执行了一个`create table.. partition of..`的语句，直到22:38:28才跑完。中间的日志忽略了，一大堆会话阻塞信息，阻塞源均是125889这个会话。
被阻塞的会话类似如下：
```sql
process 33569 still waiting for RowExclusiveLock on relation 53733 of database 17073 after 1000.048 ms","Process holding the lock: 125889. Wait queue: 33569.
```
partition of添加分区时，会在主表上加8级锁，然后阻塞分区表上的所有操作。正常来说partition of添加分区是非常快的，锁也会立即释放。不过如果分区表上有长事务，那么这个主表上的8级锁得等着，然后就造成后续的阻塞。
盗[自己的图](https://blog.csdn.net/qq_40687433/article/details/132525655?ops_request_misc=%257B%2522request%255Fid%2522%253A%2522171591065916800225570929%2522%252C%2522scm%2522%253A%252220140713.130102334.pc%255Fblog.%2522%257D&request_id=171591065916800225570929&biz_id=0&utm_medium=distribute.pc_search_result.none-task-blog-2~blog~first_rank_ecpm_v1~rank_v31_ecpm-1-132525655-null-null.nonecase&utm_term=%E5%88%86%E5%8C%BA%E8%A1%A8&spm=1018.2226.3001.4450)：
![在这里插入图片描述](https://img-blog.csdnimg.cn/direct/a116bdcc67984fcf8c3f13faa9ed7e88.png)

然而这个案例表上没有长事务，partition of添加分区却执行了35分钟。
从历史的进程信息可以看出这个进程是D状态，是有问题的。刚开始以为是内存、磁盘这些问题，排查了一圈都正常。

然而这个问题很好复现，直接在仿真环境上跑一个`create table parttion of`执行会非常慢。pg_stat_activity会话信息显示，该语句等待在IO上：
```sql
wait_event_type  | IO
wait_event	 | DataFileRead
state		| active
query		| create table xxx partition of xx for values from ('2025-05-01 00:00:00') to ('2025-06-01 00:00:00');
```
strace追踪进程信息发现，该进程大量的读取一个文件
```sql
pread64(53, "\22\2\0\0\220w\321>\0\0\5\0\24\0018\1\0 \4 \0\0\0\0\200\237\0\1\310\236p\1"..., 8192, 863485952) = 8192
```
通过文件描述符53找到该文件
```sql
[/proc/356174/fd] ll |grep 53
lrwx------ 1 postgres postgres 64 May 17 15:34 53 -> /lzl/pglzl/data/base/17076/25883
```
```sql
oid2name -d lzldb  -f 25883
From database "lzldb":
  Filenode				   Table Name
-----------------------------------------------
     25883  table_partition_default
```
最后定位这个表table_partition_default
```sql
=> \d+ table_partition_default
...
Partition of: table_partition_default DEFAULT
Partition constraint: (NOT ((date_created IS NOT NULL) AND ((date_created < '2022-05-01 00:00:00'::timestamp without time zone) OR ((date_created >= '2022-05-01 00:00:00'::timestamp without time zone) AND (da


=> \dt+ table_partition_default
                                          List of relations
 Schema |                Name             | Type  | Owner | Persistence | Size  | Description 
--------+------------------------------------+-------+------------+-------------+-------+-------------
 public | table_partition_default         | table | user1 | permanent   | 50 GB | 
(1 row)
```
原来是default分区表，分区数据有几十GB。oracle dba可能很陌生···pg的default分区会接收不在分区范围中的数据，default分区可以保证即使没有定义到数据范围，也可以接收数据。
如果有数据存在default分区中，新分区又需要包含这部分数据，那这个游戏咋玩呢···直接报错：
```sql
=> create table if not exists table_partition_pxxxx partition of table_partition for values from ('2023-01-12 00:00:00') to ('2023-01-13 00:00:00');
ERROR:  23514: updated partition constraint for default partition "table_partition_default" would be violated by some row
SCHEMA NAME:  public
TABLE NAME:  table_partition_default
LOCATION:  check_default_partition_contents, partbounds.c:3227
```
可以看到，添加子分区时，会自动修改default分区的分区约束（Partition constraint）,default分区约束检查即是在做添加普通子分区时的default分区数据校验。

到这原因已经很明显：
分区表新增子分区时，由于建分区的语句需要校验default分区中的数据，保证新分区数据范围与default分区的现有数据不冲突，导致`create table partition of`读取了大量的default分区数据，新建分区一直未完成。随后阻塞扩大，业务数据无法查询和写入。


### 小结和建议
postgresql分区表使用的越来越多了，维护分区还有很多需要注意的知识点，推荐看下[PostgreSQL分区表](https://blog.csdn.net/qq_40687433/article/details/132525655?ops_request_misc=%257B%2522request%255Fid%2522%253A%2522171591065916800225570929%2522%252C%2522scm%2522%253A%252220140713.130102334.pc%255Fblog.%2522%257D&request_id=171591065916800225570929&biz_id=0&utm_medium=distribute.pc_search_result.none-task-blog-2~blog~first_rank_ecpm_v1~rank_v31_ecpm-1-132525655-null-null.nonecase&utm_term=%E5%88%86%E5%8C%BA%E8%A1%A8&spm=1018.2226.3001.4450)，几乎面面俱到。

在这个案例中，改造关键在于default分区的数据。在default改造前，不要使用partition of方式创建子分区。
default分区改造方案：
1. detach default子分区，然后合理创建子分区，再将default表数据回插到分区表中。
2. 如有必要，可在detach且创建合理子分区后，创建一个空的default分区，以保持业务数据的连续性。
3. 注意detach跟attach不同，detach需要主表的8级锁。PG14支持detach concurrently。

如不改造default分区，应检查当前default分区的数据范围。再用attach添加子分区，会很慢，但不会阻塞读写。

最后在复习下分区表新增分区最佳实践：
partition of添加子分区要申请主表的8级锁，风险还是有的。推荐attach方式为表新增子分区（分区索引也可以这么做），不会阻塞读写，完全不影响业务，可在线执行。
**分区表添加新分区的正确姿势**：
```sql
CREATE TABLE lzlpartition1_202303
  (LIKE lzlpartition1 INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
alter table LZLPARTITION1 attach partition LZLPARTITION1_202303 for values from ('2023-03-01 00:00:00') to ('2023-04-01 00:00:00');
```
如果新分区还有数据的话，attach还可能比较慢，可提前创建约束来优化
**分区表添加有数据分区的正确姿势**：
```sql
--减少繁琐的ddl，like方式创建表
CREATE TABLE lzlpartition1_202303
  (LIKE lzlpartition1 INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
--无数据可忽略该步骤。参考其他分区的Partition constraint，添加表的check约束，减少attach检查约束的时间。
alter table lzlpartition1_202303 add constraint chk_202303 CHECK ((date_created IS NOT NULL) AND (date_created >= '2023-03-01 00:00:00'::timestamp without time zone) AND (date_created < '2023-04-01 00:00:00'::timestamp without time zone));
--attach方式添加分区
alter table LZLPARTITION1 attach partition LZLPARTITION1_202303 for values from ('2023-03-01 00:00:00') to ('2023-04-01 00:00:00');
--可选。在新分区有事务之前，删除多余的check约束
alter table lzlpartition1_202303 drop constraint  chk_202303;
```

