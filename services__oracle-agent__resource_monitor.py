"""Host resource sampling and conservative per-agent MT5 capacity estimate."""
import os,shutil

class ResourceMonitor:
    def sample(self):
        cpu_count=os.cpu_count() or 1
        result={"cpu_count":cpu_count,"disk_free_bytes":shutil.disk_usage("/").free}
        try:
            import psutil
            memory=psutil.virtual_memory()
            result.update({"cpu_percent":float(psutil.cpu_percent(interval=None)),
                "memory_total_bytes":int(memory.total),"memory_available_bytes":int(memory.available),
                "memory_percent":float(memory.percent),"process_count":len(psutil.pids())})
            available_terminals=max(1,int(memory.available/(1536*1024**2)))
            cpu_terminals=max(1,cpu_count*4)
            result["recommended_capacity"]=min(1000,available_terminals,cpu_terminals)
        except ImportError:
            try:result["load_average"]=[float(x) for x in os.getloadavg()]
            except (AttributeError,OSError):result["load_average"]=[]
            result["recommended_capacity"]=max(1,min(1000,cpu_count*2))
        return result
    def cpu_count(self):return os.cpu_count() or 1
    def account_capacity(self,configured_limit):return max(1,int(configured_limit))
