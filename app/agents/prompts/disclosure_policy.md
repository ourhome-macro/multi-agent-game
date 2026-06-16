Disclosure policy:

- none: the speech does not touch the constrained fact.
- deny: deny or reject a premise without confirming hidden truth.
- deflect: redirect away from the fact without confirming hidden truth.
- hint: provide a low-resolution clue-shaped signal without direct confirmation.
- partial: acknowledge a bounded fragment allowed by current constraints.
- full: direct reveal. This is forbidden for real LLM output.

For disclosure_claims, only use world_info_id values that appear in
disclosure_constraints. Only use modes listed in that item's allowed_modes.
Never use a mode listed in forbidden_modes. Never use mode full.

For world_info constraints, safe_fragments are the only bounded fact fragments
the Director has approved for this turn. You may express only those summaries,
at the listed modes, and you must put the matching fragment ref in claim_refs
or an allowed source ref in source_refs. Do not invent claim_refs or source_refs.
Do not infer or combine safe_fragments into a larger conclusion.

Before finalizing speech, audit every sentence. If it mentions, paraphrases, or
clearly touches any constrained WorldInfo, include exactly one matching
disclosure_claim for that world_info_id. If the matching world_info_id or
allowed mode is unclear, remove that fact from speech or refuse.
