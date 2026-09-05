import unittest

from iosagent import tree


def node(kind, ident="", label="", frame=(0, 0, 10, 10), children=(), **extra):
    payload = {"type": kind, "frame": list(frame)}
    if ident:
        payload["id"] = ident
    if label:
        payload["label"] = label
    if children:
        payload["children"] = list(children)
    payload.update(extra)
    return payload


class Flatten(unittest.TestCase):
    def test_visits_every_node(self):
        root = node("Application", children=[node("Button", "a"), node("Button", "b")])
        self.assertEqual(len(tree.flatten(root)), 3)

    def test_identical_siblings_get_distinct_keys(self):
        root = node("Window", children=[node("Other"), node("Other")])
        keys = [n.key for n in tree.flatten(root)]
        self.assertEqual(len(keys), len(set(keys)))

    def test_identifier_wins_over_position(self):
        before = tree.flatten(node("Window", children=[node("Button", "save")]))
        after = tree.flatten(node("Window", children=[node("Other"), node("Button", "save")]))
        # the button moved in the tree but kept its identity
        self.assertNotIn("Button#save", [n.key for n in tree.diff(before, after).removed])


class Diff(unittest.TestCase):
    def test_reports_added_and_removed(self):
        before = tree.flatten(node("Window", children=[node("Button", "a", "A")]))
        after = tree.flatten(node("Window", children=[node("Button", "b", "B")]))
        result = tree.diff(before, after)
        self.assertEqual([n.id for n in result.added], ["b"])
        self.assertEqual([n.id for n in result.removed], ["a"])

    def test_reports_a_changed_label(self):
        before = tree.flatten(node("Window", children=[node("Button", "t", "Record")]))
        after = tree.flatten(node("Window", children=[node("Button", "t", "Stop")]))
        result = tree.diff(before, after)
        self.assertEqual(len(result.changed), 1)
        self.assertIn("Record", result.changed[0][2][0])
        self.assertIn("Stop", result.changed[0][2][0])

    def test_ignores_sub_threshold_movement(self):
        before = tree.flatten(node("Button", "t", "x", frame=(0, 0, 10, 10)))
        after = tree.flatten(node("Button", "t", "x", frame=(1, 0, 10, 10)))
        self.assertTrue(tree.diff(before, after).empty)

    def test_counts_unnamed_containers_separately(self):
        before = tree.flatten(node("Window"))
        after = tree.flatten(node("Window", children=[node("Other"), node("Other")]))
        result = tree.diff(before, after)
        self.assertEqual(result.added, [])
        self.assertEqual(result.added_anonymous, 2)

    def test_explains_a_modal_instead_of_listing_the_background(self):
        background = [node("Button", f"b{i}", f"B{i}") for i in range(12)]
        before = tree.flatten(node("Window", children=background))
        after = tree.flatten(node("Window", children=[node("Sheet", label="New")]))
        result = tree.diff(before, after)
        self.assertIn("modal appeared", result.modal)
        self.assertIn("inaccessible", result.modal)

    def test_interactive_keeps_only_addressable_elements(self):
        nodes = tree.flatten(node("Window", children=[
            node("Button", "go", "Go"), node("Other", label="decoration"),
        ]))
        self.assertEqual([n.id for n in tree.interactive(nodes)], ["go"])


if __name__ == "__main__":
    unittest.main()
