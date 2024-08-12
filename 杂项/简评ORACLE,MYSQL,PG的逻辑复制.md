## postgresql逻辑复制
​​​​![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/a08ca737a2394f822852afd725acb1ca.png)
（https://www.pgconf.asia/JA/2017/wp-content/uploads/sites/2/2017/12/D2-A7-EN.pdf）

PostgreSQL把所有逻辑解析相关的事情全部放在数据库中的复制槽进行管理，大包大揽。早期版本的逻辑复制支持的还不太好，近期的几个大版本中，逻辑复制是主要的功能提升之一。
PG方案的优势：
 - 非常灵活，把逻辑解码接口提供给用户，有多种类的解析方式
 - 用户可根据需求订阅所需要的数据

PG方案的劣势：
 - 知识点多学习成本相对MYSQL要高很多。仅仅是基础知识点：发布、订阅、walsender、复制槽、output plugin等等，我相信很多人没有弄明白他们概念和关系
 - 干最累的活挨最毒的打。逻辑解析的问题全部暴露在数据库中，wal积压、大事物、长事务、reorder事务排序、权限问题、流式传输等等都是PG要考虑的问题

## mysql的binlog
![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/c73818768535ffcbd6f2ba77a407901a.png)
(https://blog.fasterinfo.top/6243.html)

mysql把所有解析出来的逻辑数据放在本地——binlog文件中，方案简单。*mysql的binlog约等于PostgreSQL开启全表逻辑复制并写入本地*。
MYSQL方案的优势：
 - 简单粗暴，mysql不把逻辑解码接口直接暴露给用户，而是把已解析出来的文件直接给到用户，用户不需要关心怎么解析的，直接读binlog文件即可
 - 生态成熟。个人认为mysql生态成熟跟binlog有较大关系，在互联网时代PG的逻辑复制还很弱，而binlog十分简单，下游解析binlog把数据放到其他平台已成为一种常见方案

MYSQL方案的劣势：
 - 数据必须全部解析，不可定制化订阅数据，灵活性差
 - 两阶段提交。由于mysql主从强依赖binlog，又导致binlog数据在提交的时候必须全部落盘到binlog file，一次提交必须写两份（或者两种）日志——binlog和redolog，日志双写是mysql永恒的痛点之一。

## oracle的逻辑复制
![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/e03f0d5a01db5b4b21965ce96f65f955.png)
（https://www.oracle-scn.com/oracle-goldengate-integrated-capture/）

oracle本身是有逻辑DG的功能的，但基本上没见有人用过，这里只聊logminer 。oracle数据库本身提供了logminer这样的接口来解析日志（如OGG集成模式），逻辑复制链路管理本身完全没有，依赖第三方工具来创建和管理复制链路
ORACLE方案的优势：
 - 只提供解析接口，没有复制链路管理，对于数据库本身来说非常省心
 - 充值就有方案。把强大的OGG直接买下来，不要说我ORACLE没有提供逻辑复制解决方案，我们不仅有，而且很强大、认可度高。

ORACLE方案的劣势：
 - 依赖第三方软件管理复制链路


总之，PG的逻辑复制是大包大揽什么都做，非常有开源精神、技术精神。MYSQL的方案简单粗暴但好用，有点“一步到位”的意思。ORACLE属于给个接口后就什么都不管，全部给第三方管理，但对于客户来说是有成熟的解决方案的。
