# Git for reviewers (if you have never used git)

You do not need to learn git to run a review with `strata`. This page explains the handful of ideas you will
meet, what to do about each, and what to do when you share a review with colleagues. Everything else `strata`
does for you.

## What git is doing for you

A `strata` review is a folder. Git keeps that folder's whole history: every decision, who made it, when, and
the reason you gave. Each time you do something that changes the review (import a file, screen a record, edit
a criterion) `strata` saves a **commit**, a labelled snapshot, with the reason you passed in `--why` (or typed
when asked). That history lets you answer "why did we exclude this paper?" months later and lets a
co-author see exactly what you changed. You never need to type `git commit`.

> **The one exception to "one command, one commit" is screening.** While you screen, each decision is saved to
> disk the moment you make it, and the commit is made when you end the session. If the program stops half way
> (a crash, a closed terminal, a flat battery), start the same `strata screen` command again and carry on; the
> decisions you saw accepted are already saved.

## The words you will see

| Word | What it means here |
|---|---|
| **repository** (or *repo*) | Your review folder, with its history |
| **commit** | One saved, labelled snapshot. `strata` makes them for you |
| **remote** | A copy of the review kept on a server (GitHub, your institution's GitLab, ...) so others can share it |
| **clone** | A complete copy of a remote on your own computer. Everyone who works on a review has one |
| **sync** | Bring in what others did and send yours: `strata sync` |
| **conflict** | Two people changed the same thing differently. `strata` shows you both versions and asks |

## Working alone

```
strata init my-review --title "My review" --actor you --actor-name "Your Name"
cd my-review
strata status          # always safe: shows where things stand and what to do next
```

That is all of git you need. Back the folder up as you would any folder, or give it a remote (below) so there
is always a second copy.

## Working with others

Several people can work on one review at once, each on their own computer, by sharing it through a **remote**.

### Once, for the whole team: make the remote

1. On GitHub (or GitLab), create a **new empty repository**, private unless the review is public. Do not add a
   README or licence; it must be empty.
2. Copy its address. The HTTPS form looks like `https://github.com/your-group/your-review.git`.
3. In your review folder, give the address to the repository (this is the single git command you may need):

   ```
   git remote add origin https://github.com/your-group/your-review.git
   ```

4. Send your work up: `strata sync`.

You will be asked for GitHub credentials the first time. GitHub no longer accepts account passwords on the
command line: use a [personal access token](https://github.com/settings/tokens) as the password, or set up
[GitHub's credential helper](https://docs.github.com/en/get-started/getting-started-with-git/caching-your-github-credentials-in-git)
once and not be asked again. Add your collaborators on the repository's *Settings > Collaborators* page.

### Each collaborator, once: get a copy

```
strata clone https://github.com/your-group/your-review.git
cd your-review
strata actor list
```

`strata clone` makes the copy, installs the small helpers `strata` needs for shared reviews, and checks the
result. The lead adds each person as an actor (`strata actor add sam "Sam Example"`, see
[Setting up a review](Setting-Up-a-Review)) and `sync`s; after the next `strata sync` that person can screen
as `sam`.

### Every working session

```
strata sync            # before you start: bring in what others did
...                    # screen, extract, ...
strata sync            # when you stop: send yours up
```

`strata sync` says what changed in terms you recognise ("sam screened 40 record(s) at title-abstract (31
include, 9 exclude)"), not in git's. Two people screening the same records at the same time never conflict,
because each person writes to their own file.

If two people edit the **same criterion or settings file** at the same time, `strata sync` stops and shows
both versions as *mine* and *theirs*; choose one (`strata sync --resolve mine` or `--resolve theirs`) or
answer the prompts. You will not be shown the `<<<<<<<` markers git itself would put in a file. If anything
about the merged result would break the review, `strata sync` puts everything back exactly as it was and
pushes nothing.

More on sharing: [Working with others](Working-with-Others).

## The rules that keep it safe

1. **Do not edit files under `events/`, `records/`, `derived/` or `reports/` by hand.** They are the record
   and what is computed from it. `strata verify` tells you if one has been damaged.
2. **Run `strata sync` before and after each session** when you share a review.
3. **Give a real reason** when asked why. It is the most useful sentence in the history.
4. **If something looks wrong, run `strata verify`** and read
   [Recovery and troubleshooting](Recovery-and-Troubleshooting). Nearly every problem has a one-line fix,
   and nothing you have recorded is lost while it is in git.

## "Is it OK to ...?"

| Question | Answer |
|---|---|
| ... use GitHub Desktop, VS Code or another git tool alongside `strata`? | Yes. It is ordinary git. Just do not hand-edit the files listed above |
| ... copy the folder to a USB stick or cloud drive? | Yes, as a backup. Do not *work* in two copies of a folder at once without `strata sync` between them; a cloud-synced folder (Dropbox, OneDrive) can corrupt the history, so keep the review outside it and share through a remote |
| ... delete a decision I regret? | No, and you do not need to: record a new decision. Both stay in the history, and the later one counts. See [Recovery](Recovery-and-Troubleshooting#i-made-a-wrong-decision) |
| ... rename the folder? | Yes. Nothing refers to its location |
| ... put full-text PDFs in the review folder? | You can, but they are never committed (`fulltext/*` is ignored). Keep a shared drive for the PDFs and record identifiers in `strata` |

## The browser instead of the terminal

`strata serve` opens the same review in your browser: screening, criteria, the dashboard, analyses and the
PRISMA diagram. It uses the same folder and makes the same commits; there is no separate account or database.
See [The web interface](The-Web-Interface).
