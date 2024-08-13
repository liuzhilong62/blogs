​

# 什么是pg_rewind?
pg_rewind是pg提供的工具，当2个pg实例时间线（timeline）出现分叉时，pg_rewind可以做实例间的同步。（比如主库运行的情况下，备库failover后运行了一段时间，此时主备的时间线就出现了分叉）
pg_rewind会对比两者的大小，然后把大小不一样的文件从源拷贝到目标，包括配置文件。但是它不会对比没有发生改变的文件，所以pg_rewind在比较大的库，更改少量数据时，运行效率较高。
pg_rewind可以运用在备库failover后，备库即时运行一段时间，也可以把备库拉到和主库一样的状态，重新成为standby。
pg_rewind运行过程中，会对比主（源）备（目标）的差异点，并把主库的差异点后的WAL日志传递给备库。所以，如果主库在差异点之后的WAL也丢失了，那么rewind是不会拷贝不存在的WAL日志的，所以此时备库仍然不会被成功做成standby。解决该问题需要用restore。

！！！在使用pg_rewind时，应备份目标实例。pg_rewind会直接覆盖目标库的文件，如果rewind失败，那么可能目标库无法启动。

# pg_rewind的使用
主备切换后，老主库仍然运行，导致主备时间线不一致，老主库无法当做新主库的备库启动

拉起备库时，报时间线错误如下

LOG:  entering standby mode
FATAL:  requested timeline 2 is not a child of this server's history
DETAIL:  Latest checkpoint is at 0/6000028 on timeline 1, but in the history of the requested timeline, the server forked off from that timeline at 0/4000098.
LOG:  startup process (PID 22321) exited with exit code 1
LOG:  aborting startup due to startup process failure
LOG:  database system is shut down

此时需要用rewind重新拉齐一次主备


1.配置当前主库的pg_hba
配置pg_rewind的登陆用户登陆源库许可，hba生效需要重启数据库

vi $source/pg_hba.conf
host    all       pg         172.17.100.150/32          trust


pg_rewind需要使用高权限用户，pg新版本可以授权，pg老版本最好用超级用户。
我当前环境的版本为pg9.6，直接使用OS超级用户

2.wal_log_hints = on参数配置
将wal_log_hints = on追加到目标库postgres.conf，重新启动并关闭一次目标库（此时主库是启动状态，备库是关闭状态）

vi $dest/postgres.conf

wal_log_hints = on

3.pg_rewind命令执行
[pg@lzl pg96data_sla]$ /pg/pg96/bin/pg_rewind --target-pgdata /pg/pg96data_pri --source-server='host=172.17.100.150 port=5433 user=pg password=oracle  dbname=postgres'
servers diverged at WAL position 0/4000098 on timeline 1
rewinding from last common checkpoint at 0/4000028 on timeline 1
Done!


4.配置备库参数
更改postgres.conf和recovery.conf中的IP、端口、目录等配置，pg_rewind会把配置文件也cp过来
[pg@lzl pg96data_pri]$ mv recovery.done recovery.conf
[pg@lzl pg96data_pri]$ vi recovery.conf
[pg@lzl pg96data_pri]$ vi postgres.conf

5.启动备库

[pg@lzl pg96data_pri]$  /pg/pg96/bin/pg_ctl -D /pg/pg96data_sla -l /pg/pg96data_sla/server.log start        
server starting
[pg@lzl pg96data_sla]$ psql -p5433 postgres
psql (9.6.17)
postgres=# \x
Expanded display is on.
postgres=# select * from  pg_stat_replication ;
-[ RECORD 1 ]----+------------------------------
pid              | 24766
usesysid         | 16384
usename          | lzl
application_name | walreceiver
client_addr      | 172.17.100.150
client_hostname  | 
client_port      | 47345
backend_start    | 2021-07-30 07:44:05.582546+00
backend_xmin     | 
state            | streaming
sent_location    | 0/4033790
write_location   | 0/4033790
flush_location   | 0/4033790
replay_location  | 0/4033790
sync_priority    | 0
sync_state       | async


# 常见问题
## pg_rewind命令报错一

could not fetch remote file "global/pg_control": ERROR:  must be superuser to read files
Failure, exiting
解决办法：
使用高权限用户

postgres=# \du
                                    List of roles
  Role name  |                         Attributes                         | Member of 
-------------+------------------------------------------------------------+-----------
 lzl         | Replication                                                | {}
 pg          | Superuser, Create role, Create DB, Replication, Bypass RLS | {}
 rewind_user |                                                            | {}


pg用户是pg server自带的超级用户，跟pg安装用户相同。os的安装用户肯定有修改pg_control的权限

/pg/pg96/bin/pg_rewind --target-pgdata /pg/pg96data_pri --source-server='host=172.17.100.150 port=5433 user=pg password=oracle  dbname=postgres'
pg_rewind命令报错二
 

could not connect to server: FATAL:  no pg_hba.conf entry for host "172.17.100.150", user "rewind_user", database "postgres"
Failure, exiting

## 没有配置pg_hba.conf连接
解决办法：配置用户的pg_hba，例如

host    all       pg         172.17.100.150/32          trust

## pg_rewind命令报错三
 

[pg@lzl pg96data_sla]$   /pg/pg96/bin/pg_rewind --target-pgdata /pg/pg96data_pri --source-server='host=172.17.100.150 port=5433 user=pg password=oracle  dbname=postgres'

target server needs to use either data checksums or "wal_log_hints = on"

问题原因：
1. full_page_writes （默认开启）
2. wal_log_hints 设置成 on 或者 PG 在初始化时开启 checksums 功能 
解决办法：将wal_log_hints = on配置到目标库postgres.conf，启动再关闭一次目标库（目标库本来就是关闭的，必须启动再关闭一次，不然参数不会生效）
vi postgres.conf 加入目标库配置

wal_log_hints = on

重启目标库以生效

[pg@lzl pg96data_sla]$  /pg/pg96/bin/pg_ctl -D /pg/pg96data_pri -l /pg/pg96data_pri/server.log start      
server starting
[pg@lzl pg96data_sla]$  /pg/pg96/bin/pg_ctl -D /pg/pg96data_pri -l /pg/pg96data_pri/server.log stop
waiting for server to shut down.... done

参考文档：
https://www.postgresql.org/docs/9.6/app-pgrewind.html

​
