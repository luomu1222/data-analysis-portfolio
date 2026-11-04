# -*- coding: utf-8 -*-
"""DWD 层（v2）：按 3 小时分批去重，避免大排序撑爆内存
- 口径：ts 为 Unix 秒，按 UTC 取日期；官方窗口 2017-11-25 ~ 2017-12-03
- 脏数据（ts 越界）此前已隔离到 dwd_dirty_rows
- 每批用 ROW_NUMBER 按 (user_id,item_id,ts,behavior) 去重
"""
import os, sys, time, calendar
from datetime import date, datetime, timedelta
import pymysql

PW = os.environ.get("MYSQL_PWD", "")
if not PW:
    print("MYSQL_PWD not set", flush=True); sys.exit(2)

CHUNK_HOURS = 3
t0 = time.time()
conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password=PW,
                       charset="utf8mb4", autocommit=True)
cur = conn.cursor()
cur.execute("SET SESSION time_zone = '+00:00'")
cur.execute("SET SESSION tmp_table_size = 1073741824")
cur.execute("SET SESSION max_heap_table_size = 1073741824")
cur.execute("USE taobao_dw")

cur.execute("TRUNCATE TABLE dwd_user_behavior_di")
cur.execute("CREATE TABLE IF NOT EXISTS dq_check_result ("
            "check_dt DATE, layer VARCHAR(16), metric VARCHAR(64),"
            "ods_value BIGINT, dwd_value BIGINT, diff BIGINT, passed TINYINT,"
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
cur.execute("DELETE FROM dq_check_result WHERE layer='DWD'")
print("开始按 %d 小时分批，共 %d 天（按北京时区 UTC+8 切日）" % (CHUNK_HOURS, 9), flush=True)

CST = 8 * 3600
day = date(2017, 11, 25)
while day < date(2017, 12, 4):
    day_start = calendar.timegm(day.timetuple()) - CST
    ods_day = dwd_day = 0
    for h in range(0, 24, CHUNK_HOURS):
        a = day_start + h * 3600
        b = a + CHUNK_HOURS * 3600
        t1 = time.time()
        cur.execute("SELECT COUNT(*) FROM ods_user_behavior_raw WHERE ts >= %s AND ts < %s", (a, b))
        ods_cnt = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO dwd_user_behavior_di (user_id, item_id, category_id, behavior, ts, dt)
            SELECT user_id, item_id, category_id, behavior, ts, %s
            FROM (
              SELECT user_id, item_id, category_id, behavior, ts,
                     ROW_NUMBER() OVER (PARTITION BY user_id, item_id, ts, behavior ORDER BY ts) AS rn
              FROM ods_user_behavior_raw
              WHERE ts >= %s AND ts < %s
                AND user_id > 0 AND item_id > 0 AND category_id > 0
                AND behavior IN ('pv','cart','fav','buy')
            ) t WHERE rn = 1
        """, (day, a, b))
        got = cur.rowcount
        ods_day += ods_cnt
        dwd_day += got
        print("  %s %02d:00  ODS=%-7d DWD=%-7d %.1fs" % (day, h, ods_cnt, got, time.time() - t1), flush=True)
    diff = ods_day - dwd_day
    cur.execute("""INSERT INTO dq_check_result (check_dt, layer, metric, ods_value, dwd_value, diff, passed)
                   VALUES (%s,'DWD','row_count',%s,%s,%s,%s)""",
                (day, ods_day, dwd_day, diff, 1 if diff == 0 else 0))
    print("== %s 汇总 ODS=%d DWD=%d 去重=%d ==  (累计 %.1f 分钟)" %
          (day, ods_day, dwd_day, diff, (time.time() - t0) / 60), flush=True)
    day = day + timedelta(days=1)

cur.execute("SELECT COUNT(*) FROM dwd_user_behavior_di")
print("DWD 总行数:", cur.fetchone()[0], flush=True)
cur.execute("SELECT COUNT(DISTINCT user_id) FROM dwd_user_behavior_di")
print("DWD 用户数:", cur.fetchone()[0], flush=True)
cur.execute("SELECT behavior, COUNT(*) FROM dwd_user_behavior_di GROUP BY behavior ORDER BY 2 DESC")
for r in cur.fetchall():
    print("  ", r[0], r[1], flush=True)
print("建索引...", flush=True)
cur.execute("ALTER TABLE dwd_user_behavior_di ADD INDEX idx_dt (dt), ADD INDEX idx_user_dt (user_id, dt)")
print("DWD 完成，用时 %.1f 分钟" % ((time.time() - t0) / 60), flush=True)
conn.close()
print("DONE", flush=True)
