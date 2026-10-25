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
import os
import difflib
import time

st.warning("**IMPORTANT**: THIS SITE IS A BETA VERSION OF GRIFFIX FEATURES, AND ONLY INCLUDES **EXPERIMENTAL FEATURES UNDERGOING TESTING**. ACCESS THE OFFICIAL VERSION OF GRIFFIX [HERE](https://griffix.streamlit.app)")
st.error("**WARNING**: THIS SITE DOES **NOT** SAVE WHAT YOU HAVE ON YOUR SCREEN AFTER YOU REFRESH OR CLOSE THE PAGE.")
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

if "degree_core_courses" not in st.session_state:
    st.session_state.degree_core_courses = []

if "degree_flex_courses" not in st.session_state:
    st.session_state.degree_flex_courses = []

if "has_flexible_module" not in st.session_state:
    st.session_state.has_flexible_module = False

if "total_degree_cp" not in st.session_state:
    st.session_state.total_degree_cp = 240

if "num_years_slider" not in st.session_state:
    st.session_state.num_years_slider = 3

if "include_t3_cb" not in st.session_state:
    st.session_state.include_t3_cb = True

# -----------------------------------------------------------------------------
# 2. CAMPUS NORMALIZATION & CODE HELPERS
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

def get_course_subject_area(code_str: str) -> str:
    """Extracts discipline suffix/prefix like MSC, ESC, NSC, ENG, CCJ, IBA."""
    if not code_str:
        return "OTHER"
    clean = code_str.replace(" ", "").upper()
    m = re.search(r'[A-Z]{3,4}', clean)
    return m.group(0) if m else "OTHER"

def get_course_level_label(code_str: str) -> str:
    """Identifies course level from the first digit (e.g. 1014MSC -> Level 1)."""
    m = re.search(r'\d', code_str)
    if not m:
        return "Other Level"
    d = int(m.group(0))
    if d == 1:
        return "Level 1 (1xxx)"
    elif d == 2:
        return "Level 2 (2xxx)"
    elif d == 3:
        return "Level 3 (3xxx)"
    elif d == 4:
        return "Level 4 (4xxx)"
    elif d >= 5:
        return "Level 5+ (5xxx+)"
    return "Other Level"

# -----------------------------------------------------------------------------
# 3. REQUISITES & OFFERINGS PARSER (CP-AWARE & PROGRAM-AWARE)
# -----------------------------------------------------------------------------
def extract_course_codes(text: str):
    """Finds valid Griffith course codes."""
    if not text:
        return []
    pattern = r'\b(?:[0-9]{4}[A-Z]{3,4}(?:_[A-Z0-9]+)?|[A-Z]{3,4}[0-9]{3,4})\b'
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(m.upper() for m in matches))

def extract_program_restrictions(desc: str, mapped_components: dict = None) -> list:
    """
    Generalized program restriction extractor.
    Extracts 4-digit degree codes from API requirement groups, link tags, and descriptions.
    """
    restricted = []

    # 1. Inspect structured mappedData components (e.g. crseOfrgRqmntGrp -> Prog: 1613)
    if mapped_components and isinstance(mapped_components, dict):
        for comp_key, comp_val in mapped_components.items():
            comp_key_lower = comp_key.lower()
            
            # Enrolment requirement groups (Prog: XXXX)
            if "rqmntgrp" in comp_key_lower:
                val_obj = comp_val.get("value", {})
                if isinstance(val_obj, dict):
                    combined_str = f"{val_obj.get('value', '')} {val_obj.get('description', '')}"
                    for m in re.finditer(r'(?:prog(?:ram)?[:\s]+)?\b([0-9]{4})\b', combined_str, re.I):
                        c = m.group(1)
                        # Exclude calendar years (2020-2035)
                        if c not in restricted and not (c.startswith("20") and 2020 <= int(c) <= 2035):
                            restricted.append(c)

                    for row in val_obj.get("rows", []):
                        if isinstance(row, dict):
                            for cell in row.values():
                                if isinstance(cell, dict):
                                    cell_str = f"{cell.get('value', '')} {cell.get('description', '')}"
                                    for m in re.finditer(r'(?:prog(?:ram)?[:\s]+)?\b([0-9]{4})\b', cell_str, re.I):
                                        c = m.group(1)
                                        if c not in restricted and not (c.startswith("20") and 2020 <= int(c) <= 2035):
                                            restricted.append(c)

            # Program link tags (data-code='XXXX')
            if "pstn" in comp_key_lower or "requiste" in comp_key_lower:
                val_str = str(comp_val.get("value", ""))
                for m in re.finditer(r'data-code=[\'"]([0-9]{4})[\'"]', val_str, re.I):
                    c = m.group(1)
                    if c not in restricted:
                        restricted.append(c)

    if not desc:
        return restricted

    # 2. Generalized text pattern matching
    patterns = [
        r'must be enrolled in\s+[^.;\n\d]*\b([0-9]{4})\b',
        r'must be undertaking\s+[^.;\n\d]*\b([0-9]{4})\b',
        r'restrictions?:\s*[^.;\n\d]*\b([0-9]{4})\b',
        r'restricted to\s+[^.;\n\d]*\b([0-9]{4})\b',
        r'\b(?:prog(?:ram)?)\s*[:#]?\s*([0-9]{4})\b',
        r'data-code=[\'"]([0-9]{4})[\'"]'
    ]

    for pat in patterns:
        for match in re.finditer(pat, desc, re.I):
            c = match.group(1)
            if c not in restricted and not (c.startswith("20") and 2020 <= int(c) <= 2035):
                restricted.append(c)

    return restricted


def extract_cp_prereq(rule_def: str = "", rule_sum: str = "", desc: str = "") -> int:
    """Extracts minimum prior credit points required (e.g. 80 CP in 3002LFC)."""
    combined = f"{rule_def} {rule_sum} {desc}".upper()
    
    # 1. Match UNITS (80)
    m = re.search(r'UNITS\s*\((\d+)\)', combined)
    if m:
        return int(m.group(1))
        
    # 2. Match phrases like 'completed at least 80 credit points', 'completion of 130CP'
    m2 = re.search(r'(?:COMPLET(?:ED?|ION OF)|ACHIEVED?|EARNED?)\s*(?:AT LEAST\s*)?(\d{2,3})\s*(?:CREDIT POINTS|CP|UNITS)', combined)
    if m2:
        return int(m2.group(1))
        
    # 3. Match '80CP completed' or '80 credit points prior'
    m3 = re.search(r'(\d{2,3})\s*(?:CREDIT POINTS|CP|UNITS)\s*(?:PRIOR TO|COMPLETED|ACHIEVED)', combined)
    if m3:
        return int(m3.group(1))
        
    return 0


def parse_rule_definition_to_groups(rule_def: str, rule_sum: str = "") -> list:
    """Parses Curriculum API ruleDefinition accurately into AND / OR course groups."""
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
    """Formats structured prerequisite groups into human-readable strings."""
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
    match = re.search(r'(?:incompatible(?:s)?|anti-?requisite(?:s)?)\s*[:\-]?\s*([^.;\n<]+)', desc, re.I)
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

# -----------------------------------------------------------------------------
# 4. OFFERING AVAILABILITY CHECKER
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

import traceback
import time

# -----------------------------------------------------------------------------
# 5. FULL CATALOG LOADER WITH DIAGNOSTICS & MULTI-PATH RESOLUTION
# -----------------------------------------------------------------------------
def find_project_file(filename: str):
    """Finds a local file regardless of execution directory on Streamlit Cloud."""
    script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "."
    candidates = [
        os.path.join(script_dir, filename),
        os.path.join(os.getcwd(), filename),
        os.path.join(os.getcwd(), "data", filename),
        filename
    ]
    for path in candidates:
        if os.path.isfile(path):
            print(f"[FILE RESOLVER] ✅ Found '{filename}' at: {path}", flush=True)
            return path
    print(f"[FILE RESOLVER] ❌ Could not find '{filename}' in candidate paths: {candidates}", flush=True)
    return None

@st.cache_data(ttl=86400, show_spinner=False)
def load_full_catalog():
    """Loads course catalog from local courses.json first, then live endpoint."""
    catalog = {}
    print("\n" + "="*70, flush=True)
    print("[CATALOG LOADER] Initializing ~3,000 course catalog...", flush=True)

    # 1. Check local pre-downloaded course catalog (Recommended for Streamlit Cloud)
    for fname in ["courses.json", "catalog.json", "courses_data.json"]:
        local_path = find_project_file(fname)
        if local_path:
            print(f"[CATALOG LOADER] Reading courses from local file: {local_path}", flush=True)
            try:
                t0 = time.time()
                with open(local_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results = data.get("response", {}).get("resultPacket", {}).get("results", [])
                    print(f"[CATALOG LOADER] Raw results in file: {len(results)} items", flush=True)
                    for item in results:
                        meta = item.get("listMetadata", {})
                        cat_numbers = meta.get("categoryNumber", [])
                        if not cat_numbers:
                            continue
                        code = str(cat_numbers[0]).replace(" ", "").upper().strip()
                        desc = meta.get("description", [""])[0] or ""
                        fallback_groups = parse_rule_definition_to_groups("", desc)

                        catalog[code] = {
                            "code": code,
                            "title": meta.get("title", [code])[0],
                            "credit_points": meta.get("creditPoints", ["10"])[0],
                            "description": desc,
                            "offerings": list(set(meta.get("nextOffering", []))),
                            "career": meta.get("academicCareerName", ["Undergraduate"])[0],
                            "group": meta.get("academicGrpDescription", ["Other"])[0],
                            "subject_area": get_course_subject_area(code),
                            "prereq_groups": fallback_groups,
                            "prereq_display": format_prereq_display(fallback_groups),
                            "min_cp_prereq": extract_cp_prereq("", "", desc),
                            "coreqs": extract_coreqs(desc),
                            "incompatibles": extract_incompatibles(desc),
                            "program_restrictions": extract_program_restrictions(desc)
                        }
                print(f"[CATALOG LOADER] ✅ Successfully indexed {len(catalog)} courses in {time.time()-t0:.2f}s.", flush=True)
                print("="*70 + "\n", flush=True)
                return catalog
            except Exception as e:
                print(f"[CATALOG LOADER] Error parsing {local_path}: {e}", flush=True)

    # 2. Live network attempt
    url = "https://search.griffith.edu.au/s/search.json?collection=griff~sp-courses-api&profile=courses&query=!padrenull&sort=metafborderna&num_ranks=500&start_rank=1"
    print(f"[CATALOG LOADER] Attempting live network fetch from:\n  -> {url}", flush=True)
    t0 = time.time()
    status_code, response_data = cloudflare_safe_get(url, timeout=12)
    print(f"[CATALOG LOADER] Live HTTP Status: {status_code} ({time.time()-t0:.2f}s)", flush=True)

    if status_code == 200 and isinstance(response_data, dict):
        results = response_data.get("response", {}).get("resultPacket", {}).get("results", [])
        for item in results:
            meta = item.get("listMetadata", {})
            cat_numbers = meta.get("categoryNumber", [])
            if not cat_numbers:
                continue
            code = str(cat_numbers[0]).replace(" ", "").upper().strip()
            desc = meta.get("description", [""])[0] or ""
            catalog[code] = {
                "code": code,
                "title": meta.get("title", [code])[0],
                "credit_points": meta.get("creditPoints", ["10"])[0],
                "description": desc,
                "offerings": list(set(meta.get("nextOffering", []))),
                "career": meta.get("academicCareerName", ["Undergraduate"])[0],
                "group": meta.get("academicGrpDescription", ["Other"])[0],
                "subject_area": get_course_subject_area(code),
                "prereq_groups": parse_rule_definition_to_groups("", desc),
                "prereq_display": format_prereq_display(parse_rule_definition_to_groups("", desc)),
                "min_cp_prereq": extract_cp_prereq("", "", desc),
                "coreqs": extract_coreqs(desc),
                "incompatibles": extract_incompatibles(desc),
                "program_restrictions": extract_program_restrictions(desc)
            }
        print(f"[CATALOG LOADER] ✅ Live network fetch loaded {len(catalog)} courses.", flush=True)
        print("="*70 + "\n", flush=True)
        return catalog

    print(f"[CATALOG LOADER] ⚠️ Could not reach Funnelback on Cloudflare (HTTP {status_code}).", flush=True)
    print(f"[CATALOG LOADER] 💡 TIP: Download courses.json via browser and commit to your repo to load all 3,000 courses.", flush=True)
    print("="*70 + "\n", flush=True)
    return catalog


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_course_from_curriculum_api(clean_code: str, selected_year: int, catalog_offerings: list):
    subscription_key = "b8ae10d400ef42f89a127abe4a760e46"
    
    # Try the selected year, then 2026, 2027, 2025
    years_to_try = [selected_year, 2026, 2027, 2025]
    years_to_try = list(dict.fromkeys([y for y in years_to_try if y]))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Origin": "https://my.griffith.edu.au",
        "Referer": "https://my.griffith.edu.au/"
    }

    for yr in years_to_try:
        yr_short = str(yr)[-2:]
        # Correct PeopleSoft term codes for the specific year: T1=3{yy}1, T2=3{yy}5, T3=3{yy}8
        terms_to_try = [f"3{yr_short}1", f"3{yr_short}5", f"3{yr_short}8"]

        for term_code in terms_to_try:
            url = f"https://api-lt.griffith.edu.au/curriculumapi/v1/course/{clean_code}/{yr}/{term_code}?subscription-key={subscription_key}"
            try:
                resp = requests.get(url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    mapped = data.get("mappedData", {}).get("components", {})

                    prereq_groups, coreqs, incompatibles = [], [], []
                    min_cp = 0

                    req_obj = mapped.get("crseRequiste", {}).get("value", {})
                    if isinstance(req_obj, dict):
                        for r in req_obj.get("requisites", []):
                            rtype = str(r.get("type", "")).upper()
                            rule_def = str(r.get("ruleDefinition", ""))
                            rule_sum = str(r.get("ruleSummary", ""))

                            cp_req = extract_cp_prereq(rule_def, rule_sum, "")
                            if cp_req > min_cp:
                                min_cp = cp_req

                            if "PRE" in rtype:
                                groups = parse_rule_definition_to_groups(rule_def, rule_sum)
                                for g in groups:
                                    filtered_codes = [c for c in g.get("courses", []) if c != clean_code]
                                    if filtered_codes:
                                        prereq_groups.append({"count": min(g.get("count", 1), len(filtered_codes)), "courses": filtered_codes})
                            elif "CO" in rtype:
                                coreqs.extend([c for c in extract_course_codes(f"{rule_def} {rule_sum}") if c != clean_code])
                            elif "ANTI" in rtype or "INCOMPATIBLE" in rtype:
                                incompatibles.extend([c for c in extract_course_codes(f"{rule_def} {rule_sum}") if c != clean_code])

                    other_req = mapped.get("crseOthrRequiste", {}).get("value") or ""
                    desc_text = mapped.get("crseDescr", {}).get("value", "")
                    cmmt_pstn = mapped.get("crseCmmtCrsePstn", {}).get("value") or ""
                    combined_req_text = f"{other_req} {desc_text} {cmmt_pstn}"

                    desc_cp = extract_cp_prereq("", "", combined_req_text)
                    if desc_cp > min_cp:
                        min_cp = desc_cp

                    incomp_match = re.search(r'(?:incompatible(?:s)?|anti-?requisite(?:s)?)\s*[:\-]?\s*([^.;\n<]+)', combined_req_text, re.I)
                    if incomp_match:
                        incompatibles.extend([c for c in extract_course_codes(incomp_match.group(1)) if c != clean_code])

                    prog_restrictions = extract_program_restrictions(combined_req_text, mapped_components=mapped)

                    final_offerings = list(catalog_offerings)
                    if not final_offerings:
                        tri_val = mapped.get("crseTri", {}).get("value", [])
                        if isinstance(tri_val, list): final_offerings.extend(tri_val)
                        elif isinstance(tri_val, str): final_offerings.append(tri_val)

                    title = data.get("name") or mapped.get("crseShrtDescr", {}).get("value") or clean_code
                    cp_val = mapped.get("crseAwrdCrdtPnts", {}).get("value", {})
                    cp = str(cp_val.get("value", 10) if isinstance(cp_val, dict) else data.get("unitsMinimum", 10))

                    return {
                        "code": clean_code,
                        "title": title,
                        "credit_points": cp,
                        "description": desc_text,
                        "offerings": list(dict.fromkeys(final_offerings)),
                        "career": data.get("subtype", "Undergraduate"),
                        "group": data.get("orgParent", "Other"),
                        "subject_area": get_course_subject_area(clean_code),
                        "prereq_groups": prereq_groups,
                        "prereq_display": format_prereq_display(prereq_groups),
                        "min_cp_prereq": min_cp,
                        "coreqs": list(dict.fromkeys(coreqs)),
                        "incompatibles": list(dict.fromkeys(incompatibles)),
                        "program_restrictions": prog_restrictions,
                        "from_curriculum_api": True
                    }
            except Exception:
                continue

    return None

def lookup_course(clean_code: str, selected_year: int = None):
    if selected_year is None:
        selected_year = datetime.now().year

    clean_code = str(clean_code).replace(" ", "").upper().strip()
    catalog_entry = catalog.get(clean_code, {})

    # If already verified via Curriculum API, return immediately from memory
    if catalog_entry.get("from_curriculum_api"):
        return catalog_entry

    offerings = catalog_entry.get("offerings", [])
    print(f"[COURSE LOOKUP] Fetching live requisites for {clean_code} from Curriculum API...", flush=True)
    curriculum_meta = fetch_course_from_curriculum_api(clean_code, selected_year, offerings)
    
    if curriculum_meta:
        print(f"[COURSE LOOKUP] ✅ {clean_code}: Pre='{curriculum_meta['prereq_display']}', Co={curriculum_meta['coreqs']}, Anti={curriculum_meta['incompatibles']}, Prog={curriculum_meta['program_restrictions']}", flush=True)
        catalog[clean_code] = curriculum_meta
        return curriculum_meta

    if catalog_entry:
        return catalog_entry
    return None


catalog = load_full_catalog()


# -----------------------------------------------------------------------------
# 6. LIVE DEGREE SEARCH WITH FLUSHED DIAGNOSTICS & RESILIENT QUERYING
# -----------------------------------------------------------------------------
def get_fallback_degrees():
    print("[DEGREE SERVICE] ⚠️ Falling back to static degree list.", flush=True)
    raw_list = [
        {"code": "1031", "title": "Bachelor of Biomedical Science", "campuses": ["Brisbane South", "Nathan", "Gold Coast"], "intakes": ["Trimester 1", "Trimester 2"], "duration_years": 3, "career": "Undergraduate", "total_cp": 240, "group": "Griffith Sciences"},
        {"code": "1651", "title": "Bachelor of Medical Science", "campuses": ["Brisbane South", "Nathan", "Gold Coast"], "intakes": ["Trimester 1"], "duration_years": 2, "career": "Undergraduate", "total_cp": 240, "group": "Griffith Health"},
        {"code": "1534", "title": "Bachelor of Computer Science", "campuses": ["Gold Coast", "Brisbane South (Nathan)"], "intakes": ["Trimester 1", "Trimester 2"], "duration_years": 3, "career": "Undergraduate", "total_cp": 240, "group": "Griffith Sciences"},
        {"code": "1280", "title": "Bachelor of Nursing", "campuses": ["Brisbane South (Nathan)", "Gold Coast", "Logan"], "intakes": ["Trimester 1"], "duration_years": 3, "career": "Undergraduate", "total_cp": 240, "group": "Griffith Health"},
        {"code": "1564", "title": "Bachelor of Business", "campuses": ["Brisbane South (Nathan)", "Gold Coast", "Online"], "intakes": ["Trimester 1", "Trimester 2", "Trimester 3"], "duration_years": 3, "career": "Undergraduate", "total_cp": 240, "group": "Griffith Business School"}
    ]
    for d in raw_list:
        d["campuses"] = list(dict.fromkeys(normalize_campus_name(c) for c in d["campuses"]))
    return raw_list


def parse_degree_results(results):
    """Parses raw Funnelback degree results JSON into clean degree records."""
    degrees = []
    print(f"[DEGREE PARSER] Parsing {len(results)} degree items from JSON...", flush=True)

    for r in results:
        meta = r.get("listMetadata", {})
        
        # 1. Degree Code
        codes = meta.get("code", [])
        code = str(codes[0]).strip() if codes else ""
        if not code:
            url = r.get("liveUrl", "") or r.get("displayUrl", "")
            match = re.search(r'-([0-9]{4})\b', url)
            if match:
                code = match.group(1)
            else:
                continue

        # 2. Title
        title_list = meta.get("title", [])
        title = title_list[0] if title_list else r.get("title", code)

        # 3. Campuses
        raw_campuses = meta.get("campusName", [])
        clean_campuses = []
        for c in raw_campuses:
            norm = normalize_campus_name(c)
            if norm and norm not in clean_campuses:
                clean_campuses.append(norm)

        # 4. Intakes
        intakes = list(dict.fromkeys(meta.get("intakesName", [])))

        # 5. Duration (Extract undergraduate full-time years, avoiding 6-year part-time)
        durations = meta.get("duration", [])
        digit_durations = [
            int(str(d).strip()) for d in durations 
            if str(d).strip().isdigit() and 1 <= int(str(d).strip()) <= 6
        ]
        if digit_durations:
            non_six = [x for x in digit_durations if x < 6]
            years = min(non_six) if non_six else digit_durations[0]
        else:
            years = 3
            for d in durations:
                m = re.search(r'(\d+)\s*years?', str(d), re.I)
                if m and int(m.group(1)) <= 6:
                    years = int(m.group(1))
                    break

        # 6. Credit Points
        cp_val = 240
        for cp in meta.get("creditPoints", []):
            if str(cp).isdigit():
                cp_val = int(cp)
                break

        career = meta.get("academicCareer", ["Undergraduate"])[0]
        group = meta.get("academicGroupDescription", ["Other"])[0]

        degrees.append({
            "code": code,
            "title": title,
            "campuses": clean_campuses,
            "intakes": intakes,
            "duration_years": years,
            "durations_raw": durations,
            "career": career,
            "total_cp": cp_val,
            "group": group
        })

    print(f"[DEGREE PARSER] Successfully parsed {len(degrees)} degrees.", flush=True)
    return degrees

# -----------------------------------------------------------------------------
# CLOUDFLARE BYPASS CLIENT (TLS IMPERSONATION)
# -----------------------------------------------------------------------------
try:
    from curl_cffi import requests as cureq
    HAS_CURL_CFFI = True
    print("[INIT] ✅ curl_cffi is available. Chrome TLS spoofing enabled.", flush=True)
except ImportError:
    HAS_CURL_CFFI = False
    print("[INIT] ⚠️ curl_cffi not installed. Standard requests will be used.", flush=True)

CHROME_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-AU,en-US;q=0.9,en;q=0.8",
    "Origin": "https://www.griffith.edu.au",
    "Referer": "https://www.griffith.edu.au/",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def cloudflare_safe_get(url: str, timeout: int = 15):
    """
    Performs an HTTP GET request that impersonates real Chrome browser TLS fingerprints
    to bypass Cloudflare's 403 'Just a moment...' WAF challenge.
    """
    if HAS_CURL_CFFI:
        try:
            # Impersonate Chrome 124 TLS & HTTP/2 framing
            resp = cureq.get(
                url,
                headers=CHROME_HEADERS,
                impersonate="chrome124",
                timeout=timeout
            )
            return resp.status_code, resp.json() if resp.status_code == 200 else resp.text
        except Exception as e:
            print(f"[CLOUDFLARE BYPASS] curl_cffi error: {e}", flush=True)

    # Fallback to standard requests if curl_cffi is absent or fails
    try:
        import requests
        resp = requests.get(url, headers=CHROME_HEADERS, timeout=timeout)
        return resp.status_code, resp.json() if resp.status_code == 200 else resp.text
    except Exception as e:
        return 0, str(e)


def find_project_file(filename: str):
    """Finds a local file regardless of execution directory."""
    script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "."
    candidates = [
        os.path.join(script_dir, filename),
        os.path.join(os.getcwd(), filename),
        os.path.join(os.getcwd(), "data", filename),
        filename
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None

# -----------------------------------------------------------------------------
# 6. DEGREE CATALOG FETCHER WITH 403 BYPASS
# -----------------------------------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_all_degrees_catalog():
    """
    Fetches the 500-degree catalog using Chrome TLS spoofing to bypass 403 blocks.
    Falls back to local degree_data1json.json if Cloudflare blocks the hosting IP.
    """
    url = "https://search.griffith.edu.au/s/search.json?collection=griff~sp-degrees-api&profile=degrees&num_ranks=500&start_rank=1"
    print("\n" + "="*70, flush=True)
    print(f"[DEGREE SERVICE] Fetching 500 degrees with Chrome TLS spoofing from:\n  -> {url}", flush=True)

    t0 = time.time()
    status_code, response_data = cloudflare_safe_get(url, timeout=15)
    elapsed = time.time() - t0
    print(f"[DEGREE SERVICE] Response status: {status_code} in {elapsed:.2f}s", flush=True)

    # If the bypass succeeds (HTTP 200)
    if status_code == 200 and isinstance(response_data, dict):
        packet = response_data.get("response", {}).get("resultPacket", {})
        results = packet.get("results", [])
        total_matching = packet.get("resultsSummary", {}).get("totalMatching", 0)
        print(f"[DEGREE SERVICE] ✅ Cloudflare bypassed! Received {len(results)}/{total_matching} degrees.", flush=True)

        parsed = parse_degree_results(results)
        if parsed:
            print("="*70 + "\n", flush=True)
            return parsed

    print(f"[DEGREE SERVICE] ⚠️ Live request returned {status_code}. Checking local file fallback...", flush=True)

    # Check local saved file
    for filename in ["degree_data1json.json", "degrees.json"]:
        local_path = find_project_file(filename)
        if local_path:
            print(f"[DEGREE SERVICE] Loading local fallback file: {local_path}", flush=True)
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results = data.get("response", {}).get("resultPacket", {}).get("results", [])
                    parsed = parse_degree_results(results)
                    if parsed:
                        print(f"[DEGREE SERVICE] ✅ Loaded {len(parsed)} degrees from {local_path}.", flush=True)
                        print("="*70 + "\n", flush=True)
                        return parsed
            except Exception as e:
                print(f"[DEGREE SERVICE] Failed reading {local_path}: {e}", flush=True)

    print("[DEGREE SERVICE] ⚠️ Falling back to built-in static degrees.", flush=True)
    print("="*70 + "\n", flush=True)
    return get_fallback_degrees()


def query_degrees_live(query_str: str):
    if not query_str or len(query_str.strip()) < 2:
        return []
    clean_q = urllib.parse.quote(query_str.strip())
    print(f"\n[LIVE DEGREE SEARCH] Querying live: '{query_str.strip()}'...", flush=True)
    
    urls = [
        f"https://search.griffith.edu.au/s/search.json?collection=griff~sp-degrees-api&profile=degrees&num_ranks=40&query={clean_q}",
        f"https://search.griffith.edu.au/s/search.json?collection=griff~sp-degrees-api&profile=degrees&num_ranks=40&query={clean_q}&smeta_intlCohortYears_orsand=2026&smeta_intlCohortYears_orsand=2027"
    ]
    
    for url in urls:
        try:
            print(f"[LIVE DEGREE SEARCH] Requesting: {url}", flush=True)
            t0 = time.time()
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
            elapsed = time.time() - t0
            print(f"[LIVE DEGREE SEARCH] -> Status: {resp.status_code} in {elapsed:.2f}s", flush=True)
            
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("response", {}).get("resultPacket", {}).get("results", [])
                parsed = parse_degree_results(results)
                if parsed:
                    print(f"[LIVE DEGREE SEARCH] ✅ Found {len(parsed)} matching live degrees.", flush=True)
                    return parsed
            else:
                print(f"[LIVE DEGREE SEARCH] -> Non-200 response: {resp.status_code} ({resp.text[:150]})", flush=True)
        except Exception as e:
            print(f"[LIVE DEGREE SEARCH] -> Exception: {e}", flush=True)
            traceback.print_exc()

    return []

def search_degrees(query: str, degrees: list):
    """Matches user keywords against the pre-fetched catalog entirely in Python."""
    if not query:
        return degrees[:25]

    q = query.strip().lower()
    q_words = q.split()

    # 1. Exact 4-digit code match (e.g. '1280' or '1162')
    exact_code = [d for d in degrees if d.get('code') == q]
    if exact_code:
        return exact_code

    # 2. Token match: ALL query words must appear in Title or Code
    matched = []
    for d in degrees:
        title_lower = d.get('title', '').lower()
        code_str = d.get('code', '').lower()
        search_corpus = f"{title_lower} {code_str}"

        if all(w in search_corpus for w in q_words):
            # Prioritize exact phrase match over separated words
            exact_phrase = q in title_lower
            matched.append((exact_phrase, d))

    if matched:
        # Sort exact phrase first, then alphabetically by title
        matched.sort(key=lambda x: (not x[0], x[1].get('title', '')))
        return [d for _, d in matched[:30]]

    # 3. Fuzzy match fallback for slight typos
    scored = []
    for d in degrees:
        target = f"{d.get('title', '')} {d.get('code', '')}".lower()
        full_ratio = difflib.SequenceMatcher(None, q, target).ratio()
        word_ratios = [max(difflib.SequenceMatcher(None, qw, tw).ratio() for tw in target.split()) for qw in q_words]
        avg_word_ratio = sum(word_ratios) / len(word_ratios) if word_ratios else 0
        best_score = max(full_ratio, avg_word_ratio)
        if best_score > 0.50:
            scored.append((best_score, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:25]]

def get_matching_degrees(query: str):
    """Pure in-memory Python search against the 500-ranks downloaded catalog."""
    if not query:
        return []

    catalog_list = fetch_all_degrees_catalog()
    results = search_degrees(query, catalog_list)
    print(f"[SEARCH DEGREE] Query '{query.strip()}' matched {len(results)} program(s): {[d['title'] + ' (' + d['code'] + ')' for d in results[:4]]}", flush=True)
    return results

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

def optimize_prescribed_plan(plan: dict, catalog_dict: dict) -> dict:
    """Smart-adjusts the auto-populated plan to satisfy term offerings and prerequisites."""
    for clist in plan.values():
        for code in clist:
            if code not in catalog_dict:
                lookup_course(code)

    def evaluate_conflicts(p):
        warns, _ = validate_plan(p, catalog_dict)
        offering_penalty = sum(1 for wlist in warns.values() for w in wlist if "not usually offered" in w.lower())
        prereq_penalty = sum(10 for wlist in warns.values() for w in wlist if "prereq" in w.lower())
        return offering_penalty * 2 + prereq_penalty

    changed = True
    iterations = 0
    while changed and iterations < 10:
        changed = False
        iterations += 1
        current_score = evaluate_conflicts(plan)
        if current_score == 0:
            break

        terms = list(plan.keys())
        for i, t1 in enumerate(terms):
            for t2 in terms[i+1:]:
                for c1 in list(plan[t1]):
                    for c2 in list(plan[t2]):
                        plan[t1].remove(c1)
                        plan[t2].remove(c2)
                        plan[t1].append(c2)
                        plan[t2].append(c1)

                        new_score = evaluate_conflicts(plan)
                        if new_score < current_score:
                            current_score = new_score
                            changed = True
                            break
                        else:
                            plan[t1].remove(c2)
                            plan[t2].remove(c1)
                            plan[t1].append(c1)
                            plan[t2].append(c2)
                    if changed:
                        break
                if changed:
                    break

    return plan

def parse_degree_rules(rules_json, degree_code="1031", selected_intake="Trimester 1", campus_preference=None, study_mode="Full-time", fallback_duration=3):
    core_courses = []
    prescribed_matrix_plan = {}
    holding_alternatives = []
    course_or_map = {}
    flexible_module_courses = []
    has_flexible_module = False
    include_t3 = False
    duration_years = fallback_duration
    target_cp_map = {}
    active_terms_per_year = {}

    total_degree_cp = 240
    if rules_json and isinstance(rules_json, dict):
        total_degree_cp = int(rules_json.get("unitsMinimum") or 240)

    if not rules_json or not isinstance(rules_json, dict):
        if study_mode == "Part-time":
            duration_years = fallback_duration * 2
        return core_courses, prescribed_matrix_plan, holding_alternatives, course_or_map, flexible_module_courses, has_flexible_module, {
            "duration_years": duration_years,
            "include_t3": include_t3,
            "target_cp_map": target_cp_map,
            "total_degree_cp": total_degree_cp,
            "active_terms_per_year": {y: [1, 2] for y in range(1, duration_years + 1)}
        }

    print(f"\n[DEGREE RULES] Parsing program rules for Degree {degree_code}...", flush=True)
    mapped = rules_json.get("mappedData", {}).get("components", {})
    struct_val = mapped.get("progRuleStruct", {}).get("value", {})
    struct_body = struct_val.get("body", [])

    target_core_data = []
    target_flex_data = []
    target_study_plan_comp = mapped.get("progRuleStdyPlan", {})

    clean_camp_pref = normalize_campus_name(campus_preference) if campus_preference else ""
    chosen_plan = None
    first_fallback_plan = None

    for item in struct_body:
        if isinstance(item, dict):
            item_title = str(item.get("title", "")).lower()
            print(f"[DEGREE RULES] Found structure section: '{item.get('title')}' with {len(item.get('data', []))} data entries", flush=True)

            if "core" in item_title:
                target_core_data.extend(item.get("data", []))
            
            # Match Flexible, Elective, Option, Major, and Listed course containers
            if any(k in item_title for k in ["flexible", "elective", "option", "major", "listed"]):
                target_flex_data.extend(item.get("data", []))
                has_flexible_module = True

            body_sub = item.get("body", [])
            for sub in body_sub:
                sub_title = str(sub.get("title", "")).lower()
                if any(k in sub_title for k in ["flexible", "elective", "option", "major", "listed"]):
                    target_flex_data.extend(sub.get("data", []))
                    has_flexible_module = True

                prog_plan = sub.get("programPlan", {})
                if prog_plan:
                    if not first_fallback_plan:
                        first_fallback_plan = prog_plan
                    plan_name = sub.get("curriculumReference", {}).get("name", "")
                    clean_plan_name = normalize_campus_name(plan_name)
                    if clean_camp_pref and (clean_camp_pref.lower() in clean_plan_name.lower() or clean_plan_name.lower() in clean_camp_pref.lower()):
                        chosen_plan = prog_plan
                        break
            if chosen_plan:
                break

    if not chosen_plan and first_fallback_plan:
        chosen_plan = first_fallback_plan

    if chosen_plan:
        plan_struct = chosen_plan.get("progRuleStruct", {}).get("body", [])
        for p_item in plan_struct:
            p_title = str(p_item.get("title", "")).lower()
            if "core" in p_title:
                target_core_data.extend(p_item.get("data", []))
            if any(k in p_title for k in ["flexible", "elective", "option", "major", "listed"]):
                target_flex_data.extend(p_item.get("data", []))
                has_flexible_module = True
        target_study_plan_comp = chosen_plan.get("progRuleStdyPlan", {})

    # Extract all flexible/elective course codes
    for entry in target_flex_data:
        # Check listOr
        for x in entry.get("listOr", []):
            if isinstance(x, dict):
                for k in ["code", "courseCode", "itemCode"]:
                    f_code = str(x.get(k, "")).replace(" ", "").upper()
                    if f_code and re.search(r'\d{4}[A-Z]{3,4}', f_code):
                        if f_code not in flexible_module_courses:
                            flexible_module_courses.append(f_code)
        # Check direct code properties on entry
        if isinstance(entry, dict):
            for k in ["code", "courseCode", "itemCode"]:
                f_code = str(entry.get(k, "")).replace(" ", "").upper()
                if f_code and re.search(r'\d{4}[A-Z]{3,4}', f_code):
                    if f_code not in flexible_module_courses:
                        flexible_module_courses.append(f_code)

    print(f"[DEGREE RULES] ✅ Extracted {len(flexible_module_courses)} flexible/elective courses from rules: {flexible_module_courses[:8]}", flush=True)

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
                    for row in sem_obj.get("rows", []):
                        row_list = row.get("list", [])
                        row_codes = [str(item.get("itemCode", "")).replace(" ", "").upper() for item in row_list if item.get("itemCode")]
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
                    target_cp_map[(yr_idx, term_num)] = 40

    if is_bmedsci and study_mode == "Full-time":
        duration_years = 2
        include_t3 = True
        target_cp_map = {
            (1, 1): 50, (1, 2): 50, (1, 3): 40,
            (2, 1): 50, (2, 2): 50
        }
        active_terms_per_year = {
            1: [1, 2, 3],
            2: [1, 2]
        }

    for c in core_courses:
        code = c["code"]
        if code not in placed_in_plan and code not in holding_alternatives:
            holding_alternatives.append(code)

    if study_mode == "Part-time":
        duration_years = duration_years * 2
        pt_target_cp_map = {}
        for k in target_cp_map:
            pt_target_cp_map[k] = 20
        target_cp_map = pt_target_cp_map
        for y in range(1, duration_years + 1):
            if y not in active_terms_per_year:
                active_terms_per_year[y] = [1, 2, 3] if include_t3 else [1, 2]

    prescribed_matrix_plan = optimize_prescribed_plan(prescribed_matrix_plan, catalog)

    return core_courses, prescribed_matrix_plan, holding_alternatives, course_or_map, flexible_module_courses, has_flexible_module, {
        "duration_years": duration_years,
        "include_t3": include_t3,
        "target_cp_map": target_cp_map,
        "total_degree_cp": total_degree_cp,
        "active_terms_per_year": active_terms_per_year
    }

# -----------------------------------------------------------------------------
# 7. PLAN VALIDATION ENGINE & WHOLE-DEGREE PREREQUISITE EVALUATOR
# -----------------------------------------------------------------------------
def term_index(year: int, trimester: int) -> int:
    return (year - 1) * 3 + trimester

def term_from_index(index: int) -> tuple[int, int]:
    yr = (index - 1) // 3 + 1
    tr = (index - 1) % 3 + 1
    return yr, tr

def validate_plan(plan: dict, catalog_dict: dict):
    warnings = {}
    satisfied = {}
    placed_coords = {}

    for (yr, tr), courses in plan.items():
        for c in courses:
            placed_coords[c] = (yr, tr)

    all_planned = set(placed_coords.keys())
    all_planned_or_held = all_planned | set(st.session_state.get("holding_zone", []))
    sel_deg_code = st.session_state.get("selected_degree", {}).get("code") if st.session_state.get("selected_degree") else None

    print(f"\n[VALIDATE PLAN] Validating {len(all_planned)} scheduled courses against plan...", flush=True)

    for (yr, tr), courses in plan.items():
        current_rank = term_index(yr, tr)
        for c in courses:
            c_warns = []
            c_sats = []

            # FORCE live lookup so real requisites from Curriculum API are verified
            info = lookup_course(c) or catalog_dict.get(c) or {}
            prereq_groups = info.get("prereq_groups", [])
            coreqs = info.get("coreqs", [])
            min_cp = info.get("min_cp_prereq", 0)

            # 1. Program restriction check
            prog_restr = [str(x).strip() for x in info.get("program_restrictions", []) if str(x).strip()]
            if prog_restr and sel_deg_code and str(sel_deg_code).strip() not in prog_restr:
                c_warns.append(f"Restricted to program(s): {', '.join(prog_restr)}")

            # 2. Offering Check
            if not is_course_offered_in_term(info, tr):
                c_warns.append(f"Not usually offered in Trimester {tr}")

            # 3. Minimum Prior Credit Points Check
            if min_cp > 0:
                prior_cp = sum(
                    int((catalog_dict.get(pc) or lookup_course(pc) or {}).get("credit_points", 10) or 10)
                    for (pyr, ptr), clist in plan.items()
                    if term_index(pyr, ptr) < current_rank
                    for pc in clist
                )
                if prior_cp < min_cp:
                    c_warns.append(f"Requires at least {min_cp} CP completed prior (currently completed: {prior_cp} CP)")
                else:
                    c_sats.append(f"Credit point requirement satisfied: {prior_cp}/{min_cp} CP completed prior")

            # 4. Course Prerequisites Check (AND/OR groups)
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
                    sat_desc = ", ".join([f"{sc[0]} (completed Y{sc[1]} T{sc[2]})" for sc in satisfied_courses[:count_needed]])
                    c_sats.append(f"Prerequisite satisfied: {sat_desc}")
                elif same_or_later_courses:
                    sample = same_or_later_courses[0]
                    if len(g_courses) == 1:
                        c_warns.append(f"Prereq {sample[0]} must be completed before Y{yr} T{tr} (currently scheduled in Y{sample[1]} T{sample[2]})")
                    else:
                        c_warns.append(f"Prereq ({' OR '.join(g_courses)}) must be completed before Y{yr} T{tr}")
                else:
                    if len(g_courses) == 1:
                        c_warns.append(f"Missing Prerequisite: {g_courses[0]}")
                    else:
                        c_warns.append(f"Missing Prerequisite: Complete at least {count_needed} of ({' OR '.join(g_courses)})")

            # 5. Corequisites Check
            for cr in coreqs:
                if cr not in placed_coords:
                    c_warns.append(f"Missing Corequisite: {cr}")
                else:
                    cr_yr, cr_tr = placed_coords[cr]
                    if term_index(cr_yr, cr_tr) <= current_rank:
                        c_sats.append(f"Corequisite satisfied: {cr} (enrolled Y{cr_yr} T{cr_tr})")
                    else:
                        c_warns.append(f"Coreq {cr} scheduled after Y{yr} T{tr}")

            # 6. Bidirectional Incompatibility Check
            incomp_issues = check_course_incompatibilities(info, all_planned_or_held, catalog_dict)
            for iss in incomp_issues:
                c_warns.append(iss)

            if c_warns:
                warnings[c] = c_warns
                print(f"[VALIDATE PLAN] ⚠️ {c} in Y{yr} T{tr} -> Warnings: {c_warns}", flush=True)
            if c_sats:
                satisfied[c] = c_sats

    return warnings, satisfied

def check_course_incompatibilities(c_info: dict, all_planned_or_held: set, catalog_dict: dict) -> list:
    """
    Bidirectional incompatibility check:
    1. Does c_info list any scheduled/held course as incompatible (e.g. 2003MSC)?
    2. Does any scheduled/held course list c_info as incompatible?
    """
    code = c_info.get("code")
    incomp_issues = []

    # Forward check
    for inc in c_info.get("incompatibles", []):
        if inc in all_planned_or_held and inc != code:
            incomp_issues.append(f"Incompatible with {inc}")

    # Reverse check
    for planned_c in all_planned_or_held:
        if planned_c == code:
            continue
        p_info = catalog_dict.get(planned_c) or {}
        if code in p_info.get("incompatibles", []):
            msg = f"Incompatible with {planned_c}"
            if msg not in incomp_issues:
                incomp_issues.append(msg)

    return incomp_issues


def is_course_degree_compatible(c_info: dict, sel_deg_code: str, all_planned_or_held: set, catalog_dict: dict) -> tuple[bool, str]:
    """Fully generalized check: degree program restrictions and bidirectional anti-requisites."""
    code = c_info.get("code", "")

    # 1. Program restriction check (e.g. 1000DOH restricted to 1613)
    prog_restr = [str(x).strip() for x in c_info.get("program_restrictions", []) if str(x).strip()]
    if prog_restr and sel_deg_code:
        deg_clean = str(sel_deg_code).strip()
        if deg_clean not in prog_restr:
            return False, f"Restricted: Only open to students in program(s): {', '.join(prog_restr)}"

    # 2. Incompatibility / Anti-requisite check (e.g. 2003MSC)
    incomp_issues = check_course_incompatibilities(c_info, all_planned_or_held, catalog_dict)
    if incomp_issues:
        return False, f"🚫 {incomp_issues[0]} (already in your plan/holding zone)"

    return True, ""

def evaluate_elective_prereqs(c_info: dict, plan: dict, planned_coords: dict, selected_degree_code: str = None) -> tuple[bool, tuple | None, str, list]:
    code = c_info.get("code")
    all_planned_or_held = set(planned_coords.keys()) | set(st.session_state.get("holding_zone", []))

    # 1. Generalized compatibility & anti-requisite check
    is_compat, compat_msg = is_course_degree_compatible(c_info, selected_degree_code, all_planned_or_held, catalog)
    if not is_compat:
        return False, None, compat_msg, []

    # 2. Mandatory Co-requisites Check
    coreqs = c_info.get("coreqs", [])
    missing_coreqs = [cr for cr in coreqs if cr not in planned_coords]
    if missing_coreqs:
        return False, None, f"⚠️ Requires co-enrolment in: {', '.join(missing_coreqs)}", []

    # 3. Calculate cumulative CP progression by term
    sorted_terms = sorted(plan.keys(), key=lambda t: term_index(t[0], t[1]))
    cum_cp_before_term = {}
    running_cp = 0
    for t in sorted_terms:
        cum_cp_before_term[t] = running_cp
        term_courses = plan[t]
        running_cp += sum(int((catalog.get(tc) or {}).get("credit_points", 10) or 10) for tc in term_courses)

    # 4. Minimum CP Prerequisite Check
    min_cp = c_info.get("min_cp_prereq", 0)
    latest_term_cp = 0
    cp_sat_msg = ""
    if min_cp > 0:
        eligible_term_for_cp = None
        for t in sorted_terms:
            if cum_cp_before_term[t] >= min_cp:
                eligible_term_for_cp = t
                break
        if not eligible_term_for_cp:
            return False, None, f"Requires at least {min_cp} CP completed prior (your plan only reaches {running_cp} CP)", []
        latest_term_cp = term_index(eligible_term_for_cp[0], eligible_term_for_cp[1]) - 1
        cp_sat_msg = f"{min_cp} CP completed"

    # 5. Course Prerequisites Check (AND/OR Groups)
    p_groups = c_info.get("prereq_groups", [])
    latest_term_courses = 0
    missing_groups = []
    sat_details = []

    for g in p_groups:
        needed = g.get("count", 1)
        g_courses = g.get("courses", [])
        sat_in_g = []

        for p in g_courses:
            if p in planned_coords:
                pyr, ptr = planned_coords[p]
                sat_in_g.append((p, pyr, ptr))

        if len(sat_in_g) < needed:
            missing_groups.append(g)
        else:
            for sc in sat_in_g[:needed]:
                latest_term_courses = max(latest_term_courses, term_index(sc[1], sc[2]))
                sat_details.append(f"{sc[0]} (Y{sc[1]} T{sc[2]})")

    if missing_groups:
        missing_str = format_prereq_display(missing_groups)
        return False, None, f"Prerequisites needed: {missing_str}", missing_groups

    overall_latest_rank = max(latest_term_courses, latest_term_cp)
    ready_yr, ready_tr = term_from_index(overall_latest_rank + 1) if overall_latest_rank > 0 else (1, 1)

    all_sat_reasons = []
    if cp_sat_msg:
        all_sat_reasons.append(cp_sat_msg)
    if sat_details:
        all_sat_reasons.append(", ".join(sat_details))

    if all_sat_reasons:
        reasons_str = " & ".join(all_sat_reasons)
        return True, (ready_yr, ready_tr), f"Prerequisites met via {reasons_str} — Eligible from Year {ready_yr} Trimester {ready_tr}", []

    return True, (1, 1), "No prerequisites required — Eligible from Year 1 Trimester 1", []

plan_warnings, plan_satisfied = validate_plan(st.session_state.plan, catalog)

# -----------------------------------------------------------------------------
# 8. STREAMLIT-JS ACTION BRIDGE
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
# 9. SIDEBAR: DEGREE SELECTION, COURSE SEARCH & STRUCTURE
# -----------------------------------------------------------------------------
with st.sidebar:
    if st.session_state.get("selected_degree") is None or st.session_state.get("degree_edit_mode", False):
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

                available_intakes = chosen_degree.get("intakes") or ["Trimester 1", "Trimester 2"]
                order_map = {"trimester 1": 1, "t1": 1, "trimester 2": 2, "t2": 2, "trimester 3": 3, "t3": 3}
                sorted_intakes = sorted(available_intakes, key=lambda x: order_map.get(str(x).lower().strip(), 99))
                intake_choice = st.selectbox("Starting Trimester", options=sorted_intakes, key="deg_start_intake")

                mode_choice = st.selectbox("Study Load", options=["Full-time", "Part-time"], key="deg_study_mode")

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
                            core_courses, prescribed_plan, holding_alts, or_map, flex_courses, has_flex, plan_meta = parse_degree_rules(
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

                            st.session_state.num_years_slider = min(10, max(1, plan_meta["duration_years"]))
                            st.session_state.include_t3_cb = plan_meta["include_t3"]
                            st.session_state.term_target_cp = plan_meta["target_cp_map"]
                            st.session_state.active_terms_per_year = plan_meta["active_terms_per_year"]
                            st.session_state.course_or_map = or_map
                            st.session_state.total_degree_cp = plan_meta["total_degree_cp"]
                            st.session_state.degree_core_courses = core_courses
                            st.session_state.degree_flex_courses = flex_courses
                            st.session_state.has_flexible_module = has_flex

                            st.session_state.plan = prescribed_plan
                            st.session_state.holding_zone = holding_alts

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
                    st.session_state.degree_core_courses = []
                    st.session_state.degree_flex_courses = []
                    st.session_state.has_flexible_module = False
                    st.session_state.plan = {}
                    st.session_state.holding_zone = []
                    st.session_state.feedback_message = ("warning", "Degree program removed.")
                    st.rerun()

    st.divider()

    # 1. ADD A COURSE
    st.header("1. Add a Course")
    current_yr = datetime.now().year
    with st.form("course_search_form", clear_on_submit=True):
        course_code_input = st.text_input("Course Code", placeholder="eg. 1001MSC", key="input_course_code")
        planned_year = st.selectbox("Planned Year", options=list(range(current_yr, 2031)), index=0, key="planned_course_year")
        submit_btn = st.form_submit_button("Add Course", type="primary")

    if submit_btn:
        st.session_state.feedback_message = None
        if not course_code_input:
            st.session_state.feedback_message = ("warning", "Please enter a course code.")
        else:
            clean_code = course_code_input.replace(" ", "").upper().strip()
            c_info = lookup_course(clean_code, planned_year)

            if c_info:
                # 1. Program & Incompatibility Validation
                sel_deg = st.session_state.get("selected_degree")
                sel_deg_code = str(sel_deg.get("code", "")).strip() if sel_deg else None
                all_planned_or_held = set(c for clist in st.session_state.plan.values() for c in clist) | set(st.session_state.holding_zone)

                is_compat, compat_msg = is_course_degree_compatible(c_info, sel_deg_code, all_planned_or_held, catalog)

                if not is_compat:
                    st.session_state.feedback_message = (
                        "error",
                        f"❌ Cannot add **{clean_code}** ({c_info['title']}): {compat_msg}."
                    )
                else:
                    already_in_holding = clean_code in st.session_state.holding_zone
                    already_in_plan = any(clean_code in clist for clist in st.session_state.plan.values())

                    if already_in_holding or already_in_plan:
                        st.session_state.feedback_message = ("warning", f"**{clean_code}** is already in your holding zone or plan.")
                    else:
                        st.session_state.holding_zone.append(clean_code)
                        pr_display = c_info.get("prereq_display", "No Prereqs")
                        st.session_state.feedback_message = ("success", f"Added **{clean_code}** - {c_info['title']} to Holding Zone! (Requisites: {pr_display})")
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

    # 2. DEGREE STRUCTURE & CORE SCHEDULE
    st.header("2. Degree Structure")
    num_years = st.slider("Degree Duration (Years)", min_value=1, max_value=10, key="num_years_slider")
    include_t3 = st.checkbox("Include Trimester 3 (Summer)", key="include_t3_cb")

    st.divider()
    total_planned = sum(len(c) for c in st.session_state.plan.values())
    total_cp = sum(
        int((catalog.get(c) or lookup_course(c) or {}).get("credit_points", 10) or 10)
        for clist in st.session_state.plan.values() for c in clist
    )
    total_deg_cp = st.session_state.get("total_degree_cp", num_years * 80)

    st.metric("Total Courses Planned", f"{total_planned}")
    st.metric("Total Credit Points", f"{total_cp} / {total_deg_cp} CP")

    core_list = st.session_state.get("degree_core_courses", [])
    if core_list:
        with st.expander("📚 Core Courses & Offerings", expanded=False):
            for c_obj in core_list:
                c_code = c_obj["code"]
                info = catalog.get(c_code) or lookup_course(c_code) or {}
                offs = format_offerings_label(info.get("offerings", []))
                st.markdown(f"**{c_code}** — {info.get('title', c_obj.get('name', ''))} (`{offs}`)")

    st.divider()

    with st.expander("⚡ Bulk Plan Controls", expanded=False):
        c_clear_all, c_hold_all = st.columns(2)
        with c_clear_all:
            if st.button("🗑️ Delete All", use_container_width=True):
                st.session_state.plan = {}
                st.session_state.selected_course = None
                st.rerun()
        with c_hold_all:
            if st.button("📥 Hold All", use_container_width=True):
                for clist in st.session_state.plan.values():
                    for c in clist:
                        if c not in st.session_state.holding_zone:
                            st.session_state.holding_zone.append(c)
                st.session_state.plan = {}
                st.session_state.selected_course = None
                st.rerun()

        st.caption("Targeted Year / Trimester Actions:")
        sel_yr = st.selectbox("Select Year", options=list(range(1, num_years + 1)), key="bulk_sel_yr")
        col_yr_del, col_yr_hold = st.columns(2)
        with col_yr_del:
            if st.button(f"Delete Year {sel_yr}", use_container_width=True):
                for tr in [1, 2, 3]:
                    st.session_state.plan[(sel_yr, tr)] = []
                st.rerun()
        with col_yr_hold:
            if st.button(f"Hold Year {sel_yr}", use_container_width=True):
                for tr in [1, 2, 3]:
                    for c in st.session_state.plan.get((sel_yr, tr), []):
                        if c not in st.session_state.holding_zone:
                            st.session_state.holding_zone.append(c)
                    st.session_state.plan[(sel_yr, tr)] = []
                st.rerun()

        sel_tr = st.selectbox("Select Trimester", options=[1, 2, 3], key="bulk_sel_tr")
        col_tr_del, col_tr_hold = st.columns(2)
        with col_tr_del:
            if st.button(f"Delete Y{sel_yr} T{sel_tr}", use_container_width=True):
                st.session_state.plan[(sel_yr, sel_tr)] = []
                st.rerun()
        with col_tr_hold:
            if st.button(f"Hold Y{sel_yr} T{sel_tr}", use_container_width=True):
                for c in st.session_state.plan.get((sel_yr, sel_tr), []):
                    if c not in st.session_state.holding_zone:
                        st.session_state.holding_zone.append(c)
                st.session_state.plan[(sel_yr, sel_tr)] = []
                st.rerun()

# -----------------------------------------------------------------------------
# 10. HTML, CSS & JS COMPONENT BUILDER
# -----------------------------------------------------------------------------
def string_to_pastel_hex(code_string: str) -> str:
    clean_code = str(code_string).strip().upper()
    hash_digest = hashlib.md5(clean_code.encode()).hexdigest()
    hash_int = int(hash_digest[:8], 16)
    hue = (hash_int % 360) / 360.0
    saturation = 0.65
    lightness = 0.55
    rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
    return '#%02x%02x%02x' % tuple(int(x * 255) for x in rgb)

def build_planner_html(holding_zone, plan, catalog_dict, num_years, include_t3, selected_code, warnings_dict, target_cp_map, study_mode, course_or_map, active_terms_map, core_set=None):
    if core_set is None:
        core_set = set()

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

    * { box-sizing: border-box; }

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
        display: flex;
        align-items: center;
    }

    .core-tag {
        background: rgba(255, 215, 0, 0.2);
        color: #ffd700;
        border: 1px solid #ffd700;
        font-size: 8.5px;
        font-weight: 800;
        padding: 1px 4px;
        border-radius: 3px;
        margin-left: 6px;
        vertical-align: middle;
        letter-spacing: 0.5px;
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

    .holding-grid::-webkit-scrollbar { width: 7px; }
    .holding-grid::-webkit-scrollbar-track { background: rgba(0, 0, 0, 0.2); border-radius: 4px; }
    .holding-grid::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.25); border-radius: 4px; }

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

    .trim-col:last-child { border-right: none; }

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

    # Inside build_planner_html -> Holding Zone Cards loop:
    for code in holding_zone:
        info = lookup_course(code) or catalog_dict.get(code) or {"title": code, "credit_points": "10", "offerings": [], "prereq_display": "No Prereqs", "group": ""}
        bg = string_to_pastel_hex(code)
        is_sel = "is-selected" if code == selected_code else ""

        pr_display = info.get('prereq_display', 'No Prereqs')
        pr_text = f"Pre: {pr_display}"
        cr_text = f" | Co: {', '.join(info['coreqs'])}" if info.get("coreqs") else ""
        offs = format_offerings_label(info.get("offerings", []))

        is_core = code in core_set
        core_badge = '<span class="core-tag">CORE</span>' if is_core else ''

        or_badge = ""
        if code in course_or_map and course_or_map[code]:
            partner_str = ", ".join(course_or_map[code])
            or_badge = f'<span class="badge-pill or-pill" title="Core choice: OR with {partner_str}">⚡ OR with {partner_str}</span>'

        html += f"""
        <div class="course-card {is_sel}" style="background-color: {bg};" onclick="onCourseClick('{code}')">
            <div class="card-top">
                <span class="card-code">{code}{core_badge}</span>
                <span class="btn-close" onclick="onRemoveHolding(event, '{code}')" title="Remove Course">&times;</span>
            </div>
            <div class="card-title" title="{info['title']}">{info['title']}</div>
            <div class="badges-row">
                <span class="badge-pill">{info.get('credit_points', '10')} CP</span>
                <span class="badge-pill">{offs}</span>
                {or_badge}
            </div>
            <div style="font-size: 9.5px; opacity: 0.95; margin-top: 5px; word-break: break-word;">{pr_text}{cr_text}</div>
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
                is_core = c in core_set
                core_badge = '<span class="core-tag">CORE</span>' if is_core else ''

                or_badge_matrix = ""
                if c in course_or_map and course_or_map[c]:
                    partner_str = ", ".join(course_or_map[c])
                    or_badge_matrix = f'<span class="badge-pill or-pill" title="Core choice: OR with {partner_str}">⚡ OR with {partner_str}</span>'

                html += f"""
                <div class="course-card {is_sel} {prereq_glow_class}" style="background-color: {bg};" onclick="onCourseClick('{c}')">
                    <div class="card-top">
                        <span class="card-code">{c}{core_badge}</span>
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

    function onCourseClick(code) { triggerBridgeAction("SELECT___TOKEN___" + code); }
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
# 11. MAIN VIEW
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

# Course Requisites Expander
if plan_warnings or plan_satisfied:
    with st.expander(f"📋 Course Requisites & Status ({len(plan_warnings)} warnings, {len(plan_satisfied)} satisfied)", expanded=False):
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

# -----------------------------------------------------------------------------
# 12. ADVANCED ELECTIVE & UNIVERSAL COURSE EXPLORER (FULL CATALOG ~3,000 COURSES)
# -----------------------------------------------------------------------------
if st.session_state.get("selected_degree"):
    with st.expander("💡 Elective & University Course Explorer (Full Catalog)", expanded=False):
        if "sug_page" not in st.session_state:
            st.session_state.sug_page = 1

        deg_flex_set = set(st.session_state.get("degree_flex_courses", []))
        core_set = {c["code"] for c in st.session_state.get("degree_core_courses", [])}
        planned_coords = {c: (yr, tr) for (yr, tr), clist in st.session_state.plan.items() for c in clist}
        planned_or_held = set(planned_coords.keys()) | set(st.session_state.holding_zone)
        sel_deg_code = st.session_state.selected_degree.get("code")

        candidates = []
        seen_cand = set()

        # 1. Degree Recommended Flexible Courses (Placed First)
        for f_code in st.session_state.get("degree_flex_courses", []):
            if f_code not in core_set and f_code not in planned_or_held and f_code not in seen_cand:
                info = lookup_course(f_code) or catalog.get(f_code) or {}
                if info and info.get("code"):
                    c_copy = dict(info)
                    c_copy["is_degree_recommended"] = True
                    candidates.append(c_copy)
                    seen_cand.add(f_code)

        # 2. Universal Course Catalog across all faculties
        for c_code, c_info in catalog.items():
            if c_code not in core_set and c_code not in planned_or_held and c_code not in seen_cand:
                career = str(c_info.get("career", "")).lower()
                if "postgrad" not in career and "research" not in career:
                    c_copy = dict(c_info)
                    c_copy["is_degree_recommended"] = (c_code in deg_flex_set)
                    candidates.append(c_copy)
                    seen_cand.add(c_code)

        # Evaluate Whole-Degree Prerequisite Satisfaction & Compatibility
        candidate_evaluations = []
        for c in candidates:
            code = c["code"]
            is_compat, compat_msg = is_course_degree_compatible(c, sel_deg_code, planned_coords)
            is_elig, early_term, expl_msg, missing = evaluate_elective_prereqs(c, st.session_state.plan, planned_coords, sel_deg_code)
            lvl_lbl = get_course_level_label(code)
            subj_area = c.get("subject_area") or get_course_subject_area(code)
            rank_score = term_index(early_term[0], early_term[1]) if early_term else 9999

            is_rec = (code in deg_flex_set) or c.get("is_degree_recommended", False)

            candidate_evaluations.append({
                "course": c,
                "is_eligible": is_elig,
                "is_degree_compat": is_compat,
                "is_degree_recommended": is_rec,
                "earliest_term": early_term,
                "earliest_term_rank": rank_score,
                "explanation": expl_msg,
                "missing": missing,
                "level": lvl_lbl,
                "subject_area": subj_area
            })

        # --- MULTISELECT CONTROLS & FILTER BAR ---
        col_f1, col_f2, col_f3 = st.columns([1.8, 1.3, 1.4])
        with col_f1:
            all_groups = sorted(list({c.get("group", "Other") for c in candidates if c.get("group")}))
            sel_groups = st.multiselect(
                "Discipline / Academic Group",
                options=all_groups,
                placeholder="All disciplines (or select multiple...)",
                key="sug_filter_grps"
            )
        with col_f2:
            level_options = ["Level 1 (1xxx)", "Level 2 (2xxx)", "Level 3 (3xxx)", "Level 4 (4xxx)", "Level 5+ (5xxx+)"]
            sel_levels = st.multiselect(
                "Course Level",
                options=level_options,
                placeholder="All levels (or select multiple...)",
                key="sug_filter_lvls"
            )
        with col_f3:
            all_areas = sorted(list({ce["subject_area"] for ce in candidate_evaluations if ce["subject_area"]}))
            sel_areas = st.multiselect(
                "Area of Study (Subject Code)",
                options=all_areas,
                placeholder="e.g. MSC, ESC, NSC, ENG...",
                key="sug_filter_areas"
            )

        col_search, col_tgl, col_pp = st.columns([2.2, 1.8, 0.8])
        with col_search:
            sug_keyword = st.text_input("Search Keyword or Code", placeholder="e.g. data, biostatistics, 2022...", key="sug_filter_kw")
        with col_tgl:
            only_prereqs_met = st.checkbox(
                "Only show courses with prerequisites satisfied in plan",
                value=True,
                key="sug_filter_prereq_met",
                help="Filters to courses that are compatible with your degree and have all prerequisites satisfied in your current plan."
            )
        with col_pp:
            per_page = st.selectbox("Per Page", options=[10, 25, 50], index=0, key="sug_per_page")

        # Apply Filters
        filtered_sug = []
        kw = sug_keyword.strip().lower()

        for item in candidate_evaluations:
            c = item["course"]
            code = c["code"]
            grp = c.get("group", "Other")
            lvl = item["level"]
            area = item["subject_area"]
            is_eligible = item["is_eligible"]
            is_compat = item["is_degree_compat"]

            # If checked, DO NOT SHOW incompatible degree courses or unsatisfied prereqs
            if only_prereqs_met:
                if not is_compat or not is_eligible:
                    continue

            if sel_groups and grp not in sel_groups:
                continue
            if sel_levels and lvl not in sel_levels:
                continue
            if sel_areas and area not in sel_areas:
                continue
            if kw:
                searchable = f"{code} {c.get('title', '')} {c.get('description', '')}".lower()
                if kw not in searchable:
                    continue

            filtered_sug.append(item)

        # Sort: Recommended electives ALWAYS first, then eligible courses, then by earliest availability
        filtered_sug.sort(key=lambda x: (
            not x["is_degree_recommended"],
            not x["is_eligible"],
            x["earliest_term_rank"],
            x["course"]["code"]
        ))

        total_results = len(filtered_sug)

        if total_results == 0:
            st.info("No courses match your active filter criteria and prerequisite settings.")
        else:
            total_pages = max(1, (total_results + per_page - 1) // per_page)
            st.session_state.sug_page = min(max(1, st.session_state.sug_page), total_pages)
            curr_page = st.session_state.sug_page

            start_idx = (curr_page - 1) * per_page
            end_idx = min(start_idx + per_page, total_results)
            page_items = filtered_sug[start_idx:end_idx]

            col_count, col_nav = st.columns([3, 2])
            with col_count:
                st.markdown(f"**Showing {start_idx + 1}–{end_idx} of {total_results:,} available courses**")
            with col_nav:
                c_prev, c_txt, c_next = st.columns([1, 1.8, 1])
                with c_prev:
                    if st.button("⬅️ Prev", disabled=(curr_page <= 1), use_container_width=True, key="sug_prev_btn"):
                        st.session_state.sug_page -= 1
                        st.rerun()
                with c_txt:
                    st.markdown(f"<div style='text-align:center; padding-top:4px; font-weight:600; font-size:12px;'>Page {curr_page} of {total_pages}</div>", unsafe_allow_html=True)
                with c_next:
                    if st.button("Next ➡️", disabled=(curr_page >= total_pages), use_container_width=True, key="sug_next_btn"):
                        st.session_state.sug_page += 1
                        st.rerun()

            # --- CSS INJECTION FOR MODERN COURSE ROWS & BADGES ---
            st.markdown(
                """
                <style>
                .sug-card {
                    background: rgba(255, 255, 255, 0.02);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 8px;
                    padding: 12px 16px;
                    margin-bottom: 9px;
                    transition: border-color 0.2s ease, background 0.2s ease;
                }
                .sug-card:hover {
                    border-color: rgba(112, 161, 255, 0.6);
                    background: rgba(255, 255, 255, 0.05);
                }
                .tag-pill {
                    display: inline-block;
                    padding: 2px 7px;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: 700;
                    margin-right: 5px;
                }
                .tag-area { background: rgba(112, 161, 255, 0.18); color: #70a1ff; border: 1px solid rgba(112, 161, 255, 0.35); }
                .tag-level { background: rgba(165, 94, 234, 0.18); color: #a55eea; border: 1px solid rgba(165, 94, 234, 0.35); }
                .tag-off { background: rgba(255, 165, 2, 0.18); color: #ffa502; border: 1px solid rgba(255, 165, 2, 0.35); }
                .tag-cp { background: rgba(255, 255, 255, 0.1); color: #f1f2f6; }
                .tag-rec { 
                    background: rgba(255, 215, 0, 0.25) !important; 
                    color: #ffd700 !important; 
                    border: 1px solid #ffd700 !important;
                    font-weight: 800 !important;
                    letter-spacing: 0.5px !important;
                }
                .status-ready { color: #2ed573; font-weight: 600; font-size: 11px; }
                .status-pending { color: #ff9f1a; font-weight: 600; font-size: 11px; }
                </style>
                """,
                unsafe_allow_html=True
            )

            for item in page_items:
                c_code = item["course"]["code"]
                was_rec = item["is_degree_recommended"]

                # Enrich with Curriculum API data if not already fetched
                if not item["course"].get("from_curriculum_api"):
                    enriched = lookup_course(c_code)
                    if enriched:
                        enriched["is_degree_recommended"] = was_rec
                        item["course"] = enriched
                        is_elig, early_term, expl_msg, missing = evaluate_elective_prereqs(
                            enriched, st.session_state.plan, planned_coords, sel_deg_code
                        )
                        item["is_eligible"] = is_elig
                        item["explanation"] = expl_msg

                c_info = item["course"]
                title = c_info["title"]
                cp = c_info.get("credit_points", "10")
                offs = format_offerings_label(c_info.get("offerings", []))
                area_tag = item["subject_area"]
                lvl_tag = item["level"].split(" ")[0] + " " + item["level"].split(" ")[1]
                expl = item["explanation"]

                status_class = "status-ready" if item["is_eligible"] else "status-pending"
                rec_badge = '<span class="tag-pill tag-rec">⭐ RECOMMENDED ELECTIVE</span>' if item["is_degree_recommended"] else ''

                with st.container():
                    c_main, c_btn = st.columns([5.3, 0.7])
                    with c_main:
                        st.markdown(
                            f"""
                            <div class="sug-card">
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <span style="font-size:13.5px; font-weight:700;">
                                        {c_code} — {title} {rec_badge}
                                    </span>
                                </div>
                                <div style="margin-top:6px; margin-bottom:4px;">
                                    <span class="tag-pill tag-area">{area_tag}</span>
                                    <span class="tag-pill tag-level">{lvl_tag}</span>
                                    <span class="tag-pill tag-cp">{cp} CP</span>
                                    <span class="tag-pill tag-off">Offerings: {offs}</span>
                                    <span class="tag-pill" style="background:rgba(255,255,255,0.06); color:#a4b0be;">{c_info.get('group', 'General')}</span>
                                </div>
                                <div class="{status_class}">
                                    {expl}
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with c_btn:
                        st.write("")
                        btn_disabled = not item["is_eligible"]
                        if st.button("➕ Add", key=f"add_sug_{c_code}", disabled=btn_disabled, use_container_width=True, help=f"Add {c_code} to Course Holding Zone"):
                            if c_code not in st.session_state.holding_zone:
                                st.session_state.holding_zone.append(c_code)
                            st.rerun()

# -----------------------------------------------------------------------------
# 13. PLANNER HTML RENDER
# -----------------------------------------------------------------------------
holding_count = len(st.session_state.holding_zone)
holding_rendered_height = 80 if holding_count == 0 else min(310, 60 + ((holding_count + 2) // 3) * 115)

max_in_any_trim = max([len(v) for v in st.session_state.plan.values()] + [1])
courses_render_factor = max_in_any_trim if max_in_any_trim >= 4 else 4
year_block_height = 65 + (courses_render_factor * 85)
calc_height = holding_rendered_height + (num_years * year_block_height) + 240

core_set = {c["code"] for c in st.session_state.get("degree_core_courses", [])}

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
    active_terms_map=st.session_state.active_terms_per_year,
    core_set=core_set
)

components.html(planner_html, height=calc_height, scrolling=True)
