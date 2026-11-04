# -*- coding: utf-8 -*-
"""数仓数据质量体检：用真实跑出来的数字生成 DQ 报告数据。

检查项：
  1. 分层对账（ODS / DWD / 脏数据 / 去重）
  2. 主键与 ID 合法性
  3. 行为枚举
  4. 时间戳合理性（越界、按日分布）
  5. 重复率
  6. 极端值（单用户单日行为数）
输出 dw/dq_report.json
"""
import json, os, time
import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
pw = os.environ["MYSQL_PWD"]
conn = pymysql.connect(host="127.0.0.1", user="root", password=pw,
                       charset="utf8mb4", database="taobao_dw")
cur = conn.cursor()
out = {}
t0 = time.time()

def q(sql):
    cur.execute(sql)
    return cur.fetchall()

# ---------- 1. 分层对账 ----------
ods_total = q("SELECT COUNT(*) FROM ods_user_behavior_raw")[0][0]
dwd_total = q("SELECT COUNT(*) FROM dwd_user_behavior_di")[0][0]
dirty_total = q("SELECT COUNT(*) FROM dwd_dirty_rows")[0][0]
out["reconcile"] = {
    "ods_total": int(ods_total),
    "dwd_total": int(dwd_total),
    "dirty_total": int(dirty_total),
    "diff_after_dirty": int(ods_total - dirty_total - dwd_total),
    "note": "ODS = DWD + 脏数据(ts 越界) + 完全重复行（重复行在 DWD 去重时被丢弃）",
}
print(f"[1] ODS={ods_total:,} DWD={dwd_total:,} dirty={dirty_total:,} 差={ods_total-dirty_total-dwd_total:,}", flush=True)

# ---------- 2. ID 合法性（一次扫描算完） ----------
r = q("""SELECT COUNT(*) AS n,
                SUM(user_id <= 0) AS bad_user,
                SUM(item_id <= 0) AS bad_item,
                SUM(category_id <= 0) AS bad_cat,
                MIN(ts) AS ts_min, MAX(ts) AS ts_max
         FROM dwd_user_behavior_di""")[0]
out["id_check"] = {"rows": int(r[0]), "user_id_le0": int(r[1] or 0),
                   "item_id_le0": int(r[2] or 0), "category_id_le0": int(r[3] or 0),
                   "ts_min": int(r[4]), "ts_max": int(r[5])}
print(f"[2] ID<=0: user={r[1]} item={r[2]} cat={r[3]} | ts∈[{r[4]},{r[5]}]", flush=True)

# ---------- 3. 行为枚举 ----------
beh = q("SELECT behavior, COUNT(*) c FROM dwd_user_behavior_di GROUP BY behavior ORDER BY c DESC")
out["behavior_enum"] = [{"behavior": b, "rows": int(c), "share": round(c / dwd_total, 6)} for b, c in beh]
print("[3] 行为枚举:", out["behavior_enum"], flush=True)

# ---------- 4. 按日分布 ----------
days = q("""SELECT dt, COUNT(*) rows_, COUNT(DISTINCT user_id) uv
            FROM dwd_user_behavior_di GROUP BY dt ORDER BY dt""")
out["daily"] = [{"dt": str(d), "rows": int(n), "uv": int(u)} for d, n, u in days]
print(f"[4] 日期数={len(days)}", flush=True)

# ---------- 5. 重复率（四键完全重复） ----------
dup = q("""SELECT SUM(c - 1) FROM (
             SELECT COUNT(*) c FROM dwd_user_behavior_di
             GROUP BY user_id, item_id, ts, behavior
             HAVING c > 1
           ) t""")[0][0]
out["dup_rows_removed"] = int(dup or 0)
out["dup_rate"] = round((dup or 0) / dwd_total, 10)
print(f"[5] 完全重复行={dup}", flush=True)

# ---------- 6. 脏数据构成 ----------
dirty = q("SELECT reason, COUNT(*) FROM dwd_dirty_rows GROUP BY reason ORDER BY 2 DESC")
out["dirty_reason"] = [{"reason": str(a), "rows": int(b)} for a, b in dirty]
print("[6] 脏数据原因:", out["dirty_reason"], flush=True)

# ---------- 7. 极端值：单用户单日行为数 ----------
ex = q("""SELECT MAX(c) FROM (
            SELECT user_id, dt, SUM(pv_cnt+fav_cnt+cart_cnt+buy_cnt) c
            FROM dws_user_action_d GROUP BY user_id, dt
          ) t""")[0][0]
avg = q("""SELECT AVG(c) FROM (
             SELECT SUM(pv_cnt+fav_cnt+cart_cnt+buy_cnt) c
             FROM dws_user_action_d GROUP BY user_id, dt
           ) t""")[0][0]
out["extreme"] = {"max_user_day_actions": int(ex), "avg_user_day_actions": round(float(avg), 4)}
print(f"[7] 单用户单日行为数 max={ex} avg={avg:.2f}", flush=True)

# ---------- 8. 用户规模 ----------
out["users"] = {
    "total": int(q("SELECT COUNT(DISTINCT user_id) FROM dwd_user_behavior_di")[0][0]),
    "dws_user_day_rows": int(q("SELECT COUNT(*) FROM dws_user_action_d")[0][0]),
}
print(f"[8] 用户数={out['users']['total']:,}", flush=True)

out["elapsed_sec"] = round(time.time() - t0, 1)
with open(os.path.join(HERE, "dq_report.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
conn.close()
print("saved dq_report.json  耗时", out["elapsed_sec"], "s")
