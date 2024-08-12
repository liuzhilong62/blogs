# 内存的基本概念

操作系统内存非常重要且比较复杂，其中有许多知识点仍然需要掌握才能更进一步分析程序问题。由于是初次全面系统地接触OS内存，目的是为了全面且低层次地理解linux内存相关概念，不会深入其中原理，所以本章也会尽量避免linux的源码知识。

## 物理内存和虚拟内存

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/37aec92963b5231f523913436be171b6.png)
(https://en.wikipedia.org/wiki/Memory_address)



**物理内存（Physical memory）**：物理内存是计算机系统中实际存在的硬件内存，通常是RAM（随机存取存储器）的形式。

**虚拟内存（Virtual memory）**：虚拟内存是一个线性区，并没有分配实际物理内存，程序认为它们有比实际物理内存更大的地址空间。虚拟内存的实现允许程序访问比物理内存更大的地址范围，而不需要所有数据都同时存在于物理内存中。内核释放物理页面是通过释放线性区，找到其所对应的物理页面，将其全部释放的过程。

**内存管理单元（Memory Management Unit，MMU）**：是一个硬件组件，负责将程序中使用的虚拟地址转换为实际在物理内存中存储数据的物理地址。MMU的主要任务是执行地址映射。

**页表（Page Table）**：页表是一种数据结构，用于存储虚拟地址空间与物理地址空间之间的映射关系。程序试图访问虚拟内存时，MMU通过查询页表确定相应的物理地址。



系统调用流程：
![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/2dda542b3f2660d3d28debaf7a1505b5.png)
https://users.cs.utah.edu/~aburtsev/cs5460/lectures/lecture19-memory-management/lecture19-memory-management.pdf

（图有点糊，最上面的字是 “User Space|Kernel Space”）

- 用户程序通过C库或通过系统调用才能访问内核系统，用户程序不能直接访问内核系统

- 内核系统通过MMU访问物理内存；通过驱动访问磁盘其他外部设备

- 虚拟内存系统（上图中的VM Subsystem）中包含buddy、slab算法等



## 用户空间和内核空间

进程虚拟地址空间分成了用户空间和内核空间。

**用户空间**：

- 用户进程在内存中运行的空间
- 这部分空间被保护，系统防止其他进程访问。（共享内存除外）
- 但是内核进程可以直接访问用户进程

**内核空间**：

- 内核空间是内核进程使用的空间
- 在内核空间，运行操作系统的内核代码，这些代码具有更高的特权级别，可以直接访问系统硬件、管理进程、进行文件系统操作等

**上下文切换：**

- 当用户程序需要访问系统服务或执行需要更高权限的操作时，会触发从用户空间到内核空间的上下文切换。
- 上下文切换是一种操作系统机制，用于保存和恢复程序的状态，确保在用户程序和内核之间切换时不会发生数据丢失。

用户空间和内核空间的划分是为了提供安全隔离，防止用户程序直接影响操作系统的关键部分。早期的操作系统和Dos系统不区分内核、用户空间，一个程序的错误或恶意行为可能对整个系统造成影响。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/f4a705a1a478a317f78e08eefd197cf2.png)
(https://www.zhihu.com/tardis/zm/art/66794639?source_id=1003)

32位系统：总共4GB地址空间，3G UserSpace|1G KernelSpace

64位系统：总共256TB地址空间，128T UserSpace|128T KernelSpace



*2^32=4GB，2^64=16777216TB，为什么是64位的系统是256TB地址空间呢？*

[64-bit computing wiki](https://en.wikipedia.org/wiki/64-bit_computing)上有解释。简而言之，256TB (256 × 1024^4 bytes) 的内存地址足够了，目前以及能想象的未来还不会出现16EB (16 × 1024^6 bytes)的内存。



## 进程虚拟地址空间

每个进程通常都有自己的独立虚拟内存空间。虚拟内存是一种抽象概念，为每个运行的进程提供了似乎是连续且私有的地址空间，使得每个进程都感觉自己拥有整个计算机系统的全部内存。

进程虚拟地址空间分布：

![img](https://i-blog.csdnimg.cn/blog_migrate/5652565ef4a9cc79e7255cc10b877546.jpeg)

![img](https://i-blog.csdnimg.cn/blog_migrate/9dc4d2ff72389b04934aa865b7a19977.jpeg)

（https://www.sohu.com/a/392831824_467784）

- mmap 映射区域至顶向下扩展，mmap 映射区域和堆相对扩展，直至耗尽虚拟地址空间中的剩余区域，这种结构便于C运行时库使用mmap 映射区域和堆进行内存分配。
- 栈区(Stack)：存储程序执行期间的本地变量和函数的参数，从高地址向低地址生长
- 堆区(Heap)：动态内存分配区域，通过 malloc、new、free 和delete 等函数管理
- 未初始化变量区(BSS)：存储未被初始化的全局变量和静态变量
- 数据区(Data)：存储在源代码中有预定义值的全局变量和静态变量
- 代码区(Text)： 存储只读的程序执行代码，即机器指令。



进程虚拟地址空间分布和映射：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/86f00cb72bea3ab1bf725151b70e8c82.png)
(https://velog.io/@mysprtlty/%EA%B0%80%EC%83%81-%EB%A9%94%EB%AA%A8%EB%A6%AC%EC%99%80-%EA%B0%80%EC%83%81-%EC%A3%BC%EC%86%8C-%EA%B3%B5%EA%B0%84)



## 共享内存

前面讲到，虚拟地址空间中的用户空间不能被其他用户进程访问，如果通过内核区域实现多进程的用户访问同一内存数据，那么无法避免上下文切换。多进程的应用程序明显需要进程间的相互访问，所以一种直接可以实现用户进程访问同一物理内存的方法便应运而生，这就是共享内存。

共享内存是实现进程相互访问IPC（inter process communication）的机制之一，其他的方式还有message queues和semaphores。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/83c8c28f715c81b8ebf8ec73388db915.png)
（https://www.geeksforgeeks.org/inter-process-communication-ipc/）

由于本身就是多个虚拟内存地址空间对应一个物理内存地址空间，所以只要把两个进程的地址空间中的一段指向同一物理内存即可。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/fd06a23e927c1b9fef9cb9aa7271822a.png)

（https://www.softprayog.in/programming/interprocess-communication-using-system-v-shared-memory-in-linux）



共享内存（seems like）有许多实现方式，例如postgresql默认是mmap来实现共享内存，参考[shared_memory_type参数](https://www.postgresql.org/docs/current/runtime-config-resource.html#GUC-SHARED-MEMORY-TYPE)和[Managing Kernel Resources](https://www.postgresql.org/docs/current/kernel-resources.html)。其他的共享内存实现可参考这篇文章：[宋宝华：世上最好的共享内存(Linux共享内存最透彻的一篇)](https://cloud.tencent.com/developer/article/1551288)



## 页表 PAGE TABLE

进程虚拟地址空间是对于每个进程而言的，而物理内存空间只有一个。那么如果映射、转换虚拟内存和共享内存呢？

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/5fe268c2856fcc3a0d830bb2922267d2.png)

(https://courses.engr.illinois.edu/cs241/sp2014/lecture/09-VirtualMemory_II_sol.pdf)



**页表就是存储虚拟内存地址和物理内存地址的对应关系的地方**。(这里有内存管理单元MMU和转换缓冲区TLB等的概念，我们简化一下，简单理解为虚拟内存到物理内存转换功能（PAGING），这里只看页表）。一个页表是一组页表项page table entries (PTEs) 组成，PTE存储了虚拟页和物理页间的map。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/15cb5641efda0539ca53435795023c1f.png)

单个页表虽然可以实现内存到虚拟内存的转换功能，但是直接这样实现话，页表本身又占用了太多的内存。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/32d5c0f41a452ecd03fdd8cdc7bec682.png)

(https://courses.engr.illinois.edu/cs241/sp2014/lecture/09-VirtualMemory_II_sol.pdf)

所以，需要对单个页表进行再分页：二级页表和四级页表



二级页表：

二级页表就是对单页表的再分页。4G 的空间需要 4M 的页表来存储映射表，如果将这 4M 分成 1K 个 页（4K）, 这 1K 个页也需要一个表进行管理，我们成为**页目录表**，这个页目录表里面有 1K 项，每项 4 个字节，页目录表大小也就是 4K 。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/f2792325d2c01b27d60c61c9bfc18211.png)



四级页表：

对于 64 位系统，两级页表也不够，需要用四级页表

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/7002f433b27058b0684f315fd719da89.png)
（https://maodanp.github.io/2019/06/02/linux-virtual-space/）


查看pagetable的大小：

```shell
[pg@lzl 2345]$ cat /proc/meminfo |grep PageTables
PageTables:        46736 kB
```



## NUMA

**Uniform Memory Access (UMA)**：所有cpu访问内存的时间是等价的。UMA存在的问题是多个处理器通过一条总线访问内存，使共享总线上负载增加。多个处理器会争用memory controller造成冲突。另外总线带宽有限，会有访问延迟。

**Non-Uniform Memory Access ([NUMA](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/7/html/virtualization_tuning_and_optimization_guide/chap-virtualization_tuning_optimization_guide-numa))**：一小组CPU一起访问它们自己的本地内存。存在多组CPU和它们的内存组时，每组CPU和内存组就构成一个NUMA节点(node)。

UMA：



![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/71d09374952e9534bd4f015f710eb943.png)



NUMA：



![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/5c69a9b56533272da4bb8da62ddaa4d0.png)

（https://users.cs.utah.edu/~aburtsev/cs5460/lectures/lecture19-memory-management/lecture19-memory-management.pdf）



*NUMA的基本特性*：

- cpu访问本地node的内存要比remote的更快
- 默认情况下linux优先在cpu上分配本地内存，策略可以配置
- 每个node都有自己的内存结构
- 不是所有场景都适合numa，需要上层应用的适配



*NUMA balancing*：

通过自动转移任务到远端cpu或者拷贝远端数据到本地内存的方式，实现本地访问。redhat 7上默认打开。

转移任务或者拷贝数据本身也消耗资源，导致任务变慢，该特性可能不适用于部分应用，例如oracle的exdata就对NUMA做了针对优化。



*numactl*：

NUMA的OS配置工具 。

numactl --show检视cpu和node情况，如下为4node总共64c256g，每个node有16c64g：

```shell
available: 4 nodes (0-3)
node 0 cpus: 0 1 2 3 4 5 6 7 32 33 34 35 36 37 38 39
node 0 size: 65418 MB
node 0 free: 310 MB
node 1 cpus: 8 9 10 11 12 13 14 15 40 41 42 43 44 45 46 47
node 1 size: 65536 MB
node 1 free: 41 MB
node 2 cpus: 16 17 18 19 20 21 22 23 48 49 50 51 52 53 54 55
node 2 size: 65536 MB
node 2 free: 82 MB
node 3 cpus: 24 25 26 27 28 29 30 31 56 57 58 59 60 61 62 63
node 3 size: 65536 MB
node 3 free: 43 MB
```



## zone

NUMA把cpus和内存分成多个node（node 0，node 1，node 2 ···），UMA结构中也可以把cpu内存整体看成node 0。

在Linux中每个node用数据结构`struct pglist_data`表示，数据类型为`typedef pg_data_t`。每个node又分为多个zone，一个zone的数据结构为`zone_t`，数据类型为`zone_struct`，一般有3种数据类型`ZONE_DMA`, `ZONE_NORMAL` , `ZONE_HIGHMEM`，每个类型的zone有各种不同的功能。



![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/72a1671ff0ea5714e2fc45708e000958.png)

（https://www.kernel.org/doc/gorman/html/understand/understand005.html）



32位zone的区域分布及功能：

- `ZONE_DMA`：(<16MB)，*Direct Memory Access* (DMA)，古老的16 MiB限制，包含[ISA devices](https://en.wikipedia.org/wiki/Industry_Standard_Architecture)。
- `ZONE_DMA32`：由于很多设备在访问无法用 32 位寻址的内存时遇到问题，在x86-64新增了这样一个区域，该区域只存在于x86-64架构中。（详见[ZONE_DMA32](https://lwn.net/Articles/152462/)）
- `ZONE_NORMAL`： (16MB to 896MB)，可直接映射到内核段的普通内存域；大部分内核操作都在NORMAL区进行，这是最重要的一个区域
- `ZONE_HIGHMEM`：(>896MB)，标记了超出内核段的物理内存，不能直接被内核调用。



32位和64位的zone分布图：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/0fc20a7da58b06b8394fd63494926c20.png)

https://users.cs.utah.edu/~aburtsev/cs5460/lectures/lecture19-memory-management/lecture19-memory-management.pdf



注意zone是对于物理内存而言的，虚拟内存的用户态转换为内核态后，才可以调用物理内存。下图便是虚拟内存空间的内核地址与物理地址空间中的zone的关系：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/b7376b2fad9da735c6345f5e534285eb.png)

（https://wr.informatik.uni-hamburg.de/_media/teaching/wintersemester_2014_2015/kp-1415-memory-management.pdf）



检视zone：

`cat /proc/zoneinfo`

`cat /proc/buddyinfo` 

` cat /proc/pagetypeinfo`

```shell
$ cat /proc/buddyinfo 
Node 0, zone      DMA      1      1      1      1      1      0      1      1      1      1      2 
Node 0, zone    DMA32    688   2080   1420    995    596    357    278    241    276     32    133 
Node 0, zone   Normal 195748 204074 161167 119070  70791  33578   9556   2070   1034   2533   7328 
Node 1, zone   Normal  11705  51467  36752  21326  11343   7309   5024   3403   2597   3056  10898
```



## 页

虚拟内存和物理内存被分割为固定大小的片段，一般是4KB大小。所以虚拟内存分割后就有了虚拟页，物理内存分割后就有了物理页（PP or PF，Physical Page or Page Frame），物理页也叫页帧，也是4KB。页帧代表系统内存的最小单位。

虚拟地址空间的每个页面都可以通过其描述项对应到物理地址空间的一个页帧上。



## Huge Pages/Transparent Huge Pages

页是内存分配的最小单元（默认4K），当map分配大量的连续页时性能较差，[Huge Page](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/6/html/performance_tuning_guide/s-memory-transhuge)就是为了解决这个问题。大页不仅分配的时候更cheap，页表同时也相对会更小。hugepagesz 为2 MB或1 GB，默认是2MB。REDHAT 6开始实现了Huge Page。

由于手动管理大页比较麻烦，REDHAT 6开始同样也提供了自动管理大页的功能，即**透明大页**。

在oracle的数据库管理中，一般把大页打开给SGA使用，透明大页关闭。相关资料也比较多可行搜索资料。

同样的，PostgreSQL也可以开启大页。由于数据库一般会占用较多的操作系统内存，数据库开启大页一般可以降低内存分配的压力。



## 文件页与PageCache/匿名页与SwapCache

文件页可以map到磁盘上的文件，文件系统的读写会通过Page Cache当做缓存IO，脏数据周期或被调用时“sync”（or fsync之类的）到对应的磁盘，Page Cache就是用来“提升”磁盘性能的内存区域。

相对应的，没有文件相关联的页叫匿名页（Anonymous pages ），一般对应着heap、stack。当内存资源紧张时，内核会把不经常使用的匿名页中的数据写入到 Swap 分区或者 Swap 文件中。

简而言之：

- page cache是与文件映射对应;
- swap cache是与匿名页对应

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/981c94fc2f5e0c49f952a144c005a5e0.png)



（https://www.slideshare.net/raghusiddarth/memory-management-in-linux-11551521?from_search=2）

以上page cache的图是站在操作系统的角度来看的，应用程序（如数据库）的写入也可以不delayed，甚至不通过Page cache。



# 内存分配

内存分配也十分复杂，涉及很多概念。两种常见的内存分配方式为buddy、slab

## buddy

buddy系统用于分配连续的内存页，每个zone都有各自的buddy系统。buddy系统划分了大块内存以响应内存分配请求，同时由于合并的特性可以减少系统内存碎片化。

buddy allocator将内存分为2的幂次方的页，最大阶数为10：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/85513810f16498a908847739edab0de6.png)

当内存请求大于已有块的大小时，系统会将较大的块分割成两个相等大小的伙伴块。当内存释放时，系统会尝试将相邻的伙伴块合并成一个更大的块：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/0d42c25338e6484c3881d780d52c879f.png)

释放⻚⾯的时候就直接把⻚⾯放回空闲列表，如果其之前拆开的另⼀半⻚⾯也没有被分配，则组合成双倍⻚⾯交给更⼤的列表，然后依次循环，直到不能再循环或者已经到头。

由于高阶页因为不停的分配没有了，此时再申请高阶页时便会触发碎片问题：
![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/873fdb221df1fd49b3cfb0f882e9ed7f.png)

等待内存回收成功后，buddy本身会合并低阶到高阶，然后分配高阶页面：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/90e5aca837455e1c440611665c616b45.png)

（The implementations of anti pages fragmentation in Linux kernel https://teawater.github.io/presentation/antif.pdf）

然而内存回收也可能赶不上分配速度，所以buddy系统不总是那么理想。



分析示例：

```shell
$ cat /proc/buddyinfo 
Node 0, zone      DMA      0      0      0      1      2      1      1      0      1      1      3 
Node 0, zone    DMA32      7      6      5      6      5      6      7      7      6      2    272 
Node 0, zone   Normal 317681  38869  31620  19250   8931   2579    815    182     19      5      0 
```

 - 上述包含3个ZONE：DMA，DMA32，Normal
 - 阶数： 0 ~ 10，即buddy里对应每一阶对应的数量。buddy最大的阶数为10, 即1024个pages，也就是4MB
 - 如Normal 行第3列表示有31620个2^2连续内存块可以用
 - 以此类推，越是往后的空间，就越是连续，数目越多，就代表这个大小的连续空间越多，当大的连续空间很少的时候，也就说明内存碎片已经不少
 - 另外，全部加起来就是当前free状态的内存

通过buddyinfo判断内存碎片问题：

```shell
#host 1
Node 0, zone   Normal 317681  38869  31620  19250   8931   2579    815    182     19      5      0 
#host 2
Node 0, zone   Normal   7321   7833  10885   8514   2311   1644   1663   1302   1141   7384  80675 
```

上面是两个主机的内存情况，对比可以发现，下面这个主机的连续内存更多，上面那个主机存在内存碎片问题。



## slab

slab分配器是**基于对象**进行管理的。slab系统是一种专门为**内核**内存设计的内存分配算法。它通过将内存划分为固定大小的cache来实现，每个slab都包含同一类型的对象集。当有内存请求时，该算法首先检查适当的slab缓存中是否存在可用的对象。如果存在，则返回该对象。如果不存在，则算法会分配一个新的slab并将其添加到适当的cache中。

不同大小的对象对应不同的slab cache：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/4bf6612d89e359d772a6cc1bdc19f005.png)

(https://bootlin.com/doc/training/linux-kernel/linux-kernel-slides.pdf)



虽然slab有不同的cache和对象，但是slab仍然使用的是物理连续的内存：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/9147df8131ea21d8042aa16169701110.png)

（https://i.stack.imgur.com/wo8Gg.png）



slab也有3种实现方式：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/25cf297d40abfe282685d046b1cf8c9a.png)





# 内存回收

推荐文章：[linux强制回收内存,linux内存源码分析 - 内存回收](https://blog.csdn.net/weixin_35094083/article/details/116688112)

## 内存回收概述

 - 当系统内存压力具大时，就会对系统的每个压力大的zone进程内存回收，内存回收主要是针对匿名页和文件页进行；
 - 对于匿名页，内存回收过程中会筛选出一些不经常使用的匿名页，将它们写入到swap分区中，然后作为空闲页框释放到伙伴系统；
 - 对于文件页，内存回收过程中也会筛选出一些不经常使用的文件页：
   - 如果此文件页中保存的内容与磁盘中文件对应内容一致，说明此文件页是一个干净的文件页，就不需要进行回写，直接将此页作为空闲页框释放到伙伴系统中；
   - 如果文件页保存的数据与磁盘中文件对应的数据不一致，则认定此文件页为脏页，需要先将此文件页回写到磁盘中对应数据所在位置上，然后再将此页作为空闲页框释放到伙伴系统中。
 - 内存回收完成后，系统空闲的页框数量就会增加，能够缓解内存压力，但在回收过程中会对系统的IO造成很大的压力，所以，在系统内，为每个zone会设置一条线，当空闲页框数量不满足这条线时，就会执行内存回收操作，而系统空闲页框数量满足这条线时，系统是不会进行内存回收操作的。

## zone的水位线与kswapd



![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/5e4504f264021c488d8a67b9b36efbe2.png)

（https://vivani.net/2022/06/14/linux-kernel-tuning-page-allocation-failure/)

当可用内存较低时kswapd守护进程会被唤醒以释放页

- **pages_low:**当可用的空闲页面数量低于pages_low 时，buddy allocator会唤醒 **kswapd **进程，内核开始将页换出到硬盘。
- **pages_min:**当可用页面数量达到 pages_min时，说明页回收工作的压力就比较大，因为内存域中急需空闲页。分配器将以同步的方式执行 kswapd 工作，有时也称为直接回收。
- **pages_high:**一旦 kswapd 被唤醒开始释放页面，只有在可用页面数量达到pages_high时，内核才认为该区域是“平衡的”。如果水位线达到pages_high，kswapd 将重新进入休眠状态。空闲页多于pages_high，则内核认为zone的状态是理想的。



内存回收以zone为单位进行，`/proc/zoneinfo`可以查看min、low、high的值。

`vm.min_free_kbytes`也就是min_pages线，十分重要的操作系统参数。非常低的值会阻止系统有效地回收内存，这可能会导致系统崩溃并中断服务。太高的值会增加系统回收活动，造成分配延迟，这可能导致系统立即进入内存不足状态。



## 内存分配和回收的种类

**快速内存分配**：是get_page_from_freelist()函数，通过low阀值从zonelist中获取合适的zone进行分配，如果zone没有达到low阀值，则会进行快速内存回收，快速内存回收后再尝试分配。

**慢速内存分配**：当快速分配失败后，也就是zonelist中所有zone在快速分配中都没有获取到内存，则会使用min阀值进行慢速分配，在慢速分配过程中主要做三件事，异步内存压缩、直接内存回收以及轻同步内存压缩，最后视情况进行oom分配。并且在这些操作完成后，都会调用一次快速内存分配尝试获取页框。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/11993cf571f71324e76d9b3057d91b51.png)

（https://blog.csdn.net/weixin_35094083/article/details/116688112）



不同的内存分配路径中，会触发不同的内存回收方式，对zone的内存回收方式分为两种：

 - **后台内存回收**（kswapd）：在物理内存紧张的时候，会唤醒 kswapd 内核线程来回收内存，这个回收内存的过程**异步**的，不会阻塞进程的执行。
- **直接内存回收**（direct reclaim）：如果后台异步回收跟不上进程内存申请的速度，就会开始直接回收，这个回收内存的过程是**同步**的，会阻塞进程的执行。



## 内存压缩

内存压缩见：内存的监控-/proc/pagetypeinfo部分



## LRU

对于zone的内存回收，它针对三样东西进程回收：slab、lru链表中的页、buffer_head。这里只讨论内存回收针对lru链。

lru链表主要作用就是将页排序，将最应该回收的页放到最后面，最不应该回收的页放到最前面，然后进行内存回收时，就会从后面向前面进行扫描，将扫描到的页尝试进行回收。



lru链表描述符，里面有5个lru链表，活动/非活动匿名页lru链表，活动/非活动文件页lru链表，禁止换出页链表：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/c0643af570b3f6be0ec201dfe0aca3c9.png)

（https://lpc.events/event/11/contributions/896/attachments/793/1493/slides-r2.pdf）

内存回收来说，它只会处理前面4个lru链表，也就是活动匿名页lru链表，非活动匿名页lru链表，活动文件页lru链表，非活动文件页lru链。回收到足够页框后直接返回：快速内存回收、kswapd内存回收中会这样做。



可以通过meminfo查看global lruvec（理解为lru区域）：

```shell
# cat /proc/meminfo |grep -i active
Active:           597380 kB
Inactive:         601920 kB
Active(anon):      10896 kB
Inactive(anon):   117376 kB
Active(file):     586484 kB
Inactive(file):   484544 kB
```



实际上lruvec不止一个，cgroup、NUMA node都有自己的lruvec，同时global也有自己的lruvec

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/7616543dcdea2dfc848e9aa1c0889a56.png)





## drop cache

Dropcache会记录哪些页面是缓存文件系统数据的页面，并在页面被强制回收时把数据写回磁盘，以便下次访问时可以再次缓存。

1. 默认值：`vm.drop_caches = 0`。默认情况下，Linux内核不会自动清除缓存

2. `/proc/sys/vm/drop_caches`的值设置为1：内核会清除未使用的页缓存pagecache。

3. `/proc/sys/vm/drop_caches`的值设置为2：内核会释放dentry和inode所使用的内存，dentry和inode是文件系统元数据结构，用于存储文件和目录的信息。

4. `/proc/sys/vm/drop_caches`的值设置为3：效果相当于1+2，释放所有未使用的缓存

当内核决定回收某些缓存时，它会检查缓存中的数据与硬盘上的数据是否一致。如果数据不一致，内核需要将数据写回磁盘，然后才能回收该缓存。这个过程可能导致IO飙高。在进行Drop Cache操作时，建议不要有任何重要的I/O操作，因为这可能会影响系统性能。

操作命令：


	echo 3 > /proc/sys/vm/drop_caches  #刷cache缓存
	echo 0 > /proc/sys/vm/drop_caches  #恢复默认值



# 内存的监控

如果不了解内存的基本知识其实很难看懂内存监控信息，在有了以上内存基础的情况下，我们来一个个过内存相关监控命令、工具的使用。



## /proc 目录有些什么？

/proc 主要是进程 (process)信息和系统信息

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/dec689fa26f20aed26badb5d8591aa01.png)

其中system information部分，有些是linux提供的一些系统状态的接口，可以查看整个操作系统层面的监控信息，比如slabinfo,swaps,zoneinfo,buddyinfo



另一部分process是每个进程运行数据和状态信息，cd到对应进程目录下，可以看到对应进程的持有的fd和进程内存信息等

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/1c4910d8ab2117d848330d1bf5b79599.png)

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/ae974553e1e85244acef3a6244bedba2.png)

进程下面还有线程，线程的信息目录：/proc/[pid]/task/[tid]/，其下内容跟进程目录下面差不多。

更多的proc信息参考[proc(5) — Linux manual page](https://man7.org/linux/man-pages/man5/proc.5.html)



## /proc/meminfo

/proc/meminfo是了解当前Linux系统内存使用状况的主要接口，最常用的`free`,`vmstat`,`ps`等命令就是通过它获取数据。/proc/meminfo的信息要更加全面，下面只列出一些常见的信息，详细含义可参考[红帽文档](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/6/html/deployment_guide/s2-proc-meminfo)

```shell
#一般的内存信息
cat /proc/meminfo | grep "Mem"
MemTotal:         994328 kB		#总内存大小（减去一些保留的和内核的）
MemFree:           66428 kB		#完全没有用到的物理内存
MemAvailable:     207192 kB		#在不使用交换空间的情况下，启动一个新的应用最大可用内存的大小

#IO缓冲区
cat /proc/meminfo | grep -e "Buffers" -we "Cached" 
Buffers:           12820 kB		#raw disk block使用的IO缓冲区，不会超过20MB
Cached:           254592 kB		#磁盘使用的page cache size（包含tmpfs和shmem不包含SwapCached）

#swap
cat /proc/meminfo | grep "Swap" 
SwapCached:        13936 kB		#swap cache中包含的是被确定要swapping换页，但是尚未写入物理交换区的匿名内存页
SwapTotal:        945416 kB		#swap空间总大小
SwapFree:         851064 kB		#剩余的swap的大小

#lru活动与非活动页数（一眼懂）
cat /proc/meminfo | grep -e "Active" -e "Inactive" 
Active:           194308 kB
Inactive:         553172 kB
Active(anon):      59024 kB
Inactive(anon):   437264 kB
Active(file):     135284 kB
Inactive(file):   115908 kB

#脏页
cat /proc/meminfo | grep -e "Dirty" -e "Writeback" 
Dirty:                 0 kB		#还未写入的脏页
Writeback:             0 kB		#正在写入的脏页
WritebackTmp:          0 kB		#？temporary buffer for writebacks used by the FUSE module

#map信息
cat /proc/meminfo | grep -e "AnonPages" -e "Map"
AnonPages:         95296 kB		#map的匿名页
Mapped:           153192 kB		#map的文件页
DirectMap4k:      113336 kB		#map的4k内核页
DirectMap2M:     1900544 kB		#map的2M内核页
DirectMap1G:           0 kB		#map的1G内核页

#共享内存
cat /proc/meminfo | grep "Shmem"
Shmem:             28920 kB		#shmem和tmpfs的总内存大小
ShmemHugePages:        0 kB		#shmem和tmpfs的总大页内存大小
ShmemPmdMapped:        0 kB		#Shared memory mapped into userspace with huge pages

#内核内存（注意slab就是内核的）
cat /proc/meminfo | grep -ie "reclaim" -e "slab" -e "kernel"
KReclaimable:      35008 kB		#分配给内核的Reclaimable内存
Slab:              88752 kB		#slab cache
SReclaimable:      35008 kB		#slab cache中Reclaimable内存
SUnreclaim:        53744 kB		#slab cache中不能reclaim的内存
KernelStack:        5988 kB		#所有任务使用的kernel stack内存

#分配的可用内存（与MemAvailable含义不同）
# CommitLimit=[("total RAM pages" - "total huge TLB pages") * overcommit_ratio]/100 + "total swap pages"
# 简而言之，设置了MemAvailable的水位然后加上了swap就等于allocatable内存
cat /proc/meminfo | grep -ie "commit"
CommitLimit:     1442580 kB		#allocatable内存
Committed_AS:    3035924 kB		#预估当前最坏场景下，需要分配的内存


#虚拟内存
cat /proc/meminfo | grep -e "Vmalloc"
VmallocTotal:   34359738367 kB	#已分配的虚拟内存总大小
VmallocUsed:       34780 kB			#已使用的虚拟内存总大小
VmallocChunk:          0 kB			#最大的连续虚拟内存块

#page table占用的内存（一眼懂）
cat /proc/meminfo | grep PageTables
PageTables:         4120 kB

#大页内存
cat /proc/meminfo | grep -i hugepage
AnonHugePages:     32768 kB
ShmemHugePages:        0 kB
FileHugePages:         0 kB
HugePages_Total:       0
HugePages_Free:        0
HugePages_Rsvd:        0
HugePages_Surp:        0
Hugepagesize:       2048 kB
```



## /proc/buddyinfo

buddyinfo由于信息简洁易懂，是最为常用的判断内存碎片问题的方式。详见 “内存分配-buddy章节”

```shell
$ cat /proc/buddyinfo 
Node 0, zone      DMA      0      0      0      1      2      1      1      0      1      1      3 
Node 0, zone    DMA32      7      6      5      6      5      6      7      7      6      2    272 
Node 0, zone   Normal 317681  38869  31620  19250   8931   2579    815    182     19      5      0 
```



## /proc/pagetypeinfo

pagetypinfo首先提供有关页块大小的信息。它提供与buddyinfo相同类型的信息，但按类型进行细分并详细说明每种类型的页的数量。

在理解pagetypeinfo前，需要先了解下[memory compaction](https://lwn.net/Articles/368869/).

假如一个zone中的内存如下：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/4ce9f4a6071a1242a9907249e2685f98.png)

白色代表可用内存，红色代表已使用内存。以上内存的碎片化已经比较严重了，如果此时有请求2阶以上的内存，是无法分配的。此时该memory compaction发生作用了，压缩算法会在原有的zone上标记movable pages和Free pages链表。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/4942e1a95d679b0904911b995b495816.png)



movable扫描器从底部到顶部扫描，free扫描器从顶部到底部扫描，movable和free扫描器最终会在中间的某点相遇。然后通过[页迁移](https://lwn.net/Articles/157066/)将已使用页转移到zone的顶端。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/07bbbc055a3aec1d09bf70a79d4ec32c.png)



*page compation两种触发方式*：

- 当分配page的时候，在LOW水位出现分配失败的时候，会尝试慢速内存分配，过程中就会出现page compaction
- 通过`echo x > /proc/sys/vm/compact_memory`来启动page compaction的动作，启动后内核线程`kcompactd`就会启动来进行页面整理



因为⻚⾯中数据被迁移到新位置，所以不会有采取的内存回收导致的那么⼤的性能问题，⽽且因为⽬标更明确，得到的连续⻚⾯的成本也更低。 另外ANON⻚⾯回收是需要SWAP的，⽽这⾥不需要。



此时再来看下/proc/pagetypeinfo的信息：

```shell
$ cat /proc/pagetypeinfo 
Page block order: 9
Pages per block:  512

...（DMA忽略）
Node    0, zone   Normal, type    Unmovable    870    530    391    157    103     41      9      2      1      0      0 
Node    0, zone   Normal, type      Movable   5886   9235   5728   4072   1561    324    115     41     12      4  13018 
Node    0, zone   Normal, type  Reclaimable      3      4      8     11      2      3      1      1      1      0      0 
Node    0, zone   Normal, type   HighAtomic      0      0      0      0      0      0      0      0      0      0      0 
Node    0, zone   Normal, type          CMA      0      0      0      0      0      0      0      0      0      0      0 
Node    0, zone   Normal, type      Isolate      0      0      0      0      0      0      0      0      0      0      0 
```

不同的page被分类，称为pageblock。每个pageblock根据其类型不同分成⼏个列表，分配内存的时候，根据申请⻚⾯类型的不同，向相应的列表中申请⻚⾯，⽽释放的时候也会根据其所属pageblock回到相应列表。不同的pageblock：

- Unmovable：无法压缩的page
- Movable：可压缩的page
- Reclaimable：可以回收的page
- HighAtomic：为了缓解碎片问题增加的pageblock。高阶并且具备同等级别的才能从该pageblock中申请page
- CMA：CMA 全称是 Contiguous Memory Allocator（连续内存分配器）
- Isolate：⻚⾯不会被分配，⽤来帮助isolate⻚⾯。isolate⻚⾯的时候会将⻚块先设置为isolate防⽌其被释放



CMA看上去又是一个大块知识，可以简单理解为buddy系统的补充：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/2ff3801ecac743a1e73092e6650cc041.png)

（内存之旅——如何提升CMA利用率？ https://ost.51cto.com/posts/10815）







## smaps & maps & pmap

***VSS/RSS/PSS/USS***

查看一个进程占用的内存，常有VSS/RSS/PSS/USS四种形式，主要是内存计算的口径不同



![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/e33fdc480dd60dff0646bd978cb29cb3.png)

（https://cloud.tencent.com/developer/article/1683708）

- VSS（Virtual Set Size）只是一个虚拟空间大小，对内存实际占用量意义不大。

- RSS（Resident Set Size）是对于计算一个进程总的内存占用量，包括共享库占用的共享内存大小，比如私有内存大小N，共享内存大小M，则RSS=N+M。肯能会有一点误解，因为像libc这种大部头库文件，共享者很多，都算在一个进程头上不科学。

- PSS （Proportional Set Size）是单个进程运行时实际占用的物理内存大小，包含比例分配共享库占用的内存，一个共享库有 N 个进程使用，那么该库比例分配给 PSS 的大小为 1/N。PSS计算进程内存更准确，除了自己独占的内存，再加上分到的共享部分。

- USS （Unique Set Size）是进程独自占用的物理内存大小，不包含共享内存

 

***/proc/[pid]/maps***

 /proc/[pid]/maps可查看**进程**的**虚拟内存**的**用户空间**内存映射

```shell
[pg@lzl 2345]$ cat maps 
起始地址-结束地址    权限  偏移地址 主次设备号 inode编号												 文件名
00400000-00bae000 r-xp 00000000 fd:00 1093852                            /pg/pg15.3/bin/postgres ---代码段
00dad000-00dc3000 rw-p 007ad000 fd:00 1093852                            /pg/pg15.3/bin/postgres
00dc3000-00df5000 rw-p 00000000 00:00 0 
00f1e000-00f60000 rw-p 00000000 00:00 0                                  [heap]                  ---heap区
33a6000000-33a6022000 r-xp 00000000 fd:00 1976006                        /lib64/ld-2.17.so
...
7fbe2ae09000-7fbe2ae0a000 rw-p 0000c000 fd:00 1975966                    /lib64/libnss_files-2.17.so
7fbe2ae1b000-7fbe33ca7000 rw-s 00000000 00:04 12556                      /dev/zero (deleted)
7fbe33ca7000-7fbe39b38000 r--p 00000000 fd:00 1181300                    /usr/lib/locale/locale-archive
7fbe39b38000-7fbe39b3d000 rw-p 00000000 00:00 0 
7fbe39b46000-7fbe39b4d000 rw-s 00000000 00:10 12559                      /dev/shm/PostgreSQL.3661351388
7fbe39b4d000-7fbe39b4e000 rw-s 00000000 00:04 32769                      /SYSV0010c0b6 (deleted)
7fbe39b4e000-7fbe39b4f000 rw-p 00000000 00:00 0 
7fffe3933000-7fffe3948000 rw-p 00000000 00:00 0                          [stack]                 --stack区      
7fffe397d000-7fffe397e000 r-xp 00000000 00:00 0                          [vdso]
ffffffffff600000-ffffffffff601000 r-xp 00000000 00:00 0                  [vsyscall]
```

(1)起始地址-结束地址：本段在虚拟内存中的地址范围
(2)权限：本段的权限; r-读，w-写，x-执行， p-私有
(3)偏移地址：即本段映射地址在文件中的偏移
(4)主次设备号：所映射的文件所属设备的设备号，对应vm_file->f_dentry->d_inode->i_sb->s_dev。**匿名映射为0。其中fd为主设备号，00为次设备号。**
(5)inode号：对应vm_file->f_dentry->d_inode->i_ino，**与ls –i显示的内容相符，匿名映射为0**。
(6)映射的文件名：对有名映射而言，是映射的文件名，对匿名映射来说，是此段内存在进程中的作用

以下是文心的分析：（真给它分析出来了，这是一个postgres主进程）

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/8f783ab400ad5df6d8bdd37fc54c49e5.png)



***/proc/[pid]/smaps***

/proc/[pid]/smaps 文件是基于 /proc/[pid]/maps 的扩展，比同一目录下的maps文件更为详细。每一个VMA都有如下的一系列数据：

```shell
[pg@lzl 2345]$ cat smaps 
00400000-00bae000 r-xp 00000000 fd:00 1093852                            /pg/pg15.3/bin/postgres
Size:               7864 kB   --VSS内存
Rss:                 408 kB		--RSS内存
Pss:                 140 kB		--PSS内存
Shared_Clean:        404 kB		--共享的、干净的内存大小
Shared_Dirty:          0 kB		--共享的、已脏的（即已修改）的内存大小
Private_Clean:         4 kB		--私有的、干净的内存大小
Private_Dirty:         0 kB		--私有的、已脏的内存大小
Referenced:          408 kB		--当前页面被标记为已引用或者包含匿名映射
Anonymous:             0 kB		--匿名页
AnonHugePages:         0 kB		--匿名大页
Swap:                  0 kB		--已交欢出的内存大小
KernelPageSize:        4 kB		--内核页面大小
MMUPageSize:           4 kB		--pagetable页面大小
...
7fffe3933000-7fffe3948000 rw-p 00000000 00:00 0                          [stack]
Size:                 88 kB
Rss:                  16 kB
Pss:                  16 kB
...
```



现在知道，maps是进程的内存映射信息，smaps还包含每段映射的内存大小（VSS,RSS,PSS）。

可通过查看进程smaps的PSS、RSS等数据，计算出进程的内存用量，注意单位是kb

*所有进程的物理总内存使用量*：

```shell
grep Pss /proc/[1-9]*/smaps | awk '{total+=$2}; END {printf "%d kB\n", total }'
```

*某进程PSS内存*：

```shell
cat /proc/90875/smaps |grep Pss |awk '{sum+=$2 };END {print sum/1024}'
```

*某进程的RSS内存* ：  

```shell 
cat /proc/68729/smaps |grep Rss |awk '{sum+=$2 };END {print sum/1024}'
```

*某进程私有内存*：

```shell
cat /proc/90875/smaps|sed '/zero/,/VmFlags/d' |grep Private |awk '{sum+=$2 };END {print sum/1024}'
```



***pmap***

pmap命令解析的是/proc/[pid]/maps和/proc/[pid]/smaps文件。参数不多，-x表示展示更多信息

```shell
[root@lzl ~]# pmap -x 2345
2345:   /pg/pg15.3/bin/postgres -D /pg/1503data
Address           Kbytes     RSS   Dirty Mode   Mapping
0000000000400000    7864     212       0 r-x--  postgres
0000000000dad000      88      12      12 rw---  postgres
0000000000dc3000     200      36      32 rw---    [ anon ]
0000000000f1e000     264      12       8 rw---    [ anon ]
00000033a6000000     136     108       0 r-x--  ld-2.17.so
...
00007fbe2ae09000       4       0       0 rw---  libnss_files-2.17.so
00007fbe2ae1b000  145968    4396    4396 rw-s-  zero (deleted)
00007fbe33ca7000   96836       8       0 r----  locale-archive
00007fbe39b38000      20      16      16 rw---    [ anon ]
00007fbe39b46000      28       4       4 rw-s-  PostgreSQL.3661351388
00007fbe39b4d000       4       0       0 rw-s-    [ shmid=0x8001 ]
00007fbe39b4e000       4       4       4 rw---    [ anon ]
00007fffe3933000      84      16      16 rw---    [ stack ]
00007fffe397d000       4       4       0 r-x--    [ anon ]
ffffffffff600000       4       0       0 r-x--    [ anon ]
----------------  ------  ------  ------
total kB          268896    5532    4540
```

pmap输出格式跟/proc/[pid]/maps差不多，每个vma地址一行，但是比maps多了VSS和RSS，这样就可以直接看进程虚拟内存的每个区域所使用的大小，帮助快速判断内存较多的区域在哪。

如果地址空间中[heap]太大，那有可能是堆内存产生了泄漏；再比如说，如果进程地址空间包含太多的 vma（可以把 maps 中的每一行理解为一个 vma），那很可能是应用程序调用了很多 mmap 而没有 munmap；再比如持续观察地址空间的变化，如果发现某些项在持续增长，那很可能是那里存在问题



***分析示例***

从主机的TOP的内存查看某pg backend进程内存看上去比较高，此时需要进一步分析map信息：

```shell
   PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND                                                                                                                                        
68729 postgres  20   0 5579004 5.116g 5.114g R  97.4  1.4 128:27.94 postgres: lzl: lzldb lzl 30.78.14.174(58067) DELETE 
```

查看这个进程Rss、Pss、Uss

```shell
cat /proc/68729/smaps |grep Rss |awk '{sum+=$2 };END {print sum/1024}'
5422.67  ---5.4G  Rss
cat /proc/68729/smaps |grep Pss |awk '{sum+=$2 };END {print sum/1024}'
467.957	 ---467mb Pss
cat /proc/68729/smaps|sed '/zero/,/VmFlags/d' |grep Private |awk '{sum+=$2 };END {print sum/1024}'
179.605  ---179mb Uss
```

Rss-Uss=5.3G的共享内存，从Pss-Uss=290mb的proportion共享内存，大致能看出这个backend只是这个共享内存proportion的一小部分

```shell
$ pmap -x 68729
68729:   postgres: pdmp: pdmpdata pdmp 30.78.14.174(46252) DELETE                           
Address           Kbytes     RSS   Dirty Mode  Mapping
0000000000400000    6084    2444       0 r-x-- postgres
0000000000bf0000       4       4       4 r---- postgres
0000000000bf1000      52      52      52 rw--- postgres
...
00002b7f65bfa000 5441216 5365444 5365444 rw-s- zero (deleted)   --这部分占用最多
00002b80b1daa000      48       0       0 r-x-- libnss_files-2.17.so
00002b80b1db6000    2044       0       0 ----- libnss_files-2.17.so
00002b80b1fb5000       4       4       4 r---- libnss_files-2.17.so
00002b80b1fb6000       4       4       4 rw--- libnss_files-2.17.so
00002b80b1fb7000      24       0       0 rw---   [ anon ]
00002b80ba001000     516     516     516 rw---   [ anon ]
00007fffe16f7000     132      88      88 rw---   [ stack ]
00007fffe175b000       8       4       0 r-x--   [ anon ]
ffffffffff600000       4       0       0 r-x--   [ anon ]
```

继续深入到smap分析，可以直接定位到zero (deleted)这部分

```shell
$ cat smaps 
00400000-009f1000 r-xp 00000000 fd:06 58726481                           /paic/postgres/base/9.6.6/bin/postgres
...
2b7f65bfa000-2b80b1daa000 rw-s 00000000 00:04 72254                      /dev/zero (deleted)
Size:            5441216 kB
Rss:             5365444 kB
Pss:              264618 kB
Shared_Clean:          0 kB
Shared_Dirty:    5365444 kB   --共享的脏数据
Private_Clean:         0 kB
Private_Dirty:         0 kB
Referenced:      5364764 kB
Anonymous:             0 kB
AnonHugePages:         0 kB
Swap:                  0 kB
KernelPageSize:        4 kB
MMUPageSize:           4 kB
Locked:                0 kB
VmFlags: rd wr sh mr mw me ms sd 
```

从以上分析可以得出：这是个pg的私有进程，变动了大量数据还没有刷脏，自己私有内存不多，大部分都是共享内存中占用的。这很有可能是一个pg中的事务变动了很多数据暂时还没提交。

另外，/dev/zero (deleted)在[proc(5) — Linux manual page](https://www.man7.org/linux/man-pages/man5/proc.5.html)有解释:

>Although these entries are present for memory regions that were mapped with the MAP_FILE flag, the way anonymous shared memory (regions created with the MAP_ANON | MAP_SHARED flags) is implemented in Linux means that such regions also appear on this directory.  Here is an example where the target file is the deleted /dev/zero one:
>
>                  lrw-------. 1 root root 64 Apr 16 21:33
>                              7fc075d2f000-7fc075e6f000 -> /dev/zero (deleted)



“非专业翻译”：匿名页和共享页由 /dev/zero (deleted)表示



##  /proc/[pid]/status

status可查看进程的状态信息，包含一部分内存信息。

```shell
[root@lzl 2345]#  cat status 
Name:   postgres			---运行这个线程的命令
State:  S (sleeping)	---进程状态
Tgid:   2345					---Thread group ID (i.e., Process ID)
Pid:    2345					---Thread ID
PPid:   1	   					---PID of parent process.
...
VmPeak:   268964 kB		---虚拟内存峰值
VmSize:   268896 kB		---虚拟内存当前值
VmLck:         0 kB
VmHWM:     13400 kB		---RSS的峰值
VmRSS:      5532 kB		---RSS的当前值
VmData:      528 kB		---数据段
VmStk:        88 kB		---stack段
VmExe:      7864 kB		---text段
VmLib:      3100 kB		---共享库代码段
VmPTE:       136 kB		---Page table entries
VmSwap:      308 kB		---swap的大小
Threads:        1			---该进程的线程数
....
```

status相对map，没有映射信息，内存数据更概况一些，也可以更直观的看到虚拟内存的每个段所占用的大小



*查看SWAP用量最多的进程*：

````shell
for file in /proc/*/status ; do awk '/VmSwap|Name|^Pid/{printf $2 " " $3}END{ print ""}' $file; done | sort -k 3 -n -r | head
````



## cgroup memory

[cgroup的memory控制](https://www.kernel.org/doc/Documentation/cgroup-v1/memory.txt)现在已经很常见。一些主机参数需要在cgroup中设置。内存设置、监控信息均在/sys/fs/cgroup/memory/下面

cginfo查看CGROUP内存分配和使用情况  ：  /opt/cgtools/cginfo -t perf -s mem 

```shell
cginfo -t perf -s mem
==================== Cgroup Performance: memory ====================
DB_TYPE     INSTANCE_NAME     MEM_OOM     MEM_FILE_GB    MEM_MAP_GB     MEM_USED_GB    MEM_ALLO_GB    ALLO_RATE      MEM_GLOB_GB    GLOB_RATE      
-------     -------------     -------     -----------    ----------     -----------    -----------    ---------      -----------    ---------      
postgres    LZLDB              0           154.3          0.0            4.2            160.0          2.6%           375            1.1%  
```



查看比较详细的CGROUP内存使用状态:    /sys/fs/cgroup/memory/[group]/memory.stat     

```shell
$ cat memory.stat 
...
total_cache 167791534080
total_rss 4006932480
total_rss_huge 0
total_mapped_file 11747328
total_swap 0
total_pgpgin 792754417976
total_pgpgout 792712474991
total_pgfault 477971874868
total_pgmajfault 97318
total_inactive_anon 1610874880
total_active_anon 2408255488
total_inactive_file 73446166528
total_active_file 94332768256
total_unevictable 0
```



## smem

[smem](https://linux.die.net/man/8/smem)是一款强大的展示内存使用情况的工具，读取/proc下面的smaps、meminfo等信息然后汇总输出。smem可以输出总体和具体map的内存情况，非常直观而且可以从不同的维度去分析，总体是一款分析内存使用非常好用的工具。

[repo](https://selenic.com/repo/smem)可直接下载，基本上解压即可使用。更多用法可参考[smem memory reporting tool](https://www.selenic.com/smem/)，以下只简单示例：

查看系统内存使用 `-w`：

```shell
[root@lzl ~]# smem -w -k
Area                           Used      Cache   Noncache 
firmware/hardware                 0          0          0 
kernel image                      0          0          0 
kernel dynamic memory        183.9M      84.0M      99.9M 
userspace memory             112.3M      62.2M      50.1M 
free memory                  700.3M     700.3M          0 
```

查看每个用户的内存消耗 `-u`:

```shell
[root@lzl ~]# smem -s pss -urk
User     Count     Swap      USS      PSS      RSS 
oracle      25    85.2M    30.8M    95.7M   383.0M 
root        93   112.4M    38.5M    42.3M    86.2M 
pg          12     5.9M     1.6M     2.5M     5.9M 
mysql        1   169.7M     1.7M     1.7M     2.0M 
```

查看某个用户的内存消耗`-U`

```shell
[root@lzl ~]# smem -U pg -k
  PID User     Command                         Swap      USS      PSS      RSS 
 2345 pg       /pg/pg15.3/bin/postgres -D    364.0K   124.0K   134.0K   228.0K 
 2352 pg       postgres: logical replicati   636.0K   144.0K   161.0K   196.0K 
 ...
```

过滤某个进程 `-P`（PROCESSFILTER，不是pid）：

```
[root@lzl ~]# smem -P postgres -p
  PID User     Command                         Swap      USS      PSS      RSS 
 2346 pg       /pg/pg16.0/bin/postgres -D     0.01%    0.01%    0.01%    0.01% 
 2350 pg       postgres: walwriter            0.01%    0.01%    0.01%    0.01% 
 ...
```

查看进程的mapping和内存占用情况 `-m`：

```shell
[root@lzl ~]# smem -P postgres -mpr -s pss
Map                                       PIDs   AVGPSS      PSS 
<anonymous>                                 13    0.02%    0.24% 
[heap]                                       3    0.07%    0.20% 
/usr/lib64/libpython2.6.so.1.0               1    0.11%    0.11% 
/pg/pg15.3/bin/postgres                      6    0.01%    0.06% 
/pg/pg16.0/bin/postgres                      6    0.01%    0.06% 
/dev/zero                                   12    0.00%    0.03% 
[stack]                                     13    0.00%    0.02% 
...
```

smem看进程内存的USS\PSS\RSS很直观，不过有个问题，smem不能过滤pid，只能通过用户名或PROCESSFILTER去过滤，对于一个主机部署多个数据库实例时，过滤父PID或子PID，不是很友好。



## top

[top](https://man7.org/linux/man-pages/man1/top.1.html)可实时的展示系统运行状态。top玩法也可以非常花哨，直接top运行同样可以展示非常多的信息。

使用top中的排序：

```shell
command   sorted-field                  supported
M         %MEM                          Yes
N         PID                           Yes
P         %CPU                          Yes
T         TIME+                         Yes
```

可以用%MEM来排序内存占用较多的进程，%MEM表示RES的内存百分比

```shell
top - 23:38:01 up 3 days, 22:32,  2 users,  load average: 1.12, 1.42, 1.09
Tasks: 198 total,  13 running, 183 sleeping,   0 stopped,   2 zombie
Cpu(s):  0.0%us,  0.3%sy,  0.0%ni, 99.7%id,  0.0%wa,  0.0%hi,  0.0%si,  0.0%st
Mem:   1020348k total,   325848k used,   694500k free,     1352k buffers
Swap:  4128760k total,   635872k used,  3492888k free,   150288k cached

  PID USER      PR  NI  VIRT  RES  SHR S %CPU %MEM    TIME+  COMMAND                                                                                       
18537 oracle    20   0  636m  24m  21m S  0.0  2.4   0:05.41 oracle                                                                                        
18533 oracle    20   0  638m  24m  21m S  0.0  2.4   0:02.01 oracle                                                                                        
...                                                                                       
18509 oracle    20   0  634m 4384 4036 S  0.0  0.4   0:01.93 oracle                                                                                        
 2639 root      20   0  729m 4052 1444 S  0.0  0.4   8:45.32 nautilus 
```

内存相关的解读：

第四行：
内存使用信息：物理内存量、已用内存量、空闲内存量、缓冲内存量
第五行：
交换分区信息：可用交换区总量、已用交换区总量、空闲交换区总量、内核用于缓存的数量

第六行（内存相关）：

- VIRT：VSS
- RES：RSS（likely），anything occupying physical memory
- SHR：Shared Memory Size。It will include shared anonymous pages and shared file-backed pages
- %MEM： RSS百分比，A task's currently resident share of available physical memory.



另外，查看内存的时候不要忘了看一眼进程的状态

S（示例第八列）Process Status：

- D = uninterruptible sleep。不可中断的睡眠状态。表示该进程正在等待某个外部事件完成，如磁盘I/O操作或网络请求。通常情况下，D进程不能被直接终止。
- I = idle
- R = running
- S = sleeping
- T = stopped by job control signal
- t = stopped by debugger during trace
- Z = zombie



top命令可以看到主机的内存汇总信息，进程使用内存信息有RSS,SHR，粗略算一下RES-SHR=USS也可以计算私有内存的占用大小，另外还可以看到进程状态，所以top -p查看某进程的内存基本信息还是很好用的。



## free

[free](https://man7.org/linux/man-pages/man1/free.1.html)展示主机的swap、内存的总量和剩余量，信息都是解析自/proc/meminfo

```
user@ubuntu:~$ free

          total    used      free   shared   buff/cache  available
Mem:    8029356  794336   6297928   183384       937092    6816804
Swap:         0       0         0
```

- total ：Total usable memory (MemTotal and SwapTotal in /proc/meminfo). This includes the physical and swap memory minus a few reserved bits and kernel binary code.

- used ： Used or unavailable memory (calculated as total - available)

- free：Unused memory (MemFree and SwapFree in /proc/meminfo) shared Memory used (mostly) by tmpfs (Shmem in /proc/meminfo)

- buffers：Memory used by kernel buffers (Buffers in /proc/meminfo)

- cache：Memory used by the page cache and slabs (Cached and SReclaimable in /proc/meminfo)。不仅有pagecache，还有SReclaimable的slab！

- buff/cache：Sum of buffers and cache
- available：cache包含pagecache和SReclaimable，free包含mem free和swap free；而available包含pagecache和即将被reclaim的内存；表示可用内存，但它们的计算方式不同，在实际应用中，由于缓存的存在，available通常会比free大



Page Cache：
Page cache 主要用来作为文件系统上的文件数据的缓存来用，尤其是针对当进程对文件有 read/write 操作的时候。

Buffer Cache：
Buffer cache 则主要是设计用来在系统对块设备进行读写的时候，对块进行数据缓存的系统来使用



## ps aux

ps最大的好处就是从进程的角度分析进程状态（包括内存），COMMAND带[ ]标志的进程为kernel进程。

```
[pg@lzl ~]$ ps  aux|head -1;ps aux|grep postgres
USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
pg        2345  0.0  0.0 268896   236 ?        Ss   Jan01   0:03 /pg/pg15.3/bin/postgres -D /pg/1503data
pg        2353  0.0  0.0 269040   196 ?        Ss   Jan01   0:00 postgres: checkpointer                 
pg        2354  0.0  0.0 269032   160 ?        Ss   Jan01   0:02 postgres: background writer            
pg        2356  0.0  0.0 269032   116 ?        Ss   Jan01   0:01 postgres: walwriter                    
pg        2357  0.0  0.0 270508   824 ?        Ss   Jan01   0:02 postgres: autovacuum launcher          
pg        2358  0.0  0.0 270492   620 ?        Ss   Jan01   0:00 postgres: logical replication launcher 
pg       29818  0.0  0.0 103372   868 pts/0    S+   09:16   0:00 grep postgres
```

VSZ,RSS单位是kb。内存信息比较少，VSZ没什么价值，RSS可以参考一下，没有PSS，USS这类信息，能分析的内容不多



## ipcs

`ipcs -m` 是一个用于查询 IPC（进程间通信）共享内存资源的命令。分析共享内存的时候比较有用。

```shell
[pg@lzl ~]$ ipcs -m

------ Shared Memory Segments --------
key        shmid      owner      perms      bytes      nattch     status      
0x0010c0b6 32769      pg         600        56         6   
```

- 共享内存的 key 值
- 共享内存的编号 (shmid)
- 创建该共享内存的用户
- 权限（perms）
- 创建的大小（bytes）
- 连接到该共享内存的进程数（nattach）
- 共享内存的状态



此时连接一个会话到PostgreSQL，会多一个backend进程

```shell
------ Shared Memory Segments --------
key        shmid      owner      perms      bytes      nattch     status   
0x0010c0b6 32769      pg         600        56         7                       
```

nattch+1，说明私有的backend进程也分享了一部分PG共享出来的内存。此时理解下面这个图也更深刻

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/070159d5ad7cda946b36219be7608941.png)

（http://gauss.ececs.uc.edu/Courses/c4029/code/memory/virtual.pdf）



## vmstat

[vmstat](https://man7.org/linux/man-pages/man8/vmstat.8.html)是Virtual Meomory Statistics（虚拟内存统计）的缩写，可对操作系统的虚拟内存、进程、CPU活动进行监控。它是对系统的整体情况进行统计，不足之处是无法对某个进程进行深入分析。
*有用的*参数说明：

```shell
vmstat [options] [delay [count]]
OPTIONS:
-a 显示活跃和非活跃内存
-m 显示slabinfo
-s 显示内存相关统计信息及多种系统活动数量
-t Append timestamp to each line，在最后加个输出时间戳
-w Wide output mode.没有加w的话，输出比较窄，可以减少对不齐问题
```

```shell
-bash-4.1$ vmstat -w 1 3
procs -------------------memory------------------ ---swap-- -----io---- --system-- -----cpu-------
 r  b       swpd       free       buff      cache   si   so    bi    bo   in   cs  us sy  id wa st
 0  1     661652     763348        324      76100   15   12    54    21   18   45   0  0  79 21  0
 2  1     661652     763340        304      75764    0    0     0    32   12   84   0  1   0 99  0
41  1     661652     760744        244      78300  228    0  3216     0  265  442   0  0   0 100  0
```



![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/96c2ccda558c45411266dae6c580ac15.png)





## pidstat

[pidstat](https://man7.org/linux/man-pages/man1/pidstat.1.html)是sysstat工具的一个命令，用于监控全部或指定进程的CPU、内存、线程、设备IO等系统资源的占用情况。

*有用的*参数说明：

```shell
pidstat OPTIONS interval [ count ] 
-d :Report I/O statistics 
-u :Report CPU utilization
-r :Report page faults and memory utilization
-w :Report task switching activity
-p :pid[,...] 
-l :Display the process command name and all its arguments.
```

查看某进程的内存情况：

```shell
-bash-4.1$ pidstat -r -l  -p 2345
Linux 2.6.32-431.el6.x86_64 (lzl)       01/06/2024      _x86_64_        (1 CPU)

02:48:32 PM       PID  minflt/s  majflt/s     VSZ    RSS   %MEM  Command
02:48:32 PM      2345      0.23      0.00  268896    240   0.02  /pg/pg15.3/bin/postgres -D /pg/1503data 
```

各类指标比较容易理解，VSZ,RSS说的都不想说了

- minflt/s：这是“minor page faults”的缩写，指的是每秒发生的“次要页面错误”的数量。当一个程序试图访问一个不在物理内存中的页面时，就会发生页面错误。如果这个页面确实在硬盘上的交换区（swap）中，那么这是一个次要页面错误（minor page fault）。

- majflt/s：这是“major page faults”的缩写，指的是每秒发生的“主要页面错误”的数量。与次要页面错误不同，主要页面错误发生在程序试图访问一个不在物理内存中，且也不在硬盘上的交换区中的页面时。



## sar

[sar](https://man7.org/linux/man-pages/man1/sar.1.html)（System Activity Reporter 系统活动情况报告）是目前 Linux 上最为全面的系统性能分析工具之一，可以从多方面对系统的活动进行报告，包括：文件的读写情况、系统调用的使用情况、磁盘 I/O、CPU 效率、内存使用状况、进程活动及 IPC 有关的活动等。SAR工具是sysstat软件包的一部分。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/112652d136f48977c71072906796af6d.png)

(https://www.brendangregg.com/Perf/linux_observability_sar.png)

sar非常强大，man的参数介绍就有1k多行，本篇不太可能解释完（偷懒）。

内存相关的参数：

```shell
sar OPTIONS interval [ count ] 
-B :Report paging statistics
-r :Report memory utilization statistics
-W :Report swapping statistics.
-H :Report hugepages utilization statistics
-s [ start_time ] ] [ -e [ end_time ] 
```

示例：sar查看内存利用率
```sar -r 1 3```

 - kbmemfree：这个值和 free 命令中的 free 值基本一致，所以它不包括 buffer 和 cache 的空间
 - kbmemused：这个值和 free 命令中的 used 值基本一致，所以它包括 buffer 和 cache 的空间
 - %memused：这个值是 kbmemused 和内存总量(不包括 swap)的一个百分比
 - kbbuffers :   free 命令中的 buffer
 - kbcached： free 命令中 cache
 - kbcommit：保证当前系统所需要的内存，即为了确保不溢出而需要的内存(RAM + swap)
 - %commit：这个值是 kbcommit 与内存总量(包括 swap)的一个百分比

示例：sar查看内存页的状态
```sar -B 1 3```

 - pgpgin/s：表示每秒从磁盘或SWAP置换到内存的字节数(KB)
 - pgpgout/s：表示每秒从内存置换到磁盘或SWAP的字节数(KB)
 - fault/s：每秒钟系统产生的缺页数，即主缺页与次缺页之和(major + minor)
 - majflt/s：每秒钟产生的主缺页数
 - pgfree/s：每秒被放入空闲队列中的页个数
 - pgscank/s：每秒被 kswapd 扫描的页个数
 - pgscand/s：每秒直接被扫描的页个数
 - pgsteal/s：每秒钟从 cache 中被清除来满足内存需要的页个数
 - %vmeff：每秒清除的页(pgsteal)占总扫描页(pgscank + pgscand)的百分比

示例：sar查看swap信息
```sar -W 1 3```
报告说明

 -  pswpin/s：每秒系统换入的交换页面（swap page）数量
 -  pswpout/s：每秒系统换出的交换页面（swap page）数量

示例：sar查看历史内存信息
```sar -B -s "08:00:00" -e "10:00:00"```



```shell
#不加-e表示从开始时间点到现在的信息
$ sar -B -s "08:00:00"
09:45:01 PM  pgpgin/s pgpgout/s   fault/s  majflt/s  pgfree/s pgscank/s pgscand/s pgsteal/s    %vmeff
09:46:01 PM 414429.37 395024.08 179478.63      0.07 352922.62  12003.78   4266.52  16269.42     99.99
09:47:01 PM 879907.08 337948.43 157970.97      0.02 402290.21      0.00      0.00      0.00      0.00
09:48:01 PM 772977.43 507343.30 150255.50      0.05 466742.08      0.00   5821.28   5821.27    100.00
```

以上pgsank表示kswapd进程介入回收内存的速度，pgscand表示直接内存回收的速度



## gcore

[gcore](https://man7.org/linux/man-pages/man1/gcore.1.html)是gdb的一部分，可生成进程的core dump文件

示例dump一个PostgreSQL的backend进程

```shell
[root@lzl ~] ps -ef|grep 8296
pg        8296  2345  0 09:41 ?        00:00:00 postgres: pg lzldb [local] idle  
[root@lzl ~] cat /proc/8296/smaps |grep Pss |awk '{sum+=$2 };END {print sum/1024}'       
0.351562
[root@lzl ~] cat /proc/8296/smaps |grep Rss |awk '{sum+=$2 };END {print sum/1024}'
0.445312
[root@lzl ~] cat /proc/8296/smaps|sed '/zero/,/VmFlags/d' |grep Private |awk '{sum+=$2 };END {print sum/1024}'
0.0078125
```

8296进程的uss只有7.8 bytes，RSS 445 bytes。dump内存：

```
gcore -o /tmp/dump 8296
```

dump要花点时间，而且dump下来的文件比较大，并且会夯住进程

```c
[root@lzl 8296]# ls -lh /tmp/dump.8296 
-rw-r--r-- 1 root root 252M Jan  7 10:59 /tmp/dump.8296
```



## gdb

[gdb](https://sourceware.org/gdb/current/onlinedocs/gdb)可查看内存中具体位置和内容

示例查看PostgreSQL backend的缓存数据

1.新开一个会话查找一个分区表，会话保持不断开

```sql
[pg@lzl ~]$ psql
psql (15.3)
Type "help" for help.

postgres=> \c lzldb
You are now connected to database "lzldb" as user "pg".
lzldb=> select * from lzlpartition limit 1;
 appl_no | is_deleted | date_created | date_updated 
---------+------------+--------------+--------------
(0 rows)
```

2.pmap，smaps查看进程内存占用情况，找到想dump的内存段

```shell
[root@lzl 13393]# pmap -x 13393
13393:   postgres: pg lzldb [local] idle        
Address           Kbytes     RSS   Dirty Mode   Mapping
0000000000400000    7864    1204       0 r-x--  postgres
..
00007fbe2ae1b000  145968    2164     176 rw-s-  zero (deleted)  ---RSS这里占用最多
00007fbe33ca7000   96836       0       0 r----  locale-archive
00007fbe39b38000      20       0       0 rw---    [ anon ]
00007fbe39b46000      28       0       0 rw-s-  PostgreSQL.3661351388
00007fbe39b4d000       4       0       0 rw-s-    [ shmid=0x8001 ]
00007fbe39b4e000       4       0       0 rw---    [ anon ]
00007fffe3933000      84      36       0 rw---    [ stack ]
00007fffe397d000       4       4       0 r-x--    [ anon ]
ffffffffff600000       4       0       0 r-x--    [ anon ]

[root@lzl 13393]# cat /proc/13393/smaps |grep -A 13 zero
7fbe2ae1b000-7fbe33ca7000 rw-s 00000000 00:04 12556                      /dev/zero (deleted)
Size:             145968 kB
Rss:                2164 kB
Pss:                2164 kB
Shared_Clean:          0 kB
Shared_Dirty:          0 kB
Private_Clean:      1988 kB
Private_Dirty:       176 kB
Referenced:         2164 kB
Anonymous:             0 kB
AnonHugePages:         0 kB
Swap:                  0 kB
KernelPageSize:        4 kB
MMUPageSize:           4 kB
```

3.gdb dump memory

dump内存的起始位置为smaps中的vm地址+`0x`

```shell
[pg@lzl tmp]$ gdb
(gdb) attach 13393
(gdb) dump memory /tmp/delete.dump 0x7fbe2ae1b000 0x7fbe33ca7000
```

4.查看dump文件

可简单通过strings 查看

```shell
[root@lzl 13393]#  strings /tmp/delete.dump|grep lzl|sort|uniq
...
 @lzlpartition_202301
lzlpartition_202301
lzlpartition_202301_appl_no_idx
lzlpartition_202301_date_created_idx
...
lzlpartition_202306
lzlpartition_202306_appl_no_idx
lzlpartition_202306_date_created_idx
 @lzlpartition_attach
lzlpartition_attach
 @nk_lzlpartition
nk_lzlpartition
select * from lzlpartition limit 1;
```

会话只要查询了分区表，就把所有分区、索引等元数据全部缓存到backend进程中

注意：

- gdb attach [pid]会夯住进程，不要随意执行
- dump文件大小等于VSS，一般远大于RSS/PSS/USS





# 内存小节

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/09fc633afef0c0504456e881d64480b5.png)



# references

轻松突破文件IO瓶颈：内存映射mmap技术 <https://blog.51cto.com/u_15481245/6582927>

一步一图带你深入理解 Linux 物理内存管理 <https://cloud.tencent.com/developer/article/2352771?areaId=106001>

从DBA的角度系统学习一下内存管理 <https://mp.weixin.qq.com/s/CybzGP44dVWQN5hfFrVx7A>

<https://linux2me.wordpress.com/2017/09/15/linux-introduction-to-memory-management/>

Memory management in Linux <https://www.slideshare.net/raghusiddarth/memory-management-in-linux-11551521?from_search=2>

Linux Performance Tunning Memory <https://www.slideshare.net/shayc1/linux-performance-tunning-memory?from_search=4>

Linux内核这样学才能学会（内存篇） <https://mp.weixin.qq.com/s/lKKHH1MMiZbnIbDQt3-IAQ>

<https://courses.engr.illinois.edu/cs241/sp2014/lecture/09-VirtualMemory_II_sol.pdf>

Linux的进程虚拟地址空间 <https://maodanp.github.io/2019/06/02/linux-virtual-space/>

redhat官方文档 <https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/7/html/virtualization_tuning_and_optimization_guide/chap-virtualization_tuning_optimization_guide-numa>

Data Processing on Modern Hardware <https://db.in.tum.de/teaching/ss21/dataprocessingonmodernhardware/MH_8.pdf?lang=de>

Chapter 2  Describing Physical Memory <https://www.kernel.org/doc/gorman/html/understand/understand005.html>

各类命令的man手册

linux强制回收内存,linux内存源码分析 - 内存回收(整体流程) <https://blog.csdn.net/weixin_35094083/article/details/116688112>

<Memory compaction https://lwn.net/Articles/368869/>

内存之旅——如何提升CMA利用率？ <https://ost.51cto.com/posts/10815>

The implementations of anti pages fragmentation in Linux kernel <https://teawater.github.io/presentation/antif.pdf>

T H E  /proc   F I L E S Y S T E M <https://www.kernel.org/doc/Documentation/filesystems/proc.txt>

The /proc/meminfo File in Linux <https://www.baeldung.com/linux/proc-meminfo>

the proc filesystem <https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/6/html/deployment_guide/s2-proc-meminfo>

linux的/proc/{pid}/maps介绍及使用(定位内存泄漏) <https://blog.csdn.net/mijichui2153/article/details/123934531>

Linux top命令的cpu使用率和内存使用率 <https://blog.csdn.net/weixin_45030965/article/details/127693042>

smem memory reporting tool <https://www.selenic.com/smem/>

Linux performance optimization <https://feiyang233.club/post/linux/>

gdb onlinedocs  <https://sourceware.org/gdb/current/onlinedocs/gdb>

Linux_Core_Dumps <https://averageradical.github.io/Linux_Core_Dumps.pdf>

