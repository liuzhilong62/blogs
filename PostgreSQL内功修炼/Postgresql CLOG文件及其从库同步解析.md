

放眼所有关系型数据库，PostgreSQL的clog也是很特殊的日志。CLOG的存在跟PG的MVCC机制不无关系。一些事务ID、clog的基础知识本篇不会涉及，感谢兴趣的可参考[clog和hintbits](https://blog.csdn.net/qq_40687433/article/details/130782857?ops_request_misc=%257B%2522request%255Fid%2522%253A%2522172343394916800211586382%2522%252C%2522scm%2522%253A%252220140713.130102334.pc%255Fblog.%2522%257D&request_id=172343394916800211586382&biz_id=0&utm_medium=distribute.pc_search_result.none-task-blog-2~blog~first_rank_ecpm_v1~rank_v31_ecpm-1-130782857-null-null.nonecase&utm_term=clog&spm=1018.2226.3001.4450)。本篇主要讲clog文件的构成、手工定位事务状态、clog的wal日志同步机制，以进一步理解PostgreSQL的clog。

# clog segment
## clog目录
为了区别普通日志，PG 10对clog和wal的目录进行了重命名[^3]：
|pg9.6|pg10|
|--|--|
|pg_clog|pg_xact|
|pg_xlog|pg_wal|

别搞错了，我也有段时间被pg_xlog和pg_xact给困扰···

## clog segment name
clog也是由slru管理，clog文件命名也在`slru.c`中
```c
#define SlruFileName(ctl, path, seg) \
	snprintf(path, MAXPGPATH, "%s/%04X", (ctl)->Dir, seg)
```
`%04X`表示十六进制（`X`），宽度为4、不足前面补0（`04`）。
clog文件名示例如下：
```shell
[pg_xact]$ ll
-rw------- 1 postgres postgres 262144 Aug 15 16:29 03C0
-rw------- 1 postgres postgres 262144 Aug 19 23:04 03C1
...
```

# TransactionID与clog位置的转换

clog只存储事务ID的状态，不存事务ID本身。通过TransactionID本身是可以直接定位到clog文件及文件中的位置的。在此之前我们需要了解一些基础知识。


## CLOG保存的事务状态
事务的状态只有4种：
```c
typedef int XidStatus;

#define TRANSACTION_STATUS_IN_PROGRESS		0x00
#define TRANSACTION_STATUS_COMMITTED		0x01
#define TRANSACTION_STATUS_ABORTED		0x02
#define TRANSACTION_STATUS_SUB_COMMITTED	0x03
```
事务状态只有进行中、已提交、回滚、子事务已提交。注意事务id没有“未开始”这个状态，只要数据库中分配了事务ID，那么这个事务肯定是已经开始了。
相反，库中还没有分配的事务ID（实际是少许，参考下面的extend clog章节），在clog中对应in_progress状态。
4个事务状态实际上2个bit位即可存储。那么1个字节（8 bits）可存储4个事务状态，1个页（8k）能放8KB*4=32768个事务状态。这些都在源码中定义了：
```c
 * Defines for CLOG page sizes.  A page is the same BLCKSZ as is used
 * everywhere else in Postgres.
//clog页大小=BLCKSZ=8k（默认） 
#define CLOG_BITS_PER_XACT	2  								 //一个事务状态占2个bit
#define CLOG_XACTS_PER_BYTE 4  								 //1个字节可存放4个事务状态
#define CLOG_XACTS_PER_PAGE (BLCKSZ * CLOG_XACTS_PER_BYTE)   //1个页可存放32768个事务状态，8KB*4=32768
#define CLOG_XACT_BITMASK ((1 << CLOG_BITS_PER_XACT) - 1)    //事务状态的bitmask位=((1<<2)-1)=3，用二进制表达为11
```
```c
#define SLRU_PAGES_PER_SEGMENT	32  //1个segment有32个pages
```
汇总：
 - 1个clog segment有32个page
 - 1个clog page有8k（一般）
 - 1个bytes有4个事务状态
 - 1个事务状态占2 bit

## clog segment/page/bytes的转换
事务id对应在哪个CLOG段不太好找，它藏在注释里：
```c
 * Note: because TransactionIds are 32 bits and wrap around at 0xFFFFFFFF,
 * CLOG page numbering also wraps around at 0xFFFFFFFF/CLOG_XACTS_PER_PAGE,
 * and CLOG segment numbering at
 * 0xFFFFFFFF/CLOG_XACTS_PER_PAGE/SLRU_PAGES_PER_SEGMENT
//segment number=xid/CLOG_XACTS_PER_PAGE/SLRU_PAGES_PER_SEGMENT=xid/32768/32            //事务id对应在哪个CLOG段，xid/32768/32,需要转成16进制
```
事务id对应对应到page、byte等比较清晰[^2]：
```c
#define TransactionIdToPage(xid)	((xid) / (TransactionId) CLOG_XACTS_PER_PAGE)       //事务id对应在哪个CLOG page,xid/32768
#define TransactionIdToPgIndex(xid) ((xid) % (TransactionId) CLOG_XACTS_PER_PAGE)       //事务id对应在上面page中的偏移量,xid%32768
#define TransactionIdToByte(xid)	(TransactionIdToPgIndex(xid) / CLOG_XACTS_PER_BYTE) //事务id对应在page中的第几个字节,(xid%32768)/4
#define TransactionIdToBIndex(xid)	((xid) % (TransactionId) CLOG_XACTS_PER_BYTE)		//事务id对应在上面字节中的哪个bit index（注意是bit index不是bit本身）,xid%4
```
一般来说（8k的BLCKSZ），1个CLOG段有32个页面；1个CLOG段有32\*8k字节，**即CLOG文件大小固定256K**；1个CLOG段可存放4\*32\*8k个事务状态。
```shell
[pg_xact]$ ll  # 256k的clog segment
-rw------- 1 postgres postgres 262144 Aug 15 16:29 03C0
-rw------- 1 postgres postgres 262144 Aug 19 23:04 03C1
...
```


## clog bit位的转换
设置clog bit和获取clog bit的函数（对应`TransactionIdSetStatusBit`和`TransactionIdGetStatus`）都有以下代码以获取事务id对应到clog中的哪两位bit：
```c
	int			bshift = TransactionIdToBIndex(xid) * CLOG_BITS_PER_XACT;
	char	   *byteptr;
...
	byteptr = XactCtl->shared->page_buffer[slotno] + byteno;
	curval = (*byteptr >> bshift) & CLOG_XACT_BITMASK;
```
`bshift`表示右移的位置，其中`TransactionIdToBIndex=xid%4`，`CLOG_BITS_PER_XACT=2`，`CLOG_XACT_BITMASK=3（二进制为11）`。
clog bit获取的关键代码`curval = (*byteptr >> bshift) & CLOG_XACT_BITMASK`分两段来看：
 - `*byteptr >> bshift`表示指针右移0、2、4、6位
 - `& CLOG_XACT_BITMASK`其实就是右移后取后两位（00&11=00、01&11=01、10&11=10、11&11=11）

so，计算在一个byte中事务id状态的位置：
 - xid%4=0时，取第7、8位
 - xid%4=1时，取第5、6位
 - xid%4=2时，取第3、4位
 - xid%4=3时，取第1、2位

注意，事务id状态在byte中的bit位是反着取的，不是正着顺序取。byte、page位这些是顺序递增的取的。



## 手动计算事务id在clog文件中的位置
如果我们要手工通过`hexdump`定位CLOG中的事务，需要计算出三个元素<**CLOG的段号、段中的偏移量in bytes、byte上的偏移量in bitindex**>。（这里参考了《PostgreSQL数据库内核分析》的说法，不过有一些区别[^1]）

计算之前还需要了解：
 - clog段文件号是16进制的
 - hexdump是16进制的，每行存放16个字节，即每行存放`16*CLOG_XACTS_PER_BYTE=16*4=64`个事务状态
 - `hexdump -s xxx`是以byte为单位

下面sql可以计算transactionid对应clog中的位置：
```sql
--CLOG的段号
--%4294967296代表事务id回卷，/(8192*4*32)代表一个段文件能包含的最大事务数，to_hex转为文件名的16进制，lpad左补全4位
select lpad(upper(to_hex(txid_current()%4294967296/(8192*4*32))),4,'0') as clog_segmentno;

--段中的偏移量in bytes 
--%4294967296代表事务id回卷，%(8192*32*4)取余下的事务id，/4计算成byte单位
select txid_current()%4294967296%(8192*32*4)/4 as in_clog_offset_bytes;

--byte上的偏移量in bitindex
--%4294967296代表事务id回卷，%4取byte中的bitindex
select txid_current()%4294967296%4 as in_byte_offset_bitindex;


--或者一条sql
select lpad(upper(to_hex(txid_current()%4294967296/(8192*4*32))),4,'0') as clog_segmentno,txid_current()%4294967296%(8192*32*4)/4 as in_clog_offset_bytes,txid_current()%4294967296%4 as in_byte_offset_bitindex;
```
实操模拟计算一个事务id在clog中的状态
```sql
begin;
 select lpad(upper(to_hex(txid_current()%4294967296/(8192*4*32))),4,'0') as clog_segmentno,txid_current()%4294967296%(8192*32*4)/4 as in_clog_offset_bytes,txid_current()%4294967296%4 as in_byte_offset_bitindex;
 clog_segmentno | in_clog_offset_bytes | in_byte_offset_bitindex 
----------------+----------------------+-------------------------
 0002           |                63196 |                       3
rollback;
checkpoint; 
```
rollback把事务回滚，主要是方便观察，因为大部分事务都是提交的。
checkpoint是未来保证clog page刷脏，不然clog page在clog buffer中还没写到clog segment文件。

```sql
cd pg_xact/
 hexdump -C 0002 -s 63196 -n 1 -v
0000f6dc  95                                                |.|
0000f6dd

--十六进制转二进制
> select 'x96'::bit(8);
   bit    
----------
 10010110
```
 xid%4=3时，取第1、2位，所以这个回滚的事务的bit位取10，10代表`TRANSACTION_STATUS_ABORTED`


## 为什么clog中一般有很多55和U？
一般的业务事务库clog文件，直接hexdump的话结果就像下面这样：
```c
hexdump -C 0001 -v|head -10
00000000  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000010  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000020  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000030  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000040  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000050  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000060  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000070  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000080  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
00000090  55 55 55 55 55 55 55 55  55 55 55 55 55 55 55 55  |UUUUUUUUUUUUUUUU|
```
因为事务提交的状态=01=`TRANSACTION_STATUS_COMMITTED`，一个byte中4个连续的事务都是提交的，那么就是01010101。
 - 二进制为01010101，十六进制为55
 - 十六进制55在ASCII中为U，所以在肉眼看CLOG文件一般可以看到很多U
 - 偶尔有些数组不是55或U，因为生产环境中偶尔有些事务没有完成或者使用了子事务。子事务在clog中的提交状态是x03。



# shared clog  buffer
clog shared buffers的个数很容易理解：
```c
/*
 * Number of shared CLOG buffers.
 *
 * On larger multi-processor systems, it is possible to have many CLOG page
 * requests in flight at one time which could lead to disk access for CLOG
 * page if the required page is not found in memory.  Testing revealed that we
 * can get the best performance by having 128 CLOG buffers, more than that it
 * doesn't improve performance.
 *
 * Unconditionally keeping the number of CLOG buffers to 128 did not seem like
 * a good idea, because it would increase the minimum amount of shared memory
 * required to start, which could be a problem for people running very small
 * configurations.  The following formula seems to represent a reasonable
 * compromise: people with very low values for shared_buffers will get fewer
 * CLOG buffers as well, and everyone else will get 128.
 */
Size
CLOGShmemBuffers(void)
{
	return Min(128, Max(4, NBuffers / 512));
}
```
翻译：经过测试128个clog buffers性能是最好的，再多也提升不了性能。但是由于有些库的配置实在是太小了，128个clog buffers显得有点大，所以取shared buffers个数的1/512。也就是说：
clog buffers的个数=1/512 shared buffer，最小是4，最大是128。注意这里都是buffer的个数，不是大小！
那么单个buffer有多大呢？
clog buffer是slru管理的，slru每个page都是8k：
>A page is the same BLCKSZ as is used everywhere

我们可以从clog slru初始化的角度窥探shared clog buffer的大小：
```c
/*
 * Initialization of shared memory for CLOG
 */
Size
CLOGShmemSize(void)
{
	return SimpleLruShmemSize(CLOGShmemBuffers(), CLOG_LSNS_PER_PAGE);
}
```
传入的`CLOGShmemBuffers()`是4~128，传入的`CLOG_LSNS_PER_PAGE`=1024 byte（8k page时）。
`SimpleLruShmemSize`初始化slru shmem：
```c
Size
SimpleLruShmemSize(int nslots, int nlsns)
{
	Size		sz;

	/* we assume nslots isn't so large as to risk overflow */
	sz = MAXALIGN(sizeof(SlruSharedData));
	sz += MAXALIGN(nslots * sizeof(char *));	/* page_buffer[] */
	sz += MAXALIGN(nslots * sizeof(SlruPageStatus));	/* page_status[] */
	sz += MAXALIGN(nslots * sizeof(bool));	/* page_dirty[] */
	sz += MAXALIGN(nslots * sizeof(int));	/* page_number[] */
	sz += MAXALIGN(nslots * sizeof(int));	/* page_lru_count[] */
	sz += MAXALIGN(nslots * sizeof(LWLockPadded));	/* buffer_locks[] */

	if (nlsns > 0)
		sz += MAXALIGN(nslots * nlsns * sizeof(XLogRecPtr));	/* group_lsn[] */

	return BUFFERALIGN(sz) + BLCKSZ * nslots;
}
```
slrus用一些数组保存slru的元数据和控制信息，sz大小都是`数据类型*buffer个数`，这些大致估算都不是特别不大。主要初始化的内存还是`BLCKSZ * nslots`，也就是`8k * (4~128)=(32k~1M)`大小。所以可以*粗略的*认为，shared clog buffer的大小为1M左右。  


# CLOG的wal：类型、写入和redo
写clog的时候会写clog的wal日志吗？如果写了那不是clog丢了也可以通过wal日志再次应用就应该找回了事务状态？我们带着问题来看clog写wal和redo的源码。
## extend clog
`ZeroCLOGPage`会写wal，`ZeroCLOGPage(pageno, true)`实际上*仅*由`ExtendCLOG`调用：
```c
/*
 * Make sure that CLOG has room for a newly-allocated XID.
 *
 * NB: this is called while holding XidGenLock.  We want it to be very fast
 * most of the time; even when it's not so fast, no actual I/O need happen
 * unless we're forced to write out a dirty clog or xlog page to make room
 * in shared memory.
 */
void
ExtendCLOG(TransactionId newestXact)
{
	int			pageno;

	/*
	 * No work except at first XID of a page.  But beware: just after
	 * wraparound, the first XID of page zero is FirstNormalTransactionId.
	 */
	if (TransactionIdToPgIndex(newestXact) != 0 &&
		!TransactionIdEquals(newestXact, FirstNormalTransactionId))
		return;

	pageno = TransactionIdToPage(newestXact); //由TransactionId换算的clog page号

	LWLockAcquire(XactSLRULock, LW_EXCLUSIVE);

	/* Zero the page and make an XLOG entry about it */
	ZeroCLOGPage(pageno, true);

	LWLockRelease(XactSLRULock);
}
```
`ZeroCLOGPage`主要调用`WriteZeroPageXlogRec`：
```c

/*
 * Write a ZEROPAGE xlog record
 */
static void
WriteZeroPageXlogRec(int pageno)
{
	XLogBeginInsert();
	XLogRegisterData((char *) (&pageno), sizeof(int));
	(void) XLogInsert(RM_CLOG_ID, CLOG_ZEROPAGE);
}
```
`WriteZeroPageXlogRec`就是在写wal record了，写入的类型是“RM_CLOG_ID, CLOG_ZEROPAGE”。
通过waldump可以查看到CLOG_ZEROPAGE，它的占比一般都是非常少的：
```sql
pg_waldump -z 000000010000056B00000018 --stat=record
Type                                           N      (%)          Record size      (%)             FPI size      (%)        Combined size      (%)
----                                           -      ---          -----------      ---             --------      ---        -------------      ---
...
CLOG/ZEROPAGE                                  1 (  0.00)                   30 (  0.00)                    0 (  0.00)                   30 (  0.00)
...
```
extend clog page时都是以page为单位，实际上在clog segment的末尾可以很容易看到00
```
hexdump 03C2
0000000 5555 5555 5555 5555 5555 5555 5555 5555
*
001bb30 5555 5555 0055 0000 0000 0000 0000 0000
001bb40 0000 0000 0000 0000 0000 0000 0000 0000  
* ##clog文件后面的都是0
001c000
```

## truncate clog

除了extend clog外，还有truncate clog，truncate clog会在vacuum期间被调用，调用时会写truncate clog的wal record，并将wal record flush到磁盘  
```c
/*
 * Remove all CLOG segments before the one holding the passed transaction ID
 *
 * Before removing any CLOG data, we must flush XLOG to disk, to ensure
 * that any recently-emitted FREEZE_PAGE records have reached disk; otherwise
 * a crash and restart might leave us with some unfrozen tuples referencing
 * removed CLOG data.  We choose to emit a special TRUNCATE XLOG record too.
 * Replaying the deletion from XLOG is not critical, since the files could
 * just as well be removed later, but doing so prevents a long-running hot
 * standby server from acquiring an unreasonably bloated CLOG directory.
 *
 * Since CLOG segments hold a large number of transactions, the opportunity to
 * actually remove a segment is fairly rare, and so it seems best not to do
 * the XLOG flush unless we have confirmed that there is a removable segment.
 */
void
TruncateCLOG(TransactionId oldestXact, Oid oldestxid_datoid)
{
	int			cutoffPage;

	/*
	 * The cutoff point is the start of the segment containing oldestXact. We
	 * pass the *page* containing oldestXact to SimpleLruTruncate.
	 */
	//写入wal的是clog的位置，clog位置是oldestXact转换出来的clog page号
	cutoffPage = TransactionIdToPage(oldestXact); 

.....
	/*
	 * Write XLOG record and flush XLOG to disk. We record the oldest xid
	 * we're keeping information about here so we can ensure that it's always
	 * ahead of clog truncation in case we crash, and so a standby finds out
	 * the new valid xid before the next checkpoint.
	 */
	// WriteTruncateXlogRec会写对应的wal record并将其写到磁盘上
	WriteTruncateXlogRec(cutoffPage, oldestXact, oldestxid_datoid);
	
	//wal写完后，才真正执行truncate clog段
	/* Now we can remove the old CLOG segment(s) */
	SimpleLruTruncate(XactCtl, cutoffPage);
}
```
`WriteTruncateXlogRec`就是写`RMGR`为`RM_CLOG_ID`，`info`为 `CLOG_TRUNCAT`的wal record：
```c
/*
 * Write a TRUNCATE xlog record
 *
 * We must flush the xlog record to disk before returning --- see notes
 * in TruncateCLOG().
 */
static void
WriteTruncateXlogRec(int pageno, TransactionId oldestXact, Oid oldestXactDb)
{
	XLogRecPtr	recptr;
	xl_clog_truncate xlrec;

	xlrec.pageno = pageno;
	xlrec.oldestXact = oldestXact;
	xlrec.oldestXactDb = oldestXactDb;

	XLogBeginInsert();
	XLogRegisterData((char *) (&xlrec), sizeof(xl_clog_truncate));
	recptr = XLogInsert(RM_CLOG_ID, CLOG_TRUNCATE);
	XLogFlush(recptr);
}
```

当制造了clog wal record后，还需要redo恢复的routine：
```c
/*
 * CLOG resource manager's routines
 */
void
clog_redo(XLogReaderState *record)
{
...
	//redo info类型是CLOG_ZEROPAGE时，将读取出来的redo信息放在内存，然后写到CLOG page文件中
	if (info == CLOG_ZEROPAGE)
	{
		int			pageno;
		int			slotno;

		memcpy(&pageno, XLogRecGetData(record), sizeof(int));

		LWLockAcquire(XactSLRULock, LW_EXCLUSIVE);

		slotno = ZeroCLOGPage(pageno, false);
		SimpleLruWritePage(XactCtl, slotno); 
		Assert(!XactCtl->shared->page_dirty[slotno]);

		LWLockRelease(XactSLRULock);
	}
	//redo info类型是CLOG_TRUNCATE时，将读取出来的redo信息放在内存中，确认page是可删除的（如果不可用需要write page），然后truncate segment
	else if (info == CLOG_TRUNCATE)
	{
		xl_clog_truncate xlrec;

		memcpy(&xlrec, XLogRecGetData(record), sizeof(xl_clog_truncate));

		/*
		 * During XLOG replay, latest_page_number isn't set up yet; insert a
		 * suitable value to bypass the sanity test in SimpleLruTruncate.
		 */
		XactCtl->shared->latest_page_number = xlrec.pageno;

		AdvanceOldestClogXid(xlrec.oldestXact);

		SimpleLruTruncate(XactCtl, xlrec.pageno);
	}
	else
		elog(PANIC, "clog_redo: unknown op code %u", info);
}
```
clog redo routine所做的事：
 - redo info类型是`CLOG_ZEROPAGE`时，找到一个合适的slot（如果没有需要换出），根据读取出来的redo信息（实际上是clog page号）进行一些是否可写的判断，可以再讲page write到clog文件
 - redo info类型是`CLOG_TRUNCATE`时，根据读取出来的redo信息（实际上是clog page号），确认page是可删除的（如果不可用需要write page），然后truncate clog segment



## clog的同步小结
CLOG只有两种wal日志，两种都不包含事务状态信息，且仅仅是在extend clog page和truncate clog segment时触发，写入的wal record只是一个clog page编号。
CLOG的wal日志RMGR类型只有一种`RM_CLOG_ID`，这种类型只有两种信息：`CLOG_ZEROPAGE`、`CLOG_TRUNCATE`。
```c
/* XLOG stuff */
#define CLOG_ZEROPAGE 0x00
#define CLOG_TRUNCATE 0x10
```

clog wal同步总结：
**从库本质上没有在同步clog信息，只是同步了一些clog文件的扩容和删除信息**。

但是，从库的clog文件中明明是有状态信息的，从库明显也需要这部分信息以提供可见性检查。clog中的事务状态是怎么同步的呢？



# 事务id的wal：类型、写入和redo
rmgr=clog的wal不包含事务状态，难道从库不同步clog事务信息？并不是，wal日志中有事务ID的状态信息，clog也会被更新：
```sql
--回滚一个事务，提交一个事务
>  begin;
BEGIN
>  select txid_current();
 txid_current 
--------------
      1817254
(1 row)

>  rollback;
ROLLBACK
> begin;
BEGIN
>  select txid_current();
 txid_current 
--------------
      1817258
(1 row)

> commit;
COMMIT
> checkpoint;
CHECKPOINT
```
```sql
--pg_waldump查看日志中的事务ID状态
[datalzl/pg_wal]$ pg_waldump ../../pg_wal/000000010000007300000008|grep  -E "1817254|1817258"
rmgr: Transaction len (rec/tot):     34/    34, tx:    1817254, lsn: 73/400ED210, prev 73/400ED1E0, desc: ABORT 2024-08-01 14:41:26.017612 CST
rmgr: Transaction len (rec/tot):     46/    46, tx:    1817258, lsn: 73/400EEB08, prev 73/400EEAD8, desc: COMMIT 2024-08-01 14:41:37.042545 CST
pg_waldump: fatal: error in WAL record at 73/400F7C78: invalid record length at 73/400F7F88: wanted 24, got 0
```
在wal中有记录事务ID（1817254，1817258）的状态，并且分别记录为`ABORT`、`COMMIT` ；rmgr为`Transaction`。
事务ID状态在wal日志中，但是pg会写到从库的clog里吗？
很明显，我们需要找到这部分的redo信息。按照刚才的经验，`clog_redo`代表rmgr=clog的wal redo源码，那么源码搜索`_redo`应该能找到rmgr=transactionid的wal redo源码。搜搜，在`xact.c`中的找到函数`xact_redo`，其主要调用`xact_redo_commit`,`xact_redo_abort`，明显各自对应提交事务和回退事务的wal日志应用逻辑。
```c
void
xact_redo(XLogReaderState *record)
{
	uint8		info = XLogRecGetInfo(record) & XLOG_XACT_OPMASK;

	/* Backup blocks are not used in xact records */
	Assert(!XLogRecHasAnyBlockRefs(record));

	if (info == XLOG_XACT_COMMIT)
	{
	...
		xact_redo_commit(&parsed, XLogRecGetXid(record),
						 record->EndRecPtr, XLogRecGetOrigin(record));
	}
...
	else if (info == XLOG_XACT_ABORT)
	{
	...
		xact_redo_abort(&parsed, XLogRecGetXid(record));
	}
...
	}
	else
		elog(PANIC, "xact_redo: unknown op code %u", info);
}

```
以commit为例
```c
static void
xact_redo_commit(xl_xact_parsed_commit *parsed,
				 TransactionId xid,
				 XLogRecPtr lsn,
				 RepOriginId origin_id)
{
...

	if (standbyState == STANDBY_DISABLED)
	{
		/*
		 * Mark the transaction committed in pg_xact.
		 */
		TransactionIdCommitTree(xid, parsed->nsubxacts, parsed->subxacts);
	}
	else//standby逻辑
	{
	...
		/*
		 * Mark the transaction committed in pg_xact. We use async commit
		 * protocol during recovery to provide information on database
		 * consistency for when users try to set hint bits. It is important
		 * that we do not set hint bits until the minRecoveryPoint is past
		 * this commit record. This ensures that if we crash we don't see hint
		 * bits set on changes made by transactions that haven't yet
		 * recovered. It's unlikely but it's good to be safe.
		 */
		//在pg_xact中标记事务提交
		TransactionIdAsyncCommitTree(xid, parsed->nsubxacts, parsed->subxacts, lsn);

...
}
```
看着`TransactionIdAsyncCommitTree`就是我们要找的写clog的函数。

为了验证wal中事务commit信息的redo逻辑，下面给从库的startup进程打三个断点，然后在源库执行`begin;select txid_current();commit;`提交一个事务，看看从库的startup进程在做redo的时候是否命中我们想要看到的函数：

```c
(gdb) bt
#0  TransactionIdAsyncCommitTree (xid=xid@entry=1818665, nxids=0, xids=0x0, lsn=lsn@entry=495398394064) at transam.c:274
#1  0x000000000050c139 in xact_redo_commit (parsed=parsed@entry=0x7ffda52c0fc0, xid=1818665, lsn=495398394064, origin_id=<optimized out>) at xact.c:5805
#2  0x000000000050ffa3 in xact_redo (record=0x2b5ff2434038) at xact.c:5962
#3  0x0000000000519ea5 in StartupXLOG () at xlog.c:7411
#4  0x000000000072f301 in StartupProcessMain () at startup.c:204
#5  0x0000000000528701 in AuxiliaryProcessMain (argc=argc@entry=2, argv=argv@entry=0x7ffda52c6ef0) at bootstrap.c:450
#6  0x000000000072c459 in StartChildProcess (type=StartupProcess) at postmaster.c:5494
#7  0x000000000072ec44 in PostmasterMain (argc=argc@entry=3, argv=argv@entry=0x2b5ff242d1c0) at postmaster.c:1407
#8  0x000000000048931f in main (argc=3, argv=0x2b5ff242d1c0) at main.c:210
(gdb) info b
Num     Type           Disp Enb Address            What
1       breakpoint     keep y   0x000000000050c060 in xact_redo_commit at xact.c:5753
        breakpoint already hit 43 times
2       breakpoint     keep y   0x0000000000508190 in TransactionIdCommitTree at transam.c:262
3       breakpoint     keep y   0x00000000005081a0 in TransactionIdAsyncCommitTree at transam.c:274
        breakpoint already hit 1 time
```
可以命中断点`TransactionIdAsyncCommitTree `，并且`xid=1818665`，也就是刚才在源库提交的事务ID。说明刚才肉眼看的代码逻辑没有问题。
so，**standby库的clog事务ID状态由wal rmgr=Transaction来同步**

# 总结
 - clog只存储了事务ID的状态，没有存储事务ID本身
 - 可以通过事务ID手动定位到CLOG文件中的事务状态
 - rmgr=clog的wal只有扩展和清理clog文件，没有更新事务状态
 - rmgr=transaction的wal会更新clog的事务状态

# references
[^2]:  阎书利 PostgreSQL的CLOG解析 <https://www.modb.pro/db/606433>
[^1]: 《PostgreSQL数据库内核分析》第7章 p380-390
[^3]:  《快速掌握PostgreSQL版本新特性》p24


