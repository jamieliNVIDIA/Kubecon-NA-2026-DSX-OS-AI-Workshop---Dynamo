"""Same-campaign recovery must retain identity and cleanup gates."""
from tests.support import ROOT

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import r610_feature_retests as subject
from testlib import Run


class ResumeGuards(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workspace = Path(temporary.name).resolve()
        (workspace / 'results').mkdir()
        (workspace / 'configs').mkdir()
        (workspace / 'configs/super-vl-tp2-lock.json').write_bytes(
            (ROOT / 'configs/super-vl-tp2-lock.json').read_bytes())
        location = patch.object(subject, 'ROOT', workspace)
        location.start()
        self.addCleanup(location.stop)

    def fixture(self, root):
        run=Run(root/'grove')
        suffix=hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
        run.state['namespace']='dynamo-ft-r610-'+suffix+'-grove'
        run.state['model_lock']=json.loads((subject.ROOT/'configs/super-vl-tp2-lock.json').read_text())
        run.state['checks']['super-vl-grove']={'status':'passed'}
        run.save()
        return run

    def test_recovers_real_result_api_without_keyword_collision(self):
        with tempfile.TemporaryDirectory(dir=subject.ROOT/'results',prefix='unit-r610-') as temp:
            root=Path(temp);self.fixture(root)
            with patch.object(subject,'cleanup') as clean:
                result=subject.recover_result(root,'grove')
            self.assertEqual(result['status'],'passed')
            clean.assert_called_once()
            state=json.loads((root/'grove/state.json').read_text())
            self.assertEqual(state['checks']['r610-feature']['tested_feature'],'grove')

    def test_cannot_promote_unfinished_child(self):
        with tempfile.TemporaryDirectory(dir=subject.ROOT/'results',prefix='unit-r610-') as temp:
            root=Path(temp);run=self.fixture(root)
            del run.state['checks']['super-vl-grove'];run.save()
            with patch.object(subject,'cleanup') as clean:
                with self.assertRaisesRegex(ValueError,'terminal'):
                    subject.recover_result(root,'grove')
            clean.assert_not_called()

    def test_wrong_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=subject.ROOT/'results',prefix='unit-r610-') as temp:
            root=Path(temp);run=self.fixture(root)
            run.state['model_lock']['runtime_image']='wrong';run.save()
            with patch.object(subject,'cleanup') as clean:
                with self.assertRaisesRegex(ValueError,'identity mismatch'):
                    subject.recover_result(root,'grove')
            clean.assert_not_called()

    def test_cleanup_failure_cannot_create_pass(self):
        with tempfile.TemporaryDirectory(dir=subject.ROOT/'results',prefix='unit-r610-') as temp:
            root=Path(temp);self.fixture(root)
            with patch.object(subject,'cleanup',side_effect=RuntimeError('not idle')):
                with self.assertRaisesRegex(RuntimeError,'not idle'):
                    subject.recover_result(root,'grove')
            state=json.loads((root/'grove/state.json').read_text())
            self.assertNotIn('r610-feature',state['checks'])

    def shadow_fixture(self, root, status='blocked', shape=True):
        run=Run(root/'shadow')
        run.state['model_lock']=json.loads((subject.ROOT/'configs/super-vl-tp2-lock.json').read_text())
        run.state['checks']['r610-feature']={'status':status}
        run.save()
        if shape:
            (run.path/'failure.log').write_text('ValueError: Shape/dtype mismatch for language_model.lm_head.input_scale: param=(1,), gms=()')
        return run

    def test_alternate_control_refused_when_preferred_passed(self):
        with tempfile.TemporaryDirectory(dir=subject.ROOT/'results',prefix='unit-r610-') as temp:
            root=Path(temp);self.shadow_fixture(root,status='passed')
            with self.assertRaisesRegex(ValueError,'recorded Nemotron'):
                subject.shadow_control(root)
            self.assertFalse((root/'shadow-control').exists())

    def test_alternate_control_needs_actual_shape_failure(self):
        with tempfile.TemporaryDirectory(dir=subject.ROOT/'results',prefix='unit-r610-') as temp:
            root=Path(temp);self.shadow_fixture(root,shape=False)
            with self.assertRaisesRegex(ValueError,'recorded Nemotron'):
                subject.shadow_control(root)
            self.assertFalse((root/'shadow-control').exists())

    def test_alternate_control_rejects_other_preferred_model(self):
        with tempfile.TemporaryDirectory(dir=subject.ROOT/'results',prefix='unit-r610-') as temp:
            root=Path(temp);run=self.shadow_fixture(root)
            run.state['model_lock']['model']='other';run.save()
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                subject.shadow_control(root)
            self.assertFalse((root/'shadow-control').exists())


if __name__=='__main__':
    unittest.main()
