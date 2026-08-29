# Data & provenance format

Everything Emberforge Lite knows about an actor lives in that actor's folder, so
the folder is portable and inspectable on its own.

```
<data-dir>/actors/<slug>/
    sprites/        source images (png, jpg, jpeg, webp)
    animations/     preview gifs
    sounds/         audio (mp3, wav, ogg, m4a)
    sheets/         spritesheets paired with generated animations
    links.json      {"animation.gif": ["sound.wav", ...]}
    generations.jsonl   append-only provider-call ledger
    provenance.json     per-asset origin metadata (schema v1)
```

## `links.json`

A map from an animation filename to the list of sound filenames linked to it.
Absent means no links.

## `generations.jsonl`

Append-only, one JSON object per line, written before and after each provider
call. It is the audit trail for spend and the resume point for an interrupted
animation job. A malformed line anywhere but the last is treated as corruption
and reported with the actor, file, and line number; a malformed final line is
tolerated as an interrupted write.

## `provenance.json` (schema version 1)

Keyed by the asset's path relative to the actor directory. Each generated asset
records the provider, model, prompt, generation and terms-review dates, the
account-rights context, attribution, the transforms applied, the reported
charge, and vendor extras. Each uploaded asset records only that its rights are
unknown.

```json
{
  "schema_version": 1,
  "assets": {
    "sprites/hero_source.png": {
      "source": "generated",
      "provider": "openai_images",
      "model": "gpt-image-2",
      "prompt": "a hooded scribe, pixel art",
      "generated_at": "2026-08-22T12:00:00+00:00",
      "terms_reviewed_at": "2026-08-21",
      "account_rights": "openai_assigns_all_interest_in_output",
      "attribution_required": false,
      "attribution_text": null,
      "transforms": [],
      "reported_charge": { "unit": "usd", "amount": "0.006" },
      "vendor": { "request_id": "req_..." }
    },
    "sprites/borrowed.png": {
      "source": "uploaded",
      "account_rights": null
    }
  }
}
```

Provenance is updated atomically under the actor lock when an asset is generated,
uploaded, renamed, or deleted, and it travels with the actor in an export. The UI
badges each asset **generated**, **uploaded**, or **rights unknown** so a
reviewer is warned before treating borrowed art as their own.
