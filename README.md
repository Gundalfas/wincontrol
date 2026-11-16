# wincontrol

**Windows desktop control for AI coding agents** (Claude Code, Codex, Gemini CLI, …) – one small Python CLI.

Screenshots, real mouse and keyboard (unicode typing), **OCR text with click coordinates** and the **UI Automation** element list.
Works with any window, **including inside Remote Desktop (RDP)** where UI Automation sees nothing – the agent reads the screen as text instead of images, which is faster and much cheaper.

```text
wincontrol use "Excel"            # pick the target window (regex on the title)
wincontrol ocr "Save|Total"       # text lines + click coordinates, no image tokens
wincontrol clicktext "Save"       # click by visible text
wincontrol elements Rename        # native controls with exact names (UI Automation)
wincontrol type "Šiauliai 12"     # unicode typing (works through RDP)
wincontrol key ctrl+s
wincontrol snap s1                # screenshot only when the layout is unclear
```

## Why
We compared desktop tools with the same model (Claude Haiku) on Excel, File Explorer and a legacy business app over RDP (70 runs, automatic checks):

| Tool | Success | Median time | Avg cost / task |
|---|---|---|---|
| **wincontrol (OCR)** | **10/10** | **77 s** | **$0.010** |
| wincontrol (screenshots only) | 10/10 | 83 s | $0.011 |
| Windows-MCP | 12/13 | ~110 s | $0.023–0.034 |
| Cua Driver | 9/10 | 180–309 s | $0.036–0.093 |
| agent-desktop | 5/9 | 135–160 s | $0.033–0.040 |

A stress test (15 hard tasks × 3 models – modal dialogs, RDP, SQL client export, unicode text, 100-action endurance) found and fixed tool bugs; after the fixes the models solved 14–15 of 15 tasks.
Most failures came from silent tool errors (“clicked” while a dialog blocked the window), so wincontrol refuses unsafe clicks and says why.

## Install
1. Python 3.10+ on Windows 10/11: `py -3 -m pip install -r requirements.txt`
2. Optional, for non-English letters: [Tesseract 5](https://github.com/UB-Mannheim/tesseract/wiki) + language models from [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) (default languages `lit+eng`, set `DPX_OCR_LANGS=deu+eng` etc.). Without Tesseract only Windows OCR (en-US) is used.
3. Call `wincontrol.cmd` (or `py -3 -X utf8 wincontrol.py`). Tell your agent: *"For Windows apps use `wincontrol --help`."*

## Commands
`windows`, `use`, `start <program|file>`, `snap [--full]`, `zoom`, `ocr ['A|B']`, `clicktext`, `elements ['A|B']`, `clickname`, `click X Y [--double|--right|--zoom]`, `type 'text' | --file f.txt`, `key`, `scroll`, `wait`, `clip` (clipboard text – exact table data, e.g. SQL grid `ctrl+a`, `ctrl+shift+c`).
Coordinates are pixels of the latest `snap` / `ocr` / `elements` image (≤ 1200 px wide). Run `wincontrol --help` for details.

## Safety and parallel agents
- **Visible agent cursor**: a coloured arrow with the agent's name follows the mouse, clicks pulse, typing shows a caption (`DPX_SHOW=0` turns it off; never captured in screenshots).
- **Never clicks blindly**: verifies the window is really in front; refuses if the point is covered by another app's window, or if a modal dialog blocks the window – and names that dialog. After an action it prints a `NOTE` if another window took the front.
- **Several agents at once**: each AI session has its own state (`DPX_SESSION`, or Codex / Claude Code session ids automatically) and mouse/keyboard input goes through one shared lock.
- It moves the **real mouse** – don't use the mouse meanwhile; does not work on a locked screen.

## Tips
- Cheapest loop: `ocr` / `elements` → chain actions in one shell call (`&&`) → `snap` only to verify.
- PowerShell treats `„ “ ”` as string quotes – put such text in a UTF-8 file and use `type --file`.
- Maximize RDP windows before OCR (small windows shrink the text).
- OCR weak spots: `@`→`O`, `0/O`, `1/l/I` – check e-mails, codes and sums with `zoom` or `clip`.
- Settings: `DPX_OCR=0`, `DPX_UIA=0`, `DPX_STATE_DIR`, `DPX_TRACE=<file.tsv>` (per-command timing), `DPX_AGENT=<name>`, `DPX_GLIDE_MS`. (`DPX_` is the tool's original short name.)

## License
MIT
