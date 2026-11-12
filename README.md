# hampi-translate: offline voice translator for phone-mode amateur radio

Concept by David P. Eisenhardt, Jr. (W4DPE).

The idea came from a Discord thread where David described the amount of AI
help he would accept on phone: something that runs locally, on prebuilt
libraries, at the wattage of a Pi. No large language model is used. Three
small single-purpose models do the work, one each for speech to text,
translation and the voice.

Speak English into a headset; a Raspberry Pi transmits it in Italian,
Japanese or any of 29 languages, and translates the reply into your
headphones. Speech recognition (whisper.cpp), translation (Argos Translate
packs on CTranslate2) and the voice (Piper; Open JTalk for Japanese) all run
on the Pi. No internet is needed after the one-time install.

- Callsigns, signal reports, Q-codes, grid squares and frequencies pass
  through untranslated.
- The radio is keyed only after your own push-to-talk press and a confirming
  press; your station ID goes out in English.
- Project page: <https://k4dia.com/projects/radio-translator/>
- Overview page: [docs/translator.html](docs/translator.html)
- Full guide: [payload/configs/TRANSLATOR.md](payload/configs/TRANSLATOR.md)
- Reviewer notes: [docs/TRANSLATOR-REVIEW.md](docs/TRANSLATOR-REVIEW.md)

## Install (Raspberry Pi OS Bookworm, 64-bit)

    sudo ./scripts/install-translator.sh        # English <-> Italian
    sudo ./scripts/install-translator.sh --langs "ja es"
    hampi-translate check
    hampi-translate run --no-tx                 # practice; never keys the radio

Where the tool or the guide says `sudo rfpi-translator-install`, that is this
same script under the name the RF Pi suite installs it by. From a checkout,
run `sudo ./scripts/install-translator.sh` with the same options.

## Tests

    pip install numpy pytest
    python3 -m pytest tests -q

## Status

Prototype. 105 automated tests pass and the tool has been run against real
whisper.cpp, CTranslate2, Open JTalk and Hamlib binaries, but it has not yet
been run on a Raspberry Pi with the real models. Wait times in the docs are
estimates.

## License and credit

MIT. See [LICENSE](LICENSE). The concept is David P. Eisenhardt, Jr.'s
(W4DPE); the build is Tony Pelfanio's (K4DIA). The engines and models it
drives are separate works under their own licenses, described in the guide
under "Where the models came from". The MIT license covers this project's own
code and documents, not those engines and models. On the air, you are the
control operator and your regulator's rules apply.

## Review and problems

Reviewer notes are in [docs/TRANSLATOR-REVIEW.md](docs/TRANSLATOR-REVIEW.md).
Open an issue for a bug, or start a thread in the
[K4DIA discussions](https://github.com/K4DIA/GitHub.io/discussions) for
anything else.
