# Using Zotero

Zotero is good at the three jobs `strata` has chosen not to do: holding the PDFs, citing while you write, and
sharing a library with a group. The link is optional and deliberately narrow:

> **Zotero owns the documents. `strata` owns the decisions.**

Nothing about a review needs Zotero. Screening, extraction and analysis run the same without it, and no
command complains that it is missing.

What crosses the link:

| From | To | What |
|---|---|---|
| Zotero | `strata` | A collection, as an import source. Later, Zotero's corrections to a paper's title, authors and so on |
| Zotero | `strata` | Whether a paper has a file attached, so the retrieval queue can show it and open it |
| `strata` | Zotero | The included studies, put in a collection for citing |

What never crosses: a screening decision, an exclusion reason, extracted data. Zotero is never asked to hold
them, and `strata` never deletes or overwrites anything in your library that it did not create.

## Linking a review

Start Zotero, then:

```
strata --why "Linking the review to our Zotero library" zotero link --by ada --library users/12345
```

```
linked users/12345 through the local API
  linked read-only through the local API; to push included studies back to Zotero, run `strata zotero link --web` with an API key that can write
  matched 3 of 4 library items to records (3 new or updated links)
  not in this review: QR8S2TUV Okafor (2017)  Retrieval practice in secondary school science: a cluster trial (`strata zotero pull` brings it in)
```

`strata` uses Zotero's **local API** when the desktop app offers it. That needs Zotero 7 or later with
*Settings > Advanced > "Allow other applications on this computer to communicate with Zotero"* switched on. It
asks for no key, and nothing leaves your computer. If the local API is not there, `strata` says why and uses
the **Web API** (`api.zotero.org`) instead, which does need a key (below).

Records are matched to Zotero items by the same ladder `strata` identifies records by: DOI, then PMID, then
title, year and first author. `--library` is `users/<your id>` or `groups/<id>`; if you do not say and there
is a choice, `strata` asks. The link is kept in `strata.toml` under `[zotero]`; the match for each record is
kept in `integrations/zotero.ndjson`, which is committed, so everyone on the review shares it.

An item that matches nothing is **listed, not guessed**. One that is close to a record but not the same
(different on every identifier, similar enough to be worth a look) is shown as a *possible match, not linked*;
check it, correct the record with `strata fix` if it is the same paper, and link again.

## An API key

The Web API needs a key from <https://www.zotero.org/settings/keys>. Give it read access to your library and,
if you want to push included studies back, write access too.

```
strata --why "Linking with a key that can write" zotero link --by ada --library users/12345 --web
```

`strata` asks for the key once and keeps it in your **operating system's keychain** (macOS Keychain, Windows
Credential Manager, or the Secret Service on Linux), never in the review folder: a key committed to a shared
repository cannot be taken back. Whether the key can write is checked now, when you link, not later when you
push.

On a machine with no keychain (a server, say), set `STRATA_ZOTERO_API_KEY` in the environment. `strata` says
that the key is read from there and is **not being stored**, and writes nothing to disk. Install the optional
keychain support with `pip install "strata-review[zotero]"`.

## Bringing a collection in

```
strata --why "Pulling the hand-searched trials" zotero pull --collection "Hand-searched trials" --by ada --via website
```

A pull is an import, so it needs to say where the records came from:

- `--search S-01-pubmed` if the collection holds the results of a database search you recorded, or
- `--via website` (or `citation-searching`, `organisation`, `registry`, `contact`) if you built the
  collection by hand. PRISMA counts those in the **other methods** column, not as a database search.

The collection's name and the day it was pulled are kept with the import. Pulling the same collection again
brings in only what is new. For papers already linked, Zotero's bibliographic metadata wins: a corrected
title, a fuller author list, a page range that was missing. Each correction is an ordinary correction in the
record (`strata why <record>` shows it, marked as from Zotero).

```
pulled 3 items from 'Hand-searched trials': 0 new records, 0 matched records already in the review, 3 already linked, 4 correction(s)
  corrected rec_6nkmc81132r4p6ag title: 'Spacing effects in learning: A temporal ridgeline of optimal retention' -> 'Spacing effects in learning: a temporal ridgeline of optimal retention'
  corrected rec_35fcqn8457xd5rt9 volume: None -> '17'
```

A pull never removes something a record has because Zotero lacks it: an abstract you screened on stays even
if the Zotero entry has none. Use `strata fix` for that.

## Full texts in the retrieval queue

With a link, `strata retrieve` shows whether Zotero has a file for each report:

```
strata retrieve --by ada --list
```

```
4 reports sought. 4 outstanding. Zotero: 2 attachments found.
  rpt_35fcqn8457xd5rt9  Roediger & Karpicke (2006)  [Zotero: files]
  rpt_6nkmc81132r4p6ag  Cepeda et al. (2008)  [Zotero: pdf]
  rpt_p1g3vhytxg5zhmxx  Okonkwo (2015)  [Zotero: unlinked]
  rpt_zgndh88w7v6anmrt  Smith (2010)  [Zotero: none]
```

Working the queue interactively, a report with a file offers `o` (open it in Zotero) and `z` (record it as
retrieved from Zotero). From a script:

```
strata --why "In our Zotero library" retrieve --by ada --report rpt_6nkmc81132r4p6ag --outcome retrieved --zotero
```

The full-text manifest then records the DOI and the **Zotero item key**, not a path on your disk.

`strata zotero open <record>` opens a record's PDF in Zotero (or, with no PDF, the item), and
`--print-only` just prints the `zotero://` link. At the full-text screening stage `strata screen` also says
where each record's full text is. If a paper has been deleted from Zotero, the full text is reported as
unavailable and screening carries on; so does Zotero not running.

## Putting the included studies in a collection

```
strata --why "Putting the included studies in Zotero for citing" zotero push --collection "Included studies" --by ada
```

```
pushed to 'Included studies': 0 created, 2 added, 1 already there
```

Papers Zotero already has are added to the collection; papers it lacks are created. It never deletes
anything, and never edits an item it did not create beyond adding it to the collection. If you edited an item
in Zotero since `strata` last saw it, that item is **refused and reported**, not overwritten: `strata zotero
pull` it first, then push again. Pushing needs a link made with `--web` and a key that can write.

## Checking the link

```
strata zotero status
```

```
linked to users/12345
  3 of 4 records mapped to a Zotero item
  1 not mapped
  no stale links
```

A *stale* link is a record whose Zotero item has since been deleted; it is listed with "full text
unavailable". Run `strata zotero link` again to map the record afresh if the paper is back in the library.

## Not yet

Mirroring screening state as Zotero tags, and reading your PDF highlights as the source of an extracted
number, are not built. See [Known limitations](Known-Limitations#zotero).

Next: [Grouping reports into studies](Grouping-Reports-into-Studies).
