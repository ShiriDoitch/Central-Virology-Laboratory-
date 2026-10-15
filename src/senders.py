"""גורם שולח: רשימה סגורה, כינויים, מיפוי סניף->קופה, והצבעה בין כל הראיות בטופס.

ההנחות כאן הן הנחות שלנו ולא כלל רשמי של המעבדה (לתעד ב-README).
הרשימות והכינויים יושבים בקבצי הגדרות: config/senders.json (בסיס), config/aliases.json (תיקוני משתמשת).
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from .rules import F_CONFLICT, F_HANDWRITTEN, F_LOW_CONFIDENCE, LOW_CONFIDENCE, Decision
from .schema import SenderMention

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
OTHER = "אחר"
F_UNKNOWN_SENDER = "unknown_sender"
F_PATIENT_FIELD_ONLY = "patient_field_only"
F_FUZZY_MATCH = "fuzzy_match"
FUZZY_MIN = 0.85               # דמיון מינימלי להתאמה מקורבת לכינוי מוכר (התאמה כזו תמיד כתומה)
FUZZY_MIN_ALIAS_LEN = 5        # כינויים קצרים יותר לא משתתפים בהתאמה מקורבת


def _dedupe_keep_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))

# משקל לפי מקום ההופעה, ומכפיל לפי התפקיד שהמודל נתן (התפקיד לא אמין: משמש רק כמשקל)
WHERE_WEIGHT = {"logo": 3.0, "header": 2.0, "stamp": 2.0, "clinic_or_doctor": 2.0, "other": 1.0, "handwritten": 1.0}
ROLE_FACTOR = {"sender": 1.0, "unknown": 0.8, "destination": 0.4}
LAB_FUZZY = 0.8      # דמיון מינימלי לשם המעבדה (כתיב רועש: "המטולב" במקום "המשולב")
CLOSE_SCORE = 0.5    # מועמד שני עם ניקוד >= חצי מהראשון = אי-הסכמה גם אם התפקיד "יעד"


def _norm(text: str) -> str:
    text = re.sub(r"[\"'״׳`]", "", text)            # גרשיים: רמב"ם -> רמבם
    text = re.sub(r"[.,\-־_/\\()]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


class SenderMatcher:
    def __init__(self, canonical: dict[str, list[str]], branches: dict[str, str],
                 lab_names: list[str], learned: dict[str, str] | None = None, hmos: list[str] | None = None):
        self.hmos = frozenset(hmos or [])      # קופות החולים (config/senders.json: "hmos"), לכלל R1
        pairs: set[tuple[str, str]] = set()
        for canon, aliases in canonical.items():
            for a in [canon, *aliases]:
                pairs.add((_norm(a), canon))
        for alias, canon in {**branches, **(learned or {})}.items():
            pairs.add((_norm(alias), canon))
        self.canonical = set(canonical) | set((learned or {}).values()) | set(branches.values())
        self._pairs = sorted((p for p in pairs if p[0]), key=lambda p: -len(p[0]))  # הכינוי הארוך קודם
        self._labs = [_norm(n) for n in lab_names]

    def match(self, text: str) -> tuple[str | None, bool]:
        """מחזיר (שם מהרשימה הסגורה או None, האם זה שם המעבדה המקבלת)."""
        n = _norm(text)
        for lab in self._labs:
            n = n.replace(lab, " ")
        n = re.sub(r"\s+", " ", n).strip()
        for alias, canon in self._pairs:
            if alias in n:
                return canon, False
        if not n or any(SequenceMatcher(None, n, lab).ratio() >= LAB_FUZZY for lab in self._labs):
            return None, True
        return None, False

    def fuzzy(self, text: str) -> str | None:
        """התאמה מקורבת כשאין התאמה מדויקת: רצף מילים בטקסט דומה (>= FUZZY_MIN) לכינוי (או לשם קנוני).
        כינויים קצרים מ-FUZZY_MIN_ALIAS_LEN תווים לא משתתפים (שגיאת תו אחת בהם משנה את המילה).
        מחזיר גורם אחד בלבד; אם כמה גורמים מתאימים באותו דמיון, או שאין אף אחד: None."""
        words = _norm(text).split()
        best: dict[str, float] = {}
        for alias, canon in self._pairs:
            if len(alias) < FUZZY_MIN_ALIAS_LEN:
                continue
            k = len(alias.split())
            for i in range(max(1, len(words) - k + 1)):
                ratio = SequenceMatcher(None, " ".join(words[i:i + k]), alias).ratio()
                if ratio >= FUZZY_MIN:
                    best[canon] = max(best.get(canon, 0.0), ratio)
        if not best:
            return None
        ranked = sorted(best.items(), key=lambda kv: -kv[1])
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return None
        return ranked[0][0]


def load_matcher(config_dir: Path = CONFIG_DIR) -> SenderMatcher:
    cfg = json.loads((config_dir / "senders.json").read_text(encoding="utf-8"))
    aliases_path = config_dir / "aliases.json"
    learned = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
    return SenderMatcher(cfg["canonical"], cfg.get("branches", {}), cfg.get("lab_names", []), learned,
                         cfg.get("hmos", []))


def add_alias(alias: str, canonical: str, config_dir: Path = CONFIG_DIR) -> None:
    """למידה מתיקון ידני: שומר כינוי חדש שישפיע על הרצות הבאות."""
    path = config_dir / "aliases.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[alias] = canonical
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_matcher: SenderMatcher | None = None


def get_matcher() -> SenderMatcher:
    global _matcher
    if _matcher is None:
        _matcher = load_matcher()
    return _matcher


def _apply_precedence(scores: dict[str, float], evidence: dict[str, list[SenderMention]],
                      hmos: frozenset[str]) -> list[str]:
    """כללי קדימות לפני ההצבעה. מסנן את scores במקום ומחזיר את הארגונים שנדרסו.
    R2: ארגון שיש לו אזכור לוגו גובר על ארגונים בלי לוגו, בלי קשר לתפקיד שהמודל נתן
        (המודל סימן לפעמים לוגו של השולח כ"יעד").
    R1: קופת חולים שאין לה אזכור לוגו מפסידה למוסד (לא קופה) שיש לו לוגו או לפחות שני אזכורים
        (למשל כותרת וחותמת); "קופ"ח" בתווית המטופל היא קופת המטופל ולא השולח."""
    overridden: list[str] = []
    logo = {c for c, items in evidence.items() if c in scores and any(m.where == "logo" for m in items)}
    if logo and set(scores) - logo:
        overridden += [c for c in scores if c not in logo]
        for c in overridden:
            del scores[c]
    hmo = [c for c in scores if c in hmos]
    institutions = [c for c in scores if c not in hmos]
    if hmo and institutions:
        hmo_has_logo = any(m.where == "logo" for c in hmo for m in evidence[c])
        institution_strong = any(
            any(m.where == "logo" for m in evidence[c]) or len(evidence[c]) >= 2 for c in institutions)
        if not hmo_has_logo and institution_strong:
            overridden += hmo
            for c in hmo:
                del scores[c]
    return overridden


def decide_sender(mentions: list[SenderMention], matcher: SenderMatcher | None = None) -> Decision:
    """מצביע בין כל האזכורים. שם המעבדה המקבלת מוחרג תמיד; אי-הסכמה או כתב יד = כתום.
    אחרי כללי הקדימות (R1, R2) המועמד שנדרס נשאר ב-alternatives, ומסומן conflict אם הוא היה מתחרה
    אמיתי (אזכור שאינו "יעד", או ניקוד של לפחות חצי מהמנצח). יעד בלבד בניקוד נמוך (למשל שיבא ככותרת)
    לא מסמן כתום."""
    matcher = matcher or get_matcher()
    scores: dict[str, float] = {}
    evidence: dict[str, list[SenderMention]] = {}
    unmatched: list[SenderMention] = []
    patient_field: list[str] = []         # קופה/משלם שכתובים בתוך תווית המטופל: קופת המטופל, לא בהכרח השולח
    fuzzy_texts: dict[str, list[str]] = {}   # גורם -> הטקסטים שהותאמו אליו בהתאמה מקורבת
    exact_canons: set[str] = set()           # גורמים שיש להם לפחות אזכור אחד בהתאמה מדויקת
    for m in mentions:
        canon, is_lab = matcher.match(m.text)
        if is_lab:
            continue
        if m.where == "patient_field":
            if canon:
                patient_field.append(canon)
            continue
        is_fuzzy = False
        if canon is None and m.role != "destination":
            canon = matcher.fuzzy(m.text)
            is_fuzzy = canon is not None
        if canon is None:
            if m.role != "destination":
                unmatched.append(m)
            continue
        scores[canon] = scores.get(canon, 0.0) + WHERE_WEIGHT.get(m.where, 1.0) * ROLE_FACTOR.get(m.role, 0.8)
        evidence.setdefault(canon, []).append(m)
        if is_fuzzy:
            fuzzy_texts.setdefault(canon, []).append(m.text)
        else:
            exact_canons.add(canon)

    patient_field = _dedupe_keep_order(patient_field)
    if not scores:
        if unmatched:  # גורם לא מוכר: "אחר", כתום, עם הטקסט כראיה (לוגו/כותרת מנצחים את שדה המטופל)
            return Decision(value=OTHER, raw=unmatched[0].text, flags=[F_UNKNOWN_SENDER],
                            alternatives=[*[m.text for m in unmatched], *patient_field])
        if patient_field:  # רק שדה בתווית המטופל: ללא דגל (ירוק); נשאר רמז, כי זו קופת המטופל ולא בהכרח השולח
            return Decision(value=patient_field[0], raw=patient_field[0], hints=[F_PATIENT_FIELD_ONLY],
                            alternatives=patient_field[1:])
        return Decision()

    scores_before = dict(scores)
    overridden = _apply_precedence(scores, evidence, matcher.hmos)
    ranked = sorted(scores, key=lambda c: -scores[c])
    top = ranked[0]
    flags: list[str] = []
    others = ranked[1:]
    if any(any(m.role != "destination" for m in evidence[c]) or scores_before[c] >= CLOSE_SCORE * scores[top]
           for c in overridden):
        flags.append(F_CONFLICT)
    if others:
        tie = scores[others[0]] == scores[top]
        disagree = any(
            any(m.role != "destination" for m in evidence[c]) or scores[c] >= CLOSE_SCORE * scores[top]
            for c in others
        )
        if tie:
            return Decision(flags=[F_CONFLICT], alternatives=ranked)
        if disagree and F_CONFLICT not in flags:
            flags.append(F_CONFLICT)
    ev = evidence[top]
    if all(m.where == "handwritten" for m in ev):
        flags.append(F_HANDWRITTEN)
    if max(m.confidence for m in ev) < LOW_CONFIDENCE:
        flags.append(F_LOW_CONFIDENCE)
    originals: list[str] = []
    if top in fuzzy_texts and top not in exact_canons:    # התאמה מקורבת בלבד: כתום, והטקסט המקורי נשמר
        flags.append(F_FUZZY_MATCH)
        originals = fuzzy_texts[top]
    return Decision(value=top, raw=ev[0].text, flags=flags,
                    alternatives=_dedupe_keep_order([*originals, *others, *overridden,
                                                     *[c for c in patient_field if c != top]]))
