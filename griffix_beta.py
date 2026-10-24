import streamlit as st
import streamlit.components.v1 as components
import urllib.request
import urllib.parse
import json
import re

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & SESSION STATE INITIALIZATION
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Griffix Timetable Master", layout="wide", initial_sidebar_state=510, page_icon="Picture1.png")


if "holding_zone" not in st.session_state:
    st.session_state.holding_zone = ["1001PSY", "1003PSY", "2000PSY", "2004ENG", "1010ENG"]
if "plan" not in st.session_state:
    # Schema: {(year, trimester): [course_code, ...]}
    st.session_state.plan = {
        (1, 1): ["1010ENG"],
        (1, 2): ["2004ENG"],
    }
if "selected_course" not in st.session_state:
    st.session_state.selected_course = None

# -----------------------------------------------------------------------------
# 2. CACHED GRIFFITH COURSE FETCHER (24-Hour TTL)
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
    """Finds valid Griffith course codes (e.g. 1001PSY, 2004ENG, IBA306, 6091CCJ_P1)."""
    if not text:
        return []
    pattern = r'\b(?:[0-9]{4}[A-Z]{3,4}(?:_[A-Z0-9]+)?|[A-Z]{3}[0-9]{3})\b'
    return list(dict.fromkeys(re.findall(pattern, text)))

def extract_prereqs(desc: str):
    if not desc: return []
    match = re.search(r'(?:pre-?requisite(?:s)?|advised prerequisite(?:s)?)\s*[:\-]\s*([^.\n;]+)', desc, re.IGNORECASE)
    if match:
        chunk = match.group(1)
        if "nil" in chunk.lower(): return []
        return extract_course_codes(chunk)
    return []

def extract_coreqs(desc: str):
    if not desc: return []
    match = re.search(r'(?:co-?requisite(?:s)?)\s*[:\-]\s*([^.\n;]+)', desc, re.IGNORECASE)
    if match:
        chunk = match.group(1)
        if "nil" in chunk.lower(): return []
        return extract_course_codes(chunk)
    return []

@st.cache_data(ttl=86400, show_spinner=False)
def get_griffith_catalog():
    """Fetches up to 3000 courses from Griffith's search API with 24-hr caching."""
    url = "https://search.griffith.edu.au/s/search.json?collection=griff~sp-courses-api&profile=courses&num_ranks=3000&start_rank=1&sort=metafborderna"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("response", {}).get("resultPacket", {}).get("results", [])
        
        catalog = {}
        for r in results:
            meta = r.get("listMetadata", {})
            cat_list = meta.get("categoryNumber", [])
            if not cat_list: continue
            code = str(cat_list[0]).strip().upper()
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
                "coreqs": extract_coreqs(desc)
            }
        return catalog
    except Exception:
        # Graceful fallback so the dashboard works even if the API or network is blocked
        return FALLBACK_COURSES

catalog = get_griffith_catalog()

# -----------------------------------------------------------------------------
# 3. PLAN VALIDATION ENGINE
# -----------------------------------------------------------------------------
def term_to_tuple_val(year, trim):
    return year * 10 + trim

def validate_plan(plan, catalog_dict):
    """
    Validates courses placed in the plan:
    - Prerequisite must be completed in an earlier trimester.
    - Corequisite must be taken in the same or an earlier trimester.
    - Offering matches current trimester.
    """
    warnings = {}  # {course_code: [warning_str, ...]}
    placed_locations = {}  # {course_code: (year, trim)}

    for (yr, tr), courses in plan.items():
        for c in courses:
            placed_locations[c] = (yr, tr)

    for (yr, tr), courses in plan.items():
        current_val = term_to_tuple_val(yr, tr)
        for c in courses:
            c_warns = []
            info = catalog_dict.get(c, {})
            prereqs = info.get("prereqs", [])
            coreqs = info.get("coreqs", [])
            offerings = [o.lower() for o in info.get("offerings", [])]

            # 1. Trimester Offering Check
            term_str = f"trimester {tr}" if tr in [1, 2] else "summer semester"
            if offerings and not any(term_str in o or f"trimester {tr}" in o for o in offerings):
                friendly_offs = ", ".join(info.get("offerings", [])) or "None listed"
                c_warns.append(f"Not usually offered in T{tr} (Offered: {friendly_offs})")

            # 2. Prerequisite Check
            for p in prereqs:
                if p not in placed_locations:
                    c_warns.append(f"Missing Prereq: {p}")
                else:
                    p_yr, p_tr = placed_locations[p]
                    if term_to_tuple_val(p_yr, p_tr) >= current_val:
                        c_warns.append(f"Prereq {p} must be completed before Year {yr} T{tr}")

            # 3. Corequisite Check
            for cr in coreqs:
                if cr not in placed_locations:
                    c_warns.append(f"Missing Coreq: {cr}")
                else:
                    cr_yr, cr_tr = placed_locations[cr]
                    if term_to_tuple_val(cr_yr, cr_tr) > current_val:
                        c_warns.append(f"Coreq {cr} scheduled after Year {yr} T{tr}")

            if c_warns:
                warnings[c] = c_warns

    return warnings

plan_warnings = validate_plan(st.session_state.plan, catalog)

# -----------------------------------------------------------------------------
# 4. ACTION PROCESSOR (STREAMLIT JS BRIDGE)
# -----------------------------------------------------------------------------
# Hidden text input receives decoded commands from the injected JavaScript
action_value = st.text_input("Hidden Bridge Action", key="bridge_action_trigger", label_visibility="collapsed")

if action_value:
    parts = action_value.split("___")
    cmd = parts[0]

    if cmd == "SELECT":
        code = parts[1]
        st.session_state.selected_course = None if st.session_state.selected_course == code else code

    elif cmd == "DESELECT":
        st.session_state.selected_course = None

    elif cmd == "PLACE":
        code = parts[1]
        target_yr = int(parts[2])
        target_tr = int(parts[3])

        # Remove from holding zone if present
        if code in st.session_state.holding_zone:
            st.session_state.holding_zone.remove(code)

        # Remove from any existing term slot in plan
        for k, clist in list(st.session_state.plan.items()):
            if code in clist:
                clist.remove(code)

        # Insert into selected slot
        slot_list = st.session_state.plan.setdefault((target_yr, target_tr), [])
        if code not in slot_list and len(slot_list) < 4:
            slot_list.append(code)

        st.session_state.selected_course = None

    elif cmd == "REMOVE_HOLDING":
        code = parts[1]
        if code in st.session_state.holding_zone:
            st.session_state.holding_zone.remove(code)
        if st.session_state.selected_course == code:
            st.session_state.selected_course = None

    elif cmd == "MOVE_TO_HOLDING":
        code = parts[1]
        yr = int(parts[2])
        tr = int(parts[3])
        if (yr, tr) in st.session_state.plan and code in st.session_state.plan[(yr, tr)]:
            st.session_state.plan[(yr, tr)].remove(code)
        if code not in st.session_state.holding_zone:
            st.session_state.holding_zone.append(code)
        st.session_state.selected_course = None

    st.rerun()

# -----------------------------------------------------------------------------
# 5. SIDEBAR: COURSE SEARCH & SETTINGS
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("🎓 Course Search")
    st.markdown("Search Griffith's 3,000+ course database and stage courses into your holding zone.")

    # Search options
    all_codes = sorted(catalog.keys())
    search_options = [f"{c} - {catalog[c]['title']}" for c in all_codes]

    selected_entry = st.selectbox(
        "Search course by code or keyword:",
        options=[""] + search_options,
        index=0
    )

    if selected_entry:
        chosen_code = selected_entry.split(" - ")[0].strip()
        c_info = catalog.get(chosen_code, {})

        st.info(f"**{c_info['code']}**: {c_info['title']}\n\n"
                f"• **Credits:** {c_info.get('credit_points', '10')} CP\n\n"
                f"• **Offered:** {', '.join(c_info.get('offerings', [])) or 'TBA'}\n\n"
                f"• **Prerequisites:** {', '.join(c_info.get('prereqs', [])) or 'None'}")

        if st.button(f"➕ Add {chosen_code} to Holding Zone", use_container_width=True):
            if chosen_code not in st.session_state.holding_zone and not any(chosen_code in lst for lst in st.session_state.plan.values()):
                st.session_state.holding_zone.append(chosen_code)
                st.success(f"Added {chosen_code}!")
                st.rerun()
            else:
                st.warning("Course is already in holding zone or degree plan.")

    st.divider()
    st.subheader("⚙️ Degree Settings")
    num_years = st.slider("Degree Duration (Years)", min_value=1, max_value=5, value=3)
    include_t3 = st.checkbox("Include Trimester 3 (Summer)", value=True)

    st.divider()
    # Summary Metrics
    total_planned = sum(len(c) for c in st.session_state.plan.values())
    total_cp = sum(
        int(catalog.get(c, {}).get("credit_points", 10) or 10)
        for clist in st.session_state.plan.values() for c in clist
    )
    st.metric("Courses Planned", f"{total_planned}")
    st.metric("Total Credit Points", f"{total_cp} CP")

    if st.button("🧹 Clear Entire Plan", use_container_width=True):
        st.session_state.plan = {}
        st.session_state.holding_zone = []
        st.session_state.selected_course = None
        st.rerun()

# -----------------------------------------------------------------------------
# 6. HTML, CSS & JS RENDERER
# -----------------------------------------------------------------------------
def get_faculty_color(group_name: str) -> str:
    """Returns color based on Griffith faculty group."""
    g = group_name.lower()
    if "health" in g:
        return "#16a085"  # Teal / Emerald
    elif "sciences" in g:
        return "#2980b9"  # Royal Blue
    elif "business" in g:
        return "#d35400"  # Amber Orange
    elif "arts" in g or "law" in g or "music" in g:
        return "#8e44ad"  # Deep Purple
    return "#546e7a"      # Slate

def build_planner_html(holding_zone, plan, catalog_dict, num_years, include_t3, selected_code, warnings_dict):
    trimesters = [1, 2, 3] if include_t3 else [1, 2]
    
    html = """
    <style>
    :root {
        --font-family: "Source Sans Pro", "Inter", "Segoe UI", Helvetica, Arial, sans-serif;
        --border-color: rgba(255, 255, 255, 0.15);
        --card-bg: rgba(255, 255, 255, 0.05);
        --card-border: rgba(255, 255, 255, 0.18);
        --text-color: #f1f2f6;
    }
    
    body {
        font-family: var(--font-family);
        color: var(--text-color);
        margin: 0;
        padding: 0;
    }

    .planner-wrapper {
        border-radius: 14px;
        background: rgba(20, 24, 33, 0.95);
        padding: 20px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.37);
        border: 1px solid var(--border-color);
        margin-bottom: 25px;
    }

    .zone-title {
        font-size: 15px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: #70a1ff;
        margin-bottom: 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    /* Course Cards */
    .course-card {
        position: relative;
        border-radius: 8px;
        padding: 10px 12px;
        cursor: pointer;
        transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out, border-color 0.15s ease-in-out;
        user-select: none;
        overflow: hidden;
        border: 1px solid var(--card-border);
        box-sizing: border-box;
        margin-bottom: 8px;
    }

    .course-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
        border-color: rgba(255, 255, 255, 0.5);
    }

    .course-card.is-selected {
        border: 2px solid #38ef7d !important;
        box-shadow: 0 0 15px rgba(56, 239, 125, 0.6) !important;
        animation: pulse 1.6s infinite;
    }

    @keyframes pulse {
        0% { box-shadow: 0 0 5px rgba(56, 239, 125, 0.4); }
        50% { box-shadow: 0 0 18px rgba(56, 239, 125, 0.8); }
        100% { box-shadow: 0 0 5px rgba(56, 239, 125, 0.4); }
    }

    .course-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
    }

    .course-code {
        font-weight: 800;
        font-size: 13px;
        letter-spacing: 0.5px;
    }

    .btn-remove {
        color: rgba(255, 255, 255, 0.6);
        font-size: 15px;
        font-weight: bold;
        line-height: 1;
        padding: 2px 5px;
        border-radius: 4px;
        transition: background 0.15s, color 0.15s;
    }

    .btn-remove:hover {
        background: rgba(255, 75, 75, 0.8);
        color: white;
    }

    .course-title-text {
        font-size: 11px;
        margin-top: 3px;
        opacity: 0.9;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .tag-container {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        margin-top: 6px;
    }

    .badge {
        font-size: 9px;
        padding: 2px 6px;
        border-radius: 4px;
        background: rgba(0, 0, 0, 0.35);
        font-weight: 600;
    }

    .warning-badge {
        background: #eb4d4b;
        color: white;
        font-size: 9px;
        padding: 2px 6px;
        border-radius: 4px;
        margin-top: 5px;
        display: inline-block;
        font-weight: 700;
    }

    /* Holding Zone */
    .holding-container {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
        gap: 12px;
        min-height: 75px;
        padding: 10px;
        background: rgba(0,0,0,0.25);
        border-radius: 8px;
        border: 1px dashed var(--border-color);
    }

    /* Year & Trimester Matrix */
    .year-block {
        margin-top: 20px;
        border: 1px solid var(--border-color);
        border-radius: 10px;
        overflow: hidden;
    }

    .year-header {
        background: rgba(255, 255, 255, 0.08);
        padding: 8px 16px;
        font-weight: 800;
        font-size: 14px;
        border-bottom: 1px solid var(--border-color);
        color: #f1f2f6;
    }

    .trimester-grid {
        display: flex;
        width: 100%;
        background: rgba(0,0,0,0.15);
    }

    .trimester-column {
        flex: 1;
        border-right: 1px solid var(--border-color);
        padding: 12px;
        box-sizing: border-box;
    }
    .trimester-column:last-child {
        border-right: none;
    }

    .trimester-col-header {
        font-size: 12px;
        font-weight: 700;
        margin-bottom: 10px;
        display: flex;
        justify-content: space-between;
        color: #a4b0be;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        padding-bottom: 6px;
    }

    .slot-placeholder {
        border: 1.5px dashed rgba(255, 255, 255, 0.18);
        border-radius: 8px;
        height: 52px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        color: rgba(255, 255, 255, 0.35);
        margin-bottom: 8px;
        transition: all 0.2s;
        cursor: pointer;
    }

    .slot-placeholder:hover, .slot-placeholder.is-active-target {
        border-color: #2ed573;
        background: rgba(46, 213, 115, 0.12);
        color: #2ed573;
    }
    </style>

    <div class="planner-wrapper">
        <div class="zone-title">
            <span>📥 Course Holding Zone (Click course to select, then click any open slot below)</span>
            <span style="font-size:11px; font-weight:normal; color:#a4b0be;">
                Selected: <b style="color:#2ed573;">""" + (selected_code if selected_code else "None (Click a course)") + """</b>
            </span>
        </div>
        <div class="holding-container">
    """

    if not holding_zone:
        html += "<div style='color: rgba(255,255,255,0.4); font-size: 12px; grid-column: 1/-1;'>No courses in holding zone. Use sidebar search to add courses.</div>"

    for code in holding_zone:
        c_info = catalog_dict.get(code, {"title": code, "credit_points": "10", "offerings": [], "prereqs": [], "coreqs": [], "group": ""})
        bg_col = get_faculty_color(c_info.get("group", ""))
        is_sel = "is-selected" if code == selected_code else ""
        
        prereq_str = f"Pre: {', '.join(c_info['prereqs'])}" if c_info["prereqs"] else "No Prereqs"
        coreq_str = f" | Co: {', '.join(c_info['coreqs'])}" if c_info["coreqs"] else ""
        offs_str = "/".join([o.replace("Trimester ", "T").replace("Summer Semester", "T3") for o in c_info.get("offerings", [])])

        html += f"""
        <div class="course-card {is_sel}" style="background-color: {bg_col};" onclick="onCourseClick('{code}')" data-course-code="{code}">
            <div class="course-header">
                <span class="course-code">{code}</span>
                <span class="btn-remove" onclick="onRemoveHolding(event, '{code}')" title="Remove Course">&times;</span>
            </div>
            <div class="course-title-text" title="{c_info['title']}">{c_info['title']}</div>
            <div class="tag-container">
                <span class="badge">{c_info.get('credit_points', '10')} CP</span>
                <span class="badge">{offs_str or 'TBA'}</span>
            </div>
            <div style="font-size: 9px; opacity: 0.85; margin-top: 5px;">{prereq_str}{coreq_str}</div>
        </div>
        """

    html += """
        </div>
    </div>
    """

    # Render Year-by-Year Trimester Matrix
    html += "<div class='planner-wrapper'>"
    html += "<div class='zone-title'>📅 Degree Plan Progression</div>"

    for yr in range(1, num_years + 1):
        html += f"""
        <div class="year-block">
            <div class="year-header">YEAR {yr}</div>
            <div class="trimester-grid">
        """
        for tr in trimesters:
            placed = plan.get((yr, tr), [])
            cp_sum = sum(int(catalog_dict.get(c, {}).get("credit_points", 10) or 10) for c in placed)
            tr_name = f"Trimester {tr}" if tr in [1, 2] else "Trimester 3 (Summer)"
            
            html += f"""
            <div class="trimester-column">
                <div class="trimester-col-header">
                    <span>{tr_name}</span>
                    <span>{cp_sum} / 40 CP</span>
                </div>
            """

            # Render Placed Courses
            for c in placed:
                c_info = catalog_dict.get(c, {"title": c, "credit_points": "10", "offerings": [], "group": ""})
                bg_col = get_faculty_color(c_info.get("group", ""))
                is_sel = "is-selected" if c == selected_code else ""
                warns = warnings_dict.get(c, [])
                
                warn_html = ""
                if warns:
                    warn_html = f"<div class='warning-badge' title='{'; '.join(warns)}'>⚠️ {warns[0]}</div>"

                html += f"""
                <div class="course-card {is_sel}" style="background-color: {bg_col};" onclick="onCourseClick('{c}')" data-course-code="{c}">
                    <div class="course-header">
                        <span class="course-code">{c}</span>
                        <span class="btn-remove" onclick="onMoveToHolding(event, '{c}', {yr}, {tr})" title="Move back to holding">&times;</span>
                    </div>
                    <div class="course-title-text" title="{c_info['title']}">{c_info['title']}</div>
                    <div class="tag-container">
                        <span class="badge">{c_info.get('credit_points', '10')} CP</span>
                    </div>
                    {warn_html}
                </div>
                """

            # Render Empty Slot Placeholders (max 4 per trimester)
            available_slots = max(0, 4 - len(placed))
            for slot_i in range(available_slots):
                target_class = "is-active-target" if selected_code else ""
                slot_label = f"+ Place {selected_code}" if selected_code else "Empty Slot"
                html += f"""
                <div class="slot-placeholder {target_class}" onclick="onSlotClick({yr}, {tr})">
                    {slot_label}
                </div>
                """

            html += "</div>" # close trimester-column
        html += "</div></div>" # close trimester-grid, year-block

    html += """
    </div>

    <script>
    function triggerStreamlitAction(param, selector) {
        let inputNodes = window.document.querySelectorAll(selector);
        if (inputNodes.length === 0 && window.parent && window.parent.document) {
            inputNodes = window.parent.document.querySelectorAll(selector);
        }
        if (inputNodes.length === 0) return;

        const input = inputNodes[0];
        const decodedValue = decodeURIComponent(param);

        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value").set || 
                                       Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        nativeInputValueSetter.call(input, decodedValue);

        const parentWindow = window.parent || window;
        const prevScrollX = parentWindow.scrollX || parentWindow.pageXOffset || 0;
        const prevScrollY = parentWindow.scrollY || parentWindow.pageYOffset || 0;

        input.focus({ preventScroll: true });
        parentWindow.scrollTo(prevScrollX, prevScrollY);

        input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
        input.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));

        setTimeout(() => {
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
            input.blur();
        }, 50);
    }

    function onCourseClick(code) {
        triggerStreamlitAction("SELECT___" + code, 'input[aria-label="Hidden Bridge Action"]');
    }

    function onSlotClick(year, term) {
        const selectedCode = \"""" + (selected_code or "") + """\";
        if (!selectedCode) return;
        triggerStreamlitAction("PLACE___" + selectedCode + "___" + year + "___" + term, 'input[aria-label="Hidden Bridge Action"]');
    }

    function onRemoveHolding(e, code) {
        e.stopPropagation();
        triggerStreamlitAction("REMOVE_HOLDING___" + code, 'input[aria-label="Hidden Bridge Action"]');
    }

    function onMoveToHolding(e, code, year, term) {
        e.stopPropagation();
        triggerStreamlitAction("MOVE_TO_HOLDING___" + code + "___" + year + "___" + term, 'input[aria-label="Hidden Bridge Action"]');
    }
    </script>
    """
    return html

# -----------------------------------------------------------------------------
# 7. MAIN PAGE VIEW
# -----------------------------------------------------------------------------
st.title("Griffith University Interactive Degree Planner")
st.markdown(
    "Plan your trimesters, balance your workloads, and prevent enrolment blocks before they happen. "
    "Click any course to select it, then click an open slot in the progression grid to place it."
)

# Display real-time validation alerts banner if issues exist
if plan_warnings:
    with st.expander(f"⚠️ Pre-requisite & Trimester Warnings ({len(plan_warnings)} detected)", expanded=True):
        for c, issues in plan_warnings.items():
            for iss in issues:
                st.error(f"**{c}**: {iss}")
else:
    st.success("✅ All scheduled courses satisfy prerequisite, corequisite, and offering guidelines.")

# Render Interactive Component Canvas
planner_html = build_planner_html(
    holding_zone=st.session_state.holding_zone,
    plan=st.session_state.plan,
    catalog_dict=catalog,
    num_years=num_years,
    include_t3=include_t3,
    selected_code=st.session_state.selected_course,
    warnings_dict=plan_warnings
)

components.html(planner_html, height=1200, scrolling=True)
