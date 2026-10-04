"""Resolve bounded prompt locations/dates before any worker can be contacted.

Registered place names have explicit coordinates. Other locations require an
explicit WGS84 bbox; neither a model nor a worker guesses a place's geometry.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import re

from backend.shared.contracts import BoundingBox
from backend.shared.context_contracts import ContextTask
from backend.shared.dam_contracts import DamTask, window_for_date


TODDBROOK_BBOX = (-2.10, 53.25, -1.85, 53.40)
TODDBROOK_NAME = 'Toddbrook Reservoir, Whaley Bridge, Derbyshire, England'
EXAMPLES = [
    f'Assess flood risk at {TODDBROOK_NAME} as of 2007-12-09. Explain in plain language whether the combined rainfall, ground conditions and dam condition indicate routine maintenance, a concerning combination, or a severe independent concern. Put technical evidence after the summary.',
    f'Assess flood risk at {TODDBROOK_NAME} as of 2019-08-01. Explain in plain language whether the combined rainfall, ground conditions and dam condition indicate routine maintenance, a concerning combination, or a severe independent concern. Put technical evidence after the summary.',
]
_DATE = re.compile(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)')
_BOX = re.compile(r'\bbbox\s*[:=]\s*\[([^\]]+)\]', re.I)
_TARGET = re.compile(r'\b(?:at|for|in|investigate|review|location\s*:)\s+(?:the\s+)?Toddbrook\s+Reservoir\b|^Toddbrook\s+Reservoir\b', re.I)


class PlanningError(ValueError):
    """A fixed, safe clarification message; never a raw external exception."""


@dataclass(frozen=True)
class InvestigationPlan:
    location_id: str
    name: str
    bbox: BoundingBox
    as_of: date
    start: datetime
    end: datetime
    dam_window: str | None

    def public(self):
        return {'location_id': self.location_id, 'name': self.name,
                'bbox': self.bbox.model_dump(mode='json'), 'as_of': self.as_of.isoformat(),
                'start': self.start.isoformat(), 'end': self.end.isoformat(),
                'private_worker_applicable': self.location_id == 'toddbrook'}

    def tasks(self, task_id):
        values = dict(task_id=task_id, location_id=self.location_id, bbox=self.bbox,
                      as_of=self.as_of, start_time=self.start, end_time=self.end)
        tasks = {'hydro': ContextTask(analysis_type='hydrometeorology', **values),
                 'flood': ContextTask(analysis_type='surface_water_and_terrain', **values)}
        if self.location_id == 'toddbrook' and self.dam_window is not None:
            tasks['dam'] = DamTask(task_id=task_id, window=self.dam_window, as_of=self.as_of)
        return tasks


def resolve_prompt(prompt: str, *, today=None) -> InvestigationPlan:
    if (not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode('utf-8')) > 4096
            or any(ord(c) < 32 and c not in '\t\n' for c in prompt)):
        raise PlanningError('Specify a location and ISO historical date in a request of at most 4096 bytes.')
    found = list(dict.fromkeys(_DATE.findall(prompt)))
    try:
        dates = [date.fromisoformat(value) for value in found]
        if not 1 <= len(dates) <= 2 or dates != sorted(dates):
            raise ValueError
        as_of = dates[-1]
        if dates[0].year < 1900 or as_of > (today or datetime.now(timezone.utc).date()):
            raise ValueError
        end = datetime.combine(as_of + timedelta(days=1), time.min, tzinfo=timezone.utc)
        start = datetime.combine(dates[0], time.min, tzinfo=timezone.utc)
        if not timedelta(0) < end - start <= timedelta(days=7):
            raise ValueError
    except (ValueError, OverflowError):
        raise PlanningError('Use one historical ISO date (YYYY-MM-DD), or an ordered inclusive range of at most seven days.') from None
    box_matches = list(_BOX.finditer(prompt))
    if len(box_matches) > 1:
        raise PlanningError('Use one location and one bounding box per investigation.')
    explicit = None
    if box_matches:
        try:
            numbers = [float(value.strip()) for value in box_matches[0].group(1).split(',')]
            if len(numbers) != 4:
                raise ValueError
            explicit = BoundingBox(**dict(zip(('west', 'south', 'east', 'north'), numbers)))
        except (TypeError, ValueError):
            raise PlanningError('Use bbox=[west,south,east,north] with finite WGS84 coordinates.') from None
    mentions_dam = bool(re.search(r'\bToddbrook\b', prompt, re.I))
    target_dam = bool(_TARGET.search(prompt))
    # Comparisons/negations cannot turn a mention of the private site into a target.
    ambiguous = bool(re.search(r'\b(?:compare|versus|vs)\b|\b(?:not|except|exclude|excluding|instead of)\s+(?:the\s+)?Toddbrook\b', prompt, re.I))
    if mentions_dam:
        before_target = re.split(r'\bToddbrook\b', prompt, maxsplit=1, flags=re.I)[0]
        if re.search(r"\b(?:not|never|don't|exclude)\b[^.;\n]{0,100}$", before_target, re.I):
            ambiguous = True
    # Reject a second named reservoir, even if its name is not in our registry.
    other_reservoir = any(match.group(1).lower() not in {'toddbrook', 'the', 'this', 'that', 'a', 'each'}
                          for match in re.finditer(r'\b([A-Za-z][A-Za-z-]+)\s+Reservoir\b', prompt, re.I))
    if target_dam and not ambiguous and not other_reservoir:
        suffix = re.split(r'\bToddbrook\s+Reservoir\b', prompt, maxsplit=1, flags=re.I)[1]
        locality = re.split(r'\b(?:as of|on|from|during|around|between|date|for)\b|\d{4}-\d{2}-\d{2}|[.;\n]', suffix, maxsplit=1, flags=re.I)[0]
        words = set(re.findall(r'[a-z]+', locality.lower()))
        if words - {'whaley', 'bridge', 'derbyshire', 'england', 'uk', 'united', 'kingdom', 'gb', 'whaleybridge'}:
            raise PlanningError('Toddbrook Reservoir is registered at Whaley Bridge, Derbyshire, England. Resolve the conflicting location before dispatch.')
        if explicit is not None and explicit.as_tuple() != TODDBROOK_BBOX:
            raise PlanningError('The named Toddbrook site conflicts with the supplied bbox; use its configured area or a separate generic AOI request.')
        location_id, name, coordinates = 'toddbrook', TODDBROOK_NAME, TODDBROOK_BBOX
    elif explicit is not None:
        # An arbitrary AOI never gains access to site-specific records by proximity.
        digest = hashlib.sha256(repr(explicit.as_tuple()).encode()).hexdigest()[:16]
        location_id, name, coordinates = 'aoi-' + digest, 'User-specified WGS84 area', explicit.as_tuple()
    elif mentions_dam:
        raise PlanningError('Specify Toddbrook Reservoir as the single target, or supply the other location with bbox=[west,south,east,north].')
    elif re.search(r'\b(?:Abbotsford|Sumas Prairie)\b', prompt, re.I) and not other_reservoir:
        location_id, name, coordinates = 'abbotsford', 'Abbotsford / Sumas Prairie, British Columbia', (-122.45, 48.95, -121.95, 49.30)
    else:
        raise PlanningError('For another location, include bbox=[west,south,east,north]. Place names alone must be registered before they can be resolved without guessing.')
    bbox = BoundingBox(**dict(zip(('west', 'south', 'east', 'north'), coordinates)))
    if bbox.east - bbox.west > 2 or bbox.north - bbox.south > 2:
        raise PlanningError('Keep the investigation area within two degrees of longitude and latitude.')
    plan = InvestigationPlan(location_id, name, bbox, as_of, start, end,
                             window_for_date(as_of) if location_id == 'toddbrook' else None)
    return plan
