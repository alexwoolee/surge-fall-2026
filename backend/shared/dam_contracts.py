"""Strict public aggregates for the Toddbrook historical screening worker."""

from datetime import date, datetime
import re
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import BeforeValidator, Field, StrictBool, model_validator

from backend.shared.contracts import Contract, Count, Finite, Fraction, TaskID

Window = Literal['2007-2008', '2015-2019', 'outside-coverage']
WINDOWS = {'2007-2008': (date(2007, 9, 3), date(2008, 2, 29)),
           '2015-2019': (date(2015, 10, 1), date(2019, 7, 31))}


def _date(value):
    if isinstance(value, datetime) or not (type(value) is date or isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
        raise ValueError('Use an exact ISO calendar date.')
    return value


CalendarDate = Annotated[date, BeforeValidator(_date)]
RecordRef = Annotated[str, Field(strict=True, pattern=r'^r_[a-f0-9]{24}$')]
RiskLevel = Literal['low', 'moderate', 'high', 'critical', 'unknown']
LIMITATIONS = (
    'Historical screening rules indicate concern, not a calibrated probability of dam failure or a flood forecast.',
    'Confidence measures evidence coverage and freshness; it is not the probability that flooding will occur.',
    'No breach hydraulics, inundation extent, downstream exposure or flood depth is calculated.',
    'Only observations available on or before the selected date are used; gaps between supported periods are not evidence of safety.',
    'Maintenance opening dates are treated as first availability where no separate availability date is recorded.',
    'A top water level of 185.67 mOD and a 0.03 m full-pool tolerance are fixed screening assumptions.',
    'Undated design information and retrospective event summaries are excluded from risk calculations.',
    'Annual instrumentation is conservatively counted only after that calendar year ends and its availability date has passed.',
)
Limitations = Literal[*LIMITATIONS]


class DamTask(Contract):
    task_id: TaskID = Field(default_factory=lambda: str(uuid4()))
    analysis_type: Literal['dam_risk'] = 'dam_risk'
    site_id: Literal['toddbrook'] = 'toddbrook'
    window: Window
    as_of: CalendarDate

    @model_validator(mode='after')
    def bounded_date(self) -> Self:
        if not 1900 <= self.as_of.year <= 2100:
            raise ValueError('Screening dates must be between 1900 and 2100.')
        inside = any(start <= self.as_of <= end for start, end in WINDOWS.values())
        if self.window == 'outside-coverage':
            if inside:
                raise ValueError('Select the supported period for this date.')
        elif not WINDOWS[self.window][0] <= self.as_of <= WINDOWS[self.window][1]:
            raise ValueError('Date must be inside the selected supported period.')
        return self


class DamSite(Contract):
    id: Literal['toddbrook'] = 'toddbrook'
    name: Literal['Toddbrook Reservoir'] = 'Toddbrook Reservoir'
    locality: Literal['Whaley Bridge, Derbyshire, England'] = 'Whaley Bridge, Derbyshire, England'
    latitude: Literal[53.327995] = 53.327995
    longitude: Literal[-1.99005] = -1.99005


class DamMetrics(Contract):
    recent_visit_count: Annotated[Count, Field(le=10000)]
    full_pool_visit_count: Annotated[Count, Field(le=10000)]
    latest_pool_level_mod: Annotated[Finite, Field(ge=0, le=1000)] | None
    latest_pool_departure_m: Annotated[Finite, Field(ge=-1000, le=1000)] | None
    latest_visit_age_days: Annotated[Count, Field(le=100000)] | None
    latest_supervision_age_days: Annotated[Count, Field(le=100000)] | None
    latest_instrumentation_age_days: Annotated[Count, Field(le=100000)] | None
    sealant_defect_fraction: Fraction | None
    blocked_relief_fraction: Fraction | None
    seepage_at_full_pool_fraction: Fraction | None
    current_spillway_flowing: StrictBool | None
    open_maintenance_count: Annotated[Count, Field(le=10000)]
    long_open_maintenance_count: Annotated[Count, Field(le=10000)]
    latest_inspection_grade: Literal['A', 'B', 'C', 'D', 'E'] | None
    known_integrity_action: StrictBool
    monitoring_gap: StrictBool

    @model_validator(mode='after')
    def consistent(self) -> Self:
        if self.full_pool_visit_count > self.recent_visit_count or self.long_open_maintenance_count > self.open_maintenance_count:
            raise ValueError('Aggregate counts are inconsistent.')
        if (self.recent_visit_count == 0) != (self.sealant_defect_fraction is None) or (self.recent_visit_count == 0) != (self.blocked_relief_fraction is None):
            raise ValueError('Observation fractions require matching denominators.')
        if (self.full_pool_visit_count == 0) != (self.seepage_at_full_pool_fraction is None):
            raise ValueError('Full-pool fraction requires a matching denominator.')
        if (self.latest_pool_level_mod is None) != (self.latest_pool_departure_m is None) or (self.latest_pool_level_mod is None) != (self.latest_visit_age_days is None):
            raise ValueError('Latest observation fields must be present together.')
        if self.latest_pool_level_mod is not None and abs(self.latest_pool_level_mod - 185.67 - self.latest_pool_departure_m) > 1e-9:
            raise ValueError('Pool departure must agree with the fixed screening datum.')
        if self.current_spillway_flowing is not None and (self.latest_visit_age_days is None or self.latest_visit_age_days > 7):
            raise ValueError('Current flow requires a recent observation.')
        return self


class DamCounts(Contract):
    operations: Annotated[Count, Field(le=10000)]
    supervision: Annotated[Count, Field(le=10000)]
    inspection: Annotated[Count, Field(le=10000)]
    maintenance: Annotated[Count, Field(le=10000)]
    instrumentation: Annotated[Count, Field(le=10000)]


class DamEvidence(Contract):
    record_count: Annotated[Count, Field(le=50000)]
    record_refs: Annotated[list[RecordRef], Field(max_length=50000)]
    counts: DamCounts
    first_observation: CalendarDate | None
    last_observation: CalendarDate | None

    @model_validator(mode='after')
    def consistent(self) -> Self:
        if self.record_count != sum(self.counts.model_dump().values()) or len(self.record_refs) != self.record_count or len(set(self.record_refs)) != self.record_count:
            raise ValueError('Evidence references and aggregate counts must agree.')
        if (self.counts.operations == 0) != (self.first_observation is None) or (self.first_observation is None) != (self.last_observation is None):
            raise ValueError('Observation coverage must agree with its count.')
        if self.first_observation and self.first_observation > self.last_observation:
            raise ValueError('Observation coverage must be ordered.')
        return self


RULE_CRITERIA = {
    'D01': 'At least 3 visits in the last 90 days and sealant defects in at least half.',
    'D02': 'At least 3 visits in the last 90 days and blocked relief in at least half.',
    'D03': 'At least 3 full-pool visits in the last 90 days and crest-joint seepage in at least 30 percent.',
    'D04': 'At least one open engineering maintenance item older than 365 days.',
    'D05': 'Latest available inspection grade is D or E, or a hydraulic-integrity action is known.',
    'D06': 'Latest observation is at most 7 days old and shows spillway flow or pool above 185.70 mOD.',
    'D07': 'Supervision or instrumentation evidence is missing, or the latest available records indicate unavailable pressure monitoring.',
}
RuleID = Literal[*RULE_CRITERIA.keys()]
Criterion = Literal[*RULE_CRITERIA.values()]


class DamRule(Contract):
    rule_id: RuleID
    triggered: StrictBool
    criterion: Criterion
    record_count: Annotated[Count, Field(le=50000)]

    @model_validator(mode='after')
    def criterion_matches(self) -> Self:
        if self.criterion != RULE_CRITERIA[self.rule_id]:
            raise ValueError('Rule criterion must match its identifier.')
        return self


class DamSummary(Contract):
    risk_level: RiskLevel
    risk_score: Annotated[Count, Field(le=100)] | None
    alert: StrictBool
    confidence_level: Literal['low', 'moderate', 'high']
    confidence_score: Fraction
    hydraulic_loading: Literal['normal', 'elevated', 'unknown']
    integrity_concern: Literal['low', 'moderate', 'high', 'unknown']


def expected_rules(metrics: DamMetrics) -> dict[str, bool]:
    m = metrics
    return {
        'D01': m.recent_visit_count >= 3 and m.sealant_defect_fraction >= .5,
        'D02': m.recent_visit_count >= 3 and m.blocked_relief_fraction >= .5,
        'D03': m.full_pool_visit_count >= 3 and m.seepage_at_full_pool_fraction >= .3,
        'D04': m.long_open_maintenance_count > 0,
        'D05': m.latest_inspection_grade in ('D', 'E') or m.known_integrity_action,
        'D06': m.latest_visit_age_days is not None and m.latest_visit_age_days <= 7 and (m.current_spillway_flowing is True or m.latest_pool_departure_m > .03),
        'D07': m.monitoring_gap,
    }


def expected_summary(m: DamMetrics, counts: DamCounts) -> DamSummary:
    rules = expected_rules(m)
    structural = sum(rules[k] for k in ('D01', 'D02', 'D03'))
    integrity = 'high' if rules['D05'] or structural >= 2 and rules['D04'] else 'moderate' if structural or rules['D04'] else 'low'
    recent = m.latest_visit_age_days is not None and m.latest_visit_age_days <= 7
    loading = 'elevated' if rules['D06'] else 'normal' if recent else 'unknown'
    enough = m.recent_visit_count >= 3 and m.latest_visit_age_days is not None and m.latest_visit_age_days <= 30
    risk = ('critical' if integrity == 'high' and loading == 'elevated' else 'high' if integrity == 'high' else 'moderate' if integrity == 'moderate' or loading == 'elevated' else 'low') if enough else 'unknown'
    confidence = (.35 if recent and m.recent_visit_count >= 3 else .2 if counts.operations else 0)
    confidence += .2 if m.latest_supervision_age_days is not None and m.latest_supervision_age_days <= 400 else 0
    confidence += .15 if counts.inspection else 0
    confidence += .15 if m.latest_instrumentation_age_days is not None and m.latest_instrumentation_age_days <= 400 else 0
    confidence += .15 if counts.maintenance else 0
    confidence = round(max(0, min(1, confidence - (.25 if m.monitoring_gap else 0))), 2)
    return DamSummary(risk_level=risk, risk_score={'unknown': None, 'low': 10, 'moderate': 35, 'high': 70, 'critical': 90}[risk],
                      alert=risk in ('high', 'critical'), confidence_level='high' if confidence >= .8 else 'moderate' if confidence >= .5 else 'low',
                      confidence_score=confidence, hydraulic_loading=loading, integrity_concern=integrity if enough else 'unknown')


class DamResult(Contract):
    task_id: TaskID
    worker_id: Literal['dam-worker'] = 'dam-worker'
    analysis_type: Literal['dam_risk'] = 'dam_risk'
    status: Literal['complete'] = 'complete'
    site: DamSite = Field(default_factory=DamSite)
    window: Window
    as_of: CalendarDate
    summary: DamSummary
    metrics: DamMetrics
    evidence: DamEvidence
    rules: Annotated[list[DamRule], Field(min_length=7, max_length=7)]
    limitations: Annotated[list[Limitations], Field(min_length=8, max_length=8)]
    methodology: Literal['toddbrook-screening-v1'] = 'toddbrook-screening-v1'

    @model_validator(mode='after')
    def consistent(self) -> Self:
        DamTask(task_id=self.task_id, window=self.window, as_of=self.as_of)
        if self.summary != expected_summary(self.metrics, self.evidence.counts):
            raise ValueError('Summary must agree with the screening rules and evidence metrics.')
        if {r.rule_id: r.triggered for r in self.rules} != expected_rules(self.metrics):
            raise ValueError('Rules must agree with the aggregate measurements.')
        if self.limitations != list(LIMITATIONS):
            raise ValueError('Required screening limitations must be retained.')
        if self.window == 'outside-coverage' and self.evidence.record_count:
            raise ValueError('Outside-coverage results cannot claim observed private evidence.')
        if self.evidence.last_observation and not WINDOWS[self.window][0] <= self.evidence.first_observation <= self.evidence.last_observation <= self.as_of:
            raise ValueError('Observation coverage must stay inside the requested period and cutoff.')
        metrics, counts = self.metrics, self.evidence.counts
        if metrics.recent_visit_count > counts.operations or metrics.open_maintenance_count > counts.maintenance:
            raise ValueError('Measurement counts cannot exceed their available evidence.')
        if (counts.operations == 0) != (metrics.latest_visit_age_days is None):
            raise ValueError('Latest observation must agree with operations coverage.')
        if self.evidence.last_observation and metrics.latest_visit_age_days != (self.as_of - self.evidence.last_observation).days:
            raise ValueError('Observation age must agree with its date and cutoff.')
        if (counts.supervision == 0) != (metrics.latest_supervision_age_days is None) or (counts.instrumentation == 0) != (metrics.latest_instrumentation_age_days is None):
            raise ValueError('Monitoring coverage must agree with evidence counts.')
        if not counts.inspection and metrics.latest_inspection_grade is not None:
            raise ValueError('An inspection grade requires inspection evidence.')
        if not counts.inspection and not metrics.open_maintenance_count and metrics.known_integrity_action:
            raise ValueError('A known integrity action requires supporting evidence.')
        if (not counts.supervision or not counts.instrumentation) and not metrics.monitoring_gap:
            raise ValueError('Absent monitoring cannot be declared available.')
        expected_counts = {'D01': metrics.recent_visit_count, 'D02': metrics.recent_visit_count,
                           'D03': metrics.full_pool_visit_count, 'D04': metrics.open_maintenance_count,
                           'D05': int(counts.inspection > 0) + metrics.open_maintenance_count,
                           'D06': int(metrics.latest_visit_age_days is not None and metrics.latest_visit_age_days <= 7),
                           'D07': int(counts.supervision > 0) + int(counts.instrumentation > 0)}
        if any(rule.record_count != expected_counts[rule.rule_id] for rule in self.rules):
            raise ValueError('Rule support counts must agree with the available evidence.')
        return self
