# -*- coding: utf-8 -*-
"""ODS 层：把 3.5GB UserBehavior.csv 全量装入 MySQL（LOAD DATA LOCAL INFILE）"""
import os, sys, time
import pymysql

CSV = r"D:/taobao_user_behavior/data/UserBehavior.csv"
PW = os.environ.get("MYSQL_PWD", "")
if not PW:
    print("MYSQL_PWD not set", flush=True)
    sys.exit(2)

t0 = time.time()
conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password=PW,
                       charset="utf8mb4", local_infile=True, autocommit=True)
cur = conn.cursor()
cur.execute("SET GLOBAL local_infile = 1")
print("local_infile=1", flush=True)

cur.execute("CREATE DATABASE IF NOT EXISTS taobao_dw DEFAULT CHARACTER SET utf8mb4")
cur.execute("USE taobao_dw")
cur.execute("DROP TABLE IF EXISTS ods_user_behavior_raw")
cur.execute("""
CREATE TABLE ods_user_behavior_raw (
  user_id     BIGINT      NOT NULL,
  item_id     BIGINT      NOT NULL,
  category_id BIGINT      NOT NULL,
  behavior    VARCHAR(8)  NOT NULL,
  ts          BIGINT      NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
print("ODS 表已建", flush=True)

# 导入前放宽耐久性换速度（MySQL 26.x 里 flush_log 只能 GLOBAL）
for s in ("SET SESSION unique_checks=0",
          "SET SESSION foreign_key_checks=0",
          "SET GLOBAL innodb_flush_log_at_trx_commit=2"):
    try:
        cur.execute(s)
    except Exception as e:
        print("跳过", s, "->", str(e)[:60], flush=True)

sql = ("LOAD DATA LOCAL INFILE '%s' INTO TABLE ods_user_behavior_raw "
       "FIELDS TERMINATED BY ',' LINES TERMINATED BY '\\n' "
       "(user_id, item_id, category_id, behavior, ts)") % CSV
print("开始 LOAD DATA ...", flush=True)
cur.execute(sql)
print("LOAD 完成，用时 %.1f 分钟" % ((time.time() - t0) / 60), flush=True)

cur.execute("SELECT COUNT(*) FROM ods_user_behavior_raw")
print("ODS 行数:", cur.fetchone()[0], flush=True)
cur.execute("SELECT behavior, COUNT(*) FROM ods_user_behavior_raw GROUP BY behavior ORDER BY 2 DESC")
for r in cur.fetchall():
    print("  behavior", r[0], r[1], flush=True)

cur.execute("ALTER TABLE ods_user_behavior_raw ADD INDEX idx_ts (ts), ADD INDEX idx_user (user_id)")
print("索引已建，总用时 %.1f 分钟" % ((time.time() - t0) / 60), flush=True)
cur.execute("SELECT TABLE_NAME, ROUND(DATA_LENGTH/1024/1024,1) AS data_mb, ROUND(INDEX_LENGTH/1024/1024,1) AS idx_mb, TABLE_ROWS "
            "FROM information_schema.TABLES WHERE TABLE_SCHEMA='taobao_dw'")
print(cur.fetchall(), flush=True)
conn.close()
print("DONE", flush=True)
