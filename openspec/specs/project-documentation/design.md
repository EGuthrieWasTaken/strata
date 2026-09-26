# Design: project-documentation

*Informative.* The requirements are in [spec.md](spec.md).

## Two audiences, two places

OpenSpec (`openspec/`) is written for implementers: what the system must do and
why. The wiki is written for the people using the tool — reviewers and
methodologists — in their register. The two must not be merged: a
methodologist looking up "staleness" needs the concept and its consequences,
not the fold algorithm.

| Document | Audience |
|---|---|
| Quickstart: first review in 30 minutes | A doctoral student running a first review |
| "I have never used git" guide | A second screener contributing 20 hours |
| Methods-text cookbook | All |
| Statistical methods reference, with formulae and sources | Methodologists |
| Repository format reference | Implementers, data archivists |
| Recovery guide | All |
| Contributing guide, including how to add a parser | Contributors |

## Why documentation ships with the feature

Documentation written months after a feature ships is written from memory, by
which point the person who best understood the feature has moved on.
Documentation written in the same pull request is written by the person who
just built it, while the reasoning is fresh. The pull-request template prompts
for it; it stays a review-time judgement rather than a CI gate because docs
quality does not reduce to a boolean a script can check.
