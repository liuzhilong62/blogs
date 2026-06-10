---
title: "PostgreSQL DDL变更的坑和巧妙方案"
date: 2025-07-19
categories: [PostgreSQL内功修炼]
description: "总结PostgreSQL DDL变更中的常见陷阱与巧妙解决方案，一图速查避坑指南。"
---

![DDL变更.png](/img/csdn/5f610ac9b703.png)



## 理解这个图的关键点

变更前的注意事项：

* 确保表上没有长事务——长事务会长期持有表上的锁，长事务在 pg 中是危害这是共识，应先处理长事务
* 确保表上没有 autovacuum (to prevent wraparound)——autovacuum 一般不会阻塞 SQL，但做 `to prevent wraparound` 的[除外](https://www.postgresql.org/docs/18/routine-vacuuming.html#VACUUM-FOR-WRAPAROUND)
  > Autovacuum workers generally don't block other commands. If a process attempts to acquire a lock that conflicts with the `SHARE UPDATE EXCLUSIVE` lock held by autovacuum, lock acquisition will interrupt the autovacuum. However, if the autovacuum is running to prevent transaction ID wraparound (i.e., the autovacuum query name in the `pg_stat_activity` view ends with `(to prevent wraparound)`), the autovacuum is not automatically interrupted.
  >

* lock_timeout=2000——即拿不到锁超过 2s 就不拿了，以免引发大面积阻塞


字段小改大的特例：

* 字段小改大一般不会重写表，但有几个例外。特别要注意 int->bigint（常见主键字段）, char(n)->char(m)）
* 分区表索引。分区表字段小改大不会重写表，但会重建索引，而分区表重建索引一般都非常慢，很可能造成长期 8 级锁阻塞。这个特性是普通表没有的。


修改字段类型：

* 基本都会重写表，除了一些类型等价，或者属于另一种小改大的


DDL 降低锁级别的注意点：

* 索引用 CIC，分区不支持就子表 CIC（记得 attach index）
* 添加主键用 using index，分区不支持就利用“子表加主键 + 父表添加主键可合并已存在的子表主键的特性”
* 约束用 validate constraint
* 17 以前不支持 not null validate，可以用 check(col1 IS NOT NULL)。这个 check 转 not null 也不会产生多余的扫描
* 加字段有 default 易失会重写，可以用非易失不重写特性先加字段，不会重写。存量数据看情况 update
* 分区表 attach 时可以利用 check 约束减少停机时间，而添加 check 约束又可以用到 validate constraint
* create table like+attach 比 partition of 的锁低很多（但我还是喜欢 parition of）


变更后的注意事项：

* 记得收集统计信息（很多场景需要）

## 案例
### 示例-26年分区创建不了，default分区转普通分区

```sql
1.确认default数据范围
select min(created_date),max(created_date) from lzltab_new_default;  --仅有24年的数据
2. default分区添加check约束
alter table lzltab_new_default add constraint const_checkit_lzl01
CHECK ((created_date IS NOT NULL) AND (created_date>='2024-01-01 00:00:00'::timestamp(6) without time zone) AND (created_date<'2025-01-01 00:00:00'::timestamp(6) without time zone)) not valid;
3. validate check
ALTER TABLE lzltab_new_default VALIDATE CONSTRAINT const_checkit_lzl01;   --SHARE UPDATE EXCLUSIVE 
4.detach default 分区
ALTER TABLE lzltab detach partition lzltab_new_default;
alter table lzltab_new_default rename to lzltab_new_2024;
5.attach为普通分区
alter table lzltab attach partition lzltab_new_2024 for values from ('2024-01-01 00:00:00'::timestamp(6) without time zone) to  ('2025-01-01 00:00:00'::timestamp(6) without time zone);
6.新建子分区
\i add_partition_lzltab.sql
7.删除check约束
alter table lzltab_new_2024 drop constraint const_checkit_lzl01;
8.创建default分区
CREATE TABLE lzltab_default partition of lzltab default;
```
因为default写入的是24年的数据，所以全程变更业务是无感的
如果default写入的当前数据，那么可以create table like +attach的方式创建未来分区，等它不再写default的时候再改造
