# Cheat sheet

The commands in the order of a review. Every command that changes the review takes `--why "reason"` *before*
its name (at least 12 characters), or asks you in a terminal. Details: the stage guides on [Home](Home) and the
[Command reference](Command-Reference).

## Always safe

```
strata status                     # where things stand, and NEXT: what to run
strata verify                     # check every file; exit code 4 if something is wrong
strata log                        # who did what, and why
strata why REC_ID                 # one record's full history
strata doctor                     # is the tooling around git in order? (--fix repairs)
```

## Start

```
strata init my-review --title "..." --actor you --actor-name "Your Name"
strata clone URL                              # join an existing shared review
strata --why "..." actor add sam "Sam Example"
strata --why "..." criteria add --kind inclusion|exclusion --label "..." --definition "..." \
    --applies-at title-abstract,full-text --by you
```

## Search and import

```
strata --why "..." search add --database MEDLINE --platform Ovid --by you --query "..." --hits 8
strata --why "..." import --by you --search S-01-medline export.ris        # --dry-run first
strata --why "..." dedup --by you                                          # then --review for doubtful pairs
strata records list --filter "year >= 2015"
```

## Screen

```
strata --why "..." assign title-abstract --actors you,sam --by you
strata --why "..." screen title-abstract --by you                          # i / e / m / s / u / q
strata --why "..." adjudicate --by you                                     # settle conflicts
strata irr                                                                 # agreement between reviewers
strata audit --criteria --sample 20                                        # spot-check exclusions
```

## Criteria changed? (staleness)

```
strata --why "..." criteria edit INC-01 --direction tightened|loosened|both|editorial --definition "..." --by you
strata --why "..." criteria add ... / criteria retire EXC-02 --by you
strata status                                                              # how many decisions are stale
strata --why "..." rescreen --by you                                       # i / e / m / k (keep) / s / q
strata criteria diff 4 5
```

## Full text, studies, extraction, risk of bias

```
strata retrieve --by you --list
strata --why "..." retrieve --by you --report RPT --outcome retrieved|ill-requested|not-retrieved [--reason no-access]
strata --why "..." studies --by you --group RPT --group RPT
strata --why "..." extract init
strata --why "..." extract STUDY --by you --set "name=value @ source" --effect '{"design": "two-group-means", ...}'
strata extract --list                                                      # what is missing (--missing works on those)
strata --why "..." rob init --instrument rob2
strata --why "..." rob STUDY --by you --domain D1 --answer 1.1=Y --judgement low
```

## Analyse and report

```
strata analyze --check                                                     # validate specs, show guardrails
strata --why "..." analyze primary [--ack k-lt-5] [--force]
strata diff v1-protocol..HEAD
strata --why "..." prisma [--columns both] [--format pdf]
strata report checklist --status
strata --why "..." report methods | results | characteristics | amendments | rob | manuscript
strata export effects --format csv --out effects.csv
strata export bibliography --set included --format ris --out included.ris
strata export package --out supplement.zip                                 # needs project.license
```

## Share

```
strata sync                       # before and after each session
strata sync --resolve mine|theirs
strata serve --actor you          # the same review in a browser
```

## Exit codes

`0` ok · `1` error · `2` usage · `3` not in a review · `4` does not validate · `5` conflict · `6` newer version ·
`7` reason refused · `8` guardrail refused ([details](Recovery-and-Troubleshooting#exit-codes)).
