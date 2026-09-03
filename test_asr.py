import sys
from pathlib import Path
from libs.platform.models.asr import FasterWhisperTranscriber

def main():
    if len(sys.argv) < 2:
        print("Usage: .\\.venv\\Scripts\\python.exe test_asr.py <path_to_audio_file>")
        return
    
    audio_path = Path(sys.argv[1])
    if not audio_path.exists():
        print(f"Error: File not found at {audio_path}")
        return
        
    print(f"Loading medium model and testing on: {audio_path}")
    print("This may take a minute or two the first time to download the medium model...\n")
    
    transcriber = FasterWhisperTranscriber(model_size="medium")
    transcript = transcriber.transcribe(audio_path, attachment_id="test_1")
    
    print("\n--- RESULTS ---")
    print(f"Detected Language: {transcript.language}")
    print(f"Transcript (Translated to English): {transcript.text}")

if __name__ == "__main__":
    main()
