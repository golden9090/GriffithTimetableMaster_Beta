import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import re
import hashlib
import colorsys
from datetime import datetime

st.warning("**IMPORTANT**: THIS SITE IS A BETA VERSION OF GRIFFIX FEATURES, AND ONLY INCLUDES **EXPERIMENTAL FEATURES UNDERGOING TESTING**. ACCESS THE OFFICIAL VERSION OF GRIFFIX [HERE](https://griffix.streamlit.app)")


# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & STATE (CLEAN START)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Griffix Degree Planner",
    layout="wide",
    page_icon="Picture1.png",
    initial_sidebar_state="expanded"
)

# Start with a clean, empty state
if "holding_zone" not in st.session_state:
    st.session_state.holding_zone = []

if "plan" not in st.session_state:
    # Schema: {(year, trimester): [course_code, ...]}
    st.session_state.plan = {}

if "selected_course" not in st.session_state:
    st.session_state.selected_course = None

if "last_action_token" not in st.session_state:
    st.session_state.last_action_token = None

if "feedback_message" not in st.session_state:
    st.session_state.feedback_message = None

# -----------------------------------------------------------------------------
# 2. COURSE METADATA & LIVE SEARCH / CACHE ENGINE
# -----------------------------------------------------------------------------
def extract_course_codes(text: str):
    """Finds valid Griffith course codes."""
    if not text:
        return []
    pattern = r'\b(?:[0-9]{4}[A-Z]{3,4}(?:_[A-Z0-9]+)?|[A-Z]{3}[0-9]{3})\b'
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(m.upper() for m in matches))

def extract_prereqs(desc: str):
    if not desc:
        return []
    match = re.search(r'(?:pre-?requisite(?:s)?|advised prerequisite(?:s)?|prior knowledge of)\s*[:\-]?\s*([^.;\n]+)', desc, re.I)
    if match:
        chunk = match.group(1)
        if "nil" in chunk.lower() or "none" in chunk.lower():
            return []
        return extract_course_codes(chunk)
    return []

def extract_coreqs(desc: str):
    if not desc:
        return []
    match = re.search(r'(?:co-?requisite(?:s)?)\s*[:\-]?\s*([^.;\n]+)', desc, re.I)
    if match:
        chunk = match.group(1)
        if "nil" in chunk.lower() or "none" in chunk.lower():
            return []
        return extract_course_codes(chunk)
    return []

def extract_incompatibles(desc: str):
    if not desc:
        return []
    match = re.search(r'(?:incompatible(?:s)?)\s*[:\-]?\s*([^.;\n]+)', desc, re.I)
    if match:
        return extract_course_codes(match.group(1))
    return []

@st.cache_data(ttl=86400, show_spinner=False)
def load_full_catalog():
    """
    Fetches courses directly from Griffith's search endpoint with pagination
    and caches the result for 24 hours.
    """
    catalog = {}
    headers = {
        'User-Agent': 'Griffix-Live-Degree-Planner-StudentProject (Contact: yiming.qu@griffithuni.edu.au)',
        'Accept': 'application/json, text/plain, */*'
    }
    base_url = "https://search.griffith.edu.au/s/search.json?collection=griff~sp-courses-api&profile=courses&sort=metafborderna"
    
    start_rank = 1
    num_ranks = 800

    while True:
        url = f"{base_url}&num_ranks={num_ranks}&start_rank={start_rank}"
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                break
            data = resp.json()
        except Exception:
            break

        results_summary = data.get("response", {}).get("resultsSummary", {})
        results = data.get("response", {}).get("resultPacket", {}).get("results", [])

        if not results:
            break

        for item in results:
            meta = item.get("listMetadata", {})
            cat_numbers = meta.get("categoryNumber", [])
            if not cat_numbers:
                continue
            code = str(cat_numbers[0]).replace(" ", "").upper().strip()
            title = meta.get("title", [code])[0]
            cp = meta.get("creditPoints", ["10"])[0]
            desc = meta.get("description", [""])[0] or ""
            offerings = meta.get("nextOffering", [])
            career = meta.get("academicCareerName", ["Undergraduate"])[0]
            group = meta.get("academicGrpDescription", ["Other"])[0]

            catalog[code] = {
                "code": code,
                "title": title,
                "credit_points": cp,
                "description": desc,
                "offerings": list(set(offerings)),
                "career": career,
                "group": group,
                "prereqs": extract_prereqs(desc),
                "coreqs": extract_coreqs(desc),
                "incompatibles": extract_incompatibles(desc)
            }

        total_matching = results_summary.get("totalMatching", 0)
        curr_end = results_summary.get("currEnd", start_rank + len(results) - 1)
        next_start = results_summary.get("nextStart")

        if not next_start or curr_end >= total_matching:
            break
        start_rank = next_start

    return catalog

def format_offerings_label(offerings_list):
    """Converts ['Trimester 2', 'Summer Semester'] -> 'T2/T3'."""
    if not offerings_list:
        return "TBA"
    formatted = []
    offs_lower = [str(o).lower() for o in offerings_list]
    if any("trimester 1" in o or "t1" in o for o in offs_lower):
        formatted.append("T1")
    if any("trimester 2" in o or "t2" in o for o in offs_lower):
        formatted.append("T2")
    if any("summer" in o or "trimester 3" in o or "t3" in o for o in offs_lower):
        formatted.append("T3")
    return "/".join(formatted) if formatted else "/".join([str(o) for o in offerings_list])

@st.cache_data(ttl=86400, show_spinner=False)
def load_full_catalog():
    """Fetches all courses from Griffith search API with standard browser headers."""
    catalog = {}
    url = "https://search.griffith.edu.au/s/search.json?collection=griff~sp-courses-api&profile=courses&num_ranks=3000&start_rank=1&sort=metafborderna"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("response", {}).get("resultPacket", {}).get("results", [])
            for item in results:
                meta = item.get("listMetadata", {})
                cat_numbers = meta.get("categoryNumber", [])
                if not cat_numbers:
                    continue
                code = str(cat_numbers[0]).replace(" ", "").upper().strip()
                title = meta.get("title", [code])[0]
                cp = meta.get("creditPoints", ["10"])[0]
                desc = meta.get("description", [""])[0] or ""
                offerings = meta.get("nextOffering", [])
                career = meta.get("academicCareerName", ["Undergraduate"])[0]
                group = meta.get("academicGrpDescription", ["Other"])[0]

                catalog[code] = {
                    "code": code,
                    "title": title,
                    "credit_points": cp,
                    "description": desc,
                    "offerings": list(set(offerings)),
                    "career": career,
                    "group": group,
                    "prereqs": extract_prereqs(desc),
                    "coreqs": extract_coreqs(desc),
                    "incompatibles": extract_incompatibles(desc)
                }
    except Exception as e:
        print(f"Catalog fetch error: {e}")
    return catalog

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_course_from_curriculum_api(clean_code: str, selected_year: int, catalog_offerings: list):
    subscription_key = "b8ae10d400ef42f89a127abe4a760e46"
    
    offs_lower = [str(o).lower() for o in catalog_offerings]
    if any("trimester 1" in o or "t1" in o for o in offs_lower):
        primary_term = "3261"
    elif any("trimester 2" in o or "t2" in o for o in offs_lower):
        primary_term = "3265"
    elif any("summer" in o or "trimester 3" in o or "t3" in o for o in offs_lower):
        primary_term = "3268"
    else:
        primary_term = "3261"

    terms_to_try = [primary_term] + [t for t in ["3261", "3265", "3268"] if t != primary_term]

    current_year = datetime.now().year
    search_year = min(selected_year, current_year)
    years_to_try = [search_year, search_year - 1]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Origin": "https://my.griffith.edu.au",
        "Referer": "https://my.griffith.edu.au/"
    }

    for yr in years_to_try:
        for term_code in terms_to_try:
            url = f"https://api-lt.griffith.edu.au/curriculumapi/v1/course/{clean_code}/{yr}/{term_code}?subscription-key={subscription_key}"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    mapped = data.get("mappedData", {}).get("components", {})

                    prereqs, coreqs, incompatibles = [], [], []
                    req_obj = mapped.get("crseRequiste", {}).get("value", {})
                    if isinstance(req_obj, dict):
                        for r in req_obj.get("requisites", []):
                            rtype = str(r.get("type", "")).upper()
                            combined_text = f"{r.get('ruleDefinition', '')} {r.get('ruleSummary', '')}"
                            codes = extract_course_codes(combined_text)
                            if "PRE" in rtype:
                                prereqs.extend(codes)
                            elif "CO" in rtype:
                                coreqs.extend(codes)
                            elif "ANTI" in rtype:
                                incompatibles.extend(codes)

                    other_req = mapped.get("crseOthrRequiste", {}).get("value")
                    if other_req and isinstance(other_req, str):
                        prereqs.extend(extract_course_codes(other_req))

                    prereqs = [p for p in dict.fromkeys(prereqs) if p != clean_code]
                    coreqs = [c for c in dict.fromkeys(coreqs) if c != clean_code]
                    incompatibles = [i for i in dict.fromkeys(incompatibles) if i != clean_code]

                    # Extract offerings from curriculum API if catalog had none
                    final_offerings = list(catalog_offerings)
                    if not final_offerings:
                        tri_val = mapped.get("crseTri", {}).get("value", [])
                        if isinstance(tri_val, list): final_offerings.extend(tri_val)
                        elif isinstance(tri_val, str): final_offerings.append(tri_val)

                        ofrg_tbl = mapped.get("crseOfrg2CrseOfrg", {}).get("value", {})
                        if isinstance(ofrg_tbl, dict):
                            for row in ofrg_tbl.get("rows", []):
                                is_y = row.get("crseOfrg2Ofrd", {}).get("key") == "Y" or row.get("crseOfrg2Ofrd", {}).get("value") == "YES"
                                p_str = row.get("crseOfrg2TchngPeriod", {}).get("value")
                                if is_y and p_str and p_str not in final_offerings:
                                    final_offerings.append(p_str)

                    title = data.get("name") or mapped.get("crseShrtDescr", {}).get("value") or clean_code
                    cp_val = mapped.get("crseAwrdCrdtPnts", {}).get("value", {})
                    cp = str(cp_val.get("value", 10) if isinstance(cp_val, dict) else data.get("unitsMinimum", 10))
                    desc = mapped.get("crseDescr", {}).get("value", "")

                    return {
                        "code": clean_code,
                        "title": title,
                        "credit_points": cp,
                        "description": desc,
                        "offerings": list(dict.fromkeys(final_offerings)),
                        "career": data.get("subtype", "Undergraduate"),
                        "group": data.get("orgParent", "Other"),
                        "prereqs": prereqs,
                        "coreqs": coreqs,
                        "incompatibles": incompatibles
                    }
            except Exception:
                continue

    return None

catalog = load_full_catalog()

def lookup_course(clean_code: str, selected_year: int = None):
    if selected_year is None:
        selected_year = datetime.now().year

    catalog_entry = catalog.get(clean_code, {})
    offerings = catalog_entry.get("offerings", [])

    curriculum_meta = fetch_course_from_curriculum_api(clean_code, selected_year, offerings)
    if curriculum_meta:
        catalog[clean_code] = curriculum_meta
        return curriculum_meta

    if catalog_entry:
        return catalog_entry
    return None
    
# -----------------------------------------------------------------------------
# 3. OFFERING AVAILABILITY CHECKER
# -----------------------------------------------------------------------------
def is_course_offered_in_term(c_info: dict, trimester: int) -> bool:
    """Checks whether the course is actively scheduled in Trimester 1, 2, or 3."""
    if not c_info:
        return True
    offerings = c_info.get("offerings", [])
    if not offerings:
        return True  # If unknown, don't lock the student out
    offs_lower = [str(o).lower() for o in offerings]
    if trimester == 1:
        return any("trimester 1" in o or "t1" in o for o in offs_lower)
    elif trimester == 2:
        return any("trimester 2" in o or "t2" in o for o in offs_lower)
    elif trimester == 3:
        return any("summer" in o or "trimester 3" in o or "t3" in o for o in offs_lower)
    return False

# -----------------------------------------------------------------------------
# 4. PLAN VALIDATION ENGINE
# -----------------------------------------------------------------------------
def term_index(year: int, trimester: int) -> int:
    return (year - 1) * 3 + trimester

def validate_plan(plan: dict, catalog_dict: dict):
    warnings = {}    # {course_code: [warning_msg, ...]}
    satisfied = {}   # {course_code: [satisfied_msg, ...]}
    placed_coords = {}

    for (yr, tr), courses in plan.items():
        for c in courses:
            placed_coords[c] = (yr, tr)

    all_planned = set(placed_coords.keys())

    for (yr, tr), courses in plan.items():
        current_rank = term_index(yr, tr)
        for c in courses:
            c_warns = []
            c_sats = []
            info = catalog_dict.get(c) or lookup_course(c) or {}
            prereqs = info.get("prereqs", [])
            coreqs = info.get("coreqs", [])
            incomps = info.get("incompatibles", [])

            # 1. Offering Check
            if not is_course_offered_in_term(info, tr):
                c_warns.append(f"Not usually offered in Trimester {tr}")

            # 2. Prerequisite Check
            for p in prereqs:
                if p not in placed_coords:
                    c_warns.append(f"Missing Prerequisite: {p}")
                else:
                    p_yr, p_tr = placed_coords[p]
                    if term_index(p_yr, p_tr) < current_rank:
                        c_sats.append(f"Prerequisite satisfied: {p} (completed in Year {p_yr} T{p_tr})")
                    else:
                        c_warns.append(f"Prereq {p} must be completed before Year {yr} T{tr}")

            # 3. Corequisite Check
            for cr in coreqs:
                if cr not in placed_coords:
                    c_warns.append(f"Missing Corequisite: {cr}")
                else:
                    cr_yr, cr_tr = placed_coords[cr]
                    if term_index(cr_yr, cr_tr) <= current_rank:
                        c_sats.append(f"Corequisite satisfied: {cr} (enrolled Year {cr_yr} T{cr_tr})")
                    else:
                        c_warns.append(f"Coreq {cr} scheduled after Year {yr} T{tr}")

            # 4. Incompatibility Check
            for inc in incomps:
                if inc in all_planned and inc != c:
                    c_warns.append(f"Incompatible with {inc}")

            if c_warns:
                warnings[c] = c_warns
            if c_sats:
                satisfied[c] = c_sats

    return warnings, satisfied

plan_warnings, plan_satisfied = validate_plan(st.session_state.plan, catalog)

# -----------------------------------------------------------------------------
# 5. STREAMLIT-JS ACTION BRIDGE
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    div[data-testid="stTextInput"]:has(input[aria-label="Hidden Bridge Action"]) {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

bridge_input = st.text_input("Hidden Bridge Action", key="bridge_action_trigger", label_visibility="collapsed")

if bridge_input:
    parts = bridge_input.split("___")
    cmd = parts[0]
    token = parts[1] if len(parts) > 1 else None

    if token != st.session_state.last_action_token:
        st.session_state.last_action_token = token

        if cmd == "SELECT":
            code = parts[2]
            st.session_state.selected_course = None if st.session_state.selected_course == code else code

        elif cmd == "DESELECT":
            st.session_state.selected_course = None

        elif cmd == "PLACE":
            code = parts[2]
            target_yr = int(parts[3])
            target_tr = int(parts[4])

            c_info = catalog.get(code) or lookup_course(code)

            # Strictly enforce that courses can only be placed into open trimesters
            if is_course_offered_in_term(c_info, target_tr):
                if code in st.session_state.holding_zone:
                    st.session_state.holding_zone.remove(code)

                for slot, c_list in list(st.session_state.plan.items()):
                    if code in c_list:
                        c_list.remove(code)

                slot_courses = st.session_state.plan.setdefault((target_yr, target_tr), [])
                if code not in slot_courses and len(slot_courses) < 7:
                    slot_courses.append(code)

                st.session_state.selected_course = None

        elif cmd == "REMOVE_HOLDING":
            code = parts[2]
            if code in st.session_state.holding_zone:
                st.session_state.holding_zone.remove(code)
            if st.session_state.selected_course == code:
                st.session_state.selected_course = None

        elif cmd == "MOVE_TO_HOLDING":
            code = parts[2]
            yr = int(parts[3])
            tr = int(parts[4])
            if (yr, tr) in st.session_state.plan and code in st.session_state.plan[(yr, tr)]:
                st.session_state.plan[(yr, tr)].remove(code)
            if code not in st.session_state.holding_zone:
                st.session_state.holding_zone.append(code)
            st.session_state.selected_course = None

        st.rerun()

# -----------------------------------------------------------------------------
# 6. SIDEBAR: COURSE SEARCH & DIRECT STAGING
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("1. Add a Course")

    current_yr = datetime.now().year
    with st.form("course_search_form", clear_on_submit=True):
        course_code_input = st.text_input(
            "Course Code",
            placeholder="eg. 1001MSC",
            key="input_course_code"
        )
        planned_year = st.selectbox(
            "Which year are you planning to do the course?",
            options=list(range(current_yr, 2031)),
            index=0,
            key="planned_course_year"
        )
        submit_btn = st.form_submit_button("Add Course", type="primary")

    if submit_btn:
        st.session_state.feedback_message = None
        if not course_code_input:
            st.session_state.feedback_message = ("warning", "Please enter a course code.")
        else:
            clean_code = course_code_input.replace(" ", "").upper().strip()
            c_info = lookup_course(clean_code, planned_year)

            if c_info:
                already_in_holding = clean_code in st.session_state.holding_zone
                already_in_plan = any(clean_code in clist for clist in st.session_state.plan.values())

                if already_in_holding or already_in_plan:
                    st.session_state.feedback_message = ("warning", f"**{clean_code}** is already in your holding zone or plan.")
                else:
                    st.session_state.holding_zone.append(clean_code)
                    st.session_state.feedback_message = ("success", f"Added **{clean_code}** - {c_info['title']} to Holding Zone!")
            else:
                st.session_state.feedback_message = ("error", f"Could not find course '{clean_code}'. Ensure the code is correct.")
        st.rerun()

    # Display feedback message
    if st.session_state.feedback_message:
        msg_type, msg_text = st.session_state.feedback_message
        if msg_type == "success":
            st.success(msg_text)
        elif msg_type == "warning":
            st.warning(msg_text)
        else:
            st.error(msg_text)
        st.session_state.feedback_message = None

    st.divider()
    st.header("2. Degree Structure")
    num_years = st.slider("Degree Duration (Years)", min_value=1, max_value=5, value=3)
    include_t3 = st.checkbox("Include Trimester 3 (Summer)", value=True)

    st.divider()
    total_planned = sum(len(c) for c in st.session_state.plan.values())
    total_cp = sum(
        int((catalog.get(c) or lookup_course(c) or {}).get("credit_points", 10) or 10)
        for clist in st.session_state.plan.values() for c in clist
    )
    st.metric("Total Courses Planned", f"{total_planned}")
    st.metric("Total Credit Points", f"{total_cp} CP")

    if st.button("🗑️ Reset Entire Plan", use_container_width=True):
        st.session_state.plan = {}
        st.session_state.holding_zone = []
        st.session_state.selected_course = None
        st.rerun()

# -----------------------------------------------------------------------------
# 7. HTML, CSS & JS COMPONENT BUILDER
# -----------------------------------------------------------------------------
def string_to_pastel_hex(code_string: str) -> str:
    """Generates a deterministic pastel hex color from the course code."""
    clean_code = str(code_string).strip().upper()
    hash_digest = hashlib.md5(clean_code.encode()).hexdigest()
    hash_int = int(hash_digest[:8], 16)
    hue = (hash_int % 360) / 360.0
    saturation = 0.65
    lightness = 0.55
    rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
    return '#%02x%02x%02x' % tuple(int(x * 255) for x in rgb)

def build_planner_html(holding_zone, plan, catalog_dict, num_years, include_t3, selected_code, warnings_dict):
    trimesters = [1, 2, 3] if include_t3 else [1, 2]
    selected_meta = catalog_dict.get(selected_code) or (lookup_course(selected_code) if selected_code else None)

    html = """
    <style>
    :root {
        --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        --border-color: rgba(255, 255, 255, 0.15);
        --bg-color: #12151c;
        --card-border: rgba(255, 255, 255, 0.15);
        --text-color: #f7f9fa;
    }

    /* Completely eliminate all scrollbars */
    html, body {
        font-family: var(--font-family);
        color: var(--text-color);
        background: transparent;
        margin: 0;
        padding: 0;
        overflow: hidden !important;
    }

    * {
        box-sizing: border-box;
    }

    .planner-box {
        background: var(--bg-color);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.25);
        margin-bottom: 20px;
        overflow: visible !important;
    }

    .section-title {
        font-size: 13.5px;
        font-weight: 700;
        letter-spacing: 0.6px;
        color: #70a1ff;
        text-transform: uppercase;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
    }

    /* Course Cards */
    .course-card {
        position: relative;
        border-radius: 6px;
        padding: 9px 12px;
        cursor: pointer;
        user-select: none;
        overflow: hidden;
        border: 1px solid var(--card-border);
        box-sizing: border-box;
        margin-bottom: 9px;
        transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
    }

    .course-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 14px rgba(0, 0, 0, 0.4);
        border-color: rgba(255, 255, 255, 0.55);
    }

    .course-card.is-selected {
        border: 2px solid #2ed573 !important;
        box-shadow: 0 0 14px rgba(46, 213, 115, 0.8) !important;
        animation: pulse 1.8s infinite;
    }

    @keyframes pulse {
        0% { box-shadow: 0 0 4px rgba(46, 213, 115, 0.4); }
        50% { box-shadow: 0 0 16px rgba(46, 213, 115, 0.85); }
        100% { box-shadow: 0 0 4px rgba(46, 213, 115, 0.4); }
    }

    .card-top {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .card-code {
        font-weight: 800;
        font-size: 13px;
        letter-spacing: 0.5px;
        color: #ffffff;
    }

    .btn-close {
        color: rgba(255, 255, 255, 0.65);
        font-size: 16px;
        font-weight: bold;
        line-height: 1;
        padding: 2px 5px;
        border-radius: 4px;
        transition: all 0.15s ease;
    }

    .btn-close:hover {
        background: #ff4757;
        color: #ffffff;
    }

    .card-title {
        font-size: 11px;
        margin-top: 3px;
        color: rgba(255, 255, 255, 0.95);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .badges-row {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
        margin-top: 6px;
    }

    .badge-pill {
        font-size: 9px;
        padding: 2px 6px;
        border-radius: 4px;
        background: rgba(0, 0, 0, 0.35);
        color: #ffffff;
        font-weight: 600;
    }

    /* Solid warning & success badges with high-contrast white text */
    .warning-pill {
        background-color: #d63031 !important;
        color: #ffffff !important;
        border: none !important;
        font-size: 10px !important;
        padding: 4px 8px !important;
        border-radius: 4px !important;
        margin-top: 6px !important;
        display: inline-block !important;
        font-weight: 700 !important;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
    }

    .success-pill {
        background-color: #00b894 !important;
        color: #ffffff !important;
        border: none !important;
        font-size: 10px !important;
        padding: 4px 8px !important;
        border-radius: 4px !important;
        margin-top: 6px !important;
        display: inline-block !important;
        font-weight: 700 !important;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
    }

    /* Red outline & glowing shadow when prerequisite is unsatisfied */
    .course-card.has-prereq-error {
        border: 2px solid #ff4757 !important;
        box-shadow: 0 0 14px rgba(255, 71, 87, 0.9) !important;
    }

    .course-card.has-prereq-error.is-selected {
        border: 2px solid #ff4757 !important;
        box-shadow: 0 0 18px rgba(255, 71, 87, 1) !important;
        animation: pulse-red 1.6s infinite !important;
    }

    @keyframes pulse-red {
        0% { box-shadow: 0 0 6px rgba(255, 71, 87, 0.5); }
        50% { box-shadow: 0 0 20px rgba(255, 71, 87, 1); }
        100% { box-shadow: 0 0 6px rgba(255, 71, 87, 0.5); }
    }

    /* Fixed-width holding grid (prevents single courses from stretching 100%) */
    .holding-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, 230px);
        gap: 12px;
        min-height: 60px;
        padding: 12px;
        background: rgba(0, 0, 0, 0.25);
        border: 1px dashed var(--border-color);
        border-radius: 8px;
        overflow: visible !important;
    }
    
    /* Progression Matrix */
    .year-container {
        margin-top: 14px;
        border: 1px solid var(--border-color);
        border-radius: 8px;
        overflow: visible !important;
    }

    .year-heading {
        background: rgba(255, 255, 255, 0.08);
        padding: 8px 14px;
        font-weight: 800;
        font-size: 13px;
        letter-spacing: 0.5px;
        border-bottom: 1px solid var(--border-color);
    }

    .trimesters-row {
        display: flex;
        width: 100%;
        background: rgba(0, 0, 0, 0.15);
        overflow: visible !important;
    }

    .trim-col {
        flex: 1;
        border-right: 1px solid var(--border-color);
        padding: 12px;
        box-sizing: border-box;
        overflow: visible !important;
    }

    .trim-col:last-child {
        border-right: none;
    }

    .trim-header {
        font-size: 11.5px;
        font-weight: 700;
        margin-bottom: 10px;
        display: flex;
        justify-content: space-between;
        color: #a4b0be;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        padding-bottom: 5px;
    }

    /* Dynamic Slot Target: N + 1 up to 7 max */
    .slot-target {
        border: 1.5px dashed rgba(255, 255, 255, 0.2);
        border-radius: 6px;
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        color: rgba(255, 255, 255, 0.35);
        margin-bottom: 8px;
        transition: all 0.2s ease;
        box-sizing: border-box;
    }

    .slot-target.ready-for-placement {
        border-color: #2ed573;
        background: rgba(46, 213, 115, 0.12);
        color: #2ed573;
        font-weight: 700;
        cursor: pointer;
    }

    .slot-target.ready-for-placement:hover {
        background: rgba(46, 213, 115, 0.25);
        transform: scale(1.02);
    }

    .slot-target.slot-disabled {
        border-color: rgba(255, 75, 75, 0.25);
        background: rgba(255, 75, 75, 0.05);
        color: rgba(255, 75, 75, 0.55);
        cursor: not-allowed;
    }
    </style>

    <div class="planner-box">
        <div class="section-title">
            <span>📥 Course Holding Zone</span>
            <span style="font-size: 11px; font-weight: normal; color: #a4b0be;">
                Selected: <b style="color: #2ed573;">""" + (selected_code if selected_code else "None (Click course to select)") + """</b>
            </span>
        </div>
        <div class="holding-grid">
    """

    if not holding_zone:
        html += "<div style='color: rgba(255,255,255,0.4); font-size: 12px; grid-column: 1/-1;'>No courses in holding zone. Add a course from the sidebar to begin planning.</div>"

    for code in holding_zone:
        info = catalog_dict.get(code) or lookup_course(code) or {"title": code, "credit_points": "10", "offerings": [], "prereqs": [], "coreqs": [], "group": ""}
        bg = string_to_pastel_hex(code)
        is_sel = "is-selected" if code == selected_code else ""

        pr_text = f"Pre: {', '.join(info['prereqs'])}" if info["prereqs"] else "No Prereqs"
        cr_text = f" | Co: {', '.join(info['coreqs'])}" if info["coreqs"] else ""
        offs = format_offerings_label(info.get("offerings", []))

        html += f"""
        <div class="course-card {is_sel}" style="background-color: {bg};" onclick="onCourseClick('{code}')">
            <div class="card-top">
                <span class="card-code">{code}</span>
                <span class="btn-close" onclick="onRemoveHolding(event, '{code}')" title="Remove Course">&times;</span>
            </div>
            <div class="card-title" title="{info['title']}">{info['title']}</div>
            <div class="badges-row">
                <span class="badge-pill">{info.get('credit_points', '10')} CP</span>
                <span class="badge-pill">{offs}</span>
            </div>
            <div style="font-size: 9px; opacity: 0.85; margin-top: 5px;">{pr_text}{cr_text}</div>
        </div>
        """

    html += """
        </div>
    </div>
    """

    # Progression Matrix
    html += "<div class='planner-box'>"
    html += "<div class='section-title'>📅 Degree Progression Matrix</div>"

    for yr in range(1, num_years + 1):
        html += f"""
        <div class="year-container">
            <div class="year-heading">YEAR {yr}</div>
            <div class="trimesters-row">
        """
        for tr in trimesters:
            scheduled = plan.get((yr, tr), [])
            n_courses = len(scheduled)
            cp_sum = sum(int((catalog_dict.get(c) or lookup_course(c) or {}).get("credit_points", 10) or 10) for c in scheduled)
            t_title = f"Trimester {tr}" if tr in [1, 2] else "Trimester 3 (Summer)"

            # Check if armed course is available in this trimester
            is_valid_term = is_course_offered_in_term(selected_meta, tr) if selected_meta else False

            html += f"""
            <div class="trim-col">
                <div class="trim-header">
                    <span>{t_title}</span>
                    <span>{cp_sum} CP</span>
                </div>
            """

            # Render Scheduled Cards
            for c in scheduled:
                c_data = catalog_dict.get(c) or lookup_course(c) or {"title": c, "credit_points": "10", "offerings": [], "group": ""}
                bg = string_to_pastel_hex(c)
                is_sel = "is-selected" if c == selected_code else ""
                warns = warnings_dict.get(c, [])
                sats = st.session_state.get('plan_satisfied_dict', {}).get(c, [])

                # Add glowing red border class if prerequisite is unsatisfied
                has_prereq_issue = any("prereq" in str(w).lower() for w in warns)
                prereq_glow_class = "has-prereq-error" if has_prereq_issue else ""

                badges_html = ""
                if warns:
                    badges_html += f"<div class='warning-pill' title='{'; '.join(warns)}'>⚠️ {warns[0]}</div>"
                if sats:
                    badges_html += f"<div class='success-pill' title='{'; '.join(sats)}'>✅ {sats[0]}</div>"

                offs = format_offerings_label(c_data.get("offerings", []))

                html += f"""
                <div class="course-card {is_sel} {prereq_glow_class}" style="background-color: {bg};" onclick="onCourseClick('{c}')">
                    <div class="card-top">
                        <span class="card-code">{c}</span>
                        <span class="btn-close" onclick="onMoveToHolding(event, '{c}', {yr}, {tr})" title="Unschedule to Holding Zone">&times;</span>
                    </div>
                    <div class="card-title" title="{c_data['title']}">{c_data['title']}</div>
                    <div class="badges-row">
                        <span class="badge-pill">{c_data.get('credit_points', '10')} CP</span>
                        <span class="badge-pill">{offs}</span>
                    </div>
                    {badges_html}
                </div>
                """
            # N + 1 Dynamic Target Slot (Max 7 courses per trimester)
            if n_courses < 7:
                if selected_code:
                    if is_valid_term:
                        slot_class = "slot-target ready-for-placement"
                        slot_label = f"+ Place {selected_code} in T{tr}"
                        slot_action = f"onclick=\"onSlotClick({yr}, {tr})\""
                    else:
                        slot_class = "slot-target slot-disabled"
                        slot_label = f"🚫 {selected_code} Not Offered in T{tr}"
                        slot_action = ""
                else:
                    slot_class = "slot-target"
                    slot_label = "+ Open Slot"
                    slot_action = ""

                html += f"""
                <div class="{slot_class}" {slot_action}>
                    {slot_label}
                </div>
                """

            html += "</div>"  # close trim-col
        html += "</div></div>"  # close trimesters-row & year-container

    html += """
    </div>

    <script>
    function triggerBridgeAction(param) {
        const selector = 'input[aria-label="Hidden Bridge Action"]';
        let nodes = window.document.querySelectorAll(selector);
        if (nodes.length === 0 && window.parent && window.parent.document) {
            nodes = window.parent.document.querySelectorAll(selector);
        }
        if (nodes.length === 0) return;

        const input = nodes[0];
        const valWithToken = param.replace("___TOKEN___", "___" + Date.now() + "___");

        const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value").set || 
                       Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        setter.call(input, valWithToken);

        const parentWin = window.parent || window;
        const scrollX = parentWin.scrollX || parentWin.pageXOffset || 0;
        const scrollY = parentWin.scrollY || parentWin.pageYOffset || 0;

        input.focus({ preventScroll: true });
        parentWin.scrollTo(scrollX, scrollY);

        input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
        input.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));

        setTimeout(() => {
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
            input.blur();
        }, 50);
    }

    function onCourseClick(code) {
        triggerBridgeAction("SELECT___TOKEN___" + code);
    }

    function onSlotClick(year, term) {
        const selCode = \"""" + (selected_code or "") + """\";
        if (!selCode) return;
        triggerBridgeAction("PLACE___TOKEN___" + selCode + "___" + year + "___" + term);
    }

    function onRemoveHolding(e, code) {
        e.stopPropagation();
        triggerBridgeAction("REMOVE_HOLDING___TOKEN___" + code);
    }

    function onMoveToHolding(e, code, year, term) {
        e.stopPropagation();
        triggerBridgeAction("MOVE_TO_HOLDING___TOKEN___" + code + "___" + year + "___" + term);
    }
    </script>
    """
    return html

# -----------------------------------------------------------------------------
# 8. MAIN VIEW
# -----------------------------------------------------------------------------
render_title_html = """
<div style="display: flex; align-items: center; margin-bottom: 0.8rem;">
    <span style="font-size: 2.2rem; margin-right: 8px;">🎓</span>
    <h1 style="margin: 0; padding: 0;">Griffix Degree Planner</h1>
</div>
"""
st.markdown(render_title_html, unsafe_allow_html=True)
st.caption("Plan your study terms, check prerequisites, and schedule your degree path. Add a course on the left to get started.")

st.session_state['plan_satisfied_dict'] = plan_satisfied

# Validation & Satisfied Requisites Report
if plan_warnings or plan_satisfied:
    with st.expander(f"📋 Course Requisites & Status ({len(plan_warnings)} warnings, {len(plan_satisfied)} satisfied)", expanded=True if plan_warnings else False):
        if plan_warnings:
            st.markdown("##### ⚠️ Warnings")
            for c, issues in plan_warnings.items():
                for iss in issues:
                    st.error(f"**{c}**: {iss}")
        if plan_satisfied:
            st.markdown("##### ✅ Satisfied Requisites")
            for c, sats in plan_satisfied.items():
                for sat_msg in sats:
                    st.success(f"**{c}**: {sat_msg}")
elif st.session_state.plan:
    st.success("✅ All scheduled courses satisfy prerequisite, corequisite, and offering constraints.")

# Compute frame height dynamically to completely eliminate scrollbars
max_in_any_trim = max([len(v) for v in st.session_state.plan.values()] + [1])
courses_render_factor = max_in_any_trim if max_in_any_trim == 7 else (max_in_any_trim + 1)
year_block_height = 50 + (courses_render_factor * 85)
calc_height = 250 + (num_years * year_block_height)

planner_html = build_planner_html(
    holding_zone=st.session_state.holding_zone,
    plan=st.session_state.plan,
    catalog_dict=catalog,
    num_years=num_years,
    include_t3=include_t3,
    selected_code=st.session_state.selected_course,
    warnings_dict=plan_warnings
)

components.html(planner_html, height=calc_height, scrolling=False)
