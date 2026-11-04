# -*- coding: utf-8 -*-
"""A/B 实验项目 · 第 0 步：从数仓取真实基线，为实验设计提供参数。

不编数据：所有基线来自 taobao_dw 里已经跑出来的表。
输出 ab/baseline.json
"""
import os, json
import pymysql

OUT = os.path.dirname(os.path.abspath(__file__))
pw = os.environ["MYSQL_PWD"]

conn = pymysql.connect(host="127.0.0.1", user="root", password=pw,
                       charset="utf8mb4", database="taobao_dw")
cur = conn.cursor()

# 1) 每日流量的真实购买转化率（buy_uv / uv）
cur.execute("""
    SELECT dt, pv, uv, buy_uv
    FROM dws_traffic_d
    ORDER BY dt
""")
days = []
for dt, pv, uv, buy_uv in cur.fetchall():
    days.append({"dt": str(dt), "pv": int(pv), "uv": int(uv),
                 "buy_uv": int(buy_uv), "cvr": round(buy_uv / uv, 6)})

# 2) 用户层的购买次数分布（用于客单价/ARPU 的方差，Welch t 检验要）
cur.execute("""
    SELECT buy_cnt, COUNT(*) AS users
    FROM dws_user_action_d
    GROUP BY buy_cnt
    ORDER BY buy_cnt
""")
dist = [{"buy_cnt": int(c), "users": int(n)} for c, n in cur.fetchall()]

# 3) 参与统计的活跃用户规模（9 天去重 UV 的上界=有行为用户数）
cur.execute("SELECT COUNT(DISTINCT user_id) FROM dwd_user_behavior_di")
total_users = int(cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM dws_user_action_d")
rows_action = int(cur.fetchone()[0])

conn.close()

data = {"days": days, "buy_cnt_dist": dist,
        "total_users": total_users, "dws_user_action_rows": rows_action}
with open(os.path.join(OUT, "baseline.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# 打印关键基线
print("日期        UV        购买UV      转化率")
for d in days:
    print(f"{d['dt']}  {d['uv']:>8}  {d['buy_uv']:>8}  {d['cvr']*100:>6.2f}%")
avg_cvr = sum(d["cvr"] for d in days) / len(days)
print(f"\n9 天平均购买转化率: {avg_cvr*100:.2f}%")
print("用户层 buy_cnt 分布(前6档):", dist[:6])
print("有行为用户总数:", total_users, "| dws_user_action_d 行数:", rows_action)
