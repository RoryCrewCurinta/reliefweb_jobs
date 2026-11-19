"""Builds the data snapshot for the story page from the dashboard's exported files
and ALNAP's published GHA 2026 chart data. Prints the facts the prose relies on.

Usage: python data.py <docs folder> <gha_2026/analyses folder> <snapshot.json to write> <inputs/iha_2019_2025.json>
Writes snapshot.json and, beside it, facts.json."""
import json, csv, collections, sys

SRC = sys.argv[1]          # docs/ folder of the dashboard
GHA = sys.argv[2]          # ALNAP gha_2026 analyses folder
OUT = sys.argv[3]

r = json.load(open(f"{SRC}/data/roles.json", encoding="utf-8"))
t = json.load(open(f"{SRC}/data/totals.json", encoding="utf-8"))
meta = json.load(open(f"{SRC}/data/meta.json", encoding="utf-8"))
months = t["months"]
assert months == r["months"]
YEARS = list(range(2019, 2026))

def yearly(series, years=YEARS):
    d = collections.Counter()
    for m, v in zip(months, series):
        d[int(m[:4])] += v or 0
    return [d[y] for y in years]

D = {"last_month": meta["last_month"], "generated": meta["generated"], "years": YEARS}
D["total"] = yearly(t["jobs"])
D["monthly"] = {"start": "2022-01", "jobs": [v for m, v in zip(months, t["jobs"]) if m >= "2022-01"]}

dims = {dim: {it["name"]: yearly(it["jobs"]) for it in vals} for dim, vals in r["dims"].items()}
D["job_type"] = {k: dims["job_type"][k] for k in ("Job", "Consultancy")}
D["experience"] = {k: dims["experience"][k] for k in ("0-2 years", "3-4 years", "5-9 years", "10+ years")}
i22, i25 = YEARS.index(2022), YEARS.index(2025)
D["org_type"] = [[k, v[i22], v[i25]] for k, v in dims["org_type"].items() if v[i22] >= 500]

cy = collections.defaultdict(dict)
for x in csv.DictReader(open(f"{SRC}/data/country_year.csv", encoding="utf-8")):
    cy[x["country"]][int(x["year"])] = int(x["posts"])
top = sorted(cy, key=lambda c: -cy[c].get(2022, 0))[:20]
D["countries"] = [[c, cy[c].get(2021, 0), cy[c][2022], cy[c].get(2025, 0)] for c in top]

ty = collections.defaultdict(dict)
for x in csv.DictReader(open(f"{SRC}/data/topic_year.csv", encoding="utf-8")):
    ty[x["topic"]][int(x["year"])] = int(x["n_core"])
D["topics"] = [[k, v.get(2022, 0), v.get(2025, 0)] for k, v in ty.items() if v.get(2022, 0) >= 300]

iha = list(csv.DictReader(open(f"{GHA}/fig-1.1-total_iha.csv", encoding="utf-8-sig")))
# 2019 and 2020: ALNAP publishes no constant-price total before 2021. Estimate = public donors in constant
# 2024 prices + private funding (current prices) scaled by the public donors' own deflator, from ALNAP's workbook (inputs/iha_2019_2025.json).
_in = json.load(open(sys.argv[4], encoding="utf-8"))
_pubc = {int(k): v for k, v in _in["public_constant_2024_usd_m"].items()}
_pubn = {int(k): v for k, v in _in["public_current_usd_m"].items()}
_priv = {int(k): v for k, v in _in["private_current_usd"].items()}
_est = lambda y: (_pubc[y] + _priv[y] / 1e6 * _pubc[y] / _pubn[y]) / 1000
_pub = {int(x["year"]): float(x["funding_total"]) for x in iha}
_err = max(abs(_est(y) / _pub[y] - 1) * 100 for y in _pub)
print("ESTIMATE", {y: round(_est(y), 3) for y in range(2019, 2026)}, "published", _pub, "max err %.2f%%" % _err)
EST_YEARS = [2019, 2020]
D["funding"] = {"years": EST_YEARS + [int(x["year"]) for x in iha],
                "total": [round(_est(y), 4) for y in EST_YEARS] + [round(float(x["funding_total"]), 4) for x in iha], "est": EST_YEARS}

D["small_topics"] = [[k, v.get(2022, 0), v.get(2025, 0)] for k, v in ty.items()
                     if v.get(2022, 0) < 300 and max(v.get(2022, 0), v.get(2025, 0)) >= 50]
D["exceptions"] = {c: [cy[c].get(y, 0) for y in range(2021, 2026)]
                   for c in ("Syrian Arab Republic", "Occupied Palestinian territory", "Myanmar")}
json.dump(D, open(OUT, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)

# ---- facts.json: every number the prose quotes, computed here so none is typed by hand ----
n = lambda v: f"{v:,}"
fall = lambda a, b: str(abs(round((b / a - 1) * 100)))
_T = dict(zip(YEARS, D["total"])); _F = dict(zip(D["funding"]["years"], D["funding"]["total"]))
_Fx = {int(x["year"]): float(x["funding_total"]) for x in iha}
_m = dict(zip([m for m in months if m >= "2022-01"], D["monthly"]["jobs"]))
_d = lambda dim, k: dict(zip(YEARS, dims[dim][k]))
job, con = _d("job_type", "Job"), _d("job_type", "Consultancy")
jr, sr = _d("experience", "0-2 years"), _d("experience", "10+ years")
ot = lambda k: _d("org_type", k)
tp_ = {k: (a, b) for k, a, b in D["topics"]}
_f25 = [_m[f"2025-{i:02d}"] for i in range(2, 12)]
_a25 = sum(_m[f"2025-{i:02d}"] for i in range(1, 11)); _a26 = sum(_m[f"2026-{i:02d}"] for i in range(1, 11))
_sc = list(csv.reader(open(f"{GHA}/fig-1.2-scenarios.csv", encoding="utf-8-sig")))
_cc = {k: _d("career_category", k) for k in dims["career_category"]}
_cca = sorted(round((v[2025] / v[2022] - 1) * -100) for k, v in _cc.items() if v[2022] >= 500)
_ccf = [v for v in _cca if v >= 60]
_roll = max(sum(t["jobs"][i - 11:i + 1]) for i in range(11, len(months)))
C = lambda c, y: cy[c].get(y, 0)
SY, PA, MM = "Syrian Arab Republic", "Occupied Palestinian territory", "Myanmar"
UK = "United Kingdom of Great Britain and Northern Ireland"; US = "United States of America"
FACTS = {
 "tot22": n(_T[2022]), "tot25": n(_T[2025]), "fund22": f"{_Fx[2022]:.1f}", "fund25": f"{_Fx[2025]:.1f}",
 "fall_ads": fall(_T[2022], _T[2025]), "fall_fund": fall(_Fx[2022], _Fx[2025]),
 "ads23": fall(_T[2022], _T[2023]), "ads24": fall(_T[2023], _T[2024]), "ads25": fall(_T[2024], _T[2025]),
 "fund23": f"{abs((_Fx[2023] / _Fx[2022] - 1) * 100):.1f}", "fund24": fall(_Fx[2023], _Fx[2024]), "fund25c": fall(_Fx[2024], _Fx[2025]),
 "ukrpol21": n(C("Ukraine", 2021) + C("Poland", 2021)), "ukrpol22": n(C("Ukraine", 2022) + C("Poland", 2022)),
 "epi23": fall(ty["Epidemics & disease control"][2022], ty["Epidemics & disease control"][2023]),
 "avg24": n(round(_T[2024] / 12)), "jan25": n(_m["2025-01"]), "feb25": n(_m["2025-02"]),
 "lo25": n(min(_f25)), "hi25": n(max(_f25)), "avg25": n(round(sum(_f25) / 10)), "dec25": n(_m["2025-12"]),
 "job_fall": fall(job[2022], job[2025]), "con_fall": fall(con[2022], con[2025]),
 "con_sh22": str(round(con[2022] / _T[2022] * 100)), "con_sh25": str(round(con[2025] / _T[2025] * 100)),
 "jr_fall": fall(jr[2022], jr[2025]), "sr_fall": fall(sr[2022], sr[2025]),
 "jr23": fall(jr[2022], jr[2023]), "jr24": fall(jr[2023], jr[2024]),
 "sr23": fall(sr[2022], sr[2023]), "sr24": fall(sr[2023], sr[2024]), "sr25": fall(sr[2024], sr[2025]),
 "us": fall(C(US, 2022), C(US, 2025)), "uk": fall(C(UK, 2022), C(UK, 2025)), "fr": fall(C("France", 2022), C("France", 2025)),
 "fr21": fall(C("France", 2021), C("France", 2025)), "fr_21n": n(C("France", 2021)), "fr_22n": n(C("France", 2022)),
 "ch": fall(C("Switzerland", 2022), C("Switzerland", 2025)), "ke": fall(C("Kenya", 2022), C("Kenya", 2025)),
 "sy22": n(C(SY, 2022)), "sy25": n(C(SY, 2025)), "sy26": n(C(SY, 2026)), "sy_up": fall(C(SY, 2022), C(SY, 2025)),
 "pa24": n(C(PA, 2024)), "pa25": n(C(PA, 2025)), "pa_fall": fall(C(PA, 2024), C(PA, 2025)),
 "mm24": n(C(MM, 2024)), "mm25": n(C(MM, 2025)), "mm_fall": fall(C(MM, 2024), C(MM, 2025)),
 "loc": fall(ot("Locally based NGO")[2022], ot("Locally based NGO")[2025]),
 "loc22": n(ot("Locally based NGO")[2022]), "loc25": n(ot("Locally based NGO")[2025]),
 "reg": fall(ot("Regional NGO (global South base)")[2022], ot("Regional NGO (global South base)")[2025]),
 "ingo": fall(ot("International NGO")[2022], ot("International NGO")[2025]),
 "ingo_sh": str(round(ot("International NGO")[2022] / _T[2022] * 100)),
 "io": fall(ot("International Organization")[2022], ot("International Organization")[2025]),
 "rc": fall(ot("Red Cross/Red Crescent Movement")[2022], ot("Red Cross/Red Crescent Movement")[2025]),
 "rc21": n(ot("Red Cross/Red Crescent Movement")[2021]), "rc22": n(ot("Red Cross/Red Crescent Movement")[2022]),
 "fund19": f"{_est(2019):.1f}", "fund20": f"{_est(2020):.1f}", "ads20": fall(_T[2019], _T[2020]), "est_err": f"{_err:.1f}",
 "ntopics": str(len(D["topics"])), "nsmall": str(len(D["small_topics"])),
 "nthin": str(len(ty) - len(D["topics"]) - len(D["small_topics"])),
 "ai22": n(ty["AI & machine learning"][2022]), "ai25": n(ty["AI & machine learning"][2025]),
 "rm22": n(ty["Remote & third-party monitoring"][2022]), "rm25": n(ty["Remote & third-party monitoring"][2025]),
 "ur22": n(ty["Urban & area-based response"][2022]), "ur25": n(ty["Urban & area-based response"][2025]),
 "lz": fall(ty["Localisation & local leadership"][2022], ty["Localisation & local leadership"][2025]),
 "lz22": n(ty["Localisation & local leadership"][2022]), "lz25": n(ty["Localisation & local leadership"][2025]),
 "lz_s22": f'{ty["Localisation & local leadership"][2022] / _T[2022] * 100:.2f}', "lz_s25": f'{ty["Localisation & local leadership"][2025] / _T[2025] * 100:.2f}',
 "mp22": n(ty["Multi-purpose cash (MPCA)"][2022]), "mp25": n(ty["Multi-purpose cash (MPCA)"][2025]),
 "mp": fall(ty["Multi-purpose cash (MPCA)"][2022], ty["Multi-purpose cash (MPCA)"][2025]),
 "it22": n(ty["Interoperability & data sharing"][2022]), "it25": n(ty["Interoperability & data sharing"][2025]),
 "coord": fall(*tp_["Humanitarian coordination"]), "epi": fall(*tp_["Epidemics & disease control"]),
 "ref": fall(*tp_["Refugees & asylum"]), "cva": fall(*tp_["Cash & voucher assistance (CVA)"]),
 "clim": fall(*tp_["Climate, environment & energy"]), "drr": fall(*tp_["Disaster risk reduction & early warning"]),
 "res": fall(*tp_["Research, studies & evaluation"]),
 "clim25": fall(ty["Climate, environment & energy"][2024], ty["Climate, environment & energy"][2025]),
 "clim22": n(ty["Climate, environment & energy"][2022]), "clim24": n(ty["Climate, environment & energy"][2024]),
 "im": fall(_cc["Information Management"][2022], _cc["Information Management"][2025]),
 "cc_lo": str(_ccf[0]), "cc_hi": str(_ccf[-1]), "cc_n": str(len(_ccf)), "cc_tot": str(len(_cca)),
 "a25": n(_a25), "a26": n(_a26), "fall26": fall(_a25, _a26),
 "sc_lo": fall(float(_sc[1][14]), float(_sc[2][15])), "sc_hi": fall(float(_sc[1][14]), float(_sc[3][15])),
 "peak12": n(_roll),
}
json.dump(FACTS, open(OUT.replace("snapshot", "facts"), "w", encoding="utf-8"), indent=1)

# ---- facts for the prose ----
pc = lambda a, b: f"{(b / a - 1) * 100:+.1f}%"
T = dict(zip(YEARS, D["total"]))
F = dict(zip(D["funding"]["years"], D["funding"]["total"]))
print("TOTAL", T)
print("adverts 22-25", pc(T[2022], T[2025]), "| yoy", pc(T[2022], T[2023]), pc(T[2023], T[2024]), pc(T[2024], T[2025]))
print("FUNDING", F)
print("funding 22-25", pc(F[2022], F[2025]), "| yoy", pc(F[2022], F[2023]), pc(F[2023], F[2024]), pc(F[2024], F[2025]))
print("index 2025: adverts", round(T[2025] / T[2022] * 100, 1), "funding", round(F[2025] / F[2022] * 100, 1))
mj = dict(zip([m for m in months if m >= "2022-01"], D["monthly"]["jobs"]))
print("2024 monthly avg", round(T[2024] / 12), "| Jan25", mj["2025-01"], "Feb25", mj["2025-02"], pc(mj["2025-01"], mj["2025-02"]))
f25 = [mj[f"2025-{m:02d}"] for m in range(2, 12)]
print("Feb-Nov 2025 avg", round(sum(f25) / 10), "min", min(f25), "max", max(f25), "| Dec25", mj["2025-12"])
a25 = sum(mj[f"2025-{m:02d}"] for m in range(1, 11)); a26 = sum(mj[f"2026-{m:02d}"] for m in range(1, 11))
print("Jan-Oct 2025", a25, "Jan-Oct 2026", a26, pc(a25, a26))
roll = [(sum(t["jobs"][i - 11:i + 1]), months[i]) for i in range(11, len(months))]
print("12m rolling peak", max(roll))
for name in ("job_type", "experience"):
    for k, v in D[name].items():
        y = dict(zip(YEARS, v))
        print(f"{name:11} {k:12} 22-25 {pc(y[2022], y[2025])} yoy {pc(y[2022], y[2023])} {pc(y[2023], y[2024])} {pc(y[2024], y[2025])}"
              f" share22 {y[2022] / T[2022] * 100:.1f} share25 {y[2025] / T[2025] * 100:.1f} n {y[2022]} {y[2025]}")
for k, a, b in sorted(D["org_type"], key=lambda x: x[2] / x[1]):
    print(f"org {k:36} {a:6} {b:6} {pc(a, b)}")
for c, a21, a, b in sorted(D["countries"], key=lambda x: x[3] / x[2]):
    print(f"country {c[:40]:40} 2021 {a21:5} 2022 {a:5} 2025 {b:5} {pc(a, b)}  vs2021 {pc(a21, b) if a21 else 'n/a'}")
for c in ("Poland", "Occupied Palestinian territory", "Myanmar", "Syrian Arab Republic"):
    print(c, {y: cy[c].get(y, 0) for y in range(2021, 2027)})
tp = sorted(D["topics"], key=lambda x: x[2] / x[1])
print("n topics", len(tp))
for k, a, b in tp[:8] + tp[-8:]:
    print(f"topic {k:46} {a:5} {b:5} {pc(a, b)}")
cc = dims["career_category"]
for k, v in cc.items():
    y = dict(zip(YEARS, v))
    if y[2022] >= 500: print(f"career {k:44} {y[2022]:6} {y[2025]:6} {pc(y[2022], y[2025])}")
sc = list(csv.reader(open(f"{GHA}/fig-1.2-scenarios.csv", encoding="utf-8-sig")))
pub25 = float(sc[1][14]); print("scenarios", pc(pub25, float(sc[2][15])), pc(pub25, float(sc[3][15])))
rec = list(csv.DictReader(open(f"{GHA}/fig-2.1-recipients.csv", encoding="utf-8-sig")))
print("recipients up in 2025:", [(x["recipient"], x["change_25_24"]) for x in rec if not x["change_25_24"].startswith("-")], "of", len(rec))
