#!/usr/bin/env python3
"""Build MuseScore 4 files of Bach's four-part chorales in chorales/.

usage: build-chorales.py [NAME ...]      e.g. bwv4.8 bwv269; default: all

The notes and text come from the music21 corpus (Margaret Greentree's
encodings from jsbchorales.net, "used by permission"): about 400 chorales,
text under the soprano. Each becomes a closed score like the church scores:
Women (soprano, alto) and Men (tenor, bass), staff names hidden, the text
under the soprano with melisma lines (see build.py's melismas). Instrumental
parts are left out. The two five-part chorales (BWV 27/6, 227/3) get a third
staff: Women (sopranos 1 and 2), Alto, Men.

The pitches are checked against two other editions in sources/:
  bcfb/          the Bach Chorales Figured Bass dataset (CC BY 4.0), after
                 the Neue Bach-Ausgabe: 139 cantata chorales;
  humdrum-370/   Craig Sapp's Humdrum edition of the 370 chorales, after
                 Breitkopf & Härtel (Dörffel, c. 1875).
A pitch is changed to the NBA's when BCFB disagrees with Greentree and
Humdrum doesn't side with Greentree (where it does, the two editions simply
differ and Greentree's note stays). Only where both are the same version in
the same key, and only for notes whose rhythm matches; octave differences
are kept (often a bass or continuo octave). A note where only Humdrum
disagrees is listed as uncertain. chorales/REPORT.md lists it all.

Titles: the hymn and verse from sources/chorale-titles.json (extracted from
Wikipedia's "List of chorale harmonisations by Johann Sebastian Bach"), else
Humdrum's title, music21's chorale list, or the first line of the text.
"""
import sys
sys.dont_write_bytecode = True  # build.py is imported below

import collections, copy, difflib, json, os, re, subprocess, tempfile
from fractions import Fraction
import xml.etree.ElementTree as ET

import build  # MuseScore helpers and the lyric functions
from music21 import corpus, converter, stream, clef, instrument, spanner

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "chorales")
BCFB = os.path.join(HERE, "sources", "bcfb")
HUMDRUM = os.path.join(HERE, "sources", "humdrum-370")
SKIP = {"bwv846"}  # a prelude, not a chorale
LABELS = {"Soprano": "s", "Soprano 1": "s", "Soprano 2": "s2", "Alto": "a", "Tenor": "t", "Bass": "b"}


# ---- sources ----

def greentree():
    return {os.path.basename(str(p)).rsplit(".", 1)[0]: str(p) for p in corpus.getComposer("bach")
            if str(p).endswith((".mxl", ".xml")) and os.path.basename(str(p)).rsplit(".", 1)[0] not in SKIP}


def bcfb_files():
    """{'bwv10.7': [BWV_10.07a_FB.musicxml, BWV_10.07b_FB.musicxml], ...}"""
    out = {}
    for f in sorted(os.listdir(BCFB)):
        m = re.match(r"BWV_(\d+)(?:\.(\d+))?([a-z]?)_FB\.musicxml$", f)
        if m:
            name = f"bwv{m.group(1)}" + (f".{int(m.group(2))}" if m.group(2) else "")
            out.setdefault(name, []).append(os.path.join(BCFB, f))
    return out


def humdrum_files():
    """{'bwv41.6': [(path, title, Breitkopf number)], ...} from the files' !!!SCT records:
    'BWV 41/6 & 171/6', 'BWV 20/7,11', 'BWV 36(2)/8' (= bwv36.8-2)."""
    out = {}
    for f in sorted(os.listdir(HUMDRUM)):
        if not f.endswith(".krn"):
            continue
        path = os.path.join(HUMDRUM, f)
        text = open(path, encoding="utf-8").read()
        sct = re.search(r"^!!!SCT: (.*)$", text, re.M)
        title = re.search(r"^!!!OTL@@DE: (.*)$", text, re.M)
        number = re.search(r"^!!!PC#: (\d+)", text, re.M)
        for part in re.split(r"\s*&\s*", sct.group(1).replace("BWV", "").strip()) if sct else []:
            m = re.match(r"(\d+)(?:\((\d)\))?(?:/([\d,]+))?", part.strip())
            if not m:
                continue
            num, sub, movs = m.groups()
            for mv in movs.split(",") if movs else [None]:
                name = f"bwv{num}" + (f".{mv}" if mv else "") + (f"-{sub}" if sub else "")
                out.setdefault(name, []).append((path, title.group(1).strip() if title else None,
                                                 int(number.group(1)) if number else None))
    return out


def lookup(table, name):
    """A variant (bwv18.5-lz) falls back on its plain number (bwv18.5)."""
    return table.get(name) or table.get(name.split("-")[0]) or []


# ---- comparing editions ----

def part_name(part):
    """The voice the part starts with: some sources add the doubling instruments
    ("Soprano\\rOboe 1,2", "Soprano Oboe 1 Violin1", "Bass Continuo")."""
    line = re.split(r"[\r\n]", part.partName or "")[0].strip()
    m = re.match(r"(Soprano(?: [12]\b)?|Alto|Tenor|Bass|Voice)\b", line)
    return m.group(1) if m else line


def voice_parts(score):
    names = [part_name(p) for p in score.parts]
    if names.count("Voice") == 4:  # BCFB and Humdrum: four "Voice" parts, SATB
        return dict(zip("satb", [p for p, n in zip(score.parts, names) if n == "Voice"]))
    return {LABELS[n]: p for p, n in zip(score.parts, names) if n in LABELS}


def groups(part):
    """[(midi or 'r', quarter length, [notes])], tied notes and consecutive rests merged."""
    out = []
    for n in part.recurse().notesAndRests:
        if n.quarterLength == 0:
            continue
        pitch = "r" if n.isRest else (n.pitch.midi if n.isNote else max(p.midi for p in n.pitches))
        d = Fraction(n.quarterLength).limit_denominator(64)
        tied = n.isNote and n.tie is not None and n.tie.type in ("stop", "continue")
        if out and ((tied and out[-1][0] == pitch) or (pitch == "r" and out[-1][0] == "r")):
            out[-1] = (pitch, out[-1][1] + d, out[-1][2] + [n])
        else:
            out.append((pitch, d, [n]))
    return out


def align(mine, theirs):
    """{voice: {my group index: their group}} for the notes that line up: in equal stretches
    and in replaced stretches with the same rhythm. None when they're different versions
    or in different keys."""
    shifts = collections.Counter(b[0] - a[0] for a, b in zip(mine.get("s", []), theirs.get("s", []))
                                 if a[0] != "r" and b[0] != "r")
    if not shifts or shifts.most_common(1)[0][0] != 0:
        return None, "another key"
    out, same, total = {}, 0, 0
    for v in "satb":
        a, b = mine.get(v, []), theirs.get(v, [])
        if not a or not b:
            continue
        x, y = [(p, d) for p, d, _ in a], [(p, d) for p, d, _ in b]
        out[v] = {}
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
            if op == "equal" or (op == "replace" and [d for _, d in x[i1:i2]] == [d for _, d in y[j1:j2]]):
                for k in range(i2 - i1):
                    out[v][i1 + k] = b[j1 + k]
                same += (i2 - i1) if op == "equal" else 0
        total += len(a)
    if total == 0 or same / total < 0.9:
        return None, "another version"
    return out, None


def check(name, score, bcfb, humdrum):
    """Correct Greentree's pitches by the NBA; returns the report lines."""
    mine = {v: groups(p) for v, p in voice_parts(score).items()}
    sources, notes = {}, []
    for label, paths in (("NBA", bcfb), ("Breitkopf", [p for p, _, _ in humdrum])):
        best = None
        for path in paths:
            try:
                theirs = {v: groups(p) for v, p in voice_parts(converter.parse(path)).items()}
            except Exception as e:  # noqa: BLE001 - a source we can't read is just not used
                notes.append(f"{label} ({os.path.basename(path)}) unreadable: {e}")
                continue
            aligned, why = align(mine, theirs)
            if aligned is None:
                notes.append(f"{label} ({os.path.basename(path)}): {why}, not used")
            elif best is None or sum(map(len, aligned.values())) > sum(map(len, best.values())):
                best = aligned
        if best is not None:
            sources[label] = best
    fixes, variants, uncertain, octaves = [], [], [], 0
    for v, gs in mine.items():
        for i, (pitch, d, ns) in enumerate(gs):
            if pitch == "r" or ns[0].isChord:
                continue
            nba = sources.get("NBA", {}).get(v, {}).get(i)
            bk = sources.get("Breitkopf", {}).get(v, {}).get(i)
            where = f"m{ns[0].measureNumber} {dict(s='S', s2='S2', a='A', t='T', b='B')[v]}"
            if nba and nba[0] != "r" and nba[0] != pitch:
                if (nba[0] - pitch) % 12 == 0:
                    octaves += 1
                elif bk and bk[0] == pitch:
                    variants.append(f"{where}: {ns[0].nameWithOctave} (Breitkopf), NBA {nba[2][0].nameWithOctave}")
                else:
                    new = nba[2][0].pitch
                    fixes.append(f"{where}: {ns[0].nameWithOctave} → {new.nameWithOctave}")
                    for n in ns:
                        n.pitch = copy.deepcopy(new)
            elif not nba and bk and bk[0] != "r" and bk[0] != pitch:
                if (bk[0] - pitch) % 12 == 0:
                    octaves += 1
                else:
                    uncertain.append(f"{where}: {ns[0].nameWithOctave}, Breitkopf {bk[2][0].nameWithOctave}")
    return {"sources": sorted(sources), "notes": notes, "fixes": fixes, "variants": variants,
            "uncertain": uncertain, "octaves": octaves}


# ---- the closed score ----

STAVES = [("Women", ["s", "a"], clef.TrebleClef), ("Men", ["t", "b"], clef.BassClef)]
STAVES5 = [("Women", ["s", "s2"], clef.TrebleClef), ("Alto", ["a"], clef.TrebleClef),
           ("Men", ["t", "b"], clef.BassClef)]


def closed_score(score):
    parts = voice_parts(score)
    dropped = [part_name(p) for p in score.parts if p not in parts.values()]
    out = stream.Score()
    for name, labels, make_clef in STAVES5 if "s2" in parts else STAVES:
        staff = stream.Part(id=name)
        staff.partName = name
        staff.insert(0, instrument.Choir())
        sources = [list(parts[l].getElementsByClass(stream.Measure)) for l in labels]
        if len({len(s) for s in sources}) != 1:
            raise ValueError(f"{name}: the voices have different numbers of measures")
        mapping = {}
        for i, ref in enumerate(sources[0]):
            m = stream.Measure(number=ref.number)
            m.numberSuffix = ref.numberSuffix
            m.paddingLeft, m.paddingRight = ref.paddingLeft, ref.paddingRight
            for side in ("leftBarline", "rightBarline"):
                if getattr(ref, side) is not None:
                    setattr(m, side, copy.deepcopy(getattr(ref, side)))
            for el in ref.getElementsByClass(["KeySignature", "TimeSignature"]):
                m.insert(el.offset, copy.deepcopy(el))
            if i == 0:
                m.insert(0, make_clef())
            mapping[id(ref)] = m
            for vi, src in enumerate(s[i] for s in sources):
                mapping[id(src)] = m
                v = stream.Voice(id=str(vi + 1))
                for el in src.recurse().notesAndRests:
                    new = copy.deepcopy(el)
                    new.stemDirection = "unspecified"
                    mapping[id(el)] = new
                    v.insert(el.getOffsetInHierarchy(src), new)
                m.insert(0, v)
            staff.append(m)
        for l in labels:  # slurs and volta brackets, re-pointed at the copies
            for sp in parts[l].spannerBundle:
                if isinstance(sp, (spanner.Slur, spanner.RepeatBracket)):
                    els = [mapping.get(id(e)) for e in sp.getSpannedElements()]
                    if not els or any(e is None for e in els):
                        continue
                    if isinstance(sp, spanner.Slur):
                        staff.insert(0, spanner.Slur(els))
                    elif l == labels[0]:  # a volta once per staff
                        staff.insert(0, spanner.RepeatBracket(els, number=sp.number))
        out.insert(0, staff)
    return out, dropped


# ---- titles ----

def text_incipit(score):
    """The soprano's first line of text, up to the first punctuation."""
    sop = voice_parts(score).get("s")
    words, word = [], ""
    for n in sop.recurse().notes if sop is not None else []:
        ly = next((l for l in n.lyrics if l.number == 1), None)
        if ly is None or not ly.text:
            continue
        word += ly.text
        if ly.syllabic in (None, "single", "end"):
            words.append(word)
            word = ""
            if re.search(r"[,.;:!?]$", words[-1]):
                break
    return re.sub(r"[,.;:]$", "", " ".join(words)) or None


TITLES = os.path.join(HERE, "sources", "chorale-titles.json")  # from Wikipedia's list of the chorales


def wiki(name):
    table = json.load(open(TITLES, encoding="utf-8"))
    return table.get(name[3:]) or table.get(name[3:].split("-")[0]) or {}


def title_of(name, score, humdrum):
    """The hymn: from Wikipedia's list, Humdrum, music21's list, or the first line of text."""
    if wiki(name).get("hymn"):
        return wiki(name)["hymn"]
    if humdrum and humdrum[0][1]:
        return humdrum[0][1]
    m = re.match(r"bwv(\d+)$", name)
    if m:
        entry = corpus.chorales.ChoraleList().byBWV.get(int(m.group(1)))
        if entry:
            return entry["title"]
    return text_incipit(score) or "Choral"


def subtitle_of(name, humdrum):
    """BWV number (with Greentree's variant), verse, Riemenschneider number."""
    bwv = name[3:].replace("-", " (") + (")" if "-" in name else "")
    numbers = sorted({n for _, _, n in humdrum if n}) or (
        [int(wiki(name)["riemenschneider"])] if wiki(name).get("riemenschneider") else [])
    verse = wiki(name).get("verse")
    return " · ".join([f"BWV {bwv}"] + ([verse] if verse else [])
                      + ([f"Riemenschneider {', '.join(map(str, numbers))}"] if numbers else []))


def finish(mscx, title, subtitle):
    """Title frame, hidden staff names, melisma lines."""
    root = build.read_mscx(mscx)
    score = root.find("Score")
    first = score.find("Staff")
    vbox = first.find("VBox")
    if vbox is None:
        vbox = ET.Element("VBox")
        ET.SubElement(vbox, "height").text = "10"
        first.insert(0, vbox)
    for t in vbox.findall("Text"):
        vbox.remove(t)
    vbox.append(build.text_el("title", title))
    vbox.append(build.text_el("subtitle", subtitle))
    vbox.append(build.text_el("composer", "Johann Sebastian Bach"))
    for tag in score.findall("metaTag"):
        if tag.get("name") == "workTitle":
            tag.text = f"{title} ({subtitle.split(' · ')[0]})"
        elif tag.get("name") == "composer":
            tag.text = "Johann Sebastian Bach"
    for part in score.findall("Part"):
        for inst in part.iter("Instrument"):
            for tag in ("longName", "shortName"):
                for el in inst.findall(tag):
                    inst.remove(el)
    for ly in score.iter("Lyrics"):
        for t in ly.findall("ticks_f"):
            ly.remove(t)
    for parent in score.iter():  # some sources force stems (chords, beams), against the two voices
        for el in parent.findall("StemDirection"):
            parent.remove(el)
    build.melismas(score)
    build.write_mscx(root, mscx)


def batch(jobs):
    """Convert with one MuseScore run: {name: (in, out)}; returns the names that failed."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump([{"in": a, "out": b} for a, b in jobs.values()], f)
    for _, b in jobs.values():
        if os.path.exists(b):
            os.remove(b)
    subprocess.run([build.MSCORE, "-j", f.name], capture_output=True, text=True)
    os.remove(f.name)
    return [n for n, (_, b) in jobs.items() if not os.path.exists(b) or os.path.getsize(b) == 0]


def report(results, failures):
    lines = ["# Chorales: build report", "",
             "Made by `build-chorales.py` from the music21 corpus (Margaret Greentree's",
             "encodings), checked against the NBA (BCFB dataset) and Breitkopf (Humdrum",
             "370 chorales). See the script for the rules.", ""]
    total = collections.Counter()
    for r in results.values():
        total["chorales"] += 1
        total["fixes"] += len(r["fixes"])
        total["variants"] += len(r["variants"])
        total["uncertain"] += len(r["uncertain"])
        total["checked against the NBA"] += "NBA" in r["sources"]
        total["checked against Breitkopf"] += "Breitkopf" in r["sources"]
        total["without text"] += not r["text"]
    lines += [f"- {k}: {v}" for k, v in total.items()] + [""]
    if failures:
        lines += ["## Not built", ""] + [f"- {n}: {why}" for n, why in sorted(failures.items())] + [""]
    for name in sorted(results, key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)]):
        r = results[name]
        lines.append(f"## {name}: {r['title']}")
        lines.append("")
        lines.append(f"Checked against: {', '.join(r['sources']) or 'nothing'}"
                     + ("" if r["text"] else "; no text in the source")
                     + (f"; instruments left out: {', '.join(r['dropped'])}" if r["dropped"] else "")
                     + (f"; {r['octaves']} octave differences kept" if r["octaves"] else ""))
        for key, head in (("fixes", "Corrected to the NBA"), ("variants", "Editions differ, Greentree kept"),
                          ("uncertain", "Uncertain (Breitkopf differs, no NBA)"), ("notes", "Notes")):
            if r[key]:
                lines.append(f"- {head}: " + "; ".join(r[key]))
        lines.append("")
    text = re.sub(r"(?<=[A-G])-(?=-?\d)", "b", "\n".join(lines))  # music21's E-4 is Eb4
    open(os.path.join(OUT, "REPORT.md"), "w").write(text)


def main():
    names = sys.argv[1:] or sorted(greentree())
    gt, bc, hd = greentree(), bcfb_files(), humdrum_files()
    os.makedirs(OUT, exist_ok=True)
    results_path = os.path.join(OUT, ".results.json")
    results = json.load(open(results_path)) if os.path.exists(results_path) and sys.argv[1:] else {}
    failures = {}
    with tempfile.TemporaryDirectory() as tmp:
        jobs = {}
        for name in names:
            if name not in gt:
                sys.exit(f"no chorale {name} in the corpus")
            try:
                score = converter.parse(gt[name])
                hum = lookup(hd, name)
                result = check(name, score, lookup(bc, name), hum)
                closed, dropped = closed_score(score)
                xml = os.path.join(tmp, f"{name}.musicxml")
                try:
                    closed.write("musicxml", fp=xml)
                except Exception:  # noqa: BLE001 - music21 splits over-full bars (a final breve
                    closed.write("musicxml", fp=xml, makeNotation=False)  # in 4/4) and fails
            except Exception as e:  # noqa: BLE001 - one odd source shouldn't stop the rest
                failures[name] = f"{type(e).__name__}: {e}"
                print(f"{name}: FAILED ({failures[name]})", flush=True)
                continue
            result.update(title=title_of(name, score, hum), subtitle=subtitle_of(name, hum), dropped=dropped,
                          text=any(n.lyrics for n in score.recurse().notes))
            results[name] = result
            jobs[name] = xml
            print(f"{name}: {len(result['fixes'])} corrected, {len(result['uncertain'])} uncertain", flush=True)
        def drop(names, why):
            for n in names:
                failures[n] = why
                jobs.pop(n, None)
                results.pop(n, None)
                if os.path.exists(os.path.join(OUT, f"{n}.mscz")):
                    os.remove(os.path.join(OUT, f"{n}.mscz"))
        drop(batch({n: (xml, os.path.join(tmp, f"{n}.mscx")) for n, xml in jobs.items()}),
             "MuseScore couldn't import the MusicXML")
        for name in jobs:
            finish(os.path.join(tmp, f"{name}.mscx"), results[name]["title"], results[name]["subtitle"])
        drop(batch({n: (os.path.join(tmp, f"{n}.mscx"), os.path.join(OUT, f"{n}.mscz")) for n in jobs}),
             "MuseScore couldn't save it")
        drop(batch({n: (os.path.join(OUT, f"{n}.mscz"), os.path.join(tmp, f"{n}.check.musicxml")) for n in jobs}),
             "doesn't load cleanly in MuseScore (corrupt measures)")
    json.dump(results, open(results_path, "w"), ensure_ascii=False, indent=1)
    report(results, failures)
    if failures:
        print(f"not built: {', '.join(sorted(failures))}")
    print(f"{len(jobs)} chorales in {os.path.relpath(OUT, HERE)}/; report in chorales/REPORT.md")


if __name__ == "__main__":
    main()
