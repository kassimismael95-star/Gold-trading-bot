import importlib.util
spec=importlib.util.spec_from_file_location("resource_monitor","services/oracle-agent/resource_monitor.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_resource_monitor_returns_bounded_capacity_and_safe_metrics():
    result=module.ResourceMonitor().sample()
    assert result["cpu_count"]>=1
    assert 1<=result["recommended_capacity"]<=1000
    assert result["disk_free_bytes"]>=0
