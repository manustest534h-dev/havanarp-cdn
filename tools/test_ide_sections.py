import unittest

from ide_sections import (
    MARKER,
    add_placeholder_collisions,
    collision_records,
    object_names,
    relocate_appended_objects,
)


class IdeSectionsTest(unittest.TestCase):
    def test_relocates_objects_before_objs_terminator(self) -> None:
        payload = (
            b"objs\r\n"
            b"1, base, base, 100, 0\r\n"
            b"\r\n"
            b"end\r\n"
            b"anim\r\n"
            b"2, animated, animated, idle, 100, 0\r\n"
            b"#end\r\n"
            b"\r\n"
            + MARKER
            + b"\r\n"
            b"17000, flag, lr, 299, 2097156\r\n"
        )

        repaired = relocate_appended_objects(payload)

        self.assertEqual(repaired.count(MARKER), 1)
        self.assertLess(repaired.index(MARKER), repaired.index(b"\r\nend\r\n"))
        self.assertTrue(repaired.endswith(b"#end\r\n"))
        self.assertEqual(object_names(repaired), ["flag"])

    def test_requires_unique_marker(self) -> None:
        with self.assertRaisesRegex(ValueError, "not unique"):
            relocate_appended_objects(
                b"objs\nend\n" + MARKER + b"\n" + MARKER + b"\n"
            )

    def test_adds_named_placeholder_collisions(self) -> None:
        template = (
            b"COL3"
            + (132).to_bytes(4, "little")
            + b"template".ljust(20, b"\0")
            + bytes(112)
        )

        repaired = add_placeholder_collisions(template, ["flag_one", "flag_two"])

        self.assertEqual(
            [name for _, _, name in collision_records(repaired)],
            ["template", "flag_one", "flag_two"],
        )


if __name__ == "__main__":
    unittest.main()
