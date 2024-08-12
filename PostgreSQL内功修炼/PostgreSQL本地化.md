# 本地化的概念

本地化的目的是支持不同国家、地区的语言特性、规则。比如拥有本地化支持后，可以使用支持汉语、法语、日语等等的字符集。除了字符集以外，还有字符排序规则和其他语言相关规则的支持，例如我们知道('a','b')该如何排序，那么('a','A')和('啊','阿')又该如何排序？
如果通过google去搜本地化、字符集、collation相关信息，可能会得到一些复杂又遥远的知识。最好的老师还是![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/a597665c1c88647293c734f3d6050ea7.png)


本地化知识点总共分为3个部分：locale本地化支持、collation校验、字符集。


# locale

pg的本地化由由操作系统提供，需要检查操作系统是否支持`locale -a`。在初始化数据库时可指定locale

```shell
initdb --locale=en_US
```

也可以单独设置本地化子类：字符串排序、字符归类方法、数值格式、日期格式、时间格式、货币格式等

```shell
initdb --locale=zh_CN --lc-monetary=en_US
```

所有本地化子类：

| 本地化子类  | 规则                                                         |
| ----------- | ------------------------------------------------------------ |
| LC_COLLATE  | String sort order                                            |
| LC_CTYPE    | Character classification (What is a letter? Its upper-case equivalent?) |
| LC_MESSAGES | Language of messages                                         |
| LC_MONETARY | Formatting of currency amounts                               |
| LC_NUMERIC  | Formatting of numbers                                        |
| LC_TIME     | Formatting of dates and times                                |

这些子类又可以分为两部分，其中lc_messages，lc_monetary，lc_numeric，lc_time在初始化后，可以通过参数进行调整。LC_COLLATE，LC_CTYPE属于collation，详见collation的调整。
locale设置会影响如下行为：

-   Sort order in queries using `ORDER BY` or the standard comparison operators on textual data
-   The `upper`, `lower`, and `initcap` functions
-   Pattern matching operators (`LIKE`, `SIMILAR TO`, and POSIX-style regular expressions); locales affect both case insensitive matching and the classification of characters by character-class regular expressions
-   The `to_char` family of functions
-   The ability to use indexes with `LIKE` clauses




# COLLATION

collation是字符排序的顺序和字符分类行为。一些数据库操作符依赖collation，比如order by、lower, upper、initcap 、to_char等等。
使用如下SQL查询系统表pg_collation，来获取字符集支持的LC_COLLATE和LC_CTYPE信息

```sql
 select pg_encoding_to_char(collencoding) as encoding,collname,collcollate,collctype from pg_collation where collname in ('default','C','POSIX','en_US.utf8','zh_CN.utf8','zh_CN.gb2312','zh_SG.gb2312') ;
 encoding |   collname   | collcollate  |  collctype   
----------+--------------+--------------+--------------
          | default      |              | 
          | C            | C            | C
          | POSIX        | POSIX        | POSIX
 UTF8     | en_US.utf8   | en_US.utf8   | en_US.utf8
 EUC_CN   | zh_CN.gb2312 | zh_CN.gb2312 | zh_CN.gb2312
 UTF8     | zh_CN.utf8   | zh_CN.utf8   | zh_CN.utf8
 EUC_CN   | zh_SG.gb2312 | zh_SG.gb2312 | zh_SG.gb2312
```

encoding是字符集，collname为collation的名字

 - encoding 为空时，表示这个 collation 支持所有的字符集
 - `default`, `C`, `POSIX`是所有平台都支持的collation，由`libc`提供，其他collation取决于操作系统是否支持(`locale -a`)
 - default表示使用建库时的collation，可通过\l查看
 - `C`语义上等价于`POSIX`，但是PG仍然认为他们是不同的collation。他们的字符都以ASCII码对比，严格按照字节序比对大小。

```sql
=> SELECT 'a' COLLATE "C" < 'b'  COLLATE "POSIX" ;
ERROR:  42P21: collation mismatch between explicit collations "C" and "POSIX"
LINE 1: SELECT 'a' COLLATE "C" < 'b'  COLLATE "POSIX" ;
LOCATION:  merge_collation_state, parse_collate.c:834
```

 - UTF8是最常见的字符集，我们最常见的语言环境是en_US和zh_CN
 - 可以通过`CREATE COLLATION ...`创建自定义的collation。不过LC_COLLATE和LC_CTYPE不同的情况非常少见

## LC_COLLATE

LC_COLLATE影响字符比对（排序、字符操作等等）
collate子句可以转化表达式的collation：

```sql
expr COLLATE collation
```

注意这里指定的是collation，不是lc_collate。如果没有显示指定collation，数据库默认使用字段的collation，如果字段没有指定collation，使用database的默认collation。

不同的collation排序测试：

```sql
 select col1 from (values ('a'), ('A'), ('啊'), ('阿')) 
->  AS l(col1)
-> order by col1 collate "C";
 col1 
------
 A
 a
 啊
 阿
 select col1 from (values ('a'), ('A'), ('啊'), ('阿')) 
->  AS l(col1)
-> order by col1 collate "en_US.utf8";
 col1 
------
 a
 A
 啊
 阿
  select col1 from (values ('a'), ('A'), ('啊'), ('阿')) 
->  AS l(col1)
-> order by col1 collate "zh_CN.utf8";
 col1 
------
 a
 A
 阿
 啊
```

这3个不同的collation有不同的lc_collate，排序方法应该是不一样的，从结果来看确实是不一样的，出现了3种排序结果。
**collation C为什么A<a?**
collation C使用的ASCII的编码顺序，ASCII码中大写在小写前面。而en_US.utf8和zh_CN.utf8的英文字母明显不是这个顺序
**中文的顺序**
同样是utf8字符集，中文环境和英文环境的中文顺序不一样。不同的lc_collate对于不同本地化语言，应该都可以对应到不同的alphabets。其中，lc_collate=C的排序一定是按字节序排的，虽然ASCII没有中文，但是C也可以排序中文，（基本）每个中文都可以对应UTF8的一个编码，而C以其字节序排序。

## LC_CTYPE

LC_CTYPE影响字符操作（如upper、initcap等）
如果字符串都是英文，比如是'abcD'，initcap在3种collation下都会转换为'Abcd'，这里不多展示了。
但是加入中文，结果就不一样了：

```sql
select initcap('啊aAAa阿bBBb' collate "C");
   initcap    
--------------
 啊Aaaa阿Bbbb

select initcap('啊aAAa阿aAAa' collate "en_US.utf8");
   initcap    
--------------
 啊aaaa阿aaaa

select initcap('啊aAAa阿aAAa' collate "zh_CN.utf8");
   initcap    
--------------
 啊aaaa阿aaaa
```

LC_CTYPE=C时，initcap把每个非连续英文字符串的首字母大写，而en_US.utf8和zh_CN.utf8只会将首个字符大写（中文就不会变），其他英文字符小写。
initcap中文也许处于需求不明的状况，但是我们可以得出结论：**不同的LC_CTYPE会导致initcap等字符敏感函数结果不一样**。
另外，中文对于大小写不敏感，一些其他本地化语言同样有大小写，不同的LC_CTYPE导致的结果会更复杂。




# 字符集
## 字符集基础

PostgreSQL支持不同的字符集character sets（也叫encodings）。字符集于collation是两个概念，但是字符集必须跟LC_CTYPE，LC_COLLATE兼容。就像在pg_collation中看到的那样，C/POSIX支持所有字符集，而其他collation只支持一种字符集（linux系统中）。

PostgreSQL中文相关可用的字符集：
*(\*collation C由libc库提供，部分collation可以由ICU库提供，需提前编译)*

| Name    | Description                | Language | Server端是否支持? | ICU是否支持? | Bytes/Char | Aliases            |
| ------- | -------------------------- | -------- | ----------------- | ------------ | ---------- | ------------------ |
| BIG5    | Big Five                   | 繁体中文 | No                | No           | 1–2        | WIN950, Windows950 |
| EUC_CN  | Extended UNIX Code-CN      | 简体中文 | Yes               | Yes          | 1–3        | GB2312             |
| GB18030 | National Standard          | 中文     | No                | No           | 1–4        |                    |
| GBK     | Extended National Standard | 简体中文 | No                | No           | 1–2        | WIN936, Windows936 |
| UTF8    | Unicode, 8-bit             | all      | Yes               | Yes          | 1–4        | Unicode            |

**繁体中文**：
[BIG5](https://baike.baidu.com/item/%E5%A4%A7%E4%BA%94%E7%A0%81/2413431?fr=ge_ala)是最常见的繁体中文字符集标准。之前是业界标准，后来被录入为国家标准。
**简体中文**：
GB是国标的意思，GB2312、GB18030、GBK都是我国的国家字符集标准。由于生僻字等问题，并经过多年发展产生了一些历史版本，所以标准看上去有多个。
其中[EUC_CN](https://baike.baidu.com/item/EUC-CN/4514294?fr=ge_ala)全称为 Extended UNIX Code-CN ，其实就是[GB2312](https://baike.baidu.com/item/%E4%BF%A1%E6%81%AF%E4%BA%A4%E6%8D%A2%E7%94%A8%E6%B1%89%E5%AD%97%E7%BC%96%E7%A0%81%E5%AD%97%E7%AC%A6%E9%9B%86/8074272?fromModule=lemma_inlink&fromtitle=GB2312&fromid=483170)，但它也不能处理所有罕见字。类似命名的还有EUC_KR,EUC_JP,EUC_TW等等。
**国际标准**：
上面的字符集都是国家标准，他们除了支持英、中外不支持其他语言。而国际标准支持世界上所有语言，这就是[unicode](https://home.unicode.org/)国际编码标准(甚至emoji也包含其中 :+1:)。（还有个著名的国际标准组织ISO也在维护字符集，他俩有交集，这里先忽略ISO）。
由于Unicode编码方案的不同又有UTF-8、UTF-16、UTF-32三种编码方式。

UTF-8编码格式:

| 字节  | 格式                                | 实际编码位 | 码点范围        |
| ----- | ----------------------------------- | ---------- | --------------- |
| 1字节 | 0xxxxxxx                            | 7          | 0 ~ 127         |
| 2字节 | 110xxxxx 10xxxxxx                   | 11         | 128 ~ 2047      |
| 3字节 | 1110xxxx 10xxxxxx 10xxxxxx          | 16         | 2048 ~ 65535    |
| 4字节 | 11110xxx 10xxxxxx 10xxxxxx 10xxxxxx | 21         | 65536 ~ 2097151 |

UTF8编码是变长的。
0x00-0x7F之间的字符(1字节），UTF-8编码与ASCII（American Standard Code for Information Interchange 美国标准信息交换代码）编码完全相同，所以UTF-8是完全兼容ASCII的。
由于同源、同义、相似性，在unicode中中日韩越使用了同一编码，称为[中日韩统一表意文字（或称中日韩越统一表意文字）](https://baike.baidu.com/item/%E4%B8%AD%E6%97%A5%E9%9F%A9%E8%B6%8A%E7%BB%9F%E4%B8%80%E8%A1%A8%E6%84%8F%E6%96%87%E5%AD%97/1301611?fromModule=lemma_inlink)。
中日韩统一表意文字编码范围为：3400-4DBF/4E00-9FFF/20000-3FFFF
![](https://i-blog.csdnimg.cn/blog_migrate/984857cd9afec1a67d5c034de8aa5a91.png)



## 字符集转换

server_encoding与client_encoding不一致，可发生自动转换Server查出来的字符集。设置服务端字和客户端字符集参考设置字符集一节。
中文相关字符集Server/Client可转化表：

| Server Character Set                                         | Available Client Character Sets                 |
| ------------------------------------------------------------ | ----------------------------------------------- |
| BIG5                                                         | _not supported as a server encoding_            |
| **EUC_CN（GB2312）**                                         | **_EUC_CN_（GB2312）, `MULE_INTERNAL`, `UTF8`** |
| GB18030                                                      | _not supported as a server encoding_            |
| GBK                                                          | _not supported as a server encoding_            |
| **UTF8**                                                     | **_all supported encodings_**                   |
| GB18030，GBK服务端都不支持，所以其实只有EUC_CN（GB2312）、UTF8能在Server/Client转换。 |                                                 |

以上是可以转换的字符集，仍需要CONVERSATION的支持。PG内置了一些转换函数，可通过`pg_conversion`查看：

| Conversion Name    | Source Encoding | Destination Encoding |
| ------------------ | --------------- | -------------------- |
| big5_to_utf8       | BIG5            | UTF8                 |
| **euc_cn_to_utf8** | **EUC_CN**      | **UTF8**             |
| gb18030_to_utf8    | GB18030         | UTF8                 |
| gbk_to_utf8        | GBK             | UTF8                 |
| utf8_to_big5       | UTF8            | BIG5                 |
| **utf8_to_euc_cn** | **UTF8**        | **EUC_CN**           |
| utf8_to_gb18030    | UTF8            | GB18030              |
| utf8_to_gbk        | UTF8            | GBK                  |

可通过`create conversation`语句创建自定义的转换，需指定转换的function。
有些字符集间看上去可以转换，但是server端根本不支持存储这些字符集（如big5、gb18030、gbk），所以也没啥用。我们这里仅需要知道euc_cn和utf8能相互转换就可以了。
没有CONVERSATION是不能发生转换的：

```sql
--EUC_CN的database
=> \encoding EUC_KR
EUC_KR: invalid encoding name or conversion procedure not found
```

**字符集转换测试**：
*需要注意客户端的字符集设置（如CRT的 "session"-"Appearance"-"Character encoding"）*
*至少*有3个端有字符集的概念：数据库server、数据库client、UI客户端。CONVERSATION也只能控制：数据库server -> 数据库client
1.server为UTF8的转换测试：

```sql
create table zh(col1 varchar(20));
insert into zh values('>'),('阿'),('〇');  --〇 ling是一个中文
--CRT不设置为UTF8中文全是乱码，只有CRT设置UTF8来插入

=> show server_encoding;
 server_encoding 
-----------------
 UTF8
=> show client_encoding;
 client_encoding 
-----------------
 UTF8
--完全没有转换的情况下，UTF8正常展示。此时3端字符集为：UTF8 - UTF8 - UTF8
=> select * from  zh;
 col1 
------
 >
 阿
 〇

--切换数据库client字符集，此时3端字符集为：UTF8 - EUC_CN - UTF8
=> \encoding EUC_CN;  --设置客户端字符集

=> select * from zh where col1 in ('阿');
ERROR:  22021: invalid byte sequence for encoding "EUC_CN": 0xe9 0x98
LOCATION:  report_invalid_encoding, mbutils.c:1597
Time: 0.112 ms
=>  select * from zh where col1 in ('〇');
ERROR:  22021: invalid byte sequence for encoding "EUC_CN": 0xe3 0x80
ERROR:  22021: invalid byte sequence for encoding "EUC_CN": 0xe3 0x80
--“阿”和“〇”看上去不能转换为EUC_CN，但不是这样的
 
=>  select * from zh limit 2;
 col1 
------
 >
 <B0><A2>
(2 rows)
--第二行即是"阿"，数据库server/client看上去转换了字符集，从UTF8转换为了EUC_CN
--但是可能是因为UI客户端问题没有正确显示（此时UI客户端CRT为UTF8）

--然而把CRT改成GB2312还是不会正确展示
select * from zh limit 2;
 col1 
------
 >
 <B0><A2>
(2 rows)

--当查询〇时，数据库直接抛出报错，说明〇不能从UTF8转换为EUC_CN
select * from zh ;
ERROR:  22P05: character with byte sequence 0xe3 0x80 0x87 in encoding "UTF8" has no equivalent in encoding "EUC_CN"
LOCATION:  report_untranslatable_char, mbutils.c:1631
```

2.server为EUC_CN的转换测试：

 ```sql
=> show server_encoding; --database为EUC_CN字符集
 server_encoding 
-----------------
 EUC_CN
 
--在EUC_CN库下同样创建一个zh表，此时尝试插入就有问题了 
=> insert into zh values('〇');
ERROR:  22P05: character with byte sequence 0xe3 0x80 0x87 in encoding "UTF8" has no equivalent in encoding "EUC_CN"
LOCATION:  report_untranslatable_char, mbutils.c:1631
 ```

同样报错〇不能从UTF8转换为EUC_CN。EUC_CN（GB2312）中文编码不完全与UTF8相同，EUC_CN（GB2312）不是所有中文都包含的，特别是罕见字。







# 设置locale、collation和字符集

上面已经了解过本地化和字符集设置了，这里做一个汇总

## database cluster的locale、collation、字符集

初始化时可设置database cluster的locale和字符集，参考：

```shell
initdb -D $DATADIR -E UTF8 --locale=en_US.UTF8 
initdb -D $DATADIR -E UTF8 --locale=en_US.UTF8 --lc_collate=C --lc_ctype=C
initdb -D $DATADIR -E UTF8 --locale=en_US.UTF8 --lc_collate=C --lc_ctype=C --lc-messages=en_US.UTF8 --lc-monetary=en_US.UTF8 --lc-numeric=en_US.UTF8 --lc-time=en_US.UTF8
```

`initdb`会创建postgres，template1，和template0三个库。`create database`语句时默认使用template1创建库。

- encoding设置字符集；locale设置LC_COLLATE，LC_CTYPE，LC_MESSAGES，LC_MONETARY，LC_NUMERIC，LC_TIME，除非特别指定（如--lc_collate）

- LC_COLLATE，LC_CTYPE称为collation，还可在database、列、索引上设置。LC_MESSAGES，LC_MONETARY，LC_NUMERIC，LC_TIME为实例参数，可随时修改。

- encoding只能在初始化、创建database时设置，一旦设置不可修改。

## database的collation、字符集

创建database时可设置database的字符集、lc_collate、lc_ctype。

create database ,createdb都可以在创建database时指定字符集，一旦创建就不能修改database的字符集。两个命令都是使用template库来创建database

template又有template0和template1，官方文档有这样一句话：

>Another common reason for copying `template0` instead of `template1` is that new encoding and locale settings can be specified when copying `template0`, whereas a copy of `template1` must use the same settings it does. This is because `template1` might contain encoding-specific or locale-specific data, while `template0` is known not to.

template1是可写数据的模板库，可能包含本地化过的数据，而template0不能写数据，所以要创建不同的本地化库应使用template0。

而且要显示使用template0，因为不指定的话默认是template1。所以在创建database时没有指定template1且指定其他字符集会报错：

```sql
=> create database db_GB2312 ENCODING 'EUC_CN'  LC_COLLATE 'zh_CN.gb2312' LC_CTYPE 'zh_CN.gb2312';
ERROR:  22023: new encoding (EUC_CN) is incompatible with the encoding of the template database (UTF8)
HINT:  Use the same encoding as in the template database, or use template0 as template.
```


另外，不能在创建database时通过指定locale来设置字符集

```sql
=> create database db_GB2312 locale 'zh_CN.gb2312' template 'template0';
ERROR:  22023: encoding "UTF8" does not match locale "zh_CN.gb2312"
DETAIL:  The chosen LC_CTYPE setting requires encoding "EUC_CN".
LOCATION:  check_encoding_locale_matches, dbcommands.c:773
```

报错表示需要指定LC_CYTPE子选项，把collation相关子选项全部加上仍然报错：

```sql
=> create database db_GB2312 LOCALE 'EUC_CN'  LC_COLLATE 'zh_CN.gb2312' LC_CTYPE 'zh_CN.gb2312';
ERROR:  42601: conflicting or redundant options
DETAIL:  LOCALE cannot be specified together with LC_COLLATE or LC_CTYPE.
```

LOCALE又不能跟LC_CTYPE等子选项一起使用
然后把locale去掉，通过设置字符集、LC_COLLATE、LC_CTYPE 来设置，可以成功。

**创建指定字符集的database的正确姿势**：

- create database

```sql
create database db_GB2312 ENCODING 'EUC_CN'  LC_COLLATE 'zh_CN.gb2312' LC_CTYPE 'zh_CN.gb2312' template 'template0';
```

- createdb
  通过cli命令createdb来创建，createdb封装了create database，他俩是等价的：

```shell
 createdb -E EUC_CN -T template0 --lc-collate=zh_CN.gb2312 --lc-ctype=zh_CN.gb2312 db_GB2312
```



**查看database字符集：**

1. `\l`

2. `pg_database`

```sql
select datname,pg_encoding_to_char(encoding),datcollate,datctype,datlocprovider,daticulocale from pg_database;
```

3. show参数

`SERVER_ENCODING`,`LC_COLLATE`,`LC_CTYPE`三个参数都是不可更改的，分别展示*当前*database的server端字符集、LC_COLLATE、LC_CTYPE



## 列的collation

collation只跟字符排序、字符函数相关，跟编码不相关。在没有索引的情况下，修改列的collation相当于只是在调整这个列的default排序输出，有索引的情况下会重建索引。不指定列的collation默认与database一致。

建表时指定collation：（注意有些字段类型是un-collatable的，比如int）

```sql
create table t1(col1 varchar(10) collate "en_US.utf8");
alter table t1 alter column col1 type varchar(10) collate "C";
```

*注意：alter table不修改长度是不会重建表的，但是一定会重建索引*



**查看列的默认collation**：

```sql
1. \d+ t1

2. information_schema.columns
select table_catalog,table_schema,table_name,column_name,collation_name from  information_schema.columns where table_name='t1';

3. pg_attribute
select a.attrelid::regclass,a.attname,a.attcollation,c.collname,c.collcollate,c.collctype from pg_attribute a left join pg_collation c on a.attcollation=c.oid  where a.attrelid::regclass='tlzl'::regclass and a.attcollation<>0;
```

推荐方式3查看。\d+ ,information_schema.columns虽然能看到collname，但是collname不是唯一的。只有方式3可以看到collate,ctype



**指定collate和查看pg_attribute的测试：**

```sql
create table tlzl(
  col1 varchar(10) ,
  col2 varchar(10) collate "C",
  col3 varchar(10) collate "zh_CN",
  col4 varchar(10) collate "en_US.utf8"
);
```

```sql
 --列的collation相当于给列打上默认排序的标记，也看不到具体是哪个collate和ctype
db_utf8_c=>                                          Table "public.tlzl"
 Column |         Type          | Collation  | Nullable | Default | Storage  | Compression | Stats target | Description 
--------+-----------------------+------------+----------+---------+----------+-------------+--------------+-------------
 col1   | character varying(10) |            |          |         | extended |             |              | 
 col2   | character varying(10) | C          |          |         | extended |             |              | 
 col3   | character varying(10) | zh_CN      |          |         | extended |             |              | 
 col4   | character varying(10) | en_US.utf8 |          |         | extended |             |              | 
--collname和collate，ctype不是一一对应的，上面的col3 zh_CN看不出来collate是哪个
db_utf8_c=> select pg_encoding_to_char(collencoding) as encoding,collname,collcollate,collctype from pg_collation where collname like 'zh_CN%';
 encoding |   collname   | collcollate  |  collctype   
----------+--------------+--------------+--------------
 EUC_CN   | zh_CN        | zh_CN        | zh_CN
 EUC_CN   | zh_CN.gb2312 | zh_CN.gb2312 | zh_CN.gb2312
 UTF8     | zh_CN.utf8   | zh_CN.utf8   | zh_CN.utf8
 UTF8     | zh_CN        | zh_CN.utf8   | zh_CN.utf8
 
--pg_attribute展示比\d+准确
db_utf8_c=> select a.attrelid::regclass,a.attname,a.attcollation,c.collname,c.collcollate,c.collctype from pg_attribute a left join pg_collation c on a.attcollation=c.oid  where a.attrelid::regclass='tlzl'::regclass and a.attcollation<>0;
 attrelid | attname | attcollation |  collname  | collcollate | collctype  
----------+---------+--------------+------------+-------------+------------
 tlzl     | col1    |          100 | default    |             | 
 tlzl     | col2    |          950 | C          | C           | C
 tlzl     | col4    |        12562 | en_US.utf8 | en_US.utf8  | en_US.utf8
 tlzl     | col3    |        13200 | zh_CN      | zh_CN.utf8  | zh_CN.utf8
--此时才知道，col3 zh_CN的collate是zh_CN.utf8 
```

**修改列的collate重写测试：**

```sql
--给字段加索引，看看重写情况
db_utf8_c=> create index idxcol4 on tlzl(col4);
CREATE INDEX

db_utf8_c=>  select pg_relation_filepath('tlzl') TableRelid, pg_relation_filepath('idxcol4') IndexRelid; 
    tablerelid    |    indexrelid    
------------------+------------------
 base/40996/41006 | base/40996/41015

db_utf8_c=> alter table tlzl alter column col4 type varchar(10) collate "C";
ALTER TABLE
db_utf8_c=> select pg_relation_filepath('tlzl') TableRelid, pg_relation_filepath('idxcol4') IndexRelid; 
    tablerelid    |    indexrelid    
------------------+------------------
 base/40996/41006 | base/40996/41016
--表没有重写，索引重写了
```

列的collation只是标记，修改列的collation不会重写表，但是如果其上有索引，那么会重写这个索引（有时候不会见下面一节）。



## 索引的collation

在创建索引时，如不显示指定索引的collation，那么索引会使用列上声明的collation。

创建索引时显示使用collation：

```sql
create index idx_C on tlzl(col3 collate "C");  
```

另外，索引还可以以text_pattern_ops，varchar_pattern_ops，bpchar_pattern_ops来创建，此时的索引不依赖collation的规则，而是一个字符一个字符的对比

> The difference from the default operator classes is that the values are compared strictly character by character rather than according to the locale-specific collation rules.

```sql
CREATE INDEX test_index ON test_table (col varchar_pattern_ops);
```

其实这种索引跟collation不是完全无关，索引一定有一个排序规则，这种索引的排序规则看上去跟C一致。参考like不走索引一节



**查看索引的collation:**

```sql
\d+ --\d+会展示指定过collate的索引，如果没有的话使用的是列默认索引
db_utf8_c=> \d+ tlzl
                                                  Table "public.tlzl"
 Column |         Type          | Collation  | Nullable | Default | Storage  | Compression | Stats target | Description 
--------+-----------------------+------------+----------+---------+----------+-------------+--------------+-------------
 col1   | character varying(10) |            |          |         | extended |             |              | 
 col2   | character varying(10) | C          |          |         | extended |             |              | 
 col3   | character varying(10) | zh_CN      |          |         | extended |             |              | 
 col4   | character varying(10) | en_US.utf8 |          |         | extended |             |              | 
Indexes:
    "idx_c" btree (col3 COLLATE "C")
    "idxcol4" btree (col4)
Access method: heap


```

通过pg_index查看更为清晰:（pg_index的indcollation类型是oidvector的，不能直接转化为oid，查起来麻烦点）

```sql
db_utf8_c=>  select indcollation,indexrelid::regclass from pg_index where indexrelid::regclass ='idx_C'::regclass;
 indcollation | indexrelid 
--------------+------------
 950          | idx_c

db_utf8_c=> select oid,pg_encoding_to_char(collencoding) as encoding,collname,collcollate,collctype from pg_collation where oid=950;
 oid | encoding | collname | collcollate | collctype 
-----+----------+----------+-------------+-----------
 950 |          | C        | C           | C
```

*另外，不能通过alter index改变索引的collation，只能删除重建*



**测试：指定过索引collate后，修改列的collate是否会重写索引？**

```sql
db_utf8_c=> select pg_relation_filepath('tlzl') TableRelid, pg_relation_filepath('idxcol4') IndexRelid4,pg_relation_filepath('idx_c') IndexRelidC; 
    tablerelid    |   indexrelid4    |   indexrelidc    
------------------+------------------+------------------
 base/40996/41020 | base/40996/41023 | base/40996/41024
(1 row)

db_utf8_c=> alter table tlzl alter column col3 type varchar(10) collate "en_US.utf8";
ALTER TABLE
db_utf8_c=> select pg_relation_filepath('tlzl') TableRelid, pg_relation_filepath('idxcol4') IndexRelid4,pg_relation_filepath('idx_c') IndexRelidC; 
    tablerelid    |   indexrelid4    |   indexrelidc    
------------------+------------------+------------------
 base/40996/41020 | base/40996/41023 | base/40996/41024   --idx_c的relfileid没有变
```

如果指定过索引的collate，修改其字段默认collate，不会重新索引。



## 客户端的字符集

客户端设置与database不同的字符集，会发生字符集转换，也可能转换不成功，具体参考字符集转换一节。

服务端的字符集在创建database后无法改变，client的字符集可随时调整。

Client字符集设置方法很多：

 - 直接在客户端设置

```sql
\encoding UTF8  --仅psql支持
SET CLIENT_ENCODING TO UTF8;  --session级修改参数
SET NAMES UTF8;  --sql标准
```

 - 设置环境变量PGCLIENTENCODING
 - 设置client_encoding服务端配置参数

优先级：客户端设置>环境变量PGCLIENTENCODING>client_encoding服务端配置参数

**查看client字符集：**

```sql
\encoding   --仅psql支持
SHOW client_encoding;
```



## 表达式collate

表达式加collate会覆盖表达式原本的collation，相当于指定了排序collation。

需在表达式的最后加collate关键字：

```sql
expr COLLATE collation

--例如
select * from tab1 order by name COLLATE "C";
```

排序和collate索引选择详见排序结果问题一节。



# MORE




## 概念整理

PostgreSQL本地化有三个重要概念：字符集、locale、collation，需要弄清他们的关系。

字符集在服务端的设置非常重要，只能在初始化和建db时指定，建库后不可修改。字符集选择直接影响编码方式，collation并不是，但是他俩之间有依赖关系。locale同样可以在初始化时指定，其中collation可在建库时指定，也可以单独指定列的collation，注意他们只是默认值。只有在建索引时指定collation，会影响其真正的存储顺序。不同的collation是无法使用索引的，即使他们同源。

client字符集和LC_MASSAGES等4个参数都比较简单，可直接修改参数，与数据存储无关。

![在这里插入图片描述](https://i-blog.csdnimg.cn/blog_migrate/ee37f4d3aa8aa82eef78f1453c33b965.png)









## 排序结果问题

因为utf8是最常见的字符集，我们测试utf相关的collation排序

```sql
create database db_UTF8 ENCODING 'UTF8'  template 'template0';  --建一个UTF8的库，collation无所谓
use db_UTF8;
create table tzlz(name varchar(10));
insert into tzlz values('a'),('aa'),('A'),('AA'),('啊'),('阿'),('〇');
```

不同collation的order by结果：

```sql
select name from tzlz where name in ('a','aa','A','AA','啊','阿','〇') order by name;
select name from tzlz where name in ('a','aa','A','AA','啊','阿','〇') order by name collate "C";
select name from tzlz where name in ('a','aa','A','AA','啊','阿','〇') order by name collate "en_US";
select name from tzlz where name in ('a','aa','A','AA','啊','阿','〇') order by name collate "en_US.utf8";
select name from tzlz where name in ('a','aa','A','AA','啊','阿','〇') order by name collate "zh_CN";
select name from tzlz where name in ('a','aa','A','AA','啊','阿','〇') order by name collate "zh_CN.utf8";
```



| 顺序 | default | C    | en_US | en_US.utf8 | zh_CN | zh_CN.utf8 |
| ---- | ------- | ---- | ----- | ---------- | ----- | ---------- |
| 1    | 〇      | A    | 〇    | 〇         | a     | a          |
| 2    | a       | AA   | a     | a          | A     | A          |
| 3    | A       | a    | A     | A          | aa    | aa         |
| 4    | aa      | aa   | aa    | aa         | AA    | AA         |
| 5    | AA      | 〇   | AA    | AA         | 阿    | 阿         |
| 6    | 啊      | 啊   | 啊    | 啊         | 啊    | 啊         |
| 7    | 阿      | 阿   | 阿    | 阿         | 〇    | 〇         |

*这里的default是en_US.utf8（字段collation(default)->database collation(en_US.utf8)）*

:star2: **C、en_US.uft8、zh_CN.uft8排序结果都不同**



**collate和索引扫描测试：**

```sql
insert into tzlz values(generate_series(1,10000));
create index idxzlz_default on tzlz(name);
create index idxzlz_C on tzlz(name collate "C");
create index idxzlz_enUS_utf8 on tzlz(name collate "en_US.utf8");
```

使用collate在索引上的优化：

```sql
--不加任何collate关键字，简单的索引扫描，不会额外排序
db_utf8_c=> explain select name from tzlz where name in ('a','aa','A','AA','啊','阿','〇') order by name;
                                   QUERY PLAN                                    
---------------------------------------------------------------------------------
 Index Only Scan using idxzlz_default on tzlz  (cost=0.29..30.13 rows=8 width=4)
   Index Cond: (name = ANY ('{a,aa,A,AA,啊,阿,〇}'::text[]))

--谓词加collate转换，可以走到正确的索引
db_utf8=> explain select name  from tzlz  where name collate "C" in ('a','aa','A','AA','啊','阿','〇');
                                QUERY PLAN                                 
---------------------------------------------------------------------------
 Index Only Scan using idxzlz_c on tzlz  (cost=0.29..30.12 rows=7 width=4)
   Index Cond: (name = ANY ('{a,aa,A,AA,啊,阿,〇}'::text[]))

db_utf8=>  explain select name  from tzlz  where name collate "en_US.utf8" in ('a','aa','A','AA','啊','阿','〇');
                                    QUERY PLAN                                     
-----------------------------------------------------------------------------------
 Index Only Scan using idxzlz_enus_utf8 on tzlz  (cost=0.29..30.12 rows=7 width=4)
   Index Cond: (name = ANY ('{a,aa,A,AA,啊,阿,〇}'::text[]))
   
--但是collation的名字必须一致
db_utf8=> explain select name  from tzlz  where name collate "en_US" in ('a','aa','A','AA','啊','阿','〇');
                           QUERY PLAN                            
-----------------------------------------------------------------
 Seq Scan on tzlz  (cost=0.00..232.63 rows=7 width=4)
   Filter: ((name)::text = ANY ('{a,aa,A,AA,啊,阿,〇}'::text[]))
   
--同时order by也需要加collate转换表达式
--此时使用了正确的索引，但是order by的时候判断为不同的collation（哪怕他们是一样的）
db_utf8=>  explain select name  from tzlz  where name collate "en_US.utf8" in ('a','aa','A','AA','啊','阿','〇') order by name;
                                       QUERY PLAN                                        
-----------------------------------------------------------------------------------------
 Sort  (cost=30.22..30.23 rows=7 width=4)
   Sort Key: name
   ->  Index Only Scan using idxzlz_enus_utf8 on tzlz  (cost=0.29..30.12 rows=7 width=4)
         Index Cond: (name = ANY ('{a,aa,A,AA,啊,阿,〇}'::text[]))

--where和order by都加上collate转换，可以小选择正确的索引，且不会在发生排序
db_utf8=> explain select name  from tzlz  where name collate "en_US.utf8" in ('a','aa','A','AA','啊','阿','〇') order by name  collate "en_US.utf8";
                                     QUERY PLAN                                     
------------------------------------------------------------------------------------
 Index Only Scan using idxzlz_enus_utf8 on tzlz  (cost=0.29..30.12 rows=7 width=42)
   Index Cond: (name = ANY ('{a,aa,A,AA,啊,阿,〇}'::text[]))
```

**索引在指定collation后，sql需要显示使用collate关键字转换表达式，即便default与当前collation一致，pg也不会使用到索引。**



## like不走索引

> The drawback of using locales other than `C` or `POSIX` in PostgreSQL is its performance impact. It slows character handling and prevents ordinary indexes from being used by `LIKE`

PostgreSQL原话：使用非C or POSIX会阻止使用普通索引！

```sql
db_utf8=>  explain select name  from tzlz  where name  like 'a%';

                                QUERY PLAN                                
--------------------------------------------------------------------------

 Index Only Scan using idxzlz_c on tzlz  (cost=0.29..4.31 rows=1 width=4)
   Index Cond: ((name >= 'a'::text) AND (name < 'b'::text))
   Filter: ((name)::text ~~ 'a%'::text)
(3 rows)

db_utf8=>  explain select name  from tzlz  where name collate "en_US.utf8" like 'a%';

                                QUERY PLAN                                
--------------------------------------------------------------------------

 Index Only Scan using idxzlz_c on tzlz  (cost=0.29..4.31 rows=1 width=4)
   Index Cond: ((name >= 'a'::text) AND (name < 'b'::text))
   Filter: ((name)::text ~~ 'a%'::text)
```

PostgreSQL在索引扫描时把like转化为了>=和<，<还加了一个比输入的值大一号的值，这里就有问题了，collation跟排序强相关，ASCII码中a+1是b，但是汉字又如何？

```sql
db_utf8=> explain select name  from tzlz  where name collate "en_US.utf8" like '阿%';
                                QUERY PLAN                                
--------------------------------------------------------------------------
 Index Only Scan using idxzlz_c on tzlz  (cost=0.29..6.49 rows=1 width=4)
   Index Cond: ((name >= '阿'::text) AND (name < '陿'::text))
   Filter: ((name)::text ~~ '阿%'::text)
```

果然出现了另一个汉字！

如果是全表扫描，不会出现>=  <的情况

```sql
db_utf8=> drop index idxzlz_c;
DROP INDEX
db_utf8=>  explain select name  from tzlz  where name collate "en_US.utf8" like '阿%';
                      QUERY PLAN                      
------------------------------------------------------
 Seq Scan on tzlz  (cost=0.00..170.09 rows=1 width=4)
   Filter: ((name)::text ~~ '阿%'::text)
```



可以创建一个与collation规则无关的索引（pg官方声称无关）

```sql
CREATE INDEX idx_pattern ON tzlz (name varchar_pattern_ops);
```

来看看他的执行计划

```sql
db_utf8=> explain select name  from tzlz  where name like '阿%';

                                 QUERY PLAN                                  
-----------------------------------------------------------------------------

 Index Only Scan using idx_pattern on tzlz  (cost=0.29..6.49 rows=1 width=4)
   Index Cond: ((name ~>=~ '阿'::text) AND (name ~<~ '陿'::text))
   Filter: ((name)::text ~~ '阿%'::text)
```

他还是把大1号的字符串自己生成了，这跟collation一定是有关系的···，看上去就是C



所以可以得出结论：

**pg在like使用普通索引时，需要把其转换为>=  <，此时必须出现一个比当前字符串大1的值。而collation又与大小强相关，此时只能使用同一collation索引才能保证数据正确。pg选择了非本地化的collation C。**

临时解决这个问题最快的办法是新建一个collation C或pattern索引:

```sql
create index idxzlz_C on tzlz(name collate "C");
CREATE INDEX idx_pattern ON tzlz (name varchar_pattern_ops);
```

其他调整各级别的默认collation参考上面的章节。

*开发习惯在建索引时不会指定collation，如果不是C或pattern，都走不了like，在加上要选择国际字符集utf8，这样在数据库运维时选择的本地化方式就非常少了。字符集为utf8，collation为C*






# 参考

https://dbafix.com/what-is-the-impact-of-lc_ctype-on-a-postgresql-database/#:~:text=Having%20LC_CTYPE%20set%20to%20%E2%80%98C%E2%80%99%20implies%20that%20C,Postgres%20on%20top%20of%20these%20libc%20functions%2C%20they%E2%80%99re
https://www.postgresql.org/docs/current/charset.html
https://www.bookstack.cn/read/rds-best-pratice/bfc0037fe00d87dc.md
https://help.aliyun.com/zh/rds/apsaradb-rds-for-postgresql/configure-the-collation-of-a-database-on-an-apsaradb-rds-for-postgresql-instance
https://baike.baidu.com/item/%E7%BB%9F%E4%B8%80%E7%A0%81/2985798?fromModule=lemma_inlink&fromtitle=Unicode&fromid=750500
https://baike.baidu.com/item/%E4%B8%AD%E6%97%A5%E9%9F%A9%E8%B6%8A%E7%BB%9F%E4%B8%80%E8%A1%A8%E6%84%8F%E6%96%87%E5%AD%97/1301611?fromModule=lemma_inlink

https://blog.csdn.net/songyundong1993/article/details/128739919

