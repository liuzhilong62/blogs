---
title: "OGG Oracle-to-PostgreSQL Sync — Hands-On Steps"
date: 2024-08-13
categories: [Miscellaneous]
description: "Hands-on steps for setting up Oracle GoldenGate Oracle-to-PostgreSQL sync link, covering environment preparation, OGG installation, parameter configuration, and sync verification."
---

Source DB: Oracle (11.2.0.4) 192.168.10.141
Target DB: PGSQL (10.12) 192.168.10.128
OGG software version: (19.1.0.0.4)
OGG download: Oracle GoldenGate Downloads
glibc issue handling: https://www.cnblogs.com/hxlasky/p/16779047.html

### 1. Install OGG Software on Source and Target

Source:

**A. Configure response file: oggcore.rsp**

```
oracle.install.responseFileVersion=/home/oracle/oggcore.rsp
INSTALL_OPTION=ORA11g
SOFTWARE_LOCATION=/oracle/ogg
START_MANAGER=false
MANAGER_PORT=7809
DATABASE_LOCATION=/oracle/db/11.2.0.4
INVENTORY_LOCATION=/oracle/oraInventory
UNIX_GROUP_NAME=oinstall
```

**B. Silent install OGG**

```
./runInstaller -silent -nowait -responseFile /home/oracle/oggcore.rsp
```

```
oracle@szgtsp431-or@ecsdb>./runInstaller -silent -nowait -responseFile /home/oracle/oggcore.rsp
Starting Oracle Universal Installer...
Checking Temp space: must be greater than 120 MB.   Actual 32405 MB    Passed
Checking swap space: must be greater than 150 MB.   Actual 2048 MB    Passed
Preparing to launch Oracle Universal Installer from /tmp/OraInstall2020-08-14_08-57-27AM. Please wait ...
You can find the log of this install session at:
 /oracle/oraInventory/logs/installActions2020-08-14_08-57-27AM.log
Successfully Setup Software.
The installation of Oracle GoldenGate Core was successful.
Please check '/oracle/oraInventory/logs/silentInstall2020-08-14_08-57-27AM.log' for more details.
```

### 2. Set Database to Archive Mode

```
oracle@szgtsp431-or@ecsdb>sqlplus / as sysdba
SQL*Plus: Release 11.2.0.4.0 Production on Fri Aug 14 09:06:34 2020
Copyright (c) 1982, 2013, Oracle.  All rights reserved.
Connected to:
Oracle Database 11g Enterprise Edition Release 11.2.0.4.0 - 64bit Production
With the Partitioning, OLAP, Data Mining and Real Application Testing options
SQL> archive log list;
Database log mode              Archive Mode
Automatic archival             Enabled
Archive destination            /oracle/oradata/archivelog
Oldest online log sequence     19
Next log sequence to archive   21
Current log sequence           21
```

### 3. Enable Force Logging and Minimum Supplemental Logging

```sql
alter database force logging;
alter database add supplemental log data;
alter system switch logfile;
```

Verify force logging and minimum supplemental logging enabled:

```sql
select force_logging,supplemental_log_data_min from v$database;
```

### 4. Set enable_goldengate_replication Parameter

```sql
alter system set enable_goldengate_replication=true scope=both;
```

If RAC, all nodes must be modified:

```sql
alter system set enable_goldengate_replication=true scope=both sid='*';
```

### 5. Create OGG User, Tablespace, and Grant Privileges

```sql
create tablespace tbs_ogg datafile '/oracle/oradata/datafile/tbs_ogg01.dbf' size 100M;
create user goldengate identified by 123456 default tablespace tbs_ogg temporary tablespace temp;
grant create session,alter session to goldengate;
grant alter system to goldengate;
grant resource to goldengate;
grant connect to goldengate;
grant select any dictionary to goldengate;
grant flashback any table to goldengate;
grant select any table to goldengate;
grant select any table to goldengate;
grant insert any table to goldengate;
grant update any table to goldengate;
grant delete any table to goldengate;
grant select on dba_clusters to goldengate;
grant execute on dbms_flashback to goldengate;
grant create table to goldengate;
grant create sequence to goldengate;
grant alter any table to goldengate;
grant dba to goldengate;
grant lock any table to goldengate;
```

### 6. Enable Table-Level Supplemental Logging

To sync table data from specific schemas, enable supplemental logging on those tables.

Check supplemental logging:

```sql
SELECT owner, table_name, log_group_name, log_group_type,
       decode(always, 'ALWAYS', 'Unconditional', NULL, 'Conditional') always
FROM dba_log_groups
ORDER BY owner, table_name, log_group_name;
```

Enable supplemental logging during low-activity window:

```
oracle@szgtsp431-or@ecsdb>ggsci
Oracle GoldenGate Command Interpreter for Oracle
Version 19.1.0.0.4 OGGCORE_19.1.0.0.0_PLATFORMS_191017.1054_FBO
Linux, x64, 64bit (optimized), Oracle 11g on Oct 17 2019 23:13:12
Operating system character set identified as US-ASCII.
Copyright (C) 1995, 2019, Oracle and/or its affiliates. All rights reserved.
GGSCI (szgtsp431-or) 1> dblogin userid goldengate,password 123456
Successfully logged into database.
GGSCI (szgtsp431-or as goldengate@ecsdb) 2> add trandata ecs.*
2020-08-14 09:13:54  INFO    OGG-15132  Logging of supplemental redo data enabled for table ECS.DEPT.
2020-08-14 09:13:54  INFO    OGG-15133  TRANDATA for scheduling columns has been added on table ECS.DEPT.
2020-08-14 09:13:54  INFO    OGG-15135  TRANDATA for instantiation CSN has been added on table ECS.DEPT.
2020-08-14 09:13:54  INFO    OGG-15132  Logging of supplemental redo data enabled for table ECS.INFO.
...
```

Verify all supplemental logging added:

```sql
select * from (
  select owner,table_name from dba_tables where owner in ('BGLWT')
  minus
  select owner,table_name from dba_log_groups)
order by owner,table_name;
-- no rows selected = all table-level supplemental logging added successfully
```

### 7. Configure Manager Process

```
oracle@szgtsp431-or@ecsdb>ggsci
...
GGSCI (szgtsp431-or) 1> dblogin userid goldengate,password 123456
Successfully logged into database.
GGSCI (szgtsp431-or as goldengate@ecsdb) 2> create subdirs
Creating subdirectories under current directory /home/oracle
...
GGSCI (szgtsp431-or as goldengate@ecsdb) 3> edit param mgr
PORT 7809
DYNAMICPORTLIST 7810-7980
PURGEOLDEXTRACTS ./dirdat/*, USECHECKPOINTS, MINKEEPDAYS 3
PURGEDDLHISTORY MINKEEPDAYS 7, MAXKEEPDAYS 10
LAGREPORTHOURS 1
LAGINFOMINUTES 30
LAGCRITICALMINUTES 45
```

### 8. Configure Extract Process

```
GGSCI (szgtsp431-or as goldengate@ecsdb) 7> add extract extecs, tranlog, threads 1,begin now
EXTRACT added.
GGSCI (szgtsp431-or as goldengate@ecsdb) 8> add exttrail ./dirdat/lt, extract extecs
EXTTRAIL added.
GGSCI (szgtsp431-or as goldengate@ecsdb) 9> info all
Program     Status      Group       Lag at Chkpt  Time Since Chkpt
MANAGER     RUNNING                                           
EXTRACT     STOPPED     EXTECS      00:00:00      00:00:38    
GGSCI (szgtsp431-or as goldengate@ecsdb) 10> edit param extecs
EXTRACT extecs
SETENV (ORACLE_HOME = "/oracle/db/11.2.0.4")
SETENV (ORACLE_SID = "ecsdb")
USERID goldengate, PASSWORD 123456
EXTTRAIL ./dirdat/lt
TRANLOGOPTIONS EXCLUDEUSER goldengate
TRANLOGOPTIONS DBLOGREADER
DBOPTIONS ALLOWUNUSEDCOLUMN
FETCHOPTIONS USESNAPSHOT, USELATESTVERSION, MISSINGROW REPORT
STATOPTIONS REPORTFETCH
WARNLONGTRANS 1h, CHECKINTERVAL 10m
DYNAMICRESOLUTION
DISCARDFILE ./dirrpt/extecs.dsc, APPEND, MEGABYTES 1024
DISCARDROLLOVER AT 6:00
REPORTROLLOVER AT 6:00
REPORTCOUNT EVERY 1 MINUTES, RATE
DDL INCLUDE MAPPED
DDLOPTIONS ADDTRANDATA, REPORT
DDLOPTIONS NOCROSSRENAME, REPORT
TABLE ECS.*;
```

### 9. Configure Pump Process

```
GGSCI (szgtsp431-or as goldengate@ecsdb) 11> add extract deliecs, exttrailsource ./dirdat/lt
EXTRACT added.
GGSCI (szgtsp431-or as goldengate@ecsdb) 12> add rmttrail ./dirdat/rt, extract deliecs, megabytes 500
RMTTRAIL added.
GGSCI (szgtsp431-or as goldengate@ecsdb) 13> edit param deliecs
EXTRACT deliecs
PASSTHRU
DYNAMICRESOLUTION
RMTHOST 192.168.10.100, MGRPORT 7809
RMTTRAIL ./dirdat/rt
DISCARDFILE ./dirrpt/deliecs.dsc, APPEND, MEGABYTES 1024
DISCARDROLLOVER AT 6:00
REPORTCOUNT EVERY 1 MINUTES, RATE
REPORT AT  0:00
REPORT AT  1:00
...
REPORT AT 23:00
REPORTROLLOVER AT 00:00
STATOPTIONS RESETREPORTSTATS
TABLE ECS.*;     
```

### 10. Start Extract Process

```
GGSCI (szgtsp431-or as goldengate@ecsdb) 20> start extecs
Sending START request to MANAGER ...
EXTRACT EXTECS starting
GGSCI (szgtsp431-or as goldengate@ecsdb) 21> info all
Program     Status      Group       Lag at Chkpt  Time Since Chkpt
MANAGER     RUNNING                                           
EXTRACT     STOPPED     DELIECS     00:00:00      00:06:06    
EXTRACT     RUNNING     EXTECS      00:00:00      00:00:01    
```

### 11. Configure Target OGG Software

**A. Upload OGG software and extract**
**B. Configure OGG environment variables**

```
[pgsql@szgtsp428-or ~]$ vi .bash_profile
## .bash_profile
## Get the aliases and functions
if [ -f ~/.bashrc ]; then
        . ~/.bashrc
fi
## User specific environment and startup programs
PATH=$PATH:$HOME/bin
export PATH
export PGHOME=/usr/local/pgsql
export PGDATA=/data/pgsql
export OGG_HOME=/data/ogg
export PATH=$PATH:$PGHOME/bin:$OGG_HOME
LD_LIBRARY_PATH=$PGHOME/lib
LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/lib:/usr/lib:/usr/local/lib:$OGG_HOME/lib
export LD_LIBRARY_PATH
export ODBCINI=/home/pgsql/odbc.ini
export DD_ODBC_HOME=/data/ogg

[pgsql@szgtsp428-or ~]$ ggsci
Oracle GoldenGate Command Interpreter for PostgreSQL
Version 19.1.0.0.200714 OGGCORE_19.1.0.0.0OGGBP_PLATFORMS_200628.2141
Linux, x64, 64bit (optimized), PostgreSQL on Jun 29 2020 03:59:15
Operating system character set identified as UTF-8.
Copyright (C) 1995, 2019, Oracle and/or its affiliates. All rights reserved.
GGSCI (szgtsp428-or) 1>
```

### 12. Create Database and Table on Target

```
ecsdb=# \l
                                List of databases
   Name    |  Owner   | Encoding |   Collate   |    Ctype    | Access privileges 
-----------+----------+----------+-------------+-------------+-------------------
 ecsdb     | postgres | UTF8     | en_US.UTF-8 | en_US.UTF-8 | 
 postgres  | pgsql    | UTF8     | en_US.UTF-8 | en_US.UTF-8 | 
 template0 | pgsql    | UTF8     | en_US.UTF-8 | en_US.UTF-8 | =c/pgsql         +
           |          |          |             |             | pgsql=CTc/pgsql
 template1 | pgsql    | UTF8     | en_US.UTF-8 | en_US.UTF-8 | =c/pgsql         +
           |          |          |             |             | pgsql=CTc/pgsql
(4 rows)

ecsdb=# \d
            List of relations
 Schema |     Name     | Type  |  Owner   
--------+--------------+-------+----------
 public | student_info | table | postgres
(1 row)

ecsdb=# select * from student_info;
 id | name | address 
----+------+---------
  1 | Zhang San | Guangzhou
  2 | Li Si  | Shenzhen
  3 | Wang Wu | Shanghai
  4 | Zhao Liu | Beijing
  5 | Sun Qi | Wuhan
  6 | A Da   | Chengdu
  7 | A Er   | Nanjing
(7 rows)
```

### 13. Configure Target Manager Process and Start

```
[pgsql@szgtsp428-or ogg]$ ggsci
Oracle GoldenGate Command Interpreter for PostgreSQL
...
GGSCI (szgtsp428-or) 1> info all
Program     Status      Group       Lag at Chkpt  Time Since Chkpt
MANAGER     STOPPED                                           
GGSCI (szgtsp428-or) 2> create subdirs
Creating subdirectories under current directory /data/ogg
...
GGSCI (szgtsp428-or) 3> edit param mgr
port 7809
GGSCI (szgtsp428-or) 4> info all
...
GGSCI (szgtsp428-or) 5> start mgr
Manager started.
GGSCI (szgtsp428-or) 7> info all
Program     Status      Group       Lag at Chkpt  Time Since Chkpt
MANAGER     RUNNING                                           
```

Now start the pump process on source (deliecs):

```
oracle@szgtsp431-or@ecsdb>ggsci
...
GGSCI (szgtsp431-or) 1> info all
Program     Status      Group       Lag at Chkpt  Time Since Chkpt
MANAGER     RUNNING                                           
EXTRACT     ABENDED     DELIECS     00:00:00      01:06:41    
EXTRACT     RUNNING     EXTECS      00:00:00      00:00:07    
GGSCI (szgtsp431-or) 2> start deliecs
Sending START request to MANAGER ...
EXTRACT DELIECS starting
GGSCI (szgtsp431-or) 3> info all
Program     Status      Group       Lag at Chkpt  Time Since Chkpt
MANAGER     RUNNING                                           
EXTRACT     RUNNING     DELIECS     00:00:00      01:06:55    
EXTRACT     RUNNING     EXTECS      00:00:00      00:00:01      
```

### 14. Target PostgreSQL Parameter Adjustment

```ini
wal_level = logical           #minimal, replica, or logical
max_replication_slots = 10    #max number of replication slots
max_wal_sender = 10           #maximum number of wal sender processes
wal_receiver_status_interval=10s  #optional, keep the system default
wal_sender_timeout  = 60s          #optional, keep the system default
track_commit_timestamp=off        #optional, keep the system default
```

Restart PostgreSQL after adjusting parameters:

```
[pgsql@szgtsp428-or pgsql]$ pg_ctl stop -D /data/pgsql/ -l /data/pgsql/logfile
waiting for server to shut down.... done
server stopped
[pgsql@szgtsp428-or pgsql]$ pg_ctl start -D /data/pgsql/
waiting for server to start.... done
server started
```

### 15. Data Source Configuration (odbc.ini)

```ini
[ODBC Data Sources]
PGDSN=DataDirect 10.12 PostgreSQL Wire Protocol
postgres=DataDirect 10.12 PostgreSQL Wire Protocol
scott=DataDirect 10.12 PostgreSQL Wire Protocol
[ODBC]
IANAAppCodePage=4
InstallDir=/data/ogg
[PGDSN]
Driver=/data/ogg/lib/GGpsql25.so
Description=DataDirect 10.12 PostgreSQL Wire Protocol
Database=ecsdb
HostName=127.0.0.1
PortNumber=5432
LogonID=postgres
Password=123456
```

### 16. Connection Test

```
[pgsql@szgtsp428-or ~]$ cd /data/ogg
[pgsql@szgtsp428-or ogg]$ ggsci
...
GGSCI (szgtsp428-or) 1> info all
Program     Status      Group       Lag at Chkpt  Time Since Chkpt
MANAGER     RUNNING                                           
GGSCI (szgtsp428-or) 2> dblogin sourcedb pgdsn userid postgres, password postgres
2020-08-14 11:35:01  INFO    OGG-03036  Database character set identified as UTF-8. Locale: en_US.UTF-8.
2020-08-14 11:35:01  INFO    OGG-03037  Session character set identified as UTF-8.
Successfully logged into database.
```

### 17. Configure and Start Replicat Process on Target

Add checkpoint table:

```
GGSCI (szgtsp428-or) 1> dblogin sourcedb pgdsn userid postgres, password 123456
Successfully logged into database.
GGSCI (szgtsp428-or as postgres@pgdsn) 2> add checkpointtable public.chkt
Successfully created checkpoint table public.chkt.
```

Configure replicat:

```
GGSCI (szgtsp428-or as postgres@pgdsn) 34> edit param repl
REPLICAT repl
SOURCEDEFS ./dirdef/student_info.def
SETENV (PGCLIENTENCODING = "UTF8")
SETENV (ODBCINI="/home/pgsql/odbc.ini")
SETENV (NLS_LANG="AMERICAN_AMERICA.AL32UTF8")
targetdb pgdsn userid postgres, password 123456
DISCARDFILE ./dirrpt/repl.dsc, purge
MAP ecs.student_info, TARGET public.student_info;

GGSCI (szgtsp428-or as postgres@pgdsn) 36> add replicat repl,exttrail ./dirdat/rt,checkpointtable public.chkt
REPLICAT added.
GGSCI (szgtsp428-or as postgres@pgdsn) 38> start repl
Sending START request to MANAGER ...
REPLICAT REPL starting

GGSCI (szgtsp428-or as postgres@pgdsn) 55> info all
Program     Status      Group       Lag at Chkpt  Time Since Chkpt
MANAGER     RUNNING                                           
REPLICAT    RUNNING     REPL        00:00:00      00:00:08
```

### 18. Test Verification

First, create matching table structure on target:

```sql
create table student_info (id int primary key, name varchar(100), address varchar(100));
```

Then initialize data:

Configure extinit process on source:

```
GGSCI (szgtsp431-or as goldengate@ecsdb) 17> edit param extinit
EXTRACT extinit
userid goldengate, PASSWORD 123456
REPORTCOUNT EVERY 30 MINUTES, RATE
DISCARDFILE ./dirrpt/extinit.dsc, APPEND, MEGABYTES 1024
RMTHOST 192.168.10.100,MGRPORT 7809, compress
RMTTASK replicat,GROUP replinit
TABLE ecs.student_info;

GGSCI (szgtsp431-or as goldengate@ecsdb) 18> ADD EXTRACT extinit, SOURCEISTABLE
EXTRACT added.
```

Configure replinit process on target:

```
GGSCI (szgtsp428-or as postgres@pgdsn) 28> edit param replinit
REPLICAT replinit
targetDB pgdsn, USERID postgres, PASSWORD 123456
discardfile ./dirrpt/replinit.dsc, PURGE
SOURCEDEFS ./dirdef/student_info.def
Map ecs.student_info,target public.student_info;

GGSCI (szgtsp428-or as postgres@pgdsn) 29> add replicat repinit, SPECIALRUN
REPLICAT added.
```

Start Oracle-to-PG data initialization:

```
GGSCI (szgtsp431-or as goldengate@ecsdb) 9> start extinit
Sending START request to MANAGER ...
EXTRACT EXTINIT starting
```

Target: (view initialization row count via View report replicat)

Check both sides:

Source (Oracle):
```
SQL> select * from student_info;
        ID NAME       ADDRESS
---------- ---------- ----------
         1 Zhang San  Guangzhou
         2 Li Si      Shenzhen
         3 Wang Wu    Shanghai
         4 Zhao Liu   Beijing
         5 Sun Qi     Wuhan
         6 A Da       Chengdu
         7 A Er       Nanjing
         8 A San      Beijing
8 rows selected.
```

Target (PostgreSQL):
```
ecsdb=# select * from student_info;
 id | name | address 
----+------+---------
  1 | Zhang San | Guangzhou
  2 | Li Si  | Shenzhen
  3 | Wang Wu | Shanghai
  4 | Zhao Liu | Beijing
  5 | Sun Qi | Wuhan
  6 | A Da   | Chengdu
  7 | A Er   | Nanjing
  8 | A San  | Beijing
(8 rows)
```

Insert data on source:

```sql
SQL> insert into ecs.student_info values (10,'aa','bb');
1 row created.
SQL> commit;
Commit complete.
```

Check target — data synchronized successfully.

> Original link: https://lastdba.com/2024/08/13/ogg搭建oracle-pg同步实操步骤/
