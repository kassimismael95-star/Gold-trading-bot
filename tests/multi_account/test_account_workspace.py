import importlib.util,tempfile,os
spec=importlib.util.spec_from_file_location('provisioner','services/oracle-agent/account_provisioner.py')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
def test_provision_isolated_and_secret_filtered():
 with tempfile.TemporaryDirectory() as root:
  path=module.provision(root,42,{'login':'123','server':'Demo','password':'never-write'})
  assert os.path.isdir(path)
  assert 'password' not in open(os.path.join(path,'account.json')).read()
