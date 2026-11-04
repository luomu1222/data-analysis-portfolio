# -*- coding: utf-8 -*-
"""DWS / ADS / SCD2 拉链表：在 dwd_user_behavior_di 之上做聚合与指标"""
import os, sys, time
import pymysql

PW = os.environ.get("MYSQL_PWD", "")
if not PW:
    print("MYSQL_PWD not set", flush=True); sys.exit(2)

t0 = time.time()
conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password=PW,
                       charset="utf8mb4", autocommit=True)
cur = conn.cursor()
cur.execute("SET SESSION time_zone = '+00:00'")
cur.execute("USE taobao_dw")


def run(name, sql, quiet=False):
    t = time.time()
    cur.execute(sql)
    dt = time.time() - t
    print("[%s] %.1fs" % (name, dt), flush=True)
    return dt


# ---------- DWS 1: 用户日粒度行为汇总 ----------
run("drop dws_user_action_d", "DROP TABLE IF EXISTS dws_user_action_d")
run("create dws_user_action_d", """
CREATE TABLE dws_user_action_d (
  dt DATE NOT NULL, user_id BIGINT NOT NULL,
  pv_cnt INT, cart_cnt INT, fav_cnt INT, buy_cnt INT,
  item_cnt INT, cat_cnt INT, first_ts BIGINT, last_ts BIGINT,
  PRIMARY KEY (dt, user_id), KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
run("insert dws_user_action_d", """
INSERT INTO dws_user_action_d
SELECT dt, user_id,
       SUM(behavior='pv'), SUM(behavior='cart'), SUM(behavior='fav'), SUM(behavior='buy'),
       COUNT(DISTINCT item_id), COUNT(DISTINCT category_id), MIN(ts), MAX(ts)
FROM dwd_user_behavior_di
GROUP BY dt, user_id
""")
cur.execute("SELECT COUNT(*) FROM dws_user_action_d")
print("  dws_user_action_d 行数:", cur.fetchone()[0], flush=True)

# ---------- DWS 2: 全站日流量 ----------
run("drop dws_traffic_d", "DROP TABLE IF EXISTS dws_traffic_d")
run("create dws_traffic_d", """
CREATE TABLE dws_traffic_d (
  dt DATE PRIMARY KEY, pv BIGINT, uv BIGINT,
  cart_uv BIGINT, fav_uv BIGINT, buy_uv BIGINT,
  buy_events BIGINT, pv_per_uv DECIMAL(10,2)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
run("insert dws_traffic_d", """
INSERT INTO dws_traffic_d
SELECT dt, SUM(pv_cnt), COUNT(*), SUM(cart_cnt>0), SUM(fav_cnt>0), SUM(buy_cnt>0),
       SUM(buy_cnt), ROUND(SUM(pv_cnt)/COUNT(*), 2)
FROM dws_user_action_d GROUP BY dt ORDER BY dt
""")
cur.execute("SELECT dt, pv, uv, buy_uv, pv_per_uv FROM dws_traffic_d ORDER BY dt")
for r in cur.fetchall():
    print("  ", r, flush=True)

# ---------- ADS 1: 转化漏斗（按天，去重用户口径） ----------
run("drop ads_funnel_d", "DROP TABLE IF EXISTS ads_funnel_d")
run("create ads_funnel_d", """
CREATE TABLE ads_funnel_d (
  dt DATE PRIMARY KEY, pv_users BIGINT, cart_users BIGINT, fav_users BIGINT, buy_users BIGINT,
  pv2cart_rate DECIMAL(8,4), cart2buy_rate DECIMAL(8,4), pv2buy_rate DECIMAL(8,4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
run("insert ads_funnel_d", """
INSERT INTO ads_funnel_d
SELECT dt, uv, cart_uv, fav_uv, buy_uv,
       ROUND(100*cart_uv/uv, 2), ROUND(100*buy_uv/cart_uv, 2), ROUND(100*buy_uv/uv, 2)
FROM dws_traffic_d
""")

# ---------- ADS 2: 留存（首访日 cohort，D0~D7） ----------
run("drop tmp_cohort", "DROP TABLE IF EXISTS tmp_cohort")
run("create tmp_cohort", """
CREATE TABLE tmp_cohort (user_id BIGINT PRIMARY KEY, first_dt DATE, KEY idx_fd (first_dt))
""")
run("insert tmp_cohort", """
INSERT INTO tmp_cohort SELECT user_id, MIN(dt) FROM dwd_user_behavior_di GROUP BY user_id
""")
run("drop tmp_cohort_size", "DROP TABLE IF EXISTS tmp_cohort_size")
run("create tmp_cohort_size", """
CREATE TABLE tmp_cohort_size (first_dt DATE PRIMARY KEY, cohort_users BIGINT)
""")
run("insert tmp_cohort_size", "INSERT INTO tmp_cohort_size SELECT first_dt, COUNT(*) FROM tmp_cohort GROUP BY first_dt")
run("drop ads_retention", "DROP TABLE IF EXISTS ads_retention")
run("create ads_retention", """
CREATE TABLE ads_retention (
  first_dt DATE, day_n INT, cohort_users BIGINT, retained_users BIGINT, retention_rate DECIMAL(8,4),
  PRIMARY KEY (first_dt, day_n)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
run("insert ads_retention", """
INSERT INTO ads_retention
SELECT c.first_dt, DATEDIFF(d.dt, c.first_dt) AS day_n, s.cohort_users,
       COUNT(DISTINCT d.user_id),
       ROUND(100*COUNT(DISTINCT d.user_id)/s.cohort_users, 2)
FROM tmp_cohort c
JOIN dws_user_action_d d ON d.user_id = c.user_id
JOIN tmp_cohort_size s ON s.first_dt = c.first_dt
WHERE DATEDIFF(d.dt, c.first_dt) BETWEEN 0 AND 7
GROUP BY c.first_dt, day_n, s.cohort_users
""")
cur.execute("""SELECT first_dt, day_n, cohort_users, retained_users, retention_rate
               FROM ads_retention WHERE first_dt = (SELECT MIN(first_dt) FROM tmp_cohort_size)
               ORDER BY day_n""")
for r in cur.fetchall():
    print("  cohort", r, flush=True)

# ---------- ADS 3: RFM 分层 ----------
run("drop ads_rfm", "DROP TABLE IF EXISTS ads_rfm")
run("create ads_rfm", """
CREATE TABLE ads_rfm (
  user_id BIGINT PRIMARY KEY, r_days INT, f_days INT, m_buy BIGINT,
  r_score INT, f_score INT, m_score INT, rfm_seg VARCHAR(24)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
run("insert ads_rfm", """
INSERT INTO ads_rfm
WITH base AS (
  SELECT user_id, DATEDIFF('2017-12-04', MAX(dt)) AS r_days,
         COUNT(DISTINCT CASE WHEN buy_cnt > 0 THEN dt END) AS f_days,
         SUM(buy_cnt) AS m_buy
  FROM dws_user_action_d GROUP BY user_id
), scored AS (
  SELECT user_id, r_days, f_days, m_buy,
         NTILE(5) OVER (ORDER BY r_days DESC) AS r_score,
         NTILE(5) OVER (ORDER BY f_days) AS f_score,
         NTILE(5) OVER (ORDER BY m_buy) AS m_score
  FROM base
)
SELECT user_id, r_days, f_days, m_buy, r_score, f_score, m_score,
       CONCAT('R', r_score, 'F', f_score, 'M', m_score)
FROM scored
""")
run("add seg label", """
ALTER TABLE ads_rfm ADD COLUMN seg_name VARCHAR(24)
""")
run("update seg label", """
UPDATE ads_rfm SET seg_name = CASE
  WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN '重要价值客户'
  WHEN r_score >= 4 AND f_score < 4 AND m_score >= 4 THEN '重要发展客户'
  WHEN r_score < 4 AND f_score >= 4 AND m_score >= 4 THEN '重要保持客户'
  WHEN r_score < 4 AND f_score < 4 AND m_score >= 4 THEN '重要挽留客户'
  WHEN r_score >= 4 AND f_score >= 4 AND m_score < 4 THEN '一般价值客户'
  WHEN r_score >= 4 AND f_score < 4 AND m_score < 4 THEN '一般发展客户'
  WHEN r_score < 4 AND f_score >= 4 AND m_score < 4 THEN '一般保持客户'
  ELSE '一般挽留客户' END
""")
cur.execute("SELECT seg_name, COUNT(*) FROM ads_rfm GROUP BY seg_name ORDER BY 2 DESC")
for r in cur.fetchall():
    print("  ", r, flush=True)

# ---------- ADS 4: 品类转化 ----------
run("drop ads_category_cvr", "DROP TABLE IF EXISTS ads_category_cvr")
run("create ads_category_cvr", """
CREATE TABLE ads_category_cvr (
  category_id BIGINT PRIMARY KEY, pv BIGINT, uv BIGINT, buyers BIGINT,
  cvr DECIMAL(8,4), pv_share DECIMAL(8,4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
run("insert ads_category_cvr", """
INSERT INTO ads_category_cvr
SELECT category_id,
       SUM(behavior='pv'), COUNT(DISTINCT user_id),
       COUNT(DISTINCT CASE WHEN behavior='buy' THEN user_id END),
       ROUND(100*COUNT(DISTINCT CASE WHEN behavior='buy' THEN user_id END)/COUNT(DISTINCT user_id), 4),
       ROUND(100*SUM(behavior='pv')/(SELECT SUM(behavior='pv') FROM dwd_user_behavior_di), 4)
FROM dwd_user_behavior_di
GROUP BY category_id
""")
cur.execute("""SELECT category_id, pv, uv, buyers, cvr FROM ads_category_cvr
               WHERE uv >= 1000 ORDER BY pv DESC LIMIT 5""")
for r in cur.fetchall():
    print("  top cat", r, flush=True)

# ---------- SCD2 拉链表：用户价值分层历史 ----------
run("drop dim_user_value_scd2", "DROP TABLE IF EXISTS dim_user_value_scd2")
run("create dim_user_value_scd2", """
CREATE TABLE dim_user_value_scd2 (
  user_id BIGINT NOT NULL, seg VARCHAR(8) NOT NULL,
  start_dt DATE NOT NULL, end_dt DATE NOT NULL, is_current TINYINT NOT NULL,
  PRIMARY KEY (user_id, start_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
run("build scd2", """
INSERT INTO dim_user_value_scd2
WITH daily AS (
  SELECT dt, user_id,
         CASE WHEN buy_cnt > 0 THEN 'high' WHEN cart_cnt > 0 OR fav_cnt > 0 THEN 'mid' ELSE 'low' END AS seg
  FROM dws_user_action_d
), lagged AS (
  SELECT dt, user_id, seg,
         LAG(seg) OVER (PARTITION BY user_id ORDER BY dt) AS prev_seg
  FROM daily
), marked AS (
  SELECT dt, user_id, seg, CASE WHEN prev_seg IS NULL OR prev_seg <> seg THEN 1 ELSE 0 END AS is_new
  FROM lagged
), grouped AS (
  SELECT dt, user_id, seg, SUM(is_new) OVER (PARTITION BY user_id ORDER BY dt) AS grp
  FROM marked
)
SELECT user_id, seg, MIN(dt) AS start_dt,
       CASE WHEN MAX(dt) = (SELECT MAX(dt) FROM daily) THEN DATE('9999-12-31') ELSE DATE_ADD(MAX(dt), INTERVAL 1 DAY) END,
       CASE WHEN MAX(dt) = (SELECT MAX(dt) FROM daily) THEN 1 ELSE 0 END
FROM grouped
GROUP BY user_id, seg, grp
""")
cur.execute("SELECT COUNT(*), SUM(is_current) FROM dim_user_value_scd2")
print("  SCD2 行数 / 当前版本:", cur.fetchone(), flush=True)
cur.execute("""SELECT user_id, seg, start_dt, end_dt, is_current FROM dim_user_value_scd2
               WHERE user_id = (SELECT user_id FROM dim_user_value_scd2 GROUP BY user_id
                                HAVING COUNT(*) > 1 LIMIT 1) ORDER BY start_dt""")
print("  多版本用户示例:", cur.fetchall()[:6], flush=True)

print("全部完成，用时 %.1f 分钟" % ((time.time() - t0) / 60), flush=True)
conn.close()
print("DONE", flush=True)
