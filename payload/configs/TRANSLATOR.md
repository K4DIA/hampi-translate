# RF π offline voice translator (`hampi-translate`)

*Concept by David P. Eisenhardt, Jr. (W4DPE): a local, low-power translator that makes
phone-mode operating across languages a real accessory, with no internet
and no phone held up to a mic.*

Speak English into your headset; the Pi transmits Italian (or another
language). The other station answers in Italian; you hear English in your
headphones and read both on screen. Everything runs on the Pi.

```
 TRANSMIT  you ─▶ headset mic ─▶ speech-to-text ─▶ translate ─▶ text-to-speech ─▶ radio
           (local PTT)            whisper.cpp       EN → IT       Piper voice      (Pi keys PTT)
                                       └─ on screen: what you said + what will be sent ─┘
 RECEIVE   radio ─▶ squelch/segment ─▶ speech-to-text ─▶ translate ─▶ text-to-speech ─▶ headphones
                                        (IT)              IT → EN                       + transcript
```

Why it works on a Pi: phone-mode radio is half-duplex. You talk, say "over",
and the other station waits, so the translator never translates while you
speak. It records the whole over, translates it, then keys up. A few seconds
of processing just looks like a slow "over".

## What you need

| Part | Notes |
| --- | --- |
| Raspberry Pi 4B (4 GB+) or Pi 5 | Pi 4 works; Pi 5 roughly halves the wait. 8 GB not required (pipeline uses ~1–1.5 GB) |
| Cooling | Fan case on a Pi 4, Active Cooler on a Pi 5 |
| USB radio interface | Digirig, SignaLink, or any CM108-based card: clean audio to and from the rig |
| Headset | Keeps translated receive audio out of your mic |
| Local PTT | Keyboard: Enter to start, Enter to stop. Or a footswitch from GPIO27 (pin 13) to GND, hold to talk (`LOCAL_PTT=gpio`) |
| Radio PTT | CAT through `rigctld` (already on RF π), RTS/DTR on the interface's serial port, a GPIO, or VOX |

## Install (once, needs internet)

```bash
sudo ./scripts/install-translator.sh  # from a checkout of this project
# on a Pi that runs the RF Pi suite the same script is installed as:
sudo rfpi-translator-install          # English <-> Italian
sudo rfpi-translator-install --langs "it es ja"   # more partner languages
sudo rfpi-translator-install --whisper small-q5_1   # Pi 5: more accurate speech recognition
```

That builds whisper.cpp (~15 min on a Pi 4) and downloads ~350 MB: the
Python engines, a Whisper model, one Argos Translate language pack per
direction, and a voice per language. It starts `hampi-whisper`, a
localhost-only service that keeps the speech model loaded (~400 MB RAM).
After this, nothing needs the internet.

Running it again is safe: it keeps your settings (model, voices, partner
language) unless you pass `--whisper` or `--langs`, and retries anything
that failed.

## Languages

English plus 29 partner languages work end to end: each has an Argos
Translate pack in both directions with English, Whisper speech recognition,
an offline voice, and a spoken disclosure line.

| Code | Language | Voice | Code | Language | Voice |
| --- | --- | --- | --- | --- | --- |
| ar | Arabic | ar_JO-kareem-medium | lv | Latvian | lv_LV-aivars-medium |
| ca | Catalan | ca_ES-upc_ona-medium | nb | Norwegian | no_NO-talesyntese-medium |
| cs | Czech | cs_CZ-jirka-medium | nl | Dutch | nl_NL-pim-medium |
| da | Danish | da_DK-talesyntese-medium | pl | Polish | pl_PL-gosia-medium |
| de | German | de_DE-thorsten-medium | pt | Portuguese | pt_BR-faber-medium |
| el | Greek | el_GR-rapunzelina-low | ro | Romanian | ro_RO-mihai-medium |
| es | Spanish | es_ES-davefx-medium | ru | Russian | ru_RU-irina-medium |
| fa | Persian | fa_IR-amir-medium | sk | Slovak | sk_SK-lili-medium |
| fi | Finnish | fi_FI-harri-medium | sl | Slovenian | sl_SI-artur-medium |
| fr | French | fr_FR-siwis-medium | sv | Swedish | sv_SE-nst-medium |
| hi | Hindi | hi_IN-pratham-medium | sw | Swahili | sw_CD-lanfrica-medium |
| hu | Hungarian | hu_HU-anna-medium | tr | Turkish | tr_TR-dfki-medium |
| it | Italian | it_IT-riccardo-x_low | uk | Ukrainian | uk_UA-ukrainian_tts-medium |
| ja | Japanese | Open JTalk (nitech atr503) | vi | Vietnamese | vi_VN-vais1000-medium |
|  |  |  | zh | Chinese | zh_CN-huayan-medium |

- Install any of them: `sudo rfpi-translator-install --langs "ja de"`. The
  first language listed becomes `THEIR_LANG`; change it in translate.conf to
  switch. Each language adds roughly 150 MB.
- **Japanese** has no Piper voice, so it uses Open JTalk from the Debian
  archive. Callsign phonetics and Q-code letters are spoken in katakana
  (キロ 1 アルファ…), because Open JTalk spells Latin words letter by letter.
- In the other non-Latin languages, callsign phonetics are said in the voice's
  own pronunciation of "Kilo", "Alfa", and so on.
- The disclosure lines and decimal-point words were written for this tool;
  have a native speaker check them before going on the air.
- Speech recognition on less common languages (Swahili, Latvian, Slovenian)
  is noticeably weaker with the `base` Whisper model; use `small` on a Pi 5.
- Argos also has packs for Korean, Thai, Hebrew, Indonesian and others, but
  there's no offline voice for them yet, so they aren't listed.

## Set up

1. Callsign: `sudo nano /etc/hampi/station.conf`. The translator refuses to
   transmit as `N0CALL`.
2. Audio and PTT: `sudo nano /etc/hampi/translate.conf`. `hampi-translate
   devices` lists sound cards; use part of the name (`USB Audio`).
3. CAT PTT: start rigctld with PTT enabled, e.g.
   `rigctld -m <model> -r /dev/ttyUSB0 -P RIG &` (or `-P RTS -p /dev/ttyUSB0`
   for a Digirig's RTS line).
4. `hampi-translate check` until every line says OK.
5. Set the TX level like any digital mode: `RADIO_GAIN` in translate.conf,
   no ALC action.

## Operate

```bash
hampi-translate run --no-tx    # practice: translations play in your headphones, radio never keyed
hampi-translate run            # on the air
hampi-translate text "Good morning, you are five nine"   # try the translation alone
hampi-translate bench          # measure the wait on this board (bench my-over.wav for your own 10 s recording)
```

Or use **Offline voice translator** in `hampi-menu`.

In `run`:

- **Talk**: press Enter, speak one over, press Enter again. With a footswitch
  (`LOCAL_PTT=gpio`), hold it while you talk.
- **Review** (`REVIEW=1`, default): the screen shows what you said and the
  translation. Press Enter (or `y`) to transmit, or tap the footswitch.
  Anything else, `n`, a 1.5 s footswitch hold, or no answer within 20 s
  (`REVIEW_TIMEOUT`) discards it. Keys pressed before the prompt appears
  don't count. Nothing is keyed until you confirm.
- **Disclosure** (`DISCLOSE=1`): each over starts with "Trasmissione tradotta
  automaticamente." so the other station knows why the voice is synthetic.
- **Station ID**: your callsign goes out in English, in ITU phonetics (or your
  own recorded `ID_WAV`), at the end of your first over, and at the end of
  any over that would otherwise finish more than 10 minutes after the last
  ID. Nothing is sent on a timer: if you go quiet, no ID goes out. Type `i`
  then Enter (or press the optional `ID_GPIO` button) to send your ID on
  its own. When you quit with `q` after transmitting, it offers a final ID
  to end the contact; that also needs a confirming press.
- **Receive**: incoming overs are transcribed, translated and played in your
  headphones, with the original Italian and the English on screen. Receive is
  muted while you transmit. It is off in `--no-tx` practice mode.
- **Quit**: `q` then Enter, or Ctrl-C (footswitch mode: Ctrl-C).
- If one over fails (a sound device or model error), the error is shown,
  nothing more is sent, and the session carries on.

## Keying policy

As everywhere in RF π, keying is a physical act. The transmitter is keyed only
as the direct result of your own PTT press, and with `REVIEW=1` only after a
second confirming press. The ID key (`i`) is the one exception to the second
press: it sends your callsign directly. No timer, network request or
dashboard button can key the radio.

Each transmission is limited to `MAX_TX_SEC` (90 s) of audio; a long message
is cut to fit, the station ID never is. The radio is unkeyed on any error,
on Ctrl-C, and when the program is killed or its SSH session drops. A
watchdog also unkeys if the sound device stalls mid-over. Set your rig's own
time-out timer as well: it is the only protection if the Pi itself loses
power or crashes while keyed.

## Ham jargon is never "translated"

Before translation these are swapped for placeholders, then put back exactly:

| Said | Screen shows | Voice says |
| --- | --- | --- |
| K1ABC, or "kilo one alfa bravo charlie" | K1ABC | Kilo 1 Alfa Bravo Charlie |
| five nine, 5 by 9, "you're 59" | 5 9 | 5 9 (in the voice's language) |
| QTH, QSL, QRZ?, CQ | QTH | Q T H |
| FN42hn, or "my grid is FN42" | FN42hn | Foxtrot November 4 2 Hotel November |
| DL/K4DIA, K4DIA/P | DL/K4DIA | Delta Lima stroke Kilo 4 Delta India Alfa |
| 7,150 kHz | 7150 kHz | 7150 kilohertz |
| 146.520 MHz | 146.520 MHz | 146 virgola 520 megahertz |
| 73, 88 | 73 | 73 |
| Names in `/etc/hampi/translate-glossary.txt` | unchanged | unchanged |

To avoid mangling ordinary speech, some forms need a cue:

- A bare two-digit number is a signal report only after a word like "you're",
  "signal" or "report", and never before a unit ("59 watts", "35 contacts").
  "Five nine" and "five by nine" always count; "four by seven" needs the cue.
- A four-character grid (FN42) needs "grid" or "locator" before it; six
  characters (FN42hn) are recognised on their own.
- A spelled-out call must be all phonetic words ("kilo four delta...") or all
  single letters ("K 4 D I A"), not a mix.

If the translation model drops a placeholder, the tool translates the plain
words between the jargon one piece at a time and splices the jargon back in
order, and flags that over on screen as "jargon spliced: check it".

## What to expect: Pi 4 vs Pi 5

Estimated dead air after a 10-second over, from published reports and the
Pi 5's rated 2–3× CPU speed-up. **Not measured yet.** Run `hampi-translate
bench` and record real numbers below.

| Board | Speech model | Estimated wait |
| --- | --- | --- |
| Pi 4B | base (q5_1), default voices | about 5–12 s |
| Pi 5 | base or small (q5_1), default voices | about 3–8 s |

The default voices are medium quality, except Italian (x_low) and Greek
(low). A lower-quality Piper voice is faster: download one and point
`VOICE_<LANG>` at it.

Measured (fill in from `hampi-translate bench`):

| Board | Model | STT | Translate | TTS | Dead air | CPU temp | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

Settings that matter on a Pi 4: 64-bit Raspberry Pi OS, `STT=server` (keeps
the model loaded), greedy decoding (already set), `TRANSLATE_BEAM=2` or `1`,
`x_low`/`low` Piper voices where you install them, and a fan.

Power: a Pi 4 draws about 3 W idle and 5–6.5 W flat out; a Pi 5 about 3 W
idle and up to 11.5 W. The translator idles between overs and spikes for a few
seconds, so the average stays near idle. The Pi can't measure its own draw;
use a USB-C inline meter.

## Where the models came from

The translator only converts what you said. The only words it adds are the
disclosure line and your station ID.
What each model learned from is still worth knowing:

- **Whisper** (speech to text): MIT-licensed weights, trained by OpenAI on a
  large amount of audio collected from the web.
- **Argos Translate packs** (translation): mostly trained on the OPUS
  collection. That includes public records (EU Parliament, UN) and volunteer
  sentences (Tatoeba), but often also film subtitles (OpenSubtitles) and
  web-crawled text. Each pack's `README.md` under
  `/opt/hampi/translate/argos/` lists its data; `fetch-packs` prints the path.
- **Piper voices** (text to speech): each voice has a `MODEL_CARD` next to it
  in `/opt/hampi/translate/voices/`. Many Piper voices were fine-tuned from
  the "lessac" voice, whose recordings carry a non-commercial research
  license. `it_IT-riccardo-x_low` is reported to be trained from scratch; the
  German `thorsten` voice uses recordings its author donated to the public
  domain. Read the card before relying on a voice.
- **Open JTalk** (Japanese voice): BSD-licensed engine; the nitech atr503
  voice is CC BY 3.0 (Nagoya Institute of Technology), per its Debian
  copyright file.

The engines are separate open-source programs (see
`/etc/hampi/OPEN-SOURCE.txt`). Piper is GPL-3.0 and runs as its own process.

## Known limits

- Built and tested off-Pi: 105 automated tests plus runs against real
  whisper.cpp, CTranslate2, Open JTalk and Hamlib binaries. The audio
  playback and GPIO code paths have only been tested against fakes. It has **not yet been run on a
  Pi with the real models**. `bench` and a practice session come first.
- Weak or fading HF audio will transcribe poorly. Strong FM simplex and
  repeater signals work far better than DX on 20 m.
- No streaming yet: recognition starts after you release PTT.
- Argos packs that use a BPE tokenizer instead of SentencePiece aren't
  supported (the tool says so).
- There is no web or dashboard interface yet: `run` is a terminal program
  (local screen or SSH). It writes its state and transcript to
  `/var/lib/hampi/translate-status.json` for a future widget.
- Callsigns with a digit-letter-letter-digit prefix (3DA0XX) aren't
  recognised, and such a station callsign is refused.
- US rules are built in (97.119 English ID). Check your own regulator's
  rules elsewhere.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `whisper-server` !! in check | `sudo systemctl status hampi-whisper`; the model path in translate.conf must exist |
| `rigctld PTT ... RPRT -11` | rigctld wasn't started with PTT: add `-P RIG` (CAT) or `-P RTS -p <port>` |
| "No translation pack for it->en" | `sudo rfpi-translator-install --langs it` |
| Translations come out repeating or empty | Try `TRANSLATE_BEAM=4`, speak in shorter sentences |
| Receive triggers on noise | Raise `RX_THRESHOLD_DB` (e.g. -32) or tighten squelch |
| Receive misses the start of overs | Lower `RX_THRESHOLD_DB`; increase `RX_HANG_MS` for slow talkers |
| Your own transmission gets translated back | It shouldn't (receive is muted while keyed); check that `RADIO_IN` isn't your headset |
