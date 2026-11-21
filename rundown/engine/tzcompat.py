"""US Eastern time that works everywhere.

Uses the system time-zone database when it exists. Windows Python has none unless the optional `tzdata`
package is installed, so this falls back to the US daylight-saving rules (second Sunday in March to the
first Sunday in November, 2:00 a.m. local), which is all The Rundown needs.
"""
from datetime import datetime, timedelta, tzinfo


class USEastern(tzinfo):
    @staticmethod
    def _bounds(year):
        mar8, nov1 = datetime(year, 3, 8), datetime(year, 11, 1)
        start = mar8 + timedelta(days=(6 - mar8.weekday()) % 7)   # second Sunday in March
        end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)     # first Sunday in November
        return start.replace(hour=2), end.replace(hour=2)

    def dst(self, dt):
        if dt is None:
            return timedelta(0)
        start, end = self._bounds(dt.year)
        local = dt.replace(tzinfo=None)
        if getattr(dt, 'fold', 0) and end - timedelta(hours=1) <= local < end:
            return timedelta(0)                                   # the repeated hour, second time round (EST)
        return timedelta(hours=1) if start <= local < end else timedelta(0)

    def utcoffset(self, dt):
        return timedelta(hours=-5) + self.dst(dt)

    def tzname(self, dt):
        return 'EDT' if self.dst(dt) else 'EST'

    def fromutc(self, dt):
        utc = dt.replace(tzinfo=None)
        start, end = self._bounds(utc.year)
        in_dst = start + timedelta(hours=5) <= utc < end + timedelta(hours=4)   # 07:00 UTC in, 06:00 UTC out
        local = utc - timedelta(hours=4 if in_dst else 5)
        fold = int(not in_dst and end - timedelta(hours=1) <= local < end)
        return local.replace(tzinfo=self, fold=fold)


try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo('America/New_York')
except Exception:          # no time-zone database (common on Windows)
    ET = USEastern()
