# database.py — MySQL setup for SubtitleAI V2

import mysql.connector
import os
import json
from dotenv import load_dotenv
from platform_rules import PLATFORMS

load_dotenv()


def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 3306)),
        database=os.getenv("DB_NAME", "subtitleai_v2"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def init_db():
    # Create DB if not exists
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    cursor = conn.cursor()
    db_name = os.getenv("DB_NAME", "subtitleai_v2")
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
    conn.commit()
    cursor.close()
    conn.close()

    conn = get_connection()
    cursor = conn.cursor()

    # Platforms table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS platforms (
            id INT AUTO_INCREMENT PRIMARY KEY,
            platform_key VARCHAR(100) UNIQUE NOT NULL,
            platform_family VARCHAR(100) DEFAULT NULL,
            version_label VARCHAR(100) DEFAULT 'Current',
            name VARCHAR(200) NOT NULL,
            max_chars_per_line INT DEFAULT 42,
            max_lines INT DEFAULT 2,
            min_duration_seconds FLOAT DEFAULT 1.0,
            max_duration_seconds FLOAT DEFAULT 7.0,
            min_interval_seconds FLOAT DEFAULT 0.02,
            reading_speed_target_cps INT DEFAULT 17,
            reading_speed_max_cps INT DEFAULT 21,
            file_format VARCHAR(20) DEFAULT 'PAC',
            two_speaker_format VARCHAR(50) DEFAULT 'hyphen_no_space',
            zero_subtitle_required BOOLEAN DEFAULT TRUE,
            rules JSON,
            subtitler_rules JSON,
            profanity_table JSON,
            remove_elements JSON,
            summary TEXT,
            is_custom BOOLEAN DEFAULT FALSE,
            guidelines_raw TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Safe migration: add versioning columns if they don't already exist
    for col_def in [
        "ALTER TABLE platforms ADD COLUMN platform_family VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE platforms ADD COLUMN version_label VARCHAR(100) DEFAULT 'Current'",
        "ALTER TABLE platforms ADD COLUMN italics VARCHAR(100) DEFAULT ''",
        "ALTER TABLE platforms ADD COLUMN profanity_handling VARCHAR(100) DEFAULT ''",
        "ALTER TABLE platforms ADD COLUMN source_file_id VARCHAR(64) DEFAULT NULL",
        "ALTER TABLE platforms ADD COLUMN source_filename VARCHAR(255) DEFAULT NULL",
        "ALTER TABLE platforms ADD COLUMN source_files TEXT DEFAULT NULL",
    ]:
        try:
            cursor.execute(col_def)
        except Exception:
            pass  # Column already exists — ignore

    # Jobs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cleaning_jobs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            filename VARCHAR(500),
            file_format VARCHAR(50),
            platform_key VARCHAR(100),
            structure_detected VARCHAR(100),
            total_lines INT DEFAULT 0,
            flagged_lines INT DEFAULT 0,
            total_defects INT DEFAULT 0,
            status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Movies table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(500) NOT NULL,
            url VARCHAR(1000) NOT NULL,
            added_by VARCHAR(200) DEFAULT 'Anonymous',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Delete old built-in platforms (is_custom = False)
    cursor.execute("DELETE FROM platforms WHERE is_custom = 0")

    conn.commit()
    cursor.close()
    conn.close()
    print("[DB] Database initialized")


def get_all_platforms():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM platforms ORDER BY is_custom ASC, name ASC, created_at DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    result = {}
    _list_fields = {"rules", "subtitler_rules", "remove_elements", "source_files"}
    _dict_fields = {"profanity_table"}
    for row in rows:
        for field in _list_fields:
            val = row.get(field)
            if isinstance(val, str):
                try:
                    row[field] = json.loads(val)
                except Exception:
                    row[field] = []
            elif val is None:
                row[field] = []
        for field in _dict_fields:
            val = row.get(field)
            if isinstance(val, str):
                try:
                    row[field] = json.loads(val)
                except Exception:
                    row[field] = {}
            elif val is None:
                row[field] = {}
        result[row["platform_key"]] = row
    return result


def save_custom_platform(platform_key: str, data: dict):
    conn = get_connection()
    cursor = conn.cursor()

    family  = data.get("platform_family", platform_key)
    version = (data.get("version_label") or "Current").strip()

    # ── Overwrite guard ────────────────────────────────────────────────────────
    # If a row already exists with the same OTT family AND version label (but
    # possibly a different key — e.g. old "custom_netflix" vs new
    # "custom_netflix__current") we re-use that existing key so the
    # ON DUPLICATE KEY UPDATE below overwrites it instead of creating a duplicate.
    cursor.execute(
        """SELECT platform_key FROM platforms
           WHERE platform_family = %s
             AND LOWER(TRIM(version_label)) = LOWER(TRIM(%s))
             AND platform_key != %s
           LIMIT 1""",
        (family, version, platform_key)
    )
    existing = cursor.fetchone()
    if existing:
        platform_key = existing[0]   # redirect upsert to the existing row
    # ──────────────────────────────────────────────────────────────────────────

    cursor.execute("""
        INSERT INTO platforms (
            platform_key, platform_family, version_label, name,
            max_chars_per_line, max_lines,
            min_duration_seconds, max_duration_seconds, min_interval_seconds,
            reading_speed_target_cps, reading_speed_max_cps,
            file_format, two_speaker_format, zero_subtitle_required,
            rules, subtitler_rules, remove_elements, profanity_table,
            italics, profanity_handling, summary, is_custom, guidelines_raw,
            source_file_id, source_filename, source_files
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, TRUE, %s,
            %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            platform_family = VALUES(platform_family),
            version_label = VALUES(version_label),
            name = VALUES(name),
            max_chars_per_line = VALUES(max_chars_per_line),
            max_lines = VALUES(max_lines),
            min_duration_seconds = VALUES(min_duration_seconds),
            max_duration_seconds = VALUES(max_duration_seconds),
            min_interval_seconds = VALUES(min_interval_seconds),
            reading_speed_target_cps = VALUES(reading_speed_target_cps),
            reading_speed_max_cps = VALUES(reading_speed_max_cps),
            file_format = VALUES(file_format),
            two_speaker_format = VALUES(two_speaker_format),
            zero_subtitle_required = VALUES(zero_subtitle_required),
            rules = VALUES(rules),
            subtitler_rules = VALUES(subtitler_rules),
            remove_elements = VALUES(remove_elements),
            profanity_table = VALUES(profanity_table),
            italics = VALUES(italics),
            profanity_handling = VALUES(profanity_handling),
            summary = VALUES(summary),
            is_custom = TRUE,
            guidelines_raw = VALUES(guidelines_raw),
            source_file_id = VALUES(source_file_id),
            source_filename = VALUES(source_filename),
            source_files = VALUES(source_files)
    """, (
        platform_key,
        family,
        version,
        data.get("name", platform_key),
        data.get("max_chars_per_line", 42),
        data.get("max_lines", 2),
        data.get("min_duration_seconds", 1.0),
        data.get("max_duration_seconds", 7.0),
        data.get("min_interval_seconds", 0.02),
        data.get("reading_speed_target_cps", 17),
        data.get("reading_speed_max_cps", 21),
        data.get("file_format", "PAC"),
        data.get("two_speaker_format", "hyphen_no_space"),
        data.get("zero_subtitle_required", True),
        json.dumps(data.get("rules", [])),
        json.dumps(data.get("subtitler_rules", [])),
        json.dumps(data.get("remove_elements", []) or []),
        json.dumps(data.get("profanity_table", {}) or {}),
        data.get("italics", ""),
        data.get("profanity_handling", ""),
        data.get("summary", ""),
        data.get("guidelines_raw", "")[:20000],
        data.get("source_file_id") or None,
        data.get("source_filename") or None,
        json.dumps(data.get("source_files") or [])
    ))
    conn.commit()
    cursor.close()
    conn.close()


def log_job(filename, fmt, platform, structure, total, flagged, defects):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cleaning_jobs
            (filename, file_format, platform_key, structure_detected,
             total_lines, flagged_lines, total_defects, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (filename, fmt, platform, structure, total, flagged, defects, "completed"))
        conn.commit()
    except Exception as e:
        print("Log error:", e)
    finally:
        cursor.close()
        conn.close()

def get_all_movies():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM movies ORDER BY created_at DESC")
    movies = cursor.fetchall()
    cursor.close()
    conn.close()
    return movies

def add_movie(title, url, added_by="Anonymous"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO movies (title, url, added_by) VALUES (%s, %s, %s)",
        (title, url, added_by)
    )
    conn.commit()
    cursor.close()
    conn.close()
