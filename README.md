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

## 2. Make an episode

```bash
python run.py make --series grandma-tales
```
In ~30 seconds you get the script and all voices, then it pauses:
```
⏸ 20261109-0930 needs visuals for shot(s) [1, 2, 3, 4, 5, 6]
   1. open  output/jobs/20261109-0930/FLOW_PACK.html
   2. save images/clips into  output/jobs/20261109-0930/inbox
   3. run   python run.py finish 20261109-0930
```

## 3. Open FLOW_PACK.html and make the visuals

The page lists the cast and every shot, with **Copy** buttons:

1. Go to **Google Flow** (labs.google/fx/tools/flow) or any free image site.
2. **Characters (first time only):** copy the design prompt, generate, save into the inbox as `char_dadi.png`, `char_kabir.png`…
   From then on that image is the character's official look, shown in every future pack.
3. **Each shot:** attach the listed character images as references, paste the image prompt, pick **9:16**, save as `01.png`, `02.png`…
4. **★ shots:** if you have free video credits, turn that image into a clip with the video prompt and save as `01.mp4`.
5. Run `python run.py finish <id>`.

Inbox naming rules: the **first number** in the file name is the shot (`03.png`, `shot_03.jpg`, `Flow_03.mp4` all work).
`.png/.jpg/.webp` = still image (animated automatically). `.mp4/.mov/.webm` = clip (used as-is; preferred if both exist;
short clips are slowed slightly instead of freezing; landscape clips get centre-cropped).

`python run.py pack <id>` refreshes the page (✓ marks, thumbnails) as you add files.

## 4. Review and publish

```bash
python run.py list
python run.py approve <id>
python run.py reject  <id> --note "weak ending"
python run.py redo    <id> --shots 3        # moves shot 3's file aside so you can make a new one
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
python run.py finish <id>      →   python run.py approve <id>   →   python run.py publish --approved
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
run.py                  CLI: make, finish, pack, cast, series, ideas, voices, list, approve, redo, publish
config.yaml             providers, series, voices, style, captions
characters/<id>/        character.yaml + front.png (official look)
series_memory/          episode summaries per series
pipeline/llm.py         Gemini (free) / Claude
pipeline/writer.py      cast + dialogue + shot list, genre rotation, memory
pipeline/voice.py       Edge (free) / ElevenLabs, one voice per speaker, word timings
pipeline/flowpack.py    FLOW_PACK.html, inbox, animated stills, clip fitting
pipeline/visuals.py     paid automatic visuals (fal.ai: Nano Banana + Kling 3 elements)
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
