

# 问题描述
postgresql数据库执行delete报错：```attempted to delete invisible tuple```，执行同样条件的select不报错
```sql
delete from lzltab1;
select count(*) from  lzltab1;
```
执行全表删除和全表查询的结果：
```sql
M=# delete from lzltab1;
ERROR:  55000: attempted to delete invisible tuple
LOCATION:  heap_delete, heapam.c:2500
Time: 511.050 ms
```
```sql
M=#   select count(*) from  lzltab1;
 count  
--------
 231187
 ```
 delete找到了不可见的元组，select却是正常的 。
当时觉得很奇怪。pg的可见性通过元组的xmin,xmax,cid和快照的xmin，xmax，xip_list判断的，虽然delete元组的事务状态和时间会对可见性产生影响，但是表数据如果稳定（当前没有任何dml操作的话），随后的任何快照进去拍摄，都应该是一个稳定的可见集，它并不存在当前事务可见性判断，dml事务元组可见性判断也应该一致。也就是说这种场景下，select快照和delete快照不应该有这种差异。
# 问题分析
## 找到源码
注意报错信息```heapam.c:2500```
找到源码位置```src/backend/access/heap/heapam.c```
2500的行是空的，附近的代码如下
```c
	/*
	 * Before locking the buffer, pin the visibility map page if it appears to
	 * be necessary.  Since we haven't got the lock yet, someone else might be
	 * in the middle of changing this, so we'll need to recheck after we have
	 * the lock.
	 */

	if (PageIsAllVisible(page))
		visibilitymap_pin(relation, block, &vmbuffer);

	LockBuffer(buffer, BUFFER_LOCK_EXCLUSIVE);
```
从源码看，它在尝试获得vm上的锁，看来问题跟vm文件相关。

## vm文件
**什么是vm文件？**
vm文件是为了减少vacuum扫描page时间的，如果一个page不需要vacuum那么它应该可以被vacuum跳过，这样可以大大减少vacuum寻找需要清理的page的时间，这是vm文件最初的目的。（有时候也会被index-only scan使用，不过我们这里不会涉及，我们用的是全表扫描）
vm文件包含两个信息：
 1. page中的元组是不是都是可见的。说明page中没有需要被vacuum的死元组
 2. page中的元组是不是都是冻结的。说明vacuum freeze不需要访问这个page

![Fig. 6.2. How the VM is used.](https://i-blog.csdnimg.cn/blog_migrate/ccb1a1be80037d514c666dc272d4869c.png)

vm会帮助vacuum寻找死元组，减少扫描的页的数量。比如上面这个图（interdb yyds！），第一个页面1st不包含死元组，那么vacuum就可以跳过这个页面。

**找到vm文件**
每个表都有Visibility Map (VM)（索引没有vm文件），单独存放在表文件的旁边，如果一个表的filenode为```12345```，那么vm文件应该是```12345_vm```
首先cd到data目录
```shell
M=# show data_directory;
    data_directory    
----------------------
 /pg/pg6666/data
 ```
通过database oid，表的oid可以找到文件存储的位置
```sql
=# select oid,datname from pg_database where datname='sdp';
-------+----------------------
  oid  |  datname
 17075 | sdp
=# select  oid,relname from pg_class where relname='lzltab1';     
-------+----------------------
 17362 | lzltab1
 ```
 or
 ```sql
 #  select pg_relation_filepath('lzltab1');
 pg_relation_filepath 
----------------------
 base/17075/17362
 ```
 找到数据文件和vm
 ```shell
$ cd  /pg/pg6666/data/base/17075
$ ll 17362*
-rw------- 1 postgres postgres 86761472 Jun 15 17:43 17362
-rw------- 1 postgres postgres    40960 Jun  9 21:09 17362_fsm
-rw------- 1 postgres postgres     8192 Nov 14  2022 17362_vm
```

## pg_visibility插件
pg_visibility提供通过检查vm文件输出页级别的可见性信息，而且可以检测vm是否损坏。因为vm存储了“*page中的元组是不是都是可见的；page中的元组是不是都是冻结的*”这些信息，pg_visibility可以检查出哪些页是all-frozen的，哪些是all-visible的。
pg_visibility插件使用参考：<https://www.postgresql.org/docs/current/pgvisibility.html>
### 会用到的pg_visibility中的function

**pg_visibility_map_summary()**：显示vm中的all-visible页和all-frozen页
**pg_check_frozen()**：有元组不是frozen的，但在它所在的页在vm中被标记为了all-frozen，如果该函数有返回，表示vm文件损坏。
**pg_check_visible()**：有元组不是visible的，但在它所在的页在vm中被标记为了all-visible，如果该函数有返回，表示vm文件损坏。
**pg_truncate_visibility_map()**：清理vm文件。清理vm后，当表首次执行vacuum时，会扫描表上的所有页并重建vm。
## 修复vm文件
检查vm是否损坏
```sql
M=# select pg_visibility_map_summary('lzltab1');
 pg_visibility_map_summary 
---------------------------
 (472,0)
```
all-visible 472页，all-frozen 0页

```sql
M=# select pg_check_frozen('lzltab1');
 pg_check_frozen 
-----------------
(0 rows)
M=#  select pg_check_visible('lzltab1');
 pg_check_visible 
------------------
 (6839,1)
 (6839,2)
 ...
  (7296,15)
(1423 rows)
```
pg_check_visible()有结果说明**vm已经损坏了**
然后用pg_truncate_visibility_map()执行清空vm

```sql
M=# select   pg_truncate_visibility_map('lzltab1');
 pg_truncate_visibility_map 
----------------------------
```
从磁盘上也能看出来vm被清空了
 ```shell
   ll 17362*
-rw------- 1 postgres postgres 86761472 Jun 27 10:39 17362
-rw------- 1 postgres postgres    40960 Jun  9 21:09 17362_fsm
-rw------- 1 postgres postgres        0 Jun 27 18:18 17362_vm
```
然后我们验证一下，vacuum表看下是否会生产vm文件，并检验vm文件是否没有损坏
```sql
M=# vacuum lzltab1;
VACUUM
Time: 3692.402 ms (00:03.692)
M=# \q
$ ll 17362*
-rw------- 1 postgres postgres 86761472 Jun 28 03:37 17362
-rw------- 1 postgres postgres    40960 Jun  9 21:09 17362_fsm
-rw------- 1 postgres postgres     8192 Jun 28 10:21 17362_vm
```
可以看到手动vacuum后vm正常生成
```sql
M=# select pg_check_visible('lzltab1');
 pg_check_visible 
------------------
(0 rows)

M=# select pg_check_frozen('lzltab1');
 pg_check_frozen 
-----------------
(0 rows)
```
check检查后没有输出，vm文件正常，修复完成。

最后再来跑下sql
```sql
# delete from lzltab1;
DELETE 229766
```
delete执行正常，问题解决
## 检查全库是否有vm损坏
虽然我们解决了一个vm文件损坏的问题，但是仍然需要全库检查是否有其他的vm损坏（前提是安装了extension pg_visibility)
```sql
SELECT oid::regclass AS relname
FROM pg_class
WHERE relkind IN ('r', 'm', 't') AND (
  EXISTS (SELECT * FROM pg_check_visible(oid))
  OR EXISTS (SELECT * FROM pg_check_frozen(oid)));
  ```
如果返回非空结果，说明有vm损坏了。就像上面的方法，用pg_truncate_visibility_map()清理vm，然后vacuum生成一个vm。
如果是9.6前的版本，因为没有pg_visibility插件，需要停库然后手动删除vm文件，再启动数据库，然后再vacuum生成一个vm。


# 为什么vm会损坏？
我们通过一步步分析，检查到是vm文件损坏了，但是vm为什么会损坏呢？
 1. pg数据库的bug。pg确实有些bug会导致vm损坏（参考wiki Visibility Map Problems），不过这些都是pg9.6.1以前的
 2. 操作系统和硬件问题

我们版本是pg13的，问题基本只能笼统地归于操作系统或者硬件问题。
# 为什么select没有问题，delete报错？
select全表正常，delete全表报错，看上去就很奇怪。问题的根因是vm文件的损坏。
就像前面说的，vm文件是为了加快vacuum效率的，我们虽然没有做vacuum，而vm文件总要更新的吧？dml每次都会去更新vm（至少要检查），而select不会改变vm状态的。所以本案例中select正常执行，delete在执行到vm的处理时报错。
我们的案例中，delete扫描了vm找到了all-visible的页，但是vm标记错了，这些页上仍然有不可见的元组，这里就对应了开头的报错`attempted to delete invisible tuple`。不可见的元组可能已经被delete了，再次跑delete当然会报错，这也违背了事务的可见性规则。
另外，如果是index-only-scan也会用到vm文件，所以也会影响select语句，不过这个案例是全表扫描的，所以select没有问题。

# vm损坏导致index-only-scan出现错误的数据结果
前面在介绍vm的时候提到处理vacuum外，index-only-scan也会用到vm文件，虽然我们这个案例没有涉及index-only-scan，但本着研究透彻的原则，把问题搞清楚。
## 什么是index-only-scan
index-only-scan顾名思义就是仅索引扫描。在访问数据的时候不需要访问表，而只访问索引结构就能得到想要的结果。几乎所有的关系型数据库都有仅索引扫描，因为B+树索引结构保存了键值，如果查询只查了键值，那么仅索引扫描就是可能的。
但是，postgresql因为其事务实现跟其他数据库（Oracle、mysql）有很大的不同，它的仅索引扫描index-only-scan有一些特殊性。
postgresql通过元组头部的xmin、xmax等信息，校验元组和事务的可见性，而索引上没有这些信息，所以就导致pg的仅索引扫描必须访问数据块来检查可见性。这个时候vm的作用就体现了出来，因为vm文件中保存了all-visible，all-frozen的信息，这些被标记的页其实不需要校验元组可见性，因为他们已经被vm标记为可见了。
![Fig. 7.7. How Index-Only Scans performs](https://i-blog.csdnimg.cn/blog_migrate/b601cc6d8f18e1e1d8bb28e2644eddf5.png)
再来一个interdb的图（interdb yyds！）。当一个sql查询在访问key是18和19两个元组时，key=18元组所在的页已经被vm标记为all-visible了，所以访问key=18的元组只需要访问索引页和vm文件；而key=19的元组所在的页没有被标记为all-visible，仅索引扫描还是要访问所在数据页获取元组可见信息。
## index-only-scan查询出错误的结果
因为index-only-scan要访问vm，而vm损坏而保存了错误的信息，比如页中的元组本来不是所有都可见的（比如几个元组被delete了），但是页还是在vm中被标记为all-visible，导致index-only-scan没有进数据页检测元组可见性，直接返回了索引页上的本来是不可见的键值。
可以设置`enable_indexonlyscan=off`来关闭index-only-scan特性，保证数据的正确性；当然也可以像上面那样去修复vm文件，也许是更好的选择。

# 总结
虽然刚开始有些曲折，一看报错以为是事务可见性规则出现了问题，这个有问题的话问题就有点大了，但是实际上要简单的多。
我们从报错```attempted to delete invisible tuple```分析到源码，并定位到了是vm问题，再通过pg_visibility插件检测出vm corrupt并修复了vm文件，从而解决了delete报错，最后扩展了一下index-only-scan和vm。
总结一下文章的知识点：
 - pg_visibility插件可以读取、检测、清理vm文件
 - 如果没有vm信息的话，vacuum会生成新的vm
 - dml会读取/更新vm文件，select不会（非index-only-scan）
 - vm文件是为了提升vacuum的效率，有时候也会提升index-only-scan的效率
 - ```attempted to delete invisible tuple```报错应该检查vm文件是否损坏
 - vm文件损坏会造成dml失败，也会造成index-only-scan查询出错误的结果

# 参考
https://www.postgresql.org/docs/13/pgvisibility.html
https://wiki.postgresql.org/wiki/Visibility_Map_Problems
https://www.interdb.jp/pg/pgsql06.html
https://www.interdb.jp/pg/pgsql07.html

