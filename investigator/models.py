"""The provider-neutral investigation contract. No model confidence percentages."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Fact(Contract):
    name: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=220)
    kind: Literal["image_reading", "user_report", "inference"]
    source_ids: list[str] = Field(min_length=1, max_length=8)


class Constraint(Contract):
    name: str = Field(min_length=1, max_length=100)
    original: str = Field(max_length=160)
    candidate: str = Field(max_length=160)
    status: Literal["missing", "matches", "conflicts"]
    source_ids: list[str] = Field(max_length=8)


class Compatibility(Contract):
    decision: Literal["not_applicable", "unverified", "mismatch", "requirements_identified"]
    summary: str = Field(max_length=350)
    constraints: list[Constraint] = Field(max_length=10)


class Finding(Contract):
    title: str = Field(min_length=1, max_length=80)
    answer: str = Field(min_length=1, max_length=900)
    status: Literal["answered", "needs_evidence", "concluded", "safety_stop"]
    facts: list[Fact] = Field(max_length=12)
    interpretations: list[str] = Field(max_length=4)
    unknowns: list[str] = Field(max_length=6)
    next_question: str = Field(max_length=300)
    next_action: str = Field(max_length=350)
    risk: Literal["ordinary", "caution", "hazard"]
    compatibility: Compatibility


class Region(Contract):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0.03, le=1)
    height: float = Field(ge=0.03, le=1)

    @model_validator(mode="after")
    def inside_photo(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Selected area must be inside the photo")
        return self


class ImageInput(Contract):
    data: str = Field(min_length=1, max_length=8_000_000)
    mime_type: Literal["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"]
    region: Region | None = None
    conversion_receipt: str | None = Field(default=None,max_length=2048)


class TurnInput(Contract):
    question: str = Field(default="", max_length=1800)
    image: ImageInput | None = None
    consent: bool = False
    decision_goal: Literal['general','dc_adapter','filter','thread'] = 'general'


class Specification(Contract):
    subject: Literal['original','candidate']
    name: Literal['voltage','current','polarity','connector_outer','connector_inner','regulated_dc','thread_diameter','thread_standard','filter_width','filter_length','filter_depth']
    value: str = Field(min_length=1,max_length=60)
    unit: Literal['V','A','mm','in','text']
    picture_id: str | None = Field(default=None,max_length=3)
    replaces_id: str | None = Field(default=None,max_length=4)
    basis: Literal['measured','nominal','label','manual','unspecified'] = 'unspecified'
    current_is_requirement: bool = False

    @model_validator(mode='after')
    def valid_unit(self):
        if self.current_is_requirement and (self.subject!='original' or self.name!='current' or self.basis not in ('label','manual')):
            raise ValueError('Confirm a device current requirement from its label or manual, not an adapter maximum.')
        expected={'voltage':('V',),'current':('A',),'polarity':('text',),'regulated_dc':('text',),'thread_standard':('text',)}
        if self.unit not in expected.get(self.name,('mm','in')):raise ValueError('Choose the appropriate unit for this specification.')
        if self.name=='polarity':
            self.value=self.value.lower().replace(' ','').replace('-','')
            if self.value not in ('centerpositive','centernegative'):raise ValueError('Use center positive or center negative.')
        if self.name=='regulated_dc':
            self.value=self.value.lower().strip()
            if self.value not in ('yes','no'):raise ValueError('Confirm regulated DC with yes or no.')
        return self
