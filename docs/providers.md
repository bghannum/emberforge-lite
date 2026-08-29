# Provider guide

Emberforge Lite talks to three providers. Each has an adapter under
`src/emberforge_lite/providers/` and a deterministic fake that imitates its
documented behavior so the whole flow runs offline.

| Provider | Stage | Endpoint | Notes |
|---|---|---|---|
| **SpriteLab** | animation | `/animate` | Async: submit, poll, collect. Refuses inputs over 256 px per axis and returns the canvas it is given, so a source is fitted to 256×256 with a motion margin first. Fixed 8 fps. |
| **SpriteLab** | source | `/generate` | Returns a multi-view sheet with transparent gutters. |
| **OpenAI** | source | Images API (`gpt-image-2`) | Returns a 1024×1024 transparent PNG. |
| **ElevenLabs** | sound | sound-effect generation | Returns short audio; metered per second of requested duration. |

## Offline by default

Without `--allow-spend`, every provider is replaced by a deterministic fake: the
same request always produces the same bytes, no network is touched, and nothing
is spent. The fakes reproduce the awkward parts of the real endpoints — a
256 px input cap, an automatic refund on failure, an ambiguous timeout, a charge
the provider will not state — so code exercised offline is exercised against the
shape of the real thing.

## Cost snapshots

The per-call costs shown in the UI are **dated snapshots**, not live quotes, and
each generate call requires you to echo the exact estimate you were shown before
anything is submitted.

| Provider | Snapshot | Reviewed |
|---|---|---|
| SpriteLab animation | 20 credits | 2026-08-21 |
| SpriteLab source | 1 credit (epic) / 6 (mythic) | 2026-08-21 |
| OpenAI `gpt-image-2` source | $0.006 (low, 1024×1024) | 2026-08-22 |
| ElevenLabs sound | 40 credits per second requested (800 ms → 32) | 2026-08-22 |

## Rights and terms (as reviewed)

> **These are notes from a review on the dates below, not a legal statement, and
> not our call to make.** Provider terms change, differ by plan, and are the
> provider's to define. Before you rely on any of this, read each provider's own
> current terms — they are authoritative, we are not:
>
> - SpriteLab — <https://www.spritelab.io> (pricing and API/output terms)
> - OpenAI — <https://openai.com/policies/> and <https://openai.com/api/pricing/>
> - ElevenLabs — <https://elevenlabs.io/terms> and <https://elevenlabs.io/pricing>

What the review found (recorded per asset in
[provenance-format.md](provenance-format.md), and configured on each adapter
rather than inferred):

- **SpriteLab** (reviewed 2026-08-21 against terms last revised 2026-06-09,
  §"Your content and generated sprites"). SpriteLab grants no copyright at any
  tier; commercial use is permitted; no attribution is required. On the **free**
  plan, output is public and non-exclusive (anyone may use it, and SpriteLab may
  display it in its galleries/marketplace); on the **paid** plan, output is
  private by default, SpriteLab claims no ownership, and community sharing is a
  reversible per-sprite choice. A failed job refunds its credits automatically.
- **OpenAI Images** (reviewed 2026-08-22). The terms assign the user all of
  OpenAI's interest in the Output ("you own the Output") and the user keeps the
  Input; recorded as exclusive in the sense our provenance tracks. Two things the
  reviewed text does not settle — whether OpenAI may itself display or reuse the
  output, and whether attribution is required — are recorded **open**, not
  resolved favorably, so a downstream reader sees the gap.
- **ElevenLabs** (reviewed 2026-08-22, from the paid subscription agreement).
  Every paid tier conveys ownership of the generated files with a full commercial
  licence and no attribution requirement. A key scoped narrowly to Sound Effects
  cannot read `/user/subscription`; that is expected, and the estimate prices
  every generation as overage rather than widening the key's permissions.

The dates above are when a human last read the terms. Emberforge Lite records the
review date with each asset and never treats an old review as a current
guarantee; re-read the provider's terms whenever you are unsure.

## Adding or updating an adapter

An adapter implements the `Provider` protocol in `providers/base.py` (estimate,
submit, poll, collect) and returns a `CandidateProvenance` filled with the
required fields. Meter costs by deriving from the adapter's own pricing tables
rather than retyping them, and keep vendor-specific data in the `vendor`
compartment so it never leaks into a manifest. Network access goes through the
`transport` seam, which the tests replace with a no-network double.
