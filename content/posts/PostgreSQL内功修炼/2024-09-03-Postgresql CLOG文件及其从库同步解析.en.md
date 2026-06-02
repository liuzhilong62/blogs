---
title: "PostgreSQL CLOG Files and Standby Synchronization Analysis"
date: 2024-09-03
categories: [PostgreSQL Internals]
description: "An in-depth analysis of PostgreSQL CLOG file structure and transaction status storage principles, including transaction ID location and standby synchronization mechanisms."
---



Among all relational databases, PostgreSQL's CLOG is a very special type of log. CLOG's existence is inseparable from PostgreSQL's MVCC mechanism. Some basic knowledge about transaction IDs and CLOG won't be covered in this article. If interested, please refer to [CLOG and Hint Bits](https://blog.csdn.net/qq_40687433/article/details/130782857?ops_request_misc=%257B%2522request%255Fid%2522%253A%2522172343394916800211586382%2522%252C%2522scm%2522%253A%252220140713.130102334.pc%255Fblog.%2522%257D&request_id=172343394916800211586382&biz_id=0&utm_medium=distribute.pc_search_result.none-task-blog-2~blog~first_rank_ecpm_v1~rank_v31_ecpm-1-130782857-null-null.nonecase&utm_term=clog&spm=1018.2226.3001.4450). This article focuses on the structure of CLOG files, manually locating transaction states, and the CLOG WAL log synchronization mechanism, to further understand PostgreSQL's CLOG.

## CLOG Segment
### CLOG Directory
To distinguish from regular logs, PostgreSQL 10 renamed the CLOG and WAL directories [^3]:
|pg9.6|pg10|
|--|--|
|pg_clog|pg_xact|
|pg_xlog|pg_wal|

Don't get confused — I was also troubled by pg_xlog and pg_xact for a while...

### CLOG Segment Name
CLOG is also managed by SLRU, and CLOG file naming is also in `slru.c`:
```c
#define SlruFileName(ctl, path, seg) \
	snprintf(path, MAXPGPATH, "%s/%04X", (ctl)->Dir, seg)
```
`%04X` means hexadecimal (`X`), width of 4, zero-padded on the left (`04`).
Example CLOG filenames:
```shell
[pg_xact]$ ll
-rw------- 1 postgres postgres 262144 Aug 15 16:29 03C0
-rw------- 1 postgres postgres 262144 Aug 19 23:04 03C1
...
```

## TransactionID and CLOG Location Conversion

CLOG only stores transaction ID status, not the transaction ID itself. Through the TransactionID itself, you can directly locate the CLOG file and the position within the file. Before that, we need to understand some fundamentals.


### Transaction States Stored in CLOG
There are only 4 transaction states:
```c
typedef int XidStatus;

#define TRANSACTION_STATUS_IN_PROGRESS		0x00
#define TRANSACTION_STATUS_COMMITTED		0x01
#define TRANSACTION_STATUS_ABORTED		0x02
#define TRANSACTION_STATUS_SUB_COMMITTED	0x03
```
Transaction states are only: in progress, committed, aborted, subtransaction committed. Note that transaction IDs don't have an "not started" state — as soon as a transaction ID is allocated in the database, that transaction has definitely already started.
Conversely, transaction IDs not yet allocated in the database (actually a few — see the extend CLOG section below) correspond to `in_progress` status in CLOG.
Four transaction states actually only need 2 bits to store. So 1 byte (8 bits) can store 4 transaction states, and 1 page (8k) can hold 8KB*4=32768 transaction states. These are all defined in the source code:
```c
 * Defines for CLOG page sizes.  A page is the same BLCKSZ as is used
 * everywhere else in Postgres.
// CLOG page size = BLCKSZ = 8k (default)
#define CLOG_BITS_PER_XACT	2  							 // One transaction state occupies 2 bits
#define CLOG_XACTS_PER_BYTE 4  							 // 1 byte can hold 4 transaction states
#define CLOG_XACTS_PER_PAGE (BLCKSZ * CLOG_XACTS_PER_BYTE)   // 1 page can hold 32768 transaction states, 8KB*4=32768
#define CLOG_XACT_BITMASK ((1 << CLOG_BITS_PER_XACT) - 1)    // Transaction status bitmask = ((1<<2)-1) = 3, expressed in binary as 11
```
```c
#define SLRU_PAGES_PER_SEGMENT	32  // 1 segment has 32 pages
```
Summary:
 - 1 CLOG segment has 32 pages
 - 1 CLOG page is 8k (typically)
 - 1 byte has 4 transaction states
 - 1 transaction state occupies 2 bits

### CLOG Segment/Page/Byte Conversion
Finding which CLOG segment a transaction ID corresponds to is not easy — it's hidden in the comments:
```c
 * Note: because TransactionIds are 32 bits and wrap around at 0xFFFFFFFF,
 * CLOG page numbering also wraps around at 0xFFFFFFFF/CLOG_XACTS_PER_PAGE,
 * and CLOG segment numbering at
 * 0xFFFFFFFF/CLOG_XACTS_PER_PAGE/SLRU_PAGES_PER_SEGMENT
// segment number = xid/CLOG_XACTS_PER_PAGE/SLRU_PAGES_PER_SEGMENT = xid/32768/32            // Which CLOG segment the transaction ID corresponds to, xid/32768/32, needs to be converted to hex
```
Mapping transaction ID to page, byte, etc. is clearer [^2]:
```c
#define TransactionIdToPage(xid)	((xid) / (TransactionId) CLOG_XACTS_PER_PAGE)       // Which CLOG page the transaction ID corresponds to, xid/32768
#define TransactionIdToPgIndex(xid) ((xid) % (TransactionId) CLOG_XACTS_PER_PAGE)       // The offset within the above page, xid%32768
#define TransactionIdToByte(xid)	(TransactionIdToPgIndex(xid) / CLOG_XACTS_PER_BYTE) // Which byte in the page the transaction ID corresponds to, (xid%32768)/4
#define TransactionIdToBIndex(xid)	((xid) % (TransactionId) CLOG_XACTS_PER_BYTE)		// Which bit index in the above byte (note: bit index, not the bit itself), xid%4
```
Generally (with 8k BLCKSZ), 1 CLOG segment has 32 pages; 1 CLOG segment has 32*8k bytes, **i.e., CLOG file size is fixed at 256K**; 1 CLOG segment can hold 4*32*8k transaction states.
```shell
[pg_xact]$ ll  # 256k CLOG segment
-rw------- 1 postgres postgres 262144 Aug 15 16:29 03C0
-rw------- 1 postgres postgres 262144 Aug 19 23:04 03C1
...
```


### CLOG Bit Conversion
The functions for setting CLOG bits and getting CLOG bits (corresponding to `TransactionIdSetStatusBit` and `TransactionIdGetStatus`) both have the following code to obtain which two bits in the CLOG the transaction ID corresponds to:
```c
	int			bshift = TransactionIdToBIndex(xid) * CLOG_BITS_PER_XACT;
	char	   *byteptr;
...
	byteptr = XactCtl->shared->page_buffer[slotno] + byteno;
	curval = (*byteptr >> bshift) & CLOG_XACT_BITMASK;
```
`bshift` represents the right-shift position, where `TransactionIdToBIndex=xid%4`, `CLOG_BITS_PER_XACT=2`, `CLOG_XACT_BITMASK=3 (binary: 11)`.
The key code for getting CLOG bits `curval = (*byteptr >> bshift) & CLOG_XACT_BITMASK` can be understood in two parts:
 - `*byteptr >> bshift` means right-shifting the pointer by 0, 2, 4, or 6 bits
 - `& CLOG_XACT_BITMASK` is simply taking the last two bits after the right shift (00&11=00, 01&11=01, 10&11=10, 11&11=11)

So, calculating the position of a transaction ID's state within a byte:
 - xid%4=0: takes bits 7 and 8
 - xid%4=1: takes bits 5 and 6
 - xid%4=2: takes bits 3 and 4
 - xid%4=3: takes bits 1 and 2

Note: the transaction ID state's bit positions within a byte are taken in reverse order, not sequentially forward. Byte and page positions are taken in sequential increasing order.



### Manually Calculating Transaction ID Position in CLOG File
If we want to manually locate a transaction in CLOG using `hexdump`, we need to calculate three elements: **<CLOG segment number, offset within segment in bytes, offset on byte in bit index>**. (This references the approach in "PostgreSQL Database Kernel Analysis" but with some differences [^1])

Before calculating, you also need to understand:
 - CLOG segment file numbers are in hexadecimal
 - hexdump is in hexadecimal, each line holds 16 bytes, i.e., each line holds `16*CLOG_XACTS_PER_BYTE=16*4=64` transaction states
 - `hexdump -s xxx` is in byte units

The following SQL can calculate the position of a transaction ID in CLOG:
```sql
-- CLOG segment number
-- %4294967296 represents transaction ID wraparound, /(8192*4*32) represents the maximum number of transactions a segment file can contain, to_hex converts to hex for filename, lpad left-pads to 4 digits
select lpad(upper(to_hex(txid_current()%4294967296/(8192*4*32))),4,'0') as clog_segmentno;

-- Offset within segment in bytes
-- %4294967296 represents transaction ID wraparound, %(8192*32*4) takes the remaining transaction IDs, /4 converts to byte units
select txid_current()%4294967296%(8192*32*4)/4 as in_clog_offset_bytes;

-- Offset on byte in bit index
-- %4294967296 represents transaction ID wraparound, %4 takes the bit index within the byte
select txid_current()%4294967296%4 as in_byte_offset_bitindex;


-- Or a single SQL
select lpad(upper(to_hex(txid_current()%4294967296/(8192*4*32))),4,'0') as clog_segmentno,txid_current()%4294967296%(8192*32*4)/4 as in_clog_offset_bytes,txid_current()%4294967296%4 as in_byte_offset_bitindex;
```
Practical simulation — computing a transaction ID's state in CLOG:
```sql
begin;
 select lpad(upper(to_hex(txid_current()%4294967296/(8192*4*32))),4,'0') as clog_segmentno,txid_current()%4294967296%(8192*32*4)/4 as in_clog_offset_bytes,txid_current()%4294967296%4 as in_byte_offset_bitindex;
 clog_segmentno | in_clog_offset_bytes | in_byte_offset_bitindex 
----------------+----------------------+-------------------------
 0002           |                63196 |                       3
rollback;
checkpoint; 
```
Rollback is used to roll back the transaction, mainly for easier observation, since most transactions are committed.
Checkpoint is to ensure the CLOG page is flushed — otherwise the CLOG page might still be in the CLOG buffer and not yet written to the CLOG segment file.

```sql
cd pg_xact/
 hexdump -C 0002 -s 63196 -n 1 -v
0000f6dc  95                                                |.|
0000f6dd

-- Convert hex to binary
> select 'x96'::bit(8);
   bit    
----------
 10010110
```
When xid%4=3, take bits 1 and 2. So the bit value for this rolled-back transaction is 10, where 10 represents `TRANSACTION_STATUS_ABORTED`.


### Why CLOG Usually Contains Many 55s and U's?
In a typical transactional database CLOG file, a direct hexdump looks like this:
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
Because the committed transaction state = 01 = `TRANSACTION_STATUS_COMMITTED`. When 4 consecutive transactions in a byte are all committed, it becomes 01010101.
 - Binary: 01010101, hex: 55
 - Hex 55 in ASCII is 'U', so when visually examining CLOG files you can generally see many U's
 - Occasionally some bytes are not 55 or U because in production environments some transactions occasionally haven't completed or use subtransactions. The committed state of subtransactions in CLOG is 0x03.



## Shared CLOG Buffer
The number of CLOG shared buffers is easy to understand:
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
Translation: Testing has shown that 128 CLOG buffers provide the best performance — more than that doesn't improve performance. However, because some database configurations are too small, 128 CLOG buffers seems a bit large, so it takes 1/512 of the shared_buffers count. In other words:
Number of CLOG buffers = 1/512 shared_buffer, minimum is 4, maximum is 128. Note: these are all buffer counts, not sizes!

How large is a single buffer?
CLOG buffer is managed by SLRU, and each SLRU page is 8k:
>A page is the same BLCKSZ as is used everywhere

We can glimpse the size of shared CLOG buffer from the perspective of CLOG SLRU initialization:
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
The passed `CLOGShmemBuffers()` is 4~128, and the passed `CLOG_LSNS_PER_PAGE` = 1024 bytes (with 8k pages).
`SimpleLruShmemSize` initializes SLRU shared memory:
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
SLRU uses some arrays to store SLRU metadata and control information. The sz size is all roughly `data type * buffer count`, and these are generally not very large. The main initialized memory is `BLCKSZ * nslots`, i.e., `8k * (4~128) = (32k~1M)`. So we can *roughly* estimate that the shared CLOG buffer size is around 1M.


## CLOG WAL: Types, Writing, and Redo
When writing CLOG, is CLOG WAL log also written? If so, wouldn't that mean lost CLOG could be restored by reapplying WAL logs to recover transaction states? Let's explore the CLOG WAL writing and redo source code with these questions in mind.

### Extend CLOG
`ZeroCLOGPage` writes WAL. `ZeroCLOGPage(pageno, true)` is actually *only* called by `ExtendCLOG`:
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

	pageno = TransactionIdToPage(newestXact); // CLOG page number converted from TransactionId

	LWLockAcquire(XactSLRULock, LW_EXCLUSIVE);

	/* Zero the page and make an XLOG entry about it */
	ZeroCLOGPage(pageno, true);

	LWLockRelease(XactSLRULock);
}
```
`ZeroCLOGPage` mainly calls `WriteZeroPageXlogRec`:
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
`WriteZeroPageXlogRec` is writing a WAL record, with type "RM_CLOG_ID, CLOG_ZEROPAGE".
Using waldump, you can view CLOG_ZEROPAGE. Its proportion is generally very small:
```sql
pg_waldump -z 000000010000056B00000018 --stat=record
Type                                           N      (%)          Record size      (%)             FPI size      (%)        Combined size      (%)
----                                           -      ---          -----------      ---             --------      ---        -------------      ---
...
CLOG/ZEROPAGE                                  1 (  0.00)                   30 (  0.00)                    0 (  0.00)                   30 (  0.00)
...
```
Extending CLOG page is always in page units. In fact, at the end of a CLOG segment you can easily see 00s:
```
hexdump 03C2
0000000 5555 5555 5555 5555 5555 5555 5555 5555
*
001bb30 5555 5555 0055 0000 0000 0000 0000 0000
001bb40 0000 0000 0000 0000 0000 0000 0000 0000  
* ## The end of the CLOG file is all zeros
001c000
```

### Truncate CLOG

Besides extending CLOG, there's also truncating CLOG. Truncate CLOG is called during vacuum. When called, it writes a truncate CLOG WAL record and flushes the WAL record to disk:
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
	// What's written to WAL is the CLOG position, which is the CLOG page number converted from oldestXact
	cutoffPage = TransactionIdToPage(oldestXact); 

.....
	/*
	 * Write XLOG record and flush XLOG to disk. We record the oldest xid
	 * we're keeping information about here so we can ensure that it's always
	 * ahead of clog truncation in case we crash, and so a standby finds out
	 * the new valid xid before the next checkpoint.
	 */
	// WriteTruncateXlogRec writes the corresponding WAL record and flushes it to disk
	WriteTruncateXlogRec(cutoffPage, oldestXact, oldestxid_datoid);
	
	// After WAL is written, actually execute the CLOG segment truncation
	/* Now we can remove the old CLOG segment(s) */
	SimpleLruTruncate(XactCtl, cutoffPage);
}
```
`WriteTruncateXlogRec` writes a WAL record with `RMGR` as `RM_CLOG_ID` and `info` as `CLOG_TRUNCATE`:
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

After generating CLOG WAL records, the redo recovery routine is also needed:
```c
/*
 * CLOG resource manager's routines
 */
void
clog_redo(XLogReaderState *record)
{
...
	// When redo info type is CLOG_ZEROPAGE, place the read redo information in memory, then write to the CLOG page file
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
	// When redo info type is CLOG_TRUNCATE, place the read redo information in memory, confirm the page is deletable (write page if not), then truncate the segment
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
What the CLOG redo routine does:
 - When redo info type is `CLOG_ZEROPAGE`: finds a suitable slot (evict if necessary), performs writability checks based on the read redo information (actually the CLOG page number), then writes the page to the CLOG file
 - When redo info type is `CLOG_TRUNCATE`: based on the read redo information (actually the CLOG page number), confirms the page is deletable (write page if not available), then truncates the CLOG segment


### CLOG Synchronization Summary
CLOG has only two types of WAL logs, neither containing transaction status information. They are only triggered when extending CLOG pages and truncating CLOG segments, and the written WAL record is just a CLOG page number.
CLOG's WAL log RMGR type has only one: `RM_CLOG_ID`. This type has only two info codes: `CLOG_ZEROPAGE`, `CLOG_TRUNCATE`.
```c
/* XLOG stuff */
#define CLOG_ZEROPAGE 0x00
#define CLOG_TRUNCATE 0x10
```

CLOG WAL synchronization summary:
**The standby database is essentially not synchronizing CLOG information — it's only synchronizing some CLOG file expansion and deletion information.**

However, the standby's CLOG file clearly does have status information, and the standby obviously needs this information for visibility checking. How is the transaction status in CLOG synchronized?


## Transaction ID WAL: Types, Writing, and Redo
The WAL for rmgr=CLOG doesn't contain transaction status. Does the standby not synchronize CLOG transaction information? No — WAL logs do contain transaction ID status information, and CLOG is also updated:
```sql
-- Roll back a transaction, commit a transaction
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
-- pg_waldump to view transaction ID status in logs
[datalzl/pg_wal]$ pg_waldump ../../pg_wal/000000010000007300000008|grep  -E "1817254|1817258"
rmgr: Transaction len (rec/tot):     34/    34, tx:    1817254, lsn: 73/400ED210, prev 73/400ED1E0, desc: ABORT 2024-08-01 14:41:26.017612 CST
rmgr: Transaction len (rec/tot):     46/    46, tx:    1817258, lsn: 73/400EEB08, prev 73/400EEAD8, desc: COMMIT 2024-08-01 14:41:37.042545 CST
pg_waldump: fatal: error in WAL record at 73/400F7C78: invalid record length at 73/400F7F88: wanted 24, got 0
```
The WAL records the status of transaction IDs (1817254, 1817258), recorded as `ABORT` and `COMMIT` respectively; rmgr is `Transaction`.
Transaction ID status is in WAL logs, but does PostgreSQL write it to the standby's CLOG?
Obviously, we need to find this redo information. Based on previous experience, `clog_redo` represents the WAL redo source code for rmgr=CLOG. Searching the source for `_redo` should find the WAL redo source code for rmgr=Transaction. Searching... in `xact.c` we find the function `xact_redo`, which mainly calls `xact_redo_commit` and `xact_redo_abort`, clearly corresponding to WAL log application logic for committed and rolled-back transactions respectively.
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
Taking commit as an example:
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
	else // standby logic
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
		// Mark transaction committed in pg_xact
		TransactionIdAsyncCommitTree(xid, parsed->nsubxacts, parsed->subxacts, lsn);

...
}
```
It looks like `TransactionIdAsyncCommitTree` is the function we're looking for that writes to CLOG.

To verify the redo logic for transaction commit information in WAL, let's set three breakpoints on the standby's startup process, then execute `begin;select txid_current();commit;` on the source database to commit a transaction, and see if the standby's startup process hits the functions we want to see when doing redo:

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
The breakpoint `TransactionIdAsyncCommitTree` is hit, and `xid=1818665`, which is the transaction ID just committed on the source database. This confirms the code logic we visually traced is correct.
So, **the standby database's CLOG transaction ID status is synchronized by WAL with rmgr=Transaction.**

## Summary
 - CLOG only stores transaction ID status, not the transaction ID itself
 - Transaction status in CLOG files can be manually located via the transaction ID
 - WAL for rmgr=CLOG only extends and cleans up CLOG files, it does not update transaction status
 - WAL for rmgr=Transaction updates CLOG transaction status

## References
[^2]: Yan Shuli, PostgreSQL CLOG Analysis <https://www.modb.pro/db/606433>
[^1]: "PostgreSQL Database Kernel Analysis", Chapter 7, p380-390
[^3]: "Quickly Mastering PostgreSQL Version New Features", p24


