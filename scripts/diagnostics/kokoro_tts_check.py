import time
from modules.voice_io.tts import TextToSpeech

def test_tts():
    tts = TextToSpeech()
    tts.speak("This is a test of the new Kokoro TTS system.")
    tts.speak_chunked("It should process this chunk by chunk. ")
    tts.speak_chunked("Here is another sentence. ")
    
    while tts.is_speaking or tts.has_pending_speech:
        time.sleep(0.1)
        
    print("Done testing basic speech.")
    
    print("Testing interruption...")
    tts.speak_chunked("This is a very long sentence that I am going to try to interrupt before it finishes. It just keeps going and going, because I need it to take long enough for the script to stop it. Here is some more text. Blah blah blah.")
    time.sleep(1.0)
    tts.stop()
    print("Interrupted!")
    
    time.sleep(1.0)
    print("All tests finished.")

if __name__ == "__main__":
    test_tts()
