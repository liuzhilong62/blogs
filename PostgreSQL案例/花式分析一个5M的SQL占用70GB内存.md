## 进程内存分析

```shell
"WAL writer process (PID 66902) was terminated by signal 6: Aborted",,,,,,,,,"","postmaster"
```

从日志中找到被kill的postmaster进程66902

到osw中找进程消耗的内存。由于top没有PPID，PS没有USS信息，所以要两个一起看

```shell
USER        PID   PPID PRI %CPU %MEM    VSZ   RSS WCHAN                                      S  STARTED     TIME COMMAND
postgres 211276  66478  19  8.7 10.6 57488380 56389972 -                                     R 17:13:03 00:02:47 postgres: BIND
postgres 211277  66478  19  7.8  9.6 52294700 51127480 -                                     R 17:13:03 00:02:31 postgres: BIND
postgres 222749  66478  19 22.7  9.3 51320000 49073368 -                                     R 17:35:33 00:02:09 postgres: BIND
postgres  39513  66478  19  2.9  6.8 38651084 36354736 ep_poll                               S 16:13:03 00:02:43 postgres: idle
```

通过PPID找个backend消耗较高的进程，比如211276进程进行进一步分析

```shell
[postgres@lzl]$ zcat /osw/oswtop/toposw.dat.gz |grep 211276

   PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND
211276 postgres  20   0 3271756   1.1g   1.1g S   7.3  0.2   0:03.93 postgres
211276 postgres  20   0 3291784   1.3g   1.2g R  96.4  0.2   0:11.87 postgres
211276 postgres  20   0 7369628   6.0g   2.1g R 100.0  1.2   0:46.58 postgres
211276 postgres  20   0   17.0g  15.9g   2.1g R 100.0  3.2   1:16.70 postgres
211276 postgres  20   0   28.8g  27.7g   2.1g R 100.0  5.5   1:46.82 postgres
211276 postgres  20   0   41.4g  40.4g   2.1g R 100.0  8.0   2:16.99 postgres
211276 postgres  20   0   54.7g  53.7g   2.1g R  88.8 10.7   2:47.60 postgres
211276 postgres  20   0   66.5g  64.9g   2.1g R  34.7 12.9   3:22.76 postgres
211276 postgres  20   0   71.0g  68.2g   2.1g R  99.1 13.6   3:52.94 postgres
211276 postgres  20   0   74.9g  71.2g   2.1g R 100.0 14.2   4:23.05 postgres
211276 postgres  20   0       0      0      0 R 100.0  0.0   4:45.65 postgres
```

top可以通过RES-SHR=USS来判断进程私有内存的消耗。211276进程的内存几分钟内暴涨到70g挂掉，并且都是进程私有内存消耗



## sql分析

PG日志中一个5M的SQL，包含5000+个union all，3万个变量
执行计划长达7W行

```sql
Append  (cost=218196.51..218216.28 rows=1318 width=1628)
  InitPlan 1 (returns $0)
    ->  Index Scan using table1 on table1nfo  (cost=0.29..5.31 rows=1 width=40)
          Index Cond: ((col1)::text = 'xxx'::text)
          Filter: ((colcolcol)::text = 'xxx'::text)
  InitPlan 2 (returns $1)
    ->  Index Scan using table1 on table1nfo table1nfo_1  (cost=0.29..5.31 rows=1 width=40)
          Index Cond: ((col1)::text = 'xxx'::text)
          Filter: ((colcolcol)::text = 'xxx'::text)
  ...
  InitPlan 10544 (returns $10543)
    ->  Aggregate  (cost=5.58..5.59 rows=1 width=32)
          ->  Index Scan using table2 on table2col t_1317  (cost=0.56..5.58 rows=1 width=19)
                Index Cond: ((ididid)::text = 'xxx'::text)
                Filter: ((idididid)::text = '1'::text)
```

执行计划结构非常简单，1w个子计划查数据，最后append结果。

就是这么个拼接怪SQL把backend进程打到70GB。其实不用深入分析也知道，这个sql是有问题的，把union all减少，问题应该是可以修复的（事实上就是这样）。但是如果仔细想想，这里有很多问题可以深入分析：

1. 为什么5M的SQL可以把内存打到70GB？
2. 数据本身跟内存有关系吗？是因为返回数据过多导致的吗？
3. 是解析数据缓存大，还是因为执行计划缓存数据大？
4. work_mem明明不大，为什么没有起到限制operation内存的效果？



## 初步分析

如果一个5M的sql缓存在backend中，里面至少应该包含所要的元数据、SQL解析数据、执行计划缓存信息
我们之前碰到过几十万个表/分区表的元数据缓存导致relcache过大，从而导致backend内存很大。而这个库的表不多，初步可以排除relcache问题（后续查看dump内存可以确认排除）。
SQL解析数据理应不会太多，5M的sql解析出来至少不应该是70G。

**work_mem的内存限制and more：**
work_mem只限制每个operation的sort（可以用到sort的操作）、hash（可以用到hash的操作）的内存。这里就存在multiple sort/hash的问题，一个sql有多个sort的话可使用多个work_mem，所以pg13新增`hash_mem_multiplier`以限制一个语句中的hash使用次数。但是sort呢？sort目前没有multiplier参数，但是现实场景中问题较少，因为一个语句中大量的plan node存在sort操作的情况是比较少的，想想代价就很高，优化器源码中也有把排序操作放在执行计划最后的逻辑，以减少反复排序。

这里实例的work_mem为128M，并且这个库是pg13+的，hash_mem_multiplier为1，基本可以排除执行计划使用大量hash操作导致内存暴涨的问题。另外从上面的执行计划看，完全没有sort和hash操作，所以可以排除sort/hash操作过多导致的问题。

所以之前的提问，*“work_mem明明不大，为什么没有起到限制operation内存的效果？”*

因为sql语句只有union all，没有任何排序和hash操作，所以work_mem不会限制这里的内存



**其他plan node**:
无论怎样，work_mem只（？）限制sort/hash。plan operation有这么多类型的操作，是不是没有限制？



## 复现问题并深入分析

### 空表复现内存飙升

```sql
--建空表
 create table lzl1(col1 varchar(1));
--非常多union all的查询
select col1 from lzl1 union all
select col1 from lzl1 union all 
...(5000个union all，sql大小150KB)
select col1 from lzl1
```

（UNION ALL过多可能超过max_stack_depth限制）
一个空表，多个union all，直接就容复现出来内存飙升问题。不仅如此，还可以发现sql运行完后，backend的内存回收了。

因为是一个空表，数据文件0kb，所以可以排除数据问题导致内存飙高。所以“数据本身跟内存有关系吗？是因为返回数据过多导致的吗？”——跟数据本身关系不大。



### strace操作系统调用分析

执行语句的同时通过strace -p抓操作系统调用信息：

```shell
 strace -p 198337 > strace.198337 2>&1 
```

在看strace信息前先了解一点点linux调用函数：

- [epoll_wait](https://man7.org/linux/man-pages/man2/epoll_wait.2.html):等待event，什么都不做的进程就是这个状态
- [recvfrom](https://man7.org/linux/man-pages/man3/recvfrom.3p.html):receive a message from a socket，从socket接收消息
- [getrusage](https://man7.org/linux/man-pages/man3/recvfrom.3p.html):get resource usage，获取资源使用情况
- [brk](https://man7.org/linux/man-pages/man2/brk.2.html): program break.Increasing the program break has the effect of allocating memory to the process; decreasing the break deallocates memory.操作系统底层管理内存的函数，malloc本质上也是在调用brk。
- [lseek](https://man7.org/linux/man-pages/man2/lseek.2.html):repositions the file offset of the open file description associated with the file descriptor fd to the argument offset，定位文件偏移量用的
- [write]():write to a file descriptor，write不保证写入磁盘
- [sendto](https://man7.org/linux/man-pages/man3/sendto.3p.html):send a message on a socket，从socket发送消息



其中，lseek、write、sendto等系统函数中包含fd文件描述符信息

```shell
lseek(37, 0, SEEK_END)                  = 0
```

在/proc/[pid]/pd目录中缓存了进程持有的文件描述符，从文件描述符反查relation，可以找到SQL执行打开的表lzl1

```shell
[postgres@lzl]$ cd /proc/198337/fd
[postgres@lzl]$ ll 37
lrwx------ 1 postgres postgres 64 Jan 26 22:59 37 -> /pgdata/lzl/data13/base/16385/16386
[postgres@lzl]$ oid2name -d lzldb -f 16386
From database "lzldb":
  Filenode  Table Name
----------------------
     16386        lzl1
```



strace信息非常多，但是结构简单：

```shell
strace: Process 198337 attached
epoll_wait(4, [{EPOLLIN, {u32=44314568, u64=44314568}}], 1, -1) = 1
# step1
recvfrom(9, "Q\0\2p\372select col1 from lzl1 union"..., 8192, 0, NULL, NULL) = 8192
recvfrom(9, " all\nselect col1 from lzl1 union"..., 8192, 0, NULL, NULL) = 8192
recvfrom(9, " all\nselect col1 from lzl1 union"..., 8192, 0, NULL, NULL) = 8192
...
recvfrom(9, " all\nselect col1 from lzl1 union"..., 8192, 0, NULL, NULL) = 8192
recvfrom(9, " all\nselect col1 from lzl1 union"..., 8192, 0, NULL, NULL) = 4347
# step2
brk(NULL)                               = 0x34d5000
brk(0x3cd5000)                          = 0x3cd5000
brk(NULL)                               = 0x3cd5000
...
brk(NULL)                               = 0x88cd6000
brk(0x894d6000)                         = 0x894d6000
# step3
lseek(37, 0, SEEK_END)                  = 0
lseek(37, 0, SEEK_END)                  = 0
...
lseek(37, 0, SEEK_END)                  = 0
# step4
brk(NULL)                               = 0x89cd6000
brk(0x8a4d6000)                         = 0x8a4d6000
brk(NULL)                               = 0x8a4d6000
...
brk(NULL)                               = 0x8a516000
brk(0x8a556000)                         = 0x8a556000
# step5
write(2, "2024-01-26 23:08:01.800 CST [198"..., 165521) = 165521
brk(NULL)                               = 0x8a556000
brk(0x8a57d000)                         = 0x8a57d000
brk(NULL)                               = 0x8a57d000
brk(0x8a59f000)                         = 0x8a59f000
...
brk(NULL)                               = 0x8d449000
brk(0x8d46b000)                         = 0x8d46b000
brk(NULL)                               = 0x8d46b000
brk(0x8d48d000)                         = 0x8d48d000
#step6
lseek(37, 0, SEEK_END)                  = 0
lseek(37, 0, SEEK_END)                  = 0
...
lseek(37, 0, SEEK_END)                  = 0
#step7
brk(NULL)                               = 0x8dcb1000
brk(NULL)                               = 0x8dcb1000
brk(0x8c179000)                         = 0x8c179000
brk(NULL)                               = 0x8c179000
brk(NULL)                               = 0x8c179000
brk(NULL)                               = 0x8c179000
brk(0x8a526000)                         = 0x8a526000
...
brk(0x34d5000)                          = 0x34d5000
brk(NULL)                               = 0x34d5000
#step8
sendto(8, "\2\0\0\0\230\0\0\0\1@\0\0\1\0\0\0\1\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0"..., 152, 0, NULL, 0) = 152
sendto(9, "T\0\0\0\35\0\1col1\0\0\0\0\0\0\0\0\0\4\23\377\377\0\0\0\5\0\0C\0"..., 50, 0, NULL, 0) = 50
#step9
recvfrom(9, 0xddcf60, 8192, 0, NULL, NULL) = -1 EAGAIN (Resource temporarily unavailable)
epoll_wait(4, strace: Process 198337 detached
 <detached ...> 
```

1. 从fd=9的socket接收到message，也就是我们发送的union all语句
2. brk分配内存，进程的内存从0x34d5000（54MB）涨到0x894d6000（2.1GB）
3. lseek表lzl1
4. 内存上涨4MB
5. write到fd=2的文件，就是日志文件；内存上涨48MB
6. lseek表lzl1
7. 内存到达峰值0x8dcb1000（2.1GB），开始通过brk释放内存，直到0x34d5000（54MB），跟开始时分毫不差
8. 从socket返回消息，也就是返回查询结果
9. 从fd=9的socket接收到空消息



strace分析到的东西不多，不过可以看到操作系统为进程分配和释放内存的具体过程。



### dump内存分析

内存飙高后的pmap信息：

```shell
[postgres@lzl pg_log]$ pmap -x 76207
76207:   postgres: postgres lzldb [local] SELECT            
Address           Kbytes     RSS   Dirty Mode  Mapping
0000000000400000    7984    2192       0 r-x-- postgres
0000000000dcc000       4       4       4 r---- postgres
0000000000dcd000      60      60      60 rw--- postgres
0000000000ddc000     200      60      60 rw---   [ anon ]
0000000001e49000     264     224     224 rw---   [ anon ]
0000000001e8b000 1812380 1804400 1804400 rw---   [ anon ]
...
ffffffffff600000       4       0       0 r-x--   [ anon ]
---------------- ------- ------- ------- 
total kB         2089384 1810232 1807384
```

pmap这里没有展示具体段是什么，但是可以确认内存起始地址为1e49000的内存段占用最多。此时需要smap来看是什么段，smap的段信息更为准确：

```shell
[postgres@lzl 76207]$ cat smaps |grep 1e49000 -A 30
01e49000-01e8b000 rw-p 00000000 00:00 0                                  [heap]
Size:                264 kB
...
01e8b000-70872000 rw-p 00000000 00:00 0                                  [heap]
Size:            1812380 kB
Rss:             1804400 kB
Pss:             1804400 kB
Shared_Clean:          0 kB
Shared_Dirty:          0 kB
Private_Clean:         0 kB
Private_Dirty:   1804400 kB
Referenced:      1804400 kB
Anonymous:       1804400 kB
AnonHugePages:         0 kB
Swap:                  0 kB
KernelPageSize:        4 kB
MMUPageSize:           4 kB
```

heap段，PSS进程私有内存达到1.8GB！
*（这里本来应该dump 01e8b000-70872000内存段，但是gdb dump memory会报错，不太明白具体原因，大佬可以指点一下，谢谢！）*
这里粗糙一点用gcore dump内存，比较难看，什么东西都有，没有发现占用特别多的内容。不过strings后发现内存数据实际上很少：

```shell
[postgres@lzl lzl]$ gcore -o /pgdata/lzl/gcore.dump 76207
[postgres@lzl lzl]$ strings gcore.dump.76207> text.dump.76207
[postgres@lzl lzl]$ ll -h
-rw-r-----  1 postgres postgres 2.0G Jan 26 17:29 gcore.dump.76207
-rw-r-----  1 postgres postgres 5.2M Jan 26 17:30 text.dump.76207
```

申请了2G的虚拟内存，占用1.8G的物理内存，实际上只存储了5.2M的数据！
用hexdump极粗略地看一下，可以发现很多内存空洞

```shell
[postgres@lzl lzl]$ hexdump -C gcore.dump.76207 |head -10000  |grep "00 00 00 00 00 00 00 00"|wc -l
3690
```



### log_planner_stats等信息

为了验证是否缓存执行计划的问题
把复现环境的相关log参数**先后**打开以观察parse、planner、executor阶段的资源消耗

```shell
 log_parser_stats = on
 log_planner_stats = on
 log_executor_stats = on
```

从日志上看parse阶段的消耗内存较少，而planner的内存消耗较多
log planner stat的信息：

```shell
2024-01-26 18:01:41.592 CST [208503] LOG:  PLANNER STATISTICS
2024-01-26 18:01:41.592 CST [208503] DETAIL:  ! system usage stats:
        !       0.048955 s user, 0.004996 s system, 0.054077 s elapsed
        !       [11.208034 s user, 1.313838 s system total]
        !       2255352 kB max resident size
        !       0/0 [0/352] filesystem blocks in/out
        !       0/1315 [0/563859] page faults/reclaims, 0 [0] swaps
        !       0 [0] signals rcvd, 0/0 [0/0] messages rcvd/sent
        !       0/0 [1/16] voluntary/involuntary context switches
```

2GB的max resident size大小跟进程观察的res差不多，所以上面的信息可以回答刚才的问题：“是解析数据缓存大，还是因为执行计划缓存数据大？”——planner阶段消耗的内存。



### 查看TopMemoryContext

pg通过memorycontext管理backend进程的私有内存，可通过gdb输出TopMemoryContext信息：

```shell
TopMemoryContext: 101488 total in 6 blocks; 48464 free (28 chunks); 53024 used
  pgstat TabStatusArray lookup hash table: 8192 total in 1 blocks; 1408 free (0 chunks); 6784 used
  TopTransactionContext: 8192 total in 1 blocks; 7720 free (0 chunks); 472 used
  TableSpace cache: 8192 total in 1 blocks; 2048 free (0 chunks); 6144 used
  RowDescriptionContext: 8192 total in 1 blocks; 6880 free (0 chunks); 1312 used
  MessageContext: 1854981336 total in 235 blocks; 7911304 free (9 chunks); 1847070032 used
...
Grand total: 1856104056 bytes in 431 blocks; 8226712 free (179 chunks); 1847877344 used
```

内存消耗最多的是MessageContext 1.8G
src/backend/utils/mmgr/README对MessageContext 的解释：

>MessageContext --- this context holds the current command message from the frontend, as well as any derived storage that need only live as long as the current message (for example, in simple-Query mode the parse and plan trees can live here).  This context will be reset, and any children deleted, at the top of each cycle of the outer loop of PostgresMain.  This is kept separate from per-transaction and per-portal contexts because a query string might need to live either a longer or shorter time than any single transaction or portal.

>When creating a prepared statement, the parse and plan trees will be built in a temporary context that's a child of MessageContext 

 - MessageContext缓存frontend发来传递的消息，包含派生的parse、plan tree信息
 - parse and plan trees 是MessageContext的child，也就是说MessageContext回收，parse and plan trees 就回收



这里就的messagecontext还可以解释私有内存回收问题，planner阶段产生的plan tree内存数据是MessageContext的child，数据结果返回后MessageContext被回收，child内容也被回收，同样也可以解释从strace中观察的内存释放后跟释放前的大小是完全一致的。



## 总结

回答最后一个问题：*“为什么5M的SQL可以把内存打到70GB？”*

绝大部分内存是在生产执行计划期间消耗的，planner申请了大量的内存，并且work_mem，hash_mem_multiplier只能限制到排序操作和hash操作，对于planner过程中的其他内存操作还无法限制，planner本身产生的plan tree并不大，但是申请内存时存在大量的内存空洞，导致本身M级的数据（元数据、parse tree、plan tree等等）存储在G级的内存中。

这些SQL、parse tree、plan tree都缓存在MessageContext及其child中，消息发送完毕后，此部分产生的内存全部回收。
