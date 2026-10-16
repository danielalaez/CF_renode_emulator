# IronPython 2.7 - appended to build/renode-cf/scripts/monitor.py at launch.
# Exposes: cpu_stats, imu_tick, imu_burst, imu_stream_start/stop/status, baro_tick
#
# IMU stream uses Machine.ClockSource (emulation thread), NOT System.Threading.
# A host thread calling Feed*/TriggerDataInterrupt races Renode and can CPU-abort.

from Antmicro.Renode.Core import EmulationManager
from Antmicro.Renode.Time import ClockEntry
from System import Action
import time

_last_ins = None
_last_virt = None
_last_wall = None

# Clock-driven IMU feeder state
_stream_handler = None
_stream_machine = None
_stream_n = 0
_stream_hz = 0.0
_stream_t0 = 0.0
_stream_virt0 = 0.0


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


def _require_machine():
    machine = self.Machine
    if machine is None:
        print "error=no machine selected (run: mach set \"CF2.1\")"
        return None
    return machine


def _virt_seconds():
    master = EmulationManager.Instance.CurrentEmulation.MasterTimeSource
    return master.ElapsedVirtualTime.TotalSeconds


def _imu_feed_one(machine, gx, gy, gz, ax, ay, az):
    gyro = machine["sysbus.i2c3.bmi_gyro"]
    accel = machine["sysbus.i2c3.bmi_accel"]
    gyro.FeedGyroSample(float(gx), float(gy), float(gz), 1)
    accel.FeedAccSample(float(ax), float(ay), float(az), 1)
    gyro.TriggerDataInterrupt()


def mc_imu_tick(gx, gy, gz, ax, ay, az):
    """Feed one gyro+accel sample and pulse gyro DRDY (Int3)."""
    machine = _require_machine()
    if machine is None:
        return
    paused = machine.ObtainPausedState()
    try:
        _imu_feed_one(machine, gx, gy, gz, ax, ay, az)
    finally:
        paused.Dispose()


def mc_imu_burst(n, gx, gy, gz, ax, ay, az):
    """Feed N identical IMU samples + DRDY in one monitor round-trip."""
    machine = _require_machine()
    if machine is None:
        return
    count = int(n)
    if count < 1:
        print "error=n must be >= 1"
        return
    if count > 5000:
        count = 5000
    paused = machine.ObtainPausedState()
    try:
        i = 0
        while i < count:
            _imu_feed_one(machine, gx, gy, gz, ax, ay, az)
            i += 1
    finally:
        paused.Dispose()
    print "fed=%d" % count


def mc_baro_tick(pressure_pa, temp_c):
    """Feed one barometer pressure/temperature sample."""
    machine = _require_machine()
    if machine is None:
        return
    paused = machine.ObtainPausedState()
    try:
        baro = machine["sysbus.i2c3.bmp_baro"]
        baro.FeedPTSample(float(pressure_pa), float(temp_c), 1)
    finally:
        paused.Dispose()


def mc_imu_hover_tick():
    """One rest/hover sample: gyro ~0, accel ~1g on Z, then DRDY."""
    mc_imu_tick(0, 0, 0, 0, 0, 1000)


def _imu_stream_stop_internal():
    global _stream_handler, _stream_machine
    handler = _stream_handler
    machine = _stream_machine
    _stream_handler = None
    _stream_machine = None
    if handler is None or machine is None:
        return False
    try:
        paused = machine.ObtainPausedState()
        try:
            machine.ClockSource.RemoveClockEntry(handler)
        finally:
            paused.Dispose()
    except Exception:
        pass
    return True


def mc_imu_stream_stop():
    """Stop clock-driven IMU feeder."""
    _imu_stream_stop_internal()
    print "stream=stopped n=%d" % _stream_n


def mc_imu_stream_start(hz, gx, gy, gz, ax, ay, az, baro_hz=0, pressure=101325, temp=25):
    """Start IMU feeder on Machine.ClockSource at hz (virtual-time rate)."""
    global _stream_handler, _stream_machine, _stream_n, _stream_hz, _stream_t0, _stream_virt0
    machine = _require_machine()
    if machine is None:
        return
    rate = float(hz)
    if rate <= 0:
        print "error=hz must be > 0"
        return
    if rate > 2000:
        rate = 2000.0

    _imu_stream_stop_internal()

    gyro = machine["sysbus.i2c3.bmi_gyro"]
    accel = machine["sysbus.i2c3.bmi_accel"]
    baro = None
    baro_every = 0
    if float(baro_hz) > 0:
        baro_every = max(1, int(round(rate / float(baro_hz))))
        baro = machine["sysbus.i2c3.bmp_baro"]

    gx_f = float(gx)
    gy_f = float(gy)
    gz_f = float(gz)
    ax_f = float(ax)
    ay_f = float(ay)
    az_f = float(az)
    pressure_f = float(pressure)
    temp_f = float(temp)

    def on_tick():
        global _stream_n
        try:
            gyro.FeedGyroSample(gx_f, gy_f, gz_f, 1)
            accel.FeedAccSample(ax_f, ay_f, az_f, 1)
            gyro.TriggerDataInterrupt()
            n = _stream_n
            if baro is not None and baro_every > 0 and (n % baro_every) == 0:
                baro.FeedPTSample(pressure_f, temp_f, 1)
            _stream_n = n + 1
        except Exception:
            pass

    handler = Action(on_tick)
    # period=1 tick at `rate` Hz virtual time (same pattern as SimpleTicker)
    ratio = ClockEntry.FrequencyToRatio(gyro, long(rate))
    entry = ClockEntry(1, ratio, handler, gyro, "imu_stream")

    paused = machine.ObtainPausedState()
    try:
        machine.ClockSource.AddClockEntry(entry)
    finally:
        paused.Dispose()

    _stream_handler = handler
    _stream_machine = machine
    _stream_n = 0
    _stream_hz = rate
    _stream_t0 = time.time()
    _stream_virt0 = _virt_seconds()
    print "stream=started hz=%.1f baro_hz=%.1f mode=clock" % (rate, float(baro_hz))


def mc_imu_stream_status():
    """Print clock-driven feeder progress (wall + virtual rates)."""
    running = 0
    if _stream_handler is not None:
        running = 1
    elapsed = time.time() - _stream_t0 if _stream_t0 > 0 else 0.0
    out_hz = (_stream_n / elapsed) if elapsed > 0.05 else 0.0
    virt_elapsed = _virt_seconds() - _stream_virt0 if _stream_t0 > 0 else 0.0
    virt_hz = (_stream_n / virt_elapsed) if virt_elapsed > 0.05 else 0.0
    print (
        "streaming=%d n=%d target_hz=%.1f out_hz=%.1f virt_hz=%.1f "
        "elapsed=%.2f virt=%.2f"
    ) % (running, _stream_n, _stream_hz, out_hz, virt_hz, elapsed, virt_elapsed)


# ELF symbols (cf2.elf / sensors_bmi088_bmp3xx.c) - refresh if firmware rebuild moves BSS.
_GYRO_BIAS_FOUND_ADDR = 0x200060F8
_GYRO_BIAS_RUNNING_ADDR = 0x10002DD0  # CCM BiasObj
_BIAS_IS_FOUND_OFF = 36
_BIAS_IS_FILLED_OFF = 37


def mc_calib_status():
    """Read gyroBiasFound / BiasObj flags from guest RAM (past sensor calib?)."""
    machine = _require_machine()
    if machine is None:
        return
    bus = machine.SystemBus
    bias_found = int(bus.ReadByte(_GYRO_BIAS_FOUND_ADDR))
    # Second byte is the other sensors_*.c copy if linked; BMI088 uses first.
    bias_found_b = int(bus.ReadByte(_GYRO_BIAS_FOUND_ADDR + 1))
    is_found = int(bus.ReadByte(_GYRO_BIAS_RUNNING_ADDR + _BIAS_IS_FOUND_OFF))
    is_filled = int(bus.ReadByte(_GYRO_BIAS_RUNNING_ADDR + _BIAS_IS_FILLED_OFF))
    pc = long(machine["sysbus.cpu"].PC.RawValue)
    calibrated = 1 if (bias_found != 0 or is_found != 0) else 0
    print (
        "calibrated=%d gyroBiasFound=%d/%d isBiasValueFound=%d "
        "isBufferFilled=%d pc=0x%x"
    ) % (calibrated, bias_found, bias_found_b, is_found, is_filled, pc)


# supervisorMem @ 0x2000baa0 (cf2.elf DWARF). state is uint8 enum.
_SUPERVISOR_MEM_ADDR = 0x2000BAA0
_SUP_OFF_CAN_FLY = 0
_SUP_OFF_IS_FLYING = 1
_SUP_OFF_IS_TUMBLED = 2
_SUP_OFF_IS_ARMED = 3
_SUP_OFF_IS_CRASHED = 4
_SUP_OFF_INFO = 6
_SUP_OFF_STATE = 40
_SUP_OFF_CONDITIONS = 44

_SUP_STATE_NAMES = {
    0: "NotInitialized",
    1: "PreFlChecksNotPassed",
    2: "PreFlChecksPassed",
    3: "Arming",
    4: "ReadyToFly",
    5: "Flying",
    6: "Landed",
    7: "Reset",
    8: "WarningLevelOut",
    9: "ExceptFreeFall",
    10: "Locked",
    11: "Crashed",
}


def mc_preflight_status():
    """Read supervisorMem: preflight / arm / canFly (past pre-flight checks?)."""
    machine = _require_machine()
    if machine is None:
        return
    bus = machine.SystemBus
    base = _SUPERVISOR_MEM_ADDR
    can_fly = int(bus.ReadByte(base + _SUP_OFF_CAN_FLY))
    is_flying = int(bus.ReadByte(base + _SUP_OFF_IS_FLYING))
    is_tumbled = int(bus.ReadByte(base + _SUP_OFF_IS_TUMBLED))
    is_armed = int(bus.ReadByte(base + _SUP_OFF_IS_ARMED))
    is_crashed = int(bus.ReadByte(base + _SUP_OFF_IS_CRASHED))
    info = int(bus.ReadWord(base + _SUP_OFF_INFO))
    state = int(bus.ReadByte(base + _SUP_OFF_STATE))
    cond = long(bus.ReadDoubleWord(base + _SUP_OFF_CONDITIONS))
    name = _SUP_STATE_NAMES.get(state, "Unknown")
    # Past the PreFlChecksNotPassed gate (includes Arming / ReadyToFly / ...)
    preflight_ok = 1 if state in (2, 3, 4, 5, 6, 8) else 0
    tumbled_c = 1 if (cond & (1 << 2)) else 0
    deck_c = 1 if (cond & (1 << 9)) else 0
    print (
        "preflight_ok=%d state=%d(%s) canFly=%d isArmed=%d isFlying=%d "
        "isTumbled=%d isCrashed=%d info=0x%x cond=0x%x tumbled_c=%d deck_c=%d"
    ) % (
        preflight_ok, state, name, can_fly, is_armed, is_flying,
        is_tumbled, is_crashed, info, cond, tumbled_c, deck_c,
    )
