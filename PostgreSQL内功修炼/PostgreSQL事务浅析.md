# PG的事务

为了保证事务的ACID特性，rdbms必须要实现并发控制。pg和oracle、mysql(innodb)数据库都使用MVCC来实现并发控制。MVCC通过数据变化时不断生成新版本对象和可查询一定范围的老版本对象来实现并发，MVCC保存数据在某个时间点的快照，读数时选择一个版本进行读取。

oracle、mysql都通过undo来记录老版本对象，pg没有undo，而是在DML时在直接将历史数据写在原表上（update会创建新行，delete标记行），并在表中记录额外的列xmin,xmax来记录事务号，通过对比事务号和一些其他信息来实现mvcc机制。

在众多关系型数据库中，pg的事务机制非常有特色，了解pg的事务机制是了解pg数据库运行原理的关键。



# 事务隔离级别

一般关系型数据库都可以设置多个不同的事务隔离级别。在不步的事务隔离级别下，事务并发行为有所不同

## 设置事务隔离级别

pg支持设置4种事务隔离级别（实际上只会生效有3个）

```sql
{ SERIALIZABLE | REPEATABLE READ | READ COMMITTED | READ UNCOMMITTED }
```

**事务隔离级别参数**

`default_transaction_isolation`：设置全局事务的默认隔离级别

`transaction_isolation`:设置当前会话的事务隔离级别

默认隔离级别`read committed`

**修改全局事务的默认隔离级别**

直接修改`default_transaction_isolation`参数，然后`reload`即可

修改完成后，每个新的事物都会使用`default_transaction_isolation`隔离级别

```sqlite
postgres=# alter system set default_transaction_isolation to 'serializable';
ALTER SYSTEM
postgres=# select pg_reload_conf();
 pg_reload_conf 
----------------
 t
 (1 row)
 postgres=# show transaction_isolation;
 transaction_isolation 
-----------------------
 serializable
```

**设置当前会话的隔离级别**

注意参数`transaction_isolation`只是展示当前会话的隔离级别，这个参数是不可以直接修改的

```sqlite
lzldb=# alter system set transaction_isolation to 'REPEATABLE READ';
ERROR: parameter "transaction_isolation" cannot be changed
```

通过`SET SESSION`修改会话的隔离级别，例如：

```sqlite
lzldb=# SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET
lzldb=# show transaction_isolation ;
-[ RECORD 1 ]---------+----------------
transaction_isolation | repeatable read
```

**设置事务的隔离级别**

pg可以指定事务本身的隔离级别

可通过在开启事务时设置事务的隔离级别，例如：

```sqlite
lzldb=# BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
BEGIN
lzldb=# start TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION
```

或者开启事务后`set transaction`

```sqlite
lzldb=# begin;
BEGIN
lzldb=*# set transaction ISOLATION LEVEL REPEATABLE READ;
SET
```


## ANSI92的事务隔离级别

在*ANSI SQL-92*事务隔离级别标准中包含4种隔离级别：

**Serializable(可串行化或称可序列号)**

 系统中所有的事务串行化执行，事务之间互不影响。

以串行地方式逐个执行，能避免所有数据不一致情况。

 早期以排他锁来控制并发事务，串行化执行方式会导致事务排队，系统的并发量大幅下，不过ANSI 92后出现更多序列化实现方法，并发性和性能均有较大提升。

**Repeatable read(可重复读)**

一个事务一旦开始，事务过程中所读取的所有数据不允许被其他事务修改。可重复读是mysql的默认隔离级别。

注意， 在ANSI SQL中可重复读级别可发生幻读，但是pg的可重复读不会发生幻读

**Read Committed(已提交读)**

一个事务能读取到其他事务提交过的数据。

事务在处理过程中如果重复读取某一个数据，而且这个数据恰好被其他事务修改并提交了， 那么当前重复读取数据的事务就会出现同一个数据前后不同的情况。 已提交读是oracle、pg的默认隔离级别

在这个隔离级别会发生“不可重复读”和”幻读“的场景。

**Read Uncommitted(未提交读)**

一个事务能读取到其他事务修改过，但是还没有提交的(Uncommitted)的数据。

数据被其他事务修改过，但还没有提交，就存在着回滚的可能性，这时候读取这些“未提交” 数据的情况就是“脏读”。

在这个隔离级别会发生“脏读”场景。 

pg没有未提交读这个隔离级别，设置未提交读会被当做已提交读

 

**标准的一致性读和隔离级别矩阵**

| 事务隔离级别 | 脏读   | 不可重复读 | 幻影读 |
| ------------ | ------ | ---------- | ------ |
| 未提交读     | 可能   | 可能       | 可能   |
| 已提交读     | 不可能 | 可能       | 可能   |
| 可重复读     | 不可能 | 不可能     | 可能   |
| 序列化       | 不可能 | 不可能     | 不可能 |

 

**pg的一致性度和隔离级别矩阵**

| 事务隔离级别 | 脏读   | 不可重复读 | 幻影读 |
| ------------ | ------ | ---------- | ------ |
| 未提交读     | 不可能 | 可能       | 可能   |
| 已提交读     | 不可能 | 可能       | 可能   |
| 可重复读     | 不可能 | 不可能     | 不可能 |
| 序列化       | 不可能 | 不可能     | 不可能 |

## 事务隔离级别的历史

ANSI SQL-92定义的隔离级别和异常现象确实对数据库行业影响深远，甚至30年后的今天，绝大部分工程师对事务隔离级别的概念还停留在此，甚至很多真实的数据库隔离级别实现也停留在此。但后ANSI92时代对事物隔离有许多讨论甚至批评，针对隔离级别和异常现象的论文、博客、文章、讨论非常多，这里概况一下事务的比较重要发展历史：

- 1992年，由于数据库行业处于混沌的事务状态，美国国家标准学会定义ANSI SQL-92标准。也就是广泛流传的4种隔离级别和4种异常现象 

- 1995年，snapshot isolation等隔离级别提出和更多的异常现象。微软工程师等提出snapshot isolation隔离级别，并对ANSI SQL-92做出批判，92标准定义模糊，而且有许多隔离级别和异常现象未定义。参考[《对ANSI SQL隔离级别的批判》](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf ).

  此时隔离级别已不止4个，异常现象也更多，其中也包括写偏序异常。

- 1999年 ，由于锁模式的不同发展出过多的隔离级别，[Atul Adya的论文](http://publications.csail.mit.edu/lcs/pubs/pdf/MIT-LCS-TR-786.pdf)整理了这些现象，并根据异常现象和功能将众多隔离级别回溯到ANSI SQL92标准进行对应。

- 2005年 ，由于绝大部分数据库声称他们是可串行化的，但他们实际上是快照隔离， Alan Fekete et al 提出[“使快照隔离可序列化”]( https://pdfs.semanticscholar.org/d658/2728e30011adfe27b329c35203dfb8d1e7a8.pdf)。在snapshot isolation级别基础上实现可序列化，消除快照隔离的异象。

- 2008年 ，Fekete 扩展了可序列化，并提出数据库层面实现“使快照隔离可序列化”，称之为[快照隔离可序列化SSI (Serializable Snapshot Isolation) ](https://cs.nyu.edu/courses/fall09/G22.2434-001/p729-cahill.pdf)

- 2012年 ，postgresql第一个在数据库中实现SSI ，参考[postgresql数据库实现SSI的论文](https://drkp.net/papers/ssi-vldb12.pdf)

  

其中，95年《对ANSI SQL隔离级别的批判》中的隔离级别和异常现象
![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/133096f5549b12c15e739e460cbfe254.png)


## 各种数据库支持的隔离级别

很多数据库的声称他们”完全支持ACID“特性，但是没有可串行化是不能完全实现ACID的（特别是一致性）。然而许多数据库在不支持可串行化级别下声称他们支持ACID。其实他们绝大部分都没有完全实现，包括数据库老大哥oracle。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/537227ac85413b1d19cceef604f36fe1.png)




## 可串行化

人们对可串行化存在许多误解。

可串行化的含义：如果每个事务本身是正确的，即满足某些完整性条件，那么包括这些事务的任何串行执行的时间表是正确的（其事务仍然满足其条件）：“串行”意味着事务在时间上不重叠，并且不能相互干扰，即彼此之间存在完全隔离。

1970年代可串行化（serializable）通过严格两阶段锁（SS2PL）实现，读写相互阻塞，直到事务结束。SS2PL丢失高可用性但消除了异常现象。

除了SS2PL实现可串行化，还有其他方式，比如可串行化快照隔离（SSI）。

为了保证没有异常，可串行化会丢失一些并发性（不同实现方式有所不同），但可以真正保证数据的一致性（ACID中的consistency）。也就是说没有实现串行化的数据库，其实没有完全支持ACID特性

可串行化在数学上已经证明可以实现，但是真实的数据库世界有点”不正常“。实际上，可串行化是事务隔离级别中最高级的，也是所有学者和大佬强力推荐的隔离级别，不过绝大部分数据库在RC或快照隔离级别上运行

## 为什么弱隔离级别在学术上有问题，实际上没出现严重问题？

1.非可串行化隔离级别的异常现象，一般都需要再高并发情况下才会发生，一般低并发数据库不太会出现问题

2.异常现象真的发生的时候，有些应用可能没发现异常现象或没检查到异常对他们不重要。

3.有可能数据异常了，但应用只是返回报错，并进入数据异常处理程序。

4.成本过高。不仅是数据库序列化隔离级别开发成本高，应用对可序列化也需要适应成本。光是理解这部分复杂的理论就不是一件容易的事

5.高级别的隔离会丢失一些性能。大量的改造工作可能是吃力不讨好的，应用需要在“高并发”和“无异常现象”间做抉择

6.业务基于机制开发，而不是规则开发。业务多少有点适应弱隔离级别的异常现象，特别是RC或快照隔离级别  

## 快照隔离

ANSI SQL92并未定义快照隔离snapshot isolation(SI)，这个隔离级别随着数据库行业发展才出现。

引自wiki定义：在快照隔离下执行的事务是在事务开始时拍摄的数据库的快照上操作的。当事务结束时，只有当事务更新的值自快照拍摄以来没有外部更改时，它才会成功提交。这样写冲突将导致事务中止。

快照隔离级别顾名思义就是就是使用了快照，存在于使用了MVCC的数据库中，多版本并发机制支持用户并发执行事务。

1992年 ANSI SQL92标准基于数据库的锁而定义，所以没有快照隔离级别这个定义。直到1995年《批判》的出现才被提出。

## 快照隔离串行化

由于快照隔离的广泛应用，而可序列化是学术上的数据库需要达到的隔离级别目标，可序列化快照隔离Serializable Snapshot Isolation (SSI) 随即产生。顾名思义，在快照隔离的基础上实现可序列化。

由于ANSI92标准的模糊性，虽然没有定义快照隔离，但许多数据库实际上就是使用的快照隔离。而快照隔离同样存在一些异常现象（包括写偏序），SSI的出现就是为了解决这些异常现象。

主流数据库通过基于S2PL或MVCC实现并发控制。在S2PL下写操作会阻塞其他事务读写，因此不会有写偏序异常问题。而MVCC实现了读写互不阻塞，只有写写冲突。在并发RW模式模式下会导致写偏序问题。SSI在pg9.1开始已经嵌入快照隔离SI中（pg只有快照隔离，哪怕是在可序列化级别下），解决了写偏序等异常。

## 写偏序

由于某些冲突构成环，会出现串行化异常**。**其中比较容易理解的一个就是写偏序(write skew)。

写偏序只发生在rw模型，ww、wr均不会发生写偏序，并且事务必须在并发条件下才会出现。前一个事务写入依赖后一个事务写入才会形成依赖环。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/b02dc01651f6a4b47ad6d66669abde0f.png)


有许多现实案例可以出现写偏序异常，我们用一个经典的**黑白球问题**来理解写偏序

袋中有10个球，5个白球和5个黑球。此时有两个事务，P和Q。P将所有黑球改成白球，Q将所有白球改成黑球。此时可以有两个串行执行，P，Q或Q，P。在这两种情况下，最终结果是袋中有10个白球或者10个黑球。但是，快照隔离允许另一种结果：

- 事务 P 拿出5个黑球
- 事务 Q 拿出5个白球
- 事务 P 将手中所有黑球改成白球，放回袋中
- 事务 Q 将手中所有白球改成黑球，放回袋中

此时袋中还是5个黑球和5个白球，这在任何一个串行执行中都是不可能的。但这在快照隔离中是有效：每个事务都维护数据库的一致视图，并且其写集不与任何并发事务的写集重叠，如此白球黑球发生交换。

黑白球问题说明：快照隔离执行结果与串行化执行结果不一致，快照隔离下发生写偏序异常，数据结果与预期不一致。

## pg中的SSI

postgresql数据库是首个在数据库中实现SSI的数据库。

引用wiki的黑白球代码示例

```sql
create table dots
  (
   id int not null primary key,
   color text not null
  );
 insert into dots
  with x(id) as (select generate_series(1,10))
  select id, case when id % 2 = 1 then 'black'
   else 'white' end from x;
```

| set  default_transaction_isolation = 'serializable';         | set  default_transaction_isolation = 'serializable';         |
| :----------------------------------------------------------- | :----------------------------------------------------------- |
| begin;     <br />update dots set color = 'black'      where color = 'white'; |                                                              |
|                                                              | begin;    <br /> update dots set color = 'white'      where color = 'black'; |
| commit                                                       |                                                              |
|                                                              | commit                                                       |
| *(pg SSI先提交者成功提交，后提交者抛出报错 )*                | ERROR: could not serialize access due to  read/write dependencies among transactions  DETAIL: Reason code: Canceled on identification as  a pivot, during commit attempt.  HINT: The transaction might succeed if retried. |

（已提交读和可重复读级别，均不会出现报错，黑白球颜色交换，不再展示测试结果）

严格两阶段提交（S2PL）也可以实现可串行化，但S2PL需要很重的读写锁，直到事务提交为止。S2PL会极大的影响并发性能，而且用户一般不会接受读写互相阻塞的情况，所以pg没有采用S2PL。

SSI是可序列化的另一种方案。它仍然会使用快照隔离，只是会额外检查是否有异常现象发生。

两个方案的处理方式也不同：在异常现象发生时，S2PL会阻塞事务，而SSI会中断事务以打破循环。

人们没有使用可串行化，原因之一有可串行化会降低数据库性能。这其实可以理解，因为有”检查异常现象“的SSI必定比什么检查都没有的弱隔离级别性能低。不过经过SSI实现理论的发展和pg本身对只读事务的优化，SSI的性能已于SI相差无几。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/193a5f143674d188e9aaea9d56d71133.png)


可序列化能极大的简化应用对一致性的担心，而pg9.1已实现ssi并加以优化。期待应用有一天真的能使用可串行化隔离级别。

## 事务隔离级别参考 

<https://wiki.postgresql.org/wiki/SSI>

<https://en.wikipedia.org/wiki/Serializability>

<https://en.wikipedia.org/wiki/Snapshot_isolation>

<https://justinjaffray.com/what-does-write-skew-look-like/>

<http://www.bailis.org/blog/when-is-acid-acid-rarely/>

<https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf> 95年SI隔离级别以及对SQL92标准的批评

<https://www.cse.iitb.ac.in/infolab/Data/Courses/CS632/2009/Papers/p492-fekete.pdf> SSI论文

<https://drkp.net/papers/ssi-vldb12.pdf> postgresql实现SSI

<https://ristret.com/s/f643zk/history_transaction_histories> 事务隔离级别的历史



# 事务的处理

## 事务块

从事务形态划分可分为隐式事务和显示事务。隐式事务是一个独立的SQL语句，执行完成后默认提交。显示事务需要显示声明一个事务，多个sql语句组合到一起称为一个事务块。

事务块通过`begin`，`begin transaction`，`start transaction`开始

通过`COMMIT`,`END`或`ABORT`,`ROLLBACK`结束，其中`COMMIT=END`，`ABORT=ROLLBACK`

```sql
BEGIN;
select * from lzl1 limit 1;
update lzl1 set a=2;
END;
```

如果事务块执行过程中一旦有报错，由于事务必须满足原子性，事务只能回退

```sql
lzldb=# begin;
BEGIN
lzldb=*# select * from lzl2;
ERROR: relation "lzl2" does not exist
LINE 1: select * from lzl2;
^
lzldb=!# commit;
ROLLBACK
```



## 事务处理函数

事务处理函数分为3个层次：顶层事务函数、中层事务函数、底层事务函数
顶层事务函数，处理事务块命令，比如`BEGIN`, `COMMIT`, `ROLLBACK`, `SAVEPOINT`等，有如下函数

| BeginTransactionBlock     | 启动事务块         |
| ------------------------- | ------------------ |
| EndTransactionBlock       | 结束事务块         |
| UserAbortTransactionBlock | 用户显示结束事务块 |
| DefineSavepoint           | 生成保存点         |
| RollbackToSavepoint       | 回滚到某保存点     |
| ReleaseSavepoint          | 释放保存点         |

中层事务函数，每个sql在执行前后都会调用中层事务函数，包括检测到异常后，有如下函数

| StartTransactionCommand  | 启动事务命令                   |
| ------------------------ | ------------------------------ |
| CommitTransactionCommand | 完成事务命令，注意不是提交命令 |
| AbortCurrentTransaction  | 退出当前事务                   |

底层事务函数，真正的事务处理函数，负责维护事务状态、事务资源分配和回收等，有如下函数

| StartTransaction      | 启动事务        |
| --------------------- | --------------- |
| CommitTransaction     | 提交事务        |
| AbortTransaction      | 回滚/中断事务   |
| CleanupTransaction    | 清理事务        |
| StartSubTransaction   | 启动子事务      |
| CommitSubTransaction  | 提交子事务      |
| AbortSubTransaction   | 回滚/中断子事务 |
| CleanupSubTransaction | 清理子事务      |

其实这上面几个函数还是比较好分辨的。抛开几个特殊的函数（上层相关`savepoint`，中层`abort`函数），其实上、中、下三层事务层分成了：*Block（事务块函数），*Command（command函数），*Transaction（真正的事务处理函数）。然后把`savepoint`子事务当做事务块函数（后面会介绍，子事务可以在事务块中回退，所以这里把子事务放在事务块一级理所当然），把`abort`命令当做command级函数就可以了。

 ## 事务块状态

上层函数和中层函数同时控制事务块状态，底层函数控制事务状态

事务块状态和事务状态均在`src/backend/access/transam/xact.c`

```c
typedef enum TBlockState
{
/* 不在事务块中的状态 */
TBLOCK_DEFAULT,                /* 空闲状态，事务开始或结束后都处于此状态 */
TBLOCK_STARTED,                /* 刚开始进入事务块时的状态，由TBLOCK_DEFAULT转换到此状态，此状态存在时间较短 */
 
/* 事务块状态 */
TBLOCK_BEGIN,                /* 启动事务块，此时才启动数据块，进入数据块级状态 */
TBLOCK_INPROGRESS,            /* 活跃的事务，BEGIN以后事务块一直处于此状态，直到事务结束 */
TBLOCK_IMPLICIT_INPROGRESS, /* 隐式BEGIN的活跃事务 */
TBLOCK_PARALLEL_INPROGRESS, /* 并行执行的活跃事务 */
TBLOCK_END,                    /* 收到COMMIT命令 */
TBLOCK_ABORT,                /* 事务失败，等待ROLLBACK */
TBLOCK_ABORT_END,            /* 事务失败，收到ROLLBACK */
TBLOCK_ABORT_PENDING,        /* 活跃事务，收到ROLLBACK */
TBLOCK_PREPARE,                /* 活跃事务，收到PREPARE（显式2PC） */

/* 子事务状态（仍然是事务块级状态） */
TBLOCK_SUBBEGIN,            /* 启动子事务 */
TBLOCK_SUBINPROGRESS,        /* 活跃的子事务 */
TBLOCK_SUBRELEASE,            /* 收到RELEASE（释放保存点） */
TBLOCK_SUBCOMMIT,            /* 当子事务还在运行的时候（SUBINPROGRESS），收到父事务COMMIT */
TBLOCK_SUBABORT,            /* 失败子事务，等待rollback命令 */
TBLOCK_SUBABORT_END,        /* 失败子事务，收到rollback命令 */
TBLOCK_SUBABORT_PENDING,    /* 活跃子事务，收到rollback命令 */
TBLOCK_SUBRESTART,            /* 活跃子事务，收到rollback to命令 */
TBLOCK_SUBABORT_RESTART        /* 失败子事务，收到ROLLBACK TO命令 */
} TBlockState;
```

大部分状态是显而易见的。需要补充说明的是事务回滚（rollback）和事务失败(ABORT)两者后续行为是相似的，他们都要把清理事务资源和退出当前事务。但是pg把他们分为了两种行为，设置了两种状态`TBLOCK_ABORT`，`TBLOCK_ABORT_END`（子事务亦然），为什么会这样呢？

在`src/backend/access/transam/README`中对此现象作了详细的说明：

> | 场景 1                                   | 场景 2                                    |
> | ---------------------------------------- | ----------------------------------------- |
> | 1) 用户输入 `BEGIN`                      | 1) 用户输入 `BEGIN`                       |
> | 2) 用户执行某些命令                      | 2) 用户执行某些命令                       |
> | 3) 用户不喜欢她所看到的东西，输入`ABORT` | 3) 事务系统因为某些原因中断（语法错误等） |
>
> 场景1中，我们想中断事务并把事务回退到default状态 。
>
> 场景2中，可能后续还会有更多的命令，这些命令也是当前事务块的一部分，我们不得不忽略这些命令，直到我们看见`COMMIT` or `ROLLBACK`。
>
> `AbortCurrentTransaction`处理事务内部中断，`UserAbortTransactionBlock`处理事务用户中断。两个函数都依赖`AbortTransaction`来处理所有真正的工作。唯一区别在于`AbortTransaction`工作结束后我们进入了什么状态:
>
> \* AbortCurrentTransaction leaves us in TBLOCK_ABORT
>
> \* UserAbortTransactionBlock leaves us in TBLOCK_ABORT_END（*原文如此，不过用户输入结束应该进入TBLOCK_ABORT_PENDING状态*） 

> 底层事务中断处理分为两个阶段：
>
> \* 一旦我们意识到事务失败，就会执行`AbortTransaction`。这应该释放所有共享资源（锁等），以防不必要的增加其他backends的延迟。
>
> \* 当我最终看到用户`COMMIT`或者`ROLLBACK`时，执行`CleanupTransaction`；该函数将清理资源并让我们完全跳出事务。特别是，在此之前我们不能破坏`TopTransactionContext`。

## 事务状态

事务状态一目了然(注意跟事务块状态是不同的)

```c
typedef enum TransState
{
TRANS_DEFAULT,                /* 空闲 */
TRANS_START,                /* 事务启动 */
TRANS_INPROGRESS,            /* 活跃的事务 */
TRANS_COMMIT,                /* 事务提交 */
TRANS_ABORT,                /* 退出事务 */
TRANS_PREPARE                /* prepare事务（2pc） */
} TransState;
```

## 事务状态流转

事务块中的一个个命令，调用事务函数，事务函数转变事务、事务块的状态
以一个最简单的事务块举例（参考readme）

```sql
1)BEGIN
2)SELECT * FROM foo
3)INSERT INTO foo VALUES (...)
4)COMMIT
```

命令调用关系：
 	  
 	  	/  StartTransactionCommand;    --中层事务命令启动函数
	   /    StartTransaction;        --底层真正处理启动事务函数
	1)<  ProcessUtility;         --ProcessUtility处理BEGIN命
	   \    BeginTransactionBlock;     --顶层事务块启动函数
  	    \ CommitTransactionCommand;    --中层完成命令函数  
  			 
        /  StartTransactionCommand;    --中层事务命令启动函数
    2) /  PortalRunSelect;        --SELECT语句执行
       \  CommitTransactionCommand;    --中层完成命令函数
        \    CommandCounterIncrement;    --中层完成命令函数
        
        /  StartTransactionCommand;    --中层事务命令启动函数
    3) /  ProcessQuery;          --INSERT语句执行
       \  CommitTransactionCommand;    --中层完成命令函数
        \    CommandCounterIncrement;    --命令计数器计数+1

  	      / StartTransactionCommand;    --中层事务命令启动函数
 	     /  ProcessUtility;         --ProcessUtility处理commit命令
 	 4) <    EndTransactionBlock;      --调用顶层事务块结束函数
 	     \  CommitTransactionCommand;    --中层完成命令函数
	      \   CommitTransaction;       --底层真正处理提交事务函数

- 事务块的每一个命令，都会以中层函数`StartTransactionCommand`和`CommitTransactionCommand`开始和结束
- 在以上两个中层函数中间，可以看成真正执行的命令处理

2)SELECT和3)INSERT事务块状态都是`TBLOCK_INPROGRESS`，`BEGIN`和`COMMIT`状态块转换流程如下：

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/fc91705f57a6b932520d4a3280a648f2.png)


## 事务函数参考
《postgresql技术内幕》
src/backend/access/transam/README
