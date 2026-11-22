"""Quiz "Adivina el imperio" sobre fronteras historicas (aourednik/historical-basemaps, aproximadas).

`select` elige los rasgos del mapa; `note` es la fecha que se imprime en el mapa (la pista principal).
Pistas de la mas dificil a la mas facil (<= 35 caracteres). `verified` sigue en False hasta pasar la verificacion de hechos.
"""

def _e(label, map_year, select, note, clues, **kw):
    return dict(country=label, map_year=map_year, select=select, note=note, clues=clues, verified=False,
                labels=True, max_km=99999, near_deg=75, caption=None, **kw)


EMPIRE_DEMO = [
    _e("Roman Empire", 100, {"NAME": ["Roman Empire"]}, "c. 100 A.D.", [
        "Called the Mediterranean 'Our Sea'",
        "Hadrian built a wall in Britain",
        "Capital: Rome"]),
    _e("Ottoman Empire", 1600, {"NAME": ["Ottoman Empire"]}, "1600 A.D.", [
        "Janissaries were its elite troops",
        "Conquered Constantinople in 1453",
        "Capital: Istanbul"]),
    _e("Mongol Empire", 1279, {"SUBJECTO": ["Mongol Empire"]}, "1279 A.D.", [
        "Largest contiguous land empire ever",
        "Founded by Genghis Khan in 1206",
        "Kublai Khan was its Great Khan"]),
    _e("Inca Empire", 1530, {"NAME": ["Inca Empire"]}, "1530 A.D.", [
        "Recorded data on knotted cords",
        "Built Machu Picchu in the Andes",
        "Capital: Cusco"]),
    _e("Achaemenid Empire", "bc500", {"NAME": ["Achaemenid Empire"]}, "c. 500 B.C.", [
        "Its Royal Road ran 2,500 km",
        "Founded by Cyrus the Great",
        "The first Persian Empire"]),
]
for i, q in enumerate(EMPIRE_DEMO):
    q["caption"] = f"Fig. {i + 1}.  The world, {q['note']}  Borders approximate."
