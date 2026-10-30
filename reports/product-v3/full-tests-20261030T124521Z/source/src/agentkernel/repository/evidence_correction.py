"""A correction is eligible only after an applied candidate's observed TSan race."""
from pydantic import BaseModel, ConfigDict, Field
from agentkernel.concurrency.repair.source_edits import SourceEdit, edits_to_diff


def require_race_failure(verification):
    campaign=verification.get('evidence',{}).get('sanitizer',{}).get('campaign',{})
    runs=campaign.get('representative_runs',[])
    if not (verification.get('passed') is False and verification.get('build_passed') is True
            and verification.get('infrastructure_failures') == 0
            and campaign.get('infrastructure_failures') == 0
            and campaign.get('counts',{}).get('RACE_DETECTED',0)>0
            and any(r.get('classification')=='RACE_DETECTED'
                    and 'WARNING: ThreadSanitizer: data race' in r.get('stderr','') for r in runs)):
        raise ValueError('Correction requires a recorded TSan race on a built candidate, without infrastructure failure')


class ConflictingAccess(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    first_access: str=Field(min_length=1,max_length=2000)
    second_access: str=Field(min_length=1,max_length=2000)
    observed_evidence: str=Field(min_length=1,max_length=4000)


class EvidenceCorrection(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    conflicting_accesses: list[ConflictingAccess]=Field(min_length=1,max_length=8)
    missing_synchronization: str=Field(min_length=1,max_length=4000)
    invariant_to_preserve: str=Field(min_length=1,max_length=4000)
    edits: list[SourceEdit]=Field(min_length=1,max_length=16)


def parse_correction(text,failed_sources):
    if len(text)>300000:raise ValueError('Correction exceeds size limit')
    result=EvidenceCorrection.model_validate_json(text)
    return result,edits_to_diff(result.edits,failed_sources)
