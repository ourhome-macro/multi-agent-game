from __future__ import annotations

from app.domain.models import AgentIntent, CasePackage, DirectorDecision, NarrativeState


class NarrativeDirector:
    def validate(
        self,
        case: CasePackage,
        narrative: NarrativeState,
        intent: AgentIntent,
    ) -> DirectorDecision:
        normalized_speech = intent.speech.lower()
        for fact in case.forbidden_facts:
            if fact.reveal_phase is not None and fact.reveal_phase == narrative.phase:
                continue
            for term in fact.blocked_terms:
                if term.lower() in normalized_speech:
                    return DirectorDecision(
                        allowed=False,
                        reason=f"Blocked forbidden fact '{fact.id}' in phase '{narrative.phase}'",
                        blocked_fact_id=fact.id,
                        safe_speech="我现在还不能谈这个。",
                    )
        return DirectorDecision(allowed=True)
