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
            profanity_table JSON,
            remove_elements JSON,
            summary TEXT,
            is_custom BOOLEAN DEFAULT FALSE,
            guidelines_raw TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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

    # Insert all built-in platforms
    for key, p in PLATFORMS.items():
        cursor.execute("""
            INSERT IGNORE INTO platforms
            (platform_key, name, max_chars_per_line, max_lines,
             min_duration_seconds, max_duration_seconds, min_interval_seconds,
             reading_speed_target_cps, reading_speed_max_cps,
             file_format, two_speaker_format, zero_subtitle_required,
             rules, profanity_table, remove_elements, is_custom)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            key, p["name"],
            p.get("max_chars_per_line", 42),
            p.get("max_lines", 2),
            p.get("min_duration_seconds", 1.0),
            p.get("max_duration_seconds", 7.0),
            p.get("min_interval_seconds", 0.02),
            p.get("reading_speed_target_cps", 17),
            p.get("reading_speed_max_cps", 21),
            p.get("file_format", "PAC"),
            p.get("two_speaker_format", "hyphen_no_space"),
            p.get("zero_subtitle_required", True),
            json.dumps(p.get("rules", [])),
            json.dumps(p.get("profanity_table", {})),
            json.dumps(p.get("remove_elements", [])),
            False
        ))

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
    for row in rows:
        for field in ["rules", "profanity_table", "remove_elements"]:
            if isinstance(row.get(field), str):
                try:
                    row[field] = json.loads(row[field])
                except:
                    row[field] = []
        result[row["platform_key"]] = row
    return result


def save_custom_platform(platform_key: str, data: dict):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO platforms
        (platform_key, name, max_chars_per_line, max_lines,
         min_duration_seconds, max_duration_seconds, min_interval_seconds,
         reading_speed_target_cps, reading_speed_max_cps,
         file_format, two_speaker_format, zero_subtitle_required,
         rules, summary, is_custom, guidelines_raw)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
        name=VALUES(name), rules=VALUES(rules),
        summary=VALUES(summary), guidelines_raw=VALUES(guidelines_raw)
    """, (
        platform_key, data.get("name", platform_key),
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
        data.get("summary", ""),
        True,
        data.get("guidelines_raw", "")[:5000]
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
