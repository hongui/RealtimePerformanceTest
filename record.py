# coding=utf-8
import subprocess
import time
import re
from threading import Thread
import csv
from datetime import datetime

S_UNIT=1_000_000_000
PACKAGE='com.hongui.test'

class Record:
    def __init__(self,file,cmd):
        self.file=file
        self.cmd=cmd

    def write_title(self):
        origin=self.title()
        header=('Timestamp',*origin,'Camera status','ScreenSharing status','Foreground status','Display status')
        self.write([header],'w')

    def execute(self):
        records=self.fetch()
        if records:
            self.write(records)

    def write(self, rows,mode='a'):
        with open(self.file, mode=mode, newline='') as file:
            writer = csv.writer(file)
            writer.writerows(rows)

    def fetch(self):
        lines = self.adb()
        result=self.compose(lines)
        camera=self.device_status('CameraService')
        screen=self.device_status('CaptureService')
        display=self.display_status()
        foreground=self.foreground_status()
        return ([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),*line,camera,screen,foreground,display] for line in result)
        
    def compose(self,lines):
        for line in lines:
            c=self.convert(line)
            if c:
                yield c

    def title(self):
        return []

    def adb(self,cmd=None):
        result = subprocess.run((cmd if cmd else self.cmd).split(), capture_output=True, text=True,encoding='utf-8')
        result=result.stdout.strip()
        return result.splitlines()

    def convert(self,line):
        return [line]

    def can_be_continue(self):
        lines=self.adb('adb shell dumpsys activity -p "{}" r'.format(PACKAGE))
        for l in lines:
            if "Activities" in l and PACKAGE in l:
                return True
        return False

    def device_status(self,device):
        try:
            lines=self.adb('adb shell dumpsys activity -p "{}" service {}/.{}'.format(PACKAGE,PACKAGE,device))
            return lines[0].startswith('SERVICE')
        except:
            return False

    def display_status(self):
        lines=self.adb('adb shell dumpsys power')
        for l in lines:
            if "Display Power" in l:
                return "ON" in l
        return False
    
    def foreground_status(self):
        lines=self.adb('adb shell dumpsys window d')
        for l in lines:
            if 'mFocusedApp' in l:
                return PACKAGE in l
        return False

class MemoryRecord(Record):

    def __init__(self,file):
        super().__init__(file,'adb shell dumpsys meminfo {}'.format(PACKAGE))

    def title(self):
        return ["Memory Total (MB)"]

    def convert(self,line):
        if "TOTAL" in line:
            contents=line.split()
            try:
                memory_total = int(contents[1]) / 1024  # 转换为MB
                return [memory_total]
            except (ValueError):
                return None
        return None

class CPURecord(Record):
    
    def __init__(self,file):
        super().__init__(file,'adb shell top -n 1 | grep {}'.format(PACKAGE))

    def title(self):
        return ["CPU Usage (%)"]

    def convert(self,line):
        parts = line.split()
        try:
            cpu_usage = float(parts[8].replace('%', ''))  # CPU占用率
            return [cpu_usage]
        except (ValueError, IndexError):
            return None

class BatteryRecord(Record):

    def __init__(self,file):
        super().__init__(file,'adb shell dumpsys battery')

    def title(self):
        return ["Battery Level (%)"]

    def convert(self,line):
        if "level" in line:
            battery_level = int(line.split(':')[1].strip())
            return [battery_level]
        return None

class FPSRecord(Record):

    def __init__(self,file):
        super().__init__(file,'')
        self.pat=r'Frame reports\((.+)\)\:Frames received = (\d+),Frames lost = (\d+),Frame render = (\d+)'

    def title(self):
        return ["User","Received fps","Render fps"]

    def execute(self):
        self.format_cmd()
        return super().execute()

    def convert(self,line):
        match=re.search(self.pat,line)
        if match:
            return (match.group(1),match.group(2),match.group(4))
        return None

    def format_cmd(self):
        self.cmd='adb logcat -T {} -d tag:V *:S'.format(time.time())
        print(self.cmd)

class NetworkRecord(Record):

    def __init__(self,file):
        super().__init__(file,'')

    def title(self):
        return ["User","Media","Bitrate","PackagesLost","PackagesLostFraction","QualityLimitationReason"]

    def execute(self):
        self.format_cmd()
        return super().execute()

    def convert(self,line):
        base=line.split(':')
        if 4==len(base):
            content=base[2].strip()
        else:
            content=""
        if not content.endswith('Stats'):
            return None
        contents=base[3].split(',')
        if len(contents)>=4:
            target=contents[0].split('=')
            if len==5:
                reason=contents[4].split('=')[1].strip()
            else:
                reason='None'
            return (target[0].strip(),target[1].strip(),contents[1].split('=')[1].strip(),contents[2].split('=')[1].strip(),contents[3].split('=')[1].strip(),reason)
        return None

    def format_cmd(self):
        self.cmd='adb logcat -T {} -d Stats:V *:S'.format(time.time())

class TemperatureRecord(Record):

    def __init__(self,file):
        zones=self.adb("adb shell ls /sys/class/thermal/")
        zones=[temp for temp in zones if temp.startswith("thermal_zone")]
        temps_types=["cat /sys/class/thermal/{}/type".format(temp) for temp in zones]
        temps_values=["cat /sys/class/thermal/{}/temp".format(temp) for temp in zones]
        types=';'.join(temps_types)
        values=';'.join(temps_values)
        cmd_types="adb shell {}".format(types)
        cmd_value="adb shell {}".format(values)

        super().__init__(file,cmd_value)
        self.cmd_title=cmd_types
        self.zones=zones

    def title(self):
        types=self.adb(self.cmd_title)
        return [f"{zone} ({t})" for zone,t in zip(self.zones,types)]
    
    def compose(self,lines):
        yield (int(temp) / 1000 for temp in lines)

def run(record):
    while record.can_be_continue():
        before=time.time_ns()
        record.execute()
        usage=time.time_ns()-before
        if usage>=S_UNIT:
            continue
        else:
            time.sleep(1-usage/S_UNIT)

def main():
    records=[MemoryRecord("memory_stats.csv"),CPURecord('cpu_stats.csv'),FPSRecord('fps_stats.csv'),NetworkRecord('network_stats.csv'),BatteryRecord('battery_stats.csv'),TemperatureRecord('temperature_stats.csv')]

    #init 
    for record in records:
        record.write_title()

    threads=[]
    for record in records:
        thread=Thread(target=run,args=(record,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

if __name__ == "__main__":
    main()
