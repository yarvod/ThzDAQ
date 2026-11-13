"""A change looked at hunk by hunk, without Qt: its hunks, taking and leaving
one or all, what a waiting hunk counts as by where the change comes from, the
rows the editor shows."""

from thzdaq_gui.review import Kind, Review, Source, hunks

BASE = "a = 1\nb = 2\nc = 3\nd = 4\n"
# b changed, a line after c, d gone
PROPOSED = "a = 1\nb = 20\nc = 3\nc2 = 5\n"


def test_hunks_are_the_lines_that_differ():
    found = hunks(BASE, PROPOSED)
    assert [(h.start, h.old, h.new) for h in found] == [
        (1, ("b = 2\n",), ("b = 20\n",)),
        (3, ("d = 4\n",), ("c2 = 5\n",)),
    ]
    assert hunks(BASE, BASE) == ()
    assert [(h.start, h.old, h.new) for h in hunks("", "x\n")] == [(0, (), ("x\n",))]


def test_taking_and_leaving_one_or_all():
    review = Review(BASE, PROPOSED, Source.PROPOSED)
    assert review.waiting() == [0, 1] and not review.done()
    assert review.text() == BASE  # nothing proposed is taken before ✓
    review.take(1)
    assert review.text() == "a = 1\nb = 2\nc = 3\nc2 = 5\n"
    review.leave(0)
    assert review.done() and review.text() == "a = 1\nb = 2\nc = 3\nc2 = 5\n"
    review = Review(BASE, PROPOSED, Source.PROPOSED)
    review.take_all()
    assert review.done() and review.text() == PROPOSED
    review = Review(BASE, PROPOSED, Source.PROPOSED)
    review.take(0)
    review.leave_all()  # the waiting ones: the one taken stays
    assert review.text() == "a = 1\nb = 20\nc = 3\nd = 4\n"


def test_a_change_made_outside_counts_until_it_is_taken_back():
    review = Review(BASE, PROPOSED, Source.OUTSIDE)
    assert review.text() == PROPOSED  # the file has it already
    review.leave(0)
    assert review.text() == "a = 1\nb = 2\nc = 3\nc2 = 5\n"
    review.leave_all()
    assert review.text() == BASE
    # Compared with the text here: mine until the file's hunk is taken
    review = Review(BASE, PROPOSED, Source.COMPARED)
    assert review.text() == BASE
    review.take(1)
    assert review.text() == "a = 1\nb = 2\nc = 3\nc2 = 5\n"


def test_rows_show_what_goes_and_what_comes_of_a_waiting_hunk():
    review = Review(BASE, PROPOSED, Source.PROPOSED)
    shown = [(r.text, r.kind, r.hunk, r.line) for r in review.rows()]
    assert shown == [
        ("a = 1", Kind.SAME, None, 1),
        ("b = 2", Kind.GOES, 0, 2),  # in the text until it is taken
        ("b = 20", Kind.COMES, 0, None),
        ("c = 3", Kind.SAME, None, 3),
        ("d = 4", Kind.GOES, 1, 4),
        ("c2 = 5", Kind.COMES, 1, None),
    ]
    made = Review(BASE, PROPOSED, Source.OUTSIDE).rows()
    assert [(r.text, r.line) for r in made[1:3]] == [("b = 2", None), ("b = 20", 2)]
    assert review.first_row(1) == 4
    review.take(0)
    shown = [(r.text, r.kind, r.line) for r in review.rows()]
    assert shown[:3] == [
        ("a = 1", Kind.SAME, 1),
        ("b = 20", Kind.SAME, 2),
        ("c = 3", Kind.SAME, 3),
    ]
    assert review.first_row(0) is None


def test_a_line_that_is_the_same_in_both_still_shows_where_it_belongs():
    review = Review("x\n", "y\nx\nx\n", Source.PROPOSED)
    assert [(r.text, r.kind) for r in review.rows()] == [
        ("y", Kind.COMES),
        ("x", Kind.SAME),
        ("x", Kind.COMES),
    ]


def test_the_last_line_without_its_end_is_kept_as_it_is():
    review = Review("a\nb", "a\nb\nc", Source.PROPOSED)
    review.take_all()
    assert review.text() == "a\nb\nc"
    review = Review("a\nb", "a\nb\nc", Source.PROPOSED)
    review.leave_all()
    assert review.text() == "a\nb"
