# Bach

MuseScore 4 scores of Bach cantatas, built from Capella files.

| Folder | Contents |
|---|---|
| `bwv4/` | BWV 4 *Christ lag in Todesbanden*, all eight movements (`bwv4_1.mscz` … `bwv4_8.mscz`) |
| `bwv80/` | BWV 80 *Ein feste Burg ist unser Gott*, movements 1, 2, 5, 7 and 8 |
| `chorales/` | about 400 four-part chorales (`bwv4.8.mscz`, `bwv269.mscz`, …) and `REPORT.md`, made by `build-chorales.py` |
| `sources/capella/` | the Capella files from [bach-cantatas.com](https://www.bach-cantatas.com/BWV4.htm) (the "Capella Files" links on each cantata's page) |
| `sources/bcfb/` | the [Bach Chorales Figured Bass](https://zenodo.org/record/5084914) dataset's MusicXML (CC BY 4.0), after the Neue Bach-Ausgabe |
| `sources/humdrum-370/` | Craig Sapp's [370 chorales](https://github.com/craigsapp/bach-370-chorales) in Humdrum, after Breitkopf (Dörffel, c. 1875) |
| `sources/chorale-titles.json` | hymn, verse and Riemenschneider number per BWV, from Wikipedia's [list of the chorale harmonisations](https://en.wikipedia.org/wiki/List_of_chorale_harmonisations_by_Johann_Sebastian_Bach) |

## The chorales

```sh
./build-chorales.py               # all
./build-chorales.py bwv4.8 bwv269 # some
```

The notes and text come from the music21 corpus: Margaret Greentree's
encodings (jsbchorales.net, "used by permission"), which follow the
Breitkopf edition, keys included: BWV 4/8 is in D minor there, E minor in
the cantata. Each chorale becomes a closed score like the church scores,
Women (S, A) and Men (T, B), names hidden, text under the soprano with
melisma lines; instruments are left out. So `church/tools`
(`voice-explode-mscz.py`, `score-reflow.py`, `score-video.py`) work on
them too.

The pitches are checked against the NBA (BCFB) and Breitkopf (Humdrum); a
note is corrected only where the NBA differs and Breitkopf doesn't side
with Greentree. `chorales/REPORT.md` lists the corrections, the places
where the editions differ, and the notes only Breitkopf questions.

Rebuild with:

```sh
./build.py            # all movements
./build.py 4.8 80.5   # some
```

`build.py` imports each Capella file with MuseScore's command line, repairs
the defects described in its docstring (BWV 80/5 violin II m56; BWV 4/8
re-barred, with its alto and bass text checked against the BGA), gives each
movement a clean title frame and removes Capella page headers from the
music. Every result must load in MuseScore without `-f`. It needs music21
for BWV 4/8 (installed in MacPorts' Python 3.14).

## What the sources contain

- Full scores: BWV 4/1 (Sinfonia), BWV 80/1, 2, 5 and 7.
- Voices and keyboard: BWV 4/2, 3, 4, 6, 7, 8.
- Voices only: BWV 4/5 (the keyboard staves are empty).
- BWV 80/8: the chorale on two staves, text under the top staff.
- Not available as Capella files: BWV 80/3, 4 and 6.

Text is missing in places in the sources: BWV 4/2 soprano (3 syllables)
and tenor (none), BWV 4/5 soprano and tenor, BWV 4/7 soprano. In BWV 4/8
the text sits under the alto and bass only, as in Capella. The Capella
encoding marks hyphens over a melisma with empty syllables; only BWV 4/8
has been converted to proper words with melisma lines so far.

Credit: the Capella encodings come from the Bach Cantatas Website; checks
against the Bach-Gesellschaft edition (BGA) used its scans on the same site.
