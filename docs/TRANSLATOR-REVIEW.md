# Review brief: `hampi-translate` (offline voice translator)

For reviewers of the offline voice translator change. Concept by
David P. Eisenhardt, Jr. (W4DPE). User guide:
[`payload/configs/TRANSLATOR.md`](../payload/configs/TRANSLATOR.md).

## What it is

An optional tool, written for RF π and able to run on its own. The operator speaks English into a headset; the Pi
transcribes it (whisper.cpp), translates it (Argos Translate packs run on
CTranslate2), synthesizes the other language (Piper; Open JTalk for
Japanese), keys the radio and plays it. Incoming overs go the other way into
the headphones. Everything runs on the Pi with no internet after install.
English plus 29 partner languages.

It installs with `scripts/install-translator.sh` and touches nothing else on
the Pi. Inside RF π the same script is installed as `rfpi-translator-install`.

## Where to look

| File | What | Review priority |
| --- | --- | --- |
| `payload/tools/hampi-translate` | The tool (one Python file, stdlib + numpy; engines are separate processes or lazily imported) | High |
| `tests/test_hampi_translate.py` | 105 tests; models, sound cards and radios are faked | High |
| `scripts/install-translator.sh` | Engines, whisper.cpp build, model/voice/pack downloads, service | Medium |
| `payload/systemd/hampi-whisper.service` | Localhost whisper-server that keeps the model loaded | Medium |
| `payload/configs/translate.conf`, `translate-glossary.txt` | Settings template, do-not-translate list | Low |
| `payload/configs/TRANSLATOR.md`, `README.md`, `LICENSE` | Docs and license | Low |
| `.github/workflows/tests.yml` | Runs the tests on Python 3.11 and 3.13 | Low |

Suggested reading order in the tool: `cmd_run` and `_transmit` (the operating
loop), `keyed` and the PTT classes, `KeyboardLocal`/`GpioLocal`, then
`protect`/`restore`/`PhraseTranslator` (jargon), then the engines.

## Run it

```bash
cd hampi-translate
pip install numpy pytest
python3 -m pytest tests -q          # 105 pass, about 10 s, no hardware needed
bash -n scripts/install-translator.sh
```

On a Pi (Raspberry Pi OS Bookworm 64-bit, needs internet once):

```bash
sudo ./scripts/install-translator.sh
hampi-translate check
hampi-translate text "Good morning K1ABC, you are five nine"
hampi-translate bench
hampi-translate run --no-tx         # practice; never keys the radio
```

## Design decisions worth challenging

1. **Keying policy.** The radio keys only after the operator's own PTT press
   and, with `REVIEW=1` (default), a confirming press typed after the
   translation is shown. The `i` ID command keys directly. Is that the right
   line, and should `REVIEW=0` exist at all?
2. **Station ID.** English ITU phonetics appended to the first over and to
   any over that would end past 10 minutes since the last ID; offered again
   on quit. There is no timer, by design (nothing keys without a press). Is
   this adequate for 97.119, and for non-US operators?
3. **Disclosure line** ("machine-translated transmission") spoken before
   every over, in the partner's language. Every over, or first over only?
4. **Jargon guard by regex.** Callsigns, reports, Q-codes, grids and
   frequencies are masked before translation and restored after. Some forms
   need a spoken cue to avoid false positives (see the guide). The trade is
   missed jargon (it gets translated like ordinary words) against mangled
   ordinary speech. Where should that line sit?
5. **No `argostranslate` library.** Packs are run directly on CTranslate2 +
   SentencePiece because the library imports stanza and PyTorch (5.9 GB
   install on x86 vs 199 MB). Cost: we own the sentence splitter and the
   pack-layout handling; BPE-tokenized packs are unsupported.
6. **One file, no package.** Matches the other `hampi-*` tools, at ~1,900
   lines. Split it?
7. **Licensing.** The tool is MIT licensed and drives GPL-3.0 Piper as a
   separate process. Model licenses vary per voice and
   pack (non-commercial terms on some Piper voices). Needs a decision before
   any sale; see "Where the models came from" in the guide.

## Verification done

- 105 unit tests on Python 3.11 and 3.13 (CI runs both).
- Run against real binaries off-Pi: whisper.cpp server and CLI (request and
  response format), a real CTranslate2 model in Argos pack layout, Open JTalk
  synthesis, Hamlib `rigctld` keying and unkeying a dummy rig.
- A real child process killed with SIGTERM mid-transmission sends the unkey.
- The installer run end to end in a container (downloads were blocked there)
  and its settings logic exercised in a sandbox with stubbed system commands.
- Code review of the tool, the installer/integration and the docs against the
  code, with the findings fixed and covered by tests.

## Not verified: please test

- **Never run on a Raspberry Pi with the real models.** The model hosts were
  unreachable from the build environment. Latency figures in the docs are
  estimates; translation quality is unmeasured.
- **Audio playback and capture** (`play`, `record_while`, the receive
  stream) and **GPIO** (`GpioLocal`, `GpioPTT`) are tested only against
  fakes. `play` was rewritten during review to use its own output stream.
- **Serial PTT** line behaviour on a real Digirig/CAT cable.
- The **29 voice download paths** were checked against the piper-voices
  v1.0.0 voice list, not downloaded.
- **Disclosure sentences** in 29 languages were written for this tool and
  need native-speaker review before use on the air.
- systemd unit behaviour (start limits, `EnvironmentFile` parsing) was
  reasoned from documentation, not run.

## Known limits (accepted for now)

- Recognition starts after PTT release (no streaming).
- Weak-signal HF audio will transcribe poorly; no noise reduction stage.
- Sentence splitting is punctuation-based ("Dr." splits a sentence).
- Callsigns like 3DA0XX are not recognised, and refused as a station call.
- No dashboard widget; `run` is a terminal program. It writes
  `/var/lib/hampi/translate-status.json` for a future one.
- If the Pi loses power while keyed, only the rig's own time-out timer helps.

## Suggested on-air acceptance test

1. `bench` on a Pi 4: under 12 s dead air for a 10 s over.
2. `run --no-tx`: callsigns, reports and Q-codes correct in 10 of 10 overs.
3. Into a dummy load: clean audio with no ALC, ID on the first over, unkeys
   every time, including Ctrl-C and `kill` mid-over.
4. Receive a strong FM signal in the partner language.
5. A complete simplex contact with a partner speaking the other language.
