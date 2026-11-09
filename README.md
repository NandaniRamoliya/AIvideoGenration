# AI Video Generation — Character Story Shorts

Automated pipeline that makes 45–60 s vertical **animated story episodes with recurring characters**:
each character has a fixed design, their own voice, and they talk to each other on screen.
Videos go to a review queue and are uploaded to YouTube Shorts only after you approve them.

```
 Series / genre ─► Episode script ─► Character ─► Voices ─► Keyframes ─► AI video ─► Edit ─► REVIEW ─► YouTube
                  (cast + dialogue)  ref sheets   per char   FROM refs    + elements   captions  (you)   + post kit
     config         Claude            Nano Banana  ElevenLabs Nano Banana  Kling 3      ffmpeg            for IG/TikTok
```

## How characters stay the same in every shot

1. **Character library** — `characters/<id>/character.yaml` holds the name, exact look (outfit + colours), personality and voice.
2. **Reference sheet** — the first time a character is used, it gets a front portrait and a matching side view (`front.png`, `side.png`). Same images forever after.
3. **Keyframes from references** — every shot's starting image is generated *from* the reference images of the characters in that shot.
4. **Kling 3 elements** — the video model also receives each character's reference sheet, so faces and outfits don't drift while they move.
5. **Own voices** — every line is voiced separately (narrator, Dadi, Kabir…), and captions glow in the speaker's colour with a name tag.

Series remember previous episodes (`series_memory/`), so stories continue instead of repeating.

## Included to start

| Series | Cast | Genres |
|---|---|---|
| `grandma-tales` — *Dadi's Midnight Tales* | Dadi (grandmother storyteller), Kabir (9-year-old grandson) | folklore, fantasy, mystery |
| `space-cadets` — *Zara & Bolt* | Zara (teen pilot), Bolt (sarcastic repair robot) | sci-fi, comedy, survival |

Plus **stand-alone stories** in any genre (horror, mystery, myth, urban legend, comedy, time travel, animal tales…) where the writer invents new characters — they're saved to the library, so a good one can come back.

Edit or add series in `config.yaml`; edit or add characters in `characters/`.

---

## 1. Install

Python 3.10+ and ffmpeg.

```powershell
# Windows
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```
Mac: `brew install python ffmpeg` · Linux: `sudo apt install python3-pip ffmpeg`

```bash
git clone https://github.com/NandaniRamoliya/AIvideoGenration.git
cd AIvideoGenration
pip install -r requirements.txt
```

## 2. Free test run (no keys)

```bash
python run.py make --series grandma-tales --mock
```
⚠️ **Mock mode does not make real visuals.** It produces a *storyboard animatic*: placeholder character cards, the shot descriptions as text, and robot voices. It's only for checking that timing, voices and captions work. Real characters and animation need the API keys below.

> Mock runs save placeholder cards as character images; your first real run replaces them with real designs automatically.

## 3. API keys

Copy `.env.example` → `.env`:

| Key | Get it at | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com | episode scripts |
| `ELEVENLABS_API_KEY` | elevenlabs.io → API keys | character voices (paid plan = commercial use) |
| `FAL_KEY` | fal.ai/dashboard/keys | character designs, keyframes, AI video |

Pick voices: `python run.py voices` lists your ElevenLabs voices → paste IDs into `config.yaml > voices` (by type) or into a character's `voice_id`.

## 4. Make episodes

```bash
python run.py make --series grandma-tales            # next episode of Dadi's Midnight Tales
python run.py make --series space-cadets --idea "Bolt falls in love with a vending machine"
python run.py make --count 3                         # 3 stand-alone stories, new characters
python run.py ideas --series grandma-tales           # 10 episode ideas to choose from
```

**First real run:** look at `characters/dadi/front.png` etc. If you don't like a design, change the `look` in `character.yaml` and run `python run.py cast redesign dadi`. Lock the cast **before** making many episodes.

Create your own character:
```bash
python run.py cast new --name "Meera" --voice-type girl \
  --look "12-year-old girl, long black braid with a red ribbon, green kurta, white sneakers, carries a sketchbook" \
  --personality "shy artist, notices everything"
```
Then add `meera` to a series' `cast:` list in `config.yaml`, or create a new series.

## 5. Review and publish

```bash
python run.py list                                  # queue + file paths
python run.py approve <id>
python run.py reject  <id> --note "weak ending"
python run.py redo    <id> --shots 3,5              # regenerate only bad shots
python run.py redo    <id> --shots 3 --prompt "Kabir hides behind Dadi, close-up, scared eyes"
python run.py publish --approved                    # upload approved to YouTube
python run.py publish <id> --at "2026-11-10 18:30"  # scheduled release
```
Each job folder has `final.mp4`, `thumbnail.jpg` and `post_kit.txt` (titles, hashtags, IG/TikTok caption).

### YouTube setup (once)
1. console.cloud.google.com → new project → enable **YouTube Data API v3**.
2. OAuth consent screen → External → add your Gmail as test user.
3. Credentials → OAuth client ID → **Desktop app** → download → save as `secrets/client_secret.json`.
4. `python run.py auth-youtube`.

New projects have a small daily upload quota, and uploads may stay private until Google verifies the app (you can make them public in YouTube Studio). Uploads are marked as AI-generated automatically.

## 6. Daily automation

Creates videos every morning; posting still waits for your approval.

```powershell
# Windows Task Scheduler
schtasks /create /tn "AI Story Episodes" /sc daily /st 07:00 ^
  /tr "cmd /c cd /d C:\path\to\AIvideoGenration && python run.py make --series grandma-tales && python run.py make --count 2 >> output\daily.log 2>&1"
```
```bash
# Mac / Linux cron
0 7 * * * cd /path/to/AIvideoGenration && python3 run.py make --series grandma-tales && python3 run.py make --count 2 >> output/daily.log 2>&1
```

## Cost (estimate, check fal.ai pricing)

| Item | Approx. |
|---|---|
| Script (Claude) | $0.03 |
| New character design (2 images, once per character) | $0.08 |
| 6–9 keyframes (Nano Banana edit) | $0.25–0.35 |
| ~60 s video (Kling 3 Standard, no audio, $0.084/s) | ~$5.00 |
| **Per episode** | **≈ $5.30** + ElevenLabs plan |

Cheaper: lower `story.target_words`, or set `video.model` to a cheaper fal image-to-video model (set `use_elements: false` if that model doesn't support elements).

## Customise (`config.yaml`)

- `visual_style` — "3D animated feature film" by default; try "anime, painterly Ghibli-inspired", "2D storybook illustration", "photorealistic cinematic". Each series can have its own.
- `series` — premise, world, cast, genres.
- `story` — length, number of shots, characters per story, dialogue vs narration, content rules.
- `voices`, `tts` — voice per type, gap between lines.
- `captions` — font, size, colours, name tags, hook title card.

## Project layout

```
run.py                  CLI: make, cast, series, ideas, list, approve, redo, publish …
config.yaml             all settings, series definitions
characters/<id>/        character.yaml + front.png / side.png reference sheet
series_memory/          episode summaries per series (continuity)
pipeline/writer.py      Claude: cast + dialogue + shot list, genre rotation, memory
pipeline/cast.py        character library, reference sheets, uploads
pipeline/voice.py       one voice per speaker, stitched, word timestamps
pipeline/visuals.py     keyframes from references + Kling 3 elements, parallel, resumable
pipeline/captions.py    speaker-coloured word-by-word captions, name tags, hook card
pipeline/assemble.py    ffmpeg edit: timing, captions, music ducking, -14 LUFS
pipeline/youtube.py     upload / schedule
output/jobs/<id>/       everything for one video
```

## Next upgrades (not built yet)
- **Lip-sync**: run each speaking shot through a lip-sync model so mouths match the words.
- **Instagram/TikTok auto-posting** (needs a business account + public video URL).

## Rules
- Original stories and characters only; no real people or copyrighted characters.
- Turn on the platform's "AI-generated" label when posting manually.
- Only use music you have rights to (`assets/music/`).
