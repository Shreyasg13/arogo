"""
db/providers.py — "My care team": a directory of the user's own healthcare
providers (doctors, clinics, specialists).

Plain contact records the user types themselves — name, specialty, phone,
clinic, address, notes. Appointments can reference a provider by id so a visit
shows who it's with. Everything is user-scoped; nothing is looked up externally.
"""
from .core import execute, now_iso, new_id, current_user_id


def _s(v, n=200):
    return str(v or '').strip()[:n]


def create_provider(data) -> dict:
    name = _s(data.get('name'), 120)
    if not name:
        raise ValueError('A name is required')
    pid = new_id()
    execute("""INSERT INTO providers (id, name, specialty, phone, clinic, address, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (pid, name, _s(data.get('specialty'), 80), _s(data.get('phone'), 40),
             _s(data.get('clinic'), 120), _s(data.get('address'), 300),
             _s(data.get('notes'), 500), now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM providers WHERE id=?", (pid,), fetchone=True))


def update_provider(pid, data) -> dict:
    uid = current_user_id()
    row = execute("SELECT * FROM providers WHERE id=? AND user_id=?", (pid, uid), fetchone=True)
    if not row:
        raise ValueError('Provider not found')
    row = dict(row)
    name = _s(data.get('name', row['name']), 120) or row['name']
    execute("""UPDATE providers SET name=?, specialty=?, phone=?, clinic=?, address=?, notes=?
               WHERE id=? AND user_id=?""",
            (name, _s(data.get('specialty', row['specialty']), 80),
             _s(data.get('phone', row['phone']), 40), _s(data.get('clinic', row['clinic']), 120),
             _s(data.get('address', row['address']), 300), _s(data.get('notes', row['notes']), 500),
             pid, uid), commit=True)
    return dict(execute("SELECT * FROM providers WHERE id=? AND user_id=?", (pid, uid), fetchone=True))


def delete_provider(pid) -> bool:
    uid = current_user_id()
    # Unlink any appointments pointing at this provider so they don't dangle.
    try:
        execute("UPDATE appointments SET provider_id=NULL WHERE provider_id=? AND user_id=?", (pid, uid), commit=True)
    except Exception:
        pass
    from .trash import soft_delete
    return soft_delete('providers', pid)
    return True


def list_providers() -> list:
    rows = execute("SELECT * FROM providers WHERE user_id=? ORDER BY LOWER(name)",
                   (current_user_id(),), fetchall=True) or []
    return [dict(r) for r in rows]
