#!/usr/bin/env python3
"""
Bilingual (English + Arabic) narration via edge-tts: Microsoft's neural voices, free, no key.
Clearly more natural than Piper, especially in Arabic. Needs internet; tts.py (Piper) is the
offline fallback.

Voices:
  Arabic (Modern Standard) -> Taim (ar-JO), or Zariyah (ar-SA) with --female
  English                  -> Guy (en-US), or Aria (en-US) with --female

Before synthesis, a pronunciation lexicon respells words the engine says wrong: the built-in
lexicon.json, then narrate-lexicon.json in the current folder, then --lexicon FILE. Later wins.

Usage:
  edge.py --text "Welcome to the tour."                         --out out.mp3
  edge.py --text "مرحبا بكم" --female                            --out out.mp3
  edge.py --input script.json                                   --out out.mp3
  edge.py --input script.json --per-segment segs_dir            # one file per segment, NNN_<lang>.mp3
  edge.py --text "..." --voice ar-SA-ZariyahNeural              # any edge voice id

Tunables: --rate +0%  --pitch +0Hz  --volume +0%  --gap-between 350 (ms between segments)
Output format follows the --out extension (.mp3/.wav/.m4a). ffmpeg is required.
"""
import argparse, asyncio, json, os, re, sys, subprocess, tempfile
from shutil import which

LEXICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lexicon.json")
PROJECT_LEXICON = "narrate-lexicon.json"
AR_RANGE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")

# lang -> gender -> voice
VOICES = {
    ("ar", "m"): "ar-JO-TaimNeural",
    ("ar", "f"): "ar-SA-ZariyahNeural",
    ("en", "m"): "en-US-GuyNeural",
    ("en", "f"): "en-US-AriaNeural",
}

def detect_lang(text):
    ar = len(AR_RANGE.findall(text))
    letters = len(re.findall(r"\w", text, re.UNICODE)) or 1
    return "ar" if ar / letters > 0.15 else "en"

def load_lexicon(extra=None):
    """Built-in, then the project's narrate-lexicon.json, then --lexicon. Later files win."""
    lex = {"ar": {}, "en": {}}
    for path in (LEXICON, PROJECT_LEXICON, extra):
        if not path or not os.path.exists(path):
            if path == extra and extra:
                sys.exit(f"lexicon not found: {extra}")
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except ValueError as err:
            sys.exit(f"{path} is not valid JSON: {err}")
        for lang in ("ar", "en"):
            lex[lang].update(data.get(lang, {}))
    return lex

def apply_lexicon(text, lang, lex):
    """Respell known problem words. Longest keys first (phrases beat single words)."""
    bucket = {k: v for k, v in lex.get(lang, {}).items() if k != "_doc"}
    for key in sorted(bucket, key=len, reverse=True):
        rep = bucket[key]
        if lang == "en":
            text = re.sub(re.escape(key), rep, text, flags=re.IGNORECASE)
        else:
            text = text.replace(key, rep)
    return text

def pick_voice(lang, female, override):
    if override:
        return override
    return VOICES[(lang, "f" if female else "m")]

def load_segments(args):
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
        else:
            for para in re.split(r"\n\s*\n", data):
                para = para.strip()
                if para:
                    segs.append((args.lang, para))
    else:
        sys.exit("provide --text or --input")
    return [((detect_lang(t) if (l in (None, "auto")) else l), t) for l, t in segs]

async def _synth(text, voice, rate, pitch, volume, out_mp3):
    import edge_tts
    kw = {"rate": rate, "volume": volume}
    if pitch:
        kw["pitch"] = pitch
    comm = edge_tts.Communicate(text, voice, **kw)
    await comm.save(out_mp3)


async def synth(text, voice, rate, pitch, volume, out_mp3):
    """edge-tts talks to an unofficial Microsoft endpoint that changes without notice. When it
    refuses, say so plainly and point at the offline engine instead of dumping a traceback."""
    try:
        await _synth(text, voice, rate, pitch, volume, out_mp3)
    except Exception as err:  # aiohttp and edge_tts raise several unrelated types
        status = getattr(err, "status", None)
        why = f"HTTP {status}" if status else type(err).__name__
        sys.exit(
            f"Microsoft's voice service refused the request ({why}). Nothing was made.\n"
            "This is the free edge endpoint changing or blocking the client, not your text.\n"
            "Try again later, update with `bash scripts/setup.sh` after a new edge-tts release, or narrate\n"
            "offline now with Piper: bash scripts/run.sh piper --text \"...\" --out a.wav"
        )

def ffmpeg_ok():
    return which("ffmpeg") is not None

def make_silence(path, ms):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{ms/1000:.3f}", "-q:a", "9", path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def concat(mp3_list, out_path, gap_ms, tmpdir):
    """Concat segment mp3s with gap_ms silence between them, then convert to out ext."""
    parts = []
    if gap_ms > 0 and len(mp3_list) > 1:
        sil = os.path.join(tmpdir, "sil.mp3")
        make_silence(sil, gap_ms)
        for i, m in enumerate(mp3_list):
            if i:
                parts.append(sil)
            parts.append(m)
    else:
        parts = mp3_list
    listfile = os.path.join(tmpdir, "list.txt")
    with open(listfile, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    merged = os.path.join(tmpdir, "merged.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                    "-c:a", "libmp3lame", "-q:a", "3", merged],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ext = os.path.splitext(out_path)[1].lower()
    if ext == ".mp3":
        os.replace(merged, out_path)
    else:
        subprocess.run(["ffmpeg", "-y", "-i", merged, out_path],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(merged)

def main():
    ap = argparse.ArgumentParser(description="Bilingual EN/AR voiceover (edge-tts, Azure neural)")
    ap.add_argument("--text"); ap.add_argument("--input")
    ap.add_argument("--out", default="voiceover.mp3")
    ap.add_argument("--lang", default="auto", choices=["auto", "en", "ar"])
    ap.add_argument("--female", action="store_true", help="use the female voice")
    ap.add_argument("--voice", help="explicit edge voice id, overrides the default map")
    ap.add_argument("--rate", default="+0%"); ap.add_argument("--pitch", default="+0Hz")
    ap.add_argument("--volume", default="+0%")
    ap.add_argument("--gap-between", type=int, default=350, help="ms silence between segments")
    ap.add_argument("--per-segment", metavar="DIR", help="write each segment to its own file")
    ap.add_argument("--no-lexicon", action="store_true", help="disable pronunciation respelling")
    ap.add_argument("--lexicon", help="extra lexicon JSON file, applied last")
    args = ap.parse_args()

    if not ffmpeg_ok():
        sys.exit("ffmpeg not found. The edge engine needs it to join and convert audio.\n"
                 "Install it: macOS `brew install ffmpeg`, Debian/Ubuntu `sudo apt install ffmpeg`, "
                 "Windows `winget install Gyan.FFmpeg`.")

    segments = load_segments(args)
    if not segments:
        sys.exit("no text")
    lex = None if args.no_lexicon else load_lexicon(args.lexicon)

    def prep(lang, text):
        return text if lex is None else apply_lexicon(text, lang, lex)

    if args.per_segment:
        os.makedirs(args.per_segment, exist_ok=True)
        ext = os.path.splitext(args.out)[1] or ".mp3"
        for idx, (lang, text) in enumerate(segments, 1):
            voice = pick_voice(lang, args.female, args.voice)
            spoken = prep(lang, text)
            with tempfile.TemporaryDirectory() as td:
                seg_mp3 = os.path.join(td, "s.mp3")
                asyncio.run(synth(spoken, voice, args.rate, args.pitch, args.volume, seg_mp3))
                out = os.path.join(args.per_segment, f"{idx:03d}_{lang}{ext}")
                if ext.lower() == ".mp3":
                    os.replace(seg_mp3, out)
                else:
                    subprocess.run(["ffmpeg", "-y", "-i", seg_mp3, out],
                                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[{idx}/{len(segments)}] {lang} {voice} -> {out}", flush=True)
        return

    with tempfile.TemporaryDirectory() as td:
        mp3s = []
        for idx, (lang, text) in enumerate(segments, 1):
            voice = pick_voice(lang, args.female, args.voice)
            spoken = prep(lang, text)
            seg = os.path.join(td, f"{idx:03d}.mp3")
            asyncio.run(synth(spoken, voice, args.rate, args.pitch, args.volume, seg))
            mp3s.append(seg)
            print(f"[{idx}/{len(segments)}] {lang} {voice}", flush=True)
        concat(mp3s, args.out, args.gap_between, td)
    print(f"DONE -> {args.out}", flush=True)

if __name__ == "__main__":
    main()
