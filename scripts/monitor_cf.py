# IronPython 2.7 - appended to build/renode-cf/scripts/monitor.py at launch.
# Exposes monitor commands: cpu_stats, cpu_stats_reset

from Antmicro.Renode.Core import EmulationManager
import time

_last_ins = None
_last_virt = None
_last_wall = None


def mc_cpu_stats():
    global _last_ins, _last_virt, _last_wall

    machine = self.Machine
    if machine is None:
        print "error=no machine selected (run: mach set CF2.1)"
        return

    cpu = machine["sysbus.cpu"]
    ins = long(cpu.ExecutedInstructions)
    mips_cap = int(cpu.PerformanceInMips)
    pc = long(cpu.PC.RawValue)

    master = EmulationManager.Instance.CurrentEmulation.MasterTimeSource
    virt_s = master.ElapsedVirtualTime.TotalSeconds
    host_s = master.ElapsedHostTime.TotalSeconds

    wall = time.time()
    rate = 0.0
    util = 0.0
    sim_speed = 0.0

    if _last_wall is not None:
        dt = wall - _last_wall
        if dt > 0:
            if _last_ins is not None and ins >= _last_ins:
                rate = (ins - _last_ins) / dt
            if _last_virt is not None:
                sim_speed = (virt_s - _last_virt) / dt
                if rate <= 0 and mips_cap > 0:
                    rate = sim_speed * mips_cap * 1000000.0
            if mips_cap > 0 and rate > 0:
                util = min(100.0, 100.0 * rate / (mips_cap * 1000000.0))

    print (
        "ins=%d rate=%.0f util=%.1f%% mips_cap=%d sim_speed=%.3fx "
        "pc=0x%x virt=%.6fs host=%.6fs"
    ) % (ins, rate, util, mips_cap, sim_speed, pc, virt_s, host_s)

    _last_ins = ins
    _last_virt = virt_s
    _last_wall = wall


def mc_cpu_stats_reset():
    global _last_ins, _last_virt, _last_wall
    _last_ins = None
    _last_virt = None
    _last_wall = None
    print "cpu_stats baseline reset"
