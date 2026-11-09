# AI Video Generation — Character Story Shorts (₹0 setup)

Makes 45–60 s vertical **story episodes with recurring characters** — each character has a fixed design and
their own voice, and they talk to each other on screen. **The default setup costs nothing.**

```
 Series / genre ─► Script + dialogue ─► Character voices ─► FLOW PACK ─► you make visuals ─► Edit ─► REVIEW ─► YouTube
                     Gemini (free)       Edge TTS (free)    prompts page   on Google Flow      ffmpeg   (you)     (free API)
                                                                           or any free site   captions, motion, music
```

| Step | Tool | Cost |
|---|---|---|
| Story, characters, dialogue, shot list | Google Gemini API free tier | ₹0 (no card) |
| A different voice for every character | Microsoft Edge neural voices (`edge-tts`) | ₹0 |
| Character designs, shot images, a few video clips | **You**, on Google Flow / Gemini / Luma / any free site, using the generated prompts | ₹0 |
| Camera motion on images, captions, music, edit | ffmpeg (on your PC) | ₹0 |
| Upload to YouTube | YouTube Data API | ₹0 |

**Your time per video:** ~10–15 minutes of copy-pasting prompts on the website. Everything else is automatic.

### Why the visuals step is manual
Google Flow, Luma, MagicLight etc. give free daily credits on their **websites** but no free API. Auto-clicking their
websites with a bot breaks their terms and gets accounts banned, so the pipeline does everything around that step:
writes every prompt, tells you which character images to attach, and finishes the video from whatever you drop in.
When you're ready to pay, one line in `config.yaml` (`visuals: fal`) makes it fully automatic.

### Free-tier limits to know
- **Google Flow** (free): images don't use credits; video gets ~50 credits/day ≈ a few short clips. In India, free outputs carry a **visible watermark**. Check Flow's terms before monetizing.
- **Luma Dream Machine** (free): about 1 clip/day, watermarked, **non-commercial**.
- **Gemini API** (free): Google may use free-tier prompts to improve its products (fine for story scripts).
- **Edge voices**: free but unofficial (it uses Microsoft Edge's read-aloud service). For a monetized channel, the safest free option is an open-source voice like Kokoro; paid option is ElevenLabs.

That's why the pipeline needs only **images** for most shots: each image gets smooth camera motion (push-ins,
pans, tilts), and you spend your few free video credits on the ★ hero shots it marks for you.

---

## 1. Install

Python 3.10+ and ffmpeg.
```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```
```bash
git clone https://github.com/NandaniRamoliya/AIvideoGenration.git
cd AIvideoGenration
pip install -r requirements.txt
```
Copy `.env.example` → `.env` and paste a free Gemini key from **aistudio.google.com/apikey** (no card needed).
That's the only key the free setup needs.

## 2. The 9 phases

Every video goes through the same phases. Each one saves its own files in `output/jobs/<id>/`,
is skipped when it's already done, and can be redone on its own.

| # | Phase | Who | What it makes |
|---|---|---|---|
| 1 | **idea** | auto (Gemini) | premise for the episode — from an idea bank: 10 ideas per request |
| 2 | **story** | auto (Gemini) | script, dialogue, shot list → `script.json` |
| 3 | **voices** | auto (Edge TTS) | every line in its character's voice → `voice.wav`, `timing.json` |
| 4 | **characters** | **you**, once per character | official look of each character → `characters/<id>/front.png` |
| 5 | **scenes** | **you**, every episode | one image (or clip) per shot → `inbox/01.png`, `02.mp4`… |
| 6 | **motion** | auto (ffmpeg) | camera moves on stills, clips fitted to length |
| 7 | **captions** | auto | word-by-word captions in each speaker's colour, name tags, hook card |
| 8 | **segments** | auto | every shot cut to its voice lines, joined |
| 9 | **final** | auto | captions + voice + music, loudness → `final.mp4`, thumbnail, post kit |

Voices come before the pictures because each shot's length comes from its lines — so the
pipeline stops for you only once.

```bash
python run.py make --series grandma-tales   # runs phases 1-3, then waits for your pictures
python run.py status <id>                   # the phase table (no id = latest video)
python run.py next <id>                     # continue from where it stopped
python run.py run <id> --phase voices       # redo a phase and everything after it (--only: just that one)
python run.py list                          # every video and the phase it's on
```
```
  The Rain Maker's Key   20261109-184701-117
  1 idea       ✔ done       8.6s  "Dadi tells Kabir about a key that locks the monsoon…"  (idea bank, 9 left)
  2 story      ✔ done      11.0s  "The Rain Maker's Key" · 6 shots · 104 words · gemini-3.5-flash
  3 voices     ✔ done      39.0s  60.4 s · 10 lines · dadi, kabir, narrator
  4 characters ⏸ waiting          need: char_dadi.png, char_kabir.png
  5 scenes     ⏸ waiting          0/6 shots · missing 01, 02, 03, 04, 05, 06
  6 motion     · pending
  ...
  Next → open .../FLOW_PACK.html, save the files into .../inbox, then: python run.py next 20261109-184701-117
```

## 3. Phases 4 + 5: make the pictures with FLOW_PACK.html

Two kinds of pictures: **character designs** are each character's official look (made **once**, reused
in every episode); **scenes** are this episode's shots (made every episode, with the designs attached
so faces and outfits match). The page lists both, with **Copy** buttons:

1. Go to **Google Flow** (labs.google/fx/tools/flow) or any free image site.
2. **Characters (first time only):** copy the design prompt, generate, save into the inbox as `char_dadi.png`, `char_kabir.png`…
3. **Each shot:** attach the listed character designs as references, paste the image prompt, pick **9:16**, save as `01.png`, `02.png`…
4. **★ shots:** if you have free video credits, turn that image into a clip with the video prompt and save as `01.mp4`.
5. Run `python run.py next <id>` — phases 6-9 run by themselves.

Inbox naming rules: the **first number** in the file name is the shot (`03.png`, `shot_03.jpg`, `Flow_03.mp4` all work).
`.png/.jpg/.webp` = still image (animated automatically). `.mp4/.mov/.webm` = clip (used as-is; preferred if both exist;
short clips are slowed slightly instead of freezing; landscape clips get centre-cropped).

`python run.py pack <id>` refreshes the page (✓ marks, thumbnails) as you add files.

## 4. Review and publish

```bash
python run.py list
python run.py approve <id>
python run.py reject  <id> --note "weak ending"
python run.py redo    <id> --shots 3        # puts shot 3's picture aside (inbox/_replaced) so you can make a new one
python run.py publish --approved            # YouTube (free API) — setup below
```
Every job folder has `final.mp4`, `thumbnail.jpg` and `post_kit.txt` (titles, hashtags, captions for Instagram/TikTok).

---

## Characters & series

Starter series in `config.yaml`:

| Series | Cast |
|---|---|
| `grandma-tales` — *Dadi's Midnight Tales* | Dadi (storyteller grandmother), Kabir (9-year-old grandson) |
| `space-cadets` — *Zara & Bolt* | Zara (teen pilot), Bolt (sarcastic repair robot) |

- `python run.py make --count 3` → stand-alone stories in rotating genres (horror, mystery, myth, urban legend, comedy…); the writer invents characters and saves them so they can return.
- Series remember previous episodes (`series_memory/`) for continuity.
- Characters live in `characters/<id>/character.yaml` (look, personality, voice). Their official image is `front.png`.
- New character: `python run.py cast new --name "Meera" --voice-type girl --look "12-year-old girl, long black braid with red ribbon, green kurta, white sneakers, sketchbook"`
- `python run.py ideas --series space-cadets` → 10 episode ideas; use one with `make --series space-cadets --idea "..."`.

### Voices
Each `voice_type` maps to a free Edge voice in `config.yaml > edge_voices` (with rate/pitch tweaks).
`python run.py voices --lang en-IN` lists voices; Hindi `hi-IN`, Gujarati `gu-IN`. Give one character a specific
voice with `edge_voice: "hi-IN-SwaraNeural"` in its `character.yaml`. For Hindi/Gujarati stories set `channel.language`.

### Look
`visual_style` in `config.yaml` (default: 3D animated feature-film style). Every prompt includes it, so all
shots match. Each series can override it.

---

## YouTube setup (once, free)
1. console.cloud.google.com → new project → enable **YouTube Data API v3**.
2. OAuth consent screen → External → add your Gmail as test user.
3. Credentials → OAuth client ID → **Desktop app** → download → `secrets/client_secret.json`.
4. `python run.py auth-youtube`.

New projects have a small daily upload quota, and uploads may stay private until Google verifies the app.

## Daily routine
```bash
python run.py make --series grandma-tales && python run.py make --count 2    # morning: scripts + voices (automatic)
# open each FLOW_PACK.html, make images on Flow, drop them in the inbox          (~10–15 min per video)
python run.py next <id>        →   python run.py approve <id>   →   python run.py publish --approved
```
The first line can run on a schedule (Windows Task Scheduler / cron) so packs are waiting for you every morning.

## Free test without any key
```bash
python run.py make --series grandma-tales --mock
```
Robot voices + storyboard placeholders. Only for checking timing and captions; it never makes real visuals.

## Going paid later (optional)
Change `providers` in `config.yaml`:
```yaml
providers:
  llm: claude          # ANTHROPIC_API_KEY
  tts: elevenlabs      # ELEVENLABS_API_KEY — commercial license, more natural voices
  visuals: fal         # FAL_KEY — fully automatic: character sheets, keyframes from references, Kling 3 clips (~$5/video)
```
Any mix works, e.g. free script + free voices + paid visuals.

## Project layout
```
run.py                  CLI: make, status, next, run, list, pack, redo, cast, series, ideas, voices, approve, publish
config.yaml             providers, series, voices, style, captions
characters/<id>/        character.yaml + front.png (official look)
series_memory/          episode summaries per series
pipeline/phases.py      the 9 phases: order, skip-if-done, redo, tracking table
pipeline/llm.py         Gemini (free, with fallback models) / Claude
pipeline/writer.py      idea bank, cast + dialogue + shot list, genre rotation, memory
pipeline/voice.py       Edge (free) / ElevenLabs, one voice per speaker, word timings
pipeline/flowpack.py    FLOW_PACK.html, inbox, animated stills, clip fitting
pipeline/visuals.py     automatic scenes into the inbox: mock storyboards, or paid fal.ai
pipeline/captions.py    speaker-coloured word-by-word captions, name tags, hook card
pipeline/assemble.py    ffmpeg edit, music ducking, -14 LUFS
pipeline/youtube.py     upload / schedule
output/jobs/<id>/       one video: script, voices, FLOW_PACK.html, inbox/, final.mp4
```

## Rules
- Original stories and characters only; no real people or copyrighted characters.
- Turn on the platform's "AI-generated" label when posting.
- Only use music you have rights to (`assets/music/`).
- Respect each website's terms for free-tier output, especially before monetizing.
