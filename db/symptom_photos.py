"""
db/symptom_photos.py — M3 symptom photo journal.

Attach a photo to track how something LOOKS over time — a rash, a healing
wound, swelling. Photos are grouped by a free-text label so the same thing can
be followed across days. Everything is the user's own image, shown by date:
Arogo stores and lines them up, it never analyses or diagnoses from a photo.

All queries are user-scoped. The image files live in UPLOAD_FOLDER and are
served only through the ownership-checked /uploads/<filename> route.
"""
from .core import execute, current_user_id, new_id, now_iso, valid_date, user_today


def add_photo(label: str, filename: str, taken_date=None, notes='') -> dict:
    label = str(label or '').strip()[:120] or 'Untitled'
    td = str(taken_date or '').strip()
    if not valid_date(td):
        td = user_today()
    pid = new_id()
    execute("""INSERT INTO symptom_photos (id, label, filename, taken_date, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (pid, label, filename, td, str(notes or '').strip()[:300], now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM symptom_photos WHERE id=?", (pid,), fetchone=True))


def list_photos() -> list:
    """All of the user's symptom photos, newest first. The frontend groups them
    by label into per-subject timelines."""
    rows = execute("""SELECT * FROM symptom_photos WHERE user_id=?
                      ORDER BY taken_date DESC, created_at DESC""",
                   (current_user_id(),), fetchall=True)
    return [dict(r) for r in (rows or [])]


def get_photo(pid: str):
    r = execute("SELECT * FROM symptom_photos WHERE id=? AND user_id=?",
                (pid, current_user_id()), fetchone=True)
    return dict(r) if r else None


def delete_photo(pid: str):
    """Delete the row if it's the caller's, returning its filename so the route
    can remove the file from disk. None if it wasn't theirs."""
    row = get_photo(pid)
    if not row:
        return None
    from .trash import soft_delete
    soft_delete('symptom_photos', pid)
    # The file stays on disk while the photo is recoverable; the trash owns it
    # now and removes it when the entry is purged. Returning None keeps the
    # route from deleting a file its record can still be restored to.
    return None
