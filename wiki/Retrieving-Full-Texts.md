# Retrieving full texts

Once title-abstract screening has settled which records move on, you need the full text of each. `strata`
does not fetch papers for you and never will from unofficial sources. It keeps the **queue** of reports you
are seeking, records what became of each, and counts them for the PRISMA diagram ("reports sought", "reports
not retrieved").

## The queue

A record that resolved to *include* at title-abstract becomes a **report sought**. `strata status` shows the
state, and `strata retrieve --list` the outstanding reports:

```
strata retrieve --by ada --list
```

```
6 reports sought. 6 outstanding.
  rpt_1qjn6pvab3h794qe  Jovanovic & Keller (2020)
  rpt_3bfqqz4nft3qqtqr  Haddad & Ito (2019)
  ...
```

Work through them interactively (no `--list`): for each report you can press `f` (I have the file), `u`
(open the DOI in a browser), `i` (interlibrary loan requested), `n` (not retrievable), `s` (skip) or `q`.

## Recording an outcome from a script

```
strata --why "Obtained through the library" retrieve --by ada --report rpt_3bfqqz4nft3qqtqr \
    --outcome retrieved --source institutional-access --version version-of-record
strata --why "Interlibrary loan requested" retrieve --by ada --report rpt_9fz6sp8zep3zep1h --outcome ill-requested
strata --why "Not held; the interlibrary loan was refused" retrieve --by ada \
    --report rpt_1qjn6pvab3h794qe --outcome not-retrieved --reason no-access
```

| Outcome | Meaning |
|---|---|
| `sought` | Still to obtain (the starting state) |
| `ill-requested` | You have asked for it (interlibrary loan or similar) |
| `retrieved` | You have it |
| `not-retrieved` | You could not get it. A **reason is required** |

Reasons for `not-retrieved`: `no-access`, `not-found`, `retracted`, `language`, `no-response-from-author`, or
`other` (then `--reason-text "..."` is required). They fill in the "reports not retrieved" box of the PRISMA
diagram, so be accurate.

Useful extras: `--source` (where you got it, e.g. `institutional-access`, `author`), `--version` (the
document version you assessed: `preprint`, `accepted-manuscript`, `version-of-record`, `corrected`,
`retracted`), `--locator doi=...` / `pmid=...` for an identifier other than the record's own, and `--path` to
remember the local file (a convenience only).

## What is recorded, and what is not

- **The PDF is never committed.** The review records only an *identifier and version* in
  `fulltext/manifest.ndjson`, which is committed; your files stay on your disk or a shared drive. This avoids
  both publisher-copyright problems and a repository that balloons.
- **There is no content hash of the file.** Two reviewers may well hold differently annotated copies of the
  same paper, and that is fine; the identifier and version are what identify the document.
- **Two versions of the same paper** (a preprint and the version of record) are distinguished by `--version`;
  record which one each reviewer assessed.
- **Open-access links are opt-in.** If you enable *enrichment* in `strata.toml` (`[enrichment] enabled =
  true`, with your email in `contact_email` as Unpaywall asks), the queue offers a legal open-access link for
  a report. Nothing is downloaded automatically. See [Configuration](Configuration).

## Then screen the full texts

Assign and screen at the `full-text` stage: [Screening](Screening#moving-to-full-text). An exclusion must cite
a criterion; the cited criteria become the exclusion reasons in the PRISMA diagram. Reports that could not
be retrieved appear as such and are not counted as assessed.

Next: [Grouping reports into studies](Grouping-Reports-into-Studies).
