"""Zonas de liquidez (pivotes con grosor ATR) con ruptura y retest SIMETRICOS (arriba y abajo)."""


class ZoneTracker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.zones = []

    def step(self, i, h, l, c, atr, ph, pl):
        """Avanza una vela. Devuelve eventos de retest: [(side, bot, top)]."""
        cfg = self.cfg
        events = []
        if atr:
            pad = max(atr * cfg.ZONE_ATR_MULT, 1e-12)
            if ph is not None:
                self._add({"hi": True, "top": ph, "bot": ph - pad, "broken": False, "bb": None, "retested": False})
            if pl is not None:
                self._add({"hi": False, "top": pl + pad, "bot": pl, "broken": False, "bb": None, "retested": False})
        for z in self.zones:
            if not z["broken"]:
                if (z["hi"] and c[i] > z["top"]) or (not z["hi"] and c[i] < z["bot"]):
                    z["broken"], z["bb"] = True, i
                continue
            if z["retested"] or i <= z["bb"]:
                continue
            if i - z["bb"] > cfg.ZONE_RETEST_EXPIRY:
                z["retested"] = True   # caducada
                continue
            if z["hi"] and l[i] <= z["top"] and h[i] >= z["bot"] and c[i] >= z["top"]:
                z["retested"] = True
                events.append(("LONG", z["bot"], z["top"]))
            elif (not z["hi"]) and h[i] >= z["bot"] and l[i] <= z["top"] and c[i] <= z["bot"]:
                z["retested"] = True
                events.append(("SHORT", z["bot"], z["top"]))
        return events

    def _add(self, z):
        if len(self.zones) >= self.cfg.ZONE_MAX:
            self.zones.pop(0)
        self.zones.append(z)

    def snapshot(self):
        return tuple((z["hi"], z["bot"], z["top"], z["broken"]) for z in self.zones)
