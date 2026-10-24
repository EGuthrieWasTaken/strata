# strata

**A free, version-controlled workbench for systematic reviews and meta-analyses.**

A systematic review is a series of reasoned decisions about a body of literature. `strata` keeps every one
of them (the protocol, the searches, each record, every screening decision, the extracted data and the
analyses) as plain text in a git repository, together with *who* decided *what* and *why*. You never need to
type a git command: `strata` does the versioning, and gives you the provenance, collaboration and
reproducibility that come with it.

It exists to answer, mechanically, the question every reviewer eventually asks:

> We changed a criterion halfway through screening. Which of our 4,000 decisions are still valid? Which papers
> re-enter the pool? What did it do to the pooled effect? And how do we explain it in the manuscript?

## Start here

| I want to... | Go to |
|---|---|
| Install it | [Installation](Installation) |
| See the whole workflow once, on a small example | [Quickstart](Quickstart) |
| Understand the git side without learning git | [Git for reviewers](Git-for-Reviewers) |
| Run it without installing Python | [Running in a container](Running-in-a-Container) |

## Doing a review, stage by stage

Each guide explains what the stage is for, walks through it with real commands and output, and says what to
check before moving on. They follow the order of a review.

1. [Setting up a review](Setting-Up-a-Review): the repository, collaborators, eligibility criteria, settings.
2. [Searching and importing](Searching-and-Importing): record each search, import its export, fix a record.
3. [Removing duplicates](Removing-Duplicates)
4. [Screening](Screening): title and abstract, then full text; working alone or as a pair.
5. [Adjudication and agreement](Adjudication-and-Agreement): resolving disagreements, kappa, spot-checks.
6. [Changing your criteria mid-review](Changing-Criteria-Mid-Review): what becomes stale and what to do.
7. [Retrieving full texts](Retrieving-Full-Texts)
8. [Grouping reports into studies](Grouping-Reports-into-Studies)
9. [Extracting data](Extracting-Data)
10. [Risk of bias](Risk-of-Bias)
11. [Analysis](Analysis): specifications, models, guardrails, plots.
12. [Reporting](Reporting): PRISMA flow diagram, checklist, generated Methods and Results, exports.

Around those: [Working with others](Working-with-Others) (sharing, syncing, checks on pull requests) and
[The web interface](The-Web-Interface) (the same review in a browser).

## Concepts

Short explanations in a methodologist's terms rather than an implementer's.

- [Staleness](Staleness): when a past decision stops being safe to rely on.
- [Criteria versions and direction](Criteria-Versions-and-Direction): why a change is "tightened" or "loosened".
- [How deduplication works](How-Deduplication-Works)
- [Blinding and independent screening](Blinding-and-Independence)
- [What is in a review folder](The-Review-Folder)
- [Glossary](Glossary)

## Reference

- [Command reference](Command-Reference): every `strata` command, its options and exit codes.
- [Filter language](Filter-Language) (the `--filter` expressions), [Configuration](Configuration) (`strata.toml`).
- [Statistical methods](Statistical-Methods): the formulae, conventions and sources.
- [Methods-text cookbook](Methods-Text-Cookbook): which command produces which part of a methods section.
- [Recovery and troubleshooting](Recovery-and-Troubleshooting), [Known limitations](Known-Limitations).

## Project

- Source and issues: <https://github.com/EGuthrieWasTaken/strata>
- Licence: GNU General Public License v3.0 or later.
- Status: the pipeline from import to a generated manuscript draft is implemented; what is deliberately
  unfinished is listed on [Known limitations](Known-Limitations).
- This wiki is kept in the repository's `wiki/` folder and published from there, so a change to a command
  and the page that describes it can be reviewed together (see [Contributing to the wiki](Contributing-to-the-Wiki)).
