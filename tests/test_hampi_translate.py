"""Tests for payload/tools/hampi-translate.

Run from the project folder:   python3 -m pytest tests -q
Needs only numpy and pytest: models, sound cards and radios are all faked.
"""

import importlib.machinery
import importlib.util
import json
import os
import socket
import stat
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

TOOL = os.path.join(os.path.dirname(__file__), "..", "payload", "tools", "hampi-translate")


def _load():
    loader = importlib.machinery.SourceFileLoader("hampi_translate", TOOL)
    spec = importlib.util.spec_from_loader("hampi_translate", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


ht = _load()


def identity(text, src, dst):
    return text


def upper(text, src, dst):
    return text.upper()


# --- jargon protection ------------------------------------------------------

def test_phonetic():
    assert ht.phonetic("K4DIA") == "Kilo 4 Delta India Alfa"
    assert ht.phonetic("IK0ABC/P") == "India Kilo 0 Alfa Bravo Charlie stroke Papa"


@pytest.mark.parametrize("said,expect", [
    ("this is kilo four delta india alfa over", "this is K4DIA over"),
    ("Kilo 4 Delta India Alpha", "K4DIA"),
    ("india kilo zero alfa bravo charlie", "IK0ABC"),
    ("five nine", "five nine"),                 # digits only: not a callsign
    ("I have one two three radios", "I have one two three radios"),
])
def test_collapse_spelled_calls(said, expect):
    assert ht.collapse_spelled_calls(said) == expect


def test_protect_and_restore_full_exchange():
    text = ("Good morning K1ABC, you are five nine. My QTH is Boston, grid FN42hn. "
            "Meet me on 146.520 MHz. 73")
    masked, items = ht.protect(text)
    for jargon in ("K1ABC", "five nine", "QTH", "FN42", "146.520", "73"):
        assert jargon not in masked
    kinds = [i.kind for i in items]
    assert kinds.count("call") == 1 and "rst" in kinds and "q" in kinds
    assert "grid" in kinds and "freq" in kinds and "greeting" in kinds

    display, spoken = ht.restore(masked, items, "it")
    assert "K1ABC" in display and "5 9" in display and "QTH" in display
    assert "FN42hn" in display and "146.520 MHz" in display and display.endswith("73")
    assert "Kilo 1 Alfa Bravo Charlie" in spoken
    assert "Q T H" in spoken
    assert "146 virgola 520 megahertz" in spoken
    assert "Foxtrot November 4 2 Hotel November" in spoken


def test_restore_rejects_dropped_placeholder():
    masked, items = ht.protect("Hello K1ABC and W1AW")
    broken = masked.replace("ZXQ1", "")
    assert ht.restore(broken, items, "it") is None


@pytest.mark.parametrize("said,is_report", [
    ("you are 59 into Rome", True),
    ("your signal is 5/9", True),
    ("giving you 599", True),
    ("I'm 59 years old", False),
    ("it costs 45 dollars", False),
    ("four by seven", False),                  # no cue: could be lumber
    ("your signal is four by seven", True),
    ("five by nine", True),
    ("five nine, five nine", True),
    ("two three", False),
    # ordinary numbers that used to be mistaken for reports
    ("I run 5-7 watts", False),
    ("a two by four for the mast", False),
    ("I got 35 contacts", False),
    ("you are 45 years old", False),
    ("one four five five zero zero", False),
    ("a five nine-element yagi", False),
])
def test_signal_reports(said, is_report):
    _, items = ht.protect(said)
    assert any(i.kind == "rst" for i in items) is is_report


def test_ordinary_words_untouched():
    text = "The weather here is sunny and the antenna is up."
    masked, items = ht.protect(text)
    assert masked == text and items == []


def test_glossary_terms_kept():
    masked, items = ht.protect("I run a Baofeng from the Blue Ridge", ["Baofeng", "Blue Ridge"])
    assert "Baofeng" not in masked and "Blue Ridge" not in masked
    assert ht.restore(masked, items, "it")[0] == "I run a Baofeng from the Blue Ridge"


def test_q_code_question_mark_and_cq():
    masked, items = ht.protect("CQ CQ, QRZ? QSL")
    assert [i.display for i in items] == ["CQ", "CQ", "QRZ?", "QSL"]


# --- translator wrapper -----------------------------------------------------

def test_translator_passes_jargon_through_backend():
    seen = []

    def backend(text, src, dst):
        seen.append(text)
        return text.replace("Good morning", "Buongiorno")

    t = ht.PhraseTranslator(backend).translate("Good morning K1ABC, five nine", "en", "it")
    assert "K1ABC" not in seen[0]
    assert t.display == "Buongiorno K1ABC, 5 9"
    assert t.spoken == "Buongiorno Kilo 1 Alfa Bravo Charlie, 5 9"
    assert not t.fallback


def test_translator_falls_back_when_placeholders_are_mangled():
    def eats_placeholders(text, src, dst):
        return ht.PH_RE.sub("", text).upper()

    t = ht.PhraseTranslator(eats_placeholders).translate(
        "hello K1ABC you are five nine", "en", "it")
    assert t.fallback
    assert t.display == "HELLO K1ABC YOU ARE 5 9"


def test_translator_no_jargon_and_same_language():
    tr = ht.PhraseTranslator(upper)
    assert tr.translate("good morning", "en", "it").display == "GOOD MORNING"
    assert tr.translate("good morning K1ABC", "en", "en").display == "good morning K1ABC"


@pytest.mark.parametrize("raw,clean", [
    ("[BLANK_AUDIO]", ""),
    (" Thanks for watching!", ""),
    ("Sottotitoli creati dalla comunità Amara.org", ""),
    ("(static) hello there [noise]", "hello there"),
    ("Buongiorno, ti sento cinque nove.", "Buongiorno, ti sento cinque nove."),
])
def test_clean_transcript(raw, clean):
    assert ht.clean_transcript(raw) == clean


# --- audio --------------------------------------------------------------------

def tone(seconds, rate, db=-10.0, hz=440.0):
    t = np.arange(int(seconds * rate)) / rate
    return (10 ** (db / 20) * np.sqrt(2) * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_resample_length_and_pitch():
    x = tone(1.0, 48000, hz=1000)
    y = ht.resample(x, 48000, 16000)
    assert abs(len(y) - 16000) <= 1
    spectrum = np.abs(np.fft.rfft(y))
    assert abs(np.argmax(spectrum) * 16000 / len(y) - 1000) < 5


def test_resample_removes_alias():
    x = tone(1.0, 48000, hz=12000)            # above the 8 kHz Nyquist of 16 kHz
    assert ht.rms_db(ht.resample(x, 48000, 16000)) < -35


def test_wav_roundtrip(tmp_path):
    x = tone(0.5, 22050)
    path = str(tmp_path / "t.wav")
    ht.write_wav(path, x, 22050)
    y, rate = ht.read_wav(path)
    assert rate == 22050 and np.allclose(x, y, atol=1e-4)


def test_segmenter_finds_one_transmission():
    rate = 16000
    rng = np.random.default_rng(1)
    noise = lambda s: (rng.standard_normal(int(s * rate)) * 0.001).astype(np.float32)
    stream = np.concatenate([noise(1.0), tone(1.5, rate), noise(1.5),
                             tone(0.2, rate), noise(1.5)])          # last burst is too short
    seg = ht.Segmenter(rate, threshold_db=-38, hang_ms=900, min_ms=700)
    out = []
    for i in range(0, len(stream), 800):
        out += seg.feed(stream[i:i + 800])
    assert len(out) == 1
    assert 1.4 < len(out[0]) / rate < 2.2


def test_join_audio_adds_gaps():
    a, b = np.ones(100, np.float32), np.ones(50, np.float32)
    out = ht.join_audio([a, None, b], 1000, gap_ms=10)
    assert len(out) == 160


# --- station ID -------------------------------------------------------------

def test_id_timer():
    now = [0.0]
    ids = ht.IdTimer(every_min=10, margin_s=45, clock=lambda: now[0])
    assert ids.due()                           # first transmission carries the ID
    ids.mark()
    now[0] = 300
    assert not ids.due()
    now[0] = 600 - 44
    assert ids.due()                           # before the 10-minute window lapses


def test_callsign_check():
    assert ht._callsign_ok("K4DIA")
    assert not ht._callsign_ok("N0CALL")
    assert not ht._callsign_ok("")


# --- PTT ----------------------------------------------------------------------

class FakeRigctld:
    def __init__(self, reply="RPRT 0"):
        self.cmds, self.reply = [], reply
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            with c:
                line = c.recv(64).decode().strip()
                self.cmds.append(line)
                c.sendall((("0" if line == "t" else self.reply) + "\n").encode())


def test_rigctld_keyed_unkeys_even_on_error():
    rig = FakeRigctld()
    ptt = ht.RigctldPTT(f"127.0.0.1:{rig.port}")
    with pytest.raises(ValueError):
        with ht.keyed(ptt, lead_ms=0, tail_ms=0):
            raise ValueError("audio failed")
    assert rig.cmds == ["T 1", "T 0"]
    assert ptt.status() == "0"


def test_rigctld_refusal_is_an_error():
    rig = FakeRigctld(reply="RPRT -11")
    with pytest.raises(RuntimeError):
        ht.RigctldPTT(f"127.0.0.1:{rig.port}").key(True)


# --- whisper.cpp ------------------------------------------------------------

def test_whisper_server_request_and_language_mapping():
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode("latin-1")
            got.setdefault("bodies", []).append(body)
            fmt = "verbose_json" if 'name="response_format"\r\n\r\nverbose_json' in body else "json"
            out = {"text": " Buongiorno, cinque nove. "}
            if fmt == "verbose_json":
                out["language"] = "italian"
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    stt = ht.WhisperServerSTT(f"http://127.0.0.1:{srv.server_port}")
    audio = tone(1.0, 16000)
    assert stt.transcribe(audio, "it") == ("Buongiorno, cinque nove.", "it")
    assert stt.transcribe(audio, "auto") == ("Buongiorno, cinque nove.", "it")
    fixed, auto = got["bodies"]
    assert 'name="language"\r\n\r\nit' in fixed and "\r\n\r\njson\r\n" in fixed
    assert 'name="language"\r\n\r\nauto' in auto
    assert "RIFF" in fixed                      # a real WAV was attached
    srv.shutdown()


def _script(path, body):
    path.write_text("#!" + sys.executable + "\n" + textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_whisper_cli_parses_json(tmp_path):
    cli = _script(tmp_path / "whisper-cli", """
        import json, sys
        a = sys.argv
        assert a[a.index("-bs") + 1] == "1" and "-oj" in a
        out = a[a.index("-of") + 1] + ".json"
        json.dump({"result": {"language": "it"},
                   "transcription": [{"text": " Ciao,"}, {"text": " QTH Roma."}]}, open(out, "w"))
    """)
    stt = ht.WhisperCliSTT(cli, "model.bin")
    assert stt.transcribe(tone(0.5, 16000), "it") == ("Ciao, QTH Roma.", "it")


# --- Piper --------------------------------------------------------------------

def test_piper_tts_runs_subprocess(tmp_path):
    piper = _script(tmp_path / "piper", f"""
        import sys, wave
        sys.path.insert(0, {os.path.dirname(TOOL)!r})
        text = sys.stdin.read()
        assert text.endswith("\\n") and text.count("\\n") == 1
        out = sys.argv[sys.argv.index("-f") + 1]
        with wave.open(out, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
            w.writeframes(b"\\x00\\x10" * 2205 * len(text.split()))
    """)
    tts = ht.PiperTTS(piper, {"it": "it.onnx"})
    audio, rate = tts.synth("Buongiorno\nK1ABC", "it")
    assert rate == 22050 and len(audio) == 2205 * 2
    with pytest.raises(RuntimeError):
        tts.synth("hello", "fr")


# --- whole chain ------------------------------------------------------------

class FakeSTT:
    def __init__(self, text, lang="en"):
        self.text, self.lang = text, lang

    def transcribe(self, audio, lang):
        return self.text, lang or self.lang


class FakeTTS:
    def __init__(self):
        self.said = []

    def synth(self, text, lang):
        self.said.append((lang, text))
        return np.zeros(2205, np.float32), 22050


def test_engine_end_to_end_with_disclosure():
    tts = FakeTTS()
    conf = dict(ht.DEFAULTS, CALLSIGN="K4DIA")
    eng = ht.Engine(conf, stt=FakeSTT("Good morning W1AW, you are five nine"),
                    translator=ht.PhraseTranslator(
                        lambda t, s, d: t.replace("Good morning", "Buongiorno")
                                         .replace("you are", "sei")),
                    tts=tts)
    r = eng.translate_audio(tone(1.0, 16000), "en", "it", speak=True, disclose=True)
    assert r.translation.display == "Buongiorno W1AW, sei 5 9"
    lang, said = tts.said[-1]
    assert lang == "it" and said.startswith("Trasmissione tradotta automaticamente.")
    assert "Whiskey 1 Alfa Whiskey" in said
    assert set(r.timings) == {"stt", "translate", "tts"}


def test_engine_stops_when_nothing_heard():
    eng = ht.Engine(dict(ht.DEFAULTS), stt=FakeSTT(""), translator=ht.PhraseTranslator(identity),
                    tts=FakeTTS())
    r = eng.translate_audio(tone(1.0, 16000), "en", "it")
    assert r.heard == "" and r.translation is None


def test_station_id_audio_is_english_phonetics():
    tts = FakeTTS()
    eng = ht.Engine(dict(ht.DEFAULTS, CALLSIGN="K4DIA", ID_WAV=""), stt=FakeSTT(""),
                    translator=ht.PhraseTranslator(identity), tts=tts)
    eng.id_audio()
    assert tts.said[-1] == ("en", "This is Kilo 4 Delta India Alfa.")


# --- config -------------------------------------------------------------------

def test_load_conf(tmp_path, monkeypatch):
    station = tmp_path / "station.conf"
    station.write_text("CALLSIGN=k4dia\nGRID=EM12\n")
    conf = tmp_path / "translate.conf"
    conf.write_text("# comment\nTHEIR_LANG=es   # Spanish\nREVIEW=0\n")
    monkeypatch.setattr(ht, "STATION_CONF", str(station))
    c = ht.load_conf(str(conf))
    assert c["CALLSIGN"] == "K4DIA" and c["THEIR_LANG"] == "es"
    assert not ht.flag(c, "REVIEW") and c["MY_LANG"] == "en"


def test_shipped_config_template_matches_defaults():
    tmpl = os.path.join(os.path.dirname(TOOL), "..", "configs", "translate.conf")
    shipped = ht.load_kv(tmpl)
    assert len(shipped) > 30                        # the template really was read
    assert set(shipped) <= set(ht.DEFAULTS), set(shipped) - set(ht.DEFAULTS)
    assert {k: ht.DEFAULTS[k] for k in shipped} == shipped
    # systemd reads this file too and keeps trailing comments as part of the value
    for line in open(tmpl, encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            assert "#" not in line, line


# --- the operating loop -----------------------------------------------------

def test_run_loop_review_discard_then_send_with_id(monkeypatch, tmp_path):
    from argparse import Namespace
    events = []

    class Local:
        presses = ["talk", "talk", "quit"]
        answers = [False, True]          # discard the first, send the second

        def wait_press(self):
            return self.presses.pop(0)

        def is_down(self):
            return False

        def end_talk(self):
            pass

        def confirm(self, timeout):
            return self.answers.pop(0)

    class PTT:
        name = "fake"

        def key(self, on):
            events.append(("key", on))

        def close(self):
            pass

    tts = FakeTTS()
    real_engine = ht.Engine
    monkeypatch.setattr(ht, "Engine", lambda conf: real_engine(
        conf, stt=FakeSTT("good morning K1ABC"), translator=ht.PhraseTranslator(upper), tts=tts))
    monkeypatch.setattr(ht, "make_local", lambda conf: Local())
    monkeypatch.setattr(ht, "make_ptt", lambda conf: PTT())
    monkeypatch.setattr(ht, "find_device", lambda spec, kind: None)
    monkeypatch.setattr(ht, "record_while", lambda dev, is_down, max_s: tone(1.0, 16000))
    monkeypatch.setattr(ht, "play", lambda a, r, d, gain=1.0: events.append(("play", d)))
    conf = dict(ht.DEFAULTS, CALLSIGN="K4DIA", RX="0", PTT_LEAD_MS="0", PTT_TAIL_MS="0",
                STATUS_FILE=str(tmp_path / "status.json"))

    ht.cmd_run(conf, Namespace(no_tx=False))

    # Discarded transmission never keyed; the sent one keyed exactly once
    # (the final unkey is the shutdown safety net).
    assert events == [("key", True), ("play", None), ("key", False), ("key", False)]
    # First transmission of a contact carries the English station ID.
    assert ("en", "This is Kilo 4 Delta India Alfa.") in tts.said
    assert any(lang == "it" and "Kilo 1 Alfa Bravo Charlie" in t for lang, t in tts.said)
    status = json.load(open(tmp_path / "status.json"))
    assert status["state"] == "stopped" and status["log"][-1]["dir"] == "tx"


def test_run_refuses_to_transmit_without_callsign():
    from argparse import Namespace
    with pytest.raises(SystemExit):
        ht.cmd_run(dict(ht.DEFAULTS, CALLSIGN="N0CALL"), Namespace(no_tx=False))


# --- translation packs (Argos layout, run on CTranslate2) --------------------

def _make_pack(root, name, src, dst, prefix=""):
    d = root / name
    (d / "model").mkdir(parents=True)
    (d / "sentencepiece.model").write_bytes(b"sp")
    meta = {"from_code": src, "to_code": dst, "package_version": "1.0"}
    if prefix:
        meta["target_prefix"] = prefix
    (d / "metadata.json").write_text(json.dumps(meta))
    return d


def test_find_packs_skips_junk(tmp_path):
    _make_pack(tmp_path, "translate-en_it-1_0", "en", "it")
    (tmp_path / "notapack").mkdir()
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "metadata.json").write_text("{not json")
    assert list(ht.find_packs(str(tmp_path))) == [("en", "it")]
    assert ht.find_packs(str(tmp_path / "missing")) == {}


def test_split_sentences():
    assert ht.split_sentences("Good morning. You are ZXQ0! QTH? ") == \
        ["Good morning.", "You are ZXQ0!", "QTH?"]
    assert ht.split_sentences("146.520 is the frequency") == ["146.520 is the frequency"]


def test_pack_backend_glue(tmp_path, monkeypatch):
    """CTranslate2 and SentencePiece are faked; checks paths, batching,
    decoding options and target-prefix stripping."""
    import types
    _make_pack(tmp_path, "p", "en", "it", prefix="__it__")
    calls = {}

    class Translator:
        def __init__(self, path, **kw):
            calls["path"], calls["init"] = path, kw

        def translate_batch(self, tokens, **kw):
            calls["batch"], calls["kw"] = tokens, kw
            return [types.SimpleNamespace(hypotheses=[["__it__", "▁ciao"] + t[1:]])
                    for t in tokens]

    class SP:
        def __init__(self, model_file):
            calls["sp"] = model_file

        def encode(self, s, out_type=str):
            return ["▁" + w for w in s.split()]

        def decode_pieces(self, pieces):
            return "".join(pieces).replace("▁", " ")

    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(Translator=Translator))
    monkeypatch.setitem(sys.modules, "sentencepiece",
                        types.SimpleNamespace(SentencePieceProcessor=SP))
    b = ht.PackBackend(str(tmp_path), beam=2, threads=3)
    out = b("Hello ZXQ0. Bye now.", "en", "it")
    assert out == "ciao ZXQ0. ciao now."
    assert calls["path"].endswith("/p/model") and calls["sp"].endswith("sentencepiece.model")
    assert calls["init"]["compute_type"] == "int8" and calls["init"]["intra_threads"] == 3
    assert calls["kw"]["beam_size"] == 2 and calls["kw"]["target_prefix"] == [["__it__"]] * 2
    assert calls["kw"]["max_decoding_length"] == 2 * 2 + 16
    with pytest.raises(RuntimeError, match="rfpi-translator-install --langs it"):
        b("Ciao", "it", "en")


def _serve_dir(path):
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(path))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_fetch_packs_downloads_newest_and_unzips(tmp_path):
    import zipfile
    served = tmp_path / "served"
    served.mkdir()
    for ver in ("1_0", "1_9"):
        with zipfile.ZipFile(served / f"en_it-{ver}.zip", "w") as z:
            z.writestr(f"translate-en_it-{ver}/metadata.json",
                       json.dumps({"from_code": "en", "to_code": "it", "package_version": ver}))
            z.writestr(f"translate-en_it-{ver}/README.md", "Trained on: Europarl, Tatoeba")
    with zipfile.ZipFile(served / "it_en.zip", "w") as z:
        z.writestr("translate-it_en-1_0/metadata.json",
                   json.dumps({"from_code": "it", "to_code": "en", "package_version": "1.0"}))
    srv, base = _serve_dir(served)
    (served / "index.json").write_text(json.dumps([
        {"from_code": "en", "to_code": "it", "package_version": "1.0",
         "links": [f"{base}/en_it-1_0.zip"]},
        {"from_code": "en", "to_code": "it", "package_version": "1.9",
         "links": ["ipfs://skip-me", f"{base}/en_it-1_9.zip"]},
        {"from_code": "it", "to_code": "en", "package_version": "1.0",
         "links": [f"{base}/it_en.zip"]},
    ]))
    root = tmp_path / "packs"
    ht.fetch_packs("en", ["it"], str(root), f"{base}/index.json")
    packs = ht.find_packs(str(root))
    assert set(packs) == {("en", "it"), ("it", "en")}
    assert packs[("en", "it")][1]["package_version"] == "1_9"
    with pytest.raises(RuntimeError, match="en->xx"):
        ht.fetch_packs("en", ["xx"], str(root), f"{base}/index.json")
    srv.shutdown()


def test_fetch_packs_rejects_path_traversal(tmp_path):
    import zipfile
    served = tmp_path / "served"
    served.mkdir()
    with zipfile.ZipFile(served / "evil.zip", "w") as z:
        z.writestr("pack/../../escape.txt", "x")
    srv, base = _serve_dir(served)
    (served / "index.json").write_text(json.dumps([
        {"from_code": "en", "to_code": "it", "links": [f"{base}/evil.zip"]}]))
    with pytest.raises(RuntimeError, match="unexpected layout"):
        ht.fetch_packs("en", ["it"], str(tmp_path / "packs"), f"{base}/index.json")
    assert not (tmp_path / "escape.txt").exists()
    srv.shutdown()


def test_keyboard_enter_after_time_limit_goes_to_next_prompt(monkeypatch):
    import time as _t
    r, w = os.pipe()                    # a stdin that stays open (EOF would mean "quit")
    monkeypatch.setattr(sys, "stdin", os.fdopen(r))
    kb = ht.KeyboardLocal()
    kb.lines.put("")                    # Enter: start talking
    assert kb.wait_press() == "talk"
    kb.end_talk()                       # recording hit MAX_RECORD_SEC
    threading.Timer(0.2, kb.lines.put, [""]).start()    # the operator's next Enter...
    try:
        assert kb.confirm(timeout=2)    # ...answers the review prompt
    finally:
        os.close(w)


# --- languages ----------------------------------------------------------------

def _installer_voices():
    path = os.path.join(os.path.dirname(TOOL), "..", "..", "scripts", "install-translator.sh")
    text = open(path, encoding="utf-8").read()
    block = text.split('VOICES="', 1)[1].split('"', 1)[0]
    return dict(line.split("|", 1) for line in block.split() if "|" in line)


def test_every_installable_language_is_fully_described():
    voices = _installer_voices()
    langs = set(voices) | {"ja"}                    # ja comes from Open JTalk
    assert langs == set(ht.LANGUAGES), langs ^ set(ht.LANGUAGES)
    for code, (name, disclosure, decimal, wcode) in ht.LANGUAGES.items():
        assert name and disclosure and decimal and len(wcode) == 2, code
    for code, path in voices.items():
        stem = path.rsplit("/", 1)[-1]
        assert path.count("/") == 4 and stem.endswith(("-x_low", "-low", "-medium")), path


def test_norwegian_code_mapping():
    assert ht.whisper_code("nb") == "no" and ht.whisper_code("it") == "it"
    assert ht.lang_code("no") == "nb" and ht.lang_code("norwegian") == "nb"
    assert ht.lang_code("japanese") == "ja" and ht.lang_code("persian") == "fa"


def test_engine_passes_whisper_code_and_maps_back():
    seen = []

    class STT:
        def transcribe(self, audio, lang):
            seen.append(lang)
            return "God morgen", "no"

    eng = ht.Engine(dict(ht.DEFAULTS), stt=STT(), translator=ht.PhraseTranslator(identity),
                    tts=FakeTTS())
    r = eng.translate_audio(tone(0.5, 16000), "nb", "en", speak=False)
    assert seen == ["no"] and r.lang == "nb"


def test_split_sentences_cjk_and_hindi():
    assert ht.split_sentences("おはようございます。シグナルは ZXQ0 です。") == \
        ["おはようございます。", "シグナルは ZXQ0 です。"]
    assert ht.split_sentences("你好。再见！") == ["你好。", "再见！"]
    assert ht.split_sentences("नमस्ते। धन्यवाद।") == ["नमस्ते।", "धन्यवाद।"]


def test_japanese_jargon_is_spoken_in_katakana():
    t = ht.PhraseTranslator(lambda x, s, d: x.replace("Good morning", "おはようございます")
                            ).translate("Good morning K1ABC, QTH? 146.520 MHz, 5 9", "en", "ja")
    assert "K1ABC" in t.display and "QTH?" in t.display
    assert "キロ 1 アルファ ブラボー チャーリー" in t.spoken
    assert "キュー ティー エイチ？" in t.spoken
    assert "146 てん 520 メガヘルツ" in t.spoken
    assert "Kilo" not in t.spoken


def test_voicebank_dispatches_piper_and_openjtalk(tmp_path):
    jtalk = _script(tmp_path / "open_jtalk", """
        import sys, wave
        a = sys.argv
        assert a[a.index("-x") + 1] == "DIC" and a[a.index("-m") + 1] == "voice.htsvoice"
        with wave.open(a[a.index("-ow") + 1], "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
            w.writeframes(b"\\x00\\x00" * 480)
    """)
    calls = []
    monkey = ht.OpenJTalkTTS.__init__

    def init(self, voice, dic, binary="open_jtalk"):
        calls.append(voice)
        monkey(self, voice, dic, jtalk)
    ht.OpenJTalkTTS.__init__ = init
    try:
        bank = ht.VoiceBank("piper", {"ja": "openjtalk:voice.htsvoice"}, "DIC")
        audio, rate = bank.synth("こんにちは", "ja")
    finally:
        ht.OpenJTalkTTS.__init__ = monkey
    assert rate == 48000 and len(audio) == 480 and calls == ["voice.htsvoice"]
    with pytest.raises(RuntimeError, match="VOICE_KO"):
        bank.synth("hi", "ko")


@pytest.mark.skipif(not os.path.exists(
    "/usr/share/hts-voice/nitech-jp-atr503-m001/nitech_jp_atr503_m001.htsvoice"),
    reason="Open JTalk not installed")
def test_real_open_jtalk():
    tts = ht.OpenJTalkTTS("/usr/share/hts-voice/nitech-jp-atr503-m001/nitech_jp_atr503_m001.htsvoice",
                          "/var/lib/mecab/dic/open-jtalk/naist-jdic")
    audio, rate = tts.synth(ht.DISCLOSURE["ja"] + " キロ 1 アルファ", "ja")
    assert rate == 48000 and len(audio) / rate > 1.5 and ht.rms_db(audio) > -40


# --- review fixes: jargon -----------------------------------------------------

@pytest.mark.parametrize("said,expect", [
    ("kilo four delta india alfa. I am in Rome.", "K4DIA. I am in Rome."),
    ("whiskey one alfa whiskey, a good signal", "W1AW, a good signal"),
    ("On November 2 I went to the hamfest", "On November 2 I went to the hamfest"),
    ("I stayed at the hotel. 5 a.m.", "I stayed at the hotel. 5 a.m."),
    ("Mike, 1 a day", "Mike, 1 a day"),
    ("K 4 D I A calling", "K4DIA calling"),
])
def test_collapse_leaves_ordinary_speech_alone(said, expect):
    assert ht.collapse_spelled_calls(said) == expect


@pytest.mark.parametrize("said,shown", [
    ("7,150 kHz", "7150 kHz"),                  # thousands comma, not a decimal
    ("1,234.5 kHz", "1234.5 kHz"),
    ("14,250 MHz", "14.250 MHz"),               # decimal comma (Italian style)
    ("146.520 MHz", "146.520 MHz"),
])
def test_frequency_commas(said, shown):
    _, items = ht.protect(said)
    assert [i.display for i in items] == [shown]


def test_portable_prefix_and_lookalikes():
    _, items = ht.protect("DL/K4DIA, VP2E/K4DIA and K4DIA/P")
    assert [i.display for i in items] == ["DL/K4DIA", "VP2E/K4DIA", "K4DIA/P"]
    assert ht.protect("H2O and B2B, part AB12, an FM10 radio")[1] == []
    assert [i.kind for i in ht.protect("my grid is FN42, locator JN61")[1]] == ["grid", "grid"]


def test_load_kv_quotes_comments_export(tmp_path):
    f = tmp_path / "c.conf"
    f.write_text("RADIO_OUT=USB Audio #2\nCALLSIGN='k4dia'\nA=\"x  # y\"\n"
                 "B=1  # note\nC=2\t# note\nexport D=3\n")
    assert ht.load_kv(str(f)) == {"RADIO_OUT": "USB Audio #2", "CALLSIGN": "k4dia",
                                  "A": "x  # y", "B": "1", "C": "2", "D": "3"}


def test_resample_short_input_length():
    assert len(ht.resample(np.ones(10, np.float32), 48000, 16000)) == 3


def test_make_tts_knows_every_configured_voice():
    bank = ht.make_tts(dict(ht.DEFAULTS, VOICE_FR="/v/fr.onnx", VOICE_DE=""))
    assert set(bank.voices) == {"en", "it", "fr"}


def test_tool_failure_reports_stderr(tmp_path):
    bad = _script(tmp_path / "piper", """
        import sys
        sys.stderr.write("voice file is corrupt")
        sys.exit(3)
    """)
    with pytest.raises(RuntimeError, match="exit 3.*voice file is corrupt"):
        ht.PiperTTS(bad, {"it": "x.onnx"}).synth("ciao", "it")
    with pytest.raises(RuntimeError, match="not installed"):
        ht.PiperTTS(str(tmp_path / "missing"), {"it": "x.onnx"}).synth("ciao", "it")


# --- review fixes: keying safety ----------------------------------------------

class RecPTT:
    name = "fake"

    def __init__(self):
        self.events = []

    def key(self, on):
        self.events.append(on)

    def close(self):
        pass


def test_watchdog_unkeys_a_stalled_transmission():
    import time as _t
    ptt = RecPTT()
    with ht.keyed(ptt, 0, 0, max_s=0.1):
        _t.sleep(0.4)                       # the sound device "hangs"
        assert ptt.events == [True, False]  # ...but the radio was already unkeyed
    assert ptt.events == [True, False, False]


def test_watchdog_does_not_fire_on_a_normal_over():
    import time as _t
    ptt = RecPTT()
    with ht.keyed(ptt, 0, 0, max_s=0.2):
        pass
    _t.sleep(0.35)
    assert ptt.events == [True, False]


def test_rigctld_empty_reply_is_an_error():
    rig = FakeRigctld(reply="")
    with pytest.raises(RuntimeError, match="no reply"):
        ht.RigctldPTT(f"127.0.0.1:{rig.port}").key(False)


def test_serial_ptt_sets_lines_low_before_opening(monkeypatch):
    import types
    log = []

    class Serial:
        def __init__(self, *a):
            assert not a, "Serial(port) would assert RTS/DTR while opening"
            object.__setattr__(self, "is_open", False)

        def __setattr__(self, k, v):
            log.append((k, v, self.is_open))
            object.__setattr__(self, k, v)

        def open(self):
            object.__setattr__(self, "is_open", True)

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=Serial))
    ptt = ht.SerialPTT("/dev/ttyUSB0", "rts")
    assert ("rts", False, False) in log and ("dtr", False, False) in log
    ptt.key(True)
    assert log[-1] == ("rts", True, True)


def _kb(monkeypatch):
    r, w = os.pipe()
    monkeypatch.setattr(sys, "stdin", os.fdopen(r))
    return ht.KeyboardLocal(), w


@pytest.mark.parametrize("answer,sends", [("", True), ("y", True), ("yes", True),
                                           ("n", False), ("q", False), ("i", False),
                                           ("stop", False), ("abort", False)])
def test_confirm_only_sends_on_a_clear_yes(monkeypatch, answer, sends):
    kb, w = _kb(monkeypatch)
    threading.Timer(0.15, kb.lines.put, [answer]).start()
    try:
        assert kb.confirm(timeout=2) is sends
    finally:
        os.close(w)


def test_confirm_ignores_keys_pressed_before_the_prompt(monkeypatch):
    kb, w = _kb(monkeypatch)
    kb.lines.put("")                        # an impatient Enter during processing
    kb.lines.put("")
    try:
        assert kb.confirm(timeout=0.3) is False
    finally:
        os.close(w)


def test_id_due_counts_the_length_of_the_over():
    now = [0.0]
    ids = ht.IdTimer(every_min=10, clock=lambda: now[0])
    ids.mark()
    now[0] = 500
    assert not ids.due(60)                  # ends at 560 s: fine
    assert ids.due(90)                      # would end at 590 s, inside the margin
    now[0] = 550
    assert ids.due(40)


def _run_setup(monkeypatch, tmp_path, local, stt_text="good morning K1ABC", id_len=22050,
               msg_len=2205, **conf_over):
    """cmd_run with fakes; returns (events, played_audio_list, tts, conf)."""
    events, played = [], []

    class PTT(RecPTT):
        def key(self, on):
            events.append(("key", on))

    class TTS(FakeTTS):
        def synth(self, text, lang):
            self.said.append((lang, text))
            n = id_len if text.startswith("This is") else msg_len
            return np.full(n, 0.5 if text.startswith("This is") else 0.1, np.float32), 22050

    tts = TTS()
    real_engine = ht.Engine
    monkeypatch.setattr(ht, "Engine", lambda conf: real_engine(
        conf, stt=FakeSTT(stt_text), translator=ht.PhraseTranslator(upper), tts=tts))
    monkeypatch.setattr(ht, "make_local", lambda conf: local)
    monkeypatch.setattr(ht, "make_ptt", lambda conf: PTT())
    monkeypatch.setattr(ht, "find_device", lambda spec, kind: None)
    monkeypatch.setattr(ht, "record_while", lambda dev, is_down, max_s: tone(1.0, 16000))

    def fake_play(a, r, d, gain=1.0, stop=None):
        events.append(("play", d))
        played.append(np.array(a))
    monkeypatch.setattr(ht, "play", fake_play)
    conf = dict(ht.DEFAULTS, CALLSIGN="K4DIA", RX="0", PTT_LEAD_MS="0", PTT_TAIL_MS="0",
                STATUS_FILE=str(tmp_path / "status.json"), **conf_over)
    return events, played, tts, conf


class ScriptedLocal:
    def __init__(self, presses, answers=()):
        self.presses, self.answers, self.asked = list(presses), list(answers), []

    def wait_press(self):
        return self.presses.pop(0)

    def is_down(self):
        return False

    def end_talk(self):
        pass

    def confirm(self, timeout, what="Send it?"):
        self.asked.append(what)
        return self.answers.pop(0)


def test_id_is_really_in_the_transmitted_audio_and_only_when_due(monkeypatch, tmp_path):
    from argparse import Namespace
    local = ScriptedLocal(["talk", "talk", "quit"], [True, True, False])
    events, played, tts, conf = _run_setup(monkeypatch, tmp_path, local)
    ht.cmd_run(conf, Namespace(no_tx=False))
    first, second = played
    assert np.isclose(first[-22050:], 0.5).all()        # the ID samples went out
    assert not np.isclose(second, 0.5).any()            # second over: no ID due
    # The second over went out without an ID, so quitting offers one.
    assert "end the contact" in local.asked[-1]


def test_id_survives_the_max_tx_cap(monkeypatch, tmp_path):
    from argparse import Namespace
    local = ScriptedLocal(["talk", "quit"], [True])
    events, played, tts, conf = _run_setup(monkeypatch, tmp_path, local, msg_len=22050 * 10,
                                           MAX_TX_SEC="5")
    ht.cmd_run(conf, Namespace(no_tx=False))
    audio = played[0]
    assert len(audio) <= 5 * 22050
    assert np.isclose(audio[-22050:], 0.5).all()        # message trimmed, ID intact


def test_quit_sends_end_of_contact_id_only_after_a_press(monkeypatch, tmp_path):
    from argparse import Namespace
    now = [0.0]
    monkeypatch.setattr(ht.time, "monotonic", lambda: now[0])
    local = ScriptedLocal(["talk", "talk", "quit"], [True, True, True])
    events, played, tts, conf = _run_setup(monkeypatch, tmp_path, local)
    ht.cmd_run(conf, Namespace(no_tx=False))
    assert len(played) == 3 and np.isclose(played[2], 0.5).all()    # ID-only transmission
    assert events.count(("key", True)) == 3


def test_one_failed_over_does_not_end_the_session(monkeypatch, tmp_path, capsys):
    from argparse import Namespace
    local = ScriptedLocal(["talk", "talk", "quit"], [True, True, False])
    events, played, tts, conf = _run_setup(monkeypatch, tmp_path, local)
    calls = []

    def flaky_play(a, r, d, gain=1.0, stop=None):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("USB audio unplugged")
        played.append(np.array(a))
    monkeypatch.setattr(ht, "play", flaky_play)
    ht.cmd_run(conf, Namespace(no_tx=False))
    assert len(calls) == 2 and len(played) == 1         # second over still went out
    assert events == [("key", True), ("key", False), ("key", True), ("key", False),
                      ("key", False)]                   # unkeyed after the failure
    assert "USB audio unplugged" in capsys.readouterr().err
    # The failed over's ID never went out, so the next one carries it.
    assert np.isclose(played[0][-22050:], 0.5).all()


def test_no_tx_never_keys(monkeypatch, tmp_path):
    from argparse import Namespace
    local = ScriptedLocal(["talk", "id", "quit"], [True])
    events, played, tts, conf = _run_setup(monkeypatch, tmp_path, local)
    conf["CALLSIGN"] = "N0CALL"
    ht.cmd_run(conf, Namespace(no_tx=True))
    assert ("key", True) not in events and len(played) == 2


def test_sigterm_while_keyed_unkeys(tmp_path):
    """A real child process, killed mid-transmission, must send the unkey."""
    import signal as _signal
    import subprocess as _sp
    import time as _t
    log = tmp_path / "ptt.log"
    code = textwrap.dedent(f"""
        import importlib.machinery, importlib.util, sys, time, argparse
        import numpy as np
        l = importlib.machinery.SourceFileLoader("ht", {TOOL!r})
        s = importlib.util.spec_from_loader("ht", l); ht = importlib.util.module_from_spec(s)
        l.exec_module(ht)
        class PTT:
            name = "fake"
            def key(self, on):
                print(on, file=open({str(log)!r}, "a"), flush=True)
            def close(self): pass
        class Local:
            def wait_press(self): return "id"
            def confirm(self, *a, **k): return False
        class TTS:
            def synth(self, text, lang): return np.zeros(2205, np.float32), 22050
        real = ht.Engine
        ht.Engine = lambda conf: real(conf, stt=None or object(), translator=ht.PhraseTranslator(
            lambda t, s, d: t), tts=TTS())
        ht.make_local = lambda conf: Local()
        ht.make_ptt = lambda conf: PTT()
        ht.find_device = lambda spec, kind: None
        ht.play = lambda *a, **k: time.sleep(30)        # "transmitting"
        conf = dict(ht.DEFAULTS, CALLSIGN="K4DIA", RX="0", STATUS_FILE="")
        ht.cmd_run(conf, argparse.Namespace(no_tx=False))
    """)
    proc = _sp.Popen([sys.executable, "-c", code], stderr=_sp.PIPE)
    try:
        for _ in range(100):
            if log.exists() and "True" in log.read_text():
                break
            _t.sleep(0.1)
        assert log.exists(), proc.stderr.read().decode()[-800:] if proc.poll() is not None else "timeout"
        proc.send_signal(_signal.SIGTERM)
        proc.wait(timeout=10)
    finally:
        proc.kill()
    assert log.read_text().split()[-1] == "False"


def test_play_uses_its_own_stream_and_honours_stop(monkeypatch):
    import types
    made = []

    class Out:
        def __init__(self, **kw):
            self.kw, self.written, self.calls = kw, 0, []
            made.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.calls.append("close")

        def write(self, block):
            assert block.dtype == np.float32 and block.ndim == 2
            self.written += len(block)

        def stop(self):
            self.calls.append("stop")

        def abort(self):
            self.calls.append("abort")

    fake = types.SimpleNamespace(OutputStream=Out,
                                 query_devices=lambda d, k: {"default_samplerate": 48000})
    monkeypatch.setattr(ht, "_sd", lambda: fake)
    ht.play(tone(0.5, 16000), 16000, None, gain=0.5)
    assert made[0].written == 24000 and made[0].calls == ["stop", "close"]
    stop = threading.Event()
    stop.set()
    ht.play(tone(0.5, 16000), 16000, None, stop=stop)
    assert made[1].written == 0 and made[1].calls == ["abort", "close"]


def test_rx_drops_audio_captured_while_muted_and_survives_errors(monkeypatch, capsys):
    import types
    feed = {}

    class In:
        def __init__(self, callback=None, **kw):
            feed["cb"] = callback

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    fake = types.SimpleNamespace(InputStream=In,
                                 query_devices=lambda d, k: {"default_samplerate": 16000})
    monkeypatch.setattr(ht, "_sd", lambda: fake)
    monkeypatch.setattr(ht, "find_device", lambda spec, kind: None)
    heard, played = [], []

    class Eng:
        def translate_audio(self, audio, src, dst, speak=True):
            heard.append(len(audio))
            return ht.Result(heard="ciao", lang="it",
                             translation=ht.Translation("ciao", "hello", "hello"),
                             audio=np.zeros(10, np.float32), rate=16000)

    monkeypatch.setattr(ht, "play", lambda a, r, d, gain=1.0, stop=None: played.append(stop))
    muted = threading.Event()
    conf = dict(ht.DEFAULTS)
    t = threading.Thread(target=ht._rx_loop, args=(conf, Eng(), ht.Status(""), muted,
                                                   threading.Lock(), "it", "en", None),
                         daemon=True)
    t.start()
    import time as _t
    for _ in range(50):
        if "cb" in feed:
            break
        _t.sleep(0.02)
    block = lambda x: feed["cb"](x.reshape(-1, 1))
    quiet, loud = np.zeros(800, np.float32), tone(0.05, 16000)
    muted.set()
    for _ in range(60):                     # 3 s of our own transmission
        block(loud)
    muted.clear()
    for _ in range(30):
        block(quiet)
    _t.sleep(0.3)
    assert heard == []                      # none of it was translated back to us
    for _ in range(30):                     # a real incoming over
        block(loud)
    for _ in range(30):
        block(quiet)
    for _ in range(50):
        if played:
            break
        _t.sleep(0.02)
    assert len(heard) == 1 and played == [muted]


def test_rx_reports_a_missing_device_instead_of_dying_silently(monkeypatch, capsys):
    def boom(spec, kind):
        raise RuntimeError("No input audio device matching 'USB Audio'")
    monkeypatch.setattr(ht, "_sd", lambda: object())
    monkeypatch.setattr(ht, "find_device", boom)
    ht._rx_loop(dict(ht.DEFAULTS), None, ht.Status(""), threading.Event(), threading.Lock(),
                "it", "en", None)
    assert "Receive translation stopped" in capsys.readouterr().err
