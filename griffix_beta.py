import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import re

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & STATE (CLEAN START)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Griffix Degree Planner",
    layout="wide",
    page_icon="🎓",
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

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_single_course_from_api(course_code: str):
    """
    Direct fallback for specific courses (e.g. 2022MSC) using Griffith's REST API.
    """
    url = f"https://degrees.griffith.edu.au/rest-api/v3/course/{course_code}"
    headers = {
        'User-Agent': 'Griffix-Live-Degree-Planner-StudentProject (Contact: yiming.qu@griffithuni.edu.au)',
        'Accept': 'application/json'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            d = resp.json()
            desc = d.get("description", "") or d.get("summary", "") or ""
            offerings = []
            for off in d.get("offerings", []):
                term = off.get("offeringTerm", {})
                cat = term.get("category", "")
                if cat:
                    offerings.append(cat)

            return {
                "code": course_code,
                "title": d.get("name", course_code),
                "credit_points": str(d.get("creditPointValue", 10)),
                "description": desc,
                "offerings": list(set(offerings)),
                "career": d.get("career", {}).get("name", "Undergraduate"),
                "group": d.get("school", {}).get("group", {}).get("name", "Other"),
                "prereqs": extract_prereqs(desc),
                "coreqs": extract_coreqs(desc),
                "incompatibles": extract_incompatibles(desc)
            }
    except Exception:
        pass
    return None

catalog = load_full_catalog()

def lookup_course(clean_code: str):
    """Checks the cached catalog first; if absent, fetches from the live course endpoint."""
    if clean_code in catalog:
        return catalog[clean_code]
    direct_res = fetch_single_course_from_api(clean_code)
    if direct_res:
        catalog[clean_code] = direct_res
        return direct_res
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
    warnings = {}       # {course_code: [warning_msg, ...]}
    placed_coords = {}  # {course_code: (year, trimester)}

    for (yr, tr), courses in plan.items():
        for c in courses:
            placed_coords[c] = (yr, tr)

    all_planned = set(placed_coords.keys())

    for (yr, tr), courses in plan.items():
        current_rank = term_index(yr, tr)
        for c in courses:
            c_warns = []
            info = catalog_dict.get(c) or lookup_course(c) or {}
            prereqs = info.get("prereqs", [])
            coreqs = info.get("coreqs", [])
            incomps = info.get("incompatibles", [])

            # 1. Offering Check
            if not is_course_offered_in_term(info, tr):
                c_warns.append(f"Not usually offered in Trimester {tr}")

            # 2. Prerequisite Check (Must occur strictly earlier)
            for p in prereqs:
                if p not in placed_coords:
                    c_warns.append(f"Missing Prerequisite: {p}")
                else:
                    p_yr, p_tr = placed_coords[p]
                    if term_index(p_yr, p_tr) >= current_rank:
                        c_warns.append(f"Prereq {p} must be completed before Year {yr} T{tr}")

            # 3. Corequisite Check (Must occur in same or earlier trimester)
            for cr in coreqs:
                if cr not in placed_coords:
                    c_warns.append(f"Missing Corequisite: {cr}")
                else:
                    cr_yr, cr_tr = placed_coords[cr]
                    if term_index(cr_yr, cr_tr) > current_rank:
                        c_warns.append(f"Coreq {cr} scheduled after Year {yr} T{tr}")

            # 4. Incompatibility Check
            for inc in incomps:
                if inc in all_planned and inc != c:
                    c_warns.append(f"Incompatible with {inc}")

            if c_warns:
                warnings[c] = c_warns

    return warnings

plan_warnings = validate_plan(st.session_state.plan, catalog)

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

    with st.form("course_search_form", clear_on_submit=True):
        course_code_input = st.text_input(
            "Course Code",
            placeholder="eg. 1001MSC",
            key="input_course_code"
        )
        submit_btn = st.form_submit_button("Add Course", type="primary")

    if submit_btn:
        st.session_state.feedback_message = None
        if not course_code_input:
            st.session_state.feedback_message = ("warning", "Please enter a course code.")
        else:
            # Capitalise and strip all spaces
            clean_code = course_code_input.replace(" ", "").upper().strip()

            c_info = lookup_course(clean_code)

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
def get_faculty_color(group_name: str) -> str:
    """Colors aligned with Griffith academic groups."""
    g = group_name.lower()
    if "health" in g:
        return "#00897b"  # Teal / Emerald
    elif "sciences" in g or "engineering" in g:
        return "#1976d2"  # Griffith Ocean Blue
    elif "business" in g:
        return "#d35400"  # Amber Orange
    elif "arts" in g or "education" in g or "law" in g or "music" in g:
        return "#7b1fa2"  # Royal Purple
    return "#455a64"      # Slate

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

    .warning-pill {
        background: #ff4757;
        color: #ffffff;
        font-size: 9.5px;
        padding: 3px 6px;
        border-radius: 4px;
        margin-top: 6px;
        display: inline-block;
        font-weight: 700;
    }

    /* Holding Grid */
    .holding-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 10px;
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
        bg = get_faculty_color(info.get("group", ""))
        is_sel = "is-selected" if code == selected_code else ""

        pr_text = f"Pre: {', '.join(info['prereqs'])}" if info["prereqs"] else "No Prereqs"
        cr_text = f" | Co: {', '.join(info['coreqs'])}" if info["coreqs"] else ""
        offs = "/".join([o.replace("Trimester ", "T").replace("Summer Semester", "T3") for o in info.get("offerings", [])])

        html += f"""
        <div class="course-card {is_sel}" style="background-color: {bg};" onclick="onCourseClick('{code}')">
            <div class="card-top">
                <span class="card-code">{code}</span>
                <span class="btn-close" onclick="onRemoveHolding(event, '{code}')" title="Remove Course">&times;</span>
            </div>
            <div class="card-title" title="{info['title']}">{info['title']}</div>
            <div class="badges-row">
                <span class="badge-pill">{info.get('credit_points', '10')} CP</span>
                <span class="badge-pill">{offs or 'TBA'}</span>
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
                    <span>{cp_sum} CP ({n_courses}/7)</span>
                </div>
            """

            # Render Scheduled Cards
            for c in scheduled:
                c_data = catalog_dict.get(c) or lookup_course(c) or {"title": c, "credit_points": "10", "offerings": [], "group": ""}
                bg = get_faculty_color(c_data.get("group", ""))
                is_sel = "is-selected" if c == selected_code else ""
                warns = warnings_dict.get(c, [])

                warn_snippet = ""
                if warns:
                    warn_snippet = f"<div class='warning-pill' title='{'; '.join(warns)}'>⚠️ {warns[0]}</div>"

                html += f"""
                <div class="course-card {is_sel}" style="background-color: {bg};" onclick="onCourseClick('{c}')">
                    <div class="card-top">
                        <span class="card-code">{c}</span>
                        <span class="btn-close" onclick="onMoveToHolding(event, '{c}', {yr}, {tr})" title="Unschedule to Holding Zone">&times;</span>
                    </div>
                    <div class="card-title" title="{c_data['title']}">{c_data['title']}</div>
                    <div class="badges-row">
                        <span class="badge-pill">{c_data.get('credit_points', '10')} CP</span>
                    </div>
                    {warn_snippet}
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

# Validation warning alert banner
if plan_warnings:
    with st.expander(f"⚠️ Degree Plan Warnings ({len(plan_warnings)} issues detected)", expanded=True):
        for c, issues in plan_warnings.items():
            for iss in issues:
                st.error(f"**{c}**: {iss}")
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
