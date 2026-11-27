import threading
import unittest
from uuid import uuid4

from fastapi import HTTPException

from backend.app.routers import projects


class PaidRunOnceTest(unittest.TestCase):
    """A second click (or a second request) while a paid Claude run is going is refused, so it is paid once."""

    def test_second_start_is_refused_until_the_first_ends(self):
        project = uuid4()
        projects._paid_start("pick", project, "장면 고르기")
        try:
            with self.assertRaises(HTTPException) as caught:
                projects._paid_start("pick", project, "장면 고르기")
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.detail["code"], "PAID_RUN_IN_PROGRESS")
            self.assertIn("이미 장면 고르기 중", caught.exception.detail["message"])
            projects._paid_start("finish", project, "마무리 손질")  # another kind of run may go
            projects._paid_start("pick", uuid4(), "장면 고르기")  # and another project
        finally:
            projects._paid_end("pick", project)
            projects._paid_end("finish", project)
        projects._paid_start("pick", project, "장면 고르기")  # free again after the first ended
        projects._paid_end("pick", project)

    def test_many_at_once_only_one_goes(self):
        project, started, refused = uuid4(), [], []
        gate = threading.Barrier(8)

        def click():
            gate.wait()
            try:
                projects._paid_start("pick", project, "장면 고르기")
                started.append(1)
            except HTTPException:
                refused.append(1)
        threads = [threading.Thread(target=click) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        projects._paid_end("pick", project)
        self.assertEqual((len(started), len(refused)), (1, 7))


if __name__ == "__main__":
    unittest.main()
