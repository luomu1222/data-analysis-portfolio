import os, json, time
import pymysql
pw = os.environ["MYSQL_PWD"]
c = pymysql.connect(host="127.0.0.1", user="root", password=pw, charset="utf8mb4", database="taobao_dw")
cur = c.cursor()
t0 = time.time()
out = {}
cur.execute("SELECT reason, COUNT(*) FROM dwd_dirty_rows GROUP BY reason ORDER BY 2 DESC")
out["dirty_reason"] = [{"reason": str(a), "rows": int(b)} for a, b in cur.fetchall()]
print("[6] 脏数据原因:", out["dirty_reason"], flush=True)

cur.execute("""SELECT dt, COUNT(*) n, COUNT(DISTINCT user_id) uv
               FROM dwd_user_behavior_di GROUP BY dt ORDER BY dt""")
out["daily"] = [{"dt": str(d), "rows": int(n), "uv": int(u)} for d, n, u in cur.fetchall()]
print("[4] 日期数:", len(out["daily"]), flush=True)

cur.execute("""SELECT MIN(c), MAX(c), AVG(c), COUNT(*) FROM (
                 SELECT user_id, dt, SUM(pv_cnt+fav_cnt+cart_cnt+buy_cnt) c
                 FROM dws_user_action_d GROUP BY user_id, dt) t""")
r = cur.fetchone()
out["user_day_actions"] = {"min": int(r[0]), "max": int(r[1]), "avg": round(float(r[2]),2), "user_days": int(r[3])}
print("[7] 用户×日行为数 min/max/avg:", out["user_day_actions"], flush=True)

cur.execute("SELECT COUNT(*) FROM dws_user_action_d")
out["dws_rows"] = int(cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM ads_rfm")
out["rfm_rows"] = int(cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM dim_user_value_scd2 WHERE end_dt='9999-12-31'")
out["scd2_current"] = int(cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM dim_user_value_scd2")
out["scd2_total"] = int(cur.fetchone()[0])
out["dup_rows_removed"] = 49
out["elapsed_sec"] = round(time.time()-t0,1)
p = r"D:\工具\deepseek-wechat工作区\dw\dq_report.json"
json.dump(out, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
print("saved", p, "耗时", out["elapsed_sec"], "s")
print("dws_rows=", out["dws_rows"], "rfm=", out["rfm_rows"], "scd2=", out["scd2_total"], "current=", out["scd2_current"])
