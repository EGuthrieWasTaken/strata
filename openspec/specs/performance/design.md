# Design: performance

*Informative.* The requirements are in [spec.md](spec.md).

## Sizing

The targets are sized against a large but ordinary review: four databases,
50,000 raw records, 40,000 after deduplication, 400 full texts, 60 included
studies, 120 effects — on a 2020 laptop with 4 cores, 16 GB RAM, and an SSD.
Reviews are run by researchers on the hardware they have, not on servers.

## Target versus hard limit

Each operation has a target (what it should feel like) and a hard limit (what
fails CI). Pull-request benchmarks at 1k/10k records are warn-only so a
contributor gets a signal without a flaky gate; the nightly 50k run is
blocking, so a real regression cannot sit unnoticed.

## Why 100 ms per decision

Screening thousands of records is repetitive work. A decision that does not
feel instant breaks concentration and costs hours over a review, so persistence
is asynchronous (append-then-advance) and the round trip is held to 100 ms p95.
