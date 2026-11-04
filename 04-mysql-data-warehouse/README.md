# 04 · 电商用户行为 MySQL 数据仓库（ODS→DWD→DWS→ADS + SCD2）

**1.0015 亿行原始日志**，用 MySQL 单机搭出四层数仓，含去重规则、时区修正、脏数据隔离、上下游对账、拉链表与指标口径文档。

## 为什么做这个

绝大多数数据分析简历上的「数据清洗」是 `pandas.dropna()`。真实数仓要解决的问题是另一套：

- 上游同一秒重复上报，聚合时会不会把 GMV 算两遍？
- 业务按北京时间算天，时间戳是 Unix 秒，切日错 8 小时会丢多少数据？
- 出问题时能不能说清「少了多少行、少在哪、为什么」？

这个项目把这些问题全部量化了。

## 数据与规模

| 项 | 值 |
|---|---|
| 原始行数 | **100,150,807** |
| 时间范围 | 2017-11-25 ~ 2017-12-03（9 天） |
| 用户数 | 987,991 |
| 原始文件 | 3.5 GB CSV（无表头，5 列） |
| 数据库 | MySQL 26.7，单机 |

## 结构

```
ODS  ods_user_behavior_raw     1.0015 亿  原样落地，不删不改
 ├─ dwd_dirty_rows                 55,576  ts 越界隔离区
DWD  dwd_user_behavior_di       1.0009 亿  四键去重 + 北京时间分区
DWS  dws_user_action_d          6,968,544  用户×日行为计数
     dws_traffic_d                     9  全站日流量
ADS  ads_funnel_d                      9  漏斗
     ads_retention                    63  cohort D0–D7 留存
     ads_rfm                     987,991  RFM 八档分层
     ads_category_cvr            全量类目  类目转化
DIM  dim_user_value_scd2         4,192,553  SCD2 拉链表（当前有效 966,977）
```

## 三个关键动作

**1. 去重——先立规则再跑数据**

```sql
ROW_NUMBER() OVER (
  PARTITION BY user_id, item_id, ts, behavior
  ORDER BY ts
) AS rn   -- 只保留 rn = 1
```

四键缺一不可：少 `behavior` 会误删「同秒既浏览又加购」，少 `ts` 会合并真实多次浏览。
实测只剔除 **49 行**（重复率 4.9e-7），但这套规则保证了换数据源不会翻车。

**2. 时区——一次差 8 小时，丢了 118 万行**

第一版 DWD 只有 98,914,484 行，比预期少 123 万。排查链条：NULL 为 0 → 窗口外行数 1,236,274 → 窗口定义不一致。

修复只需一行：

```python
CST = 8 * 3600
day_start = calendar.timegm(day.timetuple()) - CST
```

**3. 对账——三层闭合才叫平账**

```
100,150,807 (ODS)
 −    55,576 (ts 越界脏数据，隔离)
 −        49 (完全重复)
 = 100,095,182 (DWD)  ✅
```

只说「DWD 应该等于 ODS」会永远差一点，差一点就是一笔糊涂账。

## 性能排障（真踩过）

| 问题 | 现象 | 处理 |
|---|---|---|
| buffer pool 太小 | 按天整块 `ROW_NUMBER` 排序时 **MySQL 直接崩溃**：`Difficult to find free blocks in the buffer pool` | `innodb_buffer_pool_size` 128M → **6G**，按 **3 小时分批**去重（每批 130–170 万行），全程 56 分钟 |
| my.ini 带 BOM | PowerShell `Set-Content -Encoding UTF8` 写入 EF BB BF，MySQL 拒绝启动 | 用 `UTF8Encoding($false)` 写无 BOM，`mysqld --validate-config` 验证 |
| 重复率查询太慢 | 全表 `GROUP BY` 四键跑十几分钟 | 把重复统计**下推到 DWD 构建过程**，不在校验阶段重跑 |

## 文档

- [`METRICS.md`](./METRICS.md) —— 每个指标的定义、公式、口径边界，以及**这份数据算不了的 8 个指标**（GMV/客单价/退款率…）
- [`DQ_REPORT.md`](./DQ_REPORT.md) —— 数据质量校验报告：P0/P1/P2 分级、对账明细、可复现命令

**这两份文档才是这个项目的重点。** 代码谁都能写，能说清「哪些数字不能信、为什么」才是分析师的活。

## 产出示例（真实跑出来的）

| 指标 | 值 |
|---|---|
| 日均 PV / UV | 900–1230 万 / 71–97 万 |
| 购买转化率（用户级） | 17.9%–20.7%，9 天均值 **19.26%** |
| cohort D1 留存 | **78.87%** |
| 类目最高转化率 | **7.28%** |
| RFM 重要价值用户 | 143,363 |
| SCD2 价值版本段 | 4,192,553（人均 4.2 段） |

> 12-02/12-03 流量 +32%、D7 留存跳到 98.55%，是双十二预热效应。**校验报告必须能区分「脏数据」和「业务波动」**——把活动当 bug 修掉是典型初级错误。

## 复现

```bash
# 1. 装数据（需先把 CSV 放在本地，开启 local_infile）
python 01_ods_load.py       # ~11 分钟

# 2. 建 DWD（3 小时分批去重）
python 02_dwd_build.py      # ~56 分钟

# 3. 建 DWS / ADS / SCD2
python 03_dws_ads.py        # ~15 分钟

# 4. 质量校验
python 04_dq_check.py
python 04b_dq_rest.py
```

数据库连接走环境变量 `MYSQL_PWD`，不落盘。
