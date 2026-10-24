import streamlit as st
import streamlit.components.v1 as components
import urllib.request
import urllib.parse
import json
import os
import re

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & SESSION STATE (CLEAN NULL START)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Griffix Degree Planner",
    layout="wide",
    page_icon="🎓",
    initial_sidebar_state="expanded"
)

# Initialise completely clean state on launch
if "holding_zone" not in st.session_state:
    st.session_state.holding_zone = []

if "plan" not in st.session_state:
    # Schema: {(year, trimester): [course_code, ...]}
    st.session_state.plan = {}

if "selected_course" not in st.session_state:
    st.session_state.selected_course = None

if "last_action_token" not in st.session_state:
    st.session_state.last_action_token = None

if "search_msg" not in st.session_state:
    st.session_state.search_msg = None

# -----------------------------------------------------------------------------
# 2. CACHED GRIFFITH CATALOG FETCHER (24-Hour TTL)
# -----------------------------------------------------------------------------
FALLBACK_COURSES = {
    "1001PSY": {
        "code": "1001PSY", "title": "Introduction to Psychology 1", "credit_points": "10",
        "description": "Prerequisites: NIL Co-requisites: NIL. Cognitive and biological bases of behaviour.",
        "offerings": ["Trimester 1", "Summer Semester"], "career": "Undergraduate", "group": "Griffith Health",
        "prereqs": [], "coreqs": [], "incompatibles": ["1015HSV"]
    },
    "1003PSY": {
        "code": "1003PSY", "title": "Research Methods and Statistics in Psychology", "credit_points": "10",
        "description": "Prerequisites: Nil Co-requisites: Nil. Data gathering in psychology.",
        "offerings": ["Trimester 2", "Summer Semester"], "career": "Undergraduate", "group": "Griffith Health",
        "prereqs": [], "coreqs": [], "incompatibles": ["1014SCG", "1305AFE"]
    },
    "2000PSY": {
        "code": "2000PSY", "title": "Experimental Design and Analysis", "credit_points": "10",
        "description": "Prerequisites: 1003PSY Research Methods and Statistics in Psychology OR 1305AFE. Competence in SPSS.",
        "offerings": ["Trimester 1"], "career": "Undergraduate", "group": "Griffith Health",
        "prereqs": ["1003PSY"], "coreqs": [], "incompatibles": []
    },
    "1010ENG": {
        "code": "1010ENG", "title": "Engineering Mathematics 1", "credit_points": "10",
        "description": "Vectors, matrices, complex numbers. Prerequisites: Nil.",
        "offerings": ["Trimester 1", "Summer Semester"], "career": "Undergraduate", "group": "Griffith Sciences",
        "prereqs": [], "coreqs": [], "incompatibles": ["1201SCG"]
    },
    "2004ENG": {
        "code": "2004ENG", "title": "Hydrology", "credit_points": "10",
        "description": "Prerequisite: 1010ENG Engineering Mathematics 1. Hydrological processes.",
        "offerings": ["Trimester 2"], "career": "Undergraduate", "group": "Griffith Sciences",
        "prereqs": ["1010ENG"], "coreqs": [], "incompatibles": []
    }
}

def extract_course_codes(text: str):
    """Extracts valid Griffith course codes (e.g. 1001MSC, 2004ENG, 6091CCJ_P1, IBA306)."""
    if not text:
        return []
    pattern = r'\b(?:[0-9]{4}[A-Z]{3,4}(?:_[A-Z0-9]+)?|[A-Z]{3}[0-9]{3})\b'
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(m.upper() for m in matches))

def extract_prereqs(desc: str):
    if not desc: return []
    match = re.search(r'(?:pre-?requisite(?:s)?|advised prerequisite(?:s)?|prior knowledge of)\s*[:\-]?\s*([^.;\n]+)', desc, re.I)
    if match:
        chunk = match.group(1)
        if "nil" in chunk.lower() or "none" in chunk.lower(): return []
        return extract_course_codes(chunk)
    return []

def extract_coreqs(desc: str):
    if not desc: return []
    match = re.search(r'(?:co-?requisite(?:s)?)\s*[:\-]?\s*([^.;\n]+)', desc, re.I)
    if match:
        chunk = match.group(1)
        if "nil" in chunk.lower() or "none" in chunk.lower(): return []
        return extract_course_codes(chunk)
    return []

def extract_incompatibles(desc: str):
    if not desc: return []
    match = re.search(r'(?:incompatible(?:s)?)\s*[:\-]?\s*([^.;\n]+)', desc, re.I)
    if match:
        return extract_course_codes(match.group(1))
    return []

@st.cache_data(ttl=86400, show_spinner=False)
def load_griffith_catalog():
    """Fetches up to 3000 courses from Griffith Funnelback API with 24-hr cache."""
    url = "https://search.griffith.edu.au/s/search.json?collection=griff~sp-courses-api&profile=courses&num_ranks=3000&start_rank=1&sort=metafborderna"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    data = None

    # Check local cache fallback if present
    for local_file in ["coursesearch_shorter_800.json", "coursesearch.json"]:
        if os.path.exists(local_file):
            try:
                with open(local_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    break
            except Exception:
                pass

    if data is None:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return FALLBACK_COURSES

    raw_results = data.get("response", {}).get("resultPacket", {}).get("results", [])
    if not raw_results:
        return FALLBACK_COURSES

    catalog = {}
    for item in raw_results:
        meta = item.get("listMetadata", {})
        cat_numbers = meta.get("categoryNumber", [])
        if not cat_numbers:
            continue
        code = str(cat_numbers[0]).strip().upper()
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
    return catalog

catalog = load_griffith_catalog()

# -----------------------------------------------------------------------------
# 3. OFFERING AVAILABILITY CHECKER
# -----------------------------------------------------------------------------
def is_course_offered_in_term(c_info: dict, trimester: int) -> bool:
    """Checks whether the course is actively scheduled in Trimester 1, 2, or 3."""
    if not c_info:
        return True
    offerings = c_info.get("offerings", [])
    if not offerings:
        return True  # If unknown, allow placement
    offs_lower = [o.lower() for o in offerings]
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
            info = catalog_dict.get(c, {})
            prereqs = info.get("prereqs", [])
            coreqs = info.get("coreqs", [])
            incomps = info.get("incompatibles", [])

            # 1. Offering Check
            if not is_course_offered_in_term(info, tr):
                c_warns.append(f"Not usually offered in Trimester {tr}")

            # 2. Prerequisite Check (Must occur strictly earlier)
            for p in prereqs:
                if p not in placed_coords:
                    c_warns.append(f"Missing Prereq: {p}")
                else:
                    p_yr, p_tr = placed_coords[p]
                    if term_index(p_yr, p_tr) >= current_rank:
                        c_warns.append(f"Prereq {p} must be completed before Year {yr} T{tr}")

            # 3. Corequisite Check (Must occur in same or earlier trimester)
            for cr in coreqs:
                if cr not in placed_coords:
                    c_warns.append(f"Missing Coreq: {cr}")
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

            # Remove from holding zone if present
            if code in st.session_state.holding_zone:
                st.session_state.holding_zone.remove(code)

            # Remove from any previous slot in plan
            for slot, c_list in list(st.session_state.plan.items()):
                if code in c_list:
                    c_list.remove(code)

            # Insert into targeted trimester slot (up to 7 courses max)
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
    
    # Form layout matching timetablegenWEB exactly
    with st.form("course_search_form", clear_on_submit=True):
        search_query = st.text_input(
            "Course Code or Title", 
            placeholder="eg. 1001MSC or Chemistry",
            key="input_course_query"
        )
        submit_btn = st.form_submit_button("Add Course", type="primary")

    if submit_btn and search_query:
        query_clean = search_query.strip().upper().replace(" ", "")
        
        # 1. Exact match lookup
        target_code = None
        if query_clean in catalog:
            target_code = query_clean
        else:
            # 2. Fuzzy search by code prefix or title substring
            for c_code, c_meta in catalog.items():
                if query_clean == c_code.replace("_", "") or search_query.strip().lower() in c_meta["title"].lower():
                    target_code = c_code
                    break
        
        if target_code:
            already_in_holding = target_code in st.session_state.holding_zone
            already_in_plan = any(target_code in clist for clist in st.session_state.plan.values())

            if already_in_holding or already_in_plan:
                st.session_state.search_msg = ("warning", f"**{target_code}** is already in your staging area or degree plan.")
            else:
                st.session_state.holding_zone.append(target_code)
                meta = catalog[target_code]
                st.session_state.search_msg = ("success", f"Added **{target_code}** ({meta['title']}) to Holding Zone!")
        else:
            st.session_state.search_msg = ("error", f"Could not find course '{search_query}'. Ensure the code is correct.")
        st.rerun()

    # Display feedback message if present
    if st.session_state.search_msg:
        msg_type, msg_text = st.session_state.search_msg
        if msg_type == "success":
            st.success(msg_text)
        elif msg_type == "warning":
            st.warning(msg_text)
        else:
            st.error(msg_text)
        st.session_state.search_msg = None

    st.divider()
    st.header("2. Degree Structure")
    num_years = st.slider("Degree Duration (Years)", min_value=1, max_value=5, value=3)
    include_t3 = st.checkbox("Include Trimester 3 (Summer)", value=True)

    st.divider()
    # Live summary counters
    total_planned = sum(len(c) for c in st.session_state.plan.values())
    total_cp = sum(
        int(catalog.get(c, {}).get("credit_points", 10) or 10)
        for clist in st.session_state.plan.values() for c in clist
    )
    st.metric("Total Courses Planned", f"{total_planned}")
    st.metric("Total Credit Points", f"{total_cp} CP")

    if st.button("🗑️ Clear Entire Plan", use_container_width=True):
        st.session_state.plan = {}
        st.session_state.holding_zone = []
        st.session_state.selected_course = None
        st.rerun()

# -----------------------------------------------------------------------------
# 7. HTML, CSS & JAVASCRIPT BUILDER
# -----------------------------------------------------------------------------
def get_faculty_color(group_name: str) -> str:
    """Distinctive color palette aligned with Griffith faculties."""
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
    selected_meta = catalog_dict.get(selected_code) if selected_code else None

    html = """
    <style>
    :root {
        --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        --border-color: rgba(255, 255, 255, 0.15);
        --bg-color: #12151c;
        --card-border: rgba(255, 255, 255, 0.15);
        --text-color: #f7f9fa;
    }

    /* Remove scrollbars completely */
    html, body {
        font-family: var(--font-family);
        color: var(--text-color);
        background: transparent;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }

    .planner-box {
        background: var(--bg-color);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.25);
        margin-bottom: 20px;
        box-sizing: border-box;
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
    }

    /* Degree Progression Matrix */
    .year-container {
        margin-top: 14px;
        border: 1px solid var(--border-color);
        border-radius: 8px;
        overflow: hidden;
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
    }

    .trim-col {
        flex: 1;
        border-right: 1px solid var(--border-color);
        padding: 12px;
        box-sizing: border-box;
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

    /* Slot Target Buttons (Dynamic N + 1 up to 7) */
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
                Selected: <b style="color: #2ed573;">""" + (selected_code if selected_code else "None (Click a course to arm placement)") + """</b>
            </span>
        </div>
        <div class="holding-grid">
    """

    if not holding_zone:
        html += "<div style='color: rgba(255,255,255,0.4); font-size: 12px; grid-column: 1/-1;'>No courses in holding zone. Search for a course code in the sidebar to add one.</div>"

    for code in holding_zone:
        info = catalog_dict.get(code, {"title": code, "credit_points": "10", "offerings": [], "prereqs": [], "coreqs": [], "group": ""})
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

    # Year & Trimesters Progression Matrix
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
            cp_sum = sum(int(catalog_dict.get(c, {}).get("credit_points", 10) or 10) for c in scheduled)
            t_title = f"Trimester {tr}" if tr in [1, 2] else "Trimester 3 (Summer)"

            # Check if currently armed/selected course is offered in this trimester
            is_valid_term = is_course_offered_in_term(selected_meta, tr) if selected_meta else False

            html += f"""
            <div class="trim-col">
                <div class="trim-header">
                    <span>{t_title}</span>
                    <span>{cp_sum} CP ({n_courses}/7)</span>
                </div>
            """

            # Render Scheduled Course Cards
            for c in scheduled:
                c_data = catalog_dict.get(c, {"title": c, "credit_points": "10", "offerings": [], "group": ""})
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

            # Dynamic N + 1 Slot Target: Show exactly 1 target slot if n < 7, else hide it
            if n_courses < 7:
                if selected_code:
                    if is_valid_term:
                        slot_class = "slot-target ready-for-placement"
                        slot_label = f"+ Place {selected_code} in T{tr}"
                        slot_action = f"onclick=\"onSlotClick({yr}, {tr})\""
                    else:
                        slot_class = "slot-target slot-disabled"
                        slot_label = f"🚫 Not Offered in T{tr}"
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
# 8. MAIN INTERFACE RENDER
# -----------------------------------------------------------------------------
# Header matching timetablegenWEB title styling
render_title_html = """
<div style="display: flex; align-items: center; margin-bottom: 0.8rem;">
    <span style="font-size: 2.2rem; margin-right: 8px;">🎓</span>
    <h1 style="margin: 0; padding: 0;">Griffix Degree Planner</h1>
</div>
"""
st.markdown(render_title_html, unsafe_allow_html=True)
st.caption("Interactively build your degree path across trimesters. Search a course code on the left to add it, click to select, and place it into valid open trimesters.")

# Validation warning alert banner
if plan_warnings:
    with st.expander(f"⚠️ Degree Plan Warnings ({len(plan_warnings)} issues detected)", expanded=True):
        for c, issues in plan_warnings.items():
            for iss in issues:
                st.error(f"**{c}**: {iss}")
elif st.session_state.plan:
    st.success("✅ All scheduled courses satisfy prerequisite, corequisite, and offering constraints.")

# Calculate frame height based on maximum scheduled load per trimester to avoid scrollbars
max_in_any_trim = max([len(v) for v in st.session_state.plan.values()] + [1])
courses_render_factor = max_in_any_trim if max_in_any_trim == 7 else (max_in_any_trim + 1)
year_block_height = 45 + (courses_render_factor * 85)
calc_height = 240 + (num_years * year_block_height)

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
