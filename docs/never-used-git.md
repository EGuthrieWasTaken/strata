# "I have never used git"

You do not need to learn git to run a review with `strata`. This page explains the four ideas you will meet
and what to do about each; everything else `strata` does for you.

## What git is doing for you

A `strata` review is a folder. Git keeps its whole history: every decision, who made it, when, and the
reason you gave. Each time you do something that changes the review (import a file, screen a record, edit a
criterion) `strata` saves a **commit**, a labelled snapshot, with the reason you passed in `--why` (or typed
when asked). That history is what lets you answer "why did we exclude this paper?" months later and what lets
a co-author see exactly what you changed. You never need to type `git commit`.

**Screening is the one exception to "one command, one commit".** While you screen, each decision is saved to
disk the moment you make it, and the commit is made when you end the session; if the program stops half way,
start `strata screen` again and carry on.

## Working alone

```
strata init my-review --title "My review" --actor you --actor-name "Your Name"
cd my-review
strata status          # always safe: shows where things stand and what to do next
```

That is all of git you need. Back the folder up as you would any folder, or give it a remote (below).

## Working with others

Several people can work on the same review at once, each on their own computer, by sharing it through a
**remote**: a copy kept on a server such as GitHub or your institution's GitLab. You create an empty
repository there once, give its address to `strata`'s folder (`git remote add origin <address>` is the single
git command you may need), and from then on:

```
strata sync            # bring in what others have done, put yours in, check the result, report in plain terms
```

`strata sync` says what changed in terms you recognise (for example "sam screened 40 record(s) at
title-abstract (31 include, 9 exclude)"), not in git's. Two people screening the same records at the same time never conflict,
because each person writes to their own file. A new collaborator starts with `strata clone <address>`.

If two people edit the same criterion at the same time, `strata sync` stops and shows both versions, `mine`
and `theirs`; choose one (`strata sync --resolve mine` or `--resolve theirs`), or answer the prompts. You
will not be shown the markers git itself would put in a file. If anything about the merged result would
break the review, `strata sync` puts everything back as it was and pushes nothing.

## The rules that keep it safe

1. **Do not edit the files under `events/`, `records/`, `derived/` or `reports/` by hand.** They are the
   record and what is computed from it; `strata verify` will tell you if one has been damaged.
2. **Run `strata sync` before you start a session and after you finish it** when you share a review.
3. **Give a real reason** when asked why. It is the most useful sentence in the history.
4. **If something looks wrong, run `strata verify`** and read [`recovery.md`](recovery.md): nearly every problem
   has a one-line fix, and nothing you have recorded is lost while it is in git.

## The browser instead of the terminal

`strata serve` opens the same review in your browser: screening, criteria, the dashboard, analyses and the PRISMA
diagram. It uses the same folder and makes the same commits; there is no separate account or database. See
[`container.md`](container.md) if you would rather not install anything but a container runtime.
