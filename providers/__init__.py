"""Provider adapters, copied from emberforge (stdlib only).

Live adapters: `spritelab.SpriteLab` / `SpriteLabSource`, `openai_images.OpenAIImages`,
`elevenlabs.ElevenLabs`. Offline stand-ins: `fakes`. Selection between the two
lives in `generate.select_providers`, and nowhere else.
"""

from providers.base import (
    AmbiguousOutcome,
    AuthenticationFailed,
    Candidate,
    GenerationRequest,
    ProviderError,
    ProviderRejected,
    RateLimited,
)
from providers.transport import redact

__all__ = [
    "AmbiguousOutcome",
    "AuthenticationFailed",
    "Candidate",
    "GenerationRequest",
    "ProviderError",
    "ProviderRejected",
    "RateLimited",
    "redact",
]
