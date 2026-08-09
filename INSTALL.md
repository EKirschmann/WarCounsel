# Installing the WarCounsel — the plain-language guide

Written for people who have never installed a program from a ZIP file.
You do NOT need git, GitHub knowledge, or anything a programmer uses.

There are two ways to install, and the quick one takes under a minute —
read the table below before you download anything.

**Before you start, you need:**
- Windows 10 or 11
- EverQuest Legends installed (and run at least once)
- About 100 MB free for the single .exe, or 1 GB for the full install

The companion is passive — it only **reads** your combat log. It never
touches game files, never injects, never automates anything in-game.

---

> **On a Mac or Linux?** Both options below are Windows-only. Skip to
> [Mac and Linux](#mac-and-linux) at the end of this guide.

## Which download do I want?

Three, and **most people want the first one.**

| | **The single .exe** | **The OCR build** | **The full install** |
|---|---|---|---|
| What you download | one file, about 44 MB | a ZIP, about five times bigger | a ZIP you unpack and set up |
| Do I need anything else first? | **no** | **no** | Python and Node (the installer offers to fetch them) |
| How long | under a minute | a few minutes | about ten minutes |
| Live HUD, damage meter, overlay, maps | yes | yes | yes |
| Spell/gear advice | yes — built-in, or plug in an AI model | same | same |
| Reads your position off the screen | no | **yes** | yes |

**Take the single .exe** and follow Option A. The only thing it gives up is
reading your position off the screen — and your position still updates every
time you type `/loc`, so this matters less than it sounds.

**Only if you want that screen reading:** download `WarCounsel-OCR.zip`
instead, unzip it anywhere, and run the `WarCounsel.exe` inside. It is the
same app; the difference is entirely the image-recognition packages, which
weigh around 200 MB on their own. They are a separate download precisely so
that everyone else's copy stays small and starts quickly. Everything in
Option A below applies to it too — the only change is that you unzip a
folder first and keep the exe inside it.

---

## Option A — the single .exe

### A1. Download it

1. Open <https://github.com/EKirschmann/WarCounsel/releases> in your
   browser.
2. Under the newest release, click **WarCounsel.exe**.
3. Put it wherever you like — Desktop is fine. It makes a `data` folder next
   to itself, so a folder of its own (say `Documents\WarCounsel`) keeps
   things tidy.

> **Avoid `C:\Program Files`.** Windows makes that folder read-only for
> normal programs. The app copes — it puts its data in your AppData folder
> instead — but the tidy "everything in one place" setup is lost.

### A2. Windows will warn you. This is expected.

The file is **unsigned** — code-signing certificates cost hundreds of
dollars a year, and this is a free hobby project — so Windows does not
recognise the publisher. You will see a blue box: *"Windows protected your PC"*.

To run it anyway:

1. Click **More info** (small link in the blue box).
2. Click **Run anyway**.

Your antivirus may also grumble. Programs built this way (a Python app
packed into one file) get flagged by pattern-matching scanners fairly
often; it is a known false positive for this kind of build, not a sign of
anything specific to this app.

**Seen in the wild:** Windows Defender quarantined v2.4.0 as
`Trojan:Win32/Wacatac.B!ml`, and the GitHub source `.zip` as
`Trojan:Script/Wacatac.B!ml`. The `!ml` suffix means the verdict came from
Defender's machine-learning model rather than a signature — that is the
category with the highest false-positive rate, and it is corrected
server-side without any change to the file. Both cleared on their own
after a signature update, with no change to the app.

If you hit this, **update your definitions first** — an elevated
PowerShell running `Update-MpSignature`, or Windows Security ▸ Virus &
threat protection ▸ Check for updates — and try again. If it still fires,
please open an issue with the exact detection name from Windows Security ▸
Protection history; that string is the only thing Microsoft can act on.

**If you would rather verify than trust:** every release is built from the
public source in this repository, and you can upload the file to
<https://www.virustotal.com> for a second opinion before running it. You
can also build it yourself — `build_exe.bat` in the source tree produces
exactly this file.

### A3. First run

Double-click **WarCounsel.exe**. The first launch takes a few seconds
(the one-file build unpacks itself each time it starts), then a window
opens with the dashboard.

It should find your game on its own — it reads the install location from
the Windows registry. You will know it worked when your character's name
appears at the top left.

**Checkpoint:** character name and level showing, top left. If it says
`—` instead, go to A4.

### A4. If it did not find your game

Click the **gear icon** in the top-right corner of the window.

1. In **Game folder**, type or paste the folder EverQuest Legends is
   installed in (the folder that contains a `Logs` folder).
2. Click **Test**. It will tell you either how many character logs it found,
   or what is wrong.
3. Click **Save**.

If Test says *"no eqlog files yet"*, logging is off in the game — see
**Step 3** further down, then click Test again.

### A5. Where its files live

Everything the app creates sits in a `data` folder next to the .exe:
your session history, settings, alert rules, and any map geometry it mined
from the game files. Nothing else on your PC is touched.

(If you put the .exe somewhere Windows will not let programs write, it uses
`%LOCALAPPDATA%\WarCounsel\data` instead. The gear panel always shows the
folder it actually chose.)

### A6. Updating

Download the newer **WarCounsel.exe** and replace the old one. Your `data`
folder is left alone, so sessions, settings, and maps survive. The version
number in the top-left corner of the app tells you when a newer release is
out — click it to check.

### A7. Uninstalling

Delete `WarCounsel.exe` and its `data` folder. That is the whole
uninstall — nothing was written to the registry, and nothing was installed
anywhere else.

### Using an AI advisor (optional)

Out of the box, spell and gear advice comes from the built-in advisor: it
reads the wiki and your own exports, costs nothing, and answers instantly.

If you would rather have an AI write the counsel, open the **gear** and
pick a model under **Advisor model**:

- **OpenAI** — paste an API key from <https://platform.openai.com>. A
  consult costs a few cents.
- **Local — LM Studio** — free and private, but you need
  [LM Studio](https://lmstudio.ai) running with a model loaded.
- **Custom** — any OpenAI-compatible endpoint (Groq, OpenRouter, and
  friends; several have free tiers).

Your key is saved in `secrets.json` in the `data` folder, on your PC only,
and is never shown again once saved — the panel just remembers that one is
there. Clear it any time with the **Clear** button.

### The one thing the .exe does not do

**Reading your position off the screen (OCR).** Your position still updates
whenever you type `/loc` in-game, and the maps, route finder, and 3D view
all work normally. Everything else — HUD, damage meter, timers, alerts,
the in-game overlay, session history, spell-set writing — is exactly the
same app as the full install.

If you do want it, you have two options and neither needs Python:
**`WarCounsel-OCR.zip`** from the same releases page is this exact app with
screen reading built in, or do the full install below. Point either at the
same folder and your data and settings carry over — the `data` folder is
shared, so switching costs you nothing.

---

## Option B — the full install

### Step 1 — Download and unzip

1. Open <https://github.com/EKirschmann/WarCounsel/releases> in your
   browser.
2. Under the newest version (the one at the top), click
   **Source code (zip)** to download it.
3. Open your Downloads folder, **right-click the ZIP → Extract All… →
   Extract**. Put it somewhere easy, like `Documents\WarCounsel`.

> ⚠ **The one mistake everyone makes:** double-clicking INTO the ZIP
> without extracting first. Nothing works from inside a ZIP. If your
> folder path starts with something like `Downloads\WarCounsel.zip\`,
> you are inside the ZIP — go back and use **Extract All**.

**You'll know it worked when:** you have a normal folder containing
files like `install_companion.bat` and `README.md`.

### Step 2 — Run the installer

1. In that folder, double-click **install_companion.bat**.
   - If Windows shows a blue **"Windows protected your PC"** box, click
     **More info → Run anyway**. That warning appears for any script
     Windows hasn't seen before; this one is plain text you can open in
     Notepad and read.
2. A black window opens and stays open. If Python or Node.js are
   missing, it **offers to install them for you — just press Y** and
   wait. (No winget on your PC? Install Python from
   <https://www.python.org/downloads/> — **tick "Add python.exe to
   PATH"** on the first screen — and the LTS from <https://nodejs.org/>,
   then run the installer again.)
3. After a few minutes of progress bars, a short wizard asks:
   - **Your game folder** — it finds this by itself, even custom
     installs (it reads the game's own registry entry, then scans every
     drive). Press **Enter** to accept what it found. You should never
     need to type a path.
   - **Map pack** — press **y** to download the community maps.
   - **Counsel model** — press **Enter** for **None**. Everything works
     without one, and you can pick a model later inside the app.
4. When it asks to launch — press **Enter**. A browser tab opens with
   your HUD.

**You'll know it worked when:** the browser shows the dark-gold EQL
Companion page (it may say "waiting" — that's normal until Step 3).

---

## Step 3 — In the game (once per character)

*(This applies to both installs — the .exe needs it too.)*

Type these two lines in the EQL chat box:

    /log on
    /who

That's all the companion needs. The HUD fills in as you play.

**For the Advisor tab** (optional but worth it), also type:

    /outputfile spellbook
    /outputfile inventory
    /outputfile missingspells
    /alternateadv list

then press **check exports** in the app's Advisor tab.

**You'll know it worked when:** killing one mob makes rows appear in
the War Ledger within a second.

## Day to day

- **Start it:** double-click **WarCounsel.exe** (Option A) or
  **start_companion.bat** (Option B). Right-click → Send to → Desktop to
  make a shortcut either way.
- **Settings:** the **gear** in the top-right corner — game folder, and
  which advisor model to use. The **Test** button next to the game folder
  tells you exactly what it found, instead of leaving you guessing.
- **Playing in a group?** Everyone's damage shows in the encounter panel,
  pets on their own line. If a groupmate runs this too, their "You" number
  and your number for them should agree — handy for working out who needs
  what.
- **The overlay** (in-game meter): press the **Overlay** button in the
  app header. Scroll Lock ON lets you move/adjust it; OFF makes clicks
  pass through to the game.
- **Overlay shortcuts** work from inside the game — you never have to click
  the overlay or alt-tab:

  | Keys | Does |
  |---|---|
  | `Ctrl+Alt+O` | Show / hide the overlay |
  | `Ctrl+Alt+C` | Compact mode (one small line) |
  | `Ctrl+Alt+↑ / ↓` | More / less see-through |
  | `Ctrl+Alt+X` | Make it clickable without touching Scroll Lock |

- **Tray icon:** the overlay adds an icon near the clock — right-click it for
  the same options plus **Reset position**, which rescues an overlay dragged
  off-screen. Windows 11 hides new tray icons in the `^` overflow by default;
  drag it onto the taskbar to keep it visible.
- **Updates:** the version number in the app header shows a badge when a
  new version exists. Using the .exe, download the new one and replace the
  old file. Using the full install, double-click
  **update_companion.bat**. Either way your settings and history survive.
- **Alerts:** edit `tracked_rules.json` in your `data` folder with Notepad
  to get a chime when a rare item drops (the file has an example to copy).
  The gear panel shows where that folder is.

## If something goes wrong

| What you see | What to do |
|---|---|
| "python is not recognized" | Press **Y** when the installer offers Python — or install it yourself with **Add python.exe to PATH** ticked, then re-run the installer |
| **"'pip' is not recognized"**, or Python "is installed" but nothing works | Windows ships a fake `python.exe` — a Microsoft Store shortcut that does nothing and reports success, which is why this looks so strange. The installer now sees through it and finds your real Python (including Anaconda/Miniconda) by itself, so **re-run install_companion.bat**. If you would rather clear it out: Settings → Apps → **Advanced app settings** → **App execution aliases**, switch **python.exe** and **python3.exe** off |
| "winget is not recognized" | Your Windows is older — install Python and Node.js manually from the links in Step 2.2, then re-run |
| Nothing happens on double-click | You're inside the ZIP — do Step 1.3 (**Extract All**) first |
| The wizard can't find the game | Only happens on very unusual setups: find the folder containing `eqgame.exe` (right-click your desktop EQL shortcut → Open file location), copy the address bar, paste it into the wizard |
| App opens but everything says "waiting" | Type `/log on` in the game — the companion is blind without the log |
| It worked yesterday, empty today | The game turns logging off sometimes — type `/log on` again. The Vitals panel reminds you when the log goes quiet |
| "Windows protected your PC" (blue box) | Expected for the .exe — it is unsigned. **More info** → **Run anyway**. See A2 |
| Antivirus quarantines something | Restore it and add it to exclusions. The full install is plain readable Python/JavaScript; the .exe is a packed Python build, which scanners flag by pattern fairly often |
| The .exe starts and nothing appears | Open the `data` folder next to it and read the end of `companion.log` — it records exactly what failed |
| Something else (full install) | Close the black window, run **start_companion.bat** again, and read the last lines it prints — they usually say exactly what's missing |

---

## Mac and Linux

EverQuest Legends has no Mac or Linux version, so you are already running
it through **Wine** — CrossOver, Whisky or osxEQL on a Mac; Lutris,
Bottles or plain Wine on Linux. Get the game working that way first;
those projects have their own guides and this one cannot help with them.

Once the game runs, WarCounsel is three commands. It reads your combat log
straight off the disk — Wine is not involved on our side at all.

**1. Install Python and Node**, if you do not have them.

```bash
# macOS, with Homebrew
brew install python node

# Debian / Ubuntu
sudo apt install python3 python3-venv nodejs npm
```

**2. Download and start it.**

```bash
git clone https://github.com/EKirschmann/WarCounsel.git
cd WarCounsel
./start_companion.sh
```

The first run takes a couple of minutes while it fetches what it needs.
After that it opens **http://localhost:3000** by itself.

**3. In the game, type `/log on` once** — then the commands in the table
under [Day to day](#day-to-day), which are the same on every platform.

### If it cannot find your game

It looks in the usual places automatically. If yours is somewhere else,
tell it where — the folder is the one containing `eqclient.ini`:

```bash
EQL_GAME_DIR="/full/path/to/EverQuest Legends" ./start_companion.sh
```

Inside a bottle that path usually ends
`.../drive_c/users/Public/Daybreak Game Company/Installed Games/EverQuest Legends`.

### Two things are missing here

**The in-game overlay does not run.** It is built on Windows-only
plumbing — click-through windows, global hotkeys, a tray icon — and macOS
will not reliably draw over a fullscreen Wine game regardless. **Play
windowed and put the browser next to the game**; that is how it is meant
to be used on these platforms.

**Automatic position tracking does not run** either, because it works by
reading pixels off the screen. Typing `/loc` still puts you on the map.

Everything else is identical: the live HUD, the damage meter, encounter
breakdowns, both map views, the Advisor and session history.

### It did not work

Open an issue at
<https://github.com/EKirschmann/WarCounsel/issues> with your platform, how
you run the game (CrossOver, Lutris, …) and the path to your game folder.
Mac and Linux support is new and untested on real hardware, so a bad path
is the most likely cause and the easiest to fix.
