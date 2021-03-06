from tests.shared import getEmptyCol


def test_deferred_frontside():
    col = getEmptyCol()
    m = col.models.current()
    m["tmpls"][0]["qfmt"] = "{{custom:Front}}"
    col.models.save(m)

    note = col.newNote()
    note["Front"] = "xxtest"
    note["Back"] = ""
    col.addNote(note)

    assert "xxtest" in note.cards()[0].a()
