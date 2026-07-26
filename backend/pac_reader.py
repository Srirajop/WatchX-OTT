import math

def frames_to_ms(frames: int, fps: float = 25.0) -> int:
    return int(math.floor(frames * 1000.0 / fps))

def format_time(h: int, m: int, s: int, ms: int) -> str:
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def get_timecode(buffer: bytes, index: int) -> str:
    if index < 0 or index + 3 >= len(buffer):
        return format_time(0, 0, 0, 0)
    
    val_high = buffer[index] + buffer[index + 1] * 256
    val_low = buffer[index + 2] + buffer[index + 3] * 256
    
    high_str = f"{val_high:06d}"
    low_str = f"{val_low:06d}"
    
    hours = int(high_str[0:4])
    minutes = int(high_str[4:6])
    seconds = int(low_str[2:4])
    frames = int(low_str[4:6])
    
    ms = frames_to_ms(frames)
    return format_time(hours, minutes, seconds, ms)

def read_pac(file_bytes: bytes) -> str:
    if not file_bytes or len(file_bytes) < 20:
        return ""
        
    paragraphs = []
    index = 15
    
    while True:
        index += 1
        if index + 20 >= len(file_bytes):
            break
            
        if file_bytes[index] == 0xFE:
            minus15 = file_bytes[index - 15]
            minus12 = file_bytes[index - 12]
            
            fe_index = index
            time_start_index = -1
            
            if 0x60 <= minus15 <= 0x67:
                time_start_index = fe_index - 15
            elif 0x60 <= minus12 <= 0x67:
                time_start_index = fe_index - 12
                
            if time_start_index >= 0:
                # We found a paragraph
                if file_bytes[time_start_index] == 0x60:
                    start_time = get_timecode(file_bytes, time_start_index + 1)
                    end_time = get_timecode(file_bytes, time_start_index + 5)
                elif file_bytes[time_start_index + 3] == 0x60:
                    time_start_index += 3
                    start_time = get_timecode(file_bytes, time_start_index + 1)
                    end_time = get_timecode(file_bytes, time_start_index + 5)
                elif 0x61 <= file_bytes[time_start_index] <= 0x67:
                    start_time = get_timecode(file_bytes, time_start_index + 1)
                    end_time = get_timecode(file_bytes, time_start_index + 5)
                elif 0x61 <= file_bytes[time_start_index + 3] <= 0x67:
                    time_start_index += 3
                    start_time = get_timecode(file_bytes, time_start_index + 1)
                    end_time = get_timecode(file_bytes, time_start_index + 5)
                else:
                    continue
                    
                text_len = file_bytes[time_start_index + 9] + file_bytes[time_start_index + 10] * 256
                if text_len > 500:
                    continue
                    
                max_index = time_start_index + 10 + text_len
                
                # vertical_alignment = file_bytes[time_start_index + 11]
                alignment = file_bytes[fe_index + 1] & 0x03
                
                text_start = fe_index + 3
                
                if text_start + 4 <= len(file_bytes) and file_bytes[text_start] == 0x1f and file_bytes[text_start:text_start+4] == b"\x1fW16":
                    text_start += 5
                
                text_bytes = []
                curr_idx = text_start
                while curr_idx < len(file_bytes) and curr_idx <= max_index:
                    if curr_idx + 4 <= len(file_bytes) and file_bytes[curr_idx] == 0x1f and file_bytes[curr_idx:curr_idx+4] == b"\x1fW16":
                        curr_idx += 5
                        continue
                        
                    if curr_idx + 4 <= len(file_bytes) and file_bytes[curr_idx:curr_idx+4] == b"\x1f\xef\xbb\xbf":
                        curr_idx += 4
                        continue
                        
                    b = file_bytes[curr_idx]
                    
                    if b == 0xFE:
                        text_bytes.extend(b"\n")
                        curr_idx += 2
                    elif b == 0xFF:
                        text_bytes.extend(b" ")
                    elif 0x00 < b < 0x08 or b in (0x00, 0x0b, 0x0d, 0x17, 0x1d):
                        pass
                    else:
                        text_bytes.append(b)
                    
                    curr_idx += 1
                
                try:
                    # Best effort decode using cp1252 (Latin)
                    text_str = bytes(text_bytes).decode('cp1252', errors='replace')
                except Exception:
                    text_str = bytes(text_bytes).decode('utf-8', errors='replace')
                
                text_str = text_str.replace('\x00', '')
                
                # Remove pos codes
                idx_pos = text_str.find('\x2e\x1f')
                if idx_pos > 0:
                    text_str = text_str[:idx_pos + 1]
                
                # We can do minimal styling
                if alignment == 1:
                    text_str = r"{\an7}" + text_str
                elif alignment == 0:
                    text_str = r"{\an9}" + text_str
                
                paragraphs.append({
                    'start': start_time,
                    'end': end_time,
                    'text': text_str.strip()
                })
                
                index = max_index
                
    srt_out = []
    for i, p in enumerate(paragraphs, 1):
        srt_out.append(f"{i}")
        srt_out.append(f"{p['start']} --> {p['end']}")
        srt_out.append(p['text'])
        srt_out.append("")
        
    return "\n".join(srt_out)
