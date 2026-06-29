# guidelines_db.py — OTT Guidelines Search Engine
#
# Matches the exact data shape from the company's own mockup
# (June_26_2026_OTT_Guidelines_SearchEngine.pptx, slide 2):
#   Client | OTT Platform | S.No. | Spec | Category | Guideline | Keywords
#
# Plus a Year column — the company's stated reason for wanting this tool at
# all is that guidelines change rapidly and get hard to track over time, so
# every entry is versioned by the year it was captured/updated, and the
# search UI can filter by year the same way it filters by platform/category.
#
# This is a separate table from `platforms` (database.py) on purpose:
# `platforms` stores numeric cleaning-rule VALUES the AI cleaner consumes
# (max_chars_per_line, reading_speed_cps, etc). This table stores free-text
# SPEC ENTRIES — the actual guideline wording, for humans to search and read,
# not for the cleaner to parse. Different shape, different purpose.

import json
from database import get_connection


def _ensure_version_columns(cursor, conn):
    """
    For a guidelines table created by an earlier version of this file
    (before version history existed) — add the new columns without losing
    any existing data. MySQL doesn't support "ADD COLUMN IF NOT EXISTS"
    directly in all versions, so we check information_schema first.
    """
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'guidelines'
    """)
    existing_cols = {row[0] for row in cursor.fetchall()}

    migrations = [
        ("version_no", "ALTER TABLE guidelines ADD COLUMN version_no INT NOT NULL DEFAULT 1"),
        ("is_current", "ALTER TABLE guidelines ADD COLUMN is_current BOOLEAN NOT NULL DEFAULT TRUE"),
        ("supersedes_id", "ALTER TABLE guidelines ADD COLUMN supersedes_id INT DEFAULT NULL"),
        ("superseded_at", "ALTER TABLE guidelines ADD COLUMN superseded_at TIMESTAMP NULL DEFAULT NULL"),
    ]
    for col_name, alter_sql in migrations:
        if col_name not in existing_cols:
            try:
                cursor.execute(alter_sql)
                conn.commit()
                print(f"[guidelines_db] Migrated existing table: added column '{col_name}'")
            except Exception as e:
                print(f"[guidelines_db] Migration warning for '{col_name}': {e}")


def init_guidelines_table():
    """Create the guidelines table and seed it from the company's own sample data."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guidelines (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client VARCHAR(200) NOT NULL,
            ott_platform VARCHAR(200) NOT NULL,
            spec_no VARCHAR(50),
            spec VARCHAR(500) NOT NULL,
            category VARCHAR(200) NOT NULL,
            guideline TEXT NOT NULL,
            keywords TEXT,
            year INT NOT NULL,
            sub_specific TEXT,
            dhoh_specific TEXT,
            -- Version history: editing a guideline never deletes the old
            -- version. Instead a new row is inserted, linked back to the
            -- row it replaces via supersedes_id, and is_current marks which
            -- one is "the current rule" for searches. Old projects that
            -- were built under an earlier version of the guideline can
            -- still look it up by selecting it directly, even after a
            -- newer version exists — this is the actual requirement: OTT
            -- guidelines change often, and old projects need the rules
            -- that were in force when THEY were built, not just whatever
            -- is current today.
            version_no INT NOT NULL DEFAULT 1,
            is_current BOOLEAN NOT NULL DEFAULT TRUE,
            supersedes_id INT DEFAULT NULL,
            superseded_at TIMESTAMP NULL DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_client (client),
            INDEX idx_platform (ott_platform),
            INDEX idx_category (category),
            INDEX idx_year (year),
            INDEX idx_is_current (is_current),
            INDEX idx_supersedes (supersedes_id)
        )
    """)
    conn.commit()

    # Migration for databases created before version history existed —
    # adds the new columns if they're missing, without losing existing data.
    _ensure_version_columns(cursor, conn)

    # Seed with the real entries from the company's own slide 1/2 mockup,
    # so the tool isn't empty on first run — these are the actual Deluxe >
    # Netflix spec rows shown in the reference deck.
    cursor.execute("SELECT COUNT(*) FROM guidelines")
    count = cursor.fetchone()[0]

    if count == 0:
        seed_rows = [
            (
                "Deluxe", "Netflix", "1.1.1", "Special Instruction: Treatment of word 'black'",
                "General Guidelines",
                "When the word \"black\" appears in reference to someone's race or ethnicity, "
                "capitalize it as Black. Use this form when referring to an African American or "
                "Black person and when referring to collective groups or institutions, e.g. Black "
                "cinema, the Black community, a Black person. Note, however, that Black should "
                "only be used as an adjective (e.g. Black history) and not as a singular or plural "
                "noun (e.g. a Black, Blacks). Please follow this rule in all variants of English "
                "(template or DHOH), including into-English files. Additionally, for SDH, always "
                "follow the word order and choice of the audio.",
                "Black, African, Black Person", 2026, None, "Same as SUB"
            ),
            (
                "Deluxe", "Netflix", "2.1.1", "Duration", "General Guidelines",
                "Minimum duration: 5/6 of a second (this is dependent on the frame rate — at 23 "
                "frames per second, this is 20 frames). Maximum duration: 6 seconds 23 frames per "
                "subtitle event (regardless of frame rate).",
                "Minimum Duration, Maximum Duration, Frames per subtitle", 2026, None, None
            ),
            (
                "Deluxe", "Netflix", "3.1.1", "Frame Gap", "General Guidelines",
                "2 frames minimum (regardless of frame rate).",
                "Frame Gap, Minimum Gap", 2026, None, None
            ),
            (
                "Deluxe", "Netflix", "4.1.1", "Maximum lines per box", "General Guidelines",
                "2 lines maximum for SUB and SDH. 3 lines maximum for CC.",
                "Maximum lines, Line limit", 2026, "2 (SUB, SDH)", "3 (CC)"
            ),
            (
                "Deluxe", "Netflix", "3.1.1", "Positioning and Alignment", "General Guidelines",
                "Subtitles should be center justified and placed at either the top center (Ctrl+8) "
                "or bottom center (Ctrl+2) of the screen. Ensure subtitles are positioned "
                "accordingly to avoid overlap with onscreen text. In cases where overlap is "
                "impossible to avoid (text at the top and bottom of screen), the subtitle should "
                "be placed where easier to read.",
                "Subtitle Alignment, Positioning", 2026,
                "Positioning is typically handled by the Positioning Team.",
                "Same as SUB. CC files: Center Pop-On. Positioning for manual placement: to avoid "
                "covering the character's mouth (speaking or not) with dialogue, adjust any "
                "dialogue text that touches the chin by dividing the box (3 to 2 lines or 2 to 1 "
                "line)."
            ),
        ]
        cursor.executemany("""
            INSERT INTO guidelines
            (client, ott_platform, spec_no, spec, category, guideline, keywords, year, sub_specific, dhoh_specific)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, seed_rows)
        conn.commit()

    cursor.close()
    conn.close()


def search_guidelines(
    keyword: str = "",
    client: str = "",
    ott_platform: str = "",
    category: str = "",
    year: int = None,
    include_all_versions: bool = False,
) -> list:
    """
    Free-text keyword search across spec/guideline/keywords, combined with
    exact-match dropdown filters — matches the mockup's "type a keyword,
    pick Deluxe/Netflix/CC from dropdowns, see matching rows" behaviour.
    Any filter left blank/None is simply not applied.

    By default, only returns the CURRENT version of each guideline — so
    day-to-day searches aren't cluttered with old superseded rows.

    Set include_all_versions=True, OR filter by a specific `year`, to see
    every version that existed — this is the actual "old project" use case:
    someone working on a project built under a 2023 guideline needs to find
    the 2023 version specifically, even though a newer 2026 version is now
    "current". Filtering by year automatically implies wanting that year's
    historical version, not just whatever is current today.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    clauses = []
    params = []

    if keyword.strip():
        clauses.append("(spec LIKE %s OR guideline LIKE %s OR keywords LIKE %s OR category LIKE %s)")
        like = f"%{keyword.strip()}%"
        params.extend([like, like, like, like])

    if client.strip():
        clauses.append("client = %s")
        params.append(client.strip())

    if ott_platform.strip():
        clauses.append("ott_platform = %s")
        params.append(ott_platform.strip())

    if category.strip():
        clauses.append("category = %s")
        params.append(category.strip())

    if year is not None:
        clauses.append("year = %s")
        params.append(year)
    elif not include_all_versions:
        # No specific year requested and history wasn't explicitly asked
        # for — show only the current version of each guideline.
        clauses.append("is_current = TRUE")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM guidelines {where} ORDER BY client, ott_platform, spec_no, version_no DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_filter_options() -> dict:
    """
    Returns the distinct values for every filter dropdown — clients, OTT
    platforms, categories, years — so the frontend can populate the dropdown
    lists from real data instead of a hardcoded guess, and the list grows
    automatically as new guidelines get added.
    """
    conn = get_connection()
    cursor = conn.cursor()

    def distinct(col):
        cursor.execute(f"SELECT DISTINCT {col} FROM guidelines WHERE {col} IS NOT NULL ORDER BY {col}")
        return [r[0] for r in cursor.fetchall()]

    result = {
        "clients": distinct("client"),
        "ott_platforms": distinct("ott_platform"),
        "categories": distinct("category"),
        "years": sorted(distinct("year"), reverse=True),
    }
    cursor.close()
    conn.close()
    return result


def add_guideline(entry: dict) -> int:
    """
    Add a brand-new guideline entry (version 1, no prior version) — used by
    the 'Add Guideline' form and the bulk-import endpoint.
    Returns the new row's id.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO guidelines
        (client, ott_platform, spec_no, spec, category, guideline, keywords, year,
         sub_specific, dhoh_specific, version_no, is_current, supersedes_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,TRUE,NULL)
    """, (
        entry.get("client", "").strip(),
        entry.get("ott_platform", "").strip(),
        entry.get("spec_no", "").strip(),
        entry.get("spec", "").strip(),
        entry.get("category", "General Guidelines").strip(),
        entry.get("guideline", "").strip(),
        entry.get("keywords", "").strip(),
        entry.get("year"),
        entry.get("sub_specific", "").strip() or None,
        entry.get("dhoh_specific", "").strip() or None,
    ))
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_guideline(guideline_id: int, entry: dict) -> bool:
    """
    Update a guideline WITHOUT destroying the old version.

    This is the actual requirement: "the previous guidelines for that will
    also be saved so if any old project comes... they can select that
    guidelines." So "editing" here means:
      1. Mark the existing row as no-longer-current (is_current=False,
         superseded_at=now), but leave every field on it untouched.
      2. Insert a brand-new row with the edited values, version_no+1, linked
         back to the row it replaces via supersedes_id, and is_current=True.

    Old projects can still find and select the exact version of the
    guideline that was in force when they were built, by year or by
    explicitly browsing that spec's version history — see
    get_guideline_history() below.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM guidelines WHERE id=%s", (guideline_id,))
    old_row = cursor.fetchone()
    if not old_row:
        cursor.close()
        conn.close()
        return False

    cursor.execute(
        "UPDATE guidelines SET is_current=FALSE, superseded_at=CURRENT_TIMESTAMP WHERE id=%s",
        (guideline_id,)
    )

    cursor.execute("""
        INSERT INTO guidelines
        (client, ott_platform, spec_no, spec, category, guideline, keywords, year,
         sub_specific, dhoh_specific, version_no, is_current, supersedes_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s)
    """, (
        entry.get("client", old_row["client"]).strip(),
        entry.get("ott_platform", old_row["ott_platform"]).strip(),
        entry.get("spec_no", old_row["spec_no"] or "").strip(),
        entry.get("spec", old_row["spec"]).strip(),
        entry.get("category", old_row["category"]).strip(),
        entry.get("guideline", old_row["guideline"]).strip(),
        entry.get("keywords", old_row["keywords"] or "").strip(),
        entry.get("year", old_row["year"]),
        (entry.get("sub_specific", old_row["sub_specific"]) or "").strip() or None,
        (entry.get("dhoh_specific", old_row["dhoh_specific"]) or "").strip() or None,
        old_row["version_no"] + 1,
        guideline_id,
    ))
    conn.commit()
    cursor.close()
    conn.close()
    return True


def get_guideline_history(guideline_id: int) -> list:
    """
    Given ANY version's id for a guideline, walk the supersedes_id chain in
    both directions and return every version, oldest first — so the UI can
    show "this rule has changed 3 times, here's what it said each time"
    and let someone pick an older version for an older project.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM guidelines WHERE id=%s", (guideline_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return []

    # Walk backwards to find the original (version 1) row of this chain.
    current = row
    while current.get("supersedes_id"):
        cursor.execute("SELECT * FROM guidelines WHERE id=%s", (current["supersedes_id"],))
        prev = cursor.fetchone()
        if not prev:
            break
        current = prev
    root_id = current["id"]

    # Walk forwards from the root, following whichever row supersedes it,
    # collecting every version along the way.
    chain = [current]
    cursor.execute("SELECT * FROM guidelines WHERE supersedes_id=%s", (root_id,))
    next_row = cursor.fetchone()
    while next_row:
        chain.append(next_row)
        cursor.execute("SELECT * FROM guidelines WHERE supersedes_id=%s", (next_row["id"],))
        next_row = cursor.fetchone()

    cursor.close()
    conn.close()
    return chain


def delete_guideline(guideline_id: int, hard_delete: bool = False) -> bool:
    """
    By default this is a SOFT delete (is_current=False, data preserved) —
    consistent with "previous guidelines are also saved", a guideline that
    was wrongly marked current should be retractable without erasing the
    historical record a past project might still reference.

    hard_delete=True genuinely removes the row — only for real mistakes
    (e.g. a garbage/test entry that should never have existed at all, not
    a real guideline that simply changed), and should be used sparingly.
    """
    conn = get_connection()
    cursor = conn.cursor()
    if hard_delete:
        cursor.execute("DELETE FROM guidelines WHERE id=%s", (guideline_id,))
    else:
        cursor.execute(
            "UPDATE guidelines SET is_current=FALSE, superseded_at=CURRENT_TIMESTAMP WHERE id=%s",
            (guideline_id,)
        )
    conn.commit()
    affected = cursor.rowcount
    cursor.close()
    conn.close()
    return affected > 0


def extract_guidelines_with_ai(raw_text: str, client: str, ott_platform: str, year: int) -> list:
    """
    Given raw guideline document text (pasted or extracted from an uploaded
    PDF/DOC/XLSX), use the AI to split it into individual structured spec
    rows matching the Client/Platform/Spec/Category/Guideline/Keywords shape.
    This is how a whole new guidelines document gets digitized in one step,
    instead of someone typing each spec row in by hand.
    """
    import os, re, json as _json
    from groq import Groq

    client_api = Groq(api_key=os.getenv("GROQ_API_KEY"))

    prompt = f"""You are digitizing an OTT subtitling guidelines document into structured database rows.

CLIENT: {client}
OTT PLATFORM: {ott_platform}
YEAR: {year}

Read the guidelines text below. Split it into individual spec entries — one entry per distinct rule/topic (e.g. "Duration", "Frame Gap", "Positioning and Alignment", "Treatment of word 'black'", etc). For each entry, extract:
- spec: short title of the rule (e.g. "Duration", "Maximum lines per box")
- category: usually "General Guidelines" unless the document specifies otherwise (e.g. "SUB-specific", "DHOH-specific")
- guideline: the full rule text, verbatim from the document — do not summarize or shorten it
- keywords: 2-5 short comma-free search terms someone would type to find this rule (e.g. "Duration, Minimum Duration, Frames per subtitle")
- sub_specific: any text specifically about SUB/subtitle-only handling, or null if not mentioned separately
- dhoh_specific: any text specifically about DHOH/SDH/CC handling, or null if not mentioned separately

Return ONLY a JSON array, nothing else, no markdown:
[
  {{"spec": "...", "category": "...", "guideline": "...", "keywords": "...", "sub_specific": null, "dhoh_specific": "..."}}
]

GUIDELINES DOCUMENT TEXT:
---
{raw_text[:14000]}
---"""

    response = client_api.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=8000,
    )

    result_text = response.choices[0].message.content.strip()
    result_text = re.sub(r"```json\s*", "", result_text)
    result_text = re.sub(r"```\s*", "", result_text)
    parsed = _json.loads(result_text.strip())

    entries = []
    for i, row in enumerate(parsed, 1):
        entries.append({
            "client": client,
            "ott_platform": ott_platform,
            "spec_no": f"{i}.1.1",
            "spec": row.get("spec", ""),
            "category": row.get("category", "General Guidelines"),
            "guideline": row.get("guideline", ""),
            "keywords": row.get("keywords", ""),
            "year": year,
            "sub_specific": row.get("sub_specific"),
            "dhoh_specific": row.get("dhoh_specific"),
        })
    return entries
