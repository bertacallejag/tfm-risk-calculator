"""
Stage 2 risk engine, packaged for the Streamlit app.
Same logic as RiskEngine.ipynb:
    final p0 = base p0 (Table A1) x county multiplier (Table A2)
    R        = product of Table B relative risks (missing -> 1.0)
    risk     = min(CAP, 1 - (1 - final p0) ** R)

Needs A1_Base.csv, A2_County.csv and B_RR.csv in the same folder as this file.
"""

from pathlib import Path
import pandas as pd

HERE = Path(__file__).parent
CAP = 0.90
CONDITIONS = ["Type 2 diabetes", "Hypertension", "Coronary Heart Disease", "Stroke"]
STRATIFIERS = {"age_band", "sex", "race", "county"}


def _clean_dash(s):
    return s.astype(str).str.replace("\u2013", "-").str.replace("\u2014", "-").str.strip()


# keep_default_na=False so the reference category "None" is not turned into NaN
base = pd.read_csv(HERE / "A1_Base.csv", sep=";", keep_default_na=False)
county = pd.read_csv(HERE / "A2_County.csv", sep=";", keep_default_na=False)
rr = pd.read_csv(HERE / "B_RR.csv", sep=";", keep_default_na=False)

base["Age Band"] = _clean_dash(base["Age Band"])
base["Base 10-yr incidence p0"] = pd.to_numeric(base["Base 10-yr incidence p0"])
county["Multiplier"] = pd.to_numeric(county["Multiplier"])
rr["RR"] = pd.to_numeric(rr["RR"])

# fast lookups, built once
P0 = {(r["Condition"], r["Age Band"], r["Sex"], r["Race/Ethnicity"]): r["Base 10-yr incidence p0"]
      for _, r in base.iterrows()}
COUNTY_MULT = {(r["Condition"], str(r["County"]).strip().lower()): r["Multiplier"]
               for _, r in county.iterrows()}
RR_LOOKUP = {(r["Condition"], r["Factor"], r["Category"]): r["RR"] for _, r in rr.iterrows()}

RACES = sorted(base["Race/Ethnicity"].unique())


def _race_label(app_race):
    """App wording -> Table A label. Returns None for 'Another background'."""
    low = {r: r.lower() for r in RACES}
    if app_race.startswith("Hispanic"):
        hits = [r for r, l in low.items() if "hispanic" in l and "non" not in l]
    elif app_race == "White":
        hits = [r for r, l in low.items() if "white" in l]
    elif app_race.startswith("Black"):
        hits = [r for r, l in low.items() if "black" in l]
    elif app_race == "Asian":
        hits = [r for r, l in low.items() if "asian" in l]
    else:
        return None
    return hits[0] if hits else None


def get_p0(condition, age_band, sex, app_race):
    race = _race_label(app_race)
    if race is not None:
        return P0[(condition, age_band, sex, race)]
    # "Another background": NH Other was dropped from Table A,
    # so use the simple mean of the four race groups for that age and sex
    vals = [P0[(condition, age_band, sex, r)] for r in RACES
            if (condition, age_band, sex, r) in P0]
    return sum(vals) / len(vals)


def get_county_mult(condition, county_name):
    return COUNTY_MULT.get((condition, county_name.strip().lower()), 1.0)


def factor_rr(condition, factor, value):
    """RR for one factor. Dict values are condition specific (family history)."""
    category = value.get(condition) if isinstance(value, dict) else value
    if category is None:
        return None
    return RR_LOOKUP.get((condition, factor, category), 1.0)


def project(condition, profile):
    p0 = get_p0(condition, profile["age_band"], profile["sex"], profile["race"])
    final_p0 = p0 * get_county_mult(condition, profile["county"])

    breakdown = {}
    for factor, value in profile.items():
        if factor in STRATIFIERS:
            continue
        v = factor_rr(condition, factor, value)
        if v is not None:
            breakdown[factor] = v

    R = 1.0
    for v in breakdown.values():
        R *= v

    raw = 1 - (1 - final_p0) ** R
    return {"risk": float(min(CAP, raw)), "capped": raw > CAP,
            "p0": float(final_p0), "R": float(R), "breakdown": breakdown}


def project_all(profile):
    return {c: project(c, profile) for c in CONDITIONS}


def check_labels(profile_values):
    """Pass {factor: [categories the app can send]}; prints any that B_RR.csv
    does not contain (those would silently count as 1.0)."""
    ok = True
    for factor, cats in profile_values.items():
        for cond in CONDITIONS:
            known = set(rr[(rr["Condition"] == cond) & (rr["Factor"] == factor)]["Category"])
            if not known:
                continue
            for c in cats:
                if c not in known:
                    ok = False
                    print(f"MISSING  {cond} | {factor} | {c!r}   (B_RR has {sorted(known)})")
    print("All labels match." if ok else "Fix the rows above.")
