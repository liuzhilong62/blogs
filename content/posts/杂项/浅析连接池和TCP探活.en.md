---
title: "A Brief Analysis of Connection Pools and TCP Probing"
date: 2026-06-11
categories: ["Miscellaneous"]
tags: ["TCP", "keepalive", "connection pool", "PostgreSQL", "RST", "FIN"]
description: "Deep dive into TCP keepalive, FIN vs RST, and connection pool probing mechanisms — with hands-on packet capture tests"
---



It's important for DBAs to understand some connection pool and TCP probing/keepalive knowledge — it helps with troubleshooting disconnection errors, SQL execution errors, and HA failover scenarios.

## TCP Keepalive and PostgreSQL Parameters

Applications (including business clients, database servers, psql) and the operating system can all set socket options. If not explicitly set, the Linux kernel parameter defaults are used.

| Linux Parameter              | Linux Default | Socket Option         | PG Server Parameter                | libpq Parameter (PG Client) |               |
| ---------------------------- | ------------- | --------------------- | ---------------------------------- | --------------------------- | ------------- |
|                              |               | SO_KEEPALIVE (default 1) |                                 | `keepalives`                | 1(default),on |
| `tcp_keepalive_time`         | 7200s         | TCP_KEEPIDLE          | `tcp_keepalives_idle`              | `keepalives_idle`           |               |
| `tcp_keepalive_intvl`        | 75s           | TCP_KEEPINTVL         | `tcp_keepalives_interval`          | `keepalives_interval`       |               |
| `tcp_keepalive_probes`       | 9             |                       | `tcp_keepalives_count`             | `keepalives_count`          |               |
| `tcp_retries2`               | 15            |                       |                                    |                             |               |
|                              |               | TCP_USER_TIMEOUT      | `tcp_user_timeout`                 | `tcp_user_timeout`          |               |
|                              |               |                       | `client_connection_check_interval` |                             |               |

Both PG server and libpq use the OS socket defaults by default.

What the defaults mean: after a connection has been idle for 2 hours, the TCP kernel actively sends a keepalive probe, and after 75s × 9 = 11.25 minutes, the connection is terminated.

The default `net.ipv4.tcp_keepalive_time=7200s` is far too large — it's almost meaningless. What's the point of doing keepalive only after the intermediate network layer (firewalls, etc.) has already killed the connection?

`client_connection_check_interval` is an application-layer mechanism introduced in PG 14 — the PG server performs a non-blocking `recv()` on the client socket every N milliseconds, and if it returns an error (connection broken), it proactively cleans up. This doesn't require any Linux kernel parameter configuration.





## TCP FIN and RST Packets

Reference: <https://linuxvox.com/blog/what-is-the-reason-and-how-to-avoid-the-fin-ack-rst-and-rst-ack/>

TCP 6 control bits:

| Flag | Name        | Purpose                                                      |
| ---- | ----------- | ------------------------------------------------------------ |
| SYN  | Synchronize | Initiates a connection (used in the handshake).              |
| ACK  | Acknowledge | Confirms receipt of a packet (includes an ACK number for sequence tracking). |
| FIN  | Finish      | Signals intent to close a connection gracefully.             |
| RST  | Reset       | Abruptly terminates a connection (no graceful closure).      |
| PSH  | Push        | Forces immediate delivery of data (bypasses buffering).      |
| URG  | Urgent      | Marks data as "urgent" (rarely used today).                  |

 

FIN and RST can be sent in both normal and abnormal situations. Key takeaways:

1. Process exit or program abort sends a FIN packet — this includes `kill -9` (verified: killing a PG process with `kill -9` sends FIN; see "Tests" section)
2. Network unreachability such as port not listening produces an RST packet
3. TCP keepalive timeout also produces an RST packet, because the probe detected network unreachability
4. Firewalls may also send RESET
5. RST packets are related to the application-layer `connection reset by peer` error

Below is a detailed explanation of the 6 TCP control bits and FIN/RST:



## TCP Disconnection Tests

### Test: Does killing a session trigger an active disconnect?

- ORACLE: whether using the built-in `alter system` to kill a session or `kill -9` to kill a session, the client receives a FIN packet from the server.
- PG: using the built-in `pg_terminate_backend()` to kill a session, the client receives a FIN packet from the server.
- Redis: shutting down the database or `kill -9` on the redis-server process, the client receives a FIN packet from the server.

**Test conclusion: Even when a process terminates abnormally, the TCP kernel can send a FIN packet.**

Additionally, in this round of testing, redis-cli did not appear to handle the FIN packet correctly — it sent RST on its own:

| Seq | Time                | Direction | Flags        | Notes                           |
| :-- | :------------------ | :-------- | :----------- | :------------------------------ |
| 1   | 17:42:43.131958     | S→C       | `.` ACK      | Server sends ACK                |
| 2   | 17:42:49.264831     | S→C       | [F.] FIN+ACK | Server actively requests close  |
| 3   | 17:42:49.304905     | C→S       | `.` ACK      | Client ACKs FIN (ack=9=8+1)     |
| 4~15 | 17:43:04 ~ 17:44:19 | C→S       | `.` ACK      | Client keeps ACKing (holding connection?) |
| 16  | 17:44:19.323962     | S→C       | [R] RST      | Server sends RST                |

### Test: What packet does the client receive when PG process terminates, normal shutdown, or forced shutdown?

Test environment: Rocky 10.1 + PG 18.2, tcpdump capturing TCP packets on the lo interface.

| Scenario | Server sends | Four-way handshake | Client error |
|----------|-------------|--------------------|--------------|
| `pg_terminate_backend(PID)` | `[F.]` FIN+ACK | ✅ Complete | `FATAL: terminating connection due to administrator command` |
| `pg_ctl stop -m fast` | `[F.]` FIN+ACK | ✅ Complete | `FATAL: terminating connection due to administrator command` |
| `kill -9 postmaster` | `[F.]` FIN+ACK | ✅ Complete | `server closed the connection unexpectedly` |

**Conclusion: kill -9 also sends FIN, not RST.** When a process is SIGKILLed, the Linux TCP kernel closes the socket on behalf of the process, sending FIN to complete the four-way handshake. In all three scenarios, the client receives a normal FIN close — no scenario produces RST.

### Test: How to produce an RST packet

**Port not listening (PG already shut down)**

```text
14:01:48.492004 IP 127.0.0.1.52092 > 127.0.0.1.ircu-2: Flags [S], seq 2570941791
14:01:48.492012 IP 127.0.0.1.ircu-2 > 127.0.0.1.52092: Flags [R.], seq 0, ack 2570941792, win 0
```

Client SYN → kernel returns `[R.]` RST+ACK, `win 0`. psql reports `Connection refused`.

**iptables REJECT --reject-with tcp-reset**

```text
14:02:37.768515 IP 127.0.0.1.36436 > 127.0.0.1.ircu-2: Flags [S], seq 382980016
14:02:37.768522 IP 127.0.0.1.ircu-2 > 127.0.0.1.36436: Flags [R.], seq 0, ack 382980017, win 0
```

Exactly the same as port not listening: `[R.]` RST+ACK. psql likewise reports `Connection refused`.

**iptables DROP (simulating firewall silent drop)**

```text
14:00:07.050040 IP 127.0.0.1.33166 > 127.0.0.1.ircu-2: Flags [S], seq 985608804
14:00:08.095618 IP 127.0.0.1.33166 > 127.0.0.1.ircu-2: Flags [S], seq 985608804   ← retransmit after 1s
14:00:09.119647 IP 127.0.0.1.33166 > 127.0.0.1.ircu-2: Flags [S], seq 985608804   ← retransmit after 2s
```

No response from the server. The client retransmits SYN 3 times (at 1s, 2s, 4s intervals) then times out. **Unlike REJECT, DROP produces no RST — the client can only detect it via timeout.**

**Summary of RST-producing scenarios**

| Scenario | Layer | Packet Type | Triggered By |
|----------|-------|-------------|--------------|
| Port not listening | TCP kernel | `[R.]` RST+ACK | OS kernel |
| Firewall REJECT | iptables | `[R.]` RST+ACK | Firewall |
| TCP keepalive timeout | TCP kernel | `[R]` RST | OS kernel (after keepalive probe fails) |
| Process termination (kill -9) | TCP kernel | `[F.]` FIN+ACK (NOT RST!) | OS kernel closes socket on behalf of process |
| Firewall DROP | — | None | — |

**Core distinction: FIN comes from process exit (kernel gracefully closes on behalf of the process, even for kill -9); RST comes from network unreachability.**

### Test: Does taking an IP offline trigger an active disconnect?

redis-cli test, taking the Redis server's listening IP offline.

```shell
#term1:
r -h 30.181.15.96 -p 17742 -a 1qaz@WSX
sudo tcpdump host 30.181.48.7 and port 54854 -n -vv   
#term2:
sudo tcpdump host 30.181.48.7 and port 54854 -n -vv   
```

In this test, taking the IP offline did not produce any FIN or RST packets. Only the keepalive mechanism itself initiated an RST. The sequence:

| Seq | Time            | Direction      | Flags        | Notes                              |
| :-- | :-------------- | :------------- | :----------- | :--------------------------------- |
| 1   | 17:02:43.004897 | Client→Server  | `.` ACK      | Client sends ACK (15s interval)    |
| 2   | 17:02:43.004960 | Server→Client  | `.` ACK      | Server responds ACK                |
| 3   | 17:02:58.043896 | Client→Server  | `.` ACK      | Client Keep-Alive (15s interval)   |
| 4   | 17:02:58.043953 | Server→Client  | `.` ACK      | Server responds ACK                |
| 5   | 17:02:58.063214 | Server→Client  | `.` ACK      | Server duplicate ACK               |
| 6   | 17:02:58.063234 | Client→Server  | `.` ACK      | Client responds ACK                |
| 7   | 17:03:13.051905 | Client→Server  | `.` ACK      | Client Keep-Alive (15s interval)   |
| 8   | 17:03:18.059901 | Client→Server  | `.` ACK      | Client Keep-Alive (5s interval)    |
| 9   | 17:03:23.067901 | Client→Server  | `.` ACK      | Client Keep-Alive (5s interval)    |
| 10  | 17:03:28.075899 | Client→Server  | [R.] RST+ACK | Client actively disconnects (5s interval) |

redis-cli has no keepalive configuration, but the [redis-cli source code](https://raw.githubusercontent.com/redis/redis/refs/heads/4.0/src/redis-cli.c) hardcodes:

```c
#define REDIS_CLI_KEEPALIVE_INTERVAL 15 /* seconds */
```

redis-cli's keepalive is hardcoded at 15 seconds in the code, hence the 15-second keepalive packets visible in the capture.

During the capture, the server IP was taken offline but no disconnection notification was received. Eventually, the client's keepalive probe detected the socket anomaly, and the client actively sent RST.

(The Redis server side can also initiate keepalive, but it wasn't triggered this time.)

**Test conclusion: Directly taking an IP offline — the kernel may not perform any FIN/RST action at all.**



### Test: Does normal data communication interfere with the tcp_keepalive cycle?

Conclusion: Yes, it does. Data communication not only sends PSH packets to the peer but also includes ACK packets.

The following test uses redis-cli, where redis-cli's keepalive = 15s and redis-server's keepalive = 2h:

| Client Trigger | TCP Timestamp                          | Client Sends | Server Sends |
| -------------- | -------------------------------------- | ------------ | ------------ |
| tcp_keepalive  | 17:16:05.558570-17:16:15.048701        | ACK          | ACK          |
| PING           | 17:16:15.048312-17:16:15.048701        | PSH          | PSH          |
| tcp_keepalive  | 17:16:15.048433-17:16:30.071278        | ACK          | ACK          |
| tcp_keepalive  | 17:16:30.070906-17:16:30.071278        | ACK          | ACK          |

### Test: Does idle_in_transaction and long-running SQL trigger keepalive?

Test environment: Rocky 10.1 + PG 18.2, client libpq configured with `keepalives_idle=5 keepalives_interval=3`.

**idle_in_transaction:**

```text
16:32:11.611  Last data ACK
16:32:16.927  Client → Server [.] ACK  ← after 5.3s, first keepalive probe
16:32:16.927  Server → Client [.] ACK
16:32:21.983  Client → Server [.] ACK  ← after 5s, second probe
16:32:21.983  Server → Client [.] ACK
16:32:27.039  Client → Server [.] ACK  ← after 5s, third probe
16:32:27.039  Server → Client [.] ACK
```

Conclusion: idle_in_transaction **does send keepalive**. Every 5 seconds, a pair of probe+response — no other TCP packets whatsoever.

**Long-running SQL (server `tcp_keepalives_idle=10`):**

```text
16:32:43.148  Last ACK (after client sends SELECT pg_sleep(30))
             ← 10 seconds of zero TCP packets ← SQL is running, but no data returned
16:32:53.279  Server → Client [.] ACK  ← after 10.1s, server sends keepalive probe
16:32:53.279  Client → Server [.] ACK
```

Conclusion: **SQL running ≠ TCP has packets.** During `pg_sleep(30)`, there's zero TCP communication — keepalive still fires. It only cares whether there's data exchange at the TCP layer, not what the database is doing.

If a report query runs for 5 minutes without returning intermediate results, from the perspective of firewalls/NAT/load balancers, this TCP connection is a 5-minute dead connection — without keepalive configured, it will be killed.





## Connection Probing

The problem of dead connections on the client side can only be solved by the client — the server is already unreachable, so you can't expect it to notify you.

Two key concepts of connection pools:

- **`socket.close()` ≠ connection pool `close()`**: The former is a TCP four-way handshake completely disconnecting; the latter is returning the connection to the pool. The connection remains ESTABLISHED, with its state changing to idle.
- **Goal of probing**: To promptly detect "zombie connections" — sockets that are already broken but the connection pool still considers alive.

Two common socket error states:

- **ESTABLISHED but actually unusable**: The connection pool hasn't detected that the socket has failed; errors only appear when the application layer tries to use it.
- **TIME_WAIT**: The socket is known to be unusable but not released in time; a large number of TIME_WAIT connections can exhaust ports.



Broadly speaking, probing mechanisms are divided into two types by network layer:

| Type | Action | Trigger Method | Content Sent |
|------|--------|----------------|--------------|
| Layer 4 probing | Kernel-level TCP packets | `tcp_keepalive` series parameters; connection pool's own keepalive | ACK packets (empty probe to check if peer is alive) |
| Layer 7 probing | Application-layer database commands | `testOnBorrow` / `testOnReturn` / `testWhileIdle` / `PING` / configure test-query | Depends on driver, e.g., `SELECT 1`, `PING`; `SELECT NOT pg_is_in_recovery()` / `SELECT @@READ_ONLY` |







### Layer 4 Probing

Linux's `tcp_keepalive` is the foundation of Layer 4 probing:

```shell
net.ipv4.tcp_keepalive_time   = 7200   # Start probing after 2 hours of idle
net.ipv4.tcp_keepalive_intvl  = 75     # Probe interval 75 seconds
net.ipv4.tcp_keepalive_probes = 9      # After 9 failed probes, disconnect
```

The problem with the defaults: 7200 seconds (2 hours) before probing begins — by then the firewall has long since killed the connection, making the probe pointless. Production environments typically need to tune this down to the minute level.

**If there's a proxy in the path (Nginx, HAProxy, etc.), TCP keepalive only reaches the proxy, not the backend database.** The proxy-to-database segment needs the proxy's own keepalive configuration; otherwise, if the proxy dies, the connection pool won't notice.

In actual communication, when there's data exchange, PSH/ACK packets themselves serve as a form of "keepalive." Keepalive only triggers when the connection is completely idle — if there's continuous data send/receive, the keepalive timer gets reset and no ACK probe packets are sent.

### Layer 7 Probing

Layer 7 probing is when the application actively sends database commands to verify the connection. Representative parameters for various connection pools (not exhaustive):

| Connection Pool | Parameter | Description |
|-----------------|-----------|-------------|
| JDBC Generic | `testOnBorrow`, `testOnReturn`, `testWhileIdle` | Validate on borrow/return/idle |
| HikariCP | `connectionTestQuery` | Validation SQL, commonly `SELECT 1` |
| Jedis | `testOnBorrow` | Validate on borrow |
| Lettuce | `pingBeforeActivateConnection` | PING before activation |
| Redisson | `pingConnectionInterval` | Periodic PING interval |
| Apache Commons Pool2 | `testOnBorrow`, etc. | Generic object pool validation |

Both `close()` and `returnObject()` return the connection to the pool, not truly close the TCP connection. After being returned, the connection is in idle state, but the socket remains ESTABLISHED. Apache Commons Pool2 maintains these connections through a standardized object pool management mechanism.

Regarding the performance impact of `testOnBorrow`: issuing `SELECT 1` every time a connection is borrowed adds overhead under high concurrency. Typically, `testWhileIdle` + a reasonable check interval is used to balance this.

**Choosing between Layer 4 and Layer 7:**

- Layer 4: Direct database connection, no proxy in the path — just tune TCP keepalive to a small value.
- Layer 7: Proxy in the path, need to confirm the database can truly execute SQL (not just TCP reachable), and can ensure the entire path is clear.
- Layer 7 + role awareness: When primary/replica distinction is needed, simple SQL like `SELECT 1` can't identify the database role — custom SQL must be configured. For example, Redis `PING` can't tell you the replica's status.



### Single Domain vs Dual Domain

When the driver is configured with primary/replica addresses (JDBC's `read-write` + `read-only`, or Lettuce's Master/Replica), it can automatically identify primary/replica and route accordingly.

Problems with a single domain:
- Can't detect primary/replica switchover
- Constrained by JVM/OS DNS caching (`networkaddress.cache.ttl`) — after switchover, connections may keep going to the old IP for a long time
- Layer 7 probing with `SELECT NOT pg_is_in_recovery()` can detect primary/replica changes, but it's less flexible than dual domains



## Summary

**FIN and RST occurrence scenarios:**

- FIN is sent by the kernel on behalf of the exiting process (including kill -9), completing a graceful four-way handshake close
- RST is produced when the network is unreachable: port not listening, keepalive timeout, firewall REJECT, etc.
- Directly taking an IP offline produces no FIN/RST — it can only be detected by keepalive probing
- Firewall DROP silently discards packets — no RST, client can only detect via timeout

**Layer 4 and Layer 7 probing mechanisms:**

- Layer 4 (TCP keepalive): Defaults to probing after 2 hours — must be tuned down for production. Only reaches the proxy, not the backend.
- Layer 7 (application-layer PING/SQL): Can confirm the database can truly execute commands, but has performance overhead under high concurrency.
- Proxy present / primary-replica distinction needed → Layer 7 is required
- Direct database connection → Layer 4 tuned to a small value suffices

**Keepalive behavior for idle_in_transaction and long-running SQL:**

- Both trigger keepalive — the trigger condition is no data exchange at the TCP layer, not the database state
- **SQL running ≠ TCP has packets**: Long report queries that don't return intermediate results are equivalent to dead connections at the TCP layer
- Without keepalive configured, firewalls may kill the connection while the SQL is still running

**Some notes:**

- `socket.close()` ≠ connection pool return: the former disconnects TCP; the latter merely marks the connection as idle
- The goal of connection pool probing is to discover those zombie connections whose sockets are already broken but the pool still thinks are alive
- `testOnBorrow` queries the database on every borrow — overhead under high concurrency; `testWhileIdle` + a reasonable interval is more practical
- When there's a proxy in the path, each segment needs independent keepalive configuration — if one segment breaks, the other side won't notice





# ref

- <https://raw.githubusercontent.com/redis/redis/refs/heads/4.0/src/redis-cli.c>
- <https://redisson.pro/docs/configuration/>
- <https://docs.paic.com.cn/#/post/57844638>
- <https://support.huaweicloud.com/intl/en-us/dcs_faq/dcs-faq-211230001.html>
- <https://howtodoinjava.com/spring-data/spring-boot-redis-with-lettuce-jedis/>
- <https://github.com/redis/lettuce/wiki/Connection-Pooling>
- <https://redis.github.io/lettuce/advanced-usage/client-options/>
- <https://redis.github.io/lettuce/advanced-usage/connection-pooling/>
- <https://blog.csdn.net/u014495560/article/details/103576786>
- <https://www.man7.org/linux/man-pages/man7/socket.7.html>
- <https://www.man7.org/linux/man-pages/man7/tcp.7.html>
- <https://www.postgresql.org/docs/18/runtime-config-connection.html>
- <https://www.postgresql.org/docs/18/libpq-connect.html>
- <https://linuxvox.com/blog/what-is-the-reason-and-how-to-avoid-the-fin-ack-rst-and-rst-ack/>
- <https://docs.oracle.com/cd/E13189_01/kodo/docs324/ref_guide_dbsetup.html>
