# הצעת פרומפט וסכמה v2 (הצעה בלבד, לא מיושמת)

**מטרה:** לאסוף את כל שינויי הפרומפט והסכמה לגרסה אחת, ולהריץ פעם אחת, כדי לא למחוק את המטמון שוב ושוב.
**סטטוס:** **מיושם בקוד ובבדיקות (387 בדיקות), טרם הורץ מול Gemini.** כל שינוי בפרומפט או בסכמה כבר נכנס, ולכן מפתח המטמון של המעבר הראשון השתנה (התצלום `data/part1_snapshot.json` נשאר ומומר בטעינה). אין הרצת Gemini עד אישור מפורש.
החלטות המפתחת על השאלות הפתוחות מופיעות בסוף הקובץ ומשולבות בסעיפים 5 ו-6.

## מה מיושם (סיכום)

| סעיף | סכמה | קוד |
|---|---|---|
| 1. שם מטופל בלבד + תווית | `Field_.label` | `is_father_evidence` בודק `label` ו-`evidence` |
| 2. כתב יד לא קריא = ריק | (פרומפט) | ללא שינוי (כבר מכוסה) |
| 3. `patient_field` | `SenderWhere` + `SenderMention.evidence` | `decide_sender`: לא מצביע, בחלופות; לבד = כתום `patient_field_only`; R1/R2 נשארים כרשת ביטחון |
| 4. הגדרת "שולח" | `SenderMention.evidence` | ללא שינוי נוסף |
| 5. סיבוב | `rotation_degrees` ("0"/"90"/"180"/"270") | `orientation.py` (זיהוי ציר מקומי), `plan_rotation`, `rotate_jpeg`, `render_region(rotation=)`, זרימה ב-`process_page` |
| 6. תאריך | `lab_stamp`, `handwritten_date` במקום `lab_received` | `decide_receipt_date`: חותמת מנצחת, כתב יד בהערה, כתום רק לפי כללי הביטחון הרגילים |

## זיהוי סיבוב מקומי (בלי API): מה נבדק על חלק 1

כיוון שדיווח הסיבוב של המודל הקטן לא אמין (פספס 5 מתוך 6 עמודים מסובבים), נוסף גלאי מקומי (`src/orientation.py`): הוא מחשב את מבנה שורות הטקסט (פרופיל שורות מול פרופיל עמודות אחרי הסרת קווים ארוכים). הוא מזהה את **הציר** (אופקי/אנכי), לא את הכיוון (90 מול 270, או 0 מול 180).
- **תוצאה על 26 עמודי חלק 1:** מסמן בדיוק את העמודים **3, 11, 14, 22, 23, 25**, וכולם אכן מסובבים 90° (נבדק בעין על תמונה ממוזערת). אין אזעקות שווא. כולל 14 ו-22.
- **רווח בציון:** הגבוה בין המסובבים -0.05 (עמוד 14), הנמוך בין היישרים +0.38 (עמוד 19). הסף 0.3.
- **המודל דיווח סיבוב רק על עמוד 14** (270). בעמודים 3, 11, 22, 23, 25 דיווח 0.
- **הכיוון:** הדיווח של המודל אם הוא 90/270, אחרת ניחוש 90. אם הניחוש התברר הפוך (העמוד המסובב מדווח 180), ניסיון אחד נוסף בכיוון ההפוך. כלומר בדרך כלל קריאה קטנה אחת נוספת לעמוד מסובב, ובחריג שתיים. אחרי זה, אם לא ישר: דגל `rotation_unresolved`.

## 0. מה קורה למטמון ומה העלות

- שינוי בפרומפט או בסכמה משנה את מפתח המטמון של המעבר הראשון, כלומר ריצה חדשה של כל העמודים.
- חלק 1 (26 עמודים): 26 קריאות קטנות במעבר הראשון (מרווח 5 שניות: כ-3-5 דקות כשהכול עובד), ועד קריאה חזקה אחת לעמוד שצריך מעבר שני (מכסה: 18 ליום לכל מודל חזק).
- התצלום של חלק 1 (`data/part1_snapshot.json`, סכמה ישנה) נשמר, ואפשר להשוות אליו לפני ואחרי.
- **המלצה:** להריץ על 5-6 עמודים נבחרים קודם (למשל 14, 21, 24, 26 ועמוד מסובב), ורק אז על כולם.

## 1. שם מטופל רק לפי תווית של מטופל; שם האב ובן/בת לא נחשבים; ראיה (תווית) לכל שם

**מה משתנה בפרומפט (תוספת לכללים):**
```
- first_name / last_name: only the PATIENT's name, taken from a field whose label says it is the patient
  (the person receiving the service / the examinee). Never the name of a father, mother, child, relative,
  doctor, clinician or payer. If the only name on the page is labeled as a father or a child, return null.
- For every name return `label`: the label printed next to it, copied exactly (null if there is no label).
```

**סכמה:** ב-`Field_` שדה חדש `label: str | None` ("התווית המודפסת ליד הערך"). משמש גם במעבר השני (אותו `Field_`). `evidence` נשאר.
**קוד:** `is_father_evidence` בודק גם את `label` (קודם), ואז את `evidence` כגיבוי. לא מתווספים כללי בן/בת (אין דוגמה). הכלל `handwritten_unconfirmed` ללא שינוי.
**בדיקות:** (א) תווית "שם האב" ב-`label` נדחית; (ב) תווית מטופל נשארת; (ג) `label` ריק נופל ל-`evidence`; (ד) בדיקות `father_name` הקיימות עוברות בלי שינוי.

## 2. כתב יד שלא ניתן לקרוא: ריק, בלי להשלים או לנחש

**פרומפט:**
```
- If handwriting is not legible, return null for that field. Do not complete it, do not guess it from
  context, and do not copy a name from a neighbouring printed line. Return null rather than a plausible name.
```
**סכמה:** ללא שינוי. **קוד:** ללא שינוי (הקוד כבר מאפס שם בכתב יד שאין לו שתי קריאות מסכימות).
**בדיקות:** ללא. נמדד בדוח `evaluate` (שמות ריקים מסומנים, לא שגויים).
**הערה:** כבר קיים בפרומפט הנוכחי בניסוח קצר ("If handwriting is not legible, return null. Never return an approximate or guessed name"). זו הרחבה שמכסה מפורשות את המקרה שנצפה (שם שהועתק משורה מודפסת סמוכה: עמוד 5, "ענבר הלביא").

## 3. `where` חדש: `patient_field` (קופה או משלם שכתובים בתוך תווית המטופל)

**פרומפט:**
```
- sender_mentions[].where:
    logo     = a logo at the top of the page (the issuing institution or insurer);
    header   = the institution name printed as the page title/header;
    stamp, handwritten, clinic_or_doctor, other  (as before);
    patient_field = an insurer/payer name written INSIDE the patient details box or as a field of the patient
                    (for example a field labeled "HMO"): that is the patient's insurer, not necessarily the sender.
  The logo and the institution header at the top of the page are "logo" or "header", never "patient_field".
```
**סכמה:** ב-`SenderWhere` ערך חדש `patient_field`. בנוסף שדה `evidence: str | None` ב-`SenderMention` (התווית או הטקסט שממנו נלקח האזכור), גם לסעיף 4.
**קוד:** ב-`decide_sender`: אזכור `patient_field` לא נחשב שולח כשיש לוגו או כותרת מוסד באותו עמוד (משקל 0, ונשמר בחלופות). אם הוא האזכור היחיד: מוצג בכתום (`patient_field_only`). זה הכלל שביקשת, והוא מחליף את R1 במקרה הזה (R1 נשאר כרשת ביטחון; ראו שאלה פתוחה 3).
**בדיקות:** עמוד 26: מאוחדת כ-`patient_field` ושמיר כ-`header` ← שמיר, בלי סימון כתום; אזכור `patient_field` יחיד ← כתום; בדיקות R1/R2 הקיימות ממשיכות לעבור.

## 4. הגדרה מפורשת של "גורם שולח"

**פרומפט:**
```
- sender_mentions: list every organization that could be the SENDER, i.e. whoever issued the form or sent the
  sample: the logo, the header, the insurer, the referring clinic or institution, a doctor's clinic.
  For each one return `role` (sender / destination / unknown), `where`, and `evidence`: the exact text or label
  it was read from. The receiving laboratory (the one that stamps "received") is the DESTINATION, never the sender.
  Do not decide which one is the sender: return all candidates.
```
**סכמה:** `SenderMention.evidence` (ראו סעיף 3). `role` נשאר (הקוד ממשיך להשתמש בו רק כמשקל).
**קוד:** `decide_sender` ללא שינוי מעבר לסעיף 3. `evidence` מוצג ב-audit.
**בדיקות:** `evidence` מופיע בגיליון audit; מעבדת היעד ממשיכה להיות מוחרגת לפי שמות המעבדה.

## 5. כיוון העמוד: `rotation_degrees`

**פרומפט:**
```
- rotation_degrees: how many degrees the page must be rotated clockwise so that its main text is upright:
  "0", "90", "180" or "270". Use "0" if the text is already upright.
```
**סכמה:** `rotation_needed: int` (קיים ולא בשימוש) מוחלף ב-`rotation_degrees`, כמחרוזת מתוך `"0" | "90" | "180" | "270"` (ולא int, כי enum של מספרים עלול לא להיתמך במוצא המובנה של Gemini; לאמת במימוש).
**קוד:**
1. `intake.rotate_jpeg(img, degrees)` עם Pillow.
2. ב-`process_page`: אם `rotation_degrees != "0"`, מסובבים את העמוד ומריצים שוב את המעבר הראשון **פעם אחת בלבד** על התמונה המסובבת (קריאה קטנה נוספת). אם גם אחרי הסיבוב הוא מדווח כמסובב: דגל `rotation_unresolved` (כתום) ולא סיבוב שני.
3. חיתוכי המעבר השני: `render_region` מקבל `rotation` ומשתמש ב-`page.set_rotation` של PyMuPDF לפני הרינדור, כך שהקואורדינטות של ה-box (שנמדדו על התמונה המסובבת) מתאימות.
**בדיקות:** סיבוב תמונה סינתטית ב-90/180/270 ובדיקת הגודל; `process_page` מריץ מעבר ראשון פעמיים לעמוד מסובב, ופעם אחת לעמוד ישר; בלי לולאה (פעם אחת בלבד); `render_region` עם `rotation`.
**עלות:** קריאה קטנה נוספת לכל עמוד מסובב בלבד.
**החלטה (מאושר):** להחיל פעם אחת גם כש-`page_quality` הוא `ok`.
**סיכון שנצפה בחלק 1:** רק עמוד 14 דווח כמסובב (`rotation_needed=270`), אבל **עמוד 22 מסובב בבירור והמודל דיווח עליו 0**. דיווח הסיבוב של המודל הקטן אינו אמין, ולכן בריצה הראשונה בודקים במפורש את עמוד 22. אם הדיווח נכשל שם, חלופה: להריץ 4 כיוונים ולבחור לפי ביטחון (יקר יותר), ולהחליט אחרי שרואים את התוצאה.

## 6. תאריך קבלה: חותמת "התקבל" של המעבדה מנצחת תאריך בכתב יד של השולח

**פרומפט (מחליף את ההגדרה הנוכחית של `lab_received`):**
```
- Date types:
    lab_stamp       = a date inside a received stamp applied by the receiving laboratory (a stamp that says
                      "received" with a date);
    handwritten_date = any other date written by hand onto the form;
    receipt_date    = a received/intake date that is part of the printed form (the sender's system);
    sample_date     = when the sample was taken;  print_date, birth_date, expiry_date, other  (as before).
```
**סכמה:** ב-`DateKind`: `lab_received` מוחלף ב-`lab_stamp` וב-`handwritten_date`.
**קוד (מאושר):** `decide_receipt_date` בעדיפות: `lab_stamp` > `handwritten_date` (כתום, כתב יד) > `receipt_date` מודפס (כתום) > `sample_date` (כתום). **כששניהם קיימים והם שונים: החותמת מנצחת, התאריך בכתב יד נשמר בהערה (`alternatives`), וכתום רק אם הביטחון של החותמת נמוך** (מתחת ל-`LOW_CONFIDENCE`). אין `conflict` בין חותמת לכתב יד. `effective_date_kind` (הסיווג מחדש לפי ראיות) נשאר כרשת ביטחון, מותאם לשמות החדשים (כולל הראיה "קבלה" לבדה כסימן חותמת, שכבר נוסף).
**בדיקות:** חותמת מול כתב יד שונה ← החותמת, כתב היד בהערה, ללא כתום; חותמת בביטחון נמוך ← כתום; כתב יד לבד ← כתום; עמוד 14 (חותמת `05-08-2026` מול `4-8-26`) ← `05.08.2026`; כל בדיקות התאריך הקיימות מותאמות לשמות החדשים.
**שימו לב:** זה מצמצם את ההגדרה הנוכחית (`lab_received` כולל גם חותמת וגם כתב יד שנוסף). בטבלת האמת של חלק 1, בעמודים 7 ו-12 התאריך הוא בכתב יד ללא חותמת (ולכן `handwritten_date` חייב להישאר מועמד תקף כשאין חותמת).

## מה עוד כדאי לכלול בגרסה אחת (מהממצאים עד כה, לא ביקשת)

- `Field_.label` (סעיף 1) משמש גם לת"ז: `label` מפורש במקום ניחוש לפי `evidence`.
- הנחיה כללית: "אל תחזיר ת"ז שמופיעה בשורת 'הודפס ע"י' או כשדה של איש צוות" (כבר בפרומפט הנוכחי; לשמור).

## החלטות המפתחת (14.10.2026)

1. **עמוד 13** (אותו שם בשם הפרטי ובמשפחה): **לא לכלול** כלל. אין דוגמה נוספת.
2. **חותמת מול כתב יד שונים:** החותמת מנצחת, כתב היד בהערה, כתום רק אם הביטחון נמוך (משולב בסעיף 6).
3. **R1 אחרי `patient_field`:** **להשאיר כרשת ביטחון.**
4. **סיבוב:** **כן, פעם אחת**, גם כשהאיכות `ok` (משולב בסעיף 5).
5. **הריצה הראשונה: קודם 6 עמודים, ורק אחרי שמסתכלים על התוצאה, כל חלק 1.** העמודים המוצעים:

| עמוד | למה |
|---|---|
| 14 | מסובב (270), שני מרכזיים עם התווית "מרכז", חותמת מול כתב יד, ת"ז בשני מקומות, מכון מור |
| 22 | **מסובב בבירור אבל דווח 0**: בדיקת אמינות הסיבוב. המוסד השולח חסר באזכורים |
| 21 | שם בכתב יד לא קריא (המודל החזיר ריק), ללא התחייבות |
| 24 | שולח: לוגו מול כותרת (R2); ת"ז שנקראה `11923344` |
| 26 | שם האב המודפס (`father_name`); קופ"ח בתווית המטופל (`patient_field`) |
| 5 | ת"ז המדפסת התקינה אך שגויה; ת"ז המטופל בכתב יד; חותמת "התקבל" |

העמוד השישי (5) הוא הצעה שלי: הוא מכסה את מקרה הת"ז היחיד שנשאר שגוי ללא סימון. אפשר להחליף.
6. **עמוד 14 (מכון מור):** לא נוגעים (לא מוסיפים כינוי).
7. **לא מריצים Gemini עד שהמפתחת אומרת.**
