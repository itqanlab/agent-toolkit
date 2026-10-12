#!/usr/bin/env python3
"""
Bilingual (English + Arabic) narration via Piper: fully offline, fast, on the CPU.
Lower quality than edge.py, especially in Arabic. Use it when there is no internet.
EN voice: en_US-amy-medium   AR voice: ar_JO-kareem-medium (length_scale 0.72).
The voices are downloaded once by `scripts/setup.sh --piper` (about 126 MB).

Usage:
  tts.py --text "Hello world."                       --out out.mp3
  tts.py --text "مرحبا بكم" --lang ar                 --out out.wav
  tts.py --input script.json                          --out out.mp3     # [{"lang":"en","text":"..."},{"text":"..(auto)"}]
  tts.py --input lines.txt  --lang auto               --out out.wav     # blank-line-separated paragraphs
  tts.py --input script.json --per-segment segs_dir                     # one file per segment, NNN_<lang>.<ext>

Tunables: --ar-speed 0.72  --en-speed 1.0  --sentence-gap 250  --comma-gap 110  --gap-between 350
Output format is taken from the --out extension (.wav/.mp3/.m4a/.aac); non-wav needs ffmpeg or afconvert.
"""
import argparse, json, os, re, sys, wave, subprocess, tempfile
import numpy as np

from paths import voices_dir

VOICES = voices_dir()
VOICE_FILES = {"en": "en_US-amy-medium.onnx", "ar": "ar_JO-kareem-medium.onnx"}
AR_RANGE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")
SENT_END = ".!?؟\n"
CLAUSE = ",;،؛:"

_loaded = {}

# espeak-ng, inside Piper, keeps its data path in a fixed buffer of about 160 characters. A longer
# path fails with a misleading "phontab: No such file" naming the build machine. Measured: 104
# characters worked, 186 failed. Check before loading, and say what to do.
ESPEAK_PATH_LIMIT = 150

def check_espeak_path():
    from piper.phonemize_espeak import ESPEAK_DATA_DIR
    path = os.path.join(str(ESPEAK_DATA_DIR), "phontab")
    if len(path) > ESPEAK_PATH_LIMIT:
        sys.exit(f"The Piper install sits in a folder path too long for espeak-ng ({len(path)} characters, "
                 f"the limit is about {ESPEAK_PATH_LIMIT}).\n"
                 "Point AUDIO_NARRATE_HOME at a shorter folder and run setup again: "
                 "bash scripts/setup.sh --piper")

def get_voice(lang):
    from piper import PiperVoice
    if not _loaded:
        check_espeak_path()
    if lang not in _loaded:
        p = os.path.join(VOICES, VOICE_FILES[lang])
        if not os.path.exists(p):
            sys.exit(f"Piper voice missing: {p}\n"
                     "Download the two offline voices once (about 126 MB): bash scripts/setup.sh --piper")
        _loaded[lang] = PiperVoice.load(p)
    return _loaded[lang]

def detect_lang(text):
    ar = len(AR_RANGE.findall(text))
    letters = len(re.findall(r"\w", text)) or 1
    return "ar" if ar / letters > 0.15 else "en"

def _pcm(voice, text, length_scale):
    from piper import SynthesisConfig
    cfg = SynthesisConfig(length_scale=length_scale, noise_scale=0.667, noise_w_scale=0.8)
    raw = b"".join(c.audio_int16_bytes for c in voice.synthesize(text, cfg))
    return np.frombuffer(raw, dtype=np.int16)

def _sil(sr, ms):
    return np.zeros(int(sr * ms / 1000), dtype=np.int16)

def narrate(text, lang, length_scale, sentence_gap, comma_gap):
    """Split into sentences/clauses; synth each; insert silences for natural pauses."""
    voice = get_voice(lang)
    sr = voice.config.sample_rate
    tokens = re.split(r"([" + re.escape(SENT_END + CLAUSE) + r"])", text)
    chunks = []
    i = 0
    while i < len(tokens):
        seg = tokens[i].strip(); i += 1
        delim = tokens[i] if i < len(tokens) else ""; i += 1
        if not seg:
            continue
        keep = delim if delim in ".!?؟" else ""
        chunks.append(_pcm(voice, seg + keep, length_scale))
        if delim in ".!?؟\n":
            chunks.append(_sil(sr, sentence_gap))
        elif delim in CLAUSE:
            chunks.append(_sil(sr, comma_gap))
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    return audio, sr

def load_segments(args):
    """Return list of (lang, text)."""
    segs = []
    if args.text is not None:
        segs.append((args.lang, args.text))
    elif args.input:
        data = open(args.input, encoding="utf-8").read()
        if args.input.endswith(".json"):
            for item in json.loads(data):
                if isinstance(item, str):
                    segs.append((args.lang, item))
                else:
                    segs.append((item.get("lang", args.lang), item["text"]))
        else:  # txt/md: paragraphs split on blank lines
            for para in re.split(r"\n\s*\n", data):
                para = para.strip()
                if para:
                    segs.append((args.lang, para))
    else:
        sys.exit("provide --text or --input")
    # resolve 'auto'
    return [((detect_lang(t) if (l in (None, "auto")) else l), t) for l, t in segs]

def write_wav(path, audio, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(audio.tobytes())

def to_format(wav_path, out_path):
    if out_path.lower().endswith(".wav"):
        if os.path.abspath(wav_path) != os.path.abspath(out_path):
            os.replace(wav_path, out_path)
        return
    # convert via ffmpeg, else afconvert (mac)
    if _which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-i", wav_path, out_path],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif _which("afconvert") and out_path.lower().endswith((".m4a", ".aac")):
        subprocess.run(["afconvert", wav_path, out_path, "-f", "m4af", "-d", "aac"], check=True)
    else:
        sys.exit("ffmpeg not found for non-wav output; install ffmpeg or use --out *.wav")
    os.remove(wav_path)

def _which(x):
    from shutil import which
    return which(x)

def main():
    ap = argparse.ArgumentParser(description="Bilingual EN/AR voiceover (Piper)")
    ap.add_argument("--text"); ap.add_argument("--input")
    ap.add_argument("--out", default="voiceover.mp3")
    ap.add_argument("--lang", default="auto", choices=["auto", "en", "ar"])
    ap.add_argument("--ar-speed", type=float, default=0.72)
    ap.add_argument("--en-speed", type=float, default=1.0)
    ap.add_argument("--sentence-gap", type=int, default=250)
    ap.add_argument("--comma-gap", type=int, default=110)
    ap.add_argument("--gap-between", type=int, default=350, help="ms silence between segments")
    ap.add_argument("--per-segment", metavar="DIR", help="write each segment to its own file in DIR")
    args = ap.parse_args()

    segments = load_segments(args)
    if not segments:
        sys.exit("no text")

    if args.per_segment:
        os.makedirs(args.per_segment, exist_ok=True)
        ext = os.path.splitext(args.out)[1] or ".wav"
        for idx, (lang, text) in enumerate(segments, 1):
            ls = args.ar_speed if lang == "ar" else args.en_speed
            audio, sr = narrate(text, lang, ls, args.sentence_gap, args.comma_gap)
            base = os.path.join(args.per_segment, f"{idx:03d}_{lang}")
            tmp = base + ".wav"; write_wav(tmp, audio, sr)
            to_format(tmp, base + ext)
            print(f"[{idx}/{len(segments)}] {lang} {len(audio)/sr:.1f}s -> {base+ext}", flush=True)
        return

    sr = None; parts = []
    for idx, (lang, text) in enumerate(segments):
        ls = args.ar_speed if lang == "ar" else args.en_speed
        audio, sr = narrate(text, lang, ls, args.sentence_gap, args.comma_gap)
        if idx: parts.append(np.zeros(int(sr * args.gap_between / 1000), dtype=np.int16))
        parts.append(audio)
        print(f"[{idx+1}/{len(segments)}] {lang} {len(audio)/sr:.1f}s", flush=True)
    full = np.concatenate(parts)
    tmp = args.out + ".tmp.wav"; write_wav(tmp, full, sr)
    to_format(tmp, args.out)
    print(f"DONE {len(full)/sr:.1f}s -> {args.out}", flush=True)

if __name__ == "__main__":
    main()
