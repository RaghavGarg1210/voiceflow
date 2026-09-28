"""Recorder regression tests; no microphone, hotkeys, or model downloads."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Keep macOS UI and input hooks out of the test process.
spec = importlib.util.spec_from_file_location('voiceflow_under_test', Path(__file__).with_name('voiceflow.py'))
voiceflow = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    'rumps': MagicMock(App=object),
    'sounddevice': MagicMock(),
    'pynput': MagicMock(),
}):
    spec.loader.exec_module(voiceflow)


class RecorderTests(unittest.TestCase):
    def test_failed_start_closes_stream_and_next_attempt_records(self):
        failed, working = MagicMock(), MagicMock()
        failed.start.side_effect = RuntimeError('microphone unavailable')
        recorder = voiceflow.Recorder(16000, None)
        with patch.object(voiceflow.sd, 'InputStream', side_effect=[failed, working]) as factory:
            with self.assertRaisesRegex(RuntimeError, 'microphone unavailable'):
                recorder.start()
            recorder.start()
            factory.assert_called_with(
                samplerate=16000, channels=1, dtype='float32',
                device=None, callback=recorder._callback,
            )
        failed.close.assert_called_once()
        working.start.assert_called_once()
        recorder._callback(np.array([[0.1], [0.2]], dtype=np.float32), 2, None, None)
        np.testing.assert_array_equal(recorder.stop(), np.array([0.1, 0.2], dtype=np.float32))
        working.stop.assert_called_once()
        working.close.assert_called_once()

    def test_constructor_failure_allows_retry(self):
        working = MagicMock()
        recorder = voiceflow.Recorder(16000, 2)
        with patch.object(voiceflow.sd, 'InputStream', side_effect=[RuntimeError('device missing'), working]):
            with self.assertRaisesRegex(RuntimeError, 'device missing'):
                recorder.start()
            recorder.start()
        working.start.assert_called_once()
        recorder.stop()

    def test_repeated_start_does_not_open_another_stream(self):
        recorder = voiceflow.Recorder(16000, None)
        with patch.object(voiceflow.sd, 'InputStream') as factory:
            recorder.start()
            recorder.start()
            factory.assert_called_once()
            factory.return_value.start.assert_called_once()
            self.assertEqual(recorder.stop().size, 0)
        self.assertEqual(recorder.stop().size, 0)

    def test_cleanup_error_preserves_start_error_and_allows_retry(self):
        failed, working = MagicMock(), MagicMock()
        failed.start.side_effect = RuntimeError('start failed')
        failed.close.side_effect = RuntimeError('close failed')
        recorder = voiceflow.Recorder(16000, None)
        with patch.object(voiceflow.sd, 'InputStream', side_effect=[failed, working]):
            with self.assertRaisesRegex(RuntimeError, 'start failed'):
                recorder.start()
            recorder.start()
        failed.close.assert_called_once()
        working.start.assert_called_once()
        recorder.stop()


if __name__ == '__main__':
    unittest.main()
