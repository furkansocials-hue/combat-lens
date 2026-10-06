"""--demo: made-up fight data, only to preview the window. Never mixed with real captures."""
import random
import threading
import time

PARTY = [
    # name, entity, class, skills (real skill codes, so names and icons are the game's)
    ("Aelric", 5101, "GL", [11010000, 11020000, 11030000, 11040000, 11050000, 11060000, 11080000]),
    ("Mirae", 5102, "CL", [17010000, 17020000, 17030000, 17040000, 17060000]),
    ("Tharos", 5103, "SO", [15010000, 15020000, 15030000, 15040000, 15050000, 15060000]),
    ("Velka", 5104, "RA", [14010000, 14020000, 14030000, 14040000, 14050000, 14060000]),
]
BOSS_ENTITY, BOSS_CODE = 9001, 2090175  # Fediv Wraith


class DemoDispatcher:
    """Stands in for the capture dispatcher in --demo."""

    def __init__(self, store):
        self.store = store
        self.running = True

    def status(self):
        return {"locked": True, "flow": "demo", "packets": 0, "game_bytes": 0, "dropped": 0,
                "candidates": 1, "silent_ms": 0}

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def _run(self):
        st = self.store
        rng = random.Random(7)
        with st.lock:
            st.now = int(time.time() * 1000)
            for name, eid, job, _ in PARTY:
                st.append_nickname_authoritative(eid, name)
            st.set_local_identity(PARTY[0][1], PARTY[0][0])
            st.set_party_roster([(n, {"job": j, "level": 45, "combat_power": 0}) for n, _, j, _ in PARTY],
                                True, 0)
            st.append_mob(BOSS_ENTITY, BOSS_CODE)
            st.append_mob_hp(BOSS_ENTITY, 30_000_000)  # so the boss card has an HP bar to show
            st.bosses.add(BOSS_ENTITY)
        power = {5101: 1.25, 5102: 0.55, 5103: 1.1, 5104: 0.95}
        while self.running:
            time.sleep(0.15)
            with st.lock:
                st.now = int(time.time() * 1000)
                name, eid, job, skills = rng.choice(PARTY)
                skill = rng.choice(skills[:3] * 3 + skills)
                base = 9000 + 4000 * (skills.index(skill) % 4)
                dmg = int(base * power[eid] * rng.uniform(0.7, 1.3))
                crit = rng.random() < 0.35
                if crit:
                    dmg = int(dmg * 1.8)
                specials = (["crit"] if crit else []) + (["back"] if rng.random() < 0.25 else [])
                st.append_damage(actor=eid, target=BOSS_ENTITY, skill=skill + 10, damage=dmg,
                                 specials=specials)
