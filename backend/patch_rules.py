import json
import asyncio
from database import get_connection
from cleaner import extract_platform_rules_with_ai

def process_all():
    conn = get_connection()
    c = conn.cursor(dictionary=True)
    c.execute("SELECT platform_key, name, guidelines_raw FROM platforms WHERE is_custom=TRUE AND guidelines_raw IS NOT NULL AND guidelines_raw != ''")
    rows = c.fetchall()
    
    print(f"Starting re-extraction for {len(rows)} platforms...")
    for row in rows:
        key = row['platform_key']
        name = row['name']
        raw = row['guidelines_raw']
        print(f"Processing: {name} ({key})")
        
        try:
            result = extract_platform_rules_with_ai(raw, name)
            script_rules = result.get('rules', [])
            subtitler_rules = result.get('subtitler_rules', [])
            
            c_upd = conn.cursor()
            c_upd.execute(
                "UPDATE platforms SET rules=%s, subtitler_rules=%s WHERE platform_key=%s",
                (json.dumps(script_rules), json.dumps(subtitler_rules), key)
            )
            conn.commit()
            c_upd.close()
            print(f"  -> Success: {len(script_rules)} script rules, {len(subtitler_rules)} subtitler rules")
        except Exception as e:
            print(f"  -> Failed: {e}")
            
    c.close()
    conn.close()
    print("Done all!")

if __name__ == "__main__":
    process_all()
