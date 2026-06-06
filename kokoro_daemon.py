# import asyncio
# import time
# import re
# import queue
# import threading
# import sounddevice as sd
# from kokoro_onnx import Kokoro

# # Thread-safe queue to "join" the audio chunks
# audio_queue = queue.Queue()

# def split_into_sentences(text):
#     return [c for c in re.split(r'(?<=[.!?])\s+', text.strip()) if c]

# def playback_consumer():
#     """Plays audio from the queue sequentially to avoid overlapping."""
#     while True:
#         item = audio_queue.get()
#         if item is None: break  # Poison pill to stop the thread
#         samples, rate = item
#         sd.play(samples, rate)
#         sd.wait() # Properly joins the chunks
#         audio_queue.task_done()

# async def run_optimized_benchmark(text):
#     sentences = split_into_sentences(text)
#     kokoro = Kokoro("models/kokoro-v0_19.onnx", "models/voices.npy")
    
#     # Start the playback thread
#     threading.Thread(target=playback_consumer, daemon=True).start()
    
#     print("\n" + "="*50)
#     print("           KOKORO OPTIMIZED PIPELINE           ")
#     print("="*50)
    
#     total_start = time.perf_counter()
    
#     for i, sentence in enumerate(sentences):
#         gen_start = time.perf_counter()
#         stream = kokoro.create_stream(sentence, voice="af_sarah", speed=1.0, lang="en-us")
        
#         first_chunk = True
#         async for samples, sample_rate in stream:
#             if first_chunk:
#                 gen_end = time.perf_counter()
#                 latency = gen_end - gen_start
#                 print(f"[Chunk {i+1}] Created at: {gen_end - total_start:.4f}s | Latency: {latency:.4f}s")
#                 first_chunk = False
            
#             # Pipeline the audio into the playback thread
#             audio_queue.put((samples, sample_rate))
    
#     # Wait for the queue to empty
#     audio_queue.join()
#     audio_queue.put(None) # Signal playback thread to stop

# if __name__ == "__main__":
#     test_text = (
#         "On May nineteenth, twenty twenty six, Doctor Smith reviewed Chapter four of the manual. "
#         "The system processed one thousand two hundred and fifty dollars, which is exactly three quarters of the total budget. "
#         "Furthermore, the equation E equals M C squared was verified by King Louis the fourteenth."
#     )
#     asyncio.run(run_optimized_benchmark(test_text))



# import os
# os.environ["OMP_NUM_THREADS"] = "2"
# os.environ["ORT_NUM_THREADS"] = "2"

# import asyncio
# import time
# from kokoro_onnx import Kokoro

# async def synth(kokoro, text, idx):
#     start = time.perf_counter()
#     stream = kokoro.create_stream(text, voice="af_sarah", speed=1.0, lang="en-us")
#     first = True
#     count = 0

#     async for samples, rate in stream:
#         count += 1
#         if first:
#             print(f"chunk {idx} first audio: {time.perf_counter() - start:.4f}s")
#             first = False

#     print(f"chunk {idx} full synth: {time.perf_counter() - start:.4f}s")

# async def main():
#     k1 = Kokoro("models/kokoro-v0_19.onnx", "models/voices.npy")
#     k2 = Kokoro("models/kokoro-v0_19.onnx", "models/voices.npy")

#     await asyncio.gather(
#         synth(k1, "Doctor Smith reviewed Chapter four of the manual.", 1),
#         synth(k2, "The system processed one thousand two hundred and fifty dollars.", 2),
#     )

# asyncio.run(main())



# import os
# os.environ["OMP_NUM_THREADS"] = "6"
# os.environ["ORT_NUM_THREADS"] = "6"

# import asyncio
# import time
# import re
# import queue
# import threading
# import sounddevice as sd
# from kokoro_onnx import Kokoro

# audio_queue = queue.Queue()
# text_queue = queue.Queue()

# STOP = object()

# def split_for_tts(text, max_chars=50):
#     raw_parts = re.split(r'(?<=[.!?,;:])\s+', text.strip())
#     chunks = []

#     for part in raw_parts:
#         part = part.strip()
#         if not part:
#             continue

#         while len(part) > max_chars:
#             cut = part.rfind(" ", 0, max_chars)
#             if cut == -1:
#                 cut = max_chars
#             chunks.append(part[:cut].strip())
#             part = part[cut:].strip()

#         if part:
#             chunks.append(part)

#     return chunks

# def playback_consumer():
#     playback_started = False
#     base = time.perf_counter()

#     while True:
#         item = audio_queue.get()
#         if item is STOP:
#             audio_queue.task_done()
#             break

#         samples, rate = item

#         if not playback_started:
#             print(f"[Playback] Started at: {time.perf_counter() - base:.4f}s")
#             playback_started = True

#         sd.play(samples, rate)
#         sd.wait()
#         audio_queue.task_done()

# async def warmup(kokoro):
#     stream = kokoro.create_stream("Ready.", voice="af_sarah", speed=1.0, lang="en-us")
#     async for _samples, _rate in stream:
#         break

# async def tts_worker(kokoro, total_start):
#     while True:
#         item = text_queue.get()
#         if item is STOP:
#             text_queue.task_done()
#             break

#         idx, chunk = item
#         gen_start = time.perf_counter()

#         stream = kokoro.create_stream(
#             chunk,
#             voice="af_sarah",
#             speed=1.0,
#             lang="en-us"
#         )

#         first = True
#         async for samples, sample_rate in stream:
#             if first:
#                 now = time.perf_counter()
#                 print(
#                     f"[Chunk {idx+1}] Text: {chunk[:50]!r} | "
#                     f"Created at: {now - total_start:.4f}s | "
#                     f"Latency: {now - gen_start:.4f}s"
#                 )
#                 first = False

#             audio_queue.put((samples, sample_rate))

#         text_queue.task_done()

# async def run_pipeline(text):
#     load_start = time.perf_counter()
#     kokoro = Kokoro("models/kokoro-v0_19.onnx", "models/voices.npy")
#     print(f"Model load time: {time.perf_counter() - load_start:.4f}s")

#     warm_start = time.perf_counter()
#     await warmup(kokoro)
#     print(f"Warmup time: {time.perf_counter() - warm_start:.4f}s")

#     chunks = split_for_tts(text, max_chars=80)

#     threading.Thread(target=playback_consumer, daemon=True).start()

#     print("\n" + "=" * 50)
#     print("           KOKORO OVERLAPPED PIPELINE           ")
#     print("=" * 50)

#     total_start = time.perf_counter()

#     worker_task = asyncio.create_task(tts_worker(kokoro, total_start))

#     for i, chunk in enumerate(chunks):
#         text_queue.put((i, chunk))

#     text_queue.put(STOP)

#     await worker_task

#     audio_queue.join()
#     audio_queue.put(STOP)

# if __name__ == "__main__":
#     test_text = (
#         "On May nineteenth, twenty twenty six, Doctor Smith reviewed Chapter four of the manual. "
#         "The system processed one thousand two hundred and fifty dollars, which is exactly three quarters of the total budget. "
#         "Furthermore, the equation E equals M C squared was verified by King Louis the fourteenth."
#     )

#     asyncio.run(run_pipeline(test_text))



import os

# Best result from your benchmark.
# Must be set before importing kokoro_onnx / onnxruntime.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["ORT_NUM_THREADS"] = "1"

import asyncio
import time
import re
import queue
import threading
import sounddevice as sd
from kokoro_onnx import Kokoro


MODEL_PATH = "models/kokoro-v0_19.onnx"
VOICES_PATH = "models/voices.npy"

VOICE = "af_sarah"
LANG = "en-us"
SPEED = 1.0

MAX_CHARS = 80

STOP = object()

text_queue = queue.Queue()
audio_queue = queue.Queue()


def split_for_tts(text, max_chars=MAX_CHARS):
    """
    Splits text into small TTS-friendly chunks.

    Goal:
    - Reduce first-audio latency.
    - Avoid very long Kokoro calls.
    - Preserve natural pauses at punctuation where possible.
    """
    text = " ".join(text.strip().split())
    if not text:
        return []

    raw_parts = re.split(r"(?<=[.!?,;:])\s+", text)

    chunks = []

    for part in raw_parts:
        part = part.strip()
        if not part:
            continue

        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)

            if cut == -1 or cut < max_chars * 0.45:
                cut = max_chars

            chunk = part[:cut].strip()
            if chunk:
                chunks.append(chunk)

            part = part[cut:].strip()

        if part:
            chunks.append(part)

    return chunks


def playback_consumer(total_start=None):
    """
    Sequential audio playback.

    Uses sd.play + sd.wait for simplicity and reliability.
    This is not the main bottleneck right now.
    """
    playback_started = False

    while True:
        item = audio_queue.get()

        if item is STOP:
            audio_queue.task_done()
            break

        idx, samples, rate = item

        if not playback_started:
            playback_started = True
            if total_start is not None:
                print(f"[Playback] Started at: {time.perf_counter() - total_start:.4f}s")

        sd.play(samples, rate)
        sd.wait()

        audio_queue.task_done()


async def warmup(kokoro):
    """
    Runs one tiny inference so ONNX/Kokoro initializes before real speech.
    """
    stream = kokoro.create_stream(
        "Ready.",
        voice=VOICE,
        speed=SPEED,
        lang=LANG,
    )

    async for _samples, _rate in stream:
        break


async def tts_worker(kokoro, total_start):
    """
    Single Kokoro synthesis worker.

    Do not use multiple Kokoro workers on your current machine.
    Your benchmark showed parallel workers increase latency.
    """
    while True:
        item = text_queue.get()

        if item is STOP:
            text_queue.task_done()
            break

        idx, chunk = item
        gen_start = time.perf_counter()

        stream = kokoro.create_stream(
            chunk,
            voice=VOICE,
            speed=SPEED,
            lang=LANG,
        )

        first_audio = True

        async for samples, sample_rate in stream:
            if first_audio:
                now = time.perf_counter()
                print(
                    f"[Chunk {idx + 1}] "
                    f"len={len(chunk):02d} | "
                    f"Text: {chunk[:55]!r} | "
                    f"Created at: {now - total_start:.4f}s | "
                    f"Latency: {now - gen_start:.4f}s"
                )
                first_audio = False

            audio_queue.put((idx, samples, sample_rate))

        text_queue.task_done()


async def speak(text):
    """
    Main TTS pipeline:
    - persistent Kokoro instance
    - warmup
    - strict chunking
    - one synthesis worker
    - one playback worker
    """
    load_start = time.perf_counter()
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    print(f"Model load time: {time.perf_counter() - load_start:.4f}s")

    warm_start = time.perf_counter()
    await warmup(kokoro)
    print(f"Warmup time: {time.perf_counter() - warm_start:.4f}s")

    chunks = split_for_tts(text)

    print("\nChunks:")
    for i, chunk in enumerate(chunks):
        print(f"{i + 1}. len={len(chunk):02d} | {chunk!r}")

    print("\n" + "=" * 50)
    print("        KOKORO FINAL LOW-LATENCY PIPELINE        ")
    print("=" * 50)

    total_start = time.perf_counter()

    playback_thread = threading.Thread(
        target=playback_consumer,
        args=(total_start,),
        daemon=True,
    )
    playback_thread.start()

    worker_task = asyncio.create_task(tts_worker(kokoro, total_start))

    for i, chunk in enumerate(chunks):
        text_queue.put((i, chunk))

    text_queue.put(STOP)

    await worker_task

    audio_queue.join()
    audio_queue.put(STOP)
    audio_queue.join()


if __name__ == "__main__":
    test_text = (
        "On May nineteenth, twenty twenty six, Doctor Smith reviewed Chapter four of the manual. "
        "The system processed one thousand two hundred and fifty dollars, which is exactly three quarters of the total budget. "
        "Furthermore, the equation E equals M C squared was verified by King Louis the fourteenth."
    )

    asyncio.run(speak(test_text))