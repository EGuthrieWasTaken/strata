# Design: risk-of-bias

*Informative.* The requirements are in [spec.md](spec.md).

## Structurally the same as extraction

An assessment has an instrument, a per-reviewer record, reconciliation and a
consensus. It is specified separately only because the instruments are
standardised and shipped, and because an assessment is routinely consumed as an
analysis moderator (`rob_overall`, `rob.<domain>`). In dual mode it follows the
same `by-reviewer/` and `consensus/` layout and uses the same reconciliation.

## Suggestions are algorithms; judgements are the reviewer's

For RoB 2 the signalling-question answers determine each domain's suggested
judgement and the overall suggestion by published rules. The tool computes the
suggestion and shows it, but the recorded judgement is the reviewer's. When it
differs, the override and a justification are stored together with the suggestion
that was overridden, so a reader can see where judgement departed from the
algorithm and why.

## What is verified, and what is not

The RoB 2 algorithms were checked against two independent open-source
transcriptions on every one of 82,125 answer combinations. They have **not** been
compared with Cochrane's own tables, and no official question wording is bundled
for licence reasons; `docs/rob-instruments.md` lists what to check before a
release, and a project may add the wording itself.

## Custom instruments

A custom instrument is a YAML file of domains, judgements and (optionally)
signalling questions, with an `overall` algorithm (for example `worst-domain`, or `sum` for star-based scales). Variants
without a shipped definition (cluster and crossover RoB 2, ROBINS-E, QUADAS-2) are
defined this way rather than shipped half-checked.

## Example

```
$ strata rob std_7x2k9m1p3v5r8t0w

  RoB 2 -- Domain 1: Randomisation process

  1.1  Was the allocation sequence random?                   [Y] [PY] [PN] [N] [NI]
  1.2  Was the allocation sequence concealed?                [Y] [PY] [PN] [N] [NI]
  1.3  Did baseline differences suggest a problem?           [Y] [PY] [PN] [N] [NI]

  Algorithmic suggestion: LOW
  Your judgement: [l] low  [s] some concerns  [h] high      Support: ______
```

```yaml
instrument: "RoB 2"
version: "2019-08-22"
applies_to: ["rct"]
domains:
  - id: "D1"
    label: "Randomisation process"
    judgements: ["low", "some-concerns", "high"]
    signalling_questions:
      - id: "1.1"
        text: "Was the allocation sequence random?"
        options: ["Y", "PY", "PN", "N", "NI"]
overall:
  algorithm: "worst-domain"
```
