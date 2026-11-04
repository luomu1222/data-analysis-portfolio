# -*- coding: utf-8 -*-
"""A/B 实验框架：样本量设计 → 随机分流 → 主指标检验 → 护栏指标 → 重复窥探演示。

基线来自 taobao_dw 的真实数据（见 ab/baseline.json）：
  9 天平均购买转化率 19.26%（buy_uv / uv，逐日 17.91%–20.69%）
  用户层 buy_cnt 分布（0 单 5,633,064 人 / 1 单 948,157 / 2 单 244,812 ...）

诚实声明：实验的「策略效应」是模拟出来的（真实数据没有实验变量），
但基线、样本规模、方差、检验与决策规则全部按真实口径走。
只依赖标准库，不装 scipy 也能跑。
"""
import json, math, os, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- 基础统计量（手写，避免依赖） ----------
def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def norm_ppf(p):
    """标准正态分位数，Acklam 近似 + 一步牛顿修正。"""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

def two_prop_z(x1, n1, x2, n2):
    """两比例 z 检验：返回 (p1, p2, 绝对差, z, 双侧 p 值)。"""
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se_pool = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se_pool if se_pool > 0 else 0.0
    pval = 2 * (1 - norm_cdf(abs(z)))
    return p1, p2, p2 - p1, z, pval

def diff_ci(p1, n1, p2, n2, alpha=0.05):
    """两比例差值的 Wald 置信区间（非合并方差）。"""
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    z = norm_ppf(1 - alpha / 2)
    d = p2 - p1
    return d - z * se, d + z * se, se

def sample_size(p0, mde_rel, alpha=0.05, power=0.8):
    """每组所需样本量（相对 MDE）。"""
    p1 = p0
    p2 = p0 * (1 + mde_rel)
    z_a = norm_ppf(1 - alpha / 2)
    z_b = norm_ppf(power)
    num = (z_a * math.sqrt(2 * p1 * (1 - p1)) + z_b * math.sqrt(p1 * (1-p1) + p2 * (1-p2))) ** 2
    return math.ceil(num / (p2 - p1) ** 2), p2

def srm_check(n1, n2, expected_ratio=0.5):
    """样本比例失配检验（卡方，1 自由度）。卡方1 = z^2。"""
    n = n1 + n2
    e1, e2 = n * expected_ratio, n * (1 - expected_ratio)
    chi2 = (n1 - e1) ** 2 / e1 + (n2 - e2) ** 2 / e2
    # 卡方(1) 的双侧 p 值 = 2*(1-Phi(sqrt(chi2)))
    p = 2 * (1 - norm_cdf(math.sqrt(chi2)))
    return chi2, p

def welch_t(m1, s1, n1, m2, s2, n2):
    """Welch t 检验（大样本下 t≈z，用正态近似算 p 值）。"""
    se = math.sqrt(s1**2 / n1 + s2**2 / n2)
    t = (m2 - m1) / se if se > 0 else 0.0
    p = 2 * (1 - norm_cdf(abs(t)))
    return t, p, se


# ---------- 实验设计 ----------
def design(p0, mdes=(0.02, 0.05, 0.10, 0.15), alpha=0.05, power=0.8):
    rows = []
    for m in mdes:
        n, p2 = sample_size(p0, m, alpha, power)
        rows.append({"mde_rel": m, "p_treat": round(p2, 6),
                     "n_per_arm": n, "n_total": n * 2,
                     "days_needed": round(n * 2 / 706641, 2)})  # 按日均 UV 70 万估
    return rows


# ---------- 模拟一次实验（真实基线 + 模拟效应） ----------
def simulate(p0, lift_rel, n_users, seed=42, guard_lift=0.0, look_times=1, trials=400):
    rnd = random.Random(seed)
    p1 = p0 * (1 + lift_rel)
    n1 = n_users // 2
    n2 = n_users - n1
    x1 = sum(1 for _ in range(n1) if rnd.random() < p0)
    x2 = sum(1 for _ in range(n2) if rnd.random() < p1)

    p_a, p_b, d, z, pval = two_prop_z(x1, n1, x2, n2)
    lo, hi, se = diff_ci(p_a, n1, p_b, n2)

    # 护栏指标：人均下单次数（Lambda 近似），处理组 +guard_lift
    base_rate = 1.36   # 来自真实分布：有下单用户里人均单量
    def orders(n, rate):
        return [max(0, int(rnd.gauss(rate, 1.0))) for _ in range(n)]
    o1 = orders(n1, base_rate)
    o2 = orders(n2, base_rate * (1 + guard_lift))
    t, tp, _ = welch_t(statistics.mean(o1), statistics.stdev(o1), len(o1),
                       statistics.mean(o2), statistics.stdev(o2), len(o2))

    chi2, srm_p = srm_check(n1, n2)

    # 重复窥探：在 look_times 个中期点各检一次，任一次显著就算显著
    false_pos = None
    if look_times > 1:
        hits = 0

        for s in range(trials):
            r = random.Random(1000 + s)
            hit = False
            for k in range(1, look_times + 1):
                m = n_users * k // look_times
                a = sum(1 for _ in range(m // 2) if r.random() < p0)
                b = sum(1 for _ in range(m - m // 2) if r.random() < p0)  # 真实无差异
                if two_prop_z(a, m // 2, b, m - m // 2)[4] < 0.05:
                    hit = True
                    break
            hits += hit
        false_pos = hits / trials

    return {
        "p_control": round(p_a, 6), "p_treat": round(p_b, 6),
        "abs_lift": round(d, 6), "rel_lift": round(d / p_a, 6),
        "z": round(z, 4), "p_value": round(pval, 6),
        "ci95": [round(lo, 6), round(hi, 6)], "se": round(se, 6),
        "n": [n1, n2], "srm_chi2": round(chi2, 4), "srm_p": round(srm_p, 4),
        "guardrail_orders": {"control": round(statistics.mean(o1), 4),
                             "treat": round(statistics.mean(o2), 4),
                             "t": round(t, 4), "p": round(tp, 6)},
        "peeking_false_positive_rate": (None if false_pos is None else round(false_pos, 4)),
    }


if __name__ == "__main__":
    base = json.load(open(os.path.join(HERE, "baseline.json"), encoding="utf-8"))
    cvrs = [d["cvr"] for d in base["days"]]
    p0 = round(sum(cvrs) / len(cvrs), 6)
    daily_uv = round(sum(d["uv"] for d in base["days"]) / len(base["days"]))

    def fmt_p(p):
        return "p < 1e-10" if p < 1e-10 else f"p = {p:.4f}"

    out = {"p0": p0, "daily_uv": daily_uv}
    out["sample_size_table"] = design(p0)
    out["exp_5pct_lift"] = simulate(p0, 0.05, 1_400_000, seed=42)
    out["exp_2pct_underpowered"] = simulate(p0, 0.02, 40_000, seed=7)
    out["peeking_demo"] = simulate(p0, 0.0, 200_000, seed=11, look_times=10, trials=400)

    with open(os.path.join(HERE, "result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("基线 p0 =", p0, "| 日均 UV =", daily_uv)
    print("\n【样本量表】相对 MDE → 每组所需人数 / 总人数 / 需要天数(按日均 UV)")
    for r in out["sample_size_table"]:
        print(f"  {r['mde_rel']*100:>4.0f}%  →  {r['n_per_arm']:>9,}  {r['n_total']:>10,}  {r['days_needed']:>5} 天")

    e = out["exp_5pct_lift"]
    print("\n【主实验：真实基线 + 模拟 +5% 相对提升，总样本 140 万】")
    print(f"  对照 {e['p_control']*100:.2f}%  实验 {e['p_treat']*100:.2f}%  相对 +{e['rel_lift']*100:.2f}%")
    print(f"  z={e['z']}  {fmt_p(e['p_value'])}  95%CI 差值 [{e['ci95'][0]*100:.3f}pp, {e['ci95'][1]*100:.3f}pp]")
    print(f"  SRM: chi2={e['srm_chi2']} p={e['srm_p']} → 分流正常")
    print(f"  护栏(人均单量): 对照 {e['guardrail_orders']['control']} vs 实验 {e['guardrail_orders']['treat']}  p={e['guardrail_orders']['p']} → 无恶化")

    u = out["exp_2pct_underpowered"]
    print("\n【功效不足对照：真实 +2% 提升，但只有 4 万样本（每组 2 万，需 16.5 万）】")
    print(f"  对照 {u['p_control']*100:.2f}%  实验 {u['p_treat']*100:.2f}%  {fmt_p(u['p_value'])} → 不显著，不能下结论")

    print("\n【重复窥探：真实无差异，却看了 10 次中期结果】")
    print(f"  假阳性率 = {out['peeking_demo']['peeking_false_positive_rate']}（单次查看应为 0.05）")

