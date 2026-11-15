import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from backend.app.services import face_mosaic as fm

ME = np.array([1.0, 0.0], np.float32)
OTHER = np.array([0.0, 1.0], np.float32)


def _face(x, y, w, h):
    row = np.zeros(15, np.float32)
    row[:4] = (x, y, w, h)
    row[-1] = 0.9
    return row


class FakeModels:
    """Faces are drawn as flat squares: a bright square is me, a dark one is someone else."""

    def available(self):
        return True

    def detect(self, image):
        faces = []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        for value in (250, 40):
            ys, xs = np.where(np.abs(gray.astype(int) - value) < 8)
            if len(xs) > 50:
                faces.append(_face(xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))
        return np.array(faces, np.float32).reshape(-1, 15)

    def embed(self, image, face):
        x, y = int(face[0]), int(face[1])
        return ME if image[y + 2, x + 2].mean() > 150 else OTHER


class FollowerTest(unittest.TestCase):
    def setUp(self):
        self.follower = fm.FaceFollower(np.vstack([ME]))

    def test_keeps_me_and_hides_others(self):
        self.follower.step([((10, 10, 50, 50), 0.7), ((200, 10, 50, 50), 0.1)])
        hide, me = self.follower.step([((11, 10, 50, 50), 0.7), ((201, 10, 50, 50), 0.1)])
        self.assertEqual(hide, [(201, 10, 50, 50)])
        self.assertEqual(me, 1)

    def test_a_face_that_cannot_be_compared_is_hidden(self):
        hide, _ = self.follower.step([((10, 10, 20, 20), None)])
        self.assertEqual(hide, [(10, 10, 20, 20)])

    def test_one_lucky_frame_does_not_make_someone_me(self):
        # academy edit: a teammate scored 0.15, 0.21, then 0.60 in one frame, then 0.38, 0.35
        for sim in (0.15, 0.21, 0.60, 0.38, 0.35):
            hide, me = self.follower.step([((300, 10, 60, 60), sim)])
            self.assertEqual(hide, [(300, 10, 60, 60)])
            self.assertEqual(me, 0)

    def test_me_turning_to_the_side_stays_visible(self):
        self.follower.step([((10, 10, 50, 50), 0.56)])
        self.follower.step([((11, 10, 50, 50), 0.76)])
        for sim in (0.29, 0.08, None, 0.11):  # side face, then too blurry to compare
            hide, me = self.follower.step([((12, 10, 50, 50), sim)])
            self.assertEqual(hide, [])
            self.assertEqual(me, 1)

    def test_a_cut_forgets_who_was_where(self):
        self.follower.step([((10, 10, 50, 50), 0.7)])
        self.follower.step([((10, 10, 50, 50), 0.7)])
        self.follower.cut()
        hide, _ = self.follower.step([((10, 10, 50, 50), 0.3)])  # someone else in the same spot after the cut
        self.assertEqual(hide, [(10, 10, 50, 50)])

    def test_someone_else_missed_for_a_moment_stays_hidden(self):
        self.follower.step([((200, 10, 50, 50), 0.1)])
        for _ in range(fm.HOLD_FRAMES):
            hide, _ = self.follower.step([])
            self.assertEqual(hide, [(200, 10, 50, 50)])
        hide, _ = self.follower.step([])
        self.assertEqual(hide, [])


class MyFaceStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name) / "me" / "face"

    def tearDown(self):
        self.temp.cleanup()

    def _photo(self, value):
        image = np.full((400, 400, 3), 128, np.uint8)
        if value is not None:
            image[100:300, 100:300] = value
        ok, data = cv2.imencode(".jpg", image)
        return data.tobytes()

    def test_add_list_and_remove(self):
        face = fm.add_photo(self.dir, self._photo(250), "a.jpg", FakeModels())
        face = fm.add_photo(self.dir, self._photo(250), "b.jpg", FakeModels())
        self.assertEqual([p["filename"] for p in face.photos], ["a.jpg", "b.jpg"])
        self.assertEqual(face.prints.shape, (2, 2))
        first = face.photos[0]["id"]
        self.assertIsNotNone(fm.face_image(self.dir, first))
        face = fm.remove_photo(self.dir, first)
        self.assertEqual(len(face.photos), 1)
        self.assertIsNone(fm.face_image(self.dir, first))
        self.assertFalse((self.dir / f"{first}.jpg").exists())

    def test_photo_without_face_is_refused(self):
        with self.assertRaises(fm.FaceMosaicError) as caught:
            fm.add_photo(self.dir, self._photo(None), "empty.jpg", FakeModels())
        self.assertEqual(caught.exception.code, "FACE_NOT_FOUND")
        self.assertEqual(fm.load_my_face(self.dir).photos, ())

    def test_not_an_image_is_refused(self):
        with self.assertRaises(fm.FaceMosaicError) as caught:
            fm.add_photo(self.dir, b"not a photo", "x.jpg", FakeModels())
        self.assertEqual(caught.exception.code, "FACE_PHOTO_INVALID")

    def test_face_dir_sits_next_to_projects(self):
        self.assertEqual(fm.face_dir(Path("outputs") / "projects"), Path("outputs") / "me" / "face")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is needed")
class BlurVideoTest(unittest.TestCase):
    def test_other_face_is_pixelated_and_mine_is_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "in.mp4"
            # grey 320x180 with a smooth-gradient "other" face (dark) and a flat "me" face (bright)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=320x180:d=1:r=30",
                            "-f", "lavfi", "-i", "sine=d=1", "-vf",
                            "drawbox=x=20:y=40:w=80:h=80:color=0x282828:t=fill,drawbox=x=200:y=40:w=80:h=80:color=0xFAFAFA:t=fill",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(source)], check=True)
            output = root / "faces"
            done = fm.blur_render(source, "r1", output, fm.MyFace(({"id": "a", "embedding": [1.0, 0.0]},)), FakeModels())
            self.assertEqual(done.render_id, "r1")
            self.assertGreater(done.stats.frames_hidden, 20)
            self.assertEqual(done.stats.frames_hidden - 1, done.stats.frames_with_me)  # my face needs 2 frames to be sure
            self.assertEqual(fm.saved_video(output).stats, done.stats)
            cap = cv2.VideoCapture(str(done.path))
            for _ in range(10):  # past the first frames, where my face is not confirmed yet
                ok, frame = cap.read()
            cap.release()
            self.assertTrue(ok)
            # the hidden face's box grew over the grey background → its edge is now mixed with grey blocks
            other_edge = frame[30:40, 20:100].mean()
            mine_edge = frame[30:40, 200:280].mean()
            self.assertNotAlmostEqual(other_edge, 128, delta=3)
            self.assertAlmostEqual(mine_edge, 128, delta=6)

    def test_start_blurring_reports_failure_code(self):
        project = uuid4()
        with tempfile.TemporaryDirectory() as temp:
            reason = fm.start_blurring(project, Path(temp) / "missing.mp4", "r", Path(temp), fm.MyFace(()), FakeModels(),
                                       background=False)
            self.assertIsNone(reason)
            self.assertEqual(fm.job_state(project).status, "FAILED")
            self.assertEqual(fm.job_state(project).error_code, "FACE_NOT_REGISTERED")


if __name__ == "__main__":
    unittest.main()
