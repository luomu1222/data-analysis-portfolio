# -*- coding: utf-8 -*-
"""A/B 实验项目的两张图：样本量曲线 + 重复窥探的假阳性膨胀。"""
import json, os, random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

import ab_experiment as ab

HERE = os.path.dirname(os.path.abspath(__file__))
font_manager.fontManager.addfont("C:/Windows/Fonts/msyh.ttc")
plt.rcParams["font.family"] = font_manager.FontProperties(fname="C:/Windows/Fonts/msyh.ttc").get_name()
plt.rcParams["axes.unicode_minus"] = False

res = json.load(open(os.path.join(HERE, "result.json"), encoding="utf-8"))
p0 = res["p0"]

# ---------- 图 1：MDE → 每组样本量 ----------
mdes = [round(x * 0.005, 3) for x in range(2, 41)]          # 1% ~ 20%
ns = [ab.sample_size(p0, m)[0] for m in mdes]
fig, ax = plt.subplots(figsize=(9, 5), dpi=160)
ax.plot([m * 100 for m in mdes], ns, lw=2.4, color="#2563eb")
ax.set_yscale("log")
ax.set_xlabel("最小可检测提升（相对，%）", fontsize=11)
ax.set_ylabel("每组所需样本量（对数轴）", fontsize=11)
ax.set_title(f"样本量随 MDE 变化（基线转化率 {p0*100:.2f}%，α=0.05，power=0.8）", fontsize=12, pad=12)
ax.grid(alpha=.3, ls=":")
for m, txt in ((0.02, "2%"), (0.05, "5%"), (0.10, "10%")):
    n = ab.sample_size(p0, m)[0]
    ax.plot([m * 100], [n], "o", color="#dc2626", ms=7)
    ax.annotate(f"{txt} → 每组 {n:,}", xy=(m * 100, n), xytext=(12, 18),
                textcoords="offset points", fontsize=9.5, color="#dc2626")
ax.axhline(774283, color="#16a34a", ls="--", lw=1.4)
ax.text(19.4, 774283 * 1.15, "单日 UV 77 万", ha="right", fontsize=9, color="#16a34a")
fig.tight_layout()
fig.savefig(os.path.join(HERE, "fig1_sample_size.png"))
plt.close(fig)
print("saved fig1")

# ---------- 图 2：窥探次数 → 假阳性率 ----------
def fpr(n_users, looks, trials=300):
    hits = 0
    for s in range(trials):
        r = random.Random(9000 + s)
        for k in range(1, looks + 1):
            m = n_users * k // looks
            a = sum(1 for _ in range(m // 2) if r.random() < p0)
            b = sum(1 for _ in range(m - m // 2) if r.random() < p0)
            if ab.two_prop_z(a, m // 2, b, m - m // 2)[4] < 0.05:
                hits += 1
                break
    return hits / trials

looks_list = [1, 2, 3, 5, 8, 10, 15, 20]
fprs = [fpr(200_000, k) for k in looks_list]
json.dump({"looks": looks_list, "fpr": [round(x, 4) for x in fprs]},
          open(os.path.join(HERE, "peeking_curve.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

fig, ax = plt.subplots(figsize=(9, 5), dpi=160)
ax.plot(looks_list, [x * 100 for x in fprs], "o-", lw=2.2, color="#dc2626", ms=7)
ax.axhline(5, color="#16a34a", ls="--", lw=1.4)
ax.text(19.6, 6.5, "名义显著性 5%", ha="right", fontsize=9, color="#16a34a")
ax.set_xlabel("实验期间偷看的次数", fontsize=11)
ax.set_ylabel("假阳性率（%）", fontsize=11)
ax.set_title("反复窥探把假阳性率抬高（真实无差异，每组 30 万用户以内，300 次模拟）",
             fontsize=12, pad=12)
ax.grid(alpha=.3, ls=":")
for x, y in zip(looks_list, fprs):
    ax.annotate(f"{y*100:.0f}%", xy=(x, y * 100), xytext=(0, 9),
                textcoords="offset points", ha="center", fontsize=9)
fig.tight_layout()
fig.savefig(os.path.join(HERE, "fig2_peeking.png"))
plt.close(fig)
print("saved fig2; fpr =", [round(x, 3) for x in fprs])
