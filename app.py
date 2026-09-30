"""
Chronic disease risk calculator - Stage 3 chatbot
TFM

Run with:  streamlit run app.py

Needs in this folder: stage2_engine.py, A1_Base.csv, A2_County.csv, B_RR.csv,
stage1_models.pkl. If any is missing the app shows a red banner and runs on
demo numbers instead.

All category strings below are verified against B_RR.csv.
"""

import math

import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Risk calculator", layout="centered")

# ---------------------------------------------------------------- constants

COUNTIES = [
    "Alameda", "Alpine", "Amador", "Butte", "Calaveras", "Colusa", "Contra Costa",
    "Del Norte", "El Dorado", "Fresno", "Glenn", "Humboldt", "Imperial", "Inyo",
    "Kern", "Kings", "Lake", "Lassen", "Los Angeles", "Madera", "Marin", "Mariposa",
    "Mendocino", "Merced", "Modoc", "Mono", "Monterey", "Napa", "Nevada", "Orange",
    "Placer", "Plumas", "Riverside", "Sacramento", "San Benito", "San Bernardino",
    "San Diego", "San Francisco", "San Joaquin", "San Luis Obispo", "San Mateo",
    "Santa Barbara", "Santa Clara", "Santa Cruz", "Shasta", "Sierra", "Siskiyou",
    "Solano", "Sonoma", "Stanislaus", "Sutter", "Tehama", "Trinity", "Tulare",
    "Tuolumne", "Ventura", "Yolo", "Yuba",
]

# keys match the Condition column in B_RR.csv
CONDITIONS = {
    "Type 2 diabetes": "Type 2 diabetes",
    "Hypertension": "High blood pressure",
    "Coronary Heart Disease": "Heart disease",
    "Stroke": "Stroke",
}

COL_NOW = "Likely to have it today"
COL_FUTURE = "Chance of developing it in 10 years"

# Factor name in B_RR.csv -> what the person sees
DISPLAY = {
    "Smoking": "Smoking",
    "BMI": "Weight",
    "Physical activity": "Exercise",
    "Sleep": "Sleep",
    "Alcohol consumption": "Alcohol",
    "Diet": "Sugary drinks",
    "Family history": "Family history",
    "Pregnancy complications": "Pregnancy history",
    "Working hours": "Work hours",
    "Shift work": "Night shifts",
    "Depression": "Mood",
    "Sleep apnea": "Sleep apnea",
    "Coffee consumption": "Coffee",
    "Sodium intake": "Salt",
    "Social isolation": "Loneliness",
    "Cannabis consumption": "Cannabis",
    "Education": "Education",
}

N_STEPS = 4

# ------------------------------------------------------------ binning rules
# Every string returned here is verified against the Category column of
# B_RR.csv. A mismatch does not error, it silently returns 1.0.


def bmi_from_height_weight(height_cm, weight_kg):
    if not height_cm or not weight_kg:
        return None
    return weight_kg / ((height_cm / 100) ** 2)


def bmi_to_category(bmi):
    if bmi is None:
        return None
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    if bmi < 35:
        return "Obese I"
    return "Obese II+"


def activity_to_category(minutes_per_week):
    """Minutes of moderate activity -> MET-min/week at 4 METs."""
    if minutes_per_week is None:
        return None
    met_min = minutes_per_week * 4
    if met_min < 600:
        return "Low"
    if met_min < 4000:
        return "Moderate"
    return "High"


def sleep_to_category(hours):
    if hours is None:
        return None
    if hours < 7:
        return "Short"
    if hours <= 8:
        return "Normal"
    return "Long"


def alcohol_to_category(drinks_per_week):
    if drinks_per_week is None:
        return None
    per_day = drinks_per_week / 7
    if per_day == 0:
        return "None"
    if per_day < 3:
        return "Moderate"
    return "Heavy"


def diet_to_category(servings_per_day):
    """Sugary drinks. The factor is called Diet in B_RR.csv."""
    if servings_per_day is None:
        return None
    if servings_per_day == 0:
        return "None/rarely"
    if servings_per_day <= 1:
        return "Moderate"
    return "High"


def coffee_to_category(cups_per_day):
    if cups_per_day is None:
        return None
    if cups_per_day < 2:
        return "None/rare"
    if cups_per_day <= 3:
        return "Moderate"
    return "High"


def workhours_to_category(hours):
    if hours is None:
        return None
    if hours <= 40:
        return "Standard"
    if hours <= 54:
        return "Long"
    return "Very long"


def family_to_category(answer):
    """UI wording -> B_RR labels."""
    return {"Nobody": "None",
            "One of them": "One",
            "Two or more": "Two or more"}.get(answer)


def age_to_band(age):
    if age < 35:
        return "18-34"
    if age < 50:
        return "35-49"
    if age < 65:
        return "50-64"
    return "65+"


# --------------------------------------------------------------- state


def init_state():
    if "step" not in st.session_state:
        st.session_state.step = 0
    if "a" not in st.session_state:
        st.session_state.a = {}


def goto(n):
    st.session_state.step = n
    st.rerun()


# --------------------------------------------------------- profile builder


def build_profile(a):
    """Raw answers -> the dict the Stage 2 engine expects.

    Keys are the Factor names from B_RR.csv. Anything left as None is
    dropped, falls to the reference category, and is reported on screen
    as treated as average.
    """
    bmi = bmi_from_height_weight(a.get("height_cm"), a.get("weight_kg"))

    profile = {
        # stratifiers
        "age_band": age_to_band(a["age"]),
        "sex": a["sex"],
        "race": a["race"],
        "county": a["county"],
        # required
        "Smoking": a.get("smoking"),
        "BMI": bmi_to_category(bmi),
        "Physical activity": activity_to_category(a.get("activity_min")),
        "Education": a.get("education"),
        # family history, one answer per condition
        "Family history": {c: family_to_category(a.get(f"fam_{c}"))
                           for c in CONDITIONS},
        # female branch
        "Pregnancy complications": (
            {"Type 2 diabetes": a.get("preg_gdm"), "Hypertension": a.get("preg_htn"),
             "Coronary Heart Disease": a.get("preg_htn"), "Stroke": a.get("preg_htn")}
            if a.get("sex") == "Female" else None),
        # optional
        "Sleep": sleep_to_category(a.get("sleep_hours")),
        "Sleep apnea": a.get("sleep_apnea"),
        "Alcohol consumption": alcohol_to_category(a.get("drinks_week")),
        "Diet": diet_to_category(a.get("ssb_day")),
        "Coffee consumption": coffee_to_category(a.get("coffee_day")),
        "Sodium intake": a.get("salt"),
        "Depression": a.get("depression"),
        "Shift work": a.get("shift_work"),
        "Working hours": workhours_to_category(a.get("work_hours")),
        "Social isolation": a.get("isolation"),
        "Cannabis consumption": a.get("cannabis"),
    }
    return {k: v for k, v in profile.items() if v is not None}, bmi


def stage1_features(a, bmi):
    """The six Stage 1 predictors, in training column order."""
    # Codes match stage1_datacleaning: smoking 0 never / 1 former / 2 current,
    # fin_strain 0 almost never ... 3 very often, binaries 1 = yes
    smoking_code = {"Never": 0, "Former": 1, "Current": 2}
    strain_code = {"Almost never": 0, "Now and then": 1,
                   "Fairly often": 2, "Very often": 3}
    return {
        "smoking": smoking_code.get(a.get("smoking"), 0),
        "bmi": bmi,
        "activity": 1 if (a.get("activity_min") or 0) >= 150 else 0,
        "binge": 1 if a.get("binge") == "Yes" else 0,
        "insured": 1 if a.get("insured") == "Yes" else 0,
        "fin_strain": strain_code.get(a.get("fin_strain"), 0),
    }


# ------------------------------------------------------- contribution split


def contribution_shares(breakdown):
    """RRs multiply, so decompose on the log scale: log R = sum(log RR).

    Reference factors sit at RR 1.0 -> log 0 -> no slice.
    Protective factors come out negative and are reported separately.
    """
    logs = {f: math.log(rr) for f, rr in breakdown.items() if rr and rr > 0}
    up = {f: v for f, v in logs.items() if v > 0.001}
    down = {f: rr for f, rr in breakdown.items() if rr and rr < 0.999}
    total = sum(up.values())
    shares = {DISPLAY.get(f, f): v / total for f, v in up.items()} if total else {}
    return dict(sorted(shares.items(), key=lambda x: -x[1])), down


def build_slices(breakdown, cutoff=0.03):
    """Collapse small slices into one, keeping their detail for the hover."""
    shares, protective = contribution_shares(breakdown)
    rr_by_name = {DISPLAY.get(f, f): rr for f, rr in breakdown.items()}

    big = {k: v for k, v in shares.items() if v >= cutoff}
    small = {k: v for k, v in shares.items() if v < cutoff}

    labels = list(big)
    values = list(big.values())
    hovers = [f"<b>{k}</b><br>{v:.0%} of your added risk"
              f"<br>multiplies by {rr_by_name.get(k, 1):.2f}"
              for k, v in big.items()]

    if small:
        labels.append("Everything else")
        values.append(sum(small.values()))
        inner = "<br>".join(f"{k} &mdash; {v:.0%}" for k, v in small.items())
        hovers.append(f"<b>Everything else</b> &mdash; {sum(small.values()):.0%}"
                      f"<br><br>{inner}")

    return labels, values, hovers, protective


# ------------------------------------------------------------- model calls
# PLUG IN. Both fall back to stubs so the app runs before they exist.


LOAD_ERRORS = []

# Stage 1 model keys (training labels) -> app condition keys
S1_KEYS = {"diabetes": "Type 2 diabetes", "hypertension": "Hypertension",
           "chd": "Coronary Heart Disease", "stroke": "Stroke"}


@st.cache_resource
def load_engine():
    try:
        import stage2_engine
        return stage2_engine, None
    except Exception as e:
        return None, f"Stage 2 engine not loaded: {e}"


@st.cache_resource
def load_stage1():
    try:
        import joblib
        from pathlib import Path
        return joblib.load(Path(__file__).parent / "stage1_models.pkl"), None
    except Exception as e:
        return None, f"Stage 1 models not loaded: {e}"


def run_stage2(profile):
    engine, err = load_engine()
    if engine is not None:
        return engine.project_all(profile)
    LOAD_ERRORS.append(err)
    # Deliberately different per condition, roughly in line with B_RR.csv,
    # so the chart behaves the way it will once the real engine is in.
    stub = {
        "Type 2 diabetes": {
            "BMI": 4.56, "Family history": 2.60, "Physical activity": 1.30,
            "Smoking": 1.37, "Sleep": 1.10, "Coffee consumption": 0.82},
        "Hypertension": {
            "BMI": 2.40, "Family history": 1.80, "Sodium intake": 1.35,
            "Physical activity": 1.20, "Smoking": 1.00, "Sleep apnea": 1.30},
        "Coronary Heart Disease": {
            "Smoking": 2.44, "BMI": 1.70, "Family history": 1.60,
            "Physical activity": 1.25, "Social isolation": 1.08},
        "Stroke": {
            "Smoking": 1.90, "BMI": 1.45, "Family history": 1.30,
            "Physical activity": 1.20, "Sodium intake": 1.12},
    }
    return {c: {"risk": r, "p0": r / 2, "R": 2.0, "breakdown": stub[c]}
            for c, r in zip(CONDITIONS, [0.34, 0.58, 0.14, 0.07])}


def run_stage1(features):
    models, err = load_stage1()
    if models is not None:
        import pandas as pd
        X = pd.DataFrame([features])[["smoking", "bmi", "activity", "binge",
                                      "insured", "fin_strain"]]
        return {S1_KEYS[c]: float(m.predict_proba(X)[0, 1])
                for c, m in models.items()}
    LOAD_ERRORS.append(err)
    return dict(zip(CONDITIONS, [0.18, 0.41, 0.09, 0.03]))


# ------------------------------------------------------------------ screens


def screen_about():
    st.subheader("About you")
    a = st.session_state.a

    a["age"] = st.number_input("How old are you?", 18, 100, 45, key="age_w")
    a["sex"] = st.radio(
        "Sex assigned at birth", ["Male", "Female"],
        help="Used because the studies behind this tool report male and "
             "female separately.",
        horizontal=True, key="sex_w",
    )
    a["race"] = st.selectbox(
        "Which best describes you?",
        ["Hispanic or Latino", "White", "Black or African American",
         "Asian", "Another background"], key="race_w",
    )
    a["county"] = st.selectbox("Which California county do you live in?",
                               COUNTIES, index=COUNTIES.index("Los Angeles"),
                               key="county_w")

    units = st.radio("Units", ["Feet, inches and pounds", "Centimetres and kilos"],
                     horizontal=True, key="units")

    if units == "Feet, inches and pounds":
        c1, c2, c3 = st.columns(3)
        ft = c1.number_input("Height (feet)", 3, 7, 5, key="ft")
        inch = c2.number_input("and inches", 0, 11, 6, key="inch")
        lb = c3.number_input("Weight (pounds)", 70, 450, 165, key="lb")
        a["height_cm"] = (ft * 12 + inch) * 2.54
        a["weight_kg"] = lb * 0.453592
    else:
        c1, c2 = st.columns(2)
        a["height_cm"] = c1.number_input("Height (cm)", 120, 220, 165, key="cm")
        a["weight_kg"] = c2.number_input("Weight (kg)", 35, 200, 70, key="kg")

    bmi = bmi_from_height_weight(a.get("height_cm"), a.get("weight_kg"))
    if bmi:
        st.caption(f"That's a BMI of {bmi:.1f}")


def screen_health():
    st.subheader("Your health so far")
    a = st.session_state.a

    a["diagnosed"] = st.multiselect(
        "Has a doctor ever told you that you have any of these?",
        list(CONDITIONS.values()),
        help="We will not project a condition you already have.",
        key="dx",
    )

    st.markdown("**Has a parent, brother or sister had any of these?**")
    fam_opts = ["Nobody", "One of them", "Two or more"]
    for key, label in CONDITIONS.items():
        a[f"fam_{key}"] = st.selectbox(label, fam_opts, key=f"fam_{key}_w")

    if a.get("sex") == "Female":
        st.markdown("**Pregnancy history**")
        # Two questions: the diabetes RR is for gestational diabetes, the others
        # are for preeclampsia / high blood pressure in pregnancy
        a["preg_gdm"] = st.radio(
            "During a pregnancy, were you ever told you had diabetes?",
            ["No", "Yes"], horizontal=True, key="preg_gdm_w",
            help="Answer No if you have never been pregnant.",
        )
        a["preg_htn"] = st.radio(
            "During a pregnancy, were you ever told you had preeclampsia or "
            "high blood pressure?",
            ["No", "Yes"], horizontal=True, key="preg_htn_w",
            help="Answer No if you have never been pregnant.",
        )

    a["insured"] = st.radio("Do you have health insurance right now?",
                            ["Yes", "No"], horizontal=True, key="ins")


def screen_daily():
    st.subheader("Daily life")
    a = st.session_state.a

    a["smoking"] = st.radio(
        "Do you smoke cigarettes?",
        ["Never", "Former", "Current"],
        format_func=lambda x: {"Never": "Never smoked regularly",
                               "Former": "I used to, but I quit",
                               "Current": "Yes, currently"}[x],
        key="smoke",
    )
    a["activity_min"] = st.slider(
        "In a typical week, how many minutes of exercise that gets you "
        "breathing harder?", 0, 600, 90, step=15, key="act")
    a["education"] = st.selectbox(
        "What is the highest level of school you finished?",
        ["High", "Middle", "Low"],
        format_func=lambda x: {"High": "College degree or more",
                               "Middle": "High school or some college",
                               "Low": "Less than high school"}[x],
        key="edu",
    )


def screen_optional():
    st.subheader("A few more questions")
    st.caption("All optional. Anything you skip is treated as average, and we "
               "will tell you which ones those were.")
    a = st.session_state.a

    with st.expander("Sleep", expanded=True):
        a["sleep_hours"] = st.number_input("Hours of sleep on a typical night",
                                           0.0, 12.0, None, step=0.5, key="slp")
        a["sleep_apnea"] = st.radio("Ever been told you have sleep apnea?",
                                    ["No", "Yes"], index=None, horizontal=True, key="osa")

    with st.expander("Food and drink"):
        a["drinks_week"] = st.number_input("Alcoholic drinks in a typical week",
                                           0, 40, 0, key="alc")
        a["binge"] = st.radio(
            "In the last month, did you ever have 5 or more drinks "
            "(4 for women) in one sitting?", ["No", "Yes"],
            horizontal=True, key="binge_w")
        a["ssb_day"] = st.number_input(
            "Sugary drinks per day (soda, juice, energy drinks)", 0, 6, None,
            key="ssb")
        a["coffee_day"] = st.number_input("Cups of coffee per day", 0, 8, None,
                                          key="cof")
        a["salt"] = st.radio("How salty is your food, usually?",
                             ["Low", "Moderate", "High"],
                             format_func=lambda x: {"Low": "Not very",
                                                    "Moderate": "Somewhat",
                                                    "High": "Very"}[x],
                             index=None, horizontal=True, key="salt_w")

    with st.expander("Work and mood"):
        a["depression"] = st.radio(
            "Over the last two weeks, have you often felt down, depressed "
            "or hopeless?", ["No", "Yes"], index=None, horizontal=True, key="dep")
        a["shift_work"] = st.radio("Do you work nights or rotating shifts?",
                                   ["No", "Yes"], index=None, horizontal=True, key="shift")
        a["work_hours"] = st.number_input("Hours you usually work per week",
                                          0, 90, None, key="wh")
        a["isolation"] = st.radio("Do you often feel isolated or lonely?",
                                  ["No", "Yes"], index=None, horizontal=True, key="iso")
        a["cannabis"] = st.radio("Do you use cannabis daily or near daily?",
                                 ["No/rare", "Yes"], horizontal=True, key="thc")
        a["fin_strain"] = st.select_slider(
            "How often do you worry about keeping up with rent or mortgage?",
            ["Almost never", "Now and then", "Fairly often", "Very often"],
            key="fin")


def screen_results():
    a = st.session_state.a
    profile, bmi = build_profile(a)
    s2 = run_stage2(profile)
    s1 = run_stage1(stage1_features(a, bmi))

    for err in LOAD_ERRORS:
        st.error(f"DEMO NUMBERS. {err}")

    st.subheader("Your results")
    st.caption("These two numbers answer different questions. Neither is a "
               "diagnosis.")

    header = st.columns([1.4, 1, 1])
    header[1].caption(COL_NOW)
    header[2].caption(COL_FUTURE)

    for key, label in CONDITIONS.items():
        already = label in a.get("diagnosed", [])
        c = st.columns([1.4, 1, 1])
        c[0].markdown(f"**{label}**")
        c[1].markdown(f"### {s1[key]:.0%}")
        if already:
            c[2].caption("Already diagnosed, so we do not project this one.")
        else:
            shown = f"{s2[key]['risk']:.0%}"
            if s2[key].get("capped"):
                shown += "+"
            c[2].markdown(f"### {shown}")
        st.divider()

    st.caption("How to read the 10-year column: high blood pressure means reaching "
               "130/80 or above, which many people do before they are diagnosed. "
               "For heart disease, the 10-year column is the chance of a heart attack; "
               "the today column covers any kind of heart disease.")

    with st.expander("What is driving these numbers"):
        pick = st.selectbox("Condition", list(CONDITIONS.values()), key="pick")
        key = [k for k, v in CONDITIONS.items() if v == pick][0]
        d = s2[key]

        st.write(f"Starting point for someone your age, sex, background and "
                 f"county with no major risk factors: **{d['p0']:.1%}**")
        st.write(f"Everything about your daily life multiplies that by "
                 f"**{d['R']:.2f}**")

        labels, values, hovers, protective = build_slices(d["breakdown"])

        if labels:
            fig = go.Figure(go.Pie(
                labels=labels, values=values, hole=0.45, sort=False,
                hovertext=hovers, hovertemplate="%{hovertext}<extra></extra>",
                textposition="inside", textinfo="label+percent",
                texttemplate="%{label}<br>%{percent:.0%}",
                insidetextorientation="horizontal",
            ))
            fig.update_layout(showlegend=False, height=360,
                              margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Hover any slice for detail. This shows what is adding "
                       "to your risk on top of the starting point for someone "
                       "your age and background.")
        else:
            st.write("Nothing in your answers is pushing your risk above the "
                     "starting point for someone your age and background.")

        if protective:
            names = ", ".join(DISPLAY.get(f, f).lower() for f in protective)
            st.success(f"Working in your favour: {names}")

        skipped = [DISPLAY[f] for f in DISPLAY if f not in profile
                   and not (f == "Pregnancy complications" and a.get("sex") != "Female")]
        if skipped:
            st.caption("Treated as average: " + ", ".join(skipped))

    st.info("This tool estimates risk from population patterns. It cannot tell "
            "you whether you personally will develop a condition. Talk to a "
            "doctor about anything that concerns you.")

    if st.button("Start over"):
        st.session_state.clear()
        st.rerun()


# ------------------------------------------------------------------- router

init_state()
st.title("Chronic disease risk calculator")

SCREENS = [screen_about, screen_health, screen_daily, screen_optional]
step = st.session_state.step

if step < N_STEPS:
    st.progress(step / N_STEPS, text=f"Step {step + 1} of {N_STEPS}")
    SCREENS[step]()
    st.write("")
    left, right = st.columns(2)
    if step > 0 and left.button("Back", use_container_width=True):
        goto(step - 1)
    label = "See my results" if step == N_STEPS - 1 else "Next"
    if right.button(label, type="primary", use_container_width=True):
        goto(step + 1)
else:
    screen_results()