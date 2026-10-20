#!/usr/bin/env python3
"""Build the MuseScore 4 scores bwv4/bwv4_N.mscz and bwv80/bwv80_N.mscz from
the Capella files in sources/capella (from bach-cantatas.com).

usage: build.py [MOVEMENT ...]      e.g. build.py 4.8 80.5; default: all

Each Capella file is imported with MuseScore's command line. Three of them
have bars whose notes don't add up, which MuseScore refuses without -f, so
the import is forced and the defects are repaired here:

  BWV 80/5  violin II, m56: a sixteenth short. Oboe 2 doubles violin II
            (mm55 and 57 are identical), so its last sixteenth is copied.
  BWV 4/8   the barlines were placed per staff and wrongly: the written-out
            repeat is a beat off, fermata bars hold 5/4, and a stray rest
            bar ends it. The music is re-barred as in the BGA (pickup, then
            16 bars of 4/4) with music21, the stray rest dropped. Checked
            against the BGA (BWV004-BGA.pdf, p. 124): the first line of
            text in alto and bass ran one note early ("le" on the last
            note of bar 1), with ties where the BGA re-strikes the note
            ("le-ben", "fla-den", "Gna-den"); those are fixed.

Every movement gets a clean title frame (Capella's rich-text titles came
through as HTML with CSS): the movement's first words, the cantata and
number, and the composer. Capella's page headers, which landed in the
music as staff texts, are removed (BWV 80/8's text source goes into the
title frame). The result must load in MuseScore without -f.
BWV_0004_8_2.cap (a hymn setting of verses 2, 3, 5, 6) is no part of the
cantata and isn't built.

Needs music21 (BWV 4/8 only).
"""
import copy, html, os, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(HERE, "sources", "capella")
MSCORE = "/Applications/MuseScore 4.app/Contents/MacOS/mscore"

CANTATAS = {4: "Christ lag in Todesbanden", 80: "Ein feste Burg ist unser Gott"}
MOVEMENTS = {  # (BWV, number): (first words, heading)
    (4, 1): ("Sinfonia", "1. Sinfonia"),
    (4, 2): ("Christ lag in Todes Banden", "2. Versus I"),
    (4, 3): ("Den Tod niemand zwingen kunnt", "3. Versus II"),
    (4, 4): ("Jesus Christus, Gottes Sohn", "4. Versus III"),
    (4, 5): ("Es war ein wunderlicher Krieg", "5. Versus IV"),
    (4, 6): ("Hier ist das rechte Osterlamm", "6. Versus V"),
    (4, 7): ("So feiern wir das hohe Fest", "7. Versus VI"),
    (4, 8): ("Wir essen und leben wohl", "8. Versus VII (Choral)"),
    (80, 1): ("Ein feste Burg ist unser Gott", "1. Chor"),
    (80, 2): ("Alles, was von Gott geboren", "2. Aria (Sopran, Bass)"),
    (80, 5): ("Und wenn die Welt voll Teufel wär", "5. Choral"),
    (80, 7): ("Wie selig sind doch die", "7. Duetto (Alt, Tenor)"),
    (80, 8): ("Das Wort sie sollen lassen stahn", "8. Choral"),
}
# Capella's page headers, which the import put into the music as staff texts
STRAY_TEXTS = {
    (4, 1): ["1. SINFONIA.", "Johann Sebastian Bach BWV 4"],
    (4, 5): ["5. Versus 4"],
    (4, 7): ["41"],
    (80, 1): ["Ein feste Burg ist unser Gott"],
    (80, 8): ["Ein feste Burg ist unser Gott", '(Kant. 80 "Ein\u00b4 feste Burg ist unser Gott")',
              "Worte: Martin Luther 1529 Quelle: Jos. Klug G.B. 1535"],
}
LYRICIST = {(80, 8): "Worte: Martin Luther 1529 · Quelle: Jos. Klug, Geistliche Lieder 1535"}
DURATIONS = {"long": Fraction(4), "breve": Fraction(2), "whole": Fraction(1), "half": Fraction(1, 2), "quarter": Fraction(1, 4),
             "eighth": Fraction(1, 8), "16th": Fraction(1, 16), "32nd": Fraction(1, 32)}


def mscore(*args):
    """Run MuseScore; it sometimes exits 134 after writing, so the caller checks the output."""
    return subprocess.run([MSCORE, *args], capture_output=True, text=True)


def convert(src, dst, force=False):
    if os.path.exists(dst):
        os.remove(dst)
    r = mscore(*(["-f"] if force else []), "-o", dst, src)
    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        sys.exit(f"MuseScore couldn't convert {src} to {dst} (exit {r.returncode})")


def read_mscx(path):
    text = open(path, encoding="utf-8").read()
    # MuseScore writes HTML entities such as &nbsp; that XML doesn't define
    text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)(\w+);",
                  lambda m: html.unescape(m.group()), text)
    return ET.fromstring(text)


def write_mscx(root, path):
    with open(path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8"))


def text_el(style, text):
    t = ET.Element("Text")
    ET.SubElement(t, "style").text = style
    ET.SubElement(t, "text").text = text
    return t


def title_frame(score, bwv, n):
    """Replace the first frame's texts by title, subtitle and composer."""
    words, heading = MOVEMENTS[bwv, n]
    first = score.find("Staff")
    vbox = first.find("VBox")
    if vbox is None:
        vbox = ET.Element("VBox")
        first.insert(0, vbox)
    for t in vbox.findall("Text"):
        vbox.remove(t)
    for el in vbox:
        if el.tag == "height":
            el.text = "10"
    vbox.append(text_el("title", words))
    vbox.append(text_el("subtitle", f"BWV {bwv} · {CANTATAS[bwv]} · {heading}"))
    vbox.append(text_el("composer", "Johann Sebastian Bach"))
    if (bwv, n) in LYRICIST:
        vbox.append(text_el("lyricist", LYRICIST[bwv, n]))
    for tag in score.findall("metaTag"):
        if tag.get("name") == "workTitle":
            tag.text = f"{words} (BWV {bwv}/{n})"
        elif tag.get("name") == "composer":
            tag.text = "Johann Sebastian Bach"


def plain(text_el):
    """A <text> element's text without markup, spaces collapsed."""
    if text_el is None:
        return ""
    el = copy.deepcopy(text_el)
    for br in el.iter("br"):
        br.tail = " " + (br.tail or "")
    return " ".join(ET.tostring(el, encoding="unicode", method="text").split())


def remove_stray_texts(score, bwv, n):
    wanted = {" ".join(t.split()) for t in STRAY_TEXTS.get((bwv, n), [])}
    found = set()
    for voice in score.iter("voice"):
        for el in list(voice):
            if el.tag == "StaffText" and plain(el.find("text")) in wanted:
                found.add(plain(el.find("text")))
                voice.remove(el)
    if found != wanted:
        sys.exit(f"BWV {bwv}/{n}: stray texts not found: {sorted(wanted - found)}")


def chord_at(score, staff, measure, tick, voice=0):
    """The Chord at a tick (in whole notes from the measure start) of a staff's measure (both 1-based)."""
    m = score.findall("Staff")[staff - 1].findall("Measure")[measure - 1]
    t = Fraction(0)
    for el in m.findall("voice")[voice]:
        if el.tag in ("Chord", "Rest"):
            if t == tick:
                if el.tag != "Chord":
                    sys.exit(f"staff {staff} m{measure} at {tick}: a rest, not a chord")
                return el
            t += DURATIONS[el.findtext("durationType")] * (2 - Fraction(1, 2 ** int(el.findtext("dots") or 0)))
        elif el.tag == "location":
            t += Fraction(el.findtext("fractions"))
    sys.exit(f"staff {staff} m{measure}: no chord at {tick}")


# ---- BWV 80/5 ----

def repair_80_5(score):
    """Violin II, m56: add the last sixteenth, from oboe 2, which doubles it."""
    staves = score.findall("Staff")
    names = [p.findtext("trackName").strip() for p in score.findall("Part")]
    oboe, violin = staves[names.index("Oboe 2")], staves[names.index("Violine II")]
    source = [el for el in oboe.findall("Measure")[55].find("voice") if el.tag == "Chord"][-1]
    target = violin.findall("Measure")[55].find("voice")
    length = sum(DURATIONS[el.findtext("durationType")] * (2 - Fraction(1, 2 ** int(el.findtext("dots") or 0)))
                 for el in target if el.tag in ("Chord", "Rest"))
    if length != Fraction(11, 16) or source.findtext("durationType") != "16th":
        sys.exit("BWV 80/5: violin II m56 isn't as expected; not repaired")
    note = copy.deepcopy(source)
    for parent in note.iter():
        for c in list(parent):
            if c.tag in ("eid", "Spanner", "Lyrics"):
                parent.remove(c)
    target.append(note)


# ---- BWV 4/8 ----

def positions(mscx):
    """{(staff, voice): [(onset, length, midi pitches)]} in quarters, both 0-based, from
    MuseScore's own file. A measure keeps its nominal place even when its notes run
    over; the next measure's notes then start later, after a <location>."""
    out = {}
    for si, st in enumerate(read_mscx(mscx).find("Score").findall("Staff")):
        base, sig = Fraction(0), None
        for m in st.findall("Measure"):
            for ts in m.iter("TimeSig"):
                sig = Fraction(int(ts.findtext("sigN")), int(ts.findtext("sigD")))
            length = (Fraction(m.get("len")) if m.get("len") else sig) * 4
            for vi, v in enumerate(m.findall("voice")):
                t = Fraction(0)
                for el in v:
                    if el.tag == "location":
                        t += Fraction(el.findtext("fractions")) * 4
                    elif el.tag in ("Chord", "Rest"):
                        kind = el.findtext("durationType")
                        d = (Fraction(el.findtext("duration")) if kind == "measure" else DURATIONS[kind]
                             * (2 - Fraction(1, 2 ** int(el.findtext("dots") or 0)))) * 4
                        pitches = sorted(int(n.findtext("pitch")) for n in el.findall("Note"))
                        out.setdefault((si, vi), []).append((base + t, d, pitches))
                        t += d
            base += length
    return out


def rebar_4_8(src, mscx, dst):
    """Re-bar the chorale: pickup of a quarter, then 16 bars of 4/4, as in the BGA. The
    notes come from the MusicXML src, their places from MuseScore's file mscx: MuseScore's
    export of the over-full bars has spurious gaps."""
    from music21 import converter, stream, meter, spanner, layout
    s = converter.parse(src)
    where = positions(mscx)
    out = stream.Score()
    out.metadata = s.metadata
    bars = [Fraction(0), Fraction(1)] + [Fraction(1 + 4 * k) for k in range(1, 17)]
    end = bars[-1]
    new_parts = {}
    for si, part in enumerate(s.parts):  # a part per staff: the keyboard is two PartStaffs
        new_part = type(part)()
        new_part.id, new_part.partName = part.id, part.partName
        new_parts[id(part)] = new_part
        first = part.getElementsByClass(stream.Measure)[0]
        by_voice = {}
        for m in part.getElementsByClass(stream.Measure):
            for v in list(m.voices) or [m]:
                vid = str(v.id) if v is not m else "1"
                by_voice.setdefault(vid, []).extend(el for el in v.notesAndRests if el.quarterLength)
        by_voice = {vid: els for vid, els in by_voice.items() if els}
        events, mapping = {}, {}
        for vi, vid in enumerate(sorted(by_voice, key=int)):
            # the stray rest bar at the end: its rest lies under the last note, which runs
            # over into it (MuseScore exports that rest with length 0)
            places, reach = [], Fraction(0)
            for at, length, pitches in where.get((si, vi), []):
                if pitches or at >= reach:
                    places.append((at, length, pitches))
                reach = max(reach, at + length)
            if len(places) != len(by_voice[vid]):
                sys.exit(f"BWV 4/8 {part.partName} voice {vid}: {len(by_voice[vid])} notes in the "
                         f"MusicXML, {len(places)} in MuseScore's file")
            for el, (at, length, pitches) in zip(by_voice[vid], places):
                mine = sorted(p.midi for p in el.pitches)
                if Fraction(el.quarterLength).limit_denominator(64) != length or mine != pitches:
                    sys.exit(f"BWV 4/8 {part.partName} voice {vid} at {at}: {el} isn't {pitches}, {length}")
                if at >= end:
                    if not el.isRest:
                        sys.exit(f"BWV 4/8 {part.partName}: a note after the last bar")
                    continue  # the stray rest bar
                if any(at < b < at + length for b in bars):
                    sys.exit(f"BWV 4/8 {part.partName}: {el} at {at} crosses a barline")
                new = copy.deepcopy(el)
                mapping[id(el)] = new
                events.setdefault(vid, []).append((at, new))
        for vid, evs in events.items():
            if vid == min(events) and sum(Fraction(e.quarterLength).limit_denominator(64) for _, e in evs) != end:
                sys.exit(f"BWV 4/8 {part.partName}: voice {vid} isn't {end} quarters long")
        for k in range(len(bars) - 1):
            m = stream.Measure(number=k)
            if k == 0:
                for c in first.getElementsByClass(["Instrument", "Clef", "KeySignature"]):
                    m.insert(0, copy.deepcopy(c))
                m.insert(0, meter.TimeSignature("4/4"))
                m.paddingLeft = 3.0
            for vid, evs in sorted(events.items()):
                v = stream.Voice(id=vid)
                for at, el in evs:
                    if bars[k] <= at < bars[k + 1]:
                        v.insert(float(at - bars[k]), el)
                if len(v.notesAndRests):
                    m.insert(0, v)
            new_part.append(m)
        # slurs and other spanners, re-pointed at the copied notes
        for sp in part.spannerBundle:
            notes = [mapping[id(n)] for n in sp.getSpannedElements() if id(n) in mapping]
            if len(notes) == len(sp.getSpannedElements()) and notes:
                new = type(sp)(notes) if isinstance(sp, spanner.Slur) else None
                if new is not None:
                    new_part.insert(0, new)
        out.insert(0, new_part)
    for group in s.getElementsByClass(layout.StaffGroup):
        members = [new_parts[id(p)] for p in group.getSpannedElements() if id(p) in new_parts]
        out.insert(0, layout.StaffGroup(members, name=group.name, abbreviation=group.abbreviation,
                                        symbol=group.symbol, barTogether=group.barTogether))
    out.write("musicxml", fp=dst)


def untie(score, staff, start, end):
    """Remove the tie from the chord at start (measure, tick) to the one at end."""
    for (m, t), side in ((start, "next"), (end, "prev")):
        note = chord_at(score, staff, m, t).find("Note")
        ties = [sp for sp in note.findall("Spanner") if sp.get("type") == "Tie" and sp.find(side) is not None]
        if len(ties) != 1:
            sys.exit(f"BWV 4/8 staff {staff} m{m} at {t}: no tie to remove")
        note.remove(ties[0])


def duration(el):
    kind = el.findtext("durationType")
    if kind == "measure":
        return Fraction(el.findtext("duration"))
    return DURATIONS[kind] * (2 - Fraction(1, 2 ** int(el.findtext("dots") or 0)))


def events(score, staff, voice):
    """[(onset, element)] of the Chords and Rests of a voice of a staff (0-based), in whole
    notes. A measure keeps its nominal place, also in a forced import."""
    out, base, sig = [], Fraction(0), None
    for m in score.findall("Staff")[staff].findall("Measure"):
        for ts in m.iter("TimeSig"):
            sig = Fraction(int(ts.findtext("sigN")), int(ts.findtext("sigD")))
        vs = m.findall("voice")
        if voice < len(vs):
            t = Fraction(0)
            for el in vs[voice]:
                if el.tag == "location":
                    t += Fraction(el.findtext("fractions"))
                elif el.tag in ("Chord", "Rest"):
                    out.append((base + t, el))
                    t += duration(el)
        base += Fraction(m.get("len")) if m.get("len") else sig
    return out


def lyric(chord, verse="0"):
    return next((ly for ly in chord.findall("Lyrics") if (ly.findtext("no") or "0") == verse), None)


def set_syllabic(ly, syllabic):
    el = ly.find("syllabic")
    if syllabic == "single":
        if el is not None:
            ly.remove(el)
    else:
        if el is None:
            el = ET.Element("syllabic")
            ly.insert(0, el)
        el.text = syllabic


def copy_marks(old, new):
    """Lyrics and fermatas from the forced import onto the re-barred score, chord by chord
    (matched by place and pitches): MuseScore's MusicXML export loses the fermatas and
    muddles the syllables."""
    def marks(c):
        return [x for x in c if x.tag == "Lyrics" or (x.tag == "Articulation" and
                                                      (x.findtext("subtype") or "").startswith("fermata"))]

    def chords(score, si, reach=None):
        found = {}
        for vi in range(4):
            for at, el in events(score, si, vi):
                if el.tag == "Chord" and (reach is None or at < reach):
                    key = (at, tuple(sorted(n.findtext("pitch") for n in el.findall("Note"))))
                    found.setdefault(key, []).append(el)
        return found

    end = sum((Fraction(m.get("len")) if m.get("len") else Fraction(1))
              for m in new.find("Staff").findall("Measure"))
    for si in range(len(new.findall("Staff"))):
        a, b = chords(old, si, end), chords(new, si)
        if sorted(a) != sorted(b) or any(len(a[k]) != len(b[k]) for k in a):
            sys.exit(f"staff {si + 1}: the chords differ after re-barring")
        for key in a:
            for x, y in zip(a[key], b[key]):
                for c in marks(y):
                    y.remove(c)
                at = next((i for i, c in enumerate(y) if c.tag in ("Spanner", "Note")), len(y))
                for c in marks(x):
                    c = copy.deepcopy(c)
                    strip_eids(c)
                    y.insert(at, c)
                    at += 1


def strip_eids(el):
    for parent in el.iter():
        for c in parent.findall("eid"):
            parent.remove(c)


def verses(score, si, vi):
    return sorted({ly.findtext("no") or "0" for _, el in events(score, si, vi) if el.tag == "Chord"
                   for ly in el.findall("Lyrics")})


def normalize_lyrics(score):
    """Capella's syllables to words: a syllable joins the next one when it says so (begin,
    middle) or when empty syllables, Capella's hyphen over a melisma, lie between them.
    The empty syllables go; begin/middle/end/single follow from the joins."""
    for si in range(len(score.findall("Staff"))):
        for vi in range(2):
            chords = [el for _, el in events(score, si, vi) if el.tag == "Chord"]
            for verse in verses(score, si, vi):
                items = [lyric(c, verse) for c in chords]
                real = [i for i, ly in enumerate(items) if ly is not None and (ly.findtext("text") or "").strip()]
                joins = []
                for k, i in enumerate(real):
                    nxt = real[k + 1] if k + 1 < len(real) else None
                    joins.append(nxt is not None and (
                        (items[i].findtext("syllabic") or "single") in ("begin", "middle")
                        or any(items[j] is not None for j in range(i + 1, nxt))))
                for k, i in enumerate(real):
                    ly = items[i]
                    prev = k > 0 and joins[k - 1]
                    set_syllabic(ly, {(False, False): "single", (False, True): "begin",
                                      (True, True): "middle", (True, False): "end"}[prev, joins[k]])
                    ly.find("text").text = ly.findtext("text").strip()
                    for t in ly.findall("ticks_f"):
                        ly.remove(t)
                for i, ly in enumerate(items):
                    if ly is not None and i not in real:
                        chords[i].remove(ly)


def tied_back(chord):
    return all(any(sp.get("type") == "Tie" and sp.find("prev") is not None for sp in n.findall("Spanner"))
               for n in chord.findall("Note"))


def phrase_ends(score, staff, voice):
    """Onsets (whole notes) of the voice's notes with a fermata, and the ends of the measures
    that close a repeat: a melisma doesn't run past them."""
    fermatas, repeats, base, sig = set(), set(), Fraction(0), None
    for m in score.findall("Staff")[staff].findall("Measure"):
        for ts in m.iter("TimeSig"):
            sig = Fraction(int(ts.findtext("sigN")), int(ts.findtext("sigD")))
        vs = m.findall("voice")
        if voice < len(vs):
            t = Fraction(0)
            for el in vs[voice]:
                if el.tag == "location":
                    t += Fraction(el.findtext("fractions"))
                elif el.tag == "Fermata" or (el.tag == "Chord" and any(
                        (a.findtext("subtype") or "").startswith("fermata") for a in el.findall("Articulation"))):
                    fermatas.add(base + t)
                if el.tag in ("Chord", "Rest"):
                    t += duration(el)
        base += Fraction(m.get("len")) if m.get("len") else sig
        if m.find("endRepeat") is not None:
            repeats.add(base)
    return fermatas, repeats


def melismas(score):
    """A syllable sung on several notes gets a melisma line to the start of its last note;
    a melisma inside a word splits the word there ("O-ster-fla ___ den"). It ends at a
    fermata (the end of a phrase), a rest or the end of a repeat."""
    for si in range(len(score.findall("Staff"))):
        for vi in range(2):
            evs = events(score, si, vi)
            fermatas, repeats = phrase_ends(score, si, vi)
            for verse in verses(score, si, vi):
                syll = [i for i, (_, el) in enumerate(evs) if el.tag == "Chord" and lyric(el, verse) is not None]
                for k, i in enumerate(syll):
                    last, j = None, i + 1
                    while (evs[i][0] not in fermatas and j < len(evs) and evs[j][1].tag == "Chord"
                           and lyric(evs[j][1], verse) is None
                           and not any(evs[j - 1][0] < r <= evs[j][0] for r in repeats)):
                        if not tied_back(evs[j][1]):
                            last = j
                        if evs[j][0] in fermatas:
                            break
                        j += 1
                    if last is None:
                        continue
                    ly = lyric(evs[i][1], verse)
                    ticks = evs[last][0] - evs[i][0]
                    t = ET.Element("ticks_f")
                    t.text = f"{ticks.numerator}/{ticks.denominator}"
                    ly.insert(0, t)
                    syllabic = ly.findtext("syllabic") or "single"
                    if syllabic in ("begin", "middle") and k + 1 < len(syll):
                        set_syllabic(ly, {"begin": "single", "middle": "end"}[syllabic])
                        nxt = lyric(evs[syll[k + 1]][1], verse)
                        set_syllabic(nxt, {"middle": "begin", "end": "single"}.get(
                            nxt.findtext("syllabic") or "single", nxt.findtext("syllabic") or "single"))


def set_lyric(score, staff, measure, tick, text=None, syllabic="single"):
    """Set (text given) or remove (text None) the syllable of a chord."""
    chord = chord_at(score, staff, measure, tick)
    for ly in chord.findall("Lyrics"):
        chord.remove(ly)
    if text is None:
        return
    ly = ET.Element("Lyrics")
    ET.SubElement(ly, "text").text = text
    set_syllabic(ly, syllabic)
    at = next((i for i, c in enumerate(chord) if c.tag in ("Spanner", "Note")), len(chord))
    chord.insert(at, ly)


def repair_4_8(score):
    """Ties and text placement of the first section, as in the BGA. Measure 1 is the
    pickup; ticks in whole notes. Staves: soprano, alto, tenor, bass (alto and bass carry
    the text), keyboard."""
    q = Fraction(1, 4)
    # alto and bass: "es-sen und | le-ben wohl im", not "es-sen und le- | ben"
    for staff in (2, 4):
        set_lyric(score, staff, 2, 2 * q, "und")
        set_lyric(score, staff, 2, 3 * q)
        set_lyric(score, staff, 3, 0, "le", "begin")
        set_lyric(score, staff, 3, q, "ben", "end")
    untie(score, 2, (3, 0), (3, q))
    # alto: "O-ster | fla-den," and "Wort der | Gna-den." on re-struck notes
    for ster, gna, text, syllabic, punct in ((4, 5, "fla", "middle", "den,"), (8, 9, "Gna", "begin", "den.")):
        untie(score, 2, (ster, 3 * q), (gna, 0))
        set_lyric(score, 2, gna, 0, text, syllabic)
        set_lyric(score, 2, gna, q)
        set_lyric(score, 2, gna, 2 * q, punct, "end")
    # Capella's beams followed its misplaced barlines: beam by the time signature instead
    for chord in score.iter("Chord"):
        for el in chord.findall("BeamMode"):
            chord.remove(el)
    # the staves had Capella's placeholder names ("unbenannt2"); no names, as in Capella
    for part, name in zip(score.findall("Part"), ("Sopran", "Alt", "Tenor", "Bass", "Klavier")):
        part.find("trackName").text = name
        for inst in part.iter("Instrument"):
            inst.find("trackName").text = name
            for tag in ("longName", "shortName"):
                for el in inst.findall(tag):
                    inst.remove(el)


def build(bwv, n):
    cap = os.path.join(SOURCES, f"BWV_{bwv:04d}_{n}.cap")
    out_dir = os.path.join(HERE, f"bwv{bwv}")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"bwv{bwv}_{n}.mscz")
    with tempfile.TemporaryDirectory() as tmp:
        mscx = os.path.join(tmp, f"bwv{bwv}_{n}.mscx")
        if (bwv, n) == (4, 8):
            raw, fixed = os.path.join(tmp, "raw.musicxml"), os.path.join(tmp, "rebarred.musicxml")
            forced = os.path.join(tmp, "forced.mscx")
            convert(cap, raw, force=True)
            convert(cap, forced, force=True)
            rebar_4_8(raw, forced, fixed)
            convert(fixed, mscx)
        else:
            convert(cap, mscx, force=(bwv, n) == (80, 5))
        root = read_mscx(mscx)
        score = root.find("Score")
        title_frame(score, bwv, n)
        remove_stray_texts(score, bwv, n)
        if (bwv, n) == (80, 5):
            repair_80_5(score)
        if (bwv, n) == (4, 8):
            copy_marks(read_mscx(forced).find("Score"), score)
            normalize_lyrics(score)
            repair_4_8(score)
            melismas(score)
        write_mscx(root, mscx)
        convert(mscx, out)
        check = os.path.join(tmp, "check.musicxml")
        r = mscore("-o", check, out)  # without -f: refuses a corrupt score
        if not os.path.exists(check):
            sys.exit(f"{out} doesn't load cleanly in MuseScore (exit {r.returncode})")
    print(f"{os.path.relpath(cap, HERE)} -> {os.path.relpath(out, HERE)}")


def main():
    wanted = [tuple(int(x) for x in a.split(".")) for a in sys.argv[1:]] or sorted(MOVEMENTS)
    for key in wanted:
        if key not in MOVEMENTS:
            sys.exit(f"unknown movement {key}; known: {', '.join(f'{b}.{n}' for b, n in MOVEMENTS)}")
        build(*key)


if __name__ == "__main__":
    main()
