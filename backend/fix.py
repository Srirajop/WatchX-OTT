import sys
import re

with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = lines[:707]

platforms_code = """# ─── PLATFORMS ───────────────────────────────────────────────────

@app.get("/platforms")
def get_platforms():
    try:
        platforms = get_all_platforms()
        return {"platforms": platforms}
    except:
        # Fallback to static list if DB not ready
        return {"platforms": {p["key"]: p for p in get_platform_list()}}


@app.post("/platforms/add")
async def add_platform(
    platform_name: str = Form(...),
    guidelines_file: UploadFile = File(None),
    guidelines_text: str = Form(default="")
):
    if not platform_name.strip():
        raise HTTPException(400, "Platform name is required")

    platform_key = "custom_" + re.sub(r'[^a-z0-9]', '_', platform_name.lower().strip())

    raw_guidelines = ""
    if guidelines_file and guidelines_file.filename:
        file_bytes = await guidelines_file.read()
        file_data = read_file(file_bytes, guidelines_file.filename)
        raw_guidelines = file_data["raw_text"]
    elif guidelines_text.strip():
        raw_guidelines = guidelines_text.strip()

    if raw_guidelines:
        platform_data = extract_platform_rules_with_ai(raw_guidelines, platform_name.strip())
    else:
        platform_data = {
            "name": platform_name.strip(),
            "max_chars_per_line": 42,
            "max_lines": 2,
            "rules": ["Maximum 42 characters per line", "Maximum 2 lines", "Standard guidelines"],
            "summary": f"Custom: {platform_name.strip()}"
        }

    platform_data["guidelines_raw"] = raw_guidelines
    save_custom_platform(platform_key, platform_data)

    return {
        "success": True,
        "platform_key": platform_key,
        "platform_name": platform_name.strip(),
        "rules_extracted": len(platform_data.get("rules", [])),
        "message": f"Platform '{platform_name}' added with {len(platform_data.get('rules', []))} rules"
    }


@app.delete("/platforms/{platform_key}")
def delete_platform(platform_key: str):
    if not platform_key.startswith("custom_"):
        raise HTTPException(400, "Cannot delete built-in platforms")
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM platforms WHERE platform_key=%s AND is_custom=TRUE", (platform_key,))
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    if affected == 0:
        raise HTTPException(404, "Platform not found")
    return {"success": True}


@app.put("/platforms/{platform_key}")
async def update_platform(platform_key: str, data: dict):
    if not platform_key.startswith("custom_"):
        raise HTTPException(400, "Cannot modify built-in platforms")
    
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise HTTPException(400, "Rules must be an array")

    from database import get_connection
    import json
    
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT config_json FROM platforms WHERE platform_key=%s AND is_custom=TRUE", (platform_key,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        raise HTTPException(404, "Custom platform not found")
        
    config = json.loads(row["config_json"])
    config["rules"] = rules
    
    cursor.execute("UPDATE platforms SET config_json=%s WHERE platform_key=%s", (json.dumps(config), platform_key))
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"success": True, "message": "Rules updated successfully"}


# ─── HELPER ──────────────────────────────────────────────────────

def normalize_tc(tc: str) -> str:
    if not tc:
        return ""
    tc = tc.strip()
    if re.match(r'\d{2}:\d{2}:\d{2},\d{3}', tc):
        return tc
    m = re.match(r'(\d{2}):(\d{2}):(\d{2})[:;](\d{2})', tc)
    if m:
        h, mn, s, f = m.groups()
        ms = int(int(f) * 1000 / 25)
        return f"{h}:{mn}:{s},{ms:03d}"
    m = re.match(r'(\d{2}):(\d{2}):(\d{2})\.(\d+)', tc)
    if m:
        h, mn, s, ms = m.groups()
        return f"{h}:{mn}:{s},{ms[:3].ljust(3,'0')}"
    return tc
"""

new_lines.extend([l + '\n' for l in platforms_code.split('\n')])
new_lines.extend(lines[718:])

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
