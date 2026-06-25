from transcript_aligner import align_transcription_to_script

whisper_subs = [{"id": 1, "start_time": "00:00:01,000", "end_time": "00:00:02,000", "text": "hello"}]
script_subs = [{"id": 1, "text": "hello"}]

try:
    print(align_transcription_to_script(whisper_subs, script_subs))
except Exception as e:
    import traceback
    traceback.print_exc()
