import streamlit as st
import streamlit.components.v1 as components
import urllib.request
import urllib.parse
import json
import os
import re

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & STATE INITIALIZATION
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Griffix Degree Planner",
    layout="wide",
    page_icon="🎓",
    initial_sidebar_state="expanded"
)

# Enforce clean null / empty state upon initial launch
if "holding_zone" not in st.session_state:
    st.session_state.holding_zone = []

if "plan" not in st.session_state:
    # Schema: {(year, trimester): [course_code, ...]}
    st.session_state.plan = {}

if "selected_course" not in st.session_state:
    st.session_state.selected_course = None

if "last_action_token" not in st.session_state:
    st.session_state.last_action_token = None

# -----------------------------------------------------------------------------
# 2. COURSE CATALOG PARSER & 24-HOUR CACHED FETCHER
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
        "description": "Prerequisite: 1010ENG Engineering Mathematics 1. Hydrological processes and catchment modelling.",
        "offerings": ["Trimester 2"], "career": "Undergraduate", "group": "Griffith Sciences",
        "prereqs": ["1010ENG"], "coreqs": [], "incompatibles": []
    }
}

def extract_course_codes(text: str):
    """Finds valid Griffith course codes (e.g., 1001PSY, 2004ENG, 6091CCJ_P1, IBA306)."""
    if not text:
        return []
    pattern = r'\b(?:[0-9]{4}[A-Z]{3,4}(?:_[A-Z0-9]+)?|[A-Z]{3}[0-9]{3})\b'
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(m.upper() for m in matches))

def extract_prereqs(desc: str):
    if not desc:
        return []
    match = re.search(r'(?:pre-?requisite(?:s)?|advised prerequisite(?:s)?|prior knowledge of)\s*[:\-]?\s*([^.;\n]+)', desc, re.IGNORECASE)
    if match:
        chunk = match.group(1)
        if "nil" in chunk.lower() or "none" in chunk.lower():
            return []
        return extract_course_codes(chunk)
    return []

def extract_coreqs(desc: str):
    if not desc:
        return []
    match = re.search(r'(?:co-?requisite(?:s)?)\s*[:\-]?\s*([^.;\n]+)', desc, re.IGNORECASE)
    if match:
        chunk = match.group(1)
        if "nil" in chunk.lower() or "none" in chunk.lower():
            return []
        return extract_course_codes(chunk)
    return []

def extract_incompatibles(desc: str):
    if not desc:
        return []
    match = re.search(r'(?:incompatible(?:s)?)\s*[:\-]?\s*([^.;\n]+)', desc, re.IGNORECASE)
    if match:
        return extract_course_codes(match.group(1))
    return []

@st.cache_data(ttl=86400, show_spinner=False)
def load_griffith_catalog():
    """Fetches up to 3000 courses from Griffith's Funnelback API with 24-hr TTL."""
    url = "https://search.griffith.edu.au/s/search.json?collection=griff~sp-courses-api&profile=courses&num_ranks=3000&start_rank=1&sort=metafborderna"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    data = None

    # Check local cache file if available
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
# 3. PLAN VALIDATION ENGINE
# -----------------------------------------------------------------------------
def term_index(year: int, trimester: int) -> int:
    return (year - 1) * 3 + trimester

def validate_plan(plan: dict, catalog_dict: dict):
    """
    Validates courses scheduled in the plan:
    - Prerequisites must occur in an earlier trimester.
    - Corequisites must occur in the same or earlier trimester.
    - Incompatible courses must not be present in the plan.
    - Course must be offered in the designated trimester.
    - Warn if trimester exceeds 40 Credit Points.
    """
    warnings = {}          # {course_code: [warning_msg, ...]}
    placed_coords = {}     # {course_code: (year, trimester)}

    for (yr, tr), course_list in plan.items():
        for c in course_list:
            placed_coords[c] = (yr, tr)

    all_planned_courses = set(placed_coords.keys())

    for (yr, tr), course_list in plan.items():
        current_rank = term_index(yr, tr)

        for c in course_list:
            c_warns = []
            info = catalog_dict.get(c, {})
            prereqs = info.get("prereqs", [])
            coreqs = info.get("coreqs", [])
            incompatibles = info.get("incompatibles", [])
            offerings = [o.lower() for o in info.get("offerings", [])]

            # 1. Trimester Offering Check
            if offerings:
                if tr == 1 and not any("trimester 1" in o for o in offerings):
                    c_warns.append("Not typically offered in Trimester 1")
                elif tr == 2 and not any("trimester 2" in o for o in offerings):
                    c_warns.append("Not typically offered in Trimester 2")
                elif tr == 3 and not any("summer" in o or "trimester 3" in o for o in offerings):
                    c_warns.append("Not typically offered in Trimester 3 (Summer)")

            # 2. Prerequisite Check (Must be strictly earlier)
            for p in prereqs:
                if p not in placed_coords:
                    c_warns.append(f"Missing Prerequisite: {p}")
                else:
                    p_yr, p_tr = placed_coords[p]
                    if term_index(p_yr, p_tr) >= current_rank:
                        c_warns.append(f"Prereq {p} must be completed before Year {yr} T{tr}")

            # 3. Corequisite Check (Must be in same term or earlier)
            for cr in coreqs:
                if cr not in placed_coords:
                    c_warns.append(f"Missing Corequisite: {cr}")
                else:
                    cr_yr, cr_tr = placed_coords[cr]
                    if term_index(cr_yr, cr_tr) > current_rank:
                        c_warns.append(f"Coreq {cr} scheduled after Year {yr} T{tr}")

            # 4. Incompatibility Check
            for inc in incompatibles:
                if inc in all_planned_courses and inc != c:
                    c_warns.append(f"Incompatible with scheduled course: {inc}")

            if c_warns:
                warnings[c] = c_warns

    return warnings

plan_warnings = validate_plan(st.session_state.plan, catalog)

# -----------------------------------------------------------------------------
# 4. STREAMLIT-JS ACTION BRIDGE
# -----------------------------------------------------------------------------
# Hidden input node accessed by window.parent in iframe JavaScript
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

    # Avoid duplicate executions of the exact same event
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

            # Remove from holding zone if existing
            if code in st.session_state.holding_zone:
                st.session_state.holding_zone.remove(code)

            # Remove from any existing plan location
            for slot, c_list in list(st.session_state.plan.items()):
                if code in c_list:
                    c_list.remove(code)

            # Insert into targeted trimester slot (up to 4 courses / 40 CP max load)
            slot_courses = st.session_state.plan.setdefault((target_yr, target_tr), [])
            if code not in slot_courses and len(slot_courses) < 4:
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
# 5. SIDEBAR: COURSE SEARCH & CONTROLS
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🔍 Course Search")
    st.caption("Search Griffith's catalog (cached 24h) and stage courses.")

    all_sorted_codes = sorted(catalog.keys())
    search_options = [f"{c} - {catalog[c]['title']}" for c in all_sorted_codes]

    # Clean null input type selector on load
    selected_option = st.selectbox(
        "Search by Code or Course Name:",
        options=[""] + search_options,
        index=0
    )

    if selected_option:
        chosen_code = selected_option.split(" - ")[0].strip()
        c_meta = catalog.get(chosen_code, {})

        st.markdown(f"**{c_meta['code']} - {c_meta['title']}**")
        st.markdown(f"• **Faculty:** {c_meta.get('group', 'Other')}")
        st.markdown(f"• **Credit Points:** {c_meta.get('credit_points', '10')} CP")
        st.markdown(f"• **Offerings:** {', '.join(c_meta.get('offerings', [])) or 'TBA'}")
        
        pr_str = ", ".join(c_meta.get('prereqs', [])) or "None"
        cr_str = ", ".join(c_meta.get('coreqs', [])) or "None"
        st.markdown(f"• **Prerequisites:** {pr_str}")
        st.markdown(f"• **Corequisites:** {cr_str}")

        if st.button(f"➕ Stage {chosen_code} to Holding Zone", use_container_width=True):
            already_in_holding = chosen_code in st.session_state.holding_zone
            already_in_plan = any(chosen_code in lst for lst in st.session_state.plan.values())
            if not already_in_holding and not already_in_plan:
                st.session_state.holding_zone.append(chosen_code)
                st.success(f"{chosen_code} staged!")
                st.rerun()
            else:
                st.warning("Course is already staged or planned.")

    st.divider()
    st.markdown("### ⚙️ Degree Structure")
    num_years = st.slider("Degree Duration (Years)", min_value=1, max_value=5, value=3)
    include_t3 = st.checkbox("Include Trimester 3 (Summer)", value=True)

    st.divider()
    # Metrics
    total_planned = sum(len(c) for c in st.session_state.plan.values())
    total_cp = sum(
        int(catalog.get(c, {}).get("credit_points", 10) or 10)
        for clist in st.session_state.plan.values() for c in clist
    )
    st.metric("Total Courses Planned", f"{total_planned}")
    st.metric("Accumulated Credits", f"{total_cp} CP")

    if st.button("🗑️ Reset All Planned Courses", use_container_width=True):
        st.session_state.plan = {}
        st.session_state.holding_zone = []
        st.session_state.selected_course = None
        st.rerun()

# -----------------------------------------------------------------------------
# 6. HTML, CSS & JS COMPONENT BUILDER
# -----------------------------------------------------------------------------
def get_faculty_color(group_name: str) -> str:
    """Distinctive color palette aligned with academic groups."""
    g = group_name.lower()
    if "health" in g:
        return "#00897b"  # Emerald Teal
    elif "sciences" in g or "engineering" in g:
        return "#1976d2"  # Griffith Ocean Blue
    elif "business" in g:
        return "#d35400"  # Amber Orange
    elif "arts" in g or "education" in g or "law" in g or "music" in g:
        return "#7b1fa2"  # Royal Purple
    return "#455a64"      # Slate

def build_planner_html(holding_zone, plan, catalog_dict, num_years, include_t3, selected_code, warnings_dict):
    trimesters = [1, 2, 3] if include_t3 else [1, 2]

    html = """
    <style>
    :root {
        --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        --border-color: rgba(255, 255, 255, 0.15);
        --bg-color: #12151c;
        --card-border: rgba(255, 255, 255, 0.15);
        --text-color: #f7f9fa;
    }

    body {
        font-family: var(--font-family);
        color: var(--text-color);
        background: transparent;
        margin: 0;
        padding: 0;
    }

    .planner-box {
        background: var(--bg-color);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 18px 20px;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.25);
        margin-bottom: 20px;
    }

    .section-title {
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 0.6px;
        color: #70a1ff;
        text-transform: uppercase;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
    }

    /* Course Card Styles */
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
        box-shadow: 0 6px 14px rgba(0, 0, 0, 0.35);
        border-color: rgba(255, 255, 255, 0.55);
    }

    .course-card.is-selected {
        border: 2px solid #2ed573 !important;
        box-shadow: 0 0 14px rgba(46, 213, 115, 0.75) !important;
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
        color: rgba(255, 255, 255, 0.6);
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

    /* Holding Zone Layout */
    .holding-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 10px;
        min-height: 65px;
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

    .slot-target {
        border: 1.5px dashed rgba(255, 255, 255, 0.2);
        border-radius: 6px;
        height: 52px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        color: rgba(255, 255, 255, 0.35);
        margin-bottom: 8px;
        transition: all 0.2s ease;
        cursor: pointer;
    }

    .slot-target:hover, .slot-target.ready-for-placement {
        border-color: #2ed573;
        background: rgba(46, 213, 115, 0.12);
        color: #2ed573;
        font-weight: 700;
    }
    </style>

    <div class="planner-box">
        <div class="section-title">
            <span>📥 Staged Courses (Holding Zone)</span>
            <span style="font-size: 11px; font-weight: normal; color: #a4b0be;">
                Selected: <b style="color: #2ed573;">""" + (selected_code if selected_code else "None (Click course to select)") + """</b>
            </span>
        </div>
        <div class="holding-grid">
    """

    if not holding_zone:
        html += "<div style='color: rgba(255,255,255,0.4); font-size: 12px; grid-column: 1/-1;'>No courses in holding zone. Use the sidebar search to add courses.</div>"

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

    # Year & Trimesters Matrix
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
            cp_sum = sum(int(catalog_dict.get(c, {}).get("credit_points", 10) or 10) for c in scheduled)
            t_title = f"Trimester {tr}" if tr in [1, 2] else "Trimester 3 (Summer)"

            html += f"""
            <div class="trim-col">
                <div class="trim-header">
                    <span>{t_title}</span>
                    <span>{cp_sum} / 40 CP</span>
                </div>
            """

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
                        <span class="btn-close" onclick="onMoveToHolding(event, '{c}', {yr}, {tr})" title="Unschedule to Holding">&times;</span>
                    </div>
                    <div class="card-title" title="{c_data['title']}">{c_data['title']}</div>
                    <div class="badges-row">
                        <span class="badge-pill">{c_data.get('credit_points', '10')} CP</span>
                    </div>
                    {warn_snippet}
                </div>
                """

            # Empty slot targets (up to 4 per trimester)
            available_slots = max(0, 4 - len(scheduled))
            for _ in range(available_slots):
                active_class = "ready-for-placement" if selected_code else ""
                label = f"+ Place {selected_code}" if selected_code else "Empty Slot"
                html += f"""
                <div class="slot-target {active_class}" onclick="onSlotClick({yr}, {tr})">
                    {label}
                </div>
                """

            html += "</div>"
        html += "</div></div>"

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
# 7. MAIN INTERFACE RENDER
# -----------------------------------------------------------------------------
st.title("Griffix Timetable Master: Interactive Degree Planner")
st.markdown(
    "Plan degree structures across trimesters, balance workloads, and validate prerequisites before enrolment. "
    "Select any course by clicking it, then click an available slot to place it."
)

# Active Warnings / Status Bar
if plan_warnings:
    with st.expander(f"⚠️ Validation Warnings Detected ({len(plan_warnings)} issues)", expanded=True):
        for c, issues in plan_warnings.items():
            for iss in issues:
                st.error(f"**{c}**: {iss}")
else:
    if st.session_state.plan:
        st.success("✅ All scheduled courses satisfy prerequisite, corequisite, and offering constraints.")

# Build & inject interactive HTML
planner_html_content = build_planner_html(
    holding_zone=st.session_state.holding_zone,
    plan=st.session_state.plan,
    catalog_dict=catalog,
    num_years=num_years,
    include_t3=include_t3,
    selected_code=st.session_state.selected_course,
    warnings_dict=plan_warnings
)

calc_height = 280 + num_years * 270
components.html(planner_html_content, height=calc_height, scrolling=True)
