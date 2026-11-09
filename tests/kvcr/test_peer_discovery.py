"""KVCR must select live owned peers without probabilistic router coverage."""
import copy
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from kvcr_tests import registered_workers


class PeerDiscovery(unittest.TestCase):
    def fixture(self, path):
        pods=[];metadata=[]
        for i in (1,2):
            pods.append({'metadata':{'name':f'peer-{i}','uid':f'uid-{i}',
                'labels':{'feature-test-role':'kvcr'}},
                'status':{'conditions':[{'type':'Ready','status':'True'}]}})
            metadata.append({'metadata':{'name':f'peer-{i}',
                'ownerReferences':[{'kind':'Pod','uid':f'uid-{i}'}]},
                'spec':{'data':{'endpoints':{'generate':{'component':'backend','endpoint':'generate','instance_id':i}}}}})
        def get(*args):return {'items':pods if args[1]=='pods' else metadata}
        return SimpleNamespace(path=Path(path),ns='owned',get=get),pods,metadata

    def test_uses_both_live_registered_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            run,_,metadata=self.fixture(temp)
            other=copy.deepcopy(metadata[0]);other['metadata']['name']='unrelated';metadata.append(other)
            self.assertEqual(registered_workers(run),{1,2})

    def test_rejects_stale_pod_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            run,_,metadata=self.fixture(temp)
            metadata[0]['metadata']['ownerReferences'][0]['uid']='old-pod'
            with self.assertRaisesRegex(ValueError,'live Pod'):registered_workers(run)

    def test_requires_both_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            run,pods,_=self.fixture(temp)
            pods[0]['status']['conditions'][0]['status']='False'
            with self.assertRaisesRegex(AssertionError,'Ready'):registered_workers(run)

    def test_rejects_duplicate_peer_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            run,_,metadata=self.fixture(temp)
            metadata[1]['spec']['data']['endpoints']['generate']['instance_id']=1
            with self.assertRaisesRegex(AssertionError,'two registered'):registered_workers(run)


if __name__=='__main__':unittest.main()
