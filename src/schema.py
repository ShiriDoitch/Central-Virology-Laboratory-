"""סכמת הפלט של המודל. המודל מתאר מועמדים; ההחלטות נעשות בקוד (rules.py)."""
from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["printed", "handwritten", "unknown"]
Quality = Literal["ok", "poor", "unreadable"]
DateKind = Literal[
    "sample_date",        # תאריך לקיחת דגימה
    "lab_stamp",          # תאריך בתוך חותמת "התקבל" של המעבדה המקבלת
    "handwritten_date",   # תאריך אחר שנכתב ביד על הטופס
    "receipt_date",       # תאריך קבלה/קליטה שמודפס כחלק מהטופס (של השולח)
    "print_date",         # תאריך הדפסה
    "birth_date",         # תאריך לידה
    "expiry_date",        # תוקף ההתחייבות
    "shipping_date",      # תאריך שליחת הדגימה למעבדה (משמש רק לחלון התאריכים)
    "other",
]
# v2: lab_received (הסכמה הישנה) הוחלף ב-lab_stamp ו-handwritten_date. תשובות ישנות (data/part1_snapshot.json)
# מומרות בטעינה: cache.load_snapshot -> rules.effective_date_kind.
SenderRole = Literal["sender", "destination", "unknown"]
SenderWhere = Literal["logo", "header", "stamp", "handwritten", "clinic_or_doctor", "patient_field", "other"]
Rotation = Literal["0", "90", "180", "270"]


class Field_(BaseModel):
    """שדה בודד שנקרא מהעמוד."""
    value: str | None = Field(None, description="The value exactly as it appears. null if not found.")
    confidence: float = Field(0.0, description="0-1, how sure you are that you read it correctly.")
    evidence: str | None = Field(None, description="Short quote or location on the page.")
    label: str | None = Field(None, description="The label printed next to the value, copied exactly (e.g. the label of a patient name field). null if there is no label.")
    source: Source = "unknown"
    alternatives: list[str] = Field(default_factory=list, description="Other plausible readings, strings only (never null).")


class Box(BaseModel):
    """תיבה על העמוד, מנורמלת ל-0..1000 (ymin, xmin, ymax, xmax)."""
    ymin: int
    xmin: int
    ymax: int
    xmax: int


class DateCandidate(BaseModel):
    value: str = Field(description="The date exactly as written, do not fix it.")
    kind: DateKind
    evidence: str | None = Field(None, description="Nearby label text or location.")
    confidence: float = 0.0
    source: Source = "unknown"


class NumberCandidate(BaseModel):
    value: str = Field(description="The number exactly as written, digits and any prefix letters.")
    label: str | None = Field(None, description="The label next to it, as written (e.g. the word before it). null if none.")
    location: str | None = Field(None, description="Where on the page, e.g. top-left, inside barcode, rotated on the margin.")
    confidence: float = 0.0
    source: Source = "unknown"


class SenderMention(BaseModel):
    text: str = Field(description="Name of an organization, hospital, clinic, HMO or doctor, as written.")
    where: SenderWhere
    role: SenderRole = Field(description="sender = the party that sent the sample; destination = where it is sent to; unknown if unclear.")
    evidence: str | None = Field(None, description="The exact text or label this mention was read from.")
    confidence: float = 0.0


class PageExtraction(BaseModel):
    is_commitment_form: bool = Field(description="True if this page is a sample commitment form (not an invoice copy or other document).")
    page_quality: Quality
    rotation_degrees: Rotation = Field("0", description="Clockwise degrees the page must be rotated so that its main text is upright: \"0\", \"90\", \"180\" or \"270\". \"0\" if the text is already upright.")
    first_name: Field_ = Field(default_factory=Field_)
    last_name: Field_ = Field(default_factory=Field_)
    id_numbers: list[NumberCandidate] = Field(default_factory=list, description="Every occurrence of the PATIENT's ID number, each separately, with the label printed next to it (e.g. the word for ID). Not IDs of doctors or staff.")
    dates: list[DateCandidate] = Field(default_factory=list)
    numbers: list[NumberCandidate] = Field(default_factory=list, description="All other numbers that could be commitment / request / sample / center numbers.")
    sender_mentions: list[SenderMention] = Field(default_factory=list)
    patient_box: Box | None = Field(None, description="Bounding box of the area holding the patient's personal details (name, ID number, birth date), normalized 0-1000. null if none.")
    commitment_box: Box | None = Field(None, description="Bounding box of the commitment number itself (the number whose label means commitment / requisition / sample number) together with its label, normalized 0-1000. null if there is none.")
    barcode_box: Box | None = Field(None, description="Bounding box of the sticker or barcode that the word for 'central' is written next to (not a received stamp), including the numbers printed next to it, normalized 0-1000. null if none.")
    receipt_box: Box | None = Field(None, description="Bounding box of where the receiving laboratory's receipt date appears: the 'received' stamp with its date if there is one; otherwise the handwritten central number together with the date written next to or under it. normalized 0-1000. null if neither exists.")
    notes: str | None = Field(None, description="Anything unusual, e.g. several forms on one page, cut-off page.")


# ---------- מעבר שני: חיתוכים מוגדלים ----------

class PatientRead(BaseModel):
    region_ok: bool = Field(False, description="True only if image 1 really shows the patient's personal details box (name / ID fields). False otherwise; then leave the fields null.")
    first_name: Field_ = Field(default_factory=Field_)
    last_name: Field_ = Field(default_factory=Field_)
    id_number: Field_ = Field(default_factory=Field_, description="Digits only, exactly as written.")
    birth_date: Field_ = Field(default_factory=Field_, description="dd.mm.yyyy")
    labels_seen: list[Literal["first_name", "last_name", "id_number", "father_name"]] = Field(
        default_factory=list,
        description="Which field labels are actually visible (printed) in image 1: first_name, last_name, id_number, father_name. List only labels you can see; do not infer.")


class BarcodeNumber(BaseModel):
    value: str
    label: str | None = Field(None, description="The word printed next to it, if any.")
    orientation: Literal["normal", "rotated"] = "normal"
    confidence: float = 0.0


class BarcodeRead(BaseModel):
    region_ok: bool = Field(False, description="True only if image 2 really shows a barcode or sticker area. False otherwise; then leave the fields empty.")
    visible_words: list[str] = Field(default_factory=list)
    numbers: list[BarcodeNumber] = Field(default_factory=list)
    central_number: Field_ = Field(default_factory=Field_, description="The number next to which (or on which) the word for 'central' is written. null if that word is not visible.")


class CommitmentRead(BaseModel):
    region_ok: bool = Field(False, description="True only if image 3 really shows a printed commitment / requisition / sample number. False otherwise, and also when image 3 was not provided; then leave the number null.")
    number: Field_ = Field(default_factory=Field_, description="Digits only, exactly as printed. Do not correct or complete.")


class ReceiptRead(BaseModel):
    region_ok: bool = Field(False, description="True only if image 4 really shows a received stamp or a handwritten receipt date. False otherwise, and also when image 4 was not provided; then leave the fields null.")
    date: Field_ = Field(default_factory=Field_, description="The receipt date exactly as written, day-month-year. Digit by digit; unclear digits go to alternatives.")
    central_number: Field_ = Field(default_factory=Field_, description="The central number (written by hand or printed) if it is in the crop, usually next to or above the date. null if none.")


class RegionsExtraction(BaseModel):
    patient: PatientRead = Field(default_factory=PatientRead)
    barcode: BarcodeRead = Field(default_factory=BarcodeRead)
    commitment: CommitmentRead = Field(default_factory=CommitmentRead)
    receipt: ReceiptRead = Field(default_factory=ReceiptRead)
