# Demo actor assets

`evil-treant/` is the sample actor shipped so `emberforge-lite demo` works
offline with no credentials. It is **owned, generated content**, produced on the
project owner's own **paid** provider subscriptions and covered by this project's
MIT license:

- **Sprites** — `evil_treant_source_openai.png` (OpenAI `gpt-image-2`) and
  `evil_treant_source_spritelab.png` (SpriteLab, paid).
- **Animation + spritesheet** — `evil_treant_root_slam_*` (SpriteLab `/animate`,
  paid).
- **Sounds** — three ElevenLabs sound effects generated on the paid subscription
  (linked to the animation in `links.json`).

`generations.jsonl` is the real generation ledger and `provenance.json` records
each asset's provider, prompt, review date, and rights context
(`spritelab_paid_private_exclusive`, `openai_api_assigned_exclusive`,
`paid_commercial_exclusive`). See [../../../docs/providers.md](../../../docs/providers.md)
for what those mean and the note that the provider's own current terms are
authoritative.

**Licensing:** the repository's MIT license covers the **code**. These demo
**assets** are distributed as generated provider output under the respective
providers' terms, with copyright status as provided by those terms — the project
does not assert a copyright in every asset. In particular, OpenAI and ElevenLabs
assign the generating user ownership, while SpriteLab permits commercial use and
claims no ownership but grants no copyright at any tier (whether one subsists is
unsettled and is not asserted here). See the top-level [`NOTICE`](../../../NOTICE).

Two ElevenLabs **sound-library** downloads that were in the working actor are
intentionally **excluded** here: they are stock library assets, not owned
generated output, and this repository does not redistribute them.

The procedural `synthesize_demo_actor` in `demo.py` is a separate fallback that
builds a placeholder actor from deterministic bytes; it is not third-party art.
