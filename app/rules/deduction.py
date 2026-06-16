from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.models import CasePackage, PlayerAction, SessionState, SolutionClaimConfig

DeductionRejectCode = Literal[
    "unknown_target",
    "unknown_claim",
    "target_mismatch",
    "phase_not_allowed",
    "empty_evidence",
    "unknown_evidence",
    "undiscovered_evidence",
    "missing_player_knowledge",
    "missing_required_evidence",
    "missing_required_world_info",
]


@dataclass(frozen=True)
class DeductionResult:
    matched_claim: str | None
    matched_required_evidence: list[str]
    missing_evidence: list[str]
    missing_world_info: list[str]
    phase_allowed: bool
    target_matches: bool
    accepted: bool
    result: Literal["correct", "incorrect"] | None
    reject_code: DeductionRejectCode | None = None
    unknown_evidence: list[str] | None = None
    undiscovered_evidence: list[str] | None = None
    missing_player_knowledge: list[str] | None = None
    evidence_clue_ids: list[str] | None = None


class DeductionEvaluator:
    def evaluate(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> DeductionResult:
        claim = next(
            (item for item in case.solution_claims.claims if item.id == action.claim_id),
            None,
        )
        evidence_ids = list(dict.fromkeys(action.evidence_clue_ids))
        known_target = any(character.id == action.target_id for character in case.characters)

        if claim is None:
            return DeductionResult(
                matched_claim=None,
                matched_required_evidence=[],
                missing_evidence=[],
                missing_world_info=[],
                phase_allowed=False,
                target_matches=False,
                accepted=False,
                result=None,
                reject_code="unknown_target" if not known_target else "unknown_claim",
                evidence_clue_ids=evidence_ids,
            )

        phase_allowed = session.narrative.phase in claim.allowed_phases
        target_matches = claim.target_id == action.target_id
        missing_required = sorted(set(claim.required_evidence) - set(evidence_ids))
        missing_world_info = self._missing_world_info(claim, session)

        if not known_target:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=self._matched_required_evidence(claim, evidence_ids),
                missing_evidence=missing_required,
                missing_world_info=missing_world_info,
                phase_allowed=phase_allowed,
                target_matches=target_matches,
                accepted=False,
                result=None,
                reject_code="unknown_target",
                evidence_clue_ids=evidence_ids,
            )

        if not target_matches:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=self._matched_required_evidence(claim, evidence_ids),
                missing_evidence=missing_required,
                missing_world_info=missing_world_info,
                phase_allowed=phase_allowed,
                target_matches=False,
                accepted=False,
                result=None,
                reject_code="target_mismatch",
                evidence_clue_ids=evidence_ids,
            )

        if not phase_allowed:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=self._matched_required_evidence(claim, evidence_ids),
                missing_evidence=missing_required,
                missing_world_info=missing_world_info,
                phase_allowed=False,
                target_matches=True,
                accepted=False,
                result=None,
                reject_code="phase_not_allowed",
                evidence_clue_ids=evidence_ids,
            )

        if not evidence_ids:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=[],
                missing_evidence=missing_required,
                missing_world_info=missing_world_info,
                phase_allowed=True,
                target_matches=True,
                accepted=False,
                result=None,
                reject_code="empty_evidence",
                evidence_clue_ids=evidence_ids,
            )

        clue_ids = {clue.id for clue in case.clues}
        unknown_evidence = sorted(set(evidence_ids) - clue_ids)
        if unknown_evidence:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=self._matched_required_evidence(claim, evidence_ids),
                missing_evidence=missing_required,
                missing_world_info=missing_world_info,
                phase_allowed=True,
                target_matches=True,
                accepted=False,
                result=None,
                reject_code="unknown_evidence",
                unknown_evidence=unknown_evidence,
                evidence_clue_ids=evidence_ids,
            )

        undiscovered = sorted(set(evidence_ids) - session.discovered_clues)
        if undiscovered:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=self._matched_required_evidence(claim, evidence_ids),
                missing_evidence=missing_required,
                missing_world_info=missing_world_info,
                phase_allowed=True,
                target_matches=True,
                accepted=False,
                result=None,
                reject_code="undiscovered_evidence",
                undiscovered_evidence=undiscovered,
                evidence_clue_ids=evidence_ids,
            )

        missing_knowledge = sorted(
            clue_id
            for clue_id in evidence_ids
            if player_knowledge_id_for_clue(case, clue_id) not in session.player_knowledge
        )
        if missing_knowledge:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=self._matched_required_evidence(claim, evidence_ids),
                missing_evidence=missing_required,
                missing_world_info=missing_world_info,
                phase_allowed=True,
                target_matches=True,
                accepted=False,
                result=None,
                reject_code="missing_player_knowledge",
                missing_player_knowledge=missing_knowledge,
                evidence_clue_ids=evidence_ids,
            )

        if missing_required:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=self._matched_required_evidence(claim, evidence_ids),
                missing_evidence=missing_required,
                missing_world_info=missing_world_info,
                phase_allowed=True,
                target_matches=True,
                accepted=False,
                result=None,
                reject_code="missing_required_evidence",
                evidence_clue_ids=evidence_ids,
            )

        if missing_world_info:
            return DeductionResult(
                matched_claim=claim.id,
                matched_required_evidence=sorted(claim.required_evidence),
                missing_evidence=[],
                missing_world_info=missing_world_info,
                phase_allowed=True,
                target_matches=True,
                accepted=False,
                result=None,
                reject_code="missing_required_world_info",
                evidence_clue_ids=evidence_ids,
            )

        return DeductionResult(
            matched_claim=claim.id,
            matched_required_evidence=sorted(claim.required_evidence),
            missing_evidence=[],
            missing_world_info=[],
            phase_allowed=True,
            target_matches=True,
            accepted=True,
            result=claim.result,
            evidence_clue_ids=evidence_ids,
        )

    def _missing_world_info(
        self,
        claim: SolutionClaimConfig,
        session: SessionState,
    ) -> list[str]:
        if not claim.required_world_info:
            return []
        known_world_info_ids = {
            item.world_info_id
            for item in session.player_knowledge.values()
            if item.world_info_id is not None
        }
        return sorted(set(claim.required_world_info) - known_world_info_ids)

    def _matched_required_evidence(
        self,
        claim: SolutionClaimConfig,
        evidence_ids: list[str],
    ) -> list[str]:
        return sorted(set(claim.required_evidence) & set(evidence_ids))


def player_knowledge_id_for_clue(case: CasePackage, clue_id: str) -> str:
    clue = next((item for item in case.clues if item.id == clue_id), None)
    if clue is None:
        return f"player_knowledge.{clue_id}"
    world_info_ids = {item.id for item in case.world_info}
    world_info_id = next(
        (item_id for item_id in clue.reveals_world_info if item_id in world_info_ids),
        None,
    )
    if world_info_id is None:
        return f"player_knowledge.{clue_id}"
    return f"player_knowledge.{world_info_id}"
