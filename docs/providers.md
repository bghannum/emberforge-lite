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
anything is submitted. Verify current pricing and terms with the provider before
enabling spend:

- SpriteLab — <https://www.spritelab.io> (pricing and API terms)
- OpenAI Images — <https://openai.com/api/pricing/> and the OpenAI usage terms
- ElevenLabs — <https://elevenlabs.io/pricing> and the ElevenLabs terms

> Snapshots reviewed 2026-08-22. Rights context and attribution requirements are
> recorded per asset in [provenance-format.md](provenance-format.md) exactly as
> the provider reports them; confirming that they match the provider's current
> terms is the operator's responsibility.

## Adding or updating an adapter

An adapter implements the `Provider` protocol in `providers/base.py` (estimate,
submit, poll, collect) and returns a `CandidateProvenance` filled with the
required fields. Meter costs by deriving from the adapter's own pricing tables
rather than retyping them, and keep vendor-specific data in the `vendor`
compartment so it never leaks into a manifest. Network access goes through the
`transport` seam, which the tests replace with a no-network double.
