import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import re
import hashlib
import colorsys
import difflib
import urllib.parse
from datetime import datetime

st.warning("**IMPORTANT**: THIS SITE IS A BETA VERSION OF GRIFFIX FEATURES, AND ONLY INCLUDES **EXPERIMENTAL FEATURES UNDERGOING TESTING**. ACCESS THE OFFICIAL VERSION OF GRIFFIX [HERE](https://griffix.streamlit.app)")

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & STATE
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Griffix Degree Planner",
    layout="wide",
    page_icon="Picture1.png",
    initial_sidebar_state="expanded"
)

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

# Degree Program State
if "selected_degree" not in st.session_state:
    st.session_state.selected_degree = None

if "degree_study_mode" not in st.session_state:
    st.session_state.degree_study_mode = "Full-time"

if "degree_start_intake" not in st.session_state:
    st.session_state.degree_start_intake = "Trimester 1"

if "degree_campus" not in st.session_state:
    st.session_state.degree_campus = None

if "degree_edit_mode" not in st.session_state:
    st.session_state.degree_edit_mode = False

if "course_or_map" not in st.session_state:
    st.session_state.course_or_map = {}

if "term_target_cp" not in st.session_state:
    st.session_state.term_target_cp = {}

if "active_terms_per_year" not in st.session_state:
    st.session_state.active_terms_per_year = {}

if "num_years_slider" not in st.session_state:
    st.session_state.num_years_slider = 3

if "include_t3_cb" not in st.session_state:
    st.session_state.include_t3_cb = True

# -----------------------------------------------------------------------------
# 2. CAMPUS NORMALIZATION
# -----------------------------------------------------------------------------
def normalize_campus_name(name: str) -> str:
    """Unifies campus naming so Brisbane South/Nathan and Brisbane City/South Bank merge."""
    if not name:
        return ""
    n = str(name).strip()
    n_lower = n.lower()
    if "nathan" in n_lower or "brisbane south" in n_lower:
        return "Brisbane South (Nathan)"
    if "south bank" in n_lower or "southbank" in n_lower or "brisbane city" in n_lower:
        return "Brisbane City (South Bank)"
    if "gold coast" in n_lower:
        return "Gold Coast"
    if "logan" in n_lower:
        return "Logan"
    if "online" in n_lower:
        return "Online"
    return n

# -----------------------------------------------------------------------------
# 3. COURSE METADATA & REQUISITES PARSER (AND / OR AWARE)
# -----------------------------------------------------------------------------
def extract_course_codes(text: str):
    """Finds valid Griffith course codes."""
    if not text:
        return []
    pattern = r'\b(?:[0-9]{4}[A-Z]{3,4}(?:_[A-Z0-9]+)?|[A-Z]{3}[0-9]{3})\b'
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(m.upper() for m in matches))

def parse_rule_definition_to_groups(rule_def: str, rule_sum: str = "") -> list:
    """
    Parses Curriculum API ruleDefinition accurately:
    - 'COURSES (1) 1017MSC OR COURSES (1) 1006MSC' -> 1 group: count 1, courses: ['1017MSC', '1006MSC']
    - 'COURSES (1) 1016MSC AND COURSES (1) 1014MSC, 1001AHS, 1001NSC' -> 2 groups: ['1016MSC'] AND ['1014MSC', '1001AHS', '1001NSC']
    """
    groups = []
    text_to_parse = rule_def if (rule_def and "COURSES" in rule_def.upper()) else rule_sum
    if not text_to_parse:
        return groups

    and_clauses = re.split(r'\s+AND\s+', text_to_parse, flags=re.I)
    for clause in and_clauses:
        clause = clause.strip()
        if not clause:
            continue

        or_subclauses = re.split(r'\s+OR\s+|/', clause, flags=re.I)
        all_codes_in_clause = []
        min_count = 1

        for sub in or_subclauses:
            sub = sub.strip()
            c_match = re.search(r'COURSES\s*\((\d+)\)', sub, re.I)
            if c_match:
                min_count = min(min_count, int(c_match.group(1)))
            codes = extract_course_codes(sub)
            for c in codes:
                if c not in all_codes_in_clause:
                    all_codes_in_clause.append(c)

        if all_codes_in_clause:
            groups.append({
                "count": min(min_count, len(all_codes_in_clause)),
                "courses": all_codes_in_clause
            })

    return groups

def format_prereq_display(prereq_groups: list) -> str:
    """Formats structured prerequisite groups into clean, human-readable AND / OR strings."""
    if not prereq_groups:
        return "No Prereqs"
    group_strs = []
    for g in prereq_groups:
        c_list = g.get("courses", [])
        if not c_list:
            continue
        if len(c_list) == 1:
            group_strs.append(c_list[0])
        else:
            count = g.get("count", 1)
            if count == 1:
                group_strs.append(f"({' OR '.join(c_list)})")
            else:
                group_strs.append(f"({count} of: {' OR '.join(c_list)})")
    return " AND ".join(group_strs) if group_strs else "No Prereqs"

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
    """Fetches all courses from Griffith search API."""
    catalog = {}
    url = "https://search.griffith.edu.au/s/search.json?collection=griff~sp-courses-api&profile=courses&num_ranks=3000&start_rank=1&sort=metafborderna"
    headers = {
        'User-Agent': 'Griffix-Live-Degree-Planner-StudentProject (Contact: yiming.qu@griffithuni.edu.au)',
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

                p_match = re.search(r'(?:pre-?requisite(?:s)?|advised prerequisite(?:s)?|prior knowledge of)\s*[:\-]?\s*([^.;\n]+)', desc, re.I)
                p_text = p_match.group(1) if p_match and "nil" not in p_match.group(1).lower() else ""
                fallback_groups = parse_rule_definition_to_groups("", p_text)

                catalog[code] = {
                    "code": code,
                    "title": title,
                    "credit_points": cp,
                    "description": desc,
                    "offerings": list(set(offerings)),
                    "career": career,
                    "group": group,
                    "prereq_groups": fallback_groups,
                    "prereq_display": format_prereq_display(fallback_groups),
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
        "User-Agent": "Griffix-Live-Degree-Planner-StudentProject (Contact: yiming.qu@griffithuni.edu.au)",
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

                    prereq_groups, coreqs, incompatibles = [], [], []
                    req_obj = mapped.get("crseRequiste", {}).get("value", {})
                    if isinstance(req_obj, dict):
                        for r in req_obj.get("requisites", []):
                            rtype = str(r.get("type", "")).upper()
                            rule_def = str(r.get("ruleDefinition", ""))
                            rule_sum = str(r.get("ruleSummary", ""))
                            
                            if "PRE" in rtype:
                                groups = parse_rule_definition_to_groups(rule_def, rule_sum)
                                clean_groups = []
                                for g in groups:
                                    filtered_codes = [c for c in g.get("courses", []) if c != clean_code]
                                    if filtered_codes:
                                        clean_groups.append({"count": min(g.get("count", 1), len(filtered_codes)), "courses": filtered_codes})
                                if clean_groups:
                                    prereq_groups.extend(clean_groups)
                            elif "CO" in rtype:
                                coreqs.extend([c for c in extract_course_codes(f"{rule_def} {rule_sum}") if c != clean_code])
                            elif "ANTI" in rtype:
                                incompatibles.extend([c for c in extract_course_codes(f"{rule_def} {rule_sum}") if c != clean_code])

                    other_req = mapped.get("crseOthrRequiste", {}).get("value")
                    if other_req and isinstance(other_req, str):
                        other_codes = [c for c in extract_course_codes(other_req) if c != clean_code]
                        if other_codes and not prereq_groups:
                            for oc in other_codes:
                                prereq_groups.append({"count": 1, "courses": [oc]})

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
                        "prereq_groups": prereq_groups,
                        "prereq_display": format_prereq_display(prereq_groups),
                        "coreqs": list(dict.fromkeys(coreqs)),
                        "incompatibles": list(dict.fromkeys(incompatibles))
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
# 4. OFFERING AVAILABILITY CHECKER (DEFINED BEFORE VALIDATION)
# -----------------------------------------------------------------------------
def is_course_offered_in_term(c_info: dict, trimester: int) -> bool:
    """Checks whether the course is actively scheduled in Trimester 1, 2, or 3."""
    if not c_info:
        return True
    offerings = c_info.get("offerings", [])
    if not offerings:
        return True
    offs_lower = [str(o).lower() for o in offerings]
    if trimester == 1:
        return any("trimester 1" in o or "t1" in o for o in offs_lower)
    elif trimester == 2:
        return any("trimester 2" in o or "t2" in o for o in offs_lower)
    elif trimester == 3:
        return any("summer" in o or "trimester 3" in o or "t3" in o for o in offs_lower)
    return False

# -----------------------------------------------------------------------------
# 5. LIVE DEGREE SEARCH & CURRICULUM PRESCRIBED STUDY PLAN
# -----------------------------------------------------------------------------
def get_fallback_degrees():
    raw_list = [
        {"code": "1031", "title": "Bachelor of Biomedical Science", "campuses": ["Brisbane South", "Nathan"], "intakes": ["Trimester 1", "Trimester 2"], "duration_years": 3, "career": "Undergraduate"},
        {"code": "1094", "title": "Bachelor of Biomedical Science", "campuses": ["Gold Coast"], "intakes": ["Trimester 1", "Trimester 2"], "duration_years": 3, "career": "Undergraduate"},
        {"code": "1280", "title": "Bachelor of Medical Science", "campuses": ["Gold Coast", "Brisbane South"], "intakes": ["Trimester 1"], "duration_years": 2, "career": "Undergraduate"},
        {"code": "1162", "title": "Bachelor of Nursing", "campuses": ["Gold Coast", "Logan", "Brisbane South"], "intakes": ["Trimester 1", "Trimester 2"], "duration_years": 3, "career": "Undergraduate"},
        {"code": "1577", "title": "Bachelor of Dental Health Science", "campuses": ["Gold Coast"], "intakes": ["Trimester 1"], "duration_years": 3, "career": "Undergraduate"},
        {"code": "1590", "title": "Bachelor of Physiotherapy (Honours)", "campuses": ["Gold Coast", "Brisbane South"], "intakes": ["Trimester 1"], "duration_years": 4, "career": "Undergraduate"},
        {"code": "2004", "title": "Bachelor of Psychological Science (Honours)", "campuses": ["Gold Coast", "Brisbane South"], "intakes": ["Trimester 1"], "duration_years": 1, "career": "Undergraduate"},
        {"code": "1012", "title": "Bachelor of Psychological Science", "campuses": ["Gold Coast", "Brisbane South"], "intakes": ["Trimester 1", "Trimester 2", "Trimester 3"], "duration_years": 3, "career": "Undergraduate"},
        {"code": "1619", "title": "Bachelor of Laws (Honours)", "campuses": ["Gold Coast", "Brisbane City"], "intakes": ["Trimester 1", "Trimester 2"], "duration_years": 4, "career": "Undergraduate"},
        {"code": "1662", "title": "Bachelor of Occupational Therapy (Honours)", "campuses": ["Gold Coast", "Brisbane South"], "intakes": ["Trimester 1"], "duration_years": 4, "career": "Undergraduate"},
        {"code": "1533", "title": "Bachelor of Paramedicine", "campuses": ["Gold Coast"], "intakes": ["Trimester 1"], "duration_years": 3, "career": "Undergraduate"},
        {"code": "1546", "title": "Bachelor of Engineering (Honours)", "campuses": ["Gold Coast", "Brisbane South"], "intakes": ["Trimester 1", "Trimester 2"], "duration_years": 4, "career": "Undergraduate"},
        {"code": "1632", "title": "Bachelor of Business", "campuses": ["Online", "Gold Coast", "Brisbane City", "Brisbane South"], "intakes": ["Trimester 1", "Trimester 2", "Trimester 3"], "duration_years": 3, "career": "Undergraduate"},
        {"code": "1354", "title": "Bachelor of Midwifery", "campuses": ["Logan"], "intakes": ["Trimester 1"], "duration_years": 3, "career": "Undergraduate"},
        {"code": "1540", "title": "Bachelor of Biomolecular Science (Honours)", "campuses": ["Brisbane South"], "intakes": ["Trimester 1", "Trimester 2"], "duration_years": 4, "career": "Undergraduate"}
    ]
    for d in raw_list:
        d["campuses"] = list(dict.fromkeys(normalize_campus_name(c) for c in d["campuses"]))
    return raw_list

def parse_degree_results(results):
    degrees = []
    for r in results:
        meta = r.get("listMetadata", {})
        codes = meta.get("code", [])
        code = str(codes[0]).strip() if codes else ""
        if not code:
            url = r.get("liveUrl", "")
            match = re.search(r'-([0-9]{4})\b', url)
            if match:
                code = match.group(1)
            else:
                continue

        title_list = meta.get("title", [])
        title = title_list[0] if title_list else r.get("title", code)
        campuses = meta.get("campusName", [])
        intakes = meta.get("intakesName", [])
        durations = meta.get("duration", [])
        career = meta.get("academicCareer", ["Undergraduate"])[0]

        # Normalized campuses (Nathan == Brisbane South, South Bank == Brisbane City)
        clean_campuses = []
        for c in campuses:
            norm = normalize_campus_name(c)
            if norm and norm not in clean_campuses:
                clean_campuses.append(norm)

        years = 3
        for d in durations:
            d_str = str(d).strip()
            if d_str.isdigit() and 1 <= int(d_str) <= 6:
                years = int(d_str)
                break
            match = re.search(r'(\d+)\s*years?', d_str, re.I)
            if match:
                years = int(match.group(1))
                break

        degrees.append({
            "code": code,
            "title": title,
            "campuses": clean_campuses,
            "intakes": list(dict.fromkeys(intakes)),
            "duration_years": years,
            "durations_raw": durations,
            "career": career
        })
    return degrees

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_all_degrees_catalog():
    headers = {
        'User-Agent': 'Griffix-Live-Degree-Planner-StudentProject (Contact: yiming.qu@griffithuni.edu.au)',
        'Accept': 'application/json, text/plain, */*'
    }
    urls = [
        "https://search.griffith.edu.au/s/search.json?collection=griff~sp-degrees-api&profile=degrees&num_ranks=350&start_rank=1&sort=metafborderna&smeta_intlCohortYears_orsand=2026&smeta_intlCohortYears_orsand=2027&smeta_intlCohortYears_orsand=2028",
        "https://search.griffith.edu.au/s/search.json?collection=griff~sp-degrees-api&profile=degrees&num_ranks=350&start_rank=1&sort=metafborderna&query=!padrenull"
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("response", {}).get("resultPacket", {}).get("results", [])
                parsed = parse_degree_results(results)
                if parsed:
                    return parsed
        except Exception:
            continue
    return get_fallback_degrees()

def query_degrees_live(query_str: str):
    if not query_str or len(query_str.strip()) < 2:
        return []
    clean_q = urllib.parse.quote(query_str.strip())
    url = f"https://search.griffith.edu.au/s/search.json?collection=griff~sp-degrees-api&profile=degrees&num_ranks=40&query={clean_q}&smeta_intlCohortYears_orsand=2026&smeta_intlCohortYears_orsand=2027&smeta_intlCohortYears_orsand=2028"
    headers = {
        'User-Agent': 'Griffix-Live-Degree-Planner-StudentProject (Contact: yiming.qu@griffithuni.edu.au)',
        'Accept': 'application/json, text/plain, */*'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return parse_degree_results(data.get("response", {}).get("resultPacket", {}).get("results", []))
    except Exception as e:
        print(f"Live degree query error: {e}")
    return []

def search_degrees(query: str, degrees: list):
    if not query:
        return degrees[:20]
    q = query.strip().lower()
    q_words = q.split()

    direct = [d for d in degrees if all(w in f"{d['title']} {d['code']}".lower() for w in q_words)]
    if direct:
        return direct

    scored = []
    for d in degrees:
        target = f"{d['title']} {d['code']}".lower()
        full_ratio = difflib.SequenceMatcher(None, q, target).ratio()
        word_ratios = [max(difflib.SequenceMatcher(None, qw, tw).ratio() for tw in target.split()) for qw in q_words]
        avg_word_ratio = sum(word_ratios) / len(word_ratios) if word_ratios else 0
        best_score = max(full_ratio, avg_word_ratio)
        if best_score > 0.50:
            scored.append((best_score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:20]]

def get_matching_degrees(query: str):
    if not query:
        return []
    catalog_list = fetch_all_degrees_catalog()
    local_matches = search_degrees(query, catalog_list)
    live_matches = query_degrees_live(query)

    combined = []
    seen = set()
    for d in live_matches + local_matches:
        if d['code'] not in seen:
            seen.add(d['code'])
            combined.append(d)
    return combined

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_degree_program_rules(degree_code: str):
    subscription_key = "5145ba30d5734d4cb6047c47527ef930"
    years = [2027, 2026]
    headers = {
        "User-Agent": "Griffix-Live-Degree-Planner-StudentProject (Contact: yiming.qu@griffithuni.edu.au)",
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Origin": "https://my.griffith.edu.au",
        "Referer": "https://my.griffith.edu.au/"
    }
    for yr in years:
        url = f"https://api-lt.griffith.edu.au/curriculumapi/v1/programrules/degree/{degree_code}/{yr}/Trimester%201?subscription-key={subscription_key}"
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, dict) and "mappedData" in data:
                    return data
        except Exception:
            continue
    return None

def parse_degree_rules(rules_json, degree_code="1031", selected_intake="Trimester 1", campus_preference=None, study_mode="Full-time", fallback_duration=3):
    """
    Parses program rules JSON to:
    1. Extract core courses and detect OR options.
    2. Extract prescribed study plan (semester by semester).
    3. Auto-populate courses directly into the progression matrix.
    4. Accurately assign target CP per term and active terms per year (e.g. BMedSci: Y1 T1-T3, Y2 T1-T2, no Y2 T3).
    """
    core_courses = []
    prescribed_matrix_plan = {}
    holding_alternatives = []
    course_or_map = {}
    include_t3 = False
    duration_years = fallback_duration
    target_cp_map = {}
    active_terms_per_year = {}

    if not rules_json or not isinstance(rules_json, dict):
        if study_mode == "Part-time":
            duration_years = fallback_duration * 2
        return core_courses, prescribed_matrix_plan, holding_alternatives, course_or_map, {
            "duration_years": duration_years,
            "include_t3": include_t3,
            "target_cp_map": target_cp_map,
            "active_terms_per_year": {y: [1, 2] for y in range(1, duration_years + 1)}
        }

    mapped = rules_json.get("mappedData", {}).get("components", {})
    struct_val = mapped.get("progRuleStruct", {}).get("value", {})
    struct_body = struct_val.get("body", [])

    target_core_data = []
    target_study_plan_comp = mapped.get("progRuleStdyPlan", {})

    chosen_plan = None
    clean_camp_pref = normalize_campus_name(campus_preference) if campus_preference else ""

    for item in struct_body:
        if isinstance(item, dict):
            if "core" in str(item.get("title", "")).lower():
                target_core_data = item.get("data", [])
                break
            body_sub = item.get("body", [])
            for sub in body_sub:
                prog_plan = sub.get("programPlan", {})
                if prog_plan:
                    plan_name = sub.get("curriculumReference", {}).get("name", "")
                    clean_plan_name = normalize_campus_name(plan_name)
                    if clean_camp_pref and clean_camp_pref.lower() in clean_plan_name.lower():
                        chosen_plan = prog_plan
                        break
                    elif not chosen_plan:
                        chosen_plan = prog_plan
            if chosen_plan:
                break

    if chosen_plan:
        plan_struct = chosen_plan.get("progRuleStruct", {}).get("body", [])
        for p_item in plan_struct:
            if "core" in str(p_item.get("title", "")).lower():
                target_core_data = p_item.get("data", [])
                break
        target_study_plan_comp = chosen_plan.get("progRuleStdyPlan", {})

    seen_codes = set()
    for entry in target_core_data:
        list_or = entry.get("listOr", [])
        if not list_or:
            continue
        codes_in_group = [str(x.get("code")).replace(" ", "").upper() for x in list_or if x.get("code")]
        is_or = len(codes_in_group) > 1

        for x in list_or:
            c_code = str(x.get("code")).replace(" ", "").upper()
            if not c_code or c_code in seen_codes:
                continue
            seen_codes.add(c_code)
            name = x.get("name") or x.get("courseTitle") or c_code
            cp = x.get("creditPoints", 10)
            or_partners = [c for c in codes_in_group if c != c_code]
            if is_or:
                course_or_map[c_code] = or_partners
            core_courses.append({
                "code": c_code,
                "name": name,
                "cp": cp,
                "is_or": is_or,
                "or_group": or_partners
            })

    sp_items = target_study_plan_comp.get("studyPlanItems", [])
    matched_sp = None
    for sp in sp_items:
        sp_title = str(sp.get("title", "")).lower()
        if selected_intake.lower() in sp_title:
            matched_sp = sp
            break
    if not matched_sp and sp_items:
        matched_sp = sp_items[0]

    placed_in_plan = set()
    is_bmedsci = str(degree_code).strip() == "1280"

    if matched_sp:
        years_list = matched_sp.get("years", [])
        if years_list:
            duration_years = len(years_list)
            for yr_idx, yr_obj in enumerate(years_list, start=1):
                semesters = yr_obj.get("semesters", [])
                active_terms_per_year[yr_idx] = []

                for sem_idx, sem_obj in enumerate(semesters, start=1):
                    term_num = sem_idx
                    if term_num == 3:
                        include_t3 = True
                    active_terms_per_year[yr_idx].append(term_num)

                    term_slot_courses = []
                    term_cp = 0

                    for row in sem_obj.get("rows", []):
                        row_list = row.get("list", [])
                        row_codes = [str(item.get("itemCode", "")).replace(" ", "").upper() for item in row_list if item.get("itemCode")]

                        for r_item in row_list:
                            try:
                                term_cp += int(r_item.get("units", 10))
                            except:
                                term_cp += 10

                        if row_codes:
                            primary_code = row_codes[0]
                            if primary_code not in placed_in_plan:
                                term_slot_courses.append(primary_code)
                                placed_in_plan.add(primary_code)

                            if len(row_codes) > 1:
                                for alt_code in row_codes[1:]:
                                    if alt_code not in holding_alternatives:
                                        holding_alternatives.append(alt_code)
                                    course_or_map[alt_code] = [c for c in row_codes if c != alt_code]
                                course_or_map[primary_code] = [c for c in row_codes if c != primary_code]

                    prescribed_matrix_plan[(yr_idx, term_num)] = term_slot_courses
                    target_cp_map[(yr_idx, term_num)] = term_cp

    # Override for BMedSci (1280): 50 / 50 / 40 in Year 1, 50 / 50 in Year 2, no Y2 T3
    if is_bmedsci and study_mode == "Full-time":
        duration_years = 2
        include_t3 = True
        target_cp_map = {
            (1, 1): 50, (1, 2): 50, (1, 3): 40,
            (2, 1): 50, (2, 2): 50
        }
        active_terms_per_year = {
            1: [1, 2, 3],
            2: [1, 2]  # No Trimester 3 for Year 2!
        }

    for c in core_courses:
        code = c["code"]
        if code not in placed_in_plan and code not in holding_alternatives:
            holding_alternatives.append(code)

    if study_mode == "Part-time":
        duration_years = duration_years * 2
        pt_target_cp_map = {}
        for k, cp in target_cp_map.items():
            pt_target_cp_map[k] = max(10, cp // 2)
        target_cp_map = pt_target_cp_map
        for y in range(1, duration_years + 1):
            if y not in active_terms_per_year:
                active_terms_per_year[y] = [1, 2, 3] if include_t3 else [1, 2]

    return core_courses, prescribed_matrix_plan, holding_alternatives, course_or_map, {
        "duration_years": duration_years,
        "include_t3": include_t3,
        "target_cp_map": target_cp_map,
        "active_terms_per_year": active_terms_per_year
    }

# -----------------------------------------------------------------------------
# 6. PLAN VALIDATION ENGINE (AND / OR AWARE)
# -----------------------------------------------------------------------------
def term_index(year: int, trimester: int) -> int:
    return (year - 1) * 3 + trimester

def validate_plan(plan: dict, catalog_dict: dict):
    warnings = {}
    satisfied = {}
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
            prereq_groups = info.get("prereq_groups", [])
            coreqs = info.get("coreqs", [])
            incomps = info.get("incompatibles", [])

            # 1. Offering Check
            if not is_course_offered_in_term(info, tr):
                c_warns.append(f"Not usually offered in Trimester {tr}")

            # 2. Prerequisite Check with AND / OR Evaluation
            for group in prereq_groups:
                g_courses = group.get("courses", [])
                count_needed = group.get("count", 1)

                satisfied_courses = []
                same_or_later_courses = []

                for p in g_courses:
                    if p in placed_coords:
                        p_yr, p_tr = placed_coords[p]
                        if term_index(p_yr, p_tr) < current_rank:
                            satisfied_courses.append((p, p_yr, p_tr))
                        else:
                            same_or_later_courses.append((p, p_yr, p_tr))

                if len(satisfied_courses) >= count_needed:
                    sat_desc = ", ".join([f"{sc[0]} (completed Year {sc[1]} T{sc[2]})" for sc in satisfied_courses[:count_needed]])
                    c_sats.append(f"Prerequisite satisfied: {sat_desc}")
                elif same_or_later_courses:
                    sample = same_or_later_courses[0]
                    if len(g_courses) == 1:
                        c_warns.append(f"Prereq {sample[0]} must be completed before Year {yr} T{tr} (currently scheduled in Year {sample[1]} T{sample[2]})")
                    else:
                        c_warns.append(f"Prereq ({' OR '.join(g_courses)}) must be completed before Year {yr} T{tr}")
                else:
                    if len(g_courses) == 1:
                        c_warns.append(f"Missing Prerequisite: {g_courses[0]}")
                    else:
                        c_warns.append(f"Missing Prerequisite: Complete at least {count_needed} of ({' OR '.join(g_courses)})")

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
# 7. STREAMLIT-JS ACTION BRIDGE
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
# 8. SIDEBAR: DEGREE SELECTION, COURSE SEARCH & STRUCTURE
# -----------------------------------------------------------------------------
with st.sidebar:
    # -------------------------------------------------------------------------
    # 0. DEGREE PROGRAM SELECTION (EXPANDER)
    # -------------------------------------------------------------------------
    if st.session_state.selected_degree is None or st.session_state.degree_edit_mode:
        with st.expander("🎓 Select a Degree Program", expanded=True):
            st.write("Search your degree to auto-load its structure and prescribed study plan:")
            deg_query = st.text_input("Degree Keyword", placeholder="e.g. Medical Science, Nursing, Business...", key="degree_search_input")

            matched_degs = get_matching_degrees(deg_query) if deg_query else []

            if deg_query and not matched_degs:
                st.caption("No matching degrees found. Try alternative keywords.")
            elif matched_degs:
                deg_options = {d['code']: f"{d['title']} ({d['code']})" for d in matched_degs}
                chosen_code = st.selectbox(
                    "Matching Degrees",
                    options=list(deg_options.keys()),
                    format_func=lambda x: deg_options[x],
                    key="degree_select_box"
                )
                chosen_degree = next((d for d in matched_degs if d['code'] == chosen_code), matched_degs[0])

                # Intakes / Commencing Dropdown
                available_intakes = chosen_degree.get("intakes") or ["Trimester 1", "Trimester 2"]
                order_map = {"trimester 1": 1, "t1": 1, "trimester 2": 2, "t2": 2, "trimester 3": 3, "t3": 3}
                sorted_intakes = sorted(available_intakes, key=lambda x: order_map.get(str(x).lower().strip(), 99))
                intake_choice = st.selectbox("Starting Trimester", options=sorted_intakes, key="deg_start_intake")

                # Study Load
                mode_choice = st.selectbox("Study Load", options=["Full-time", "Part-time"], key="deg_study_mode")

                # Campus Option (Unified: Nathan == Brisbane South, South Bank == Brisbane City)
                campuses = chosen_degree.get("campuses") or []
                campus_choice = None
                if len(campuses) > 1:
                    campus_choice = st.selectbox("Campus", options=campuses, key="deg_campus_choice")
                elif len(campuses) == 1:
                    campus_choice = campuses[0]

                col_set, col_cancel = st.columns([2, 1])
                with col_set:
                    if st.button("➕ Set Degree", type="primary", use_container_width=True):
                        with st.spinner(f"Loading program structure and prescribed study plan for {chosen_degree['title']}..."):
                            rules_data = fetch_degree_program_rules(chosen_degree['code'])
                            core_courses, prescribed_plan, holding_alts, or_map, plan_meta = parse_degree_rules(
                                rules_data,
                                degree_code=chosen_degree['code'],
                                selected_intake=intake_choice,
                                campus_preference=campus_choice,
                                study_mode=mode_choice,
                                fallback_duration=chosen_degree.get('duration_years', 3)
                            )

                            st.session_state.selected_degree = chosen_degree
                            st.session_state.degree_study_mode = mode_choice
                            st.session_state.degree_start_intake = intake_choice
                            st.session_state.degree_campus = campus_choice
                            st.session_state.degree_edit_mode = False

                            # Auto-configure structure
                            st.session_state.num_years_slider = min(10, max(1, plan_meta["duration_years"]))
                            st.session_state.include_t3_cb = plan_meta["include_t3"]
                            st.session_state.term_target_cp = plan_meta["target_cp_map"]
                            st.session_state.active_terms_per_year = plan_meta["active_terms_per_year"]
                            st.session_state.course_or_map = or_map

                            # AUTO-POPULATE PRESCRIBED COURSES DIRECTLY INTO MATRIX
                            st.session_state.plan = prescribed_plan
                            st.session_state.holding_zone = holding_alts

                            # Pre-lookup all courses
                            all_needed_codes = [c for c_list in prescribed_plan.values() for c in c_list] + holding_alts
                            for c_code in all_needed_codes:
                                if c_code not in catalog:
                                    lookup_course(c_code)

                            placed_count = sum(len(c) for c in prescribed_plan.values())
                            st.session_state.feedback_message = (
                                "success",
                                f"Loaded **{chosen_degree['title']}**! Auto-scheduled {placed_count} core courses into the matrix and configured {plan_meta['duration_years']} years."
                            )
                            st.rerun()

                with col_cancel:
                    if st.session_state.degree_edit_mode:
                        if st.button("Cancel", use_container_width=True):
                            st.session_state.degree_edit_mode = False
                            st.rerun()
    else:
        deg = st.session_state.selected_degree
        with st.expander(f"🎓 Program: {deg['title']}", expanded=True):
            st.markdown(f"**{deg['title']}** (`{deg['code']}`)")
            if st.session_state.degree_campus:
                st.caption(f"📍 Campus: **{st.session_state.degree_campus}**")
            st.caption(f"⏱️ Study Load: **{st.session_state.degree_study_mode}**")
            st.caption(f"🚀 Commencing: **{st.session_state.degree_start_intake}**")

            c_edit, c_del = st.columns(2)
            with c_edit:
                if st.button("✏️ Edit Degree", use_container_width=True):
                    st.session_state.degree_edit_mode = True
                    st.rerun()
            with c_del:
                if st.button("🗑️ Delete Degree", use_container_width=True):
                    st.session_state.selected_degree = None
                    st.session_state.degree_edit_mode = False
                    st.session_state.course_or_map = {}
                    st.session_state.term_target_cp = {}
                    st.session_state.active_terms_per_year = {}
                    st.session_state.plan = {}
                    st.session_state.holding_zone = []
                    st.session_state.feedback_message = ("warning", "Degree program removed.")
                    st.rerun()

    st.divider()

    # -------------------------------------------------------------------------
    # 1. ADD A COURSE
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # 2. DEGREE STRUCTURE
    # -------------------------------------------------------------------------
    st.header("2. Degree Structure")
    num_years = st.slider("Degree Duration (Years)", min_value=1, max_value=10, key="num_years_slider")
    include_t3 = st.checkbox("Include Trimester 3 (Summer)", key="include_t3_cb")

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
# 9. HTML, CSS & JS COMPONENT BUILDER
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

def build_planner_html(holding_zone, plan, catalog_dict, num_years, include_t3, selected_code, warnings_dict, target_cp_map, study_mode, course_or_map, active_terms_map):
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

    html, body {
        font-family: var(--font-family);
        color: var(--text-color);
        background: transparent;
        margin: 0;
        padding: 0;
        overflow-y: auto !important;
        overflow-x: hidden !important;
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

    .or-pill {
        background: #e67e22 !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        border: 1px solid rgba(255, 255, 255, 0.35);
    }

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

    /* Scrollable, Responsive Holding Grid */
    .holding-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(215px, 1fr));
        gap: 12px;
        max-height: 280px;
        overflow-y: auto !important;
        padding: 12px;
        background: rgba(0, 0, 0, 0.25);
        border: 1px dashed var(--border-color);
        border-radius: 8px;
    }

    .holding-grid::-webkit-scrollbar {
        width: 7px;
    }
    .holding-grid::-webkit-scrollbar-track {
        background: rgba(0, 0, 0, 0.2);
        border-radius: 4px;
    }
    .holding-grid::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.25);
        border-radius: 4px;
    }
    .holding-grid::-webkit-scrollbar-thumb:hover {
        background: rgba(255, 255, 255, 0.4);
    }
    
    .year-container {
        margin-top: 14px;
        border: 1px solid var(--border-color);
        border-radius: 8px;
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
        html += "<div style='color: rgba(255,255,255,0.4); font-size: 12px; grid-column: 1/-1;'>No courses in holding zone. Add a course from the sidebar or click a course in the matrix to unschedule it.</div>"

    for code in holding_zone:
        info = catalog_dict.get(code) or lookup_course(code) or {"title": code, "credit_points": "10", "offerings": [], "prereq_display": "No Prereqs", "group": ""}
        bg = string_to_pastel_hex(code)
        is_sel = "is-selected" if code == selected_code else ""

        pr_text = f"Pre: {info.get('prereq_display', 'No Prereqs')}"
        cr_text = f" | Co: {', '.join(info['coreqs'])}" if info.get("coreqs") else ""
        offs = format_offerings_label(info.get("offerings", []))

        or_badge = ""
        if code in course_or_map and course_or_map[code]:
            partner_str = ", ".join(course_or_map[code])
            or_badge = f'<span class="badge-pill or-pill" title="Core choice: OR with {partner_str}">⚡ OR with {partner_str}</span>'

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
                {or_badge}
            </div>
            <div style="font-size: 9px; opacity: 0.9; margin-top: 5px; word-break: break-word;">{pr_text}{cr_text}</div>
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
        default_terms = [1, 2, 3] if include_t3 else [1, 2]
        terms_for_year = active_terms_map.get(yr, default_terms)

        html += f"""
        <div class="year-container">
            <div class="year-heading">YEAR {yr}</div>
            <div class="trimesters-row">
        """
        for tr in terms_for_year:
            scheduled = plan.get((yr, tr), [])
            n_courses = len(scheduled)
            cp_sum = sum(int((catalog_dict.get(c) or lookup_course(c) or {}).get("credit_points", 10) or 10) for c in scheduled)
            t_title = f"Trimester {tr}" if tr in [1, 2] else "Trimester 3 (Summer)"

            default_target = 20 if study_mode == "Part-time" else 40
            target_cp = target_cp_map.get((yr, tr), default_target)
            cp_label = f"{cp_sum}/{target_cp} CP"

            is_valid_term = is_course_offered_in_term(selected_meta, tr) if selected_meta else False

            html += f"""
            <div class="trim-col">
                <div class="trim-header">
                    <span>{t_title}</span>
                    <span>{cp_label}</span>
                </div>
            """

            for c in scheduled:
                c_data = catalog_dict.get(c) or lookup_course(c) or {"title": c, "credit_points": "10", "offerings": [], "prereq_display": "No Prereqs", "group": ""}
                bg = string_to_pastel_hex(c)
                is_sel = "is-selected" if c == selected_code else ""
                warns = warnings_dict.get(c, [])
                sats = st.session_state.get('plan_satisfied_dict', {}).get(c, [])

                has_prereq_issue = any("prereq" in str(w).lower() for w in warns)
                prereq_glow_class = "has-prereq-error" if has_prereq_issue else ""

                badges_html = ""
                if warns:
                    badges_html += f"<div class='warning-pill' title='{'; '.join(warns)}'>⚠️ {warns[0]}</div>"
                if sats:
                    badges_html += f"<div class='success-pill' title='{'; '.join(sats)}'>✅ {sats[0]}</div>"

                offs = format_offerings_label(c_data.get("offerings", []))

                or_badge_matrix = ""
                if c in course_or_map and course_or_map[c]:
                    partner_str = ", ".join(course_or_map[c])
                    or_badge_matrix = f'<span class="badge-pill or-pill" title="Core choice: OR with {partner_str}">⚡ OR with {partner_str}</span>'

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
                        {or_badge_matrix}
                    </div>
                    {badges_html}
                </div>
                """

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
# 10. MAIN VIEW
# -----------------------------------------------------------------------------
render_title_html = """
<div style="display: flex; align-items: center; margin-bottom: 0.8rem;">
    <span style="font-size: 2.2rem; margin-right: 8px;">🎓</span>
    <h1 style="margin: 0; padding: 0;">Griffix Degree Planner</h1>
</div>
"""
st.markdown(render_title_html, unsafe_allow_html=True)
st.caption("Plan your study terms, check prerequisites, and schedule your degree path. Select your degree program on the left to get started.")

st.session_state['plan_satisfied_dict'] = plan_satisfied

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

holding_count = len(st.session_state.holding_zone)
holding_rendered_height = 80 if holding_count == 0 else min(310, 60 + ((holding_count + 2) // 3) * 115)

max_in_any_trim = max([len(v) for v in st.session_state.plan.values()] + [1])
courses_render_factor = max_in_any_trim if max_in_any_trim >= 4 else 4
year_block_height = 65 + (courses_render_factor * 85)
calc_height = holding_rendered_height + (num_years * year_block_height) + 240

planner_html = build_planner_html(
    holding_zone=st.session_state.holding_zone,
    plan=st.session_state.plan,
    catalog_dict=catalog,
    num_years=num_years,
    include_t3=include_t3,
    selected_code=st.session_state.selected_course,
    warnings_dict=plan_warnings,
    target_cp_map=st.session_state.term_target_cp,
    study_mode=st.session_state.degree_study_mode,
    course_or_map=st.session_state.course_or_map,
    active_terms_map=st.session_state.active_terms_per_year
)

components.html(planner_html, height=calc_height, scrolling=True)
