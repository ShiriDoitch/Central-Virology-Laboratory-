"""PRIVACY_MODE: dev (ברירת מחדל) מול production. ב-production שום דבר על המטופל לא נכתב לדיסק (מטמון, חיתוכי דיבוג, p<N>.json),
והתוצאה בזיכרון (מה שהאפליקציה מציגה ומייצאת) זהה בשני המצבים."""
import io
import json
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from src import cache, extractor, pipeline, upload
from src.export import build_rows
from src.privacy import is_production, privacy_mode, safe_write_text
from src.schema import Box, NumberCandidate, PageExtraction, RegionsExtraction

ROOT = Path(__file__).resolve().parent.parent


def files_under(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def production(monkeypatch):
    monkeypatch.setenv("PRIVACY_MODE", "production")


# ---------- קריאת ההגדרה ----------

@pytest.mark.parametrize("value, mode", [(None, "dev"), ("", "dev"), ("dev", "dev"), (" DEV ", "dev"),
                                         ("production", "production"), ("Production", "production"),
                                         ("prodution", "production"), ("anything", "production")])   # שגיאת כתיב: לצד הבטוח
def test_privacy_mode_parsing(monkeypatch, value, mode):
    if value is None:
        monkeypatch.delenv("PRIVACY_MODE", raising=False)
    else:
        monkeypatch.setenv("PRIVACY_MODE", value)
    assert privacy_mode() == mode and is_production() == (mode == "production")


def test_env_example_documents_privacy_mode_with_both_modes():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "PRIVACY_MODE=dev" in text and "production" in text and "dev" in text


# ---------- A. מטמון ----------

def test_dev_mode_still_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = []
    fn = lambda arg: calls.append(1) or {"ok": True, "model": "m"}
    assert cache.cached_extract([b"img"], fn)[1] is False
    assert cache.cached_extract([b"img"], fn)[1] is True and len(calls) == 1
    assert len(files_under(tmp_path)) == 1


def test_production_cache_is_skipped_entirely_no_file_created(monkeypatch, tmp_path):
    production(monkeypatch)
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    calls = []
    fn = lambda arg: calls.append(1) or {"ok": True, "model": "m"}
    assert cache.cached_extract([b"img"], fn) == ({"ok": True, "model": "m"}, False)
    assert cache.cached_extract([b"img"], fn)[1] is False and len(calls) == 2         # בכל פעם המודל נקרא
    assert cache.cached_regions({"patient": b"a", "barcode": b"b"}, fn)[1] is False
    cache.store_result("k", {"ok": True})
    assert not (tmp_path / "cache").exists()                                           # אפילו לא התיקייה


def test_production_never_reads_an_existing_dev_cache_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    images, crops = [b"img"], {"patient": b"a", "barcode": b"b"}
    # ריצת dev קודמת השאירה קובצי מטמון (אחד מהם שבור בכוונה: אם היו קוראים אותו, זה היה קורס)
    (tmp_path / f"{cache.cache_key(images)}.json").write_text(json.dumps({"ok": True, "model": "from-old-dev-run"}), encoding="utf-8")
    (tmp_path / f"{cache.regions_cache_key(crops)}.json").write_text("{not json", encoding="utf-8")
    before = files_under(tmp_path)
    production(monkeypatch)
    result, hit = cache.cached_extract(images, lambda a: {"ok": True, "model": "fresh"})
    assert result["model"] == "fresh" and hit is False                                  # לא נקרא מהקובץ
    assert cache.cached_regions(crops, lambda a: {"ok": True, "model": "fresh"})[1] is False
    assert files_under(tmp_path) == before                                              # וגם לא נכתב / שונה כלום


# ---------- B. חיתוכי דיבוג ----------

def _jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "JPEG")
    return buf.getvalue()


def test_debug_images_written_in_dev_not_in_production(monkeypatch, tmp_path):
    boxes = {"patient": {"fractions": [0, 0, 0.5, 0.5]}}
    pipeline.save_debug_images(tmp_path / "dev", 7, _jpeg(), {"patient": b"crop", "receipt": b"crop2"}, boxes)
    assert sorted(files_under(tmp_path / "dev")) == ["p7_boxes.jpg", "p7_patient.jpg", "p7_receipt.jpg"]
    production(monkeypatch)
    pipeline.save_debug_images(tmp_path / "prod", 7, _jpeg(), {"patient": b"crop", "receipt": b"crop2"}, boxes)
    assert not (tmp_path / "prod").exists()


# ---------- C. p<N>.json ----------

def test_run_dumps_written_in_dev_not_in_production(monkeypatch, tmp_path):
    assert safe_write_text(tmp_path / "a" / "p1.json", "{}") is True and (tmp_path / "a" / "p1.json").read_text() == "{}"
    production(monkeypatch)
    assert safe_write_text(tmp_path / "b" / "p1.json", "{}") is False
    assert not (tmp_path / "b").exists()


@pytest.mark.parametrize("script", ["run_clean_claude.py", "run_second_pass.py", "run_step2_dates.py"])
def test_run_scripts_write_p_dumps_only_through_safe_write(script):
    src = (ROOT / script).read_text(encoding="utf-8")
    assert 'safe_write_text(OUT / f"p{p}.json"' in src
    assert 'f"p{p}.json").write_text' not in src                  # אין כתיבה ישירה שעוקפת את מצב הפרטיות


# ---------- התוצאה בזיכרון זהה בשני המצבים ----------

@pytest.fixture
def fake_model(monkeypatch):
    """מודל מדומה: אותה תשובה בשני המעברים; הצינור האמיתי והמטמון האמיתי רצים."""
    page = PageExtraction(is_commitment_form=True, page_quality="ok",
                          id_numbers=[NumberCandidate(value="11223344", label="ת.ז.", source="handwritten", confidence=0.9)],
                          numbers=[NumberCandidate(value="939376", label="מרכזי", confidence=0.95),
                                   NumberCandidate(value="730578626", label="התחייבות", confidence=0.95)],
                          patient_box=Box(ymin=100, xmin=50, ymax=300, xmax=900),
                          receipt_box=Box(ymin=500, xmin=100, ymax=600, xmax=400))
    calls = []

    def run(contents, schema, models=None, **kw):
        calls.append(schema.__name__)
        base = page if schema is PageExtraction else RegionsExtraction()
        return {"ok": True, "model": "m", "stats": {"api_calls": 1}, **base.model_dump()}

    monkeypatch.setattr(extractor, "_run", run)
    monkeypatch.setattr(pipeline, "pdf_to_images", lambda path, pages: [b"jpeg"])
    # חיתוך שונה לכל אזור ושטח (כמו במציאות): הניסיון החוזר של תוויות השם מרונדר באזור מוגדל ולכן אינו אותו מפתח מטמון
    monkeypatch.setattr(pipeline, "render_region", lambda path, page, fractions, **k: repr(fractions).encode())
    return calls


def test_in_memory_result_is_identical_in_both_modes_and_only_dev_writes_files(monkeypatch, tmp_path, fake_model):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "dev_cache")
    dev = pipeline.process_page("x.pdf", 1)
    assert files_under(tmp_path / "dev_cache")                                    # dev: נשמר במטמון, כמו היום
    production(monkeypatch)
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "prod_cache")
    prod = pipeline.process_page("x.pdf", 1)
    assert not (tmp_path / "prod_cache").exists()                                 # production: שום קובץ
    assert dev == prod                                                            # אותה תוצאה בזיכרון
    shown = lambda res: [{k: c.shown for k, c in r.cells.items()} for r in build_rows(res)]
    assert shown(dev) == shown(prod) and shown(prod)                              # אותה טבלה שמוצגת ומיוצאת לאקסל


def test_production_calls_the_model_every_time(monkeypatch, tmp_path, fake_model):
    production(monkeypatch)
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "c")
    pipeline.process_page("x.pdf", 1)
    n = len(fake_model)
    pipeline.process_page("x.pdf", 1)
    assert len(fake_model) == 2 * n                                               # בלי מטמון: כל הריצה שוב מול המודל


def test_process_page_with_debug_dir_writes_nothing_in_production(monkeypatch, tmp_path, fake_model):
    production(monkeypatch)
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "c")
    pipeline.process_page("x.pdf", 1, debug_dir=tmp_path / "debug")
    assert not (tmp_path / "debug").exists() and not (tmp_path / "c").exists()


# ---------- D. הקובץ הזמני של ההעלאה ----------

class _Progress:
    def progress(self, *a, **k):
        pass


def _pdf(pages=1) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    return doc.tobytes()


@pytest.fixture(autouse=True)
def upload_dir(monkeypatch, tmp_path):
    """תיקיית ההעלאות הזמניות בבדיקות: תיקייה זמנית, לא תיקיית הפרויקט האמיתית."""
    d = tmp_path / "tmp_uploads"
    monkeypatch.setattr(upload, "UPLOAD_TMP_DIR", d)
    return d


def _record_mkstemp(monkeypatch) -> list[str]:
    paths: list[str] = []
    original = upload.tempfile.mkstemp

    def record(*a, **k):
        fd, path = original(*a, **k)
        paths.append(path)
        return fd, path

    monkeypatch.setattr(upload.tempfile, "mkstemp", record)
    return paths


@pytest.mark.parametrize("mode", ["dev", "production"])
def test_uploaded_temp_pdf_is_deleted_after_processing(monkeypatch, mode, upload_dir):
    monkeypatch.setenv("PRIVACY_MODE", mode)
    paths, seen_during = _record_mkstemp(monkeypatch), []
    monkeypatch.setattr(pipeline, "process_page",
                        lambda path, p: seen_during.append(Path(path).exists()) or {"page": p, "pass1": {"ok": False, "error": "x"}, "pass2": None})
    pages, images, crops = upload.process_upload("form.pdf", _pdf(2), _Progress())
    assert len(paths) == 1 and seen_during == [True, True]            # הקובץ היה קיים בזמן העיבוד
    assert Path(paths[0]).parent == upload_dir                        # בתיקיית ההעלאות הייעודית, לא בשורש ה-temp
    assert not Path(paths[0]).exists() and list(upload_dir.iterdir()) == []      # ונמחק בסיום
    assert len(pages) == 2 and set(images) == {1, 2}                  # והתוצאה בזיכרון


@pytest.mark.parametrize("mode", ["dev", "production"])
def test_uploaded_temp_pdf_is_deleted_even_when_processing_fails(monkeypatch, mode, upload_dir):
    monkeypatch.setenv("PRIVACY_MODE", mode)
    paths = _record_mkstemp(monkeypatch)
    with pytest.raises(ValueError):
        upload.process_upload("big.pdf", _pdf(upload.MAX_PAGES + 1), _Progress())      # יותר מדי עמודים
    assert len(paths) == 1 and not Path(paths[0]).exists() and list(upload_dir.iterdir()) == []


# ---------- שאריות של ריצה שקרסה ----------

@pytest.mark.parametrize("mode", ["dev", "production"])
def test_startup_cleanup_deletes_stale_leftovers(monkeypatch, upload_dir, mode):
    monkeypatch.setenv("PRIVACY_MODE", mode)
    upload_dir.mkdir()
    stale = [upload_dir / "tmpabc123.pdf", upload_dir / "tmpdef456.pdf"]
    for f in stale:
        f.write_bytes(_pdf())
    assert upload.cleanup_stale_uploads() == 2
    assert not any(f.exists() for f in stale) and list(upload_dir.iterdir()) == []


def test_startup_cleanup_with_no_folder_is_harmless(upload_dir):
    assert not upload_dir.exists() and upload.cleanup_stale_uploads() == 0


def test_startup_cleanup_does_not_touch_files_outside_its_folder(upload_dir, tmp_path):
    upload_dir.mkdir()
    other = tmp_path / "other.pdf"
    other.write_bytes(_pdf())
    (upload_dir / "stale.pdf").write_bytes(_pdf())
    upload.cleanup_stale_uploads()
    assert other.exists()


def test_app_runs_the_cleanup_once_at_startup(monkeypatch, upload_dir):
    """app.py מנקה בהפעלה (פעם אחת לתהליך, cache_resource), עם AppTest בלי להעלות קובץ."""
    from streamlit.testing.v1 import AppTest
    upload_dir.mkdir()
    stale = upload_dir / "tmpleftover.pdf"
    stale.write_bytes(_pdf())
    import streamlit as st
    st.cache_resource.clear()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception and not stale.exists()


def test_tmp_uploads_folder_is_gitignored():
    assert "tmp_uploads/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_image_upload_is_converted_to_pdf_in_memory():
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, "JPEG")
    assert upload.to_pdf_bytes("photo.jpg", buf.getvalue())[:4] == b"%PDF"
