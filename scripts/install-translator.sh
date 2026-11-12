#!/bin/bash
#
# Install the engines and models for hampi-translate (RF Pi offline voice
# translator). Needs internet ONCE; after this the translator runs offline.
#
#   sudo ./scripts/install-translator.sh                  # English <-> Italian
#   (installed by setup.sh as: sudo rfpi-translator-install)
#   sudo ./scripts/install-translator.sh --langs "it es ja"  # more partner languages
#   (29 supported: ar ca cs da de el es fa fi fr hi hu it ja lv nb nl pl pt ro
#    ru sk sl sv sw tr uk vi zh -- see TRANSLATOR.md)
#   sudo ./scripts/install-translator.sh --whisper small-q5_1   # Pi 5: more accurate
#
# Downloads ~350 MB (Python engines, base Whisper model, two Argos packs,
# two Piper voices)
# and builds whisper.cpp from source: ~15 min on a Pi 4, ~6 min on a Pi 5.
# Also run by: sudo ./setup.sh --translator. Works on its own too (translator
# only, without the rest of RF Pi): run it straight from a checkout.
#
# Same best-effort style as setup.sh: a failed step is reported at the end
# and re-running the script retries it.

set -u

SHARE=/opt/hampi/translate
MY_LANG=en
CONF=/etc/hampi/translate.conf
LANGS=""
LANGS_SET=0
WHISPER_MODEL=""
WHISPER_SET=0
TARGET_USER="${SUDO_USER:-}"

need_value() { [ $# -ge 2 ] || { echo "$1 needs a value" >&2; exit 1; }; }

while [ $# -gt 0 ]; do
    case "$1" in
        # Accept "it es", "it,es" and stray spaces alike.
        --langs)   need_value "$@"; LANGS=$(echo "$2" | tr ',' ' ' | xargs); LANGS_SET=1; shift ;;
        --whisper) need_value "$@"; WHISPER_MODEL="$2"; WHISPER_SET=1; shift ;;
        --user)    need_value "$@"; TARGET_USER="$2"; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
[ "$LANGS_SET" -eq 0 ] || [ -n "$LANGS" ] || { echo "--langs needs at least one language" >&2; exit 1; }

conf_get() {   # KEY -> current value in translate.conf, if any
    sed -n "s|^$1=||p" "$CONF" 2>/dev/null | head -n1
}

# A plain re-run (to retry a failed step, or to update) keeps what the
# operator already has: the partner language and Whisper model come from
# translate.conf unless --langs / --whisper say otherwise.
if [ "$LANGS_SET" -eq 0 ]; then
    LANGS=$(conf_get THEIR_LANG); LANGS=${LANGS:-it}
fi
if [ "$WHISPER_SET" -eq 0 ]; then
    WHISPER_MODEL=$(conf_get WHISPER_MODEL | sed -n 's|.*/ggml-\(.*\)\.bin$|\1|p')
    WHISPER_MODEL=${WHISPER_MODEL:-base-q5_1}
fi

FAILURES=()
log()  { echo -e "\n==> $*"; }
warn() { echo "WARNING: $*" >&2; }
step() {
    local name="$1"; shift
    log "$name"
    "$@" && return 0
    warn "$name failed - continuing."
    FAILURES+=("$name")
    return 1
}

# One default voice per language, all from the rhasspy/piper-voices v1.0.0
# release (paths checked against its VOICES list). Japanese has no Piper
# voice and uses Open JTalk from Debian instead. Check each MODEL_CARD
# (downloaded alongside) before relying on a voice.
# Format: argos-code|path-in-piper-voices (without .onnx)
VOICES="
en|en/en_US/ljspeech/medium/en_US-ljspeech-medium
ar|ar/ar_JO/kareem/medium/ar_JO-kareem-medium
ca|ca/ca_ES/upc_ona/medium/ca_ES-upc_ona-medium
cs|cs/cs_CZ/jirka/medium/cs_CZ-jirka-medium
da|da/da_DK/talesyntese/medium/da_DK-talesyntese-medium
de|de/de_DE/thorsten/medium/de_DE-thorsten-medium
el|el/el_GR/rapunzelina/low/el_GR-rapunzelina-low
es|es/es_ES/davefx/medium/es_ES-davefx-medium
fa|fa/fa_IR/amir/medium/fa_IR-amir-medium
fi|fi/fi_FI/harri/medium/fi_FI-harri-medium
fr|fr/fr_FR/siwis/medium/fr_FR-siwis-medium
hi|hi/hi_IN/pratham/medium/hi_IN-pratham-medium
hu|hu/hu_HU/anna/medium/hu_HU-anna-medium
it|it/it_IT/riccardo/x_low/it_IT-riccardo-x_low
lv|lv/lv_LV/aivars/medium/lv_LV-aivars-medium
nb|no/no_NO/talesyntese/medium/no_NO-talesyntese-medium
nl|nl/nl_NL/pim/medium/nl_NL-pim-medium
pl|pl/pl_PL/gosia/medium/pl_PL-gosia-medium
pt|pt/pt_BR/faber/medium/pt_BR-faber-medium
ro|ro/ro_RO/mihai/medium/ro_RO-mihai-medium
ru|ru/ru_RU/irina/medium/ru_RU-irina-medium
sk|sk/sk_SK/lili/medium/sk_SK-lili-medium
sl|sl/sl_SI/artur/medium/sl_SI-artur-medium
sv|sv/sv_SE/nst/medium/sv_SE-nst-medium
sw|sw/sw_CD/lanfrica/medium/sw_CD-lanfrica-medium
tr|tr/tr_TR/dfki/medium/tr_TR-dfki-medium
uk|uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium
vi|vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium
zh|zh/zh_CN/huayan/medium/zh_CN-huayan-medium
"
JA_VOICE=/usr/share/hts-voice/nitech-jp-atr503-m001/nitech_jp_atr503_m001.htsvoice
HF=https://huggingface.co

install_deps() {
    apt-get update || warn "apt-get update failed; trying with the existing package lists."
    apt-get install -y --no-install-recommends \
        python3-venv python3-numpy python3-serial python3-gpiozero \
        libportaudio2 libhamlib-utils build-essential cmake git curl || return 1
    install -d "$SHARE"/{models,voices,argos,build}
    [ -x "$SHARE/venv/bin/python3" ] || python3 -m venv --system-site-packages "$SHARE/venv" || return 1
    "$SHARE/venv/bin/pip" install --upgrade pip >/dev/null
    # Translation runs Argos packs on CTranslate2 + SentencePiece directly: the
    # argostranslate library would drag in stanza + PyTorch (hundreds of MB).
    # piper-tts runs as its own process (it is GPL-3.0; RF Pi only calls its CLI).
    "$SHARE/venv/bin/pip" install --upgrade ctranslate2 sentencepiece piper-tts sounddevice
}

build_whisper() {
    local src="$SHARE/build/whisper.cpp"
    if [ -d "$src/.git" ]; then
        git -C "$src" pull --ff-only || return 1
    else
        git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$src" || return 1
    fi
    # GGML_NATIVE=OFF: no -mcpu=native, so a binary built on a Pi 5 (or in an
    # image build on another ARM machine) still runs on a Pi 4.
    cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF -DGGML_NATIVE=OFF || return 1
    cmake --build "$src/build" -j"$(nproc)" --target whisper-cli whisper-server || return 1
    install -m 0755 "$src/build/bin/whisper-cli" "$src/build/bin/whisper-server" /usr/local/bin/
}

fetch() {   # url dest
    [ -s "$2" ] && return 0
    curl -fL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"
}

get_whisper_model() {
    local f="$SHARE/models/ggml-${WHISPER_MODEL}.bin"
    fetch "$HF/ggerganov/whisper.cpp/resolve/main/ggml-${WHISPER_MODEL}.bin" "$f" || return 1
    # Point the config at the model actually installed.
    sed -i "s|^WHISPER_MODEL=.*|WHISPER_MODEL=$f|" "$CONF" 2>/dev/null
    return 0
}

set_voice() {   # LANG VALUE
    local key="VOICE_${1^^}" cur
    cur=$(conf_get "$key")
    # Keep a voice the operator chose: only fill in a missing or broken one.
    if [ -n "$cur" ] && [ -e "${cur#openjtalk:}" ]; then
        return 0
    fi
    if grep -q "^$key=" "$CONF" 2>/dev/null; then
        sed -i "s|^$key=.*|$key=$2|" "$CONF"
    else
        echo "$key=$2" >> "$CONF"
    fi
}

get_voices() {
    local lang rc=0 line path stem base
    for lang in $MY_LANG $LANGS; do
        if [ "$lang" = ja ]; then
            apt-get install -y --no-install-recommends open-jtalk \
                open-jtalk-mecab-naist-jdic hts-voice-nitech-jp-atr503-m001 &&
                [ -f "$JA_VOICE" ] && set_voice ja "openjtalk:$JA_VOICE" || rc=1
            continue
        fi
        line=$(printf '%s\n' "$VOICES" | grep "^$lang|") || {
            warn "No default voice for '$lang'. Supported: $(printf '%s\n' "$VOICES" | cut -d'|' -f1 | xargs) ja"
            warn "Or put a Piper .onnx + .onnx.json in $SHARE/voices and set VOICE_${lang^^} in translate.conf."
            rc=1; continue; }
        path=${line#*|}
        stem=$(basename "$path")
        base="$HF/rhasspy/piper-voices/resolve/v1.0.0/$(dirname "$path")"
        fetch "$base/$stem.onnx" "$SHARE/voices/$stem.onnx" &&
        fetch "$base/$stem.onnx.json" "$SHARE/voices/$stem.onnx.json" || { rc=1; continue; }
        fetch "$base/MODEL_CARD" "$SHARE/voices/$stem.MODEL_CARD" ||
            warn "No MODEL_CARD for $stem; check its license on Hugging Face."
        set_voice "$lang" "$SHARE/voices/$stem.onnx"
    done
    return $rc
}

get_argos() {
    # shellcheck disable=SC2086  # LANGS is a space-separated list
    HAMPI_TRANSLATE_IN_VENV=1 "$SHARE/venv/bin/python3" /usr/local/bin/hampi-translate \
        fetch-packs --langs $LANGS
}

set_partner_language() {
    # Only switch the partner language when --langs was given explicitly, and
    # only after its voice and packs are in place (this step runs last).
    [ "$LANGS_SET" -eq 1 ] || return 0
    local l
    for l in "${FAILURES[@]}"; do
        case "$l" in *voices*|*packs*)
            warn "Leaving THEIR_LANG as it is: a download for '$LANGS' failed."; return 1 ;;
        esac
    done
    sed -i "s|^THEIR_LANG=.*|THEIR_LANG=${LANGS%% *}|" "$CONF"
}

# Works from a repo checkout (scripts/../payload) or as the installed copy
# /usr/local/sbin/rfpi-translator-install, where setup.sh already put the
# tool, configs and service unit in place.
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PAYLOAD="$HERE/payload"

enable_service() {
    [ -f "$PAYLOAD/systemd/hampi-whisper.service" ] &&
        install -m 0644 "$PAYLOAD/systemd/hampi-whisper.service" /etc/systemd/system/
    local unit=/etc/systemd/system/hampi-whisper.service model
    [ -f "$unit" ] || { warn "hampi-whisper.service missing; re-run setup.sh"; return 1; }
    chmod -R a+rX "$SHARE"
    # Don't enable a service that can only crash-loop.
    model=$(conf_get WHISPER_MODEL)
    [ -x /usr/local/bin/whisper-server ] && [ -s "$model" ] || {
        warn "whisper-server or its model ($model) is missing; not enabling the service."; return 1; }
    # No sudo user (root shell, image build): keep the user setup.sh set, else
    # fall back to the first regular account.
    if [ -z "$TARGET_USER" ]; then
        TARGET_USER=$(sed -n 's/^User=//p' "$unit" | grep -v __HAMPI_USER__ || true)
        [ -n "$TARGET_USER" ] || TARGET_USER=$(id -nu 1000 2>/dev/null || true)
    fi
    id "$TARGET_USER" >/dev/null 2>&1 || {
        warn "No such user '$TARGET_USER' to run the service as; pass --user NAME."; return 1; }
    sed -i "s/^User=.*/User=${TARGET_USER}/" "$unit"
    # hampi-translate writes its status file here (setup.sh also creates it).
    install -d -o "$TARGET_USER" /var/lib/hampi 2>/dev/null || install -d /var/lib/hampi
    touch /etc/hampi/translate.enabled
    systemctl daemon-reload
    systemctl enable hampi-whisper.service
    systemctl restart hampi-whisper.service 2>/dev/null || true   # no-op in an image chroot
}

ensure_config() {
    install -d /etc/hampi
    if [ -d "$PAYLOAD" ]; then
        [ -e "$CONF" ] || install -m 0644 "$PAYLOAD/configs/translate.conf" /etc/hampi/
        # Standalone install (without setup.sh): the callsign lives here.
        [ -e /etc/hampi/station.conf ] || install -m 0644 "$PAYLOAD/configs/station.conf" /etc/hampi/
        [ -e /etc/hampi/translate-glossary.txt ] || \
            install -m 0644 "$PAYLOAD/configs/translate-glossary.txt" /etc/hampi/
        install -m 0755 "$PAYLOAD/tools/hampi-translate" /usr/local/bin/
        ln -sf hampi-translate /usr/local/bin/rfpi-translate
        install -m 0644 "$PAYLOAD/configs/TRANSLATOR.md" /etc/hampi/TRANSLATOR.md
    fi
    [ -e "$CONF" ] && [ -x /usr/local/bin/hampi-translate ] || {
        warn "RF Pi files not found: run setup.sh first, or run this from the repo."; return 1; }
    return 0
}

step "Install translator config"                ensure_config
step "Install engines (CTranslate2, Piper)"    install_deps
step "Build whisper.cpp (speech to text)"       build_whisper
step "Download Whisper model ($WHISPER_MODEL)"  get_whisper_model
step "Download Piper voices ($MY_LANG $LANGS)"  get_voices
step "Download translation packs (Argos)"       get_argos
step "Enable hampi-whisper service"             enable_service
step "Set partner language"                     set_partner_language

log "Translator install finished."
if [ ${#FAILURES[@]} -gt 0 ]; then
    echo "These steps failed; re-run this script to retry them:"
    printf '  - %s\n' "${FAILURES[@]}"
fi
echo
echo "Next:"
echo "  1. hampi-translate check            (every line should say OK)"
echo "  2. hampi-translate run --no-tx      (practise: translations play in your headphones)"
echo "  3. hampi-translate bench            (measure the wait on this board)"
echo "Guide: /etc/hampi/TRANSLATOR.md"
[ ${#FAILURES[@]} -eq 0 ]
